"""difficulty: 3-level enum -> 1-5 integer scale

easy->2, medium->3, hard->4; the 1 and 5 extremes are assigned by a later
curation pass over the bank. Downgrade maps back by band (<=2 easy, 3 medium,
>=4 hard).

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-25
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_questions_difficulty", "questions", type_="check")
    op.execute(
        "UPDATE questions SET difficulty = CASE difficulty"
        " WHEN 'easy' THEN '2' WHEN 'medium' THEN '3' WHEN 'hard' THEN '4'"
        " ELSE '3' END"
    )
    op.execute(
        "ALTER TABLE questions ALTER COLUMN difficulty TYPE smallint USING difficulty::smallint"
    )
    op.create_check_constraint("ck_questions_difficulty", "questions", "difficulty BETWEEN 1 AND 5")


def downgrade() -> None:
    op.drop_constraint("ck_questions_difficulty", "questions", type_="check")
    op.execute(
        "ALTER TABLE questions ALTER COLUMN difficulty TYPE varchar(20)"
        " USING CASE WHEN difficulty <= 2 THEN 'easy'"
        " WHEN difficulty = 3 THEN 'medium' ELSE 'hard' END"
    )
    op.create_check_constraint(
        "ck_questions_difficulty", "questions", "difficulty IN ('easy', 'medium', 'hard')"
    )
