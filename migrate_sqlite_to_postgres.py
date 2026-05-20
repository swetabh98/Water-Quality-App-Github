r"""One-time SQLite -> PostgreSQL data migration for the Water Quality app.

Usage from the project root, after copying the PostgreSQL code files:

    python migrate_sqlite_to_postgres.py

Optional:

    python migrate_sqlite_to_postgres.py --sqlite instance\database.db
    python migrate_sqlite_to_postgres.py --force

What this script does:
- Connects to PostgreSQL using config.py.
- Creates the PostgreSQL database/tables if they do not exist.
- Copies valid SQLite rows into PostgreSQL while preserving IDs.
- Resets PostgreSQL sequences so new records continue after the copied IDs.
- Does not delete PostgreSQL data unless --force is used.

Rows that violate PostgreSQL foreign keys, such as orphaned report sections or
orphaned report parameters, are skipped because PostgreSQL correctly enforces
referential integrity.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from flask import Flask
from sqlalchemy import inspect, text

from config import Config
from app.models import db
from app.postgres_bootstrap import (
    create_missing_tables,
    ensure_postgres_database,
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SQLITE_PATH = BASE_DIR / "instance" / "database.db"

TABLE_COPY_ORDER = [
    "departments",
    "equipments",
    "users",
    "user_departments",
    "parameter_ranges",
    "reports",
    "report_sections",
    "report_parameters",
]

TABLES_WITH_SEQUENCES = [
    "departments",
    "equipments",
    "users",
    "parameter_ranges",
    "reports",
    "report_sections",
    "report_parameters",
]

TRUNCATE_ORDER = [
    "report_parameters",
    "report_sections",
    "reports",
    "user_departments",
    "equipments",
    "parameter_ranges",
    "users",
    "departments",
]

VALID_REPORT_SUBQUERY = """
    SELECT r.id
    FROM reports r
    LEFT JOIN users u ON u.id = r.user_id
    LEFT JOIN departments d ON d.id = r.department_id
    LEFT JOIN equipments e ON e.id = r.equipment_id
    WHERE (r.user_id IS NULL OR u.id IS NOT NULL)
      AND (r.department_id IS NULL OR d.id IS NOT NULL)
      AND (r.equipment_id IS NULL OR e.id IS NOT NULL)
"""

VALID_SECTION_SUBQUERY = f"""
    SELECT s.id
    FROM report_sections s
    WHERE s.report_id IS NULL OR s.report_id IN ({VALID_REPORT_SUBQUERY})
"""

COPY_QUERIES: Dict[str, str] = {
    "departments": """
        SELECT id, name
        FROM departments
        ORDER BY id
    """,
    "equipments": """
        SELECT e.id, e.name, e.department_id
        FROM equipments e
        JOIN departments d ON d.id = e.department_id
        ORDER BY e.id
    """,
    "users": """
        SELECT id, email, password, role
        FROM users
        ORDER BY id
    """,
    "user_departments": """
        SELECT ud.user_id, ud.department_id
        FROM user_departments ud
        JOIN users u ON u.id = ud.user_id
        JOIN departments d ON d.id = ud.department_id
        ORDER BY ud.user_id, ud.department_id
    """,
    "parameter_ranges": """
        SELECT id, department_name, sheet_name, parameter_name, range_value
        FROM parameter_ranges
        ORDER BY id
    """,
    "reports": f"""
        SELECT r.id, r.user_id, r.department_id, r.equipment_id, r.sampling_time
        FROM reports r
        WHERE r.id IN ({VALID_REPORT_SUBQUERY})
        ORDER BY r.id
    """,
    "report_sections": f"""
        SELECT s.id, s.report_id, s.sheet_name
        FROM report_sections s
        WHERE s.report_id IS NULL OR s.report_id IN ({VALID_REPORT_SUBQUERY})
        ORDER BY s.id
    """,
    "report_parameters": f"""
        SELECT p.id, p.section_id, p.name, p.value, p.range_value
        FROM report_parameters p
        WHERE p.section_id IS NULL OR p.section_id IN ({VALID_SECTION_SUBQUERY})
        ORDER BY p.id
    """,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate Water Quality SQLite data to PostgreSQL.")
    parser.add_argument(
        "--sqlite",
        default=str(DEFAULT_SQLITE_PATH),
        help="Path to source SQLite database. Default: instance\\database.db",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing PostgreSQL app data before copying. Use only after taking a backup.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=5000,
        help="Rows per insert batch. Default: 5000",
    )
    return parser.parse_args()


def make_minimal_app() -> Flask:
    """Create a minimal Flask app for DB work without importing all routes."""
    app = Flask(__name__)
    app.config.from_object(Config)
    ensure_postgres_database(app)
    db.init_app(app)
    with app.app_context():
        create_missing_tables(app, db)
    return app


def parse_datetime(value):
    if value is None or isinstance(value, datetime):
        return value

    value = str(value).strip()
    if not value:
        return None

    # SQLite usually stores SQLAlchemy DateTime as: YYYY-MM-DD HH:MM:SS.ffffff
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass

    formats = [
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    raise ValueError(f"Could not parse datetime value: {value!r}")


def transform_row(table_name: str, row: sqlite3.Row) -> Dict:
    data = dict(row)
    if table_name == "reports":
        data["sampling_time"] = parse_datetime(data.get("sampling_time"))
    return data


def sqlite_table_exists(sqlite_conn: sqlite3.Connection, table_name: str) -> bool:
    row = sqlite_conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def sqlite_count(sqlite_conn: sqlite3.Connection, table_name: str) -> int:
    if not sqlite_table_exists(sqlite_conn, table_name):
        return 0
    return int(sqlite_conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


def postgres_counts(connection) -> Dict[str, int]:
    counts = {}
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    for table_name in TABLE_COPY_ORDER:
        if table_name not in existing_tables:
            counts[table_name] = 0
            continue
        counts[table_name] = int(connection.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar() or 0)
    return counts


def target_has_data(connection) -> Tuple[bool, Dict[str, int]]:
    counts = postgres_counts(connection)
    return any(count > 0 for count in counts.values()), counts


def truncate_target(connection) -> None:
    joined_tables = ", ".join(TRUNCATE_ORDER)
    connection.execute(text(f"TRUNCATE TABLE {joined_tables} RESTART IDENTITY CASCADE"))


def batched_sqlite_rows(
    sqlite_conn: sqlite3.Connection,
    table_name: str,
    query: str,
    chunk_size: int,
) -> Iterable[List[Dict]]:
    cursor = sqlite_conn.execute(query)
    while True:
        rows = cursor.fetchmany(chunk_size)
        if not rows:
            break
        yield [transform_row(table_name, row) for row in rows]


def copy_table(sqlite_conn, pg_connection, table_name: str, chunk_size: int) -> int:
    if not sqlite_table_exists(sqlite_conn, table_name):
        print(f"  - {table_name}: source table missing, skipped")
        return 0

    target_table = db.metadata.tables[table_name]
    query = COPY_QUERIES[table_name]
    inserted = 0

    for batch in batched_sqlite_rows(sqlite_conn, table_name, query, chunk_size):
        if not batch:
            continue
        pg_connection.execute(target_table.insert(), batch)
        inserted += len(batch)

    source_total = sqlite_count(sqlite_conn, table_name)
    skipped = source_total - inserted
    if skipped > 0:
        print(f"  - {table_name}: inserted {inserted}, skipped {skipped} invalid/orphan rows")
    else:
        print(f"  - {table_name}: inserted {inserted}")
    return inserted


def reset_sequence(connection, table_name: str) -> None:
    sql = text(
        f"""
        SELECT setval(
            pg_get_serial_sequence('{table_name}', 'id'),
            COALESCE((SELECT MAX(id) FROM {table_name}), 1),
            (SELECT MAX(id) IS NOT NULL FROM {table_name})
        )
        """
    )
    connection.execute(sql)


def reset_sequences(connection) -> None:
    for table_name in TABLES_WITH_SEQUENCES:
        reset_sequence(connection, table_name)


def main() -> int:
    args = parse_args()
    sqlite_path = Path(args.sqlite).resolve()

    if not sqlite_path.exists():
        print(f"ERROR: SQLite database was not found: {sqlite_path}")
        return 1

    print("SQLite source:", sqlite_path)
    print("PostgreSQL target:", Config.SQLALCHEMY_DATABASE_URI)

    app = make_minimal_app()

    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row

    try:
        with app.app_context():
            with db.engine.begin() as pg_connection:
                has_data, counts = target_has_data(pg_connection)
                if has_data and not args.force:
                    print("\nERROR: PostgreSQL already has data.")
                    print("Current PostgreSQL row counts:")
                    for table_name, count in counts.items():
                        print(f"  - {table_name}: {count}")
                    print("\nUse --force only if you intentionally want to delete this PostgreSQL app data and copy again.")
                    return 1

                if args.force:
                    print("\n--force used. Truncating PostgreSQL app tables first...")
                    truncate_target(pg_connection)

                print("\nCopying data...")
                for table_name in TABLE_COPY_ORDER:
                    copy_table(sqlite_conn, pg_connection, table_name, args.chunk_size)

                print("\nResetting PostgreSQL ID sequences...")
                reset_sequences(pg_connection)

            with db.engine.connect() as pg_connection:
                counts = postgres_counts(pg_connection)

            print("\nMigration complete. PostgreSQL row counts:")
            for table_name in TABLE_COPY_ORDER:
                print(f"  - {table_name}: {counts.get(table_name, 0)}")

        return 0
    finally:
        sqlite_conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
