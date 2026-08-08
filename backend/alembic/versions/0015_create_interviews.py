"""interviews table (D7 single-round scheduling)

One interview request per application; cancelled rows stay as history
and the partial unique index lets a fresh request replace them.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interviews",
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
            nullable=False,
        ),
        sa.Column("interviewer_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("duration_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("timezone", sa.String(60), nullable=False),
        sa.Column("offered_slots", JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("google_event_id", sa.String(300), nullable=True),
        sa.Column("meet_url", sa.String(500), nullable=True),
        sa.Column("reminder_job_id", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'booked', 'cancelled')", name=op.f("ck_interviews_status")
        ),
    )
    op.create_index(op.f("ix_interviews_company_id"), "interviews", ["company_id"])
    op.create_index(op.f("ix_interviews_application_id"), "interviews", ["application_id"])
    op.create_index(
        "ix_interviews_application_active",
        "interviews",
        ["application_id"],
        unique=True,
        postgresql_where=sa.text("status != 'cancelled'"),
    )


def downgrade() -> None:
    op.drop_index("ix_interviews_application_active", table_name="interviews")
    op.drop_index(op.f("ix_interviews_application_id"), table_name="interviews")
    op.drop_index(op.f("ix_interviews_company_id"), table_name="interviews")
    op.drop_table("interviews")
