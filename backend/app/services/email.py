"""Outbound email: rendering lives here, transport in email_providers.
Logged no-op while no provider is configured.

Senders RAISE on transport errors since M5.7 H4: every send goes through
the email outbox (services/outbox.py), whose worker job owns retry with
backoff and records the failure on the row. Never call a sender directly
from a request path - queue it.
"""

import logging
from contextvars import ContextVar
from datetime import datetime, timedelta
from email.utils import parseaddr
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.services import email_providers as providers
from app.services import email_render, ics
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
    calendar: providers.CalendarPart | None = None,
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
            calendar=calendar,
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
    override_subject: str | None = None,
    override_body: str | None = None,
) -> None:
    """Render one of the four candidate stage mails and send it: from the
    recruiter's one-off edit of this send (PR 4, literal text), else from
    the template snapshot the outbox took at queue time (PR 3), else from
    the built-in. The preview endpoint renders the same context through the
    same function, so what the recruiter reads is what the candidate gets."""
    if override_subject is not None and override_body is not None:
        template = email_render.Template(subject=override_subject, body=override_body)
        rendered = email_render.render(kind, template, context, literal=True)
    else:
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
    override_subject: str | None = None,
    override_body: str | None = None,
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
        override_subject=override_subject,
        override_body=override_body,
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
    override_subject: str | None = None,
    override_body: str | None = None,
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
        override_subject=override_subject,
        override_body=override_body,
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
    override_subject: str | None = None,
    override_body: str | None = None,
) -> None:
    """Advance-to-interview email (design 22a); scheduling details follow later."""
    _send_stage(
        "stage_advance",
        to=to,
        ref=ref,
        template_subject=template_subject,
        template_body=template_body,
        override_subject=override_subject,
        override_body=override_body,
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
    override_subject: str | None = None,
    override_body: str | None = None,
) -> None:
    """Humane rejection (design 22b): neutral bar, no score, no brand accents."""
    _send_stage(
        "rejection",
        to=to,
        ref=ref,
        template_subject=template_subject,
        template_body=template_body,
        override_subject=override_subject,
        override_body=override_body,
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


def send_message(
    *,
    to: str,
    ref: str | None = None,
    subject: str,
    body: str,
    company_name: str,
    reply_to: str,
    controller_name: str | None = None,
    privacy_url: str | None = None,
) -> None:
    """A recruiter's one-off message to a candidate (PR 4): neutral card, no
    action block, replies go to the recruiter who wrote it."""
    rendered = email_render.render_message(
        subject,
        body,
        {
            "company_name": company_name,
            "controller_name": controller_name,
            "privacy_url": privacy_url,
        },
    )
    send_email(
        to=to,
        subject=rendered.subject,
        body=rendered.text,
        html=rendered.html,
        ref=ref,
        reply_to=reply_to,
    )


# Matches the team page's role select labels (Owner/Recruiter naming is
# still an open design decision - the shipped UI says Member).
ROLE_LABELS = {"admin": "Admin", "member": "Member", "reviewer": "Reviewer"}


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
        f"Once you confirm, you and your interviewer both receive a calendar\n"
        f"invite by email. You can reschedule or cancel from the same page.\n"
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
            "Once you confirm, you and your interviewer both receive a calendar invite "
            "by email. You can reschedule or cancel from the same page."
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
    # set when a time had been booked: the mail then carries METHOD:CANCEL
    title: str | None = None,
    start: datetime | None = None,
    duration_minutes: int | None = None,
    timezone: str | None = None,
    location: str = "",
    uid: str | None = None,
    sequence: int | None = None,
    interviewer_name: str | None = None,
    interviewer_email: str | None = None,
) -> None:
    """Interview request withdrawn/cancelled notice (neutral, no brand accent)."""
    safe_candidate = escape(candidate_name)
    safe_job = escape(job_title)
    safe_company = escape(company_name)
    subject = f"Interview cancelled - {job_title} at {company_name}"
    when_text = ""
    if start is not None and timezone is not None:
        when_text = f" ({_local_when(start, timezone)}, {timezone})"

    body = (
        f"Hi {candidate_name},\n"
        f"\n"
        f"The scheduled interview for the {job_title} position at\n"
        f"{company_name}{when_text} has been cancelled. If a new time is needed,\n"
        f"you'll receive a fresh scheduling link.\n"
        f"\n"
        f"- {company_name} (via Ganek)\n" + _privacy_text(privacy_url)
    )
    content = (
        '<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        "Interview cancelled</h1>"
        + _paragraph(
            f"Hi {safe_candidate} - the scheduled interview for the "
            f'<b style="font-weight: 600;">{safe_job}</b> position at {safe_company}'
            f"{escape(when_text)} has been cancelled."
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
    calendar = None
    if (
        start is not None
        and uid is not None
        and sequence is not None
        and duration_minutes is not None
    ):
        attendees: list[tuple[str, str]] = [(candidate_name, to)]
        if interviewer_name and interviewer_email:
            attendees.append((interviewer_name, interviewer_email))
        calendar = _calendar_part(
            method="CANCEL",
            uid=uid,
            sequence=sequence,
            start=start,
            duration_minutes=duration_minutes,
            summary=f"{title or 'Interview'} - {job_title} at {company_name}",
            description="",
            location=location,
            company_name=company_name,
            attendees=tuple(attendees),
            url=None,
        )
    send_email(to=to, subject=subject, body=body, html=html, ref=ref, calendar=calendar)


def send_interview_cancelled_interviewer(
    *,
    to: str,
    ref: str | None = None,
    candidate_name: str,
    candidate_email: str,
    interviewer_name: str,
    job_title: str,
    company_name: str,
    title: str,
    start: datetime,
    duration_minutes: int,
    timezone: str,
    location: str,
    uid: str,
    sequence: int,
    cancelled_by: str,
    controller_name: str | None = None,
    privacy_url: str | None = None,
) -> None:
    """Interviewer copy of a cancellation with METHOD:CANCEL so the event
    leaves their calendar. With an empty ``candidate_name`` (erasure) the
    mail and the event carry no personal data about the candidate; with only
    an empty ``candidate_email`` (a row queued before reviewer interviewers got
    the address) the event lists the interviewer alone."""
    safe_job = escape(job_title)
    safe_company = escape(company_name)
    when = _local_when(start, timezone)
    if candidate_name:
        subject = f"Interview cancelled: {candidate_name} - {job_title}"
        line = (
            f"{cancelled_by} cancelled the {title} with {candidate_name} "
            f"for the {job_title} position"
        )
        summary = f"{title} - {candidate_name} ({job_title})"
    else:
        subject = f"Interview cancelled - {job_title}"
        line = f"{cancelled_by}. The {title} for the {job_title} position is cancelled"
        summary = "Interview cancelled"

    body = (
        f"Hi {interviewer_name},\n"
        f"\n"
        f"{line}: {when} ({timezone}).\n"
        f"The attached update removes it from your calendar.\n"
        f"\n"
        f"- {company_name} (via Ganek)\n" + _privacy_text(privacy_url)
    )
    content = (
        '<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        "Interview cancelled</h1>"
        + _paragraph(
            f'{escape(line)}: <b style="font-weight: 600;">{when}</b> '
            f'<span style="font-family: monospace; font-size: 12px;">({escape(timezone)})</span>.'
        )
        + _paragraph("The attached update removes it from your calendar.")
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
    attendees: list[tuple[str, str]] = []
    if candidate_name and candidate_email:
        attendees.append((candidate_name, candidate_email))
    attendees.append((interviewer_name, to))
    calendar = _calendar_part(
        method="CANCEL",
        uid=uid,
        sequence=sequence,
        start=start,
        duration_minutes=duration_minutes,
        summary=summary,
        description="",
        location=location,
        company_name=company_name,
        attendees=tuple(attendees),
        url=None,
    )
    del safe_job
    send_email(to=to, subject=subject, body=body, html=html, ref=ref, calendar=calendar)


def send_interview_reminder(
    *,
    to: str,
    ref: str | None = None,
    candidate_name: str,
    job_title: str,
    company_name: str,
    start: datetime,
    timezone: str,
    location: str,
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
        f"\n" + (f"Where: {location}\n\n" if location else "") + f"Good luck!\n"
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
        + (_paragraph(f"Where: {escape(location)}") if location else "")
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


# ---- interview invites with a calendar part (card: scheduling without
# on ICS only). One UID per interview; REQUEST on booking and on every
# reschedule (SEQUENCE + 1), CANCEL on cancellation. The organiser is the
# sending address: replies are not tracked, the booking page is where a
# candidate changes or cancels.


def _organizer_email() -> str:
    return parseaddr(settings.email_from)[1] or settings.email_from


def _local_when(start: datetime, timezone: str) -> str:
    try:
        local = start.astimezone(ZoneInfo(timezone))
    except Exception:  # noqa: BLE001 - a bad stored zone must not kill the mail
        local = start
    return f"{local:%a}, {local:%b} {local.day} · {local:%H:%M}"


def _calendar_part(
    *,
    method: ics.Method,
    uid: str,
    sequence: int,
    start: datetime,
    duration_minutes: int,
    summary: str,
    description: str,
    location: str,
    company_name: str,
    attendees: tuple[tuple[str, str], ...],
    url: str | None,
) -> providers.CalendarPart:
    text = "\n".join(
        part for part in (description, f"Location: {location}" if location else "") if part
    )
    event = ics.CalendarEvent(
        uid=uid,
        sequence=sequence,
        start=start,
        end=start + timedelta(minutes=duration_minutes),
        summary=summary,
        description=text,
        location=location,
        organizer_email=_organizer_email(),
        organizer_name=company_name,
        attendees=attendees,
        url=url,
    )
    return providers.CalendarPart(method=method, content=ics.render(event, method=method))


def send_interview_confirmed(
    *,
    to: str,
    ref: str | None = None,
    candidate_name: str,
    interviewer_name: str,
    job_title: str,
    company_name: str,
    title: str,
    description: str,
    start: datetime,
    duration_minutes: int,
    timezone: str,
    location: str,
    uid: str,
    sequence: int,
    booking_url: str,
    interviewer_email: str,
    rescheduled: bool,
    brand_primary: str | None,
    controller_name: str | None = None,
    privacy_url: str | None = None,
) -> None:
    """Candidate copy of the booking (or reschedule) with the invite.ics."""
    brand = brand_primary or DEFAULT_BRAND_PRIMARY
    brand_fg = _brand_foreground(brand)
    safe_candidate = escape(candidate_name)
    safe_job = escape(job_title)
    safe_company = escape(company_name)
    when = _local_when(start, timezone)
    verb = "Rescheduled" if rescheduled else "Confirmed"
    subject = f"{verb}: your interview for {job_title} at {company_name}"
    where_text = f"Where: {location}\n" if location else ""

    body = (
        f"Hi {candidate_name},\n"
        f"\n"
        f"Your {title} for the {job_title} position at {company_name} is "
        f"{verb.lower()}:\n"
        f"{when} ({timezone}), {duration_minutes} minutes, with {interviewer_name}.\n"
        + where_text
        + f"\n"
        f"The attached calendar invite adds it to your calendar. Change or\n"
        f"cancel the time any time: {booking_url}\n"
        f"\n"
        f"- {company_name} (via Ganek)\n" + _privacy_text(privacy_url)
    )
    content = (
        f'<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        f"{verb}, {safe_candidate}</h1>"
        + _paragraph(
            f'Your {escape(title)} for the <b style="font-weight: 600;">{safe_job}</b> '
            f'position at {safe_company}: <b style="font-weight: 600;">{when}</b> '
            f'<span style="font-family: monospace; font-size: 12px;">({escape(timezone)})</span>, '
            f"{duration_minutes} minutes, with {escape(interviewer_name)}."
        )
        + (_paragraph(f"Where: {escape(location)}") if location else "")
        + f'<a href="{booking_url}" style="margin-top: 22px; display: block; text-align: center; '
        f"height: 46px; line-height: 46px; background: {brand}; color: {brand_fg}; "
        f'border-radius: 10px; font-size: 15px; font-weight: 600; text-decoration: none;">'
        f"Change or cancel the time</a>"
        + _paragraph("The attached calendar invite adds the interview to your calendar.")
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
    calendar = _calendar_part(
        method="REQUEST",
        uid=uid,
        sequence=sequence,
        start=start,
        duration_minutes=duration_minutes,
        summary=f"{title} - {job_title} at {company_name}",
        description=description,
        location=location,
        company_name=company_name,
        attendees=((candidate_name, to), (interviewer_name, interviewer_email)),
        url=booking_url,
    )
    send_email(to=to, subject=subject, body=body, html=html, ref=ref, calendar=calendar)


def send_interview_scheduled(
    *,
    to: str,
    ref: str | None = None,
    candidate_name: str,
    candidate_email: str,
    interviewer_name: str,
    job_title: str,
    company_name: str,
    title: str,
    description: str,
    start: datetime,
    duration_minutes: int,
    timezone: str,
    location: str,
    uid: str,
    sequence: int,
    applicant_url: str,
    rescheduled: bool,
    controller_name: str | None = None,
    privacy_url: str | None = None,
) -> None:
    """Interviewer copy of the booking (or reschedule) with the invite.ics.
    An empty ``candidate_email`` (a row queued before reviewer interviewers got
    the address) leaves the candidate out of the event; the interviewer stays
    as its attendee, so the REQUEST and any later update or CANCEL stay valid."""
    safe_candidate = escape(candidate_name)
    safe_job = escape(job_title)
    safe_company = escape(company_name)
    when = _local_when(start, timezone)
    verb = "moved" if rescheduled else "booked"
    subject = f"Interview {verb}: {candidate_name} - {job_title}"
    where_text = f"Where: {location}\n" if location else ""

    body = (
        f"Hi {interviewer_name},\n"
        f"\n"
        f"{candidate_name} {verb} the {title} for the {job_title} position:\n"
        f"{when} ({timezone}), {duration_minutes} minutes.\n" + where_text + f"\n"
        f"The attached calendar invite adds it to your calendar.\n"
        f"Open the applicant: {applicant_url}\n"
        f"\n"
        f"- {company_name} (via Ganek)\n" + _privacy_text(privacy_url)
    )
    content = (
        f'<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        f"Interview {verb}</h1>"
        + _paragraph(
            f'<b style="font-weight: 600;">{safe_candidate}</b> {verb} the {escape(title)} '
            f'for the {safe_job} position: <b style="font-weight: 600;">{when}</b> '
            f'<span style="font-family: monospace; font-size: 12px;">({escape(timezone)})</span>, '
            f"{duration_minutes} minutes."
        )
        + (_paragraph(f"Where: {escape(location)}") if location else "")
        + f'<a href="{applicant_url}" style="margin-top: 22px; display: block; text-align: center; '
        f"height: 46px; line-height: 46px; background: {DEFAULT_BRAND_PRIMARY}; color: #ffffff; "
        f'border-radius: 10px; font-size: 15px; font-weight: 600; text-decoration: none;">'
        f"Open the applicant</a>"
        + _paragraph("The attached calendar invite adds the interview to your calendar.")
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
    calendar = _calendar_part(
        method="REQUEST",
        uid=uid,
        sequence=sequence,
        start=start,
        duration_minutes=duration_minutes,
        summary=f"{title} - {candidate_name} ({job_title})",
        description=description,
        location=location,
        company_name=company_name,
        attendees=(
            ((candidate_name, candidate_email), (interviewer_name, to))
            if candidate_email
            else ((interviewer_name, to),)
        ),
        url=applicant_url,
    )
    send_email(to=to, subject=subject, body=body, html=html, ref=ref, calendar=calendar)


def send_interview_reminder_interviewer(
    *,
    to: str,
    ref: str | None = None,
    interviewer_name: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    start: datetime,
    timezone: str,
    location: str,
    applicant_url: str,
    controller_name: str | None = None,
    privacy_url: str | None = None,
) -> None:
    """T-24h reminder for the interviewer (no calendar part: the invite
    already sits in their calendar)."""
    safe_candidate = escape(candidate_name)
    safe_job = escape(job_title)
    safe_company = escape(company_name)
    when = _local_when(start, timezone)
    subject = f"Reminder: interview with {candidate_name} tomorrow"

    body = (
        f"Hi {interviewer_name},\n"
        f"\n"
        f"Your interview with {candidate_name} for the {job_title} position is\n"
        f"coming up: {when} ({timezone}).\n" + (f"Where: {location}\n" if location else "") + f"\n"
        f"Open the applicant: {applicant_url}\n"
        f"\n"
        f"- {company_name} (via Ganek)\n" + _privacy_text(privacy_url)
    )
    content = (
        '<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        "Interview tomorrow</h1>"
        + _paragraph(
            f'Your interview with <b style="font-weight: 600;">{safe_candidate}</b> for the '
            f'{safe_job} position: <b style="font-weight: 600;">{when}</b> '
            f'<span style="font-family: monospace; font-size: 12px;">({escape(timezone)})</span>.'
        )
        + (_paragraph(f"Where: {escape(location)}") if location else "")
        + f'<a href="{applicant_url}" style="margin-top: 22px; display: block; text-align: center; '
        f"height: 46px; line-height: 46px; background: {DEFAULT_BRAND_PRIMARY}; color: #ffffff; "
        f'border-radius: 10px; font-size: 15px; font-weight: 600; text-decoration: none;">'
        f"Open the applicant</a>"
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


def _scorecard_mail(
    *,
    to: str,
    ref: str | None,
    company_name: str,
    subject: str,
    heading: str,
    line: str,
    url: str,
    brand_primary: str | None,
) -> None:
    """Shared body of the two scorecard mails: one sentence and one button."""
    brand = brand_primary or DEFAULT_BRAND_PRIMARY
    brand_fg = _brand_foreground(brand)
    safe_company = escape(company_name)
    body = f"Hi,\n\n{line}\n\nOpen the scorecard: {url}\n\n- {company_name} (via Ganek)\n"
    content = (
        '<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        f"{escape(heading)}</h1>"
        + _paragraph(escape(line))
        + f'<a href="{escape(url)}" style="margin-top: 22px; display: block; text-align: center; '
        f"height: 46px; line-height: 46px; background: {brand}; color: {brand_fg}; "
        f'border-radius: 10px; font-size: 15px; font-weight: 600; text-decoration: none;">'
        f"Open scorecard</a>"
    )
    html = _card_html(
        bar_color=brand, brand=brand, brand_fg=brand_fg, safe_company=safe_company, content=content
    )
    send_email(to=to, subject=subject, body=body, html=html, ref=ref)


def send_scorecard_request(
    *,
    to: str,
    ref: str | None = None,
    company_name: str,
    requester_label: str,
    candidate_name: str,
    job_title: str,
    url: str,
    brand_primary: str | None,
) -> None:
    """A teammate asked for this person's scorecard (not editable in the
    templates feature)."""
    _scorecard_mail(
        to=to,
        ref=ref,
        company_name=company_name,
        subject=f"{requester_label} asked for your scorecard on {candidate_name} for {job_title}",
        heading="Scorecard requested",
        line=(
            f"{requester_label} asked for your scorecard on {candidate_name} "
            f"for the {job_title} position."
        ),
        url=url,
        brand_primary=brand_primary,
    )


def send_scorecard_reminder(
    *,
    to: str,
    ref: str | None = None,
    company_name: str,
    candidate_name: str,
    job_title: str,
    url: str,
    waiting_days: int,
    brand_primary: str | None,
) -> None:
    """One nudge after the reminder window; the worker sends it once per request."""
    _scorecard_mail(
        to=to,
        ref=ref,
        company_name=company_name,
        subject=f"Still waiting on your scorecard for {candidate_name}",
        heading="Still waiting on your scorecard",
        line=(
            f"Your scorecard on {candidate_name} for the {job_title} position "
            f"has been waiting {waiting_days} days."
        ),
        url=url,
        brand_primary=brand_primary,
    )
