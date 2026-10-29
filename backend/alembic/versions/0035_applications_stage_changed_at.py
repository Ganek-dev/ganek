"""applications.stage_changed_at: when the row entered its current stage,
so the applicant list can sort by time in stage (board card "Candidate
timeline", deferred there from "Applicant list" on 2026-10-29).

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-29
"""

import sqlalchemy as sa

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column(
            "stage_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # history: the latest recorded stage move, else the application itself
    op.execute(
        """
        UPDATE applications a
        SET stage_changed_at = COALESCE(
            (SELECT max(l.created_at) FROM activity_log l
             WHERE l.application_id = a.id AND l.type = 'stage.changed'),
            a.created_at)
        """
    )
    # the server default stays: code that predates the column (a rolling
    # deploy, the compose image until rebuilt) keeps inserting rows


def downgrade() -> None:
    op.drop_column("applications", "stage_changed_at")
