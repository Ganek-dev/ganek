"""activity_log + tasks (D7 dashboard v2)

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "application_id",
            sa.Uuid(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(op.f("ix_activity_log_company_id"), "activity_log", ["company_id"])
    op.create_index("ix_activity_log_company_created", "activity_log", ["company_id", "created_at"])
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "assignee_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(op.f("ix_tasks_company_id"), "tasks", ["company_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_tasks_company_id"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_activity_log_company_created", table_name="activity_log")
    op.drop_index(op.f("ix_activity_log_company_id"), table_name="activity_log")
    op.drop_table("activity_log")
