# wsgi.py — high-throughput setup for many concurrent users (Windows-friendly)

import os, socket, multiprocessing
from waitress import serve
from app import create_app

# ---------- Helpers ----------
def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # doesn't need to be reachable
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()

# ---------- App ----------
print("🔧 Importing Flask app...")
app = create_app()
print("✅ Flask app created.")

# Production toggles that directly help performance
app.config.setdefault("SEND_FILE_MAX_AGE_DEFAULT", 31536000)  # cache /static for 1y
app.config.setdefault("TEMPLATES_AUTO_RELOAD", False)

# ---------------- Compression (Gzip) ----------------
# Prefer Flask-Compress (works across Werkzeug versions), fallback to Werkzeug GzipMiddleware.
enabled_compression = False
try:
    from flask_compress import Compress
    # Tunables via env
    app.config.setdefault("COMPRESS_ALGORITHM", "gzip")
    app.config.setdefault("COMPRESS_LEVEL", int(os.getenv("GZIP_LEVEL", "6")))
    app.config.setdefault("COMPRESS_MIN_SIZE", int(os.getenv("GZIP_MIN_SIZE", "1024")))
    app.config.setdefault(
        "COMPRESS_MIMETYPES",
        [
            "text/html", "text/css", "text/xml",
            "application/json", "application/javascript", "application/xml",
            "image/svg+xml"
        ],
    )
    Compress(app)
    enabled_compression = True
    print("🗜️  Compression enabled via Flask-Compress.")
except Exception as e_fc:
    try:
        from werkzeug.middleware.gzip import GzipMiddleware
        app.wsgi_app = GzipMiddleware(
            app.wsgi_app,
            compresslevel=int(os.getenv("GZIP_LEVEL", "5")),
            minimum_size=int(os.getenv("GZIP_MIN_SIZE", "1024")),
        )
        enabled_compression = True
        print("🗜️  Compression enabled via Werkzeug Gzip.")
    except Exception as e_wz:
        print(f"⚠️  Compression not enabled: {e_fc} / {e_wz}")

# Faster /static serving with long cache headers (optional but recommended)
try:
    from whitenoise import WhiteNoise
    static_root = os.path.join(app.root_path, "static")
    app.wsgi_app = WhiteNoise(
        app.wsgi_app,
        root=static_root,
        prefix="static/",
        max_age=int(os.getenv("STATIC_MAX_AGE", "31536000")),  # 1y
        autorefresh=False  # True only in dev
    )
    print("🧊 WhiteNoise static acceleration enabled.")
except Exception as e:
    print(f"ℹ️  WhiteNoise not enabled (optional): {e}")

# Honor proxy headers if you later put Nginx/Cloudflare in front
if os.getenv("PROXY_FIX", "0") == "1":
    try:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
        print("🛡️  ProxyFix enabled.")
    except Exception as e:
        print(f"⚠️  ProxyFix not enabled: {e}")

# ---------- Waitress knobs (aggressive but safe defaults) ----------
CPU         = max(1, multiprocessing.cpu_count())
PORT        = int(os.getenv("PORT", "8826"))
HOST        = os.getenv("HOST", "0.0.0.0")
THREADS     = int(os.getenv("WAITRESS_THREADS", str(max(32, CPU * 4))))   # higher default
CONN_LIMIT  = int(os.getenv("WAITRESS_CONN_LIMIT", "1500"))
BACKLOG     = int(os.getenv("WAITRESS_BACKLOG", "4096"))
LOOKAHEAD   = int(os.getenv("WAITRESS_LOOKAHEAD", "10"))
CHAN_TIMEOUT= int(os.getenv("WAITRESS_CHANNEL_TIMEOUT", "30"))
IN_OVFL     = int(os.getenv("WAITRESS_INBUF_OVERFLOW", str(2 * 1024 * 1024)))  # 2MB
OUT_OVFL    = int(os.getenv("WAITRESS_OUTBUF_OVERFLOW", str(4 * 1024 * 1024))) # 4MB
IDENT       = os.getenv("WAITRESS_IDENT", "JSPL-Water/Waitress")
URL_SCHEME  = os.getenv("URL_SCHEME")  # set to "https" if TLS terminates at proxy

def main():
    ip = _local_ip()
    print("🚀 Starting Waitress production server...")
    print(f"🌐 Open on host machine:     http://localhost:{PORT}")
    print(f"📡 Open on local network:   http://{ip}:{PORT}")
    print(f"⚙️  Waitress: threads={THREADS}, conn_limit={CONN_LIMIT}, backlog={BACKLOG}, lookahead={LOOKAHEAD}, timeout={CHAN_TIMEOUT}")

    serve(
        app,
        host=HOST,
        port=PORT,
        threads=THREADS,
        connection_limit=CONN_LIMIT,
        backlog=BACKLOG,
        channel_request_lookahead=LOOKAHEAD,
        channel_timeout=CHAN_TIMEOUT,
        asyncore_use_poll=True,     # good on Windows
        inbuf_overflow=IN_OVFL,
        outbuf_overflow=OUT_OVFL,
        ident=IDENT,
        url_scheme=URL_SCHEME,
        expose_tracebacks=False,
    )

if __name__ == "__main__":
    main()
