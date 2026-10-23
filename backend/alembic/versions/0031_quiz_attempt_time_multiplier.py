"""quiz_attempts.time_multiplier: extra-time accommodation a recruiter
grants on request (board card "Time-multiplier accommodations").

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-23
"""

import sqlalchemy as sa

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quiz_attempts",
        sa.Column("time_multiplier", sa.Float(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("quiz_attempts", "time_multiplier")
