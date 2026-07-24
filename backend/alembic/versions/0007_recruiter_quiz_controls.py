"""company question blocklist + attempt time limit snapshot

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-24
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "blocked_question_ids",
            ARRAY(sa.String(length=100)),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "quiz_attempts",
        sa.Column("time_limit_seconds", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("quiz_attempts", "time_limit_seconds")
    op.drop_column("companies", "blocked_question_ids")
