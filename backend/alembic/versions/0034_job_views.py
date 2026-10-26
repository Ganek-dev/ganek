"""job_views: advisory page-view counters, one row per (job, UTC day,
source) (board card "Job page views", spec job posts v2 section 5.5,
decisions JP1/JP8). Nothing per visitor is stored: no IP, no user agent,
no cookie, no visitor id, no time finer than a day.

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-26
"""

import sqlalchemy as sa

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_views",
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE", name=op.f("fk_job_views_job_id_jobs")),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("views", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("job_id", "day", "source", name=op.f("pk_job_views")),
    )


def downgrade() -> None:
    op.drop_table("job_views")
