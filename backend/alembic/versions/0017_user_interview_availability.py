"""per-user interview availability (scheduling v2)

Saved weekly schedule as {"timezone": IANA, "days": {"mon": {"start": "09:00",
"end": "17:00"}, ...}}. NULL means the implicit default Mon-Fri 09:00-17:00.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-09
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("interview_availability", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "interview_availability")
