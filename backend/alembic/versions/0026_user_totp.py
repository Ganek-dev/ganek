"""users: TOTP second factor + recovery codes (board card A6, 2FA).

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fernet-encrypted base32 secret (GANEK_ENCRYPTION_KEY, like Google
    # credentials); set during enrolment, "enabled" only once confirmed
    op.add_column("users", sa.Column("totp_secret", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("totp_enabled_at", sa.DateTime(timezone=True), nullable=True))
    # last accepted 30 s step: a code never verifies twice
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))
    # sha256 hex of each unused recovery code
    op.add_column("users", sa.Column("recovery_codes", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "recovery_codes")
    op.drop_column("users", "totp_last_step")
    op.drop_column("users", "totp_enabled_at")
    op.drop_column("users", "totp_secret")
