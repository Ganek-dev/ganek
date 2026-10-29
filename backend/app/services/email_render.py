"""Template renderer for the four candidate stage mails (assessment invite,
assessment reminder, interview, rejection).

A ``Template`` is a subject and a plain-text body: paragraphs separated by
blank lines, ``{{placeholder}}`` tokens resolved from the sender's context.
The first paragraph is the heading. Each kind adds a fixed action block the
template cannot remove (the assessment link and details, the status link,
the "See open positions" button, the sign-off) inside the branded card
frame, so a workspace can change the words but never lose the link or the
privacy footer. Pure: no database, no request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Any

from app.services.email_frame import (
    DEFAULT_BRAND_PRIMARY,
    NEUTRAL_BAR,
    brand_foreground,
    card_html,
    paragraph,
    privacy_text,
)

KINDS: tuple[str, ...] = ("quiz_invite", "quiz_reminder", "stage_advance", "rejection")

_COMMON: tuple[str, ...] = ("candidate_name", "candidate_first_name", "job_title", "company_name")
PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "quiz_invite": _COMMON + ("question_count", "time_per_question", "valid_until"),
    "quiz_reminder": _COMMON + ("valid_until", "days_left", "expires_phrase", "days_left_phrase"),
    "stage_advance": _COMMON,
    "rejection": _COMMON + ("assessment_thanks",),
}

_TOKEN = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def _text(value: str) -> str:
    """Escape for HTML text content: quotes stay as typed (attribute values use ``escape``)."""
    return escape(value, quote=False)


_H1_STYLE = "margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;"
_SIGNOFF_STYLE = "margin: 22px 0 0; font-size: 14px; line-height: 21px; color: #3f3f46;"
ASSESSMENT_THANKS = (
    " We were glad you took the time to complete the assessment - "
    "a real person reviewed it, not a filter."
)


@dataclass(frozen=True)
class Template:
    subject: str
    body: str


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str


class TemplateError(ValueError):
    """A subject or body names placeholders the kind does not provide."""

    def __init__(self, placeholders: list[str]) -> None:
        self.placeholders = placeholders
        super().__init__("unknown placeholders: " + ", ".join(placeholders))


BUILTIN: dict[str, Template] = {
    "quiz_invite": Template(
        subject="Your {{company_name}} assessment - one step left",
        body=(
            "One step left, {{candidate_name}}\n"
            "\n"
            "Thanks for applying to {{job_title}}. To be shortlisted, take the short skills "
            "assessment - it's how we make sure your application is judged on skill, not keywords."
        ),
    ),
    "quiz_reminder": Template(
        subject="Your assessment link expires {{expires_phrase}}",
        body=(
            "Still in - {{days_left_phrase}}\n"
            "\n"
            "Your assessment for {{job_title}} is waiting. It takes about 10 minutes."
        ),
    ),
    "stage_advance": Template(
        subject="Next step: interviews at {{company_name}}",
        body=(
            "Good news, {{candidate_name}} - let's talk\n"
            "\n"
            "Your application for {{job_title}} stood out, and we'd like to move you to "
            "interviews. We'll follow up shortly with scheduling details."
        ),
    ),
    "rejection": Template(
        subject="Your application to {{company_name}}",
        body=(
            "Thank you, {{candidate_name}}\n"
            "\n"
            "We've finished reviewing applications for {{job_title}}, and we won't be moving "
            "forward with yours this time.\n"
            "\n"
            "This was a competitive round and the decision was close.{{assessment_thanks}}\n"
            "\n"
            "We'd genuinely welcome another application for a future role."
        ),
    ),
}


def validate(kind: str, subject: str, body: str) -> None:
    """Raise ``TemplateError`` naming every placeholder the kind does not provide."""
    if kind not in PLACEHOLDERS:
        raise ValueError(f"unknown email kind {kind!r}")
    allowed = set(PLACEHOLDERS[kind])
    unknown = sorted(
        {name for name in _TOKEN.findall(subject + "\n" + body) if name not in allowed}
    )
    if unknown:
        raise TemplateError(unknown)


def _valid_until(expires_at: datetime) -> str:
    return f"{expires_at:%a}, {expires_at:%b} {expires_at.day}"


def _values(kind: str, context: dict[str, Any]) -> dict[str, str]:
    name = str(context.get("candidate_name") or "")
    values: dict[str, str] = {
        "candidate_name": name,
        "candidate_first_name": name.split()[0] if name.split() else "",
        "job_title": str(context.get("job_title") or ""),
        "company_name": str(context.get("company_name") or ""),
    }
    expires_at = context.get("expires_at")
    if kind in ("quiz_invite", "quiz_reminder") and isinstance(expires_at, datetime):
        values["valid_until"] = _valid_until(expires_at)
    if kind == "quiz_invite":
        values["question_count"] = str(context.get("question_count") or "")
        seconds = context.get("seconds_per_question")
        values["time_per_question"] = f"{seconds}s" if seconds is not None else ""
    if kind == "quiz_reminder":
        days_left = int(context.get("days_left") or 0)
        values["days_left"] = str(days_left)
        if days_left <= 0:
            values["expires_phrase"], values["days_left_phrase"] = "today", "last day"
        elif days_left == 1:
            values["expires_phrase"], values["days_left_phrase"] = "in 1 day", "1 day left"
        else:
            values["expires_phrase"] = f"in {days_left} days"
            values["days_left_phrase"] = f"{days_left} days left"
    if kind == "rejection":
        values["assessment_thanks"] = (
            ASSESSMENT_THANKS if context.get("completed_assessment") else ""
        )
    return values


_BOLD = '<b style="font-weight: 600;">'


def _substitute(text: str, values: dict[str, str], *, html: bool = False) -> str:
    """Resolve placeholders. In HTML mode every literal segment and every
    value is escaped separately (a template is plain text, never markup),
    and the job title keeps the designed bold span."""
    out: list[str] = []
    position = 0
    for match in _TOKEN.finditer(text):
        name = match.group(1)
        if name not in values:
            raise KeyError(f"no value for placeholder {name!r}")
        literal = text[position : match.start()]
        value = values[name]
        if html:
            literal = _text(literal)
            value = _BOLD + _text(value) + "</b>" if name == "job_title" else _text(value)
        out.append(literal)
        out.append(value)
        position = match.end()
    tail = text[position:]
    out.append(_text(tail) if html else tail)
    return "".join(out)


def _paragraphs(body: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]


def _signoff(company_name: str, lead: str) -> tuple[str, str]:
    text = f"{lead}\nThe {company_name} hiring team\n"
    html = (
        f'<p style="{_SIGNOFF_STYLE}">{_text(lead)}<br><b style="font-weight: 600;">'
        f"The {_text(company_name)} hiring team</b></p>"
    )
    return text, html


def _action_block(
    kind: str, context: dict[str, Any], values: dict[str, str], brand: str, brand_fg: str
) -> tuple[str, str]:
    """(text, html) of the fixed block that follows the body for this kind."""
    company = values["company_name"]
    if kind == "quiz_invite":
        rows: list[tuple[str, str]] = [(values["question_count"], "questions, single choice")]
        if values["time_per_question"]:
            rows.append(
                (values["time_per_question"], "per question - each locks when time runs out")
            )
        rows.append(("1×", "one attempt - find a quiet 10 minutes"))
        quiz_url = str(context.get("quiz_url") or "")
        text = (
            "\n".join(f"  {figure:>4}  {label}" for figure, label in rows)
            + f"\n\nStart the assessment: {quiz_url}\n\n"
            + f"Link valid until {values['valid_until']} · works on any device\n"
        )
        details = "".join(
            f'<div style="margin-top: 6px; font-size: 13.5px; line-height: 20px; color: #3f3f46;">'
            f'<span style="font-family: monospace; font-size: 12px; color: {brand}; '
            f'font-weight: 600; display: inline-block; width: 30px;">{_text(figure)}</span>'
            f"<span>{_text(label)}</span></div>"
            for figure, label in rows
        )
        html = (
            f'<div style="margin-top: 20px; border: 1px solid #e4e4e7; border-radius: 10px; '
            f'padding: 16px 18px;">{details}</div>'
            f'<a href="{escape(quiz_url)}" style="margin-top: 22px; display: block; '
            f"text-align: center; height: 46px; line-height: 46px; background: {brand}; "
            f"color: {brand_fg}; border-radius: 10px; font-size: 15px; font-weight: 600; "
            f'text-decoration: none;">Start the assessment</a>'
            f'<div style="margin-top: 12px; text-align: center; font-family: monospace; '
            f'font-size: 11px; color: #a1a1aa;">'
            f"link valid until {_text(values['valid_until'])} · works on any device</div>"
        )
        return text, html
    if kind == "quiz_reminder":
        quiz_url = str(context.get("quiz_url") or "")
        text = f"The link stops working after {values['valid_until']}.\n\nTake it now: {quiz_url}\n"
        html = (
            f'<div style="margin-top: 18px; border: 1px solid #f0d9b5; background: #fdf9f2; '
            f'border-radius: 10px; padding: 12px 16px; font-size: 13px; color: #7c5a2b;">'
            f'Link stops working after <b style="font-weight: 600;">'
            f"{_text(values['valid_until'])}</b>.</div>"
            f'<a href="{escape(quiz_url)}" style="margin-top: 20px; display: block; '
            f"text-align: center; height: 46px; line-height: 46px; background: {brand}; "
            f"color: {brand_fg}; border-radius: 10px; font-size: 15px; font-weight: 600; "
            f'text-decoration: none;">Take it now - ~10 min</a>'
        )
        return text, html
    if kind == "stage_advance":
        status_url = context.get("status_url")
        sign_text, sign_html = _signoff(company, "Looking forward to it,")
        text = (f"Track your application: {status_url}\n\n" if status_url else "") + sign_text
        html = sign_html + (
            f'<div style="margin-top: 16px; font-family: monospace; font-size: 11px; '
            f'color: #a1a1aa;"><a href="{escape(str(status_url))}" style="color: #a1a1aa; '
            f'text-decoration: underline;">application status</a></div>'
            if status_url
            else ""
        )
        return text, html
    careers_url = str(context.get("careers_url") or "")
    sign_text, sign_html = _signoff(company, "All the best,")
    text = f"See open positions: {careers_url}\n\n" + sign_text
    html = (
        f'<div style="margin-top: 20px; text-align: center;">'
        f'<a href="{escape(careers_url)}" style="display: inline-block; height: 40px; '
        f"line-height: 40px; padding: 0 20px; border: 1.5px solid #d4d4d8; "
        f"border-radius: 10px; font-size: 13.5px; font-weight: 600; color: #3f3f46; "
        f'text-decoration: none;">See open positions</a></div>' + sign_html
    )
    return text, html


def render(kind: str, template: Template, context: dict[str, Any]) -> Rendered:
    """Subject, plain text and HTML for one candidate email.

    ``context`` is the sender's keyword arguments minus ``to`` and ``ref``.
    """
    if kind not in PLACEHOLDERS:
        raise ValueError(f"unknown email kind {kind!r}")
    values = _values(kind, context)
    subject = _substitute(template.subject, values)
    paragraphs = _paragraphs(_substitute(template.body, values))
    heading, rest = (paragraphs[0], paragraphs[1:]) if paragraphs else ("", [])
    html_paragraphs = _paragraphs(_substitute(template.body, values, html=True))
    html_heading, html_rest = (
        (html_paragraphs[0], html_paragraphs[1:]) if html_paragraphs else ("", [])
    )

    if kind == "rejection":
        brand, brand_fg, bar = DEFAULT_BRAND_PRIMARY, "#ffffff", NEUTRAL_BAR
    else:
        brand = str(context.get("brand_primary") or DEFAULT_BRAND_PRIMARY)
        brand_fg = brand_foreground(brand)
        bar = brand
    action_text, action_html = _action_block(kind, context, values, brand, brand_fg)

    text = (
        "\n\n".join([heading, *rest])
        + "\n\n"
        + action_text
        + privacy_text(context.get("privacy_url"))
    )
    content = (
        f'<h1 style="{_H1_STYLE}">{html_heading}</h1>'
        + "".join(paragraph(part.replace("\n", "<br>")) for part in html_rest)
        + action_html
    )
    controller = context.get("controller_name")
    html = card_html(
        bar_color=bar,
        brand=brand,
        brand_fg=brand_fg,
        safe_company=_text(values["company_name"]),
        content=content,
        safe_controller=_text(str(controller)) if controller else None,
        privacy_url=context.get("privacy_url"),
    )
    return Rendered(subject=subject, text=text, html=html)
