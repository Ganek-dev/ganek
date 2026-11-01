"""email_outbox.send_after + cancelled_at: delayed rejection email. A row in the
new 'scheduled' status waits until send_after, then the worker releases it; a
staff member or an un-reject can move it to 'cancelled'.

Rollback note: the downgrade marks scheduled and cancelled rows 'failed', so
a delayed email that has not gone out yet is never sent after a rollback.

Revision ID: 0044
Revises: 0043
Create Date: 2026-11-01
"""

import sqlalchemy as sa

from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_outbox", sa.Column("send_after", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "email_outbox", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        op.f("ix_email_outbox_send_after_scheduled"),
        "email_outbox",
        ["send_after"],
        postgresql_where=sa.text("status = 'scheduled'"),
    )


def downgrade() -> None:
    # a row in a status the old enum does not know would break the mapping
    op.execute(
        "UPDATE email_outbox SET status = 'failed', last_error = 'cancelled by downgrade' "
        "WHERE status IN ('scheduled', 'cancelled')"
    )
    op.drop_index(
        op.f("ix_email_outbox_send_after_scheduled"),
        table_name="email_outbox",
        postgresql_where=sa.text("status = 'scheduled'"),
    )
    op.drop_column("email_outbox", "cancelled_at")
    op.drop_column("email_outbox", "send_after")
