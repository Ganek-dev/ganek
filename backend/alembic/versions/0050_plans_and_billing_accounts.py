"""companies.plan + billing_accounts: the plan model for hosted billing
(board card B1a). Every existing and new company defaults to self_hosted
(no limits); only the ee/ package on a hosted instance sets other plans or
writes billing_accounts.

Revision ID: 0050
Revises: 0049
Create Date: 2026-11-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "plan", sa.String(length=12), nullable=False, server_default=sa.text("'self_hosted'")
        ),
    )
    op.create_table(
        "billing_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("stripe_customer_id", sa.String(length=64), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_billing_accounts_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_accounts")),
        sa.UniqueConstraint("company_id", name=op.f("uq_billing_accounts_company_id")),
        sa.UniqueConstraint(
            "stripe_customer_id", name=op.f("uq_billing_accounts_stripe_customer_id")
        ),
    )


def downgrade() -> None:
    op.drop_table("billing_accounts")
    op.drop_column("companies", "plan")
