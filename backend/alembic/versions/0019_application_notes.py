"""application_notes table — recruiter-internal notes on an application

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-10
"""

import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "application_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "application_id",
            sa.Uuid(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(op.f("ix_application_notes_company_id"), "application_notes", ["company_id"])
    op.create_index(
        op.f("ix_application_notes_application_id"), "application_notes", ["application_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_application_notes_application_id"), table_name="application_notes")
    op.drop_index(op.f("ix_application_notes_company_id"), table_name="application_notes")
    op.drop_table("application_notes")
