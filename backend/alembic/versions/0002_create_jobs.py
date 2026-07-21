"""create jobs

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-21
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description_md", sa.Text(), nullable=False),
        sa.Column("location", sa.String(200), nullable=False),
        sa.Column("remote_policy", sa.String(20), nullable=False),
        sa.Column("employment_type", sa.String(20), nullable=False),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column("salary_currency", sa.String(3), nullable=True),
        sa.Column("tags", ARRAY(sa.String(50)), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quiz_config", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_jobs_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("company_id", "slug", name=op.f("uq_jobs_company_id")),
        sa.CheckConstraint(
            "remote_policy IN ('onsite', 'hybrid', 'remote')", name=op.f("ck_jobs_remote_policy")
        ),
        sa.CheckConstraint(
            "employment_type IN ('full_time', 'part_time', 'contract', 'internship')",
            name=op.f("ck_jobs_employment_type"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'closed')", name=op.f("ck_jobs_status")
        ),
    )
    op.create_index(op.f("ix_jobs_company_id"), "jobs", ["company_id"])
    op.create_index("ix_jobs_tags", "jobs", ["tags"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_table("jobs")
