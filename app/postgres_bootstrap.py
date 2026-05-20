"""PostgreSQL startup helpers.

These helpers are intentionally conservative:
- The target PostgreSQL database is created only if it does not exist.
- Tables are created only if they do not exist.
- Performance indexes are created with CREATE INDEX IF NOT EXISTS.
- No existing data is deleted or modified by these startup helpers.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url, URL
from sqlalchemy.exc import OperationalError, SQLAlchemyError




SCHEMA_COMPATIBILITY_SQL = [
    # SQLite accepted longer parameter names than the original VARCHAR(64).
    # PostgreSQL enforces the limit, so widen these columns without deleting data.
    "ALTER TABLE report_parameters ALTER COLUMN name TYPE VARCHAR(255)",
    "ALTER TABLE report_parameters ALTER COLUMN range_value TYPE TEXT",
    "ALTER TABLE parameter_ranges ALTER COLUMN parameter_name TYPE VARCHAR(255)",
    "ALTER TABLE parameter_ranges ALTER COLUMN range_value TYPE TEXT",
]

PERFORMANCE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_reports_user_id ON reports (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_reports_department_id ON reports (department_id)",
    "CREATE INDEX IF NOT EXISTS ix_reports_equipment_id ON reports (equipment_id)",
    "CREATE INDEX IF NOT EXISTS ix_reports_sampling_time ON reports (sampling_time)",
    "CREATE INDEX IF NOT EXISTS ix_reports_department_sampling_time ON reports (department_id, sampling_time)",
    "CREATE INDEX IF NOT EXISTS ix_report_sections_report_id ON report_sections (report_id)",
    "CREATE INDEX IF NOT EXISTS ix_report_parameters_section_id ON report_parameters (section_id)",
    "CREATE INDEX IF NOT EXISTS ix_equipments_department_id ON equipments (department_id)",
    "CREATE INDEX IF NOT EXISTS ix_user_departments_department_id ON user_departments (department_id)",
]


def _is_postgres_url(database_uri: Optional[str]) -> bool:
    if not database_uri:
        return False
    try:
        return make_url(database_uri).drivername.startswith("postgresql")
    except Exception:
        return False


def _quote_identifier(identifier: str) -> str:
    """Safely quote a PostgreSQL identifier such as a database or role name."""
    if not identifier or not str(identifier).strip():
        raise ValueError("PostgreSQL identifier cannot be empty.")
    return '"' + str(identifier).replace('"', '""') + '"'


def _database_exists(connection, database_name: str) -> bool:
    result = connection.execute(
        text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
        {"database_name": database_name},
    )
    return result.scalar() is not None


def ensure_postgres_database(app) -> None:
    """Create the configured PostgreSQL database if it does not already exist.

    This connects to the maintenance database, which is configured as
    POSTGRES_MAINTENANCE_DATABASE_URI. The default maintenance DB is postgres.
    """
    database_uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    if not _is_postgres_url(database_uri):
        return

    if not app.config.get("AUTO_CREATE_POSTGRES_DATABASE", True):
        return

    target_url: URL = make_url(database_uri)
    target_database = target_url.database
    if not target_database:
        raise RuntimeError("PostgreSQL target database name is missing from SQLALCHEMY_DATABASE_URI.")

    maintenance_uri = app.config.get("POSTGRES_MAINTENANCE_DATABASE_URI")
    if not maintenance_uri:
        maintenance_database = app.config.get("POSTGRES_MAINTENANCE_DATABASE", "postgres")
        maintenance_uri = str(target_url.set(database=maintenance_database))

    maintenance_engine = create_engine(
        maintenance_uri,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )

    try:
        with maintenance_engine.connect() as connection:
            if _database_exists(connection, target_database):
                app.logger.info("PostgreSQL database already exists: %s", target_database)
                return

            owner = target_url.username
            create_sql = f"CREATE DATABASE {_quote_identifier(target_database)}"
            if owner:
                create_sql += f" OWNER {_quote_identifier(owner)}"
            create_sql += " ENCODING 'UTF8' TEMPLATE template1"

            connection.execute(text(create_sql))
            app.logger.info("Created PostgreSQL database: %s", target_database)
    except OperationalError as exc:
        raise RuntimeError(
            "Could not connect to PostgreSQL maintenance database. "
            "Check server IP, port, username, password, firewall, and pg_hba.conf."
        ) from exc
    finally:
        maintenance_engine.dispose()



def ensure_schema_compatibility(app, db) -> None:
    """Apply small non-destructive PostgreSQL schema compatibility fixes.

    db.create_all() does not alter existing columns. This function widens
    columns that were too small for existing SQLite data. It is safe to run
    repeatedly and does not delete or rewrite application rows.
    """
    database_uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    if not _is_postgres_url(database_uri):
        return

    if not app.config.get("AUTO_FIX_POSTGRES_SCHEMA", True):
        return

    inspector = inspect(db.engine)
    table_names = set(inspector.get_table_names())
    if "report_parameters" not in table_names:
        return

    with db.engine.begin() as connection:
        for statement in SCHEMA_COMPATIBILITY_SQL:
            connection.execute(text(statement))

    app.logger.info("PostgreSQL schema compatibility checked/applied.")

def ensure_performance_indexes(app, db) -> None:
    """Create known performance indexes if they are missing."""
    if not app.config.get("AUTO_CREATE_PERFORMANCE_INDEXES", True):
        return

    inspector = inspect(db.engine)
    table_names = set(inspector.get_table_names())
    required_tables = {
        "reports",
        "report_sections",
        "report_parameters",
        "equipments",
        "user_departments",
    }
    if not required_tables.issubset(table_names):
        missing = sorted(required_tables - table_names)
        app.logger.info("Skipping performance indexes because tables are missing: %s", missing)
        return

    with db.engine.begin() as connection:
        for statement in PERFORMANCE_INDEX_SQL:
            connection.execute(text(statement))

    app.logger.info("PostgreSQL performance indexes checked/created.")


def ensure_alembic_version_stamp(app, db) -> None:
    """Create/stamp alembic_version only when it is missing or empty.

    This prevents Flask-Migrate from trying to replay old migrations on a
    PostgreSQL schema that was already created from the current models.
    Existing alembic_version values are left untouched.
    """
    if not app.config.get("AUTO_STAMP_ALEMBIC_VERSION", True):
        return

    revision = app.config.get("ALEMBIC_STAMP_REVISION")
    if not revision:
        return

    with db.engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        existing = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
        if existing:
            app.logger.info("Alembic version already stamped: %s", existing)
            return

        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": revision},
        )
        app.logger.info("Alembic version stamped: %s", revision)


def create_missing_tables(app, db) -> None:
    """Create missing application tables and indexes.

    db.create_all() is non-destructive. It creates missing tables, but does not
    drop or rewrite existing tables/data.
    """
    if not app.config.get("AUTO_CREATE_TABLES", True):
        return

    try:
        with app.app_context():
            db.create_all()
            ensure_schema_compatibility(app, db)
            ensure_performance_indexes(app, db)
            ensure_alembic_version_stamp(app, db)
            app.logger.info("Database tables checked/created.")
    except SQLAlchemyError as exc:
        raise RuntimeError("Could not create/check database tables.") from exc
