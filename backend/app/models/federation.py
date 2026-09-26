"""Module 3 models: VMS federation & middleware (adapter registry)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.department import uuid_pk


class VmsSystem(Base, TimestampMixin):
    """A registered departmental VMS / camera source system (PRD §12-13, TRD 5.3).

    Federation over replacement: each department keeps its own VMS; this row
    is the adapter registration that declares how the platform talks to it
    (adapter kind, endpoint, credential env-var reference) and what the
    connector can do (capabilities JSON). Credentials are never stored here -
    only the NAMES of env vars, resolved at runtime (SEC-004).
    """

    __tablename__ = "vms_systems"

    vms_id: Mapped[str] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    vendor: Mapped[str] = mapped_column(String(120), nullable=False)
    adapter_kind: Mapped[str] = mapped_column(String(40), nullable=False)  # grid|generic_hls|mock
    base_url: Mapped[str | None] = mapped_column(Text)
    auth_env_keys: Mapped[list | None] = mapped_column(JSONB)  # ["GRID_EMAIL","GRID_PASSWORD"]
    capabilities: Mapped[list | None] = mapped_column(JSONB)  # TRD §13 capability list
    status: Mapped[str] = mapped_column(String(20), default="UNKNOWN", nullable=False)  # ONLINE|OFFLINE|UNKNOWN
    last_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
