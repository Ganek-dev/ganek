"""access_log: read-access audit trail, who looked at which candidate
(board card "Read-access audit trail").

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-24
"""

import sqlalchemy as sa

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "access_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("api_key_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_access_log_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_access_log_application_id_applications"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_access_log_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["api_key_id"],
            ["api_keys.id"],
            name=op.f("fk_access_log_api_key_id_api_keys"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_log")),
    )
    op.create_index(op.f("ix_access_log_company_id"), "access_log", ["company_id"])
    op.create_index(
        "ix_access_log_application_created", "access_log", ["application_id", "created_at"]
    )
    op.create_index("ix_access_log_company_created", "access_log", ["company_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_access_log_company_created", table_name="access_log")
    op.drop_index("ix_access_log_application_created", table_name="access_log")
    op.drop_index(op.f("ix_access_log_company_id"), table_name="access_log")
    op.drop_table("access_log")
