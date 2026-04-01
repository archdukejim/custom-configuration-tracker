from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, request, abort, url_for
from sqlalchemy import func
from models import db, Host, ConfigFile, Snapshot, FileContent
from diff_utils import compute_unified_diff, parse_diff_lines
from language_map import detect_language

web_bp = Blueprint("web", __name__, url_prefix="")


@web_bp.route("/")
def dashboard():
    hosts = Host.query.order_by(Host.last_seen.desc()).all()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    rows = []
    for host in hosts:
        file_count = (
            db.session.query(func.count(ConfigFile.id))
            .filter_by(host_id=host.id)
            .scalar()
        )
        changes_24h = (
            db.session.query(func.count(Snapshot.id))
            .join(ConfigFile, Snapshot.config_file_id == ConfigFile.id)
            .filter(ConfigFile.host_id == host.id)
            .filter(Snapshot.submitted_at >= cutoff)
            .scalar()
        )
        age = datetime.now(timezone.utc) - host.last_seen.replace(tzinfo=timezone.utc)
        status = "active" if age < timedelta(minutes=5) else "inactive"

        rows.append({
            "host": host,
            "file_count": file_count,
            "changes_24h": changes_24h,
            "status": status,
        })

    total_files = db.session.query(func.count(ConfigFile.id)).scalar()
    total_snaps = db.session.query(func.count(Snapshot.id)).scalar()

    return render_template("dashboard.html", hosts=rows, stats={
        "hosts": len(hosts),
        "files": total_files,
        "snapshots": total_snaps,
    })


@web_bp.route("/hosts/<hostname>")
def host_detail(hostname):
    host = Host.query.filter_by(hostname=hostname).first_or_404()

    q = request.args.get("q", "").strip()
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = max(10, min(int(request.args.get("per_page", 100)), 500))
    except ValueError:
        page, per_page = 1, 100

    base_query = ConfigFile.query.filter_by(host_id=host.id)
    if q:
        base_query = base_query.filter(ConfigFile.file_path.ilike(f"%{q}%"))

    total_files = base_query.count()
    pages = max(1, (total_files + per_page - 1) // per_page)
    page = min(page, pages)

    config_files = (
        base_query
        .order_by(ConfigFile.file_path)
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    files = []
    for cf in config_files:
        last = (
            Snapshot.query
            .filter_by(config_file_id=cf.id)
            .order_by(Snapshot.submitted_at.desc())
            .first()
        )
        snap_count = (
            db.session.query(func.count(Snapshot.id))
            .filter_by(config_file_id=cf.id)
            .scalar()
        )
        files.append({
            "file_path": cf.file_path,
            "last_snapshot_at": last.submitted_at if last else None,
            "snapshot_count": snap_count,
            "size": last.file_size if last else 0,
        })

    pagination = {
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "total": total_files,
        "prev_url": url_for("web.host_detail", hostname=hostname, q=q, page=page - 1) if page > 1 else None,
        "next_url": url_for("web.host_detail", hostname=hostname, q=q, page=page + 1) if page < pages else None,
    }

    return render_template("host_detail.html", host=host, hostname=hostname, files=files,
                           q=q, pagination=pagination)


@web_bp.route("/hosts/<hostname>/history")
def file_history(hostname):
    file_path = request.args.get("file_path", "").strip()
    if not file_path:
        abort(400)

    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = max(10, min(int(request.args.get("per_page", 50)), 200))
    except ValueError:
        page, per_page = 1, 50

    host = Host.query.filter_by(hostname=hostname).first_or_404()
    cf = ConfigFile.query.filter_by(host_id=host.id, file_path=file_path).first_or_404()

    total = Snapshot.query.filter_by(config_file_id=cf.id).count()
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    offset = (page - 1) * per_page

    # Fetch one extra row to resolve the "diff vs prev" link for the last visible snapshot
    # across page boundaries without an extra query.
    raw = (
        Snapshot.query
        .filter_by(config_file_id=cf.id)
        .order_by(Snapshot.submitted_at.desc())
        .offset(offset)
        .limit(per_page + 1)
        .all()
    )
    display = raw[:per_page]
    boundary = raw[per_page] if len(raw) > per_page else None

    snapshots = []
    for i, s in enumerate(display):
        if i + 1 < len(display):
            prev_id = str(display[i + 1].id)
        elif boundary:
            prev_id = str(boundary.id)
        else:
            prev_id = None
        snapshots.append({
            "id": str(s.id),
            "submitted_at": s.submitted_at,
            "content_hash": s.content_hash,
            "size": s.file_size,
            "prev_snapshot_id": prev_id,
            "number": total - offset - i,
        })

    pagination = {
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "total": total,
        "prev_url": url_for("web.file_history", hostname=hostname, file_path=file_path, page=page - 1) if page > 1 else None,
        "next_url": url_for("web.file_history", hostname=hostname, file_path=file_path, page=page + 1) if page < pages else None,
    }

    return render_template("history.html", hostname=hostname, file_path=file_path,
                           snapshots=snapshots, pagination=pagination)


@web_bp.route("/hosts/<hostname>/diff")
def file_diff(hostname):
    file_path = request.args.get("file_path", "").strip()
    from_snap_id = request.args.get("from_snapshot_id", "").strip()
    to_snap_id = request.args.get("to_snapshot_id", "").strip()

    if not file_path or not from_snap_id or not to_snap_id:
        abort(400)

    host = Host.query.filter_by(hostname=hostname).first_or_404()
    cf = ConfigFile.query.filter_by(host_id=host.id, file_path=file_path).first_or_404()
    snap_from = Snapshot.query.filter_by(id=from_snap_id, config_file_id=cf.id).first_or_404()
    snap_to = Snapshot.query.filter_by(id=to_snap_id, config_file_id=cf.id).first_or_404()

    diff_text = compute_unified_diff(
        snap_from.file_content.content,
        snap_to.file_content.content,
        filename=file_path,
        from_label=snap_from.submitted_at.strftime("%Y-%m-%d %H:%M UTC"),
        to_label=snap_to.submitted_at.strftime("%Y-%m-%d %H:%M UTC"),
    )
    diff_lines = parse_diff_lines(diff_text)

    return render_template("diff.html",
        hostname=hostname,
        file_path=file_path,
        diff_lines=diff_lines,
        from_snap={
            "id": str(snap_from.id),
            "submitted_at": snap_from.submitted_at,
            "content_hash": snap_from.content_hash,
        },
        to_snap={
            "id": str(snap_to.id),
            "submitted_at": snap_to.submitted_at,
            "content_hash": snap_to.content_hash,
        },
    )


@web_bp.route("/hosts/<hostname>/content")
def file_content(hostname):
    file_path = request.args.get("file_path", "").strip()
    snapshot_id = request.args.get("snapshot_id", "").strip()

    if not file_path or not snapshot_id:
        abort(400)

    host = Host.query.filter_by(hostname=hostname).first_or_404()
    cf = ConfigFile.query.filter_by(host_id=host.id, file_path=file_path).first_or_404()
    snap = Snapshot.query.filter_by(id=snapshot_id, config_file_id=cf.id).first_or_404()

    raw = snap.file_content.content
    is_binary = b"\x00" in raw
    language = detect_language(file_path)
    content_text = "" if is_binary else raw.decode("utf-8", errors="replace")

    return render_template("content.html",
        hostname=hostname,
        file_path=file_path,
        snapshot={
            "id": str(snap.id),
            "submitted_at": snap.submitted_at,
            "content_hash": snap.content_hash,
            "size": snap.file_size,
        },
        content_text=content_text,
        language=language,
        is_binary=is_binary,
    )
