from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.department import uuid_pk


class GapAnalysisRun(Base, TimestampMixin):
    __tablename__ = "gap_analysis_runs"

    run_id: Mapped[str] = uuid_pk()
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    params_json: Mapped[dict] = mapped_column("params", JSONB, nullable=False)
    summary_json: Mapped[dict] = mapped_column("summary", JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="COMPLETED", nullable=False)
    camera_count_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uncovered_hex_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
