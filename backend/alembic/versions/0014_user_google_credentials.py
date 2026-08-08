"""per-user google calendar credentials (D7)

One row per user with a connected Google Calendar. The refresh token is
Fernet-encrypted with a key derived from VETD_SECRET_KEY; access tokens
are never persisted.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_table("user_google_credentials")
