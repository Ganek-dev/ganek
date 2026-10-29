"""Integrity flags name questions by serve order: "Q3" is the third question
the candidate saw, the same numbering the review page gives the event log
and the session timeline. Pure unit tests, no database."""

from datetime import UTC, datetime, timedelta

from app.models import AttemptAnswer
from app.services.quiz import _integrity_flags

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)


def _answers(question_ids: list[str], *, seconds: float = 8.0) -> list[AttemptAnswer]:
    """Answered questions in serve order, one every ``seconds`` seconds."""
    answers: list[AttemptAnswer] = []
    for index, question_id in enumerate(question_ids):
        served = T0 + timedelta(seconds=index * (seconds + 1))
        answers.append(
            AttemptAnswer(
                question_id=question_id,
                option_order=["a", "b", "c", "d"],
                served_at=served,
                deadline_at=served + timedelta(seconds=30),
                answered_at=served + timedelta(seconds=seconds),
                answer_key="a",
                is_correct=True,
            )
        )
    return answers


def _flag(flags: list[dict[str, object]], code: str) -> dict[str, object]:
    return next(flag for flag in flags if flag["code"] == code)


def test_tab_hidden_names_the_questions_by_serve_order() -> None:
    answers = _answers(["py-1", "py-2", "py-3", "py-4", "py-5", "py-6"])
    integrity = {
        "blur_count": 2,
        "blur_total_ms": 20_000,
        "events": [
            {"type": "blur", "question_id": "py-1", "duration_ms": 12_000},
            {"type": "blur", "question_id": "py-6", "duration_ms": 8_000},
        ],
    }

    flag = _flag(_integrity_flags(integrity, answers), "tab_hidden")

    assert flag["summary"] == "left the tab 2x (~20s)"
    assert str(flag["detail"]).endswith("Occurred during Q1, Q6.")
    assert flag["question_ids"] == ["py-1", "py-6"]


def test_positions_follow_the_order_served_not_the_id_sort() -> None:
    # served c, a, b: a blur on "b" happened on the third question
    answers = _answers(["qc", "qa", "qb"])
    integrity = {
        "blur_count": 1,
        "blur_total_ms": 5_000,
        "paste_count": 1,
        "events": [
            {"type": "blur", "question_id": "qb", "duration_ms": 5_000},
            {"type": "paste", "question_id": "qa", "duration_ms": None},
        ],
    }

    flags = _integrity_flags(integrity, answers)

    assert str(_flag(flags, "tab_hidden")["detail"]).endswith("Occurred during Q3.")
    assert str(_flag(flags, "paste")["detail"]).endswith("Occurred during Q2.")


def test_very_fast_lists_the_fast_answers_by_serve_order() -> None:
    answers = _answers(["qz", "qy"], seconds=1.5)

    flag = _flag(_integrity_flags({}, answers), "very_fast")

    assert str(flag["detail"]).endswith("Fastest answers: Q1, Q2.")
    assert flag["question_ids"] == ["qz", "qy"]


def test_an_event_without_a_question_adds_no_position() -> None:
    answers = _answers(["py-1"])
    integrity = {
        "blur_count": 1,
        "blur_total_ms": 1_000,
        "events": [{"type": "blur", "question_id": None, "duration_ms": 1_000}],
    }

    flag = _flag(_integrity_flags(integrity, answers), "tab_hidden")

    assert "Occurred during" not in str(flag["detail"])
    assert flag["question_ids"] == []
