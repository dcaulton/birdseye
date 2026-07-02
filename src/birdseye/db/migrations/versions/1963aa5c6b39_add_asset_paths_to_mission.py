"""add asset paths to mission

Revision ID: 1963aa5c6b39
Revises: bf5da969f3b8
Create Date: 2026-07-02 10:58:12.270799

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1963aa5c6b39"
down_revision: str | Sequence[str] | None = "bf5da969f3b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("missions", sa.Column("orthophoto_path", sa.String(), nullable=True))
    op.add_column("missions", sa.Column("dsm_path", sa.String(), nullable=True))
    op.add_column("missions", sa.Column("point_cloud_path", sa.String(), nullable=True))
    op.add_column("missions", sa.Column("mesh_path", sa.String(), nullable=True))
    op.add_column("missions", sa.Column("potree_path", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("missions", "potree_path")
    op.drop_column("missions", "mesh_path")
    op.drop_column("missions", "point_cloud_path")
    op.drop_column("missions", "dsm_path")
    op.drop_column("missions", "orthophoto_path")
