"""billing_accounts.plan_override: an operator-set plan that wins over the
Stripe-synced companies.plan (board card "Operator plane: superadmin plan
override", Q21). NULL = no override. Only the superadmin /ops route writes
it; the Stripe webhook never does.

Revision ID: 0051
Revises: 0050
Create Date: 2026-11-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "billing_accounts", sa.Column("plan_override", sa.String(length=12), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("billing_accounts", "plan_override")
