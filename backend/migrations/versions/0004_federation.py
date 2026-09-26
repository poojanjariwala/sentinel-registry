"""Migration 0004: Module 3 - VMS federation registry."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_federation"
down_revision = "0003_grid_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vms_systems",
        sa.Column("vms_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("vendor", sa.String(120), nullable=False),
        sa.Column("adapter_kind", sa.String(40), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("auth_env_keys", JSONB(), nullable=True),
        sa.Column("capabilities", JSONB(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="UNKNOWN"),
        sa.Column("last_discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("vms_systems")
