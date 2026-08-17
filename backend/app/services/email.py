"""Outbound email. SMTP when configured, logged no-op otherwise.

Senders RAISE on transport errors since M5.7 H4: every send goes through
the email outbox (services/outbox.py), whose worker job owns retry with
backoff and records the failure on the row. Never call a sender directly
from a request path — queue it.
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


def send_email(
    *, to: str, subject: str, body: str, html: str | None = None, ref: str | None = None
) -> None:
    if not smtp_configured():
        logger.info("SMTP not configured; skipping email %r (ref=%s)", subject, ref)
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
    *,
    to: str,
    ref: str | None = None,
    candidate_name: str,
    job_title: str,
    company_name: str,
    privacy_url: str | None = None,
) -> None:
    subject = f"Application received — {job_title} at {company_name}"
    body = (
        f"Hi {candidate_name},\n"
        f"\n"
        f"Thanks for applying for the {job_title} position at {company_name}.\n"
        f"Your application and CV were received; the team will review them and\n"
        f"get back to you.\n"
        f"\n"
        f"— {company_name} (via Vetd)\n" + _privacy_text(privacy_url)
    )
    send_email(to=to, subject=subject, body=body, ref=ref)


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
        f"— {company_name} (via Vetd)\n" + _privacy_text(privacy_url)
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
        safe_controller=escape(controller_name) if controller_name else None,
        privacy_url=privacy_url,
    )

    send_email(to=to, subject=subject, body=body, html=html, ref=ref)


def _card_html(
    *,
    bar_color: str,
    brand: str,
    brand_fg: str,
    safe_company: str,
    content: str,
    safe_controller: str | None = None,
    privacy_url: str | None = None,
) -> str:
    """Shared email card (handoff 17/22): top bar, logo chip, content, footer.

    The footer names the data controller (legal name when the company set
    one — M5.6 G1) and links their privacy notice on candidate-facing mail.
    """
    footer = f"Sent by vetd on behalf of {safe_controller or safe_company}"
    if privacy_url:
        footer += (
            f' · <a href="{privacy_url}" style="color: #a1a1aa; '
            f'text-decoration: underline;">privacy notice</a>'
        )
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
        f"{footer}</div>"
    )


def _privacy_text(privacy_url: str | None) -> str:
    """Trailing plain-text privacy pointer for candidate emails."""
    return f"\nPrivacy & your data: {privacy_url}\n" if privacy_url else ""


def _paragraph(inner: str) -> str:
    return (
        f'<p style="margin: 12px 0 0; font-size: 14.5px; line-height: 22px; '
        f'color: #3f3f46;">{inner}</p>'
    )


NEUTRAL_BAR = "#d4d4d8"  # rejections never carry brand accents


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
) -> None:
    """Assessment reminder (design 17b), sent manually by a recruiter.

    Never claims the application auto-closes — only the link expires.
    """
    brand = brand_primary or DEFAULT_BRAND_PRIMARY
    brand_fg = _brand_foreground(brand)
    safe_job = escape(job_title)
    safe_company = escape(company_name)
    expires_on = f"{expires_at:%a}, {expires_at:%b} {expires_at.day}"

    if days_left <= 0:
        window = "today"
        heading_tail = "last day"
    elif days_left == 1:
        window = "in 1 day"
        heading_tail = "1 day left"
    else:
        window = f"in {days_left} days"
        heading_tail = f"{days_left} days left"
    subject = f"Your assessment link expires {window}"
    heading = f"Still in — {heading_tail}"

    body = (
        f"Hi {candidate_name},\n"
        f"\n"
        f"{heading}. Your assessment for {job_title} at {company_name} is\n"
        f"waiting. It takes about 10 minutes.\n"
        f"\n"
        f"The link stops working after {expires_on}.\n"
        f"\n"
        f"Take it now: {quiz_url}\n"
        f"\n"
        f"— {company_name} (via Vetd)\n" + _privacy_text(privacy_url)
    )
    content = (
        f'<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        f"{heading}</h1>"
        + _paragraph(
            f'Your assessment for <b style="font-weight: 600;">{safe_job}</b> is waiting. '
            f"It takes about 10 minutes."
        )
        + f'<div style="margin-top: 18px; border: 1px solid #f0d9b5; background: #fdf9f2; '
        f'border-radius: 10px; padding: 12px 16px; font-size: 13px; color: #7c5a2b;">'
        f'Link stops working after <b style="font-weight: 600;">{expires_on}</b>.</div>'
        + f'<a href="{quiz_url}" style="margin-top: 20px; display: block; text-align: center; '
        f"height: 46px; line-height: 46px; background: {brand}; color: {brand_fg}; "
        f'border-radius: 10px; font-size: 15px; font-weight: 600; text-decoration: none;">'
        f"Take it now — ~10 min</a>"
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
        + (f"Track your application: {status_url}\n\n" if status_url else "")
        + f"Looking forward to it,\n"
        f"The {company_name} hiring team\n" + _privacy_text(privacy_url)
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
        + (
            f'<div style="margin-top: 16px; font-family: monospace; font-size: 11px; '
            f'color: #a1a1aa;"><a href="{status_url}" style="color: #a1a1aa; '
            f'text-decoration: underline;">application status</a></div>'
            if status_url
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
        f"The {company_name} hiring team\n" + _privacy_text(privacy_url)
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
        safe_controller=escape(controller_name) if controller_name else None,
        privacy_url=privacy_url,
    )

    send_email(to=to, subject=subject, body=body, html=html, ref=ref)


# Matches the team page's role select labels (Owner/Recruiter naming is
# still an open design decision — the shipped UI says Member).
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
    subject = f"You're invited to join {company_name} on vetd"

    body = (
        f"Hi,\n"
        f"\n"
        f"{inviter_email} invited you to join {company_name}'s hiring workspace\n"
        f"on vetd as {role_label}.\n"
        f"\n"
        f"Accept the invite and set your password: {invite_url}\n"
        f"\n"
        f"Invite valid until {valid_until}.\n"
        f"\n"
        f"— {company_name} (via Vetd)\n"
    )
    content = (
        f'<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        f"Join {safe_company} on vetd</h1>"
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
    subject = "Verify your email to activate your vetd workspace"

    body = (
        f"Hi,\n"
        f"\n"
        f"You're one click away from activating the {company_name} hiring\n"
        f"workspace on vetd. Confirm this is your email address:\n"
        f"\n"
        f"{verify_url}\n"
        f"\n"
        f"The link works for {expires_days} days; unverified workspaces are\n"
        f"removed after a week. If you didn't sign up, ignore this email.\n"
        f"\n"
        f"— vetd\n"
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
    subject = "Reset your vetd password"

    body = (
        f"Hi,\n"
        f"\n"
        f"Someone asked to reset the password for your {company_name}\n"
        f"workspace account on vetd. If that was you, set a new password\n"
        f"here (the link works for {expires_minutes} minutes):\n"
        f"\n"
        f"{reset_url}\n"
        f"\n"
        f"If it wasn't you, ignore this email — your password is unchanged\n"
        f"and the link expires on its own.\n"
        f"\n"
        f"— {company_name} (via Vetd)\n"
    )
    content = (
        '<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        "Reset your password</h1>"
        + _paragraph(
            f"Someone asked to reset the password for your {safe_company} workspace "
            f"account. If that was you, set a new one below; if not, ignore this "
            f"email — your password is unchanged."
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

    Mitigates silent pre-registration takeovers — the legitimate owner
    learns immediately if someone else's Google sign-in claimed their email.
    """
    safe_company = escape(company_name)
    subject = "Google sign-in was added to your Vetd account"
    body = (
        f"Hi,\n"
        f"\n"
        f"Signing in with Google is now enabled for your Vetd account\n"
        f"at {company_name}. Your password continues to work as before.\n"
        f"\n"
        f"If you did not just sign in with Google, change your password\n"
        f"in Settings -> Account right away.\n"
        f"\n"
        f"— Vetd\n"
    )
    content = (
        '<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        "Google sign-in added</h1>"
        + _paragraph(
            f"Signing in with Google is now enabled for your Vetd account at "
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
    subject = f"Pick a time — interview for {job_title} at {company_name}"

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
        f"— {company_name} (via Vetd)\n" + _privacy_text(privacy_url)
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
    subject = f"Interview cancelled — {job_title} at {company_name}"

    body = (
        f"Hi {candidate_name},\n"
        f"\n"
        f"The scheduled interview for the {job_title} position at\n"
        f"{company_name} has been cancelled. If a new time is needed,\n"
        f"you'll receive a fresh scheduling link.\n"
        f"\n"
        f"— {company_name} (via Vetd)\n" + _privacy_text(privacy_url)
    )
    content = (
        '<h1 style="margin: 22px 0 0; font-size: 22px; line-height: 1.25; font-weight: 600;">'
        "Interview cancelled</h1>"
        + _paragraph(
            f"Hi {safe_candidate} — the scheduled interview for the "
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
        f"— {company_name} (via Vetd)\n" + _privacy_text(privacy_url)
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
