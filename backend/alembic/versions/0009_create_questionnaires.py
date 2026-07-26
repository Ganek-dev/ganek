"""create questionnaires table (D4)

Ordered, curator-authored sets of questions. ``question_refs`` stores
string ids so open-bank slugs (``py-gil-1``) and company-question UUIDs
share one column — matches the existing ``quiz_config.exclude_ids``
convention on ``jobs``.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "questionnaires",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("shuffle", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "question_refs",
            ARRAY(sa.String(100)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("meta", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("company_id", "name", name=op.f("uq_questionnaires_company_id")),
    )
    op.create_index(
        op.f("ix_questionnaires_company_id"),
        "questionnaires",
        ["company_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_questionnaires_company_id"), table_name="questionnaires")
    op.drop_table("questionnaires")
