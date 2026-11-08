"""companies.suspended_at + suspension_reason: an operator can suspend a
tenant on a hosted instance (board card "Operator plane", first slice).
NULL suspended_at = active; the reason is shown to the tenant at sign-in.

Revision ID: 0049
Revises: 0048
Create Date: 2026-11-07
"""

import sqlalchemy as sa

from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("companies", sa.Column("suspension_reason", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "suspension_reason")
    op.drop_column("companies", "suspended_at")
