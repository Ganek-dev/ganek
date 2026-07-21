"""create questions

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-21
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "questions",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), nullable=True),
        sa.Column("domain", sa.String(50), nullable=False),
        sa.Column("tags", ARRAY(sa.String(50)), nullable=False),
        sa.Column("difficulty", sa.String(20), nullable=False),
        sa.Column("prompt_md", sa.Text(), nullable=False),
        sa.Column("options", JSONB(), nullable=False),
        sa.Column("correct_key", sa.String(1), nullable=False),
        sa.Column("explanation_md", sa.Text(), nullable=False),
        sa.Column("time_limit_seconds", sa.Integer(), nullable=False),
        sa.Column("locale", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_questions")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_questions_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "difficulty IN ('easy', 'medium', 'hard')", name=op.f("ck_questions_difficulty")
        ),
        sa.CheckConstraint("status IN ('active', 'retired')", name=op.f("ck_questions_status")),
        sa.CheckConstraint("source IN ('seed', 'company')", name=op.f("ck_questions_source")),
        sa.CheckConstraint(
            "correct_key IN ('a', 'b', 'c', 'd')", name=op.f("ck_questions_correct_key")
        ),
    )
    op.create_index(op.f("ix_questions_company_id"), "questions", ["company_id"])
    op.create_index(op.f("ix_questions_domain"), "questions", ["domain"])
    op.create_index("ix_questions_tags", "questions", ["tags"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_table("questions")
