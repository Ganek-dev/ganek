"""Screening questions (board card "Per-job screening questions"): the
question model and validator, DB-free. Preferred answers are recruiter
internal; the public view must never carry them."""

import re

import pytest
from pydantic import ValidationError

from app.services.screening import (
    InvalidAnswers,
    ScreeningAnswerIn,
    ScreeningQuestion,
    build_answers,
    new_question_id,
    public_view,
    validate_questions,
)

ID = "sq_00000001"


def test_id_is_generated_when_missing() -> None:
    [q] = validate_questions([{"type": "yes_no", "prompt": "Can you work in Germany?"}])
    assert re.fullmatch(r"sq_[0-9a-f]{8}", q.id)


def test_new_question_id_format() -> None:
    assert re.fullmatch(r"sq_[0-9a-f]{8}", new_question_id())


def test_acknowledgment_is_always_required_and_has_no_preferred() -> None:
    [q] = validate_questions(
        [
            {
                "type": "acknowledgment",
                "prompt": "I confirm the above is accurate",
                "required": False,
                "preferred": "yes",
            }
        ]
    )
    assert q.required is True
    assert q.preferred is None
    assert q.options is None


def test_single_choice_needs_two_to_ten_unique_options() -> None:
    with pytest.raises(ValidationError):
        ScreeningQuestion(id=ID, type="single_choice", prompt="Days on site?", options=["1"])
    with pytest.raises(ValidationError):
        ScreeningQuestion(id=ID, type="single_choice", prompt="Days on site?", options=["1", "1"])
    with pytest.raises(ValidationError):
        ScreeningQuestion(
            id=ID, type="single_choice", prompt="Days on site?", options=[str(i) for i in range(11)]
        )
    with pytest.raises(ValidationError):
        ScreeningQuestion(id=ID, type="single_choice", prompt="Days on site?", options=None)


def test_preferred_must_be_an_option_or_yes_no() -> None:
    with pytest.raises(ValidationError):
        ScreeningQuestion(
            id=ID, type="single_choice", prompt="Days?", options=["0", "1-2"], preferred="3"
        )
    with pytest.raises(ValidationError):
        ScreeningQuestion(id=ID, type="yes_no", prompt="Permit?", preferred="maybe")
    with pytest.raises(ValidationError):
        ScreeningQuestion(id=ID, type="short_text", prompt="Notice period?", preferred="4 weeks")
    ok = ScreeningQuestion(id=ID, type="yes_no", prompt="Permit?", preferred="yes")
    assert ok.preferred == "yes"


def test_options_only_for_single_choice() -> None:
    with pytest.raises(ValidationError):
        ScreeningQuestion(id=ID, type="yes_no", prompt="Permit?", options=["yes", "no"])


def test_prompt_length_and_strip() -> None:
    [q] = validate_questions([{"type": "short_text", "prompt": "  Notice period?  "}])
    assert q.prompt == "Notice period?"
    with pytest.raises(ValidationError):
        ScreeningQuestion(id=ID, type="short_text", prompt="x" * 301)
    with pytest.raises(ValidationError):
        ScreeningQuestion(id=ID, type="short_text", prompt="   ")


def test_option_text_is_stripped_and_capped() -> None:
    [q] = validate_questions(
        [{"type": "single_choice", "prompt": "Days?", "options": [" 0 ", "1-2"]}]
    )
    assert q.options == ["0", "1-2"]
    with pytest.raises(ValidationError):
        ScreeningQuestion(id=ID, type="single_choice", prompt="Days?", options=["a", "b" * 101])


def test_id_format_is_enforced() -> None:
    with pytest.raises(ValidationError):
        ScreeningQuestion(id="nope", type="yes_no", prompt="Permit?")


def test_duplicate_ids_rejected_and_ceiling_is_twenty() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        validate_questions(
            [
                {"id": ID, "type": "yes_no", "prompt": "a"},
                {"id": ID, "type": "yes_no", "prompt": "b"},
            ]
        )
    with pytest.raises(ValueError, match="20"):
        validate_questions([{"type": "yes_no", "prompt": f"q{i}"} for i in range(21)])
    assert len(validate_questions([{"type": "yes_no", "prompt": f"q{i}"} for i in range(20)])) == 20


def test_public_view_strips_preferred() -> None:
    [q] = validate_questions([{"type": "yes_no", "prompt": "Permit?", "preferred": "yes"}])
    assert public_view([q]) == [
        {"id": q.id, "type": "yes_no", "prompt": "Permit?", "options": None, "required": False}
    ]


# --- answers: validation against the job's list and the write-once snapshot --


def _qs() -> list[ScreeningQuestion]:
    return validate_questions(
        [
            {
                "id": "sq_00000001",
                "type": "yes_no",
                "prompt": "Permit?",
                "preferred": "yes",
                "required": True,
            },
            {
                "id": "sq_00000002",
                "type": "single_choice",
                "prompt": "Days?",
                "options": ["0", "1-2", "3+"],
                "preferred": "1-2",
            },
            {"id": "sq_00000003", "type": "short_text", "prompt": "Notice period?"},
            {"id": "sq_00000004", "type": "acknowledgment", "prompt": "I confirm"},
        ]
    )


def A(question_id: str, answer: str | bool | None) -> ScreeningAnswerIn:  # noqa: N802 - test shorthand
    return ScreeningAnswerIn(question_id=question_id, answer=answer)


def test_build_answers_snapshots_and_matches() -> None:
    out = build_answers(
        _qs(),
        [
            A("sq_00000001", "no"),
            A("sq_00000002", "1-2"),
            A("sq_00000003", "  4 weeks "),
            A("sq_00000004", True),
        ],
    )
    assert [o["question_id"] for o in out] == [q.id for q in _qs()]
    assert [o["match"] for o in out] == [False, True, None, None]
    assert out[0]["prompt"] == "Permit?"
    assert out[0]["preferred"] == "yes"
    assert out[1]["options"] == ["0", "1-2", "3+"]
    assert out[2]["answer"] == "4 weeks"
    assert out[3]["answer"] is True
    assert set(out[0]) == {
        "question_id",
        "type",
        "prompt",
        "options",
        "preferred",
        "answer",
        "match",
    }


def test_skipped_optional_is_recorded_as_null() -> None:
    out = build_answers(_qs(), [A("sq_00000001", "yes"), A("sq_00000004", True)])
    assert out[1]["answer"] is None
    assert out[1]["match"] is None
    assert out[2]["answer"] is None


def test_whitespace_text_counts_as_unanswered() -> None:
    out = build_answers(
        _qs(), [A("sq_00000001", "yes"), A("sq_00000003", "   "), A("sq_00000004", True)]
    )
    assert out[2]["answer"] is None


def test_required_missing_is_refused_with_the_question_id() -> None:
    with pytest.raises(InvalidAnswers) as excinfo:
        build_answers(_qs(), [A("sq_00000004", True)])
    assert {e["question_id"] for e in excinfo.value.errors} == {"sq_00000001"}


def test_unknown_id_bad_option_false_ack_and_long_text_are_refused() -> None:
    ok = [A("sq_00000001", "yes"), A("sq_00000004", True)]
    with pytest.raises(InvalidAnswers):
        build_answers(_qs(), [*ok, A("sq_99999999", "x")])
    with pytest.raises(InvalidAnswers):
        build_answers(_qs(), [*ok, A("sq_00000002", "7")])
    with pytest.raises(InvalidAnswers):
        build_answers(_qs(), [A("sq_00000001", "yes"), A("sq_00000004", False)])
    with pytest.raises(InvalidAnswers):
        build_answers(_qs(), [*ok, A("sq_00000003", "x" * 501)])
    with pytest.raises(InvalidAnswers):
        build_answers(_qs(), [A("sq_00000001", "maybe"), A("sq_00000004", True)])


def test_no_questions_no_answers_is_empty_and_extra_answers_refused() -> None:
    assert build_answers([], []) == []
    with pytest.raises(InvalidAnswers):
        build_answers([], [A("sq_00000001", "yes")])
