"""Outbound email. SMTP when configured, logged no-op otherwise.

Sending must never break a user-facing flow: callers schedule sends as
background tasks and this module swallows transport errors with a log.
(Queue-based delivery via arq arrives with later milestones.)
"""

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def smtp_configured() -> bool:
    return settings.smtp_host is not None


def send_email(*, to: str, subject: str, body: str) -> None:
    if not smtp_configured():
        logger.info("SMTP not configured; skipping email %r to %s", subject, to)
        return
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

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
