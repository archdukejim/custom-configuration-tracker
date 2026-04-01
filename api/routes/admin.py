from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify
from models import db

admin_bp = Blueprint("admin", __name__, url_prefix="/api/v1/admin")


@admin_bp.route("/stats", methods=["GET"])
def stats():
    """Storage and snapshot statistics."""
    snap_row = db.session.execute(db.text("""
        SELECT COUNT(*) AS total_snapshots, COALESCE(SUM(file_size), 0) AS total_file_size
        FROM snapshots
    """)).fetchone()

    content_row = db.session.execute(db.text("""
        SELECT COUNT(*) AS unique_blobs, COALESCE(SUM(size), 0) AS stored_bytes
        FROM file_contents
    """)).fetchone()

    host_count = db.session.execute(db.text("SELECT COUNT(*) FROM hosts")).scalar()
    file_count = db.session.execute(db.text("SELECT COUNT(*) FROM config_files")).scalar()

    return jsonify({
        "hosts": host_count,
        "tracked_files": file_count,
        "total_snapshots": snap_row.total_snapshots,
        "total_file_size_bytes": snap_row.total_file_size,
        "unique_content_blobs": content_row.unique_blobs,
        "stored_bytes": content_row.stored_bytes,
    })


@admin_bp.route("/prune", methods=["POST"])
def prune():
    """Delete old snapshots (keeping the latest per file) and orphaned content blobs.

    Body (JSON):
        retain_days : int  — keep snapshots newer than this many days (default: 90)

    The latest snapshot for each file is always preserved regardless of age.
    """
    body = request.get_json(force=True, silent=True) or {}
    try:
        retain_days = int(body.get("retain_days", 90))
    except (TypeError, ValueError):
        return jsonify({"error": "retain_days must be an integer"}), 400
    if retain_days < 1:
        return jsonify({"error": "retain_days must be >= 1"}), 400

    cutoff = datetime.now(timezone.utc) - timedelta(days=retain_days)

    # Delete old snapshots, but always keep the most recent one per file.
    # DISTINCT ON (config_file_id) ordered by submitted_at DESC gives us the
    # latest snapshot id per file — those are excluded from deletion.
    snap_result = db.session.execute(db.text("""
        WITH latest AS (
            SELECT DISTINCT ON (config_file_id) id
            FROM snapshots
            ORDER BY config_file_id, submitted_at DESC
        )
        DELETE FROM snapshots
        WHERE submitted_at < :cutoff
          AND id NOT IN (SELECT id FROM latest)
        RETURNING file_size
    """), {"cutoff": cutoff})

    deleted_snap_rows = snap_result.fetchall()
    snapshots_deleted = len(deleted_snap_rows)
    bytes_from_snaps = sum(r.file_size for r in deleted_snap_rows)

    # Remove file_contents blobs that no snapshot references anymore.
    content_result = db.session.execute(db.text("""
        DELETE FROM file_contents
        WHERE hash NOT IN (SELECT DISTINCT content_hash FROM snapshots)
        RETURNING size
    """))

    deleted_content_rows = content_result.fetchall()
    content_deleted = len(deleted_content_rows)
    bytes_freed = sum(r.size for r in deleted_content_rows)

    db.session.commit()

    return jsonify({
        "retain_days": retain_days,
        "cutoff": cutoff.isoformat(),
        "snapshots_deleted": snapshots_deleted,
        "content_blobs_deleted": content_deleted,
        "bytes_freed": bytes_freed,
    }), 200
