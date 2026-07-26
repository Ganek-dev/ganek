"""Allow the candidate-initiated 'withdrawn' application stage.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-26
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

OLD_STAGES = "('new', 'screening', 'interview', 'offer', 'hired', 'rejected')"
NEW_STAGES = "('new', 'screening', 'interview', 'offer', 'hired', 'rejected', 'withdrawn')"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_applications_stage"), "applications", type_="check")
    op.create_check_constraint(
        op.f("ck_applications_stage"), "applications", f"stage IN {NEW_STAGES}"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_applications_stage"), "applications", type_="check")
    op.create_check_constraint(
        op.f("ck_applications_stage"), "applications", f"stage IN {OLD_STAGES}"
    )
