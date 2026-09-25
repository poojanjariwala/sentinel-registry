"""Initial Module 1 schema: departments, sites, cameras, users, RBAC, imports, gap runs, audit.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-25
"""

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "departments",
        sa.Column("department_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False, unique=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "sites",
        sa.Column("site_id", sa.String(36), primary_key=True),
        sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.department_id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.Text()),
        sa.Column("district", sa.String(100)),
        sa.Column("taluka", sa.String(100)),
        sa.Column("latitude", sa.Double()),
        sa.Column("longitude", sa.Double()),
        sa.Column("location", Geometry(geometry_type="POINT", srid=4326)),
        sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sites_department", "sites", ["department_id"])
    op.create_index("ix_sites_district", "sites", ["district"])
    op.create_index("ix_sites_location_gix", "sites", ["location"], postgresql_using="gist")

    op.create_table(
        "cameras",
        sa.Column("camera_id", sa.String(36), primary_key=True),
        sa.Column("camera_code", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.department_id"), nullable=False),
        sa.Column("site_id", sa.String(36), sa.ForeignKey("sites.site_id")),
        sa.Column("camera_type", sa.String(50), nullable=False, server_default="FIXED"),
        sa.Column("ownership", sa.String(30), nullable=False, server_default="GOVERNMENT"),
        sa.Column("public_facing", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("vendor", sa.String(120)),
        sa.Column("model", sa.String(120)),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("latitude", sa.Double()),
        sa.Column("longitude", sa.Double()),
        sa.Column("location", Geometry(geometry_type="POINT", srid=4326)),
        sa.Column("district", sa.String(100)),
        sa.Column("taluka", sa.String(100)),
        sa.Column("address", sa.Text()),
        sa.Column("connectivity_status", sa.String(30), nullable=False, server_default="UNKNOWN"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("storage_type", sa.String(30)),
        sa.Column("retention_days", sa.Integer()),
        sa.Column("install_date", sa.Date()),
        sa.Column("amc_vendor", sa.String(150)),
        sa.Column("amc_end_date", sa.Date()),
        sa.Column("maintenance_status", sa.String(30), nullable=False, server_default="OK"),
        sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column("coverage_radius_m", sa.Integer()),
        sa.Column("metadata", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cameras_camera_code", "cameras", ["camera_code"])
    op.create_index("ix_cameras_department_status", "cameras", ["department_id", "status"])
    op.create_index("ix_cameras_district_status", "cameras", ["district", "status"])
    op.create_index("ix_cameras_camera_type", "cameras", ["camera_type"])
    op.create_index("ix_cameras_maintenance", "cameras", ["maintenance_status"])
    op.create_index("ix_cameras_location_gix", "cameras", ["location"], postgresql_using="gist")

    op.create_table(
        "users",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("email", sa.String(200), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.department_id")),
        sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("permissions", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "roles",
        sa.Column("name", sa.String(50), primary_key=True),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "user_roles",
        sa.Column("user_role_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("role_name", sa.String(50), sa.ForeignKey("roles.name"), nullable=False),
        sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.department_id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_roles_user", "user_roles", ["user_id"])

    op.create_table(
        "permissions",
        sa.Column("permission_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("resource", sa.String(80), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("scope_type", sa.String(50)),
        sa.Column("granted", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_permissions_user", "permissions", ["user_id"])

    op.create_table(
        "camera_import_batches",
        sa.Column("batch_id", sa.String(36), primary_key=True),
        sa.Column("filename", sa.String(300), nullable=False),
        sa.Column("uploaded_by", sa.String(36), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(30), nullable=False, server_default="COMPLETED"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("report", JSONB),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "gap_analysis_runs",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("params", JSONB, nullable=False),
        sa.Column("summary", JSONB, nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="COMPLETED"),
        sa.Column("camera_count_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uncovered_hex_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "audit_events",
        sa.Column("audit_event_id", sa.String(36), primary_key=True),
        sa.Column("actor_user_id", sa.String(36)),
        sa.Column("actor_label", sa.String(150)),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(80)),
        sa.Column("resource_id", sa.String(64)),
        sa.Column("request_id", sa.String(100)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("user_agent", sa.Text()),
        sa.Column("before_state", JSONB),
        sa.Column("after_state", JSONB),
        sa.Column("reason", sa.Text()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("gap_analysis_runs")
    op.drop_table("camera_import_batches")
    op.drop_table("permissions")
    op.drop_table("user_roles")
    op.drop_table("roles")
    op.drop_table("users")
    op.drop_table("cameras")
    op.drop_table("sites")
    op.drop_table("departments")
