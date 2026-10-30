"""applications.rejection_reason + rejection_note: the optional internal
reason a recruiter records when a candidate is rejected (board card
"Candidate emails", PR 2; owner decision 2026-10-29: internal and optional,
never emailed, included in the candidate's data bundle).

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-30
"""

import sqlalchemy as sa

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "applications", sa.Column("rejection_reason", sa.String(length=40), nullable=True)
    )
    op.add_column("applications", sa.Column("rejection_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("applications", "rejection_note")
    op.drop_column("applications", "rejection_reason")
