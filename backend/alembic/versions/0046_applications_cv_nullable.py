"""applications.cv_object_key, cv_filename, cv_size nullable: an application
created without a CV (CSV import, screen link, connectors). All three are NULL
together; the public apply form still requires a CV.

Revision ID: 0046
Revises: 0045
Create Date: 2026-11-07
"""

import sqlalchemy as sa

from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("applications", "cv_object_key", existing_type=sa.String(500), nullable=True)
    op.alter_column("applications", "cv_filename", existing_type=sa.String(255), nullable=True)
    op.alter_column("applications", "cv_size", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # rows without a CV cannot satisfy NOT NULL again; they are removed first
    op.execute("DELETE FROM applications WHERE cv_object_key IS NULL")
    op.alter_column("applications", "cv_size", existing_type=sa.Integer(), nullable=False)
    op.alter_column("applications", "cv_filename", existing_type=sa.String(255), nullable=False)
    op.alter_column("applications", "cv_object_key", existing_type=sa.String(500), nullable=False)
