"""Audit log read endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_perm
from app.core.errors import request_id_var
from app.models.audit import AuditEvent

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def list_audit(
    page: int = 1,
    page_size: int = 50,
    action: str | None = None,
    actor: str | None = None,
    resource_type: str | None = None,
    user=Depends(require_perm("audit", "read")),
    db: Session = Depends(get_db),
):
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    stmt = select(AuditEvent)
    if action:
        stmt = stmt.where(AuditEvent.action == action.upper())
    if actor:
        stmt = stmt.where(AuditEvent.actor_label.ilike(f"%{actor}%"))
    if resource_type:
        stmt = stmt.where(AuditEvent.resource_type == resource_type.upper())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(AuditEvent.occurred_at.desc()).limit(page_size).offset((page - 1) * page_size)
    ).scalars().all()
    return {
        "data": [
            {
                "audit_event_id": e.audit_event_id,
                "actor_label": e.actor_label,
                "action": e.action,
                "resource_type": e.resource_type,
                "resource_id": e.resource_id,
                "request_id": e.request_id,
                "ip_address": e.ip_address,
                "before_state": e.before_state,
                "after_state": e.after_state,
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
            }
            for e in rows
        ],
        "meta": {"page": page, "pageSize": page_size, "total": total},
        "requestId": request_id_var.get(),
    }
