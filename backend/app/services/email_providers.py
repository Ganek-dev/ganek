"""Outbound email transports behind one interface (board card A7).

``services/email.py`` renders every message and hands an ``OutboundMessage``
to ``current()``; the provider is chosen by ``GANEK_EMAIL_PROVIDER``:

- ``smtp`` (default): any relay via smtplib, exactly as before this module.
- ``mailjet``: Mailjet's Send API v3.1 over HTTPS (EU-hosted, Paris).
  Chosen over an SMTP relay because it is the provider whose bounce and
  complaint events feed the suppression list; the API key pair replaces
  SMTP credentials.

Providers are synchronous on purpose: senders run inside the arq worker
(or the admin's synchronous test send), never in a request path. Transport
errors raise, and the outbox owns retry. No new runtime dependency: the
HTTP provider uses the standard library so the image stays as it was.
"""

from __future__ import annotations

import base64
import json
import logging
import smtplib
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any, Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 10
MAILJET_SEND_URL = "https://api.mailjet.com/v3.1/send"


@dataclass(frozen=True)
class OutboundMessage:
    to: str
    subject: str
    text: str
    html: str | None = None
    # outbox row id, when known: rides along as the provider's custom id so
    # bounce and complaint events can be mapped back to the row
    outbox_id: str | None = None
    # one-off messages answer to the recruiter who wrote them (PR 4);
    # stage mail carries none
    reply_to: str | None = None


class EmailProvider(Protocol):
    name: str

    def configured(self) -> bool: ...

    def send(self, message: OutboundMessage) -> None: ...


class ProviderError(Exception):
    """The provider refused or failed to accept the message (not retryable
    by the caller's own logic; the outbox backoff decides)."""


class SmtpProvider:
    name = "smtp"

    def configured(self) -> bool:
        return settings.smtp_host is not None

    def send(self, message: OutboundMessage) -> None:
        mime = EmailMessage()
        mime["From"] = settings.email_from
        mime["To"] = message.to
        mime["Subject"] = message.subject
        if message.reply_to is not None:
            mime["Reply-To"] = message.reply_to
        mime.set_content(message.text)
        if message.html is not None:
            mime.add_alternative(message.html, subtype="html")

        assert settings.smtp_host is not None
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=HTTP_TIMEOUT_SECONDS
        ) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_user and settings.smtp_password:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(mime)


def _http_post_json(url: str, *, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    """Tiny JSON POST; tests replace this, production never needs more.

    Returns the decoded body on 2xx; raises ``ProviderError`` with the
    status and the (truncated) response text otherwise.
    """
    if not url.startswith("https://"):  # the providers above are fixed https URLs
        raise ProviderError(f"refusing non-https provider URL {url!r}")
    data = json.dumps(body).encode()
    request = urllib.request.Request(  # noqa: S310 - scheme checked above
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https URL
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:500].decode(errors="replace")
        raise ProviderError(f"HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"request failed: {exc}") from exc
    decoded: dict[str, Any] = json.loads(payload or b"{}")
    return decoded


class MailjetProvider:
    name = "mailjet"

    def configured(self) -> bool:
        return bool(settings.mailjet_api_key and settings.mailjet_secret_key)

    def send(self, message: OutboundMessage) -> None:
        assert settings.mailjet_api_key and settings.mailjet_secret_key
        from_name, from_email = parseaddr(settings.email_from)
        sender: dict[str, str] = {"Email": from_email or settings.email_from}
        if from_name:
            sender["Name"] = from_name
        entry: dict[str, Any] = {
            "From": sender,
            "To": [{"Email": message.to}],
            "Subject": message.subject,
            "TextPart": message.text,
        }
        if message.html is not None:
            entry["HTMLPart"] = message.html
        if message.outbox_id is not None:
            entry["CustomID"] = message.outbox_id
        if message.reply_to is not None:
            entry["ReplyTo"] = {"Email": message.reply_to}
        credentials = f"{settings.mailjet_api_key}:{settings.mailjet_secret_key}".encode()
        response = _http_post_json(
            MAILJET_SEND_URL,
            headers={"Authorization": "Basic " + base64.b64encode(credentials).decode()},
            body={"Messages": [entry]},
        )
        # a 200 can still carry a per-message rejection
        for result in response.get("Messages", []):
            if result.get("Status") != "success":
                errors = result.get("Errors") or []
                reason = "; ".join(str(e.get("ErrorMessage", e)) for e in errors) or "rejected"
                raise ProviderError(f"mailjet rejected the message: {reason}")


PROVIDERS: dict[str, EmailProvider] = {
    SmtpProvider.name: SmtpProvider(),
    MailjetProvider.name: MailjetProvider(),
}


def current() -> EmailProvider:
    return PROVIDERS[settings.email_provider]


def configured() -> bool:
    """Whether outbound email can be delivered at all on this instance."""
    return current().configured()
