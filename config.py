import os
from datetime import timedelta
from urllib.parse import quote_plus


def _as_bool(value, default=False):
    """Read common true/false environment values safely."""
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _quote_url_part(value):
    """Quote username/password/database URL parts for SQLAlchemy URLs."""
    return quote_plus(str(value))


def _build_postgres_uri(database_name):
    """Build a PostgreSQL SQLAlchemy connection URL from environment/config values."""
    host = os.environ.get("POSTGRES_HOST", "172.17.0.20")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "admin1123")

    return (
        "postgresql+psycopg2://"
        f"{_quote_url_part(user)}:{_quote_url_part(password)}"
        f"@{host}:{port}/{_quote_url_part(database_name)}"
    )


class Config:
    # ---------------------------
    # Core / Database
    # ---------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY") or "REPLACE_ME_WITH_A_LONG_RANDOM_SECRET"

    # PostgreSQL target database. This database will be created automatically
    # if it does not exist, using POSTGRES_MAINTENANCE_DATABASE below.
    POSTGRES_DATABASE = os.environ.get("POSTGRES_DATABASE", "water_quality_db")

    # Maintenance database used only to check/create POSTGRES_DATABASE.
    # You specifically asked to use postgres as the maintenance database.
    POSTGRES_MAINTENANCE_DATABASE = os.environ.get("POSTGRES_MAINTENANCE_DATABASE", "postgres")

    # Main app database URL. DATABASE_URL still works as an override, but by
    # default the app now points to PostgreSQL instead of SQLite.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or _build_postgres_uri(POSTGRES_DATABASE)

    # Maintenance connection URL used to create the target database if missing.
    POSTGRES_MAINTENANCE_DATABASE_URI = (
        os.environ.get("POSTGRES_MAINTENANCE_DATABASE_URL")
        or _build_postgres_uri(POSTGRES_MAINTENANCE_DATABASE)
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RESET_DB_PASSWORD = "Swetabh2025"

    # Create PostgreSQL database and missing tables automatically on startup.
    # These are safe defaults: if the database/tables already exist, nothing
    # destructive happens.
    AUTO_CREATE_POSTGRES_DATABASE = _as_bool(os.environ.get("AUTO_CREATE_POSTGRES_DATABASE"), True)
    AUTO_CREATE_TABLES = _as_bool(os.environ.get("AUTO_CREATE_TABLES"), True)
    AUTO_CREATE_PERFORMANCE_INDEXES = _as_bool(os.environ.get("AUTO_CREATE_PERFORMANCE_INDEXES"), True)

    # Since the tables can be created directly from models on a fresh PostgreSQL
    # database, stamp Alembic so future flask db upgrade commands do not try
    # to replay old SQLite-era migrations. If you later add a new migration,
    # update this value to the latest revision after testing.
    AUTO_STAMP_ALEMBIC_VERSION = _as_bool(os.environ.get("AUTO_STAMP_ALEMBIC_VERSION"), True)
    ALEMBIC_STAMP_REVISION = os.environ.get("ALEMBIC_STAMP_REVISION", "8b9c2d1e4f01")

    # Connection pool for PostgreSQL. These can be tuned without code changes.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "280")),
        "pool_size": int(os.getenv("DB_POOL_SIZE", "20")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "40")),
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
    }

    # ---------------------------
    # Sessions & Cookies (fixes random logouts)
    # ---------------------------
    SESSION_COOKIE_NAME = "wq_session"
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    # If serving over HTTP on LAN, keep False; set to 1 in env once behind HTTPS
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True

    # Flask-Login remember cookie
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_SAMESITE = "Lax"

    # CSRF for WTForms pages (login/register)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 60 * 60 * 8  # 8 hours

    # ---------------------------
    # SMTP Email Configuration
    # ---------------------------
    SMTP_SERVER = "172.17.1.17"
    SMTP_PORT = 25
    SMTP_USERNAME = None
    SMTP_PASSWORD = None
    SMTP_USE_TLS = False

    # ---------------------------
    # Range Alert Recipients (optional override)
    # ---------------------------
    RANGE_ALERT_RECIPIENTS = [
        # e.g. "waterquality.team@jindalsteel.com"
    ]
