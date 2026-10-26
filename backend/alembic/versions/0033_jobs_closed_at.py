"""jobs.closed_at: when a posting was closed, for "days open" on the job
overview (board card "Job overview page", spec job posts v2 section 6).

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-26
"""

import sqlalchemy as sa

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    # jobs closed before this column existed: updated_at is the closest proxy
    # (late only if the posting was edited after closing)
    op.execute(
        "UPDATE jobs SET closed_at = updated_at WHERE status = 'closed' AND closed_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("jobs", "closed_at")
