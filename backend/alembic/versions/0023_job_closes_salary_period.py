"""jobs.closes_at + jobs.salary_period — honest Google Jobs JSON-LD (M5.7 H5)

closes_at is advisory (validThrough); it never auto-closes a posting.
salary_period backfills to 'year' — the JSON-LD previously hardcoded MONTH,
which misdeclared the (typical) annual salaries.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-17
"""

import sqlalchemy as sa

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("salary_period", sa.String(length=20), nullable=False, server_default="year"),
    )


def downgrade() -> None:
    op.drop_column("jobs", "salary_period")
    op.drop_column("jobs", "closes_at")
