"""create user_invites table (D6 team invites)

Pending email invites to join a company's team. Rows exist only while an
invite is outstanding — accept creates the user and deletes the row,
revoke deletes it outright — so the table doubles as the pending list.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-26
"""

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_invites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("role IN ('admin', 'member')", name=op.f("ck_user_invites_role")),
        sa.UniqueConstraint("company_id", "email", name=op.f("uq_user_invites_company_id")),
    )
    op.create_index(op.f("ix_user_invites_company_id"), "user_invites", ["company_id"])
    op.create_index(op.f("ix_user_invites_email"), "user_invites", ["email"])


def downgrade() -> None:
    op.drop_index(op.f("ix_user_invites_email"), table_name="user_invites")
    op.drop_index(op.f("ix_user_invites_company_id"), table_name="user_invites")
    op.drop_table("user_invites")
