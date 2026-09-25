"""Stream service: catalog queries, watch sessions, plate normalization."""

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import SentinelError
from app.models.camera import Camera
from app.models.department import Department
from app.models.module2 import StreamHealthEvent, StreamSource, ViewerSession
from app.services.camera_service import user_department_filter

SESSION_STALE_MINUTES = 2


def list_streams(
    db: Session, user, department_id: str | None = None, vms_system: str | None = None,
    protocol: str | None = None, status: str | None = None, q: str | None = None,
) -> list[dict]:
    stmt = (
        select(StreamSource, Camera, Department.name)
        .join(Camera, StreamSource.camera_id == Camera.camera_id)
        .join(Department, StreamSource.department_id == Department.department_id)
    )
    flt = user_department_filter(user, db)
    if flt is not None:
        stmt = stmt.where(flt)
    if department_id:
        stmt = stmt.where(StreamSource.department_id == department_id)
    if vms_system:
        stmt = stmt.where(StreamSource.vms_system == vms_system)
    if protocol:
        stmt = stmt.where(StreamSource.protocol == protocol)
    if status:
        stmt = stmt.where(StreamSource.status == status)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            func.lower(StreamSource.label).like(like)
            | func.lower(Camera.name).like(like)
            | func.lower(Camera.camera_code).like(like)
        )
    rows = db.execute(stmt.limit(2000)).all()
    out = []
    for s, cam, dept_name in rows:
        out.append({
            "stream_id": s.stream_id,
            "camera_id": s.camera_id,
            "label": s.label,
            "camera_name": cam.name,
            "camera_code": cam.camera_code,
            "district": cam.district,
            "department": dept_name,
            "department_id": s.department_id,
            "vms_system": s.vms_system,
            "protocol": s.protocol,
            "is_live": s.is_live,
            "enabled": s.enabled,
            "status": s.status,
            "latency_ms": s.latency_ms,
            "analytics_enabled": s.analytics_enabled,
            "last_probe_at": s.last_probe_at.isoformat() if s.last_probe_at else None,
        })
    return out


def get_stream_scoped(stream_id: str, user, db: Session) -> StreamSource:
    s = db.get(StreamSource, stream_id)
    if not s:
        raise SentinelError("STREAM_NOT_FOUND", "Stream not found", 404)
    flt = user_department_filter(user, db)
    if flt is not None:
        cam = db.get(Camera, s.camera_id)
        if cam is None or not db.scalar(
            select(func.count()).select_from(Camera).where(flt).where(Camera.camera_id == cam.camera_id)
        ):
            raise SentinelError("AUTH_FORBIDDEN", "Stream outside your department scope", 403)
    return s


def start_watch(db: Session, user, stream_id: str) -> dict:
    s = get_stream_scoped(stream_id, user, db)
    now = datetime.now(timezone.utc)
    sess = ViewerSession(user_id=user.user_id, stream_id=s.stream_id,
                         started_at=now, last_heartbeat_at=now, active=True)
    db.add(sess)
    db.flush()
    return {
        "session_id": sess.session_id,
        "stream_id": s.stream_id,
        "protocol": s.protocol,
        "hls_url": f"/streams/hls/{s.stream_id}/index.m3u8",
        "label": s.label,
    }


def heartbeat(db: Session, user, session_id: str) -> dict:
    sess = db.get(ViewerSession, session_id)
    if not sess or sess.user_id != user.user_id or not sess.active:
        raise SentinelError("SESSION_NOT_FOUND", "Viewer session not found or expired", 404)
    sess.last_heartbeat_at = datetime.now(timezone.utc)
    return {"session_id": sess.session_id, "active": True}


def stop_watch(db: Session, user, session_id: str) -> dict:
    sess = db.get(ViewerSession, session_id)
    if not sess or sess.user_id != user.user_id:
        raise SentinelError("SESSION_NOT_FOUND", "Viewer session not found", 404)
    sess.active = False
    sess.ended_at = datetime.now(timezone.utc)
    return {"session_id": sess.session_id, "active": False}


_PLATE_RE = re.compile(r"[^A-Z0-9]")


def normalize_plate(raw: str) -> str:
    """Uppercase, strip separators/O-swap: GJ-01 AB 1234 -> GJ01AB1234."""
    up = (raw or "").upper()
    up = up.replace("O", "0")
    return _PLATE_RE.sub("", up)


def sweep_stale_sessions(db: Session) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=SESSION_STALE_MINUTES)
    rows = db.execute(
        select(ViewerSession).where(ViewerSession.active.is_(True), ViewerSession.last_heartbeat_at < cutoff)
    ).scalars().all()
    for sess in rows:
        sess.active = False
        sess.ended_at = datetime.now(timezone.utc)
    return len(rows)


def health_history(db: Session, stream_id: str, limit: int = 50) -> list[dict]:
    rows = db.execute(
        select(StreamHealthEvent)
        .where(StreamHealthEvent.stream_id == stream_id)
        .order_by(StreamHealthEvent.checked_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        {
            "status": h.status,
            "latency_ms": h.latency_ms,
            "detail": h.detail,
            "checked_at": h.checked_at.isoformat(),
        }
        for h in rows
    ]
