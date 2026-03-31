import subprocess
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app, Response
from models import db, Host, ConfigFile, Snapshot

configs_bp = Blueprint("configs", __name__, url_prefix="/api/v1/configs")


def _get_git():
    return current_app.extensions["git_manager"]


@configs_bp.route("/submit", methods=["POST"])
def submit_config():
    agent_id = request.form.get("agent_id", "").strip()
    file_path = request.form.get("file_path", "").strip()
    file_hash = request.form.get("file_hash", "").strip()

    if not agent_id or not file_path or not file_hash:
        return jsonify({"error": "agent_id, file_path, and file_hash are required"}), 400

    if "content" not in request.files:
        return jsonify({"error": "content file part is required"}), 400

    host = Host.query.filter_by(agent_id=agent_id).first()
    if not host:
        return jsonify({"error": "Unknown agent_id — register the host first"}), 404

    host.last_seen = datetime.now(timezone.utc)

    # Upsert config_file
    cf = ConfigFile.query.filter_by(host_id=host.id, file_path=file_path).first()
    if not cf:
        cf = ConfigFile(host_id=host.id, file_path=file_path)
        db.session.add(cf)
        db.session.flush()

    # Dedup: if last snapshot has same hash, skip
    last = (
        Snapshot.query
        .filter_by(config_file_id=cf.id)
        .order_by(Snapshot.submitted_at.desc())
        .first()
    )
    if last and last.file_hash == file_hash:
        db.session.rollback()
        return jsonify({"status": "unchanged", "last_commit_sha": last.commit_sha}), 200

    content = request.files["content"].read()
    commit_message = f"[{host.hostname}] {file_path}"

    try:
        commit_sha = _get_git().write_and_commit(host.hostname, file_path, content, commit_message)
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("git commit failed")
        return jsonify({"error": "git commit failed", "detail": str(e)}), 500

    snap = Snapshot(
        config_file_id=cf.id,
        file_hash=file_hash,
        file_size=len(content),
        commit_sha=commit_sha,
        commit_message=commit_message,
    )
    db.session.add(snap)
    db.session.commit()

    return jsonify({"snapshot_id": str(snap.id), "commit_sha": commit_sha}), 201


@configs_bp.route("/<hostname>", methods=["GET"])
def list_files(hostname):
    host = Host.query.filter_by(hostname=hostname).first_or_404(
        description=f"Host {hostname!r} not found"
    )
    files = ConfigFile.query.filter_by(host_id=host.id).order_by(ConfigFile.file_path).all()
    result = []
    for cf in files:
        last = (
            Snapshot.query
            .filter_by(config_file_id=cf.id)
            .order_by(Snapshot.submitted_at.desc())
            .first()
        )
        result.append({
            "file_id": str(cf.id),
            "file_path": cf.file_path,
            "last_hash": last.file_hash if last else None,
            "last_commit_sha": last.commit_sha if last else None,
            "last_snapshot_at": last.submitted_at.isoformat() if last else None,
        })
    return jsonify(result)


@configs_bp.route("/<hostname>/history", methods=["GET"])
def file_history(hostname):
    file_path = request.args.get("file_path", "").strip()
    if not file_path:
        return jsonify({"error": "file_path query param is required"}), 400

    try:
        limit = int(request.args.get("limit", 50))
        limit = max(1, min(limit, 500))
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400

    host = Host.query.filter_by(hostname=hostname).first_or_404()
    cf = ConfigFile.query.filter_by(host_id=host.id, file_path=file_path).first_or_404(
        description=f"File {file_path!r} not tracked for host {hostname!r}"
    )

    snaps = (
        Snapshot.query
        .filter_by(config_file_id=cf.id)
        .order_by(Snapshot.submitted_at.desc())
        .limit(limit)
        .all()
    )
    return jsonify([s.to_dict() for s in snaps])


@configs_bp.route("/<hostname>/content", methods=["GET"])
def file_content(hostname):
    file_path = request.args.get("file_path", "").strip()
    commit_sha = request.args.get("commit_sha", "").strip()
    if not file_path or not commit_sha:
        return jsonify({"error": "file_path and commit_sha are required"}), 400

    host = Host.query.filter_by(hostname=hostname).first_or_404()

    try:
        content = _get_git().get_file_at_commit(commit_sha, host.hostname, file_path)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except subprocess.CalledProcessError:
        return jsonify({"error": "File or commit not found in git"}), 404
    except Exception as e:
        current_app.logger.exception("git show failed")
        return jsonify({"error": str(e)}), 500

    return Response(content, mimetype="application/octet-stream")


@configs_bp.route("/<hostname>/diff", methods=["GET"])
def file_diff(hostname):
    file_path = request.args.get("file_path", "").strip()
    from_commit = request.args.get("from_commit", "").strip()
    to_commit = request.args.get("to_commit", "HEAD").strip()

    if not file_path or not from_commit:
        return jsonify({"error": "file_path and from_commit are required"}), 400

    host = Host.query.filter_by(hostname=hostname).first_or_404()

    try:
        diff = _get_git().get_diff(from_commit, to_commit, host.hostname, file_path)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.exception("git diff failed")
        return jsonify({"error": str(e)}), 500

    return Response(diff, mimetype="text/plain")
