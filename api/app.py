import os
import logging
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify
from models import db
from routes import hosts_bp, configs_bp, web_bp, admin_bp


def _timeago(dt):
    if dt is None:
        return "never"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    seconds = int((datetime.now(timezone.utc) - dt).total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return "just now" if seconds < 5 else f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    weeks = days // 7
    if weeks < 4:
        return f"{weeks}w ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    return f"{days // 365}y ago"


def _filesizeformat(size_bytes):
    if size_bytes is None:
        return "0 B"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    kb = size_bytes / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"
    return f"{mb / 1024:.2f} GB"


def create_app():
    app = Flask(__name__, template_folder="templates")

    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO))

    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["DATABASE_URL"]
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")

    db.init_app(app)

    app.register_blueprint(hosts_bp)
    app.register_blueprint(configs_bp)
    app.register_blueprint(web_bp)
    app.register_blueprint(admin_bp)

    app.jinja_env.filters["timeago"] = _timeago
    app.jinja_env.filters["filesizeformat"] = _filesizeformat

    @app.route("/api/v1/health")
    def health():
        db_ok = True
        try:
            db.session.execute(db.text("SELECT 1"))
        except Exception:
            db_ok = False

        status = "ok" if db_ok else "degraded"
        return jsonify({"status": status, "db": "ok" if db_ok else "error"}), 200 if db_ok else 503

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
