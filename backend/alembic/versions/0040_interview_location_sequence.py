"""Scheduling without Google Calendar (board card, owner decision
2026-10-31: ICS only). Interviews carry the meeting location and the iTIP
SEQUENCE of the last invite; users carry a default location. The Google
event id and Meet URL go: bookings no longer create calendar events, the
invite travels as an .ics in Ganek's own mails.

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-31
"""

import sqlalchemy as sa

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "interviews",
        sa.Column("location", sa.String(500), nullable=False, server_default=""),
    )
    op.add_column(
        "interviews",
        sa.Column("ics_sequence", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.drop_column("interviews", "google_event_id")
    op.drop_column("interviews", "meet_url")
    op.add_column("users", sa.Column("interview_location", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "interview_location")
    op.add_column("interviews", sa.Column("meet_url", sa.String(500), nullable=True))
    op.add_column("interviews", sa.Column("google_event_id", sa.String(300), nullable=True))
    op.drop_column("interviews", "ics_sequence")
    op.drop_column("interviews", "location")
