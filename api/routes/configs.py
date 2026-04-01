import hashlib
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, Response
from models import db, Host, ConfigFile, Snapshot, FileContent
from diff_utils import compute_unified_diff

configs_bp = Blueprint("configs", __name__, url_prefix="/api/v1/configs")


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

    cf = ConfigFile.query.filter_by(host_id=host.id, file_path=file_path).first()
    if not cf:
        cf = ConfigFile(host_id=host.id, file_path=file_path)
        db.session.add(cf)
        db.session.flush()

    last = (
        Snapshot.query
        .filter_by(config_file_id=cf.id)
        .order_by(Snapshot.submitted_at.desc())
        .first()
    )
    if last and last.file_hash == file_hash:
        db.session.rollback()
        return jsonify({"status": "unchanged"}), 200

    content = request.files["content"].read()
    content_hash = hashlib.sha256(content).hexdigest()

    if not db.session.get(FileContent, content_hash):
        fc = FileContent(hash=content_hash, content=content, size=len(content))
        db.session.add(fc)

    snap = Snapshot(
        config_file_id=cf.id,
        file_hash=file_hash,
        file_size=len(content),
        content_hash=content_hash,
    )
    db.session.add(snap)
    db.session.commit()

    return jsonify({"snapshot_id": str(snap.id), "content_hash": content_hash}), 201


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
            "content_hash": last.content_hash if last else None,
            "last_snapshot_at": last.submitted_at.isoformat() if last else None,
        })
    return jsonify(result)


@configs_bp.route("/<hostname>/history", methods=["GET"])
def file_history(hostname):
    file_path = request.args.get("file_path", "").strip()
    if not file_path:
        return jsonify({"error": "file_path query param is required"}), 400
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 500))
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
    snapshot_id = request.args.get("snapshot_id", "").strip()

    if not file_path or not snapshot_id:
        return jsonify({"error": "file_path and snapshot_id are required"}), 400

    host = Host.query.filter_by(hostname=hostname).first_or_404()
    cf = ConfigFile.query.filter_by(host_id=host.id, file_path=file_path).first_or_404()
    snap = Snapshot.query.filter_by(id=snapshot_id, config_file_id=cf.id).first_or_404()

    return Response(snap.file_content.content, mimetype="application/octet-stream")


@configs_bp.route("/<hostname>/diff", methods=["GET"])
def file_diff(hostname):
    file_path = request.args.get("file_path", "").strip()
    from_snap_id = request.args.get("from_snapshot_id", "").strip()
    to_snap_id = request.args.get("to_snapshot_id", "").strip()

    if not file_path or not from_snap_id or not to_snap_id:
        return jsonify({"error": "file_path, from_snapshot_id, and to_snapshot_id are required"}), 400

    host = Host.query.filter_by(hostname=hostname).first_or_404()
    cf = ConfigFile.query.filter_by(host_id=host.id, file_path=file_path).first_or_404()

    snap_from = Snapshot.query.filter_by(id=from_snap_id, config_file_id=cf.id).first_or_404()
    snap_to = Snapshot.query.filter_by(id=to_snap_id, config_file_id=cf.id).first_or_404()

    diff_text = compute_unified_diff(
        snap_from.file_content.content,
        snap_to.file_content.content,
        filename=file_path,
        from_label=snap_from.submitted_at.isoformat(),
        to_label=snap_to.submitted_at.isoformat(),
    )
    return Response(diff_text, mimetype="text/plain")
