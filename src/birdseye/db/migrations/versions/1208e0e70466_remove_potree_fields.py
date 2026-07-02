"""remove potree fields

Revision ID: 1208e0e70466
Revises: 1963aa5c6b39
Create Date: 2026-07-02 14:12:48.047904

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1208e0e70466"
down_revision: str | Sequence[str] | None = "1963aa5c6b39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("missions", "potree_path")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "missions", sa.Column("potree_path", sa.VARCHAR(), autoincrement=False, nullable=True)
    )
