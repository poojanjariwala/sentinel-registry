"""Audit service - append-only event recording for sensitive actions."""

import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import request_id_var
from app.models.audit import AuditEvent


def record(
    db: Session,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
    reason: str | None = None,
    actor_user_id: str | None = None,
    actor_label: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditEvent:
    """Record an audit event on the caller's session (committed with the request)."""
    rid = request_id_var.get()
    now = datetime.now(timezone.utc).isoformat()

    db.execute(
        text(
            "INSERT INTO audit_events (audit_event_id, actor_user_id, actor_label, action, resource_type, resource_id,"
            " request_id, ip_address, user_agent, before_state, after_state, reason, occurred_at)"
            " VALUES (:id, :actor, :label, :action, :rtype, :rid_res, :rid, :ip, :ua, :before, :after, :reason, :at)"
        ),
        {
            "id": str(uuid4()),
            "actor": actor_user_id,
            "label": actor_label,
            "action": action,
            "rtype": resource_type,
            "rid_res": resource_id,
            "rid": rid,
            "ip": ip_address,
            "ua": user_agent,
            "before": json.dumps(before_state or {}),
            "after": json.dumps(after_state or {}),
            "reason": reason,
            "at": now,
        },
    )
    return None
