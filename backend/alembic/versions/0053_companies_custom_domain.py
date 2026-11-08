"""companies.custom_domain + custom_domain_token + custom_domain_verified_at
(board card "Custom domains + subdomain routing", slice 2: the domain and its
DNS TXT proof of ownership; Host routing follows in a later slice).

The domain is unique only once verified (partial unique index): a pending
claim proves nothing, so it must never lock a domain away from its real
owner.

Revision ID: 0053
Revises: 0052
Create Date: 2026-11-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None

INDEX = "uq_companies_verified_custom_domain"


def upgrade() -> None:
    op.add_column("companies", sa.Column("custom_domain", sa.String(253), nullable=True))
    op.add_column("companies", sa.Column("custom_domain_token", sa.String(64), nullable=True))
    op.add_column(
        "companies",
        sa.Column("custom_domain_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        INDEX,
        "companies",
        ["custom_domain"],
        unique=True,
        postgresql_where=sa.text("custom_domain_verified_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="companies")
    op.drop_column("companies", "custom_domain_verified_at")
    op.drop_column("companies", "custom_domain_token")
    op.drop_column("companies", "custom_domain")
