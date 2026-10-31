"""email_outbox.rendered_subject + rendered_text: the mail as the sender
rendered it, stored at delivery so the candidate timeline shows subject and
text without re-rendering (board card "Candidate emails", PR 4).

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-31
"""

import sqlalchemy as sa

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("email_outbox", sa.Column("rendered_subject", sa.Text(), nullable=True))
    op.add_column("email_outbox", sa.Column("rendered_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("email_outbox", "rendered_text")
    op.drop_column("email_outbox", "rendered_subject")
