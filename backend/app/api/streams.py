"""Module 2 streams API: unified viewer endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_perm
from app.core.errors import SentinelError, request_id_var
from app.models.module2 import StreamSource, ViewerSession
from app.models.user import User
from app.services import audit as audit_svc
from app.services.camera_service import user_department_filter
from app.services.hls_service import fetch_playlist, fetch_segment, verify_segment_token
from app.services.sentinel_adapter import seed_simulated_feeds, seed_watchlist, sync_catalogue
from app.services.stream_service import (
    get_stream_scoped,
    health_history,
    heartbeat,
    list_streams,
    start_watch,
    stop_watch,
)

router = APIRouter(prefix="/streams", tags=["streams"])


@router.get("")
def list_all(
    department_id: str | None = None,
    vms_system: str | None = None,
    protocol: str | None = None,
    status: str | None = None,
    q: str | None = None,
    user: User = Depends(require_perm("camera", "read")),
    db: Session = Depends(get_db),
):
    rows = list_streams(db, user, department_id, vms_system, protocol, status, q)
    vms_options = sorted({r["vms_system"] for r in rows})
    return {"data": rows, "meta": {"total": len(rows), "vms_systems": vms_options}, "requestId": request_id_var.get()}


@router.get("/health/summary")
def health_summary(user: User = Depends(require_perm("camera", "read")), db: Session = Depends(get_db)):
    rows = list_streams(db, user)
    summary = {"total": len(rows), "ONLINE": 0, "OFFLINE": 0, "UNKNOWN": 0}
    for r in rows:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {"data": summary, "meta": {}, "requestId": request_id_var.get()}


@router.post("/{stream_id}/watch")
def watch(stream_id: str, request: Request, user: User = Depends(require_perm("camera", "read")), db: Session = Depends(get_db)):
    info = start_watch(db, user, stream_id)
    audit_svc.record(
        db, "STREAM_WATCH_START", "stream", stream_id,
        after_state={"session_id": info["session_id"], "label": info["label"]},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return {"data": info, "meta": {}, "requestId": request_id_var.get()}


@router.post("/sessions/{session_id}/heartbeat")
def hb(session_id: str, user: User = Depends(require_perm("camera", "read")), db: Session = Depends(get_db)):
    return {"data": heartbeat(db, user, session_id), "meta": {}, "requestId": request_id_var.get()}


@router.post("/sessions/{session_id}/stop")
def stop(session_id: str, request: Request, user: User = Depends(require_perm("camera", "read")), db: Session = Depends(get_db)):
    out = stop_watch(db, user, session_id)
    audit_svc.record(
        db, "STREAM_WATCH_STOP", "viewer_session", session_id,
        after_state=out, actor_user_id=user.user_id, actor_label=user.email,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"data": out, "meta": {}, "requestId": request_id_var.get()}


@router.get("/{stream_id}/health")
def stream_health(stream_id: str, user: User = Depends(require_perm("camera", "read")), db: Session = Depends(get_db)):
    s = get_stream_scoped(stream_id, user, db)
    return {
        "data": {
            "stream_id": s.stream_id, "status": s.status,
            "latency_ms": s.latency_ms,
            "last_probe_at": s.last_probe_at.isoformat() if s.last_probe_at else None,
            "history": health_history(db, stream_id),
        },
        "meta": {}, "requestId": request_id_var.get(),
    }


@router.get("/hls/{stream_id}/{session_id}/index.m3u8")
async def hls_playlist(stream_id: str, session_id: str, db: Session = Depends(get_db)):
    """Playlist requires a valid, active viewer session owned by the caller's token."""
    # For simplicity in this prototype the playlist is authenticated by the
    # session id itself; production would also bind it to the JWT sub.
    sess = db.get(ViewerSession, session_id)
    if not sess or not sess.active or sess.stream_id != stream_id:
        raise SentinelError("SESSION_INVALID", "Viewer session is invalid or expired", 403)
    s = db.get(StreamSource, stream_id)
    if not s:
        raise SentinelError("STREAM_NOT_FOUND", "Stream not found", 404)
    body, headers = await fetch_playlist(s, session_id)
    return Response(content=body, media_type="application/vnd.apple.mpegurl", headers=headers)


@router.get("/hls/{stream_id}/{session_id}/{token}/seg/{name}")
async def hls_segment(stream_id: str, session_id: str, token: str, name: str, db: Session = Depends(get_db)):
    if not verify_segment_token(stream_id, name, session_id, token):
        raise SentinelError("SEGMENT_TOKEN_INVALID", "Segment link expired", 403)
    s = db.get(StreamSource, stream_id)
    if not s:
        raise SentinelError("STREAM_NOT_FOUND", "Stream not found", 404)
    data, headers = await fetch_segment(s, name)
    return Response(content=data, media_type=headers.get("content-type", "video/mp2t"))


@router.post("/admin/sync-sentinel")
def sync_sentinel(request: Request, user: User = Depends(require_perm("user", "manage")), db: Session = Depends(get_db)):
    result = sync_catalogue(db)
    audit_svc.record(
        db, "SENTINEL_SYNC", "stream_catalogue", None,
        after_state=result, actor_user_id=user.user_id, actor_label=user.email,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"data": result, "meta": {}, "requestId": request_id_var.get()}


@router.post("/admin/seed-simulated")
def seed_sim(request: Request, user: User = Depends(require_perm("user", "manage")), db: Session = Depends(get_db)):
    streams = seed_simulated_feeds(db)
    admin = user
    watch_added = seed_watchlist(db, admin.user_id)
    audit_svc.record(
        db, "STREAM_SEED_SIM", "stream_catalogue", None,
        after_state={**streams, "watchlist_seeded": watch_added},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"data": {**streams, "watchlist_seeded": watch_added}, "meta": {}, "requestId": request_id_var.get()}
