"""Per-job screening questions (board card "Per-job screening questions on
the apply form"): the question model shared by the company default set,
the job's list and the public apply form, plus the candidate's answers.

Hard rule 5 applies in full: an answer never moves a stage, never sends a
mail, never touches a score. A preferred answer only produces a mark the
recruiter reads. ``preferred`` is recruiter-internal and leaves this module
only through recruiter-facing schemas; ``public_view`` strips it.
"""

import re
import secrets
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ScreeningQuestionType = Literal["yes_no", "single_choice", "short_text", "acknowledgment"]

MAX_QUESTIONS = 20
PROMPT_MAX = 300
OPTION_MAX = 100
OPTIONS_MIN = 2
OPTIONS_MAX = 10
TEXT_ANSWER_MAX = 500

_ID_RE = re.compile(r"^sq_[0-9a-f]{8}$")
YES_NO = ("yes", "no")


def new_question_id() -> str:
    return "sq_" + secrets.token_hex(4)


class ScreeningQuestion(BaseModel):
    """One question as the job (or the company default set) stores it."""

    id: str = Field(pattern=_ID_RE.pattern)
    type: ScreeningQuestionType
    prompt: str = Field(min_length=1, max_length=PROMPT_MAX)
    options: list[str] | None = None
    preferred: str | None = None
    required: bool = False

    @field_validator("prompt", mode="before")
    @classmethod
    def _strip_prompt(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("options", mode="before")
    @classmethod
    def _strip_options(cls, value: object) -> object:
        if isinstance(value, list):
            return [item.strip() if isinstance(item, str) else item for item in value]
        return value

    @model_validator(mode="after")
    def _type_rules(self) -> "ScreeningQuestion":
        if self.type == "single_choice":
            if self.options is None or not OPTIONS_MIN <= len(self.options) <= OPTIONS_MAX:
                raise ValueError(f"single choice needs {OPTIONS_MIN} to {OPTIONS_MAX} options")
            if any(not 1 <= len(option) <= OPTION_MAX for option in self.options):
                raise ValueError(f"options must be 1 to {OPTION_MAX} characters")
            if len(set(self.options)) != len(self.options):
                raise ValueError("options must be unique")
            if self.preferred is not None and self.preferred not in self.options:
                raise ValueError("preferred answer must be one of the options")
            return self
        if self.options is not None:
            raise ValueError("only single choice questions have options")
        if self.type == "yes_no":
            if self.preferred is not None and self.preferred not in YES_NO:
                raise ValueError("preferred answer must be yes or no")
            return self
        if self.type == "acknowledgment":
            # always required, never a preferred answer: accepting is the only answer
            self.required = True
            self.preferred = None
            return self
        if self.preferred is not None:
            raise ValueError("short text questions have no preferred answer")
        return self


def validate_questions(raw: list[dict[str, Any]]) -> list[ScreeningQuestion]:
    """The list as the admin API receives it: ids filled in when missing,
    duplicates and the sanity ceiling refused (ValueError -> 422)."""
    if len(raw) > MAX_QUESTIONS:
        raise ValueError(f"at most {MAX_QUESTIONS} screening questions")
    if any(not isinstance(item, dict) for item in raw):
        # a bare string or null would TypeError on the unpack below, which
        # pydantic does not turn into a 422
        raise ValueError("each screening question must be an object")
    questions = [
        ScreeningQuestion.model_validate({**item, "id": item.get("id") or new_question_id()})
        for item in raw
    ]
    ids = [question.id for question in questions]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate question id")
    return questions


def public_view(questions: list[ScreeningQuestion]) -> list[dict[str, Any]]:
    """What a candidate may see: never ``preferred``."""
    return [
        {
            "id": question.id,
            "type": question.type,
            "prompt": question.prompt,
            "options": question.options,
            "required": question.required,
        }
        for question in questions
    ]


# --- answers ----------------------------------------------------------------


class ScreeningAnswerIn(BaseModel):
    """One answer as the apply form posts it. ``answer`` is "yes"/"no", an
    option's text, free text, ``True`` for an acknowledgment, or ``None``
    for a skipped optional question."""

    question_id: str = Field(pattern=_ID_RE.pattern)
    answer: str | bool | None = None


class InvalidAnswers(ValueError):
    """Answers that do not fit the job's questions; ``errors`` lists one
    ``{"question_id", "reason"}`` per problem so the form can mark rows."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__("invalid screening answers")
        self.errors = errors


def _normalize(question: ScreeningQuestion, raw: str | bool | None) -> str | bool | None:
    """The stored answer or None for "unanswered"; raises ValueError when
    the value does not fit the question type."""
    if raw is None:
        return None
    if question.type == "acknowledgment":
        if raw is True:
            return True
        raise ValueError("must be accepted")
    if not isinstance(raw, str):
        raise ValueError("must be text")
    value = raw.strip()
    if value == "":
        return None
    if question.type == "yes_no":
        if value not in YES_NO:
            raise ValueError("must be yes or no")
        return value
    if question.type == "single_choice":
        if question.options is None or value not in question.options:
            raise ValueError("must be one of the options")
        return value
    if len(value) > TEXT_ANSWER_MAX:
        raise ValueError(f"at most {TEXT_ANSWER_MAX} characters")
    return value


def build_answers(
    questions: list[ScreeningQuestion], answers: list[ScreeningAnswerIn]
) -> list[dict[str, Any]]:
    """The write-once snapshot stored on the application: one object per
    question in the job's order, with the question as it was asked, the
    answer (None when skipped) and ``match`` against the preferred answer
    (None when there is none or the question was skipped). Required
    questions without an answer, unknown ids and ill-fitting values raise
    ``InvalidAnswers`` with every problem collected."""
    by_id = {question.id: question for question in questions}
    errors: list[dict[str, str]] = []
    given: dict[str, str | bool | None] = {}
    for item in answers:
        if item.question_id not in by_id:
            errors.append({"question_id": item.question_id, "reason": "unknown question"})
            continue
        if item.question_id in given:
            errors.append({"question_id": item.question_id, "reason": "answered twice"})
            continue
        given[item.question_id] = item.answer
    out: list[dict[str, Any]] = []
    for question in questions:
        try:
            answer = _normalize(question, given.get(question.id))
        except ValueError as exc:
            errors.append({"question_id": question.id, "reason": str(exc)})
            continue
        if answer is None and question.required:
            errors.append({"question_id": question.id, "reason": "required"})
            continue
        match: bool | None = (
            None if question.preferred is None or answer is None else answer == question.preferred
        )
        out.append(
            {
                "question_id": question.id,
                "type": question.type,
                "prompt": question.prompt,
                "options": question.options,
                "preferred": question.preferred,
                "answer": answer,
                "match": match,
            }
        )
    if errors:
        raise InvalidAnswers(errors)
    return out
