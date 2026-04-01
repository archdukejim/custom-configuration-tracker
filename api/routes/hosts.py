from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from sqlalchemy import func
from models import db, Host, ConfigFile, Snapshot

hosts_bp = Blueprint("hosts", __name__, url_prefix="/api/v1/hosts")


@hosts_bp.route("", methods=["GET"])
def list_hosts():
    hosts = Host.query.order_by(Host.last_seen.desc()).all()
    return jsonify([h.to_dict() for h in hosts])


@hosts_bp.route("/<hostname>", methods=["GET"])
def get_host(hostname):
    host = Host.query.filter_by(hostname=hostname).first_or_404(
        description=f"Host {hostname!r} not found"
    )
    data = host.to_dict()
    data["file_count"] = db.session.query(func.count(ConfigFile.id)).filter_by(host_id=host.id).scalar()

    # Last snapshot time across all files for this host
    last_snap = (
        db.session.query(func.max(Snapshot.submitted_at))
        .join(ConfigFile, Snapshot.config_file_id == ConfigFile.id)
        .filter(ConfigFile.host_id == host.id)
        .scalar()
    )
    data["last_snapshot_at"] = last_snap.isoformat() if last_snap else None
    return jsonify(data)


@hosts_bp.route("/register", methods=["POST"])
def register_host():
    body = request.get_json(force=True, silent=True)
    if not body:
        return jsonify({"error": "JSON body required"}), 400

    hostname = body.get("hostname", "").strip()
    agent_id = body.get("agent_id", "").strip()
    if not hostname or not agent_id:
        return jsonify({"error": "hostname and agent_id are required"}), 400

    host = Host.query.filter_by(agent_id=agent_id).first()

    if host and host.hostname != hostname:
        return jsonify({"error": "agent_id already registered to a different hostname"}), 409

    if not host:
        existing = Host.query.filter_by(hostname=hostname).first()
        if existing:
            return jsonify({"error": f"hostname {hostname!r} already registered with a different agent_id"}), 409
        host = Host(hostname=hostname, agent_id=agent_id)
        db.session.add(host)

    host.last_seen = datetime.now(timezone.utc)
    host.metadata_ = body.get("metadata", {}) or {}
    db.session.commit()

    return jsonify({"host_id": str(host.id), "hostname": host.hostname}), 200


@hosts_bp.route("/<hostname>/heartbeat", methods=["POST"])
def heartbeat(hostname):
    body = request.get_json(force=True, silent=True) or {}
    agent_id = body.get("agent_id", "").strip()
    if not agent_id:
        return jsonify({"error": "agent_id is required"}), 400

    host = Host.query.filter_by(hostname=hostname, agent_id=agent_id).first()
    if not host:
        return jsonify({"error": "Host not found or agent_id mismatch"}), 404

    host.last_seen = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"ok": True}), 200
