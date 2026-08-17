"""email_outbox table — queued outbound email with delivery state (M5.7 H4)

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-17
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "application_id",
            sa.Uuid(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "status", sa.String(length=10), nullable=False, server_default=sa.text("'queued'")
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(op.f("ix_email_outbox_company_id"), "email_outbox", ["company_id"])
    op.create_index(op.f("ix_email_outbox_application_id"), "email_outbox", ["application_id"])
    # the sweeper scans for stuck queued rows; the purge scans terminal ones
    op.create_index(
        op.f("ix_email_outbox_status_created_at"), "email_outbox", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_email_outbox_status_created_at"), table_name="email_outbox")
    op.drop_index(op.f("ix_email_outbox_application_id"), table_name="email_outbox")
    op.drop_index(op.f("ix_email_outbox_company_id"), table_name="email_outbox")
    op.drop_table("email_outbox")
