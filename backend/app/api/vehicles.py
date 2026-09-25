"""Module 2 analytics API: vehicle search, events, watchlist, alerts."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_perm
from app.core.errors import SentinelError, request_id_var
from app.models.camera import Camera
from app.models.module2 import (
    StreamAlert, StreamSource, TaggedEvent, VehicleObservation, WatchlistVehicle,
)
from app.models.user import User
from app.services import audit as audit_svc
from app.services.camera_service import user_department_filter
from app.services.stream_service import normalize_plate

router = APIRouter(tags=["analytics"])


@router.get("/vehicles/search")
def vehicle_search(
    plate: str,
    hours: int = 24,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(require_perm("camera", "read")),
    db: Session = Depends(get_db),
):
    """Searchable vehicle-movement records: exact-normalized match first, then LIKE."""
    norm = normalize_plate(plate)
    if not norm:
        raise SentinelError("VALIDATION_ERROR", "plate is required", 400)
    since = datetime.now(timezone.utc) - timedelta(hours=max(1, min(hours, 24 * 30)))
    page = max(1, page)
    page_size = min(max(1, page_size), 200)

    stmt = (
        select(VehicleObservation, StreamSource.label, StreamSource.vms_system,
               Camera.name, Camera.district, Camera.latitude, Camera.longitude)
        .join(StreamSource, VehicleObservation.stream_id == StreamSource.stream_id)
        .join(Camera, VehicleObservation.camera_id == Camera.camera_id)
        .where(VehicleObservation.captured_at >= since)
        .order_by(VehicleObservation.captured_at.desc())
    )
    flt = user_department_filter(user, db)
    if flt is not None:
        stmt = stmt.where(flt)

    exact = stmt.where(VehicleObservation.plate_normalized == norm)
    total = db.scalar(select(func.count()).select_from(exact.subquery())) or 0
    mode = "exact"
    if total == 0 and len(norm) >= 4:
        stmt = stmt.where(VehicleObservation.plate_normalized.like(f"%{norm[-4:]}%"))
        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        mode = "partial-last4"
    rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).all()

    data = [
        {
            "observation_id": o.observation_id,
            "captured_at": o.captured_at.isoformat(),
            "plate_raw": o.plate_raw,
            "plate_normalized": o.plate_normalized,
            "vehicle_class": o.vehicle_class,
            "speed_kmph": o.speed_kmph,
            "confidence": o.confidence,
            "engine": o.engine,
            "stream_id": o.stream_id,
            "stream_label": label,
            "vms_system": vms,
            "camera_name": cname,
            "district": dist,
            "location": [lat, lng] if lat is not None else None,
            "meta": o.meta,
        }
        for (o, label, vms, cname, dist, lat, lng) in rows
    ]
    return {
        "data": data,
        "meta": {"query": norm, "mode": mode, "page": page, "pageSize": page_size, "total": total},
        "requestId": request_id_var.get(),
    }


@router.get("/vehicles/{plate}/timeline")
def vehicle_timeline(plate: str, hours: int = 24, user: User = Depends(require_perm("camera", "read")), db: Session = Depends(get_db)):
    r = vehicle_search(plate=plate, hours=hours, page=1, page_size=200, user=user, db=db)
    obs = list(reversed(r["data"]))  # chronological
    movements = []
    for prev, cur in zip(obs, obs[1:]):
        t0 = datetime.fromisoformat(prev["captured_at"])
        t1 = datetime.fromisoformat(cur["captured_at"])
        movements.append({
            "from": {"at": prev["captured_at"], "camera": prev["camera_name"], "district": prev["district"]},
            "to": {"at": cur["captured_at"], "camera": cur["camera_name"], "district": cur["district"]},
            "gap_seconds": int((t1 - t0).total_seconds()),
        })
    return {"data": {"plate": r["meta"]["query"], "mode": r["meta"]["mode"], "sightings": obs, "movements": movements},
            "meta": {"total": r["meta"]["total"]}, "requestId": request_id_var.get()}


@router.get("/events")
def list_events(
    hours: int = 6,
    event_type: str | None = None,
    stream_id: str | None = None,
    severity: str | None = None,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(require_perm("camera", "read")),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(hours=max(1, min(hours, 168)))
    stmt = (
        select(TaggedEvent, StreamSource.label, Camera.name, Camera.district)
        .join(StreamSource, TaggedEvent.stream_id == StreamSource.stream_id)
        .join(Camera, TaggedEvent.camera_id == Camera.camera_id)
        .where(TaggedEvent.occurred_at >= since)
        .order_by(TaggedEvent.occurred_at.desc())
    )
    flt = user_department_filter(user, db)
    if flt is not None:
        stmt = stmt.where(flt)
    if event_type:
        stmt = stmt.where(TaggedEvent.event_type == event_type.upper())
    if stream_id:
        stmt = stmt.where(TaggedEvent.stream_id == stream_id)
    if severity:
        stmt = stmt.where(TaggedEvent.severity == severity.upper())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.limit(min(page_size, 200)).offset((page - 1) * page_size)).all()
    return {
        "data": [
            {
                "event_id": e.event_id, "event_type": e.event_type, "label": e.label,
                "severity": e.severity, "occurred_at": e.occurred_at.isoformat(),
                "stream_id": e.stream_id, "stream_label": slabel,
                "camera_name": cname, "district": dist,
                "observation_id": e.observation_id, "meta": e.meta,
            }
            for (e, slabel, cname, dist) in rows
        ],
        "meta": {"page": page, "pageSize": page_size, "total": total},
        "requestId": request_id_var.get(),
    }


@router.post("/events")
def create_event(
    body: dict,
    request: Request,
    user: User = Depends(require_perm("camera", "write")),
    db: Session = Depends(get_db),
):
    s = db.get(StreamSource, body.get("stream_id") or "")
    if not s:
        raise SentinelError("STREAM_NOT_FOUND", "stream_id not found", 404)
    now = datetime.now(timezone.utc)
    evt = TaggedEvent(
        stream_id=s.stream_id, camera_id=s.camera_id,
        observation_id=body.get("observation_id"),
        event_type=str(body.get("event_type") or "CUSTOM").upper(),
        label=str(body.get("label") or "Operator tag"),
        occurred_at=now,
        severity=str(body.get("severity") or "INFO").upper(),
        created_by=user.user_id, meta=body.get("meta"),
    )
    db.add(evt)
    db.flush()
    audit_svc.record(
        db, "EVENT_TAG_CREATE", "tagged_event", evt.event_id,
        after_state={"event_type": evt.event_type, "label": evt.label, "stream_id": evt.stream_id},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"data": {"event_id": evt.event_id, "label": evt.label}, "meta": {}, "requestId": request_id_var.get()}


@router.get("/watchlist")
def list_watch(user: User = Depends(require_perm("camera", "read")), db: Session = Depends(get_db)):
    rows = db.execute(select(WatchlistVehicle).order_by(WatchlistVehicle.created_at.desc())).scalars().all()
    return {
        "data": [
            {
                "watch_id": w.watch_id, "plate_normalized": w.plate_normalized,
                "reason": w.reason, "severity": w.severity, "owner_hint": w.owner_hint,
                "valid_until": w.valid_until.isoformat() if w.valid_until else None,
                "created_at": w.created_at.isoformat(),
            }
            for w in rows
        ],
        "meta": {"total": len(rows)}, "requestId": request_id_var.get(),
    }


@router.post("/watchlist")
def add_watch(
    body: dict,
    request: Request,
    user: User = Depends(require_perm("camera", "write")),
    db: Session = Depends(get_db),
):
    plate = normalize_plate(str(body.get("plate") or ""))
    if len(plate) < 6:
        raise SentinelError("VALIDATION_ERROR", "plate must be at least 6 characters", 422)
    if db.execute(select(WatchlistVehicle).where(WatchlistVehicle.plate_normalized == plate)).scalar_one_or_none():
        raise SentinelError("WATCH_EXISTS", "Plate already on watchlist", 409)
    w = WatchlistVehicle(
        plate_normalized=plate,
        reason=str(body.get("reason") or "Operator added"),
        severity=str(body.get("severity") or "HIGH").upper(),
        owner_hint=body.get("owner_hint"),
        created_by=user.user_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(w)
    db.flush()
    audit_svc.record(
        db, "WATCHLIST_ADD", "watchlist_vehicle", w.watch_id,
        after_state={"plate": plate, "severity": w.severity, "reason": w.reason},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"data": {"watch_id": w.watch_id, "plate_normalized": plate}, "meta": {}, "requestId": request_id_var.get()}


@router.delete("/watchlist/{watch_id}")
def remove_watch(watch_id: str, request: Request, user: User = Depends(require_perm("camera", "write")), db: Session = Depends(get_db)):
    w = db.get(WatchlistVehicle, watch_id)
    if not w:
        raise SentinelError("WATCH_NOT_FOUND", "Watchlist entry not found", 404)
    audit_svc.record(
        db, "WATCHLIST_REMOVE", "watchlist_vehicle", watch_id,
        before_state={"plate": w.plate_normalized},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=request.client.host if request.client else None,
    )
    db.delete(w)
    db.commit()
    return {"data": {"ok": True}, "meta": {}, "requestId": request_id_var.get()}


@router.get("/alerts")
def list_alerts(
    status: str | None = None,
    hours: int = 24,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(require_perm("camera", "read")),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(hours=max(1, min(hours, 24 * 7)))
    stmt = (
        select(StreamAlert, StreamSource.label, Camera.name, Camera.district)
        .join(StreamSource, StreamAlert.stream_id == StreamSource.stream_id)
        .join(Camera, StreamAlert.camera_id == Camera.camera_id)
        .where(StreamAlert.raised_at >= since)
        .order_by(StreamAlert.raised_at.desc())
    )
    flt = user_department_filter(user, db)
    if flt is not None:
        stmt = stmt.where(flt)
    if status:
        stmt = stmt.where(StreamAlert.status == status.upper())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.limit(min(page_size, 200)).offset((page - 1) * page_size)).all()
    return {
        "data": [
            {
                "alert_id": a.alert_id, "plate_normalized": a.plate_normalized,
                "severity": a.severity, "status": a.status,
                "raised_at": a.raised_at.isoformat(),
                "stream_id": a.stream_id, "stream_label": slabel,
                "camera_name": cname, "district": dist,
                "ack_by": a.ack_by, "ack_at": a.ack_at.isoformat() if a.ack_at else None,
                "note": a.note, "observation_id": a.observation_id,
            }
            for (a, slabel, cname, dist) in rows
        ],
        "meta": {"page": page, "pageSize": page_size, "total": total},
        "requestId": request_id_var.get(),
    }


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: str, request: Request, user: User = Depends(require_perm("camera", "write")), db: Session = Depends(get_db)):
    a = db.get(StreamAlert, alert_id)
    if not a:
        raise SentinelError("ALERT_NOT_FOUND", "Alert not found", 404)
    a.status = "ACK"
    a.ack_by = user.user_id
    a.ack_at = datetime.now(timezone.utc)
    audit_svc.record(
        db, "ALERT_ACK", "stream_alert", alert_id,
        after_state={"status": "ACK", "plate": a.plate_normalized},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"data": {"alert_id": a.alert_id, "status": a.status}, "meta": {}, "requestId": request_id_var.get()}


@router.post("/alerts/{alert_id}/close")
def close_alert(alert_id: str, request: Request, user: User = Depends(require_perm("camera", "write")), db: Session = Depends(get_db)):
    a = db.get(StreamAlert, alert_id)
    if not a:
        raise SentinelError("ALERT_NOT_FOUND", "Alert not found", 404)
    a.status = "CLOSED"
    a.ack_by = user.user_id
    a.ack_at = datetime.now(timezone.utc)
    audit_svc.record(
        db, "ALERT_CLOSE", "stream_alert", alert_id,
        after_state={"status": "CLOSED", "plate": a.plate_normalized},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"data": {"alert_id": a.alert_id, "status": a.status}, "meta": {}, "requestId": request_id_var.get()}
