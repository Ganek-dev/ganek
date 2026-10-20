"""users.queue_dismissed: keys of derived dashboard queue items the user
hid (board card D13). Pruned on read once the item resolves.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("queue_dismissed", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "queue_dismissed")
