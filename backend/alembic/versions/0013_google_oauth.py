"""google oauth: users.google_sub + nullable password_hash (D6)

Google-only accounts carry no password; identity is keyed on the OIDC
`sub` claim stored in google_sub once an account is linked or created.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_sub", sa.String(255), nullable=True))
    op.create_index(op.f("ix_users_google_sub"), "users", ["google_sub"], unique=True)
    op.alter_column("users", "password_hash", existing_type=sa.String(200), nullable=True)


def downgrade() -> None:
    # google-only accounts would violate NOT NULL — drop them rather than
    # leaving the table in an unloadable state
    op.execute("DELETE FROM users WHERE password_hash IS NULL")
    op.alter_column("users", "password_hash", existing_type=sa.String(200), nullable=False)
    op.drop_index(op.f("ix_users_google_sub"), table_name="users")
    op.drop_column("users", "google_sub")
