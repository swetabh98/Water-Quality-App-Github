import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------
# Vercel demo mode
# ---------------------------------------------------------------------
# Vercel cannot access internal/private PostgreSQL servers like 172.17.x.x.
# For demo deployment, use temporary SQLite storage inside /tmp.
#
# Note:
# /tmp storage on Vercel is temporary. It is fine for demo hosting,
# but data may reset after redeployments or cold starts.
# ---------------------------------------------------------------------
if os.environ.get("VERCEL"):
    os.environ["WATER_QUALITY_DEMO_MODE"] = "1"
    os.environ["DATABASE_URL"] = "sqlite:////tmp/water_quality_demo.db"
    os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:////tmp/water_quality_demo.db"
    os.environ.setdefault("SECRET_KEY", "water-quality-demo-secret-key")

from app import create_app

app = create_app()