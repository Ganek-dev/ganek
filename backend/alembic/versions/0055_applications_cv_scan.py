"""applications.cv_scan_status + cv_scan_signature + cv_scanned_at
(board card "CV virus scanning (ClamAV container)")

NULL status = not scanned (no CV, scanning not configured, or uploaded
before this revision); pending / clean / infected / error otherwise.

Revision ID: 0055
Revises: 0054
Create Date: 2026-11-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("cv_scan_status", sa.String(length=16), nullable=True))
    op.add_column(
        "applications", sa.Column("cv_scan_signature", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "applications",
        sa.Column("cv_scanned_at", sa.DateTime(timezone=True), nullable=True),
    )
    # the worker's sweep looks for pending scans; keep that lookup cheap
    op.create_index(
        op.f("ix_applications_cv_scan_pending"),
        "applications",
        ["created_at"],
        postgresql_where=sa.text("cv_scan_status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_applications_cv_scan_pending"), table_name="applications")
    op.drop_column("applications", "cv_scanned_at")
    op.drop_column("applications", "cv_scan_signature")
    op.drop_column("applications", "cv_scan_status")
