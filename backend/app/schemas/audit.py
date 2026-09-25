from pydantic import BaseModel

from app.schemas.common import ORTIMixin


class AuditEventOut(ORTIMixin):
    audit_event_id: str
    actor_user_id: str | None = None
    actor_label: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    request_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    before_state: dict | None = None
    after_state: dict | None = None
    reason: str | None = None
    occurred_at: str | None = None
