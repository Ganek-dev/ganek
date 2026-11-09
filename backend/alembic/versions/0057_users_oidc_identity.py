"""users.oidc_issuer + users.oidc_sub: generic OIDC sign-in identity (board
card "SSO + multi-company user membership", OIDC slice). Unique as a pair;
NULL for every existing account until it signs in through the IdP.

Revision ID: 0057
Revises: 0056
Create Date: 2026-11-09
"""

import sqlalchemy as sa

from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("oidc_issuer", sa.String(length=500), nullable=True))
    op.add_column("users", sa.Column("oidc_sub", sa.String(length=255), nullable=True))
    op.create_unique_constraint(
        op.f("uq_users_oidc_issuer_oidc_sub"), "users", ["oidc_issuer", "oidc_sub"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_users_oidc_issuer_oidc_sub"), "users", type_="unique")
    op.drop_column("users", "oidc_sub")
    op.drop_column("users", "oidc_issuer")
