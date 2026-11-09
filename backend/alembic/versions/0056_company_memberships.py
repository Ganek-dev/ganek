"""company_memberships: user x company x role (board card "SSO +
multi-company user membership", slice 1). Every existing user gets exactly
one membership copied from users.company_id and users.role; the ORM keeps
the two in sync from here on (app/models/membership.py).

Revision ID: 0056
Revises: 0055
Create Date: 2026-11-09
"""

import sqlalchemy as sa

from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_company_memberships_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_company_memberships_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_memberships")),
        sa.UniqueConstraint("user_id", "company_id", name=op.f("uq_company_memberships_user_id")),
    )
    op.create_index(
        op.f("ix_company_memberships_company_id"), "company_memberships", ["company_id"]
    )
    # one membership per existing user, same company and role; the row's
    # created_at is the user's, so "member since" survives the move
    op.execute(
        "INSERT INTO company_memberships (id, user_id, company_id, role, created_at, updated_at) "
        "SELECT gen_random_uuid(), id, company_id, role, created_at, now() FROM users"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_company_memberships_company_id"), table_name="company_memberships")
    op.drop_table("company_memberships")
