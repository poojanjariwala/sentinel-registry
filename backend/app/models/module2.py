"""Module 2 models: unified viewing, streams, ANPR metadata, alerts, walls."""

from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.department import uuid_pk


class StreamSource(Base, TimestampMixin):
    """One ingest source exposed by a departmental VMS/simulator.

    module2: viewing layer reads the Module-1 camera registry for ownership.
    """

    __tablename__ = "stream_sources"
    __table_args__ = (
        Index("ix_stream_sources_camera", "camera_id"),
        Index("ix_stream_sources_protocol", "protocol"),
    )

    stream_id: Mapped[str] = uuid_pk()
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.camera_id"), nullable=False)
    label: Mapped[str] = mapped_column(String(150), nullable=False)
    protocol: Mapped[str] = mapped_column(String(20), nullable=False)  # HLS | RTSP | ONVIF | SIM
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    vms_system: Mapped[str] = mapped_column(String(120), nullable=False, default="UNKNOWN")
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.department_id"), nullable=False)
    is_live: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="UNKNOWN", nullable=False)  # ONLINE/OFFLINE/UNKNOWN
    last_probe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    analytics_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Optional per-source origin auth (cookie/bearer/headers). Grid feeds keep
    # credentials centrally in grid_client instead; this is for other VMSes.
    auth_json: Mapped[dict | None] = mapped_column("auth_json", JSONB, nullable=True)


class StreamHealthEvent(Base):
    """Health probe result per stream (kept short, append-only)."""

    __tablename__ = "stream_health_events"
    __table_args__ = (Index("ix_stream_health_stream_time", "stream_id", "checked_at"),)

    id: Mapped[str] = uuid_pk()
    stream_id: Mapped[str] = mapped_column(ForeignKey("stream_sources.stream_id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ViewerSession(Base):
    """A user watching a stream right now (audit + concurrency limits)."""

    __tablename__ = "viewer_sessions"
    __table_args__ = (Index("ix_viewer_sessions_active", "active"),)

    session_id: Mapped[str] = uuid_pk()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    stream_id: Mapped[str] = mapped_column(ForeignKey("stream_sources.stream_id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class VehicleObservation(Base):
    """ANPR/vehicle detection output (selective metadata, no central video)."""

    __tablename__ = "vehicle_observations"
    __table_args__ = (
        Index("ix_vehicle_obs_plate_time", "plate_normalized", "captured_at"),
        Index("ix_vehicle_obs_stream_time", "stream_id", "captured_at"),
        Index("ix_vehicle_obs_plate_raw", "plate_raw"),
    )

    observation_id: Mapped[str] = uuid_pk()
    stream_id: Mapped[str] = mapped_column(ForeignKey("stream_sources.stream_id"), nullable=False)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.camera_id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    plate_raw: Mapped[str] = mapped_column(String(40), nullable=False)
    plate_normalized: Mapped[str] = mapped_column(String(40), nullable=False)
    vehicle_class: Mapped[str | None] = mapped_column(String(40))
    speed_kmph: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    engine: Mapped[str] = mapped_column(String(20), default="simulated", nullable=False)
    snapshot_hint: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSONB)


class TaggedEvent(Base):
    """Operator/AI-tagged event on a stream, camera-wise indexed."""

    __tablename__ = "tagged_events"
    __table_args__ = (
        Index("ix_tagged_events_stream_time", "stream_id", "occurred_at"),
        Index("ix_tagged_events_type", "event_type"),
    )

    event_id: Mapped[str] = uuid_pk()
    stream_id: Mapped[str] = mapped_column(ForeignKey("stream_sources.stream_id"), nullable=False)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.camera_id"), nullable=False)
    observation_id: Mapped[str | None] = mapped_column(ForeignKey("vehicle_observations.observation_id"))
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)  # ANPR | LOITERING | WRONG_SIDE | CUSTOM
    label: Mapped[str] = mapped_column(String(150), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="INFO", nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(36))
    meta: Mapped[dict | None] = mapped_column(JSONB)


class WatchlistVehicle(Base):
    """Vehicles of interest (demo data; VAHAN/CCTNS adapter is a future drop-in)."""

    __tablename__ = "watchlist_vehicles"

    watch_id: Mapped[str] = uuid_pk()
    plate_normalized: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="HIGH", nullable=False)
    owner_hint: Mapped[str | None] = mapped_column(String(150))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StreamAlert(Base):
    """Alert generated when a watchlist vehicle is observed (or manual)."""

    __tablename__ = "stream_alerts"
    __table_args__ = (
        Index("ix_stream_alerts_status_time", "status", "raised_at"),
        Index("ix_stream_alerts_plate", "plate_normalized"),
    )

    alert_id: Mapped[str] = uuid_pk()
    observation_id: Mapped[str] = mapped_column(ForeignKey("vehicle_observations.observation_id"), nullable=False)
    watch_id: Mapped[str] = mapped_column(ForeignKey("watchlist_vehicles.watch_id"), nullable=False)
    plate_normalized: Mapped[str] = mapped_column(String(40), nullable=False)
    stream_id: Mapped[str] = mapped_column(ForeignKey("stream_sources.stream_id"), nullable=False)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.camera_id"), nullable=False)
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", nullable=False)  # OPEN/ACK/CLOSED
    ack_by: Mapped[str | None] = mapped_column(String(36))
    ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class VideoWall(Base):
    """Saved multi-camera grid layout (configurable video walls)."""

    __tablename__ = "video_walls"

    wall_id: Mapped[str] = uuid_pk()
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String(36))
    tiles: Mapped[dict] = mapped_column(JSONB, nullable=False)  # [{stream_id, slot}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
