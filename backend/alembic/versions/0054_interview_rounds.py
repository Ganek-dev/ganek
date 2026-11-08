"""interviews.round_number (board card "Multi-round interview loops")

An application holds one active interview per round: the partial unique
index moves from (application_id) to (application_id, round_number). A new
round opens once the latest round's interview is over (booked and its end
has passed); a cancelled row frees its round for a fresh request. Every
existing row is round 1.

Downgrade restores the single-round index, which fails while an application
still holds several non-cancelled rounds - cancel or erase them first.

Revision ID: 0054
Revises: 0053
Create Date: 2026-11-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None

OLD_INDEX = "ix_interviews_application_active"
NEW_INDEX = "ix_interviews_application_round_active"


def upgrade() -> None:
    op.add_column(
        "interviews",
        sa.Column("round_number", sa.SmallInteger(), nullable=False, server_default="1"),
    )
    op.drop_index(OLD_INDEX, table_name="interviews")
    op.create_index(
        NEW_INDEX,
        "interviews",
        ["application_id", "round_number"],
        unique=True,
        postgresql_where=sa.text("status != 'cancelled'"),
    )


def downgrade() -> None:
    op.drop_index(NEW_INDEX, table_name="interviews")
    op.create_index(
        OLD_INDEX,
        "interviews",
        ["application_id"],
        unique=True,
        postgresql_where=sa.text("status != 'cancelled'"),
    )
    op.drop_column("interviews", "round_number")
