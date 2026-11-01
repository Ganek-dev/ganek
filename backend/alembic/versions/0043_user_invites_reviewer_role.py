"""user_invites.role accepts 'reviewer': 0042 widened the CHECK on users only,
and reviewers join by invite.

Rollback note: 0042's downgrade demotes reviewer users to member, which grants
them recruiter access. Handle reviewer users before a rollback past 0043.

Revision ID: 0043
Revises: 0042
Create Date: 2026-11-01
"""

from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_user_invites_role"), "user_invites", type_="check")
    op.create_check_constraint(
        op.f("ck_user_invites_role"), "user_invites", "role IN ('admin', 'member', 'reviewer')"
    )


def downgrade() -> None:
    # delete rather than demote: a pending reviewer invite must not turn into
    # a member seat with recruiter access
    op.execute("DELETE FROM user_invites WHERE role = 'reviewer'")
    op.drop_constraint(op.f("ck_user_invites_role"), "user_invites", type_="check")
    op.create_check_constraint(
        op.f("ck_user_invites_role"), "user_invites", "role IN ('admin', 'member')"
    )
