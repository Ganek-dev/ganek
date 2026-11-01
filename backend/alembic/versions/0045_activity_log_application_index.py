"""activity_log (application_id, created_at) index: the stage history of one
application reads its activity rows in order.

Revision ID: 0045
Revises: 0044
Create Date: 2026-11-01
"""

from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_activity_log_application_created"),
        "activity_log",
        ["application_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_activity_log_application_created"), table_name="activity_log")
