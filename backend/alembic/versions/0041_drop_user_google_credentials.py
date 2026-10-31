"""Drop the Google Calendar credentials table (board card "Scheduling
without Google Calendar", owner decision 2026-10-31: ICS only). No user was
connected; the downgrade recreates the empty table as 0014 defined it.

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-31
"""

import sqlalchemy as sa

from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("user_google_credentials")


def downgrade() -> None:
    op.create_table(
        "user_google_credentials",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("refresh_token_encrypted", sa.String(1000), nullable=False),
        sa.Column("google_email", sa.String(320), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_refresh_error", sa.String(200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
