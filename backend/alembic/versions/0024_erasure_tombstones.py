"""erasure_tombstones: blind hashes of erased ids so a restored backup can
be re-purged (board card A3, erasure-aware backup/restore).

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "erasure_tombstones",
        sa.Column("subject_hash", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_erasure_tombstones_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("subject_hash", name=op.f("pk_erasure_tombstones")),
    )
    op.create_index(op.f("ix_erasure_tombstones_company_id"), "erasure_tombstones", ["company_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_erasure_tombstones_company_id"), table_name="erasure_tombstones")
    op.drop_table("erasure_tombstones")
