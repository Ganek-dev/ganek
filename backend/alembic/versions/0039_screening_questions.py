"""Per-job screening questions (board card "Per-job screening questions on
the apply form"): the company default set, the job's list and the
candidate's answer snapshots, all JSONB; a GIN index serves the applicant
list's screening filter (JSONB containment).

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("screening_questions", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "jobs",
        sa.Column("screening_questions", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "applications",
        sa.Column("screening_answers", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.create_index(
        op.f("ix_applications_screening_answers"),
        "applications",
        ["screening_answers"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_applications_screening_answers"), table_name="applications")
    op.drop_column("applications", "screening_answers")
    op.drop_column("jobs", "screening_questions")
    op.drop_column("companies", "screening_questions")
