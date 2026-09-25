from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator


def _iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


class ORTIMixin(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", mode="wrap")
    def _ser(self, value: Any, handler, info):
        if isinstance(value, datetime):
            return _iso_z(value)
        return handler(value)


class Page(BaseModel):
    page: int = 1
    pageSize: int = 50
    total: int = 0


def page_envelope(items: list, page: int, page_size: int, total: int) -> dict:
    return {
        "data": items,
        "meta": {"page": page, "pageSize": page_size, "total": total},
        "requestId": None,
    }


def set_request_id(envelope: dict) -> dict:
    from app.core.errors import request_id_var

    envelope["requestId"] = request_id_var.get()
    return envelope
