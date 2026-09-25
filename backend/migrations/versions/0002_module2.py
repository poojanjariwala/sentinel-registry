"""Migration 0002: Module 2 - unified viewing, ANPR metadata, alerts, walls."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_module2"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stream_sources",
        sa.Column("stream_id", sa.String(36), primary_key=True),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.camera_id"), nullable=False),
        sa.Column("label", sa.String(150), nullable=False),
        sa.Column("protocol", sa.String(20), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("vms_system", sa.String(120), nullable=False, server_default="UNKNOWN"),
        sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.department_id"), nullable=False),
        sa.Column("is_live", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(20), nullable=False, server_default="UNKNOWN"),
        sa.Column("last_probe_at", sa.DateTime(timezone=True)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("analytics_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_stream_sources_camera", "stream_sources", ["camera_id"])
    op.create_index("ix_stream_sources_protocol", "stream_sources", ["protocol"])

    op.create_table(
        "stream_health_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("stream_id", sa.String(36), sa.ForeignKey("stream_sources.stream_id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("detail", sa.Text()),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stream_health_stream_time", "stream_health_events", ["stream_id", "checked_at"])

    op.create_table(
        "viewer_sessions",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("stream_id", sa.String(36), sa.ForeignKey("stream_sources.stream_id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_viewer_sessions_active", "viewer_sessions", ["active"])

    op.create_table(
        "vehicle_observations",
        sa.Column("observation_id", sa.String(36), primary_key=True),
        sa.Column("stream_id", sa.String(36), sa.ForeignKey("stream_sources.stream_id"), nullable=False),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.camera_id"), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("plate_raw", sa.String(40), nullable=False),
        sa.Column("plate_normalized", sa.String(40), nullable=False),
        sa.Column("vehicle_class", sa.String(40)),
        sa.Column("speed_kmph", sa.Float()),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("engine", sa.String(20), nullable=False, server_default="simulated"),
        sa.Column("snapshot_hint", sa.Text()),
        sa.Column("meta", JSONB),
    )
    op.create_index("ix_vehicle_obs_plate_time", "vehicle_observations", ["plate_normalized", "captured_at"])
    op.create_index("ix_vehicle_obs_stream_time", "vehicle_observations", ["stream_id", "captured_at"])
    op.create_index("ix_vehicle_obs_plate_raw", "vehicle_observations", ["plate_raw"])

    op.create_table(
        "tagged_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("stream_id", sa.String(36), sa.ForeignKey("stream_sources.stream_id"), nullable=False),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.camera_id"), nullable=False),
        sa.Column("observation_id", sa.String(36), sa.ForeignKey("vehicle_observations.observation_id")),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("label", sa.String(150), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="INFO"),
        sa.Column("created_by", sa.String(36)),
        sa.Column("meta", JSONB),
    )
    op.create_index("ix_tagged_events_stream_time", "tagged_events", ["stream_id", "occurred_at"])
    op.create_index("ix_tagged_events_type", "tagged_events", ["event_type"])

    op.create_table(
        "watchlist_vehicles",
        sa.Column("watch_id", sa.String(36), primary_key=True),
        sa.Column("plate_normalized", sa.String(40), nullable=False, unique=True),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="HIGH"),
        sa.Column("owner_hint", sa.String(150)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "stream_alerts",
        sa.Column("alert_id", sa.String(36), primary_key=True),
        sa.Column("observation_id", sa.String(36), sa.ForeignKey("vehicle_observations.observation_id"), nullable=False),
        sa.Column("watch_id", sa.String(36), sa.ForeignKey("watchlist_vehicles.watch_id"), nullable=False),
        sa.Column("plate_normalized", sa.String(40), nullable=False),
        sa.Column("stream_id", sa.String(36), sa.ForeignKey("stream_sources.stream_id"), nullable=False),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.camera_id"), nullable=False),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("ack_by", sa.String(36)),
        sa.Column("ack_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text()),
    )
    op.create_index("ix_stream_alerts_status_time", "stream_alerts", ["status", "raised_at"])
    op.create_index("ix_stream_alerts_plate", "stream_alerts", ["plate_normalized"])

    op.create_table(
        "video_walls",
        sa.Column("wall_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False, unique=True),
        sa.Column("owner_id", sa.String(36)),
        sa.Column("tiles", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("video_walls")
    op.drop_table("stream_alerts")
    op.drop_table("watchlist_vehicles")
    op.drop_table("tagged_events")
    op.drop_table("vehicle_observations")
    op.drop_table("viewer_sessions")
    op.drop_table("stream_health_events")
    op.drop_table("stream_sources")
