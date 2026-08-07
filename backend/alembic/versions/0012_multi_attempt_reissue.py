"""allow multiple quiz attempts per application (D6 integrity v2)

Invalidate & re-invite needs attempt history: the unique attempt-per-
application constraint becomes a plain index, and the status CHECK gains
'invalidated'. The latest attempt is the one that counts; older rows are
audit history.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-07
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("uq_quiz_attempts_application_id"), "quiz_attempts", type_="unique")
    op.create_index(op.f("ix_quiz_attempts_application_id"), "quiz_attempts", ["application_id"])
    op.drop_constraint(op.f("ck_quiz_attempts_status"), "quiz_attempts", type_="check")
    op.create_check_constraint(
        op.f("ck_quiz_attempts_status"),
        "quiz_attempts",
        "status IN ('pending', 'in_progress', 'completed', 'expired', 'invalidated')",
    )


def downgrade() -> None:
    # best-effort: fails if an application already holds several attempts
    op.drop_constraint(op.f("ck_quiz_attempts_status"), "quiz_attempts", type_="check")
    op.create_check_constraint(
        op.f("ck_quiz_attempts_status"),
        "quiz_attempts",
        "status IN ('pending', 'in_progress', 'completed', 'expired')",
    )
    op.drop_index(op.f("ix_quiz_attempts_application_id"), table_name="quiz_attempts")
    op.create_unique_constraint(
        op.f("uq_quiz_attempts_application_id"), "quiz_attempts", ["application_id"]
    )
