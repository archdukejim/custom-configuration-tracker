import os
import logging
from flask import Flask, jsonify
from models import db
from git_manager import GitManager
from routes import hosts_bp, configs_bp


def create_app():
    app = Flask(__name__)

    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO))

    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["DATABASE_URL"]
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")

    db.init_app(app)

    git_repo_path = os.environ.get("GIT_REPO_PATH", "/var/cmdb/repo")
    git_user_name = os.environ.get("GIT_USER_NAME", "CMDB API")
    git_user_email = os.environ.get("GIT_USER_EMAIL", "cmdb@localhost")
    app.extensions["git_manager"] = GitManager(git_repo_path, git_user_name, git_user_email)

    app.register_blueprint(hosts_bp)
    app.register_blueprint(configs_bp)

    @app.route("/api/v1/health")
    def health():
        db_ok = True
        try:
            db.session.execute(db.text("SELECT 1"))
        except Exception:
            db_ok = False

        git_ok = app.extensions["git_manager"].health_check()

        status = "ok" if db_ok and git_ok else "degraded"
        code = 200 if status == "ok" else 503
        return jsonify({
            "status": status,
            "db": "ok" if db_ok else "error",
            "git": "ok" if git_ok else "error",
        }), code

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
