"""users.display_name: what teammates and candidates see instead of the
email local part (board card D14, good first issue).

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-21
"""

import sqlalchemy as sa

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "display_name")
