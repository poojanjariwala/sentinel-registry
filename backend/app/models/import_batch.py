from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.department import uuid_pk


class CameraImportBatch(Base, TimestampMixin):
    __tablename__ = "camera_import_batches"

    batch_id: Mapped[str] = uuid_pk()
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(36), nullable=False)
    dry_run: Mapped[bool] = mapped_column(default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="COMPLETED", nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    report_json: Mapped[dict | None] = mapped_column("report", JSONB)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
