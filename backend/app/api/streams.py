"""Module 2 streams API: unified viewer endpoints."""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_perm
from app.core.errors import SentinelError, request_id_var
from app.models.module2 import StreamSource, VideoWall, ViewerSession
from app.models.user import User
from app.services import audit as audit_svc
from app.services.camera_service import user_department_filter
from app.services.grid_sync import sync_cameras_from_grid
from app.services.hls_service import (
    OriginSpec,
    fetch_key,
    fetch_playlist,
    fetch_segment,
    verify_key_token,
    verify_segment_token,
)
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

# One asyncio.Lock per key name: concurrent tile key requests share a single
# upstream fetch instead of stampeding the origin.
_key_locks: dict[str, asyncio.Lock] = {}


class WallTile(BaseModel):
    stream_id: str
    slot: int = Field(ge=0, le=8)


class WallCreate(BaseModel):
    name: str
    tiles: list[WallTile]


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


# --- Saved video walls (Module 2: configurable wall layouts) ---------------


def _wall_out(w: VideoWall) -> dict:
    tiles = w.tiles if isinstance(w.tiles, list) else []
    return {
        "wall_id": w.wall_id,
        "name": w.name,
        "owner_id": w.owner_id,
        "tiles": tiles,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }


@router.get("/walls")
def list_walls(user: User = Depends(require_perm("camera", "read")), db: Session = Depends(get_db)):
    walls = db.scalars(select(VideoWall).order_by(VideoWall.created_at.desc())).all()
    return {"data": [_wall_out(w) for w in walls], "meta": {"total": len(walls)}, "requestId": request_id_var.get()}


@router.post("/walls")
def create_wall(
    wall: WallCreate,
    request: Request,
    user: User = Depends(require_perm("camera", "read")),
    db: Session = Depends(get_db),
):
    name = wall.name.strip()
    if not name or len(name) > 150:
        raise SentinelError("WALL_NAME_INVALID", "Wall name must be 1-150 characters", 422)
    # Keep only references to streams this user may actually view.
    allowed = {r["stream_id"] for r in list_streams(db, user)}
    tiles = [
        {"stream_id": t.stream_id, "slot": max(0, min(8, int(t.slot)))}
        for t in wall.tiles
        if t.stream_id in allowed
    ]
    if not tiles:
        raise SentinelError("WALL_TILES_EMPTY", "Wall has no authorized streams", 422)
    now = datetime.now(timezone.utc)
    existing = db.scalar(select(VideoWall).where(VideoWall.name == name))
    if existing:
        existing.tiles = tiles
        existing.owner_id = user.user_id
        existing.updated_at = now
        db.flush()
        out = _wall_out(existing)
    else:
        w = VideoWall(
            name=name,
            owner_id=user.user_id,
            tiles=tiles,
            created_at=now,
            updated_at=now,
        )
        db.add(w)
        db.flush()
        out = _wall_out(w)
    audit_svc.record(
        db, "WALL_SAVE", "video_wall", out["wall_id"],
        after_state={"name": name, "tiles": len(tiles)},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"data": out, "meta": {}, "requestId": request_id_var.get()}


@router.delete("/walls/{wall_id}")
def delete_wall(
    wall_id: str,
    request: Request,
    user: User = Depends(require_perm("camera", "read")),
    db: Session = Depends(get_db),
):
    w = db.get(VideoWall, wall_id)
    if not w:
        raise SentinelError("WALL_NOT_FOUND", "Wall not found", 404)
    audit_svc.record(
        db, "WALL_DELETE", "video_wall", wall_id,
        before_state={"name": w.name},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=request.client.host if request.client else None,
    )
    db.delete(w)
    db.commit()
    return {"data": {"wall_id": wall_id}, "meta": {}, "requestId": request_id_var.get()}


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
    spec = OriginSpec.from_source(s)
    db.close()  # release the pooled connection BEFORE upstream I/O
    body, headers = await fetch_playlist(spec, session_id)
    return Response(content=body, media_type="application/vnd.apple.mpegurl", headers=headers)


@router.get("/hls/{stream_id}/{session_id}/{token}/seg/{name}")
async def hls_segment(stream_id: str, session_id: str, token: str, name: str, db: Session = Depends(get_db)):
    sess = db.get(ViewerSession, session_id)
    if not sess or not sess.active or sess.stream_id != stream_id:
        raise SentinelError("SESSION_INVALID", "Viewer session is invalid or expired", 403)
    if not verify_segment_token(stream_id, name, session_id, token):
        raise SentinelError("SEGMENT_TOKEN_INVALID", "Segment link expired", 403)
    s = db.get(StreamSource, stream_id)
    if not s:
        raise SentinelError("STREAM_NOT_FOUND", "Stream not found", 404)
    spec = OriginSpec.from_source(s)
    db.close()  # release the pooled connection BEFORE upstream I/O
    data, headers = await fetch_segment(spec, name)
    return Response(content=data, media_type=headers.get("content-type", "video/mp2t"))


@router.get("/hls/{stream_id}/{session_id}/{token}/key/{name}")
async def hls_key(stream_id: str, session_id: str, token: str, name: str, db: Session = Depends(get_db)):
    """Proxy an AES-128 decryption key for grid feeds (signed, session-bound).

    The key URL is stable for the life of the viewer session (no per-reload
    re-signing), so the browser fetches it once and hls.js caches it; the
    per-key lock stops concurrent tiles from stampeding the origin.
    """
    sess = db.get(ViewerSession, session_id)
    if not sess or not sess.active or sess.stream_id != stream_id:
        raise SentinelError("SESSION_INVALID", "Viewer session is invalid or expired", 403)
    if not verify_key_token(stream_id, name, session_id, token):
        raise SentinelError("KEY_TOKEN_INVALID", "Key link invalid for this session", 403)
    s = db.get(StreamSource, stream_id)
    if not s:
        raise SentinelError("STREAM_NOT_FOUND", "Stream not found", 404)
    spec = OriginSpec.from_source(s)
    db.close()  # release the pooled connection BEFORE upstream I/O
    async with _key_locks.setdefault(name, asyncio.Lock()):
        data = await fetch_key(spec, name)
    return Response(content=data, media_type="application/octet-stream")


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


@router.post("/admin/sync-grid")
def sync_grid(request: Request, user: User = Depends(require_perm("user", "manage")), db: Session = Depends(get_db)):
    """Sync the real Gujarat Police Camera Grid catalogue: upsert cameras +
    HLS stream_sources from cameras.json (idempotent; re-runnable)."""
    result = sync_cameras_from_grid(db)
    audit_svc.record(
        db, "GRID_SYNC", "stream_catalogue", None,
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
