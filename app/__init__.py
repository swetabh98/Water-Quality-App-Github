from flask import Flask, redirect, url_for, request, Response, render_template, send_from_directory
from flask_login import LoginManager, current_user, login_user
from flask_migrate import Migrate
from urllib.parse import unquote
import requests
import os

from werkzeug.security import generate_password_hash

from config import Config
from .models import db, User
from .postgres_bootstrap import ensure_postgres_database, create_missing_tables

# Initialize extensions globally
login_manager = LoginManager()
login_manager.login_view = 'auth.login'

migrate = Migrate()  # Will bind to `app` inside create_app()

TRACKER_UPSTREAM = "http://127.0.0.1:6660"
TRACKER_PREFIX = "/tracker"

CRM_LOGBOOK_UPSTREAM = "http://10.37.41.120:8801"
CRM_LOGBOOK_PREFIX = "/crm_logbook"

# CRM dashboard standalone backend running on port 5490
CRM_DASHBOARD_UPSTREAM = "http://127.0.0.1:5490"

# ✅ ---------------- AC APP CONFIGURATION ----------------
AC_APP_UPSTREAM = "http://172.17.18.13:2907"  # ✅ FIXED: was 172.17.188.58
AC_APP_PREFIX = "/ac"
# ✅ ------------------------------------------------------

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "content-encoding"
}


def _set_if_column(model_obj, column_names, value):
    """
    Safely set a field only if the User model has that column.
    This keeps the code compatible with different User model shapes.
    """
    try:
        available_columns = set(model_obj.__table__.columns.keys())
    except Exception:
        available_columns = set()

    for column_name in column_names:
        if column_name in available_columns:
            setattr(model_obj, column_name, value)


def _get_user_columns():
    try:
        return set(User.__table__.columns.keys())
    except Exception:
        return set()


def _find_demo_admin_user():
    """
    Find the Vercel demo admin user.
    The real User model has columns: id, email, password, role.
    Login ID shown to user is still: admin
    Stored email is: admin@demo.com
    """
    try:
        user = User.query.filter_by(email="admin@demo.com").first()
        if user:
            return user
    except Exception:
        pass

    try:
        user = User.query.filter_by(email="admin").first()
        if user:
            return user
    except Exception:
        pass

    return None


def _seed_vercel_demo_admin_user():
    """
    Creates/updates the demo admin user on Vercel.

    Login to use:
    User / ID: admin
    Password: admin123

    The login form normally expects an email address, so app/routes/auth.py
    maps the typed value 'admin' to this stored email: admin@demo.com.
    """
    password_hash = generate_password_hash("admin123")
    user = _find_demo_admin_user()

    if user is None:
        user = User(
            email="admin@demo.com",
            password=password_hash,
            role="admin",
        )
        db.session.add(user)
        db.session.commit()
        return user

    # Keep demo credentials correct on every cold start/redeploy.
    user.email = "admin@demo.com"
    user.password = password_hash
    user.role = "admin"
    db.session.commit()
    return user

def create_app(config_class=Config):
    """Creates and configures the Flask app."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # ---------------------------------------------------------------------
    # Vercel demo mode database fix
    # ---------------------------------------------------------------------
    # On local/server deployment:
    # - Keep your existing PostgreSQL behavior unchanged.
    #
    # On Vercel:
    # - Do not connect to internal PostgreSQL server.
    # - Use temporary SQLite database inside /tmp.
    # - Create demo login user:
    #   User / ID: admin
    #   Password: admin123
    # ---------------------------------------------------------------------
    is_vercel_demo = bool(
        os.environ.get("VERCEL") or os.environ.get("WATER_QUALITY_DEMO_MODE")
    )

    if is_vercel_demo:
        demo_db_uri = os.environ.get(
            "SQLALCHEMY_DATABASE_URI",
            os.environ.get("DATABASE_URL", "sqlite:////tmp/water_quality_demo.db")
        )

        app.config["SQLALCHEMY_DATABASE_URI"] = demo_db_uri
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

        # IMPORTANT:
        # Force a stable secret key on Vercel.
        # If this changes between serverless invocations, login succeeds but session is lost,
        # causing the app to return to login screen again.
        app.config["SECRET_KEY"] = os.environ.get(
            "SECRET_KEY",
            "water-quality-demo-secret-key-fixed"
        )

        app.config["SESSION_COOKIE_HTTPONLY"] = True
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["REMEMBER_COOKIE_SECURE"] = True
        app.config["REMEMBER_COOKIE_HTTPONLY"] = True
        app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
    else:
        # Create the PostgreSQL database first if it does not exist. This uses the
        # maintenance database configured in config.py, defaulting to postgres.
        ensure_postgres_database(app)

    # ✅ Prevent Flask from collapsing double-slashes in proxied URLs
    app.url_map.merge_slashes = False

    # Initialize extensions
    db.init_app(app)

    # Explicitly import all models to make them visible to Flask-Migrate
    from .models import (
        Report, ReportSection, ReportParameter, Department, Equipment, User, ParameterRange
    )

    # Initialize migration after models are known
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Create missing tables and performance indexes if they do not already exist.
    # This is non-destructive and will not delete existing PostgreSQL data.
    if is_vercel_demo:
        with app.app_context():
            db.create_all()
            _seed_vercel_demo_admin_user()
    else:
        create_missing_tables(app, db)

    # CLI commands
    from . import cli
    app.cli.add_command(cli.init_db_command)

    # Import Blueprints
    from .routes.auth import auth_bp
    from .routes.reports import reports_bp
    from .routes.analytics import analytics_bp
    from .routes.admin import admin_bp
    from .routes.sms2_reports import sms2_reports_bp
    from .routes.sms3_reports import sms3_reports_bp
    from .routes.rail_mill_reports import rail_mill_reports_bp
    from .routes.spm_reports import spm_reports_bp
    from .routes.power_plant_reports import power_plant_reports_bp

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(sms2_reports_bp)
    app.register_blueprint(sms3_reports_bp)
    app.register_blueprint(rail_mill_reports_bp)
    app.register_blueprint(spm_reports_bp)
    app.register_blueprint(power_plant_reports_bp)

    # Flask-Login user loader
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Default home redirect
    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('reports.dashboard'))
        return redirect(url_for('auth.login'))

    # ---------------------------------------------------------------------
    # Demo direct login fallback
    # ---------------------------------------------------------------------
    # Use this only on Vercel demo if normal login form still loops.
    # URL:
    #   /demo-login
    # ---------------------------------------------------------------------
    @app.route("/demo-login", methods=["GET", "POST"])
    def demo_login():
        if not is_vercel_demo:
            return redirect(url_for("auth.login"))

        user = _find_demo_admin_user()

        if user is None:
            with app.app_context():
                user = _seed_vercel_demo_admin_user()

        if user is None:
            return Response(
                "Demo login failed: could not create or find demo admin user.",
                status=500,
                mimetype="text/plain"
            )

        login_user(user, remember=True, force=True)

        try:
            return redirect(url_for("reports.dashboard"))
        except Exception:
            return redirect("/")

    # ---------------------------------------------------------------------
    # Demo-login diagnostic route
    # ---------------------------------------------------------------------
    @app.route("/demo-login-status")
    def demo_login_status():
        if not is_vercel_demo:
            return Response("Demo mode is not enabled.", status=400, mimetype="text/plain")

        try:
            user = _find_demo_admin_user()
            return {
                "demo_mode": True,
                "user_found": bool(user),
                "user_id": getattr(user, "id", None) if user else None,
                "email": getattr(user, "email", None) if user else None,
                "role": getattr(user, "role", None) if user else None,
                "current_user_authenticated": bool(current_user.is_authenticated),
            }
        except Exception as exc:
            return {"demo_mode": True, "error": str(exc)}, 500

    # ✅ ---------------- CRM DASHBOARD ROUTE ----------------
    @app.route("/CRM_Records")
    def crm():
        return render_template("crm_dashboard.html")
    # ✅ ----------------------------------------------------

    # ✅ ---------------- CRM DASHBOARD STATIC FILES ----------------
    @app.route("/CRM_Records/assets/<path:filename>")
    def crm_dashboard_assets(filename):
        crm_static_dir = os.path.join(
            os.path.dirname(__file__),
            "static",
            "crm_dashboard"
        )
        return send_from_directory(crm_static_dir, filename)
    # ✅ ------------------------------------------------------------

    # Health check endpoint for Flask Monitor
    @app.get("/health")
    def health():
        return "OK", 200

    def _build_upstream_url(upstream_base: str, prefix: str, path: str) -> str:
        path = path or ""
        if path and not path.startswith("/"):
            path = "/" + path
        return f"{upstream_base}{prefix}{path}"

    def _filtered_request_headers(prefix: str):
        headers = {}
        for key, value in request.headers.items():
            if key.lower() not in HOP_BY_HOP_HEADERS:
                headers[key] = value

        headers["X-Forwarded-Proto"] = request.scheme
        headers["X-Forwarded-Host"] = request.host
        headers["X-Forwarded-Port"] = (
            request.host.split(":")[-1]
            if ":" in request.host
            else ("443" if request.scheme == "https" else "80")
        )
        headers["X-Forwarded-Prefix"] = prefix

        accept_encoding = headers.get("Accept-Encoding", "")
        if accept_encoding:
            headers["Accept-Encoding"] = "identity"

        return headers

    def _filtered_response_headers(upstream_response):
        excluded = HOP_BY_HOP_HEADERS.union({"server", "date"})
        headers = []

        for key, value in upstream_response.headers.items():
            if key.lower() not in excluded:
                headers.append((key, value))

        return headers

    def _proxy_request(upstream_base: str, prefix: str, path=""):
        upstream_url = _build_upstream_url(upstream_base, prefix, path)

        try:
            upstream_response = requests.request(
                method=request.method,
                url=upstream_url,
                params=request.args,
                headers=_filtered_request_headers(prefix),
                data=request.get_data(),
                cookies=request.cookies,
                allow_redirects=False,
                # stream=True removed. Buffering the full response fixes Connection Aborted socket crashes
                timeout=300
            )
        except requests.RequestException as exc:
            return Response(
                f"Upstream is unavailable: {exc}",
                status=502,
                mimetype="text/plain"
            )

        # Uses .content to fully load the uncompressed response into memory safely
        body = upstream_response.content

        response = Response(
            response=body,
            status=upstream_response.status_code
        )

        for key, value in _filtered_response_headers(upstream_response):
            if key.lower() == "content-length":
                continue
            response.headers[key] = value

        content_type = upstream_response.headers.get("Content-Type")
        if content_type:
            response.headers["Content-Type"] = content_type

        response.headers["Content-Length"] = str(len(body))
        return response

    # ✅ ---------------- CRM DASHBOARD API PROXY ----------------
    @app.route("/CRM_Records/api/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    def crm_dashboard_api_proxy(path):
        return _proxy_request(CRM_DASHBOARD_UPSTREAM, "", f"api/{path}")
    # ✅ --------------------------------------------------------

    # ---------------- TRACKER PROXY ----------------
    @app.route("/tracker", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    def tracker_root_proxy():
        return _proxy_request(TRACKER_UPSTREAM, TRACKER_PREFIX, "")

    @app.route("/tracker/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    @app.route("/tracker/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    def tracker_path_proxy(path):
        return _proxy_request(TRACKER_UPSTREAM, TRACKER_PREFIX, path)

    # ---------------- CRM LOGBOOK PROXY ----------------
    @app.route("/crm_logbook", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    def crm_logbook_root_proxy():
        return _proxy_request(CRM_LOGBOOK_UPSTREAM, CRM_LOGBOOK_PREFIX, "")

    @app.route("/crm_logbook/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    @app.route("/crm_logbook/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    def crm_logbook_path_proxy(path):
        return _proxy_request(CRM_LOGBOOK_UPSTREAM, CRM_LOGBOOK_PREFIX, path)

    # ✅ ---------------- AC APP & QR PROXY ----------------
    def _rewrite_ac_html(resp):
        """Helper to safely rewrite all absolute static paths from the AC app HTML."""
        if resp.content_type and 'text/html' in resp.content_type:
            body = resp.get_data()
            body = body.replace(b'href="/static/', b'href="/ac/static/')
            body = body.replace(b'src="/static/', b'src="/ac/static/')
            resp.set_data(body)
        return resp

    @app.route("/AC_QR/<path:machine_code>", methods=["GET"])
    def ac_qr_direct_proxy(machine_code):
        # Decode %2F back to / so the full machine code is forwarded correctly
        decoded = unquote(machine_code)
        resp = _proxy_request(AC_APP_UPSTREAM, AC_APP_PREFIX, f"/public/{decoded}")
        return _rewrite_ac_html(resp)

    # Fetch CSS, JS, and Images from the internal app's actual static folder
    @app.route("/ac/static/<path:path>", methods=["GET", "OPTIONS", "HEAD"])
    def ac_static_proxy(path):
        return _proxy_request(AC_APP_UPSTREAM, "/static", f"/{path}")

    @app.route("/ac", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    def ac_root_proxy():
        resp = _proxy_request(AC_APP_UPSTREAM, AC_APP_PREFIX, "")
        return _rewrite_ac_html(resp)

    @app.route("/ac/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    @app.route("/ac/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    def ac_path_proxy(path):
        resp = _proxy_request(AC_APP_UPSTREAM, AC_APP_PREFIX, path)
        return _rewrite_ac_html(resp)
    # ✅ ---------------------------------------------------

    return app