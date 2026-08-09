"""drop interviews.offered_slots — slots are computed live (scheduling v2)

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-09
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("interviews", "offered_slots")


def downgrade() -> None:
    op.add_column(
        "interviews",
        sa.Column("offered_slots", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
