"""Migration 0003: real grid feeds - per-source origin auth extras."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_grid_auth"
down_revision = "0002_module2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stream_sources", sa.Column("auth_json", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("stream_sources", "auth_json")
