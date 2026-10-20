"""email_suppressions: addresses that bounced or complained, stored as blind
hashes so the list holds no PII (board card A7, email deliverability).

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-21
"""

import sqlalchemy as sa

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_suppressions",
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_event_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_email_suppressions_company_id_companies"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("email_hash", name=op.f("pk_email_suppressions")),
    )
    op.create_index(op.f("ix_email_suppressions_company_id"), "email_suppressions", ["company_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_email_suppressions_company_id"), table_name="email_suppressions")
    op.drop_table("email_suppressions")
