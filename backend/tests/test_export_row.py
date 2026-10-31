"""export_row: the flat shape of one applicant line (card D9), DB-free."""

from datetime import UTC, datetime

from app.models import Application, ApplicationStage, Candidate, Job
from app.models.quiz import AttemptStatus, QuizAttempt
from app.services.applications import EXPORT_COLUMNS, export_row


def _application(**overrides: object) -> Application:
    application = Application(
        candidate=Candidate(name="Jane Applicant", email="jane@example.com"),
        job=Job(title="Backend Engineer"),
        stage=ApplicationStage.SCREENING,
        created_at=datetime(2026, 10, 1, 9, 30, tzinfo=UTC),
        decided_at=None,
        source="linkedin",
        cv_filename="jane.pdf",
        message="Hi there",
    )
    for key, value in overrides.items():
        setattr(application, key, value)
    return application


def test_row_without_quiz_has_empty_quiz_columns() -> None:
    row = export_row(_application(quiz_attempts=[]))
    assert tuple(row) == EXPORT_COLUMNS
    assert row["candidate_email"] == "jane@example.com"
    assert row["job"] == "Backend Engineer"
    assert row["stage"] == "screening"
    assert row["applied_at"] == "2026-10-01T09:30:00+00:00"
    assert row["decided_at"] == ""
    assert row["source"] == "linkedin"
    assert (row["quiz_status"], row["quiz_score_percent"], row["integrity_flags"]) == ("", "", "")


def test_row_uses_latest_attempt_score_and_flag_summaries() -> None:
    older = QuizAttempt(status=AttemptStatus.EXPIRED, score=None, integrity={})
    latest = QuizAttempt(
        status=AttemptStatus.COMPLETED,
        score=0.834,
        completed_at=datetime(2026, 10, 2, 10, 0, tzinfo=UTC),
        integrity={
            "flags": [
                {"code": "tab_hidden", "summary": "left the tab 2x (~5s)", "detail": "..."},
                {"code": "paste", "summary": "pasted into 1 answer", "detail": "..."},
            ],
            "events": [{"type": "blur", "duration_ms": 5000}],
        },
    )
    row = export_row(_application(quiz_attempts=[older, latest]))
    assert row["quiz_status"] == "completed"
    assert row["quiz_score_percent"] == 83
    assert row["quiz_completed_at"] == "2026-10-02T10:00:00+00:00"
    assert row["integrity_flags"] == "left the tab 2x (~5s); pasted into 1 answer"
    # only summaries travel, never the raw event stream or anything per-question
    assert "blur" not in str(row) and "detail" not in str(row)


def test_row_carries_the_extra_time_multiplier() -> None:
    plain = export_row(
        _application(quiz_attempts=[QuizAttempt(status=AttemptStatus.PENDING, integrity={})])
    )
    assert plain["quiz_time_multiplier"] == ""
    granted = export_row(
        _application(
            quiz_attempts=[
                QuizAttempt(
                    status=AttemptStatus.COMPLETED,
                    score=0.5,
                    time_multiplier=2.0,
                    integrity={"accommodation": {"time_multiplier": 2.0, "by_user_id": "u1"}},
                )
            ]
        )
    )
    assert granted["quiz_time_multiplier"] == "2x"
    # who granted it stays inside the app, like every other internal id
    assert "u1" not in str(granted)


def test_screening_mismatches_counts_false_matches_and_blanks_without_answers() -> None:
    answers = [{"match": False}, {"match": None}, {"match": True}, {"match": False}]
    row = export_row(_application(quiz_attempts=[], screening_answers=answers))
    assert row["screening_mismatches"] == "2"
    assert (
        export_row(_application(quiz_attempts=[], screening_answers=[]))["screening_mismatches"]
        == ""
    )
    assert EXPORT_COLUMNS.index("screening_mismatches") == EXPORT_COLUMNS.index("message") + 1
