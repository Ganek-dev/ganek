"""applications.decided_at — the retention-purge clock (M5.6 G3)

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-15
"""

import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Old terminal rows never carried a decision timestamp — created_at is the
    # documented conservative fallback (stage history lives only in
    # activity_log and is not worth mining for a one-off backfill).
    op.execute(
        "UPDATE applications SET decided_at = created_at "
        "WHERE stage IN ('rejected', 'withdrawn', 'hired')"
    )


def downgrade() -> None:
    op.drop_column("applications", "decided_at")
