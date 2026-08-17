"""hot-path indexes (M5.7 H4)

- applications(decided_at): the nightly retention purge scans it
- applications(company_id, created_at): the paginated pipeline list's
  filter + order
- quiz_attempts(application_id, created_at): every latest-attempt lookup
  since 0012 made attempts 1→N
- interviews(interviewer_user_id, status, scheduled_start): live slot
  computation's not-vetd-booked filter, on every public booking-page GET

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-17
"""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(op.f("ix_applications_decided_at"), "applications", ["decided_at"])
    op.create_index(
        op.f("ix_applications_company_id_created_at"),
        "applications",
        ["company_id", "created_at"],
    )
    op.create_index(
        op.f("ix_quiz_attempts_application_id_created_at"),
        "quiz_attempts",
        ["application_id", "created_at"],
    )
    op.create_index(
        op.f("ix_interviews_interviewer_status_start"),
        "interviews",
        ["interviewer_user_id", "status", "scheduled_start"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_interviews_interviewer_status_start"), table_name="interviews")
    op.drop_index(op.f("ix_quiz_attempts_application_id_created_at"), table_name="quiz_attempts")
    op.drop_index(op.f("ix_applications_company_id_created_at"), table_name="applications")
    op.drop_index(op.f("ix_applications_decided_at"), table_name="applications")
