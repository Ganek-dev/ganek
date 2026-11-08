"""erasure_tombstones.company_id: nullable, ON DELETE SET NULL (board card
"Operator plane", tenant delete). A deleted tenant's tombstones must outlive
the company row, or a restored backup would bring the whole tenant back
with nothing left to replay against. The tenant delete also writes a
``company`` tombstone, which the replay uses to delete a restored company.

Revision ID: 0052
Revises: 0051
Create Date: 2026-11-08
"""

from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

FK = "fk_erasure_tombstones_company_id_companies"


def upgrade() -> None:
    op.drop_constraint(op.f(FK), "erasure_tombstones", type_="foreignkey")
    op.alter_column("erasure_tombstones", "company_id", nullable=True)
    op.create_foreign_key(
        op.f(FK),
        "erasure_tombstones",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # tombstones of deleted tenants have no company left to point at
    op.execute("DELETE FROM erasure_tombstones WHERE company_id IS NULL")
    op.drop_constraint(op.f(FK), "erasure_tombstones", type_="foreignkey")
    op.alter_column("erasure_tombstones", "company_id", nullable=False)
    op.create_foreign_key(
        op.f(FK),
        "erasure_tombstones",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="CASCADE",
    )
