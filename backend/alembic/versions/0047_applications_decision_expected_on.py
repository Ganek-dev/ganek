"""applications.decision_expected_on: a per-application decision date the
team can set. NULL means the candidate status page derives the date from
the company's decision window setting (applied + N days).

Revision ID: 0047
Revises: 0046
Create Date: 2026-11-07
"""

import sqlalchemy as sa

from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("decision_expected_on", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("applications", "decision_expected_on")
