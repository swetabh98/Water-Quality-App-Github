from flask import Blueprint

health_bp = Blueprint("health", __name__)

@health_bp.get("/health")
def health():
    return "OK", 200