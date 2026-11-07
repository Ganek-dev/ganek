"""Job fields: department, seniority, language, owner, internal note, and an
opt-in auto_close that lets the worker close a posting once its closes-on day
is over. All optional; existing jobs keep today's behaviour (auto_close off).

Revision ID: 0048
Revises: 0047
Create Date: 2026-11-07
"""

import sqlalchemy as sa

from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs", sa.Column("department", sa.String(length=100), nullable=False, server_default="")
    )
    op.add_column("jobs", sa.Column("seniority", sa.String(length=20), nullable=True))
    op.add_column("jobs", sa.Column("language", sa.String(length=10), nullable=True))
    op.add_column("jobs", sa.Column("owner_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_jobs_owner_user_id_users"),
        "jobs",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_jobs_owner_user_id"), "jobs", ["owner_user_id"])
    op.add_column("jobs", sa.Column("internal_note", sa.Text(), nullable=False, server_default=""))
    op.add_column(
        "jobs",
        sa.Column("auto_close", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("jobs", "auto_close")
    op.drop_column("jobs", "internal_note")
    op.drop_index(op.f("ix_jobs_owner_user_id"), table_name="jobs")
    op.drop_constraint(op.f("fk_jobs_owner_user_id_users"), "jobs", type_="foreignkey")
    op.drop_column("jobs", "owner_user_id")
    op.drop_column("jobs", "language")
    op.drop_column("jobs", "seniority")
    op.drop_column("jobs", "department")
