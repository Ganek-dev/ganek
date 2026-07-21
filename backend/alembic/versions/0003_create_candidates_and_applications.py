"""create candidates and applications

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-21
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("links", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidates")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_candidates_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("company_id", "email", name=op.f("uq_candidates_company_id")),
    )
    op.create_index(op.f("ix_candidates_company_id"), "candidates", ["company_id"])

    op.create_table(
        "applications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", UUID(as_uuid=True), nullable=False),
        sa.Column("cv_object_key", sa.String(500), nullable=False),
        sa.Column("cv_filename", sa.String(255), nullable=False),
        sa.Column("cv_size", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_applications")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_applications_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_applications_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name=op.f("fk_applications_candidate_id_candidates"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("job_id", "candidate_id", name=op.f("uq_applications_job_id")),
        sa.CheckConstraint(
            "stage IN ('new', 'screening', 'interview', 'offer', 'hired', 'rejected')",
            name=op.f("ck_applications_stage"),
        ),
    )
    op.create_index(op.f("ix_applications_company_id"), "applications", ["company_id"])
    op.create_index("ix_applications_job_id_stage", "applications", ["job_id", "stage"])


def downgrade() -> None:
    op.drop_table("applications")
    op.drop_table("candidates")
