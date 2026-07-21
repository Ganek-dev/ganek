"""create quiz attempts and answers

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-21
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "quiz_attempts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("question_ids", ARRAY(sa.String(100)), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("per_tag_scores", JSONB(), nullable=False),
        sa.Column("integrity", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_attempts")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_quiz_attempts_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_quiz_attempts_application_id_applications"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("application_id", name=op.f("uq_quiz_attempts_application_id")),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'expired')",
            name=op.f("ck_quiz_attempts_status"),
        ),
    )
    op.create_index(op.f("ix_quiz_attempts_company_id"), "quiz_attempts", ["company_id"])

    op.create_table(
        "attempt_answers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("attempt_id", UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", sa.String(100), nullable=False),
        sa.Column("option_order", ARRAY(sa.String(1)), nullable=False),
        sa.Column("served_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answer_key", sa.String(1), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attempt_answers")),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["quiz_attempts.id"],
            name=op.f("fk_attempt_answers_attempt_id_quiz_attempts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.id"],
            name=op.f("fk_attempt_answers_question_id_questions"),
            ondelete="RESTRICT",
        ),
    )
    op.create_index(op.f("ix_attempt_answers_attempt_id"), "attempt_answers", ["attempt_id"])


def downgrade() -> None:
    op.drop_table("attempt_answers")
    op.drop_table("quiz_attempts")
