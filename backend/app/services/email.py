"""Outbound email. SMTP when configured, logged no-op otherwise.

Sending must never break a user-facing flow: callers schedule sends as
background tasks and this module swallows transport errors with a log.
(Queue-based delivery via arq arrives with later milestones.)
"""

import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage
from html import escape

from app.core.config import settings

logger = logging.getLogger(__name__)

# Mirrors frontend lib/brand.ts: per-company brand color with a
# luminance-computed foreground; near-black default.
DEFAULT_BRAND_PRIMARY = "#18181b"


def _brand_foreground(color: str) -> str:
    """Text color that stays readable on the brand color (WCAG luminance)."""
    raw = color.lstrip("#")
    if len(raw) == 3:
        raw = "".join(c * 2 for c in raw)
    try:
        channels = [int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    except (ValueError, IndexError):
        return "#ffffff"
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return "#18181b" if luminance > 0.45 else "#ffffff"


def smtp_configured() -> bool:
    return settings.smtp_host is not None


def send_email(*, to: str, subject: str, body: str, html: str | None = None) -> None:
    if not smtp_configured():
        logger.info("SMTP not configured; skipping email %r to %s", subject, to)
        return
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if html is not None:
        message.add_alternative(html, subtype="html")

    assert settings.smtp_host is not None
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user and settings.smtp_password:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


def send_application_received(
    *, to: str, candidate_name: str, job_title: str, company_name: str
) -> None:
    subject = f"Application received — {job_title} at {company_name}"
    body = (
        f"Hi {candidate_name},\n"
        f"\n"
        f"Thanks for applying for the {job_title} position at {company_name}.\n"
        f"Your application and CV were received; the team will review them and\n"
        f"get back to you.\n"
        f"\n"
        f"— {company_name} (via Vetd)\n"
    )
    try:
        send_email(to=to, subject=subject, body=body)
    except Exception:  # noqa: BLE001 - email must never break the apply flow
        logger.warning("failed to send confirmation email to %s", to, exc_info=True)


def send_quiz_invite(
    *,
    to: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    brand_primary: str | None,
    quiz_url: str,
    question_count: int,
    seconds_per_question: int | None,
    expires_at: datetime,
) -> None:
    """Assessment invite (design 17a): quiz link + what-to-expect details.

    Replaces the generic confirmation when the job has an assessment.
    """
    brand = brand_primary or DEFAULT_BRAND_PRIMARY
    safe_candidate = escape(candidate_name)
    safe_job = escape(job_title)
    safe_company = escape(company_name)
    brand_fg = _brand_foreground(brand)
    valid_until = f"{expires_at:%a}, {expires_at:%b} {expires_at.day}"
    subject = f"Your {company_name} assessment — one step left"

    detail_rows: list[tuple[str, str]] = [
        (str(question_count), "questions, single choice"),
    ]
    if seconds_per_question is not None:
        detail_rows.append(
            (f"{seconds_per_question}s", "per question — each locks when time runs out")
        )
    detail_rows.append(("1×", "one attempt — find a quiet 10 minutes"))

    text_details = "\n".join(f"  {figure:>4}  {label}" for figure, label in detail_rows)
    body = (
        f"Hi {candidate_name},\n"
        f"\n"
        f"Thanks for applying to {job_title} at {company_name}. To be shortlisted,\n"
        f"take the short skills assessment — it's how we make sure your application\n"
        f"is judged on skill, not keywords.\n"
        f"\n"
        f"{text_details}\n"
        f"\n"
        f"Start the assessment: {quiz_url}\n"
        f"\n"
        f"Link valid until {valid_until} · works on any device\n"
        f"\n"
        f"— {company_name} (via Vetd)\n"
    )

    html_details = "".join(
        f'<div style="margin-top: 6px; font-size: 13.5px; line-height: 20px; color: #3f3f46;">'
        f'<span style="font-family: monospace; font-size: 12px; color: {brand}; '
        f'font-weight: 600; display: inline-block; width: 30px;">{figure}</span>'
        f"<span>{label}</span></div>"
        for figure, label in detail_rows
    )
    content = (
        f'<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        f"One step left, {safe_candidate}</h1>"
        f'<p style="margin: 12px 0 0; font-size: 14.5px; line-height: 22px; color: #3f3f46;">'
        f'Thanks for applying to <b style="font-weight: 600;">{safe_job}</b>. To be shortlisted, '
        f"take the short skills assessment — it's how we make sure your application is judged "
        f"on skill, not keywords.</p>"
        f'<div style="margin-top: 20px; border: 1px solid #e4e4e7; border-radius: 10px; '
        f'padding: 16px 18px;">{html_details}</div>'
        f'<a href="{quiz_url}" style="margin-top: 22px; display: block; text-align: center; '
        f"height: 46px; line-height: 46px; background: {brand}; color: {brand_fg}; "
        f'border-radius: 10px; font-size: 15px; font-weight: 600; text-decoration: none;">'
        f"Start the assessment</a>"
        f'<div style="margin-top: 12px; text-align: center; font-family: monospace; '
        f'font-size: 11px; color: #a1a1aa;">'
        f"link valid until {valid_until} · works on any device</div>"
    )
    html = _card_html(
        bar_color=brand,
        brand=brand,
        brand_fg=brand_fg,
        safe_company=safe_company,
        content=content,
    )

    try:
        send_email(to=to, subject=subject, body=body, html=html)
    except Exception:  # noqa: BLE001 - email must never break the apply flow
        logger.warning("failed to send quiz invite to %s", to, exc_info=True)


def _card_html(
    *, bar_color: str, brand: str, brand_fg: str, safe_company: str, content: str
) -> str:
    """Shared email card (handoff 17/22): top bar, logo chip, content, footer."""
    return (
        f'<div style="margin: 0 auto; max-width: 480px; background: #ffffff; '
        f"border-radius: 12px; border: 1px solid #e4e4e7; overflow: hidden; "
        f"font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; "
        f'color: #18181b;">'
        f'<div style="height: 5px; background: {bar_color};"></div>'
        f'<div style="padding: 28px 32px;">'
        f'<div><span style="display: inline-block; width: 24px; height: 24px; '
        f"border-radius: 7px; background: {brand}; color: {brand_fg}; text-align: center; "
        f'line-height: 24px; font-size: 13px; font-weight: 700;">{safe_company[:1].upper()}</span>'
        f'<span style="margin-left: 9px; font-size: 15px; font-weight: 600;">'
        f"{safe_company}</span></div>"
        f"{content}"
        f"</div></div>"
        f'<div style="margin: 16px auto 0; max-width: 480px; text-align: center; '
        f'font-family: monospace; font-size: 10.5px; color: #a1a1aa; line-height: 17px;">'
        f"Sent by vetd on behalf of {safe_company}</div>"
    )


def _paragraph(inner: str) -> str:
    return (
        f'<p style="margin: 12px 0 0; font-size: 14.5px; line-height: 22px; '
        f'color: #3f3f46;">{inner}</p>'
    )


NEUTRAL_BAR = "#d4d4d8"  # rejections never carry brand accents


def send_stage_advance(
    *,
    to: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    brand_primary: str | None,
) -> None:
    """Advance-to-interview email (design 22a); scheduling details follow later."""
    brand = brand_primary or DEFAULT_BRAND_PRIMARY
    brand_fg = _brand_foreground(brand)
    safe_candidate = escape(candidate_name)
    safe_job = escape(job_title)
    safe_company = escape(company_name)
    subject = f"Next step: interviews at {company_name}"

    body = (
        f"Good news, {candidate_name} — let's talk.\n"
        f"\n"
        f"Your application for {job_title} stood out, and we'd like to\n"
        f"move you to interviews. We'll follow up shortly with scheduling details.\n"
        f"\n"
        f"Looking forward to it,\n"
        f"The {company_name} hiring team\n"
    )
    content = (
        f'<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        f"Good news, {safe_candidate} — let's talk</h1>"
        + _paragraph(
            f'Your application for <b style="font-weight: 600;">{safe_job}</b> stood out, '
            f"and we'd like to move you to interviews. We'll follow up shortly with "
            f"scheduling details."
        )
        + f'<p style="margin: 22px 0 0; font-size: 14px; line-height: 21px; color: #3f3f46;">'
        f'Looking forward to it,<br><b style="font-weight: 600;">'
        f"The {safe_company} hiring team</b></p>"
    )
    html = _card_html(
        bar_color=brand, brand=brand, brand_fg=brand_fg, safe_company=safe_company, content=content
    )

    try:
        send_email(to=to, subject=subject, body=body, html=html)
    except Exception:  # noqa: BLE001 - email must never break a recruiter flow
        logger.warning("failed to send advance email to %s", to, exc_info=True)


def send_rejection(
    *,
    to: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    careers_url: str,
    completed_assessment: bool,
) -> None:
    """Humane rejection (design 22b): neutral bar, no score, no brand accents."""
    safe_candidate = escape(candidate_name)
    safe_job = escape(job_title)
    safe_company = escape(company_name)
    subject = f"Your application to {company_name}"

    assessment_line = (
        " We were glad you took the time to complete the assessment — "
        "a real person reviewed it, not a filter."
        if completed_assessment
        else ""
    )
    body = (
        f"Thank you, {candidate_name}.\n"
        f"\n"
        f"We've finished reviewing applications for {job_title},\n"
        f"and we won't be moving forward with yours this time.\n"
        f"\n"
        f"This was a competitive round and the decision was close.{assessment_line}\n"
        f"\n"
        f"We'd genuinely welcome another application for a future role.\n"
        f"See open positions: {careers_url}\n"
        f"\n"
        f"All the best,\n"
        f"The {company_name} hiring team\n"
    )
    content = (
        f'<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        f"Thank you, {safe_candidate}</h1>"
        + _paragraph(
            f'We\'ve finished reviewing applications for <b style="font-weight: 600;">'
            f"{safe_job}</b>, and we won't be moving forward with yours this time."
        )
        + _paragraph(f"This was a competitive round and the decision was close.{assessment_line}")
        + _paragraph("We'd genuinely welcome another application for a future role.")
        + f'<div style="margin-top: 20px; text-align: center;">'
        f'<a href="{careers_url}" style="display: inline-block; height: 40px; '
        f"line-height: 40px; padding: 0 20px; border: 1.5px solid #d4d4d8; "
        f"border-radius: 10px; font-size: 13.5px; font-weight: 600; color: #3f3f46; "
        f'text-decoration: none;">See open positions</a></div>'
        + f'<p style="margin: 22px 0 0; font-size: 14px; line-height: 21px; color: #3f3f46;">'
        f'All the best,<br><b style="font-weight: 600;">'
        f"The {safe_company} hiring team</b></p>"
    )
    html = _card_html(
        bar_color=NEUTRAL_BAR,
        brand=DEFAULT_BRAND_PRIMARY,
        brand_fg="#ffffff",
        safe_company=safe_company,
        content=content,
    )

    try:
        send_email(to=to, subject=subject, body=body, html=html)
    except Exception:  # noqa: BLE001 - email must never break a recruiter flow
        logger.warning("failed to send rejection email to %s", to, exc_info=True)
