"""Module 3 federation API: VMS registry CRUD + discovery triggers."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_perm
from app.core.errors import SentinelError, request_id_var
from app.models.federation import VmsSystem
from app.models.user import User
from app.services import audit as audit_svc
from app.services import federation

router = APIRouter(prefix="/vms", tags=["federation"])


def _out(v: VmsSystem) -> dict:
    return {
        "vms_id": v.vms_id,
        "name": v.name,
        "vendor": v.vendor,
        "adapter_kind": v.adapter_kind,
        "base_url": v.base_url,
        # env-var NAMES only - never values (SEC-004)
        "auth_env_keys": v.auth_env_keys or [],
        "capabilities": v.capabilities or [],
        "status": v.status,
        "last_discovered_at": v.last_discovered_at.isoformat() if v.last_discovered_at else None,
        "last_error": v.last_error,
        "enabled": v.enabled,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


class VmsCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    vendor: str = Field(min_length=1, max_length=120)
    adapter_kind: str
    base_url: str | None = None
    auth_env_keys: list[str] = []
    enabled: bool = True


class VmsPatch(BaseModel):
    base_url: str | None = None
    auth_env_keys: list[str] | None = None
    enabled: bool | None = None
    vendor: str | None = Field(default=None, max_length=120)


@router.get("")
def list_vms(user: User = Depends(require_perm("camera", "read")), db: Session = Depends(get_db)):
    rows = db.scalars(select(VmsSystem).order_by(VmsSystem.name)).all()
    return {"data": [_out(v) for v in rows], "meta": {"total": len(rows), "adapter_kinds": federation.adapter_kinds()}, "requestId": request_id_var.get()}


@router.post("")
def register_vms(
    body: VmsCreate,
    request: Request,
    user: User = Depends(require_perm("user", "manage")),
    db: Session = Depends(get_db),
):
    if body.adapter_kind not in federation.adapter_kinds():
        raise SentinelError("VMS_ADAPTER_UNKNOWN", f"adapter_kind must be one of {federation.adapter_kinds()}", 422)
    if db.scalar(select(VmsSystem).where(VmsSystem.name == body.name.strip())):
        raise SentinelError("VMS_NAME_TAKEN", "A VMS with this name is already registered", 409)
    v = VmsSystem(
        name=body.name.strip(),
        vendor=body.vendor.strip(),
        adapter_kind=body.adapter_kind,
        base_url=(body.base_url or "").strip() or None,
        auth_env_keys=[str(k) for k in body.auth_env_keys],
        capabilities=list(federation.CORE_CAPABILITIES),
        enabled=body.enabled,
    )
    db.add(v)
    db.flush()
    audit_svc.record(
        db, "VMS_REGISTER", "vms_system", v.vms_id,
        after_state={"name": v.name, "adapter_kind": v.adapter_kind},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"data": _out(v), "meta": {}, "requestId": request_id_var.get()}


@router.patch("/{vms_id}")
def patch_vms(
    vms_id: str,
    body: VmsPatch,
    request: Request,
    user: User = Depends(require_perm("user", "manage")),
    db: Session = Depends(get_db),
):
    v = db.get(VmsSystem, vms_id)
    if not v:
        raise SentinelError("VMS_NOT_FOUND", "VMS not found", 404)
    if body.base_url is not None:
        v.base_url = body.base_url.strip() or None
    if body.auth_env_keys is not None:
        v.auth_env_keys = [str(k) for k in body.auth_env_keys]
    if body.enabled is not None:
        v.enabled = body.enabled
        if not body.enabled:
            # Federation semantics: disabling an adapter pulls its feeds from
            # the platform (streams stay for audit; re-discovery restores them).
            from app.models.module2 import StreamSource as _SS

            for s in db.scalars(select(_SS).where(_SS.vms_system == v.name)).all():
                s.enabled = False
    if body.vendor is not None:
        v.vendor = body.vendor.strip()
    audit_svc.record(
        db, "VMS_UPDATE", "vms_system", vms_id,
        after_state={"enabled": v.enabled, "base_url": v.base_url},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"data": _out(v), "meta": {}, "requestId": request_id_var.get()}


@router.delete("/{vms_id}")
def delete_vms(
    vms_id: str,
    request: Request,
    user: User = Depends(require_perm("user", "manage")),
    db: Session = Depends(get_db),
):
    v = db.get(VmsSystem, vms_id)
    if not v:
        raise SentinelError("VMS_NOT_FOUND", "VMS not found", 404)
    # Federation semantics: unregistering an adapter pulls its feeds from the
    # platform (streams are disabled, not deleted - audit trail is preserved;
    # re-registering + re-discovering restores them).
    from app.models.module2 import StreamSource as _SS

    for s in db.scalars(select(_SS).where(_SS.vms_system == v.name)).all():
        s.enabled = False
    audit_svc.record(
        db, "VMS_DELETE", "vms_system", vms_id,
        before_state={"name": v.name, "adapter_kind": v.adapter_kind},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=request.client.host if request.client else None,
    )
    db.delete(v)
    db.commit()
    return {"data": {"vms_id": vms_id}, "meta": {}, "requestId": request_id_var.get()}


@router.post("/{vms_id}/discover")
def discover_one(
    vms_id: str,
    request: Request,
    user: User = Depends(require_perm("camera", "write")),
    db: Session = Depends(get_db),
):
    v = db.get(VmsSystem, vms_id)
    if not v:
        raise SentinelError("VMS_NOT_FOUND", "VMS not found", 404)
    result = federation.discover_vms(db, v)
    audit_svc.record(
        db, "VMS_DISCOVER", "vms_system", vms_id,
        after_state={"ok": result.get("ok")},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=request.client.host if request.client else None,
    )
    return {"data": result, "meta": {}, "requestId": request_id_var.get()}


@router.post("/discover-all")
def discover_all(request: Request, user: User = Depends(require_perm("camera", "write")), db: Session = Depends(get_db)):
    result = federation.sync_all_vms(db)
    audit_svc.record(
        db, "VMS_DISCOVER_ALL", "vms_registry", None,
        after_state={"vms_count": len(result.get("results", []))},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=request.client.host if request.client else None,
    )
    return {"data": result, "meta": {}, "requestId": request_id_var.get()}


@router.get("/capabilities")
def capabilities(user: User = Depends(require_perm("camera", "read")), db: Session = Depends(get_db)):
    """TRD §13: connectors declare what they support."""
    rows = db.scalars(select(VmsSystem)).all()
    return {
        "data": [{"vms_id": v.vms_id, "name": v.name, "capabilities": v.capabilities or []} for v in rows],
        "meta": {}, "requestId": request_id_var.get(),
    }
