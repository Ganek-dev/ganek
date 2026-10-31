"""The template renderer behind the four candidate stage mails: built-in
templates reproduce the designed emails, placeholders resolve from the
sender's context, HTML escapes what text keeps raw, and validation names
unknown placeholders. Pure, no database."""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.services.email_frame import NEUTRAL_BAR
from app.services.email_render import (
    BUILTIN,
    KINDS,
    PLACEHOLDERS,
    Template,
    TemplateError,
    render,
    validate,
)

EXPIRES = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)

REJECTION_CTX: dict[str, Any] = {
    "candidate_name": "Marta Vidal",
    "job_title": "Senior Frontend Engineer",
    "company_name": "ACME Ganek",
    "careers_url": "https://jobs.example.com/",
    "completed_assessment": True,
    "controller_name": None,
    "privacy_url": None,
}

INVITE_CTX: dict[str, Any] = {
    "candidate_name": "Marta Vidal",
    "job_title": "Senior Frontend Engineer",
    "company_name": "ACME Ganek",
    "brand_primary": "#3d5afe",
    "quiz_url": "https://jobs.example.com/quiz/tok123",
    "question_count": 12,
    "seconds_per_question": 25,
    "expires_at": EXPIRES,
    "controller_name": None,
    "privacy_url": None,
}


def _reminder_ctx(days_left: int) -> dict[str, Any]:
    return {
        "candidate_name": "Marta Vidal",
        "job_title": "Senior Frontend Engineer",
        "company_name": "ACME Ganek",
        "brand_primary": None,
        "quiz_url": "https://jobs.example.com/quiz/tok123",
        "expires_at": EXPIRES,
        "days_left": days_left,
        "controller_name": None,
        "privacy_url": None,
    }


def _advance_ctx(status_url: str | None) -> dict[str, Any]:
    return {
        "candidate_name": "Marta Vidal",
        "job_title": "Senior Frontend Engineer",
        "company_name": "ACME Ganek",
        "brand_primary": "#3d5afe",
        "status_url": status_url,
        "controller_name": None,
        "privacy_url": None,
    }


def test_builtin_rejection_matches_the_designed_email() -> None:
    r = render("rejection", BUILTIN["rejection"], REJECTION_CTX)
    assert r.subject == "Your application to ACME Ganek"
    assert r.text.startswith(
        "Thank you, Marta Vidal\n\nWe've finished reviewing applications for Senior Frontend "
        "Engineer, and we won't be moving forward with yours this time.\n\nThis was a competitive "
        "round and the decision was close. We were glad you took the time to complete the "
        "assessment - a real person reviewed it, not a filter.\n\nWe'd genuinely welcome another "
        "application for a future role.\n\nSee open positions: https://jobs.example.com/\n\n"
        "All the best,\nThe ACME Ganek hiring team\n"
    )
    assert "Thank you, Marta Vidal</h1>" in r.html
    # the designed emails bold the job title; a template cannot lose that
    assert '<b style="font-weight: 600;">Senior Frontend Engineer</b>' in r.html
    assert NEUTRAL_BAR in r.html
    assert "See open positions</a>" in r.html
    assert r.html.index("See open positions</a>") < r.html.index("All the best,")


def test_assessment_thanks_is_empty_without_an_attempt() -> None:
    r = render("rejection", BUILTIN["rejection"], {**REJECTION_CTX, "completed_assessment": False})
    assert "a real person reviewed it" not in r.text
    assert "the decision was close.\n\n" in r.text


@pytest.mark.parametrize(
    ("days_left", "subject", "heading"),
    [
        (0, "Your assessment link expires today", "Still in - last day"),
        (1, "Your assessment link expires in 1 day", "Still in - 1 day left"),
        (3, "Your assessment link expires in 3 days", "Still in - 3 days left"),
    ],
)
def test_reminder_phrases(days_left: int, subject: str, heading: str) -> None:
    r = render("quiz_reminder", BUILTIN["quiz_reminder"], _reminder_ctx(days_left))
    assert r.subject == subject
    assert r.text.startswith(heading + "\n\n")
    assert "The link stops working after Fri, Jul 31." in r.text
    assert "Take it now: https://jobs.example.com/quiz/tok123" in r.text
    assert f"{heading}</h1>" in r.html


def test_invite_action_block_lists_details_and_link() -> None:
    r = render("quiz_invite", BUILTIN["quiz_invite"], INVITE_CTX)
    assert r.subject == "Your ACME Ganek assessment - one step left"
    assert r.text.startswith(
        "One step left, Marta Vidal\n\nThanks for applying to Senior Frontend Engineer."
    )
    assert "  12  questions, single choice" in r.text
    assert "25s" in r.text
    assert "one attempt" in r.text
    assert "Start the assessment: https://jobs.example.com/quiz/tok123" in r.text
    assert "Link valid until Fri, Jul 31" in r.text
    assert "#3d5afe" in r.html
    assert "Start the assessment</a>" in r.html
    assert '<b style="font-weight: 600;">Senior Frontend Engineer</b>' in r.html


def test_invite_omits_the_timer_row_without_a_limit() -> None:
    r = render("quiz_invite", BUILTIN["quiz_invite"], {**INVITE_CTX, "seconds_per_question": None})
    assert "per question" not in r.text
    assert "per question" not in r.html


def test_stage_advance_links_the_status_page_only_when_given() -> None:
    with_link = render(
        "stage_advance", BUILTIN["stage_advance"], _advance_ctx("https://jobs.example.com/s/tok")
    )
    assert "Track your application: https://jobs.example.com/s/tok" in with_link.text
    assert 'href="https://jobs.example.com/s/tok"' in with_link.html
    without = render("stage_advance", BUILTIN["stage_advance"], _advance_ctx(None))
    assert "Track your application" not in without.text
    for r in (with_link, without):
        assert r.subject == "Next step: interviews at ACME Ganek"
        assert r.text.endswith("Looking forward to it,\nThe ACME Ganek hiring team\n")
        assert "Good news, Marta Vidal - let's talk</h1>" in r.html


def test_values_are_html_escaped_and_text_kept_raw() -> None:
    r = render(
        "rejection",
        BUILTIN["rejection"],
        {**REJECTION_CTX, "candidate_name": "Marta <b>Vidal</b> & Co"},
    )
    assert "Marta <b>Vidal</b> & Co" in r.text
    assert "Marta &lt;b&gt;Vidal&lt;/b&gt; &amp; Co" in r.html
    assert "<b>Vidal" not in r.html
    # literal template text escapes too: a template is plain text, never markup
    r = render(
        "rejection",
        Template("S", "Head\n\n<i>{{job_title}}</i> & {{company_name}}"),
        {**REJECTION_CTX, "job_title": "C++ & <Go>", "company_name": "A&B <Co>"},
    )
    assert "<i>C++ & <Go></i> & A&B <Co>" in r.text
    bold = '<b style="font-weight: 600;">C++ &amp; &lt;Go&gt;</b>'
    assert f"&lt;i&gt;{bold}&lt;/i&gt; &amp; A&amp;B &lt;Co&gt;" in r.html


def test_single_line_breaks_become_br_and_empty_paragraphs_drop() -> None:
    template = Template("S", "Head\n\nLine one\nline two\n\n{{assessment_thanks}}\n\nEnd")
    r = render("rejection", template, {**REJECTION_CTX, "completed_assessment": False})
    assert "Line one<br>line two" in r.html
    assert r.text.startswith("Head\n\nLine one\nline two\n\nEnd\n\nSee open positions: ")
    assert "\n\n\n" not in r.text


def test_privacy_text_and_controller_reach_both_parts() -> None:
    r = render(
        "rejection",
        BUILTIN["rejection"],
        {
            **REJECTION_CTX,
            "controller_name": "ACME Ganek Sp. z o.o.",
            "privacy_url": "https://jobs.example.com/c/acme/privacy",
        },
    )
    assert "Privacy & your data: https://jobs.example.com/c/acme/privacy" in r.text
    assert "Sent by Ganek on behalf of ACME Ganek Sp. z o.o." in r.html


def test_validate_rejects_unknown_placeholders() -> None:
    with pytest.raises(TemplateError) as info:
        validate("rejection", "Hi {{nope}}", "x {{candidate_name}} {{other}} {{nope}}")
    assert info.value.placeholders == ["nope", "other"]


@pytest.mark.parametrize("kind", KINDS)
def test_validate_accepts_every_documented_placeholder(kind: str) -> None:
    validate(kind, "S", " ".join("{{" + name + "}}" for name in PLACEHOLDERS[kind]))


def test_validate_unknown_kind() -> None:
    with pytest.raises(ValueError, match="kind"):
        validate("message", "S", "B")


def test_rendered_body_is_the_paragraphs_before_the_action_block() -> None:
    ctx = {**REJECTION_CTX, "completed_assessment": False}
    rendered = render("rejection", BUILTIN["rejection"], ctx)
    assert rendered.body == (
        "Thank you, Marta Vidal\n"
        "\n"
        "We've finished reviewing applications for Senior Frontend Engineer, and we won't be "
        "moving forward with yours this time.\n"
        "\n"
        "This was a competitive round and the decision was close.\n"
        "\n"
        "We'd genuinely welcome another application for a future role."
    )
    assert rendered.text.startswith(rendered.body + "\n\nSee open positions:")


def test_literal_render_keeps_braces_and_escapes_html() -> None:
    template = Template(
        subject="Hi {{candidate_name}} & co", body="Line <b>one</b>\n\n{{job_title}} stays"
    )
    rendered = render("stage_advance", template, _advance_ctx("https://s/x"), literal=True)
    assert rendered.subject == "Hi {{candidate_name}} & co"
    assert rendered.body == "Line <b>one</b>\n\n{{job_title}} stays"
    assert "<h1" in rendered.html and "Line &lt;b&gt;one&lt;/b&gt;</h1>" in rendered.html
    assert "{{job_title}} stays</p>" in rendered.html
    assert "Looking forward to it," in rendered.text and "application status" in rendered.html
