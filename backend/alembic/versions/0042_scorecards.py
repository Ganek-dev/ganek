"""Interview scorecards: per-reviewer structured feedback rows, the company
and job criteria templates (JSONB) and the read-mostly 'reviewer' user role.

Revision ID: 0042
Revises: 0041
Create Date: 2026-11-01
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("scorecard_template", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "jobs",
        sa.Column("scorecard_template", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.create_table(
        "scorecards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("dismissed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("interview_id", sa.Uuid(), nullable=True),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("due_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("criteria_snapshot", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("ratings", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("recommendation", sa.String(16), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "recommendation IN ('strong_no', 'no', 'yes', 'strong_yes')",
            name=op.f("ck_scorecards_recommendation"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_scorecards_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_scorecards_application_id_applications"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_scorecards_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"],
            ["users.id"],
            name=op.f("fk_scorecards_reviewer_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_scorecards_requested_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dismissed_by_user_id"],
            ["users.id"],
            name=op.f("fk_scorecards_dismissed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["interview_id"],
            ["interviews.id"],
            name=op.f("fk_scorecards_interview_id_interviews"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scorecards")),
    )
    op.create_index(
        "uq_scorecards_application_reviewer",
        "scorecards",
        ["application_id", "reviewer_user_id"],
        unique=True,
        postgresql_where=sa.text("reviewer_user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_scorecards_company_reviewer_submitted",
        "scorecards",
        ["company_id", "reviewer_user_id", "submitted_at"],
    )
    op.create_index(
        "ix_scorecards_company_application", "scorecards", ["company_id", "application_id"]
    )
    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_role"), "users", "role IN ('admin', 'member', 'reviewer')"
    )


def downgrade() -> None:
    # reviewers have no place in the two-role world; demote so the CHECK holds
    op.execute("UPDATE users SET role = 'member' WHERE role = 'reviewer'")
    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.create_check_constraint(op.f("ck_users_role"), "users", "role IN ('admin', 'member')")
    op.drop_index("ix_scorecards_company_application", table_name="scorecards")
    op.drop_index("ix_scorecards_company_reviewer_submitted", table_name="scorecards")
    op.drop_index("uq_scorecards_application_reviewer", table_name="scorecards")
    op.drop_table("scorecards")
    op.drop_column("jobs", "scorecard_template")
    op.drop_column("companies", "scorecard_template")
