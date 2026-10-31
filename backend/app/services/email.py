"""Outbound email: rendering lives here, transport in email_providers.
Logged no-op while no provider is configured.

Senders RAISE on transport errors since M5.7 H4: every send goes through
the email outbox (services/outbox.py), whose worker job owns retry with
backoff and records the failure on the row. Never call a sender directly
from a request path - queue it.
"""

import logging
from contextvars import ContextVar
from datetime import datetime
from html import escape
from typing import Any

from app.core.config import settings
from app.services import email_providers as providers
from app.services import email_render
from app.services.email_frame import (
    DEFAULT_BRAND_PRIMARY,
    NEUTRAL_BAR,
    brand_foreground,
    card_html,
    paragraph,
    privacy_text,
)

# the eleven senders below still use the pre-move names
_brand_foreground = brand_foreground
_card_html = card_html
_paragraph = paragraph
_privacy_text = privacy_text

logger = logging.getLogger(__name__)

# set by outbox.dispatch around a sender call so send_email can hand the
# row id to the provider (Mailjet CustomID) for bounce/complaint mapping
current_outbox_id: ContextVar[str | None] = ContextVar("current_outbox_id", default=None)

# (subject, text) of the last mail a sender handed to send_email, set before
# the transport runs (or is skipped): outbox.dispatch stores it on the row so
# the timeline shows the mail without re-rendering (PR 4)
last_rendered: ContextVar[tuple[str, str] | None] = ContextVar("last_rendered", default=None)

# Mirrors frontend lib/brand.ts: per-company brand color with a
# luminance-computed foreground; near-black default.


def configured() -> bool:
    """Whether the selected provider can deliver (GANEK_EMAIL_PROVIDER)."""
    return providers.configured()


def send_email(
    *,
    to: str,
    subject: str,
    body: str,
    html: str | None = None,
    ref: str | None = None,
    outbox_id: str | None = None,
    reply_to: str | None = None,
) -> None:
    last_rendered.set((subject, body))
    if not configured():
        logger.info("email not configured; skipping email %r (ref=%s)", subject, ref)
        return
    if settings.demo_mode:
        logger.info("demo mode; skipping email %r (ref=%s)", subject, ref)
        return
    providers.current().send(
        providers.OutboundMessage(
            to=to,
            subject=subject,
            text=body,
            html=html,
            outbox_id=outbox_id or current_outbox_id.get(),
            reply_to=reply_to,
        )
    )


def send_application_received(
    *,
    to: str,
    ref: str | None = None,
    candidate_name: str,
    job_title: str,
    company_name: str,
    privacy_url: str | None = None,
) -> None:
    subject = f"Application received - {job_title} at {company_name}"
    body = (
        f"Hi {candidate_name},\n"
        f"\n"
        f"Thanks for applying for the {job_title} position at {company_name}.\n"
        f"Your application and CV were received; the team will review them and\n"
        f"get back to you.\n"
        f"\n"
        f"- {company_name} (via Ganek)\n" + _privacy_text(privacy_url)
    )
    send_email(to=to, subject=subject, body=body, ref=ref)


def _send_stage(
    kind: str,
    *,
    to: str,
    ref: str | None,
    context: dict[str, Any],
    template_subject: str | None = None,
    template_body: str | None = None,
) -> None:
    """Render one of the four candidate stage mails and send it: from the
    template snapshot the outbox took at queue time (PR 3), else from the
    built-in. The preview endpoint renders the same context through the
    same function, so what the recruiter reads is what the candidate gets."""
    template = (
        email_render.Template(subject=template_subject, body=template_body)
        if template_subject is not None and template_body is not None
        else email_render.BUILTIN[kind]
    )
    rendered = email_render.render(kind, template, context)
    send_email(to=to, subject=rendered.subject, body=rendered.text, html=rendered.html, ref=ref)


def send_quiz_invite(
    *,
    to: str,
    ref: str | None = None,
    candidate_name: str,
    job_title: str,
    company_name: str,
    brand_primary: str | None,
    quiz_url: str,
    question_count: int,
    seconds_per_question: int | None,
    expires_at: datetime,
    controller_name: str | None = None,
    privacy_url: str | None = None,
    template_id: str | None = None,
    template_subject: str | None = None,
    template_body: str | None = None,
) -> None:
    """Assessment invite (design 17a): quiz link + what-to-expect details.

    Replaces the generic confirmation when the job has an assessment.
    """
    _send_stage(
        "quiz_invite",
        to=to,
        ref=ref,
        template_subject=template_subject,
        template_body=template_body,
        context={
            "candidate_name": candidate_name,
            "job_title": job_title,
            "company_name": company_name,
            "brand_primary": brand_primary,
            "quiz_url": quiz_url,
            "question_count": question_count,
            "seconds_per_question": seconds_per_question,
            "expires_at": expires_at,
            "controller_name": controller_name,
            "privacy_url": privacy_url,
        },
    )


def send_quiz_reminder(
    *,
    to: str,
    ref: str | None = None,
    candidate_name: str,
    job_title: str,
    company_name: str,
    brand_primary: str | None,
    quiz_url: str,
    expires_at: datetime,
    days_left: int,
    controller_name: str | None = None,
    privacy_url: str | None = None,
    template_id: str | None = None,
    template_subject: str | None = None,
    template_body: str | None = None,
) -> None:
    """Assessment reminder (design 17b), sent manually by a recruiter or by
    the worker nudge. Never claims the application auto-closes - only the
    link expires."""
    _send_stage(
        "quiz_reminder",
        to=to,
        ref=ref,
        template_subject=template_subject,
        template_body=template_body,
        context={
            "candidate_name": candidate_name,
            "job_title": job_title,
            "company_name": company_name,
            "brand_primary": brand_primary,
            "quiz_url": quiz_url,
            "expires_at": expires_at,
            "days_left": days_left,
            "controller_name": controller_name,
            "privacy_url": privacy_url,
        },
    )


def send_stage_advance(
    *,
    to: str,
    ref: str | None = None,
    candidate_name: str,
    job_title: str,
    company_name: str,
    brand_primary: str | None,
    status_url: str | None = None,
    controller_name: str | None = None,
    privacy_url: str | None = None,
    template_id: str | None = None,
    template_subject: str | None = None,
    template_body: str | None = None,
) -> None:
    """Advance-to-interview email (design 22a); scheduling details follow later."""
    _send_stage(
        "stage_advance",
        to=to,
        ref=ref,
        template_subject=template_subject,
        template_body=template_body,
        context={
            "candidate_name": candidate_name,
            "job_title": job_title,
            "company_name": company_name,
            "brand_primary": brand_primary,
            "status_url": status_url,
            "controller_name": controller_name,
            "privacy_url": privacy_url,
        },
    )


def send_rejection(
    *,
    to: str,
    ref: str | None = None,
    candidate_name: str,
    job_title: str,
    company_name: str,
    careers_url: str,
    completed_assessment: bool,
    controller_name: str | None = None,
    privacy_url: str | None = None,
    template_id: str | None = None,
    template_subject: str | None = None,
    template_body: str | None = None,
) -> None:
    """Humane rejection (design 22b): neutral bar, no score, no brand accents."""
    _send_stage(
        "rejection",
        to=to,
        ref=ref,
        template_subject=template_subject,
        template_body=template_body,
        context={
            "candidate_name": candidate_name,
            "job_title": job_title,
            "company_name": company_name,
            "careers_url": careers_url,
            "completed_assessment": completed_assessment,
            "controller_name": controller_name,
            "privacy_url": privacy_url,
        },
    )


# Matches the team page's role select labels (Owner/Recruiter naming is
# still an open design decision - the shipped UI says Member).
ROLE_LABELS = {"admin": "Admin", "member": "Member"}


def send_team_invite(
    *,
    to: str,
    ref: str | None = None,
    company_name: str,
    inviter_email: str,
    role: str,
    invite_url: str,
    expires_at: datetime,
    brand_primary: str | None,
) -> None:
    """Team invite (D6): join-the-workspace link for a future recruiter/admin."""
    brand = brand_primary or DEFAULT_BRAND_PRIMARY
    brand_fg = _brand_foreground(brand)
    safe_company = escape(company_name)
    safe_inviter = escape(inviter_email)
    role_label = ROLE_LABELS.get(role, role)
    valid_until = f"{expires_at:%a}, {expires_at:%b} {expires_at.day}"
    subject = f"You're invited to join {company_name} on Ganek"

    body = (
        f"Hi,\n"
        f"\n"
        f"{inviter_email} invited you to join {company_name}'s hiring workspace\n"
        f"on Ganek as {role_label}.\n"
        f"\n"
        f"Accept the invite and set your password: {invite_url}\n"
        f"\n"
        f"Invite valid until {valid_until}.\n"
        f"\n"
        f"- {company_name} (via Ganek)\n"
    )
    content = (
        f'<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        f"Join {safe_company} on Ganek</h1>"
        + _paragraph(
            f'<b style="font-weight: 600;">{safe_inviter}</b> invited you to join '
            f"{safe_company}'s hiring workspace as "
            f'<b style="font-weight: 600;">{role_label}</b>.'
        )
        + f'<a href="{invite_url}" style="margin-top: 22px; display: block; text-align: center; '
        f"height: 46px; line-height: 46px; background: {brand}; color: {brand_fg}; "
        f'border-radius: 10px; font-size: 15px; font-weight: 600; text-decoration: none;">'
        f"Accept invite</a>"
        f'<div style="margin-top: 12px; text-align: center; font-family: monospace; '
        f'font-size: 11px; color: #a1a1aa;">invite valid until {valid_until}</div>'
    )
    html = _card_html(
        bar_color=brand, brand=brand, brand_fg=brand_fg, safe_company=safe_company, content=content
    )

    send_email(to=to, subject=subject, body=body, html=html, ref=ref)


def send_email_verification(
    *,
    to: str,
    ref: str | None = None,
    company_name: str,
    verify_url: str,
    expires_days: int,
) -> None:
    """Multi-mode signup verification (M5.7 H4): the company stays inert
    until this link is clicked; unverified signups are swept after 7 days."""
    safe_company = escape(company_name)
    brand = DEFAULT_BRAND_PRIMARY
    brand_fg = _brand_foreground(brand)
    subject = "Verify your email to activate your Ganek workspace"

    body = (
        f"Hi,\n"
        f"\n"
        f"You're one click away from activating the {company_name} hiring\n"
        f"workspace on Ganek. Confirm this is your email address:\n"
        f"\n"
        f"{verify_url}\n"
        f"\n"
        f"The link works for {expires_days} days; unverified workspaces are\n"
        f"removed after a week. If you didn't sign up, ignore this email.\n"
        f"\n"
        f"- Ganek\n"
    )
    content = (
        f'<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        f"Activate {safe_company}</h1>"
        + _paragraph(
            f"You're one click away from activating the {safe_company} hiring "
            f"workspace. Confirm this is your email address; if you didn't sign "
            f"up, ignore this email."
        )
        + f'<a href="{verify_url}" style="margin-top: 22px; display: block; text-align: center; '
        f"height: 46px; line-height: 46px; background: {brand}; color: {brand_fg}; "
        f'border-radius: 10px; font-size: 15px; font-weight: 600; text-decoration: none;">'
        f"Verify email</a>"
        f'<div style="margin-top: 12px; text-align: center; font-family: monospace; '
        f'font-size: 11px; color: #a1a1aa;">link valid for {expires_days} days</div>'
    )
    html = _card_html(
        bar_color=brand, brand=brand, brand_fg=brand_fg, safe_company=safe_company, content=content
    )
    send_email(to=to, subject=subject, body=body, html=html, ref=ref)


def send_password_reset(
    *,
    to: str,
    ref: str | None = None,
    company_name: str,
    reset_url: str,
    brand_primary: str | None,
    expires_minutes: int,
) -> None:
    """Password reset link for a recruiter (M5.7 H4). Sent only from the
    forgot-password endpoint, which never reveals whether an account exists."""
    brand = brand_primary or DEFAULT_BRAND_PRIMARY
    brand_fg = _brand_foreground(brand)
    safe_company = escape(company_name)
    subject = "Reset your Ganek password"

    body = (
        f"Hi,\n"
        f"\n"
        f"Someone asked to reset the password for your {company_name}\n"
        f"workspace account on Ganek. If that was you, set a new password\n"
        f"here (the link works for {expires_minutes} minutes):\n"
        f"\n"
        f"{reset_url}\n"
        f"\n"
        f"If it wasn't you, ignore this email - your password is unchanged\n"
        f"and the link expires on its own.\n"
        f"\n"
        f"- {company_name} (via Ganek)\n"
    )
    content = (
        '<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        "Reset your password</h1>"
        + _paragraph(
            f"Someone asked to reset the password for your {safe_company} workspace "
            f"account. If that was you, set a new one below; if not, ignore this "
            f"email - your password is unchanged."
        )
        + f'<a href="{reset_url}" style="margin-top: 22px; display: block; text-align: center; '
        f"height: 46px; line-height: 46px; background: {brand}; color: {brand_fg}; "
        f'border-radius: 10px; font-size: 15px; font-weight: 600; text-decoration: none;">'
        f"Set a new password</a>"
        f'<div style="margin-top: 12px; text-align: center; font-family: monospace; '
        f'font-size: 11px; color: #a1a1aa;">link valid for {expires_minutes} minutes</div>'
    )
    html = _card_html(
        bar_color=brand, brand=brand, brand_fg=brand_fg, safe_company=safe_company, content=content
    )

    send_email(to=to, subject=subject, body=body, html=html, ref=ref)


def send_google_linked(*, to: str, company_name: str, ref: str | None = None) -> None:
    """Security notice: a Google identity was just linked to an existing account.

    Mitigates silent pre-registration takeovers - the legitimate owner
    learns immediately if someone else's Google sign-in claimed their email.
    """
    safe_company = escape(company_name)
    subject = "Google sign-in was added to your Ganek account"
    body = (
        f"Hi,\n"
        f"\n"
        f"Signing in with Google is now enabled for your Ganek account\n"
        f"at {company_name}. Your password continues to work as before.\n"
        f"\n"
        f"If you did not just sign in with Google, change your password\n"
        f"in Settings -> Account right away.\n"
        f"\n"
        f"- Ganek\n"
    )
    content = (
        '<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        "Google sign-in added</h1>"
        + _paragraph(
            f"Signing in with Google is now enabled for your Ganek account at "
            f'<b style="font-weight: 600;">{safe_company}</b>. '
            f"Your password continues to work as before."
        )
        + _paragraph(
            "If you did not just sign in with Google, change your password in "
            '<b style="font-weight: 600;">Settings &rarr; Account</b> right away.'
        )
    )
    html = _card_html(
        bar_color=NEUTRAL_BAR,
        brand=DEFAULT_BRAND_PRIMARY,
        brand_fg="#ffffff",
        safe_company=safe_company,
        content=content,
    )
    send_email(to=to, subject=subject, body=body, html=html, ref=ref)


def send_interview_invite(
    *,
    to: str,
    ref: str | None = None,
    candidate_name: str,
    job_title: str,
    company_name: str,
    duration_minutes: int,
    booking_url: str,
    brand_primary: str | None,
    controller_name: str | None = None,
    privacy_url: str | None = None,
) -> None:
    """Interview booking link (D7, screen 23): the candidate picks a slot."""
    brand = brand_primary or DEFAULT_BRAND_PRIMARY
    brand_fg = _brand_foreground(brand)
    safe_candidate = escape(candidate_name)
    safe_job = escape(job_title)
    safe_company = escape(company_name)
    subject = f"Pick a time - interview for {job_title} at {company_name}"

    body = (
        f"Hi {candidate_name},\n"
        f"\n"
        f"{company_name} would like to schedule a {duration_minutes}-minute\n"
        f"interview with you for the {job_title} position.\n"
        f"\n"
        f"Pick a time that suits you: {booking_url}\n"
        f"\n"
        f"Once you confirm, a calendar invite with the meeting link lands\n"
        f"in your inbox. You can reschedule or cancel from the same page.\n"
        f"\n"
        f"- {company_name} (via Ganek)\n" + _privacy_text(privacy_url)
    )
    content = (
        f'<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        f"Pick a time, {safe_candidate}</h1>"
        + _paragraph(
            f'<b style="font-weight: 600;">{safe_company}</b> would like to schedule a '
            f'<b style="font-weight: 600;">{duration_minutes}-minute interview</b> with you '
            f"for the {safe_job} position."
        )
        + f'<a href="{booking_url}" style="margin-top: 22px; display: block; text-align: center; '
        f"height: 46px; line-height: 46px; background: {brand}; color: {brand_fg}; "
        f'border-radius: 10px; font-size: 15px; font-weight: 600; text-decoration: none;">'
        f"Pick a time</a>"
        + _paragraph(
            "Once you confirm, a calendar invite with the meeting link lands in your "
            "inbox. You can reschedule or cancel from the same page."
        )
    )
    html = _card_html(
        bar_color=brand,
        brand=brand,
        brand_fg=brand_fg,
        safe_company=safe_company,
        content=content,
        safe_controller=escape(controller_name) if controller_name else None,
        privacy_url=privacy_url,
    )
    send_email(to=to, subject=subject, body=body, html=html, ref=ref)


def send_interview_cancelled(
    *,
    to: str,
    ref: str | None = None,
    candidate_name: str,
    job_title: str,
    company_name: str,
    controller_name: str | None = None,
    privacy_url: str | None = None,
) -> None:
    """Interview request withdrawn/cancelled notice (neutral, no brand accent)."""
    safe_candidate = escape(candidate_name)
    safe_job = escape(job_title)
    safe_company = escape(company_name)
    subject = f"Interview cancelled - {job_title} at {company_name}"

    body = (
        f"Hi {candidate_name},\n"
        f"\n"
        f"The scheduled interview for the {job_title} position at\n"
        f"{company_name} has been cancelled. If a new time is needed,\n"
        f"you'll receive a fresh scheduling link.\n"
        f"\n"
        f"- {company_name} (via Ganek)\n" + _privacy_text(privacy_url)
    )
    content = (
        '<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        "Interview cancelled</h1>"
        + _paragraph(
            f"Hi {safe_candidate} - the scheduled interview for the "
            f'<b style="font-weight: 600;">{safe_job}</b> position at {safe_company} has '
            f"been cancelled."
        )
        + _paragraph("If a new time is needed, you'll receive a fresh scheduling link.")
    )
    html = _card_html(
        bar_color=NEUTRAL_BAR,
        brand=DEFAULT_BRAND_PRIMARY,
        brand_fg="#ffffff",
        safe_company=safe_company,
        content=content,
        safe_controller=escape(controller_name) if controller_name else None,
        privacy_url=privacy_url,
    )
    send_email(to=to, subject=subject, body=body, html=html, ref=ref)


def send_interview_reminder(
    *,
    to: str,
    ref: str | None = None,
    candidate_name: str,
    job_title: str,
    company_name: str,
    start: datetime,
    timezone: str,
    meet_url: str | None,
    brand_primary: str | None,
    controller_name: str | None = None,
    privacy_url: str | None = None,
) -> None:
    """T-24h reminder for a booked interview (D7 arq job)."""
    brand = brand_primary or DEFAULT_BRAND_PRIMARY
    brand_fg = _brand_foreground(brand)
    safe_candidate = escape(candidate_name)
    safe_job = escape(job_title)
    safe_company = escape(company_name)
    try:
        from zoneinfo import ZoneInfo

        local = start.astimezone(ZoneInfo(timezone))
    except Exception:  # noqa: BLE001 - a bad stored zone must not kill the reminder
        local = start
    when = f"{local:%a}, {local:%b} {local.day} · {local:%H:%M}"
    subject = f"Reminder: your interview at {company_name} is coming up"

    body = (
        f"Hi {candidate_name},\n"
        f"\n"
        f"A quick reminder about your {job_title} interview at\n"
        f"{company_name}: {when} ({timezone}).\n"
        f"\n" + (f"Join via Google Meet: {meet_url}\n\n" if meet_url else "") + f"Good luck!\n"
        f"- {company_name} (via Ganek)\n" + _privacy_text(privacy_url)
    )
    content = (
        f'<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        f"See you soon, {safe_candidate}</h1>"
        + _paragraph(
            f'A quick reminder about your <b style="font-weight: 600;">{safe_job}</b> '
            f'interview at {safe_company}: <b style="font-weight: 600;">{when}</b> '
            f'<span style="font-family: monospace; font-size: 12px;">({escape(timezone)})</span>.'
        )
        + (
            f'<a href="{meet_url}" style="margin-top: 22px; display: block; text-align: center; '
            f"height: 46px; line-height: 46px; background: {brand}; color: {brand_fg}; "
            f'border-radius: 10px; font-size: 15px; font-weight: 600; text-decoration: none;">'
            f"Join with Google Meet</a>"
            if meet_url
            else ""
        )
    )
    html = _card_html(
        bar_color=brand,
        brand=brand,
        brand_fg=brand_fg,
        safe_company=safe_company,
        content=content,
        safe_controller=escape(controller_name) if controller_name else None,
        privacy_url=privacy_url,
    )
    send_email(to=to, subject=subject, body=body, html=html, ref=ref)
