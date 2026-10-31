"""Screening questions (board card "Per-job screening questions"): the
question model and validator, DB-free. Preferred answers are recruiter
internal; the public view must never carry them."""

import re

import pytest
from pydantic import ValidationError

from app.services.screening import (
    ScreeningQuestion,
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
