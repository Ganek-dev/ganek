"""Transport selection and the Mailjet adapter (board card A7).

The SMTP path keeps its coverage in test_email.py (FakeSMTP); here the
HTTP provider is driven through the module's one JSON POST seam.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.config import settings
from app.services import email as email_service
from app.services import email_providers as providers


@pytest.fixture
def mailjet(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    monkeypatch.setattr(settings, "email_provider", "mailjet")
    monkeypatch.setattr(settings, "mailjet_api_key", "key")
    monkeypatch.setattr(settings, "mailjet_secret_key", "secret")
    monkeypatch.setattr(settings, "email_from", "Acme Jobs <jobs@acme.example>")
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, *, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        calls.append({"url": url, "headers": headers, "body": body})
        return {"Messages": [{"Status": "success", "To": [{"Email": "x"}]}]}

    monkeypatch.setattr(providers, "_http_post_json", fake_post)
    return calls


def test_default_provider_is_smtp_and_configured_follows_its_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "email_provider", "smtp")
    monkeypatch.setattr(settings, "smtp_host", None)
    assert providers.current().name == "smtp"
    assert email_service.configured() is False
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    assert email_service.configured() is True


def test_mailjet_needs_both_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "email_provider", "mailjet")
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")  # irrelevant now
    monkeypatch.setattr(settings, "mailjet_api_key", "key")
    monkeypatch.setattr(settings, "mailjet_secret_key", None)
    assert providers.current().name == "mailjet"
    assert email_service.configured() is False
    monkeypatch.setattr(settings, "mailjet_secret_key", "secret")
    assert email_service.configured() is True


def test_mailjet_send_builds_the_v31_payload(mailjet: list[dict[str, Any]]) -> None:
    email_service.send_email(
        to="jane@example.com",
        subject="Hello",
        body="plain",
        html="<p>rich</p>",
        outbox_id="row-1",
    )
    assert len(mailjet) == 1
    call = mailjet[0]
    assert call["url"] == providers.MAILJET_SEND_URL
    assert call["headers"]["Authorization"] == "Basic a2V5OnNlY3JldA=="  # key:secret
    assert call["body"] == {
        "Messages": [
            {
                "From": {"Email": "jobs@acme.example", "Name": "Acme Jobs"},
                "To": [{"Email": "jane@example.com"}],
                "Subject": "Hello",
                "TextPart": "plain",
                "HTMLPart": "<p>rich</p>",
                "CustomID": "row-1",
            }
        ]
    }


def test_mailjet_omits_optional_parts(mailjet: list[dict[str, Any]]) -> None:
    email_service.send_email(to="jane@example.com", subject="Hello", body="plain")
    entry = mailjet[0]["body"]["Messages"][0]
    assert "HTMLPart" not in entry
    assert "CustomID" not in entry


def test_mailjet_sends_reply_to_when_given(mailjet: list[dict[str, Any]]) -> None:
    email_service.send_email(
        to="jane@example.com", subject="Hello", body="plain", reply_to="erika@acme.example"
    )
    entry = mailjet[0]["body"]["Messages"][0]
    assert entry["ReplyTo"] == {"Email": "erika@acme.example"}

    email_service.send_email(to="jane@example.com", subject="Hello", body="plain")
    assert "ReplyTo" not in mailjet[1]["body"]["Messages"][0]


def test_mailjet_per_message_rejection_raises(
    mailjet: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    def rejecting(url: str, *, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        return {
            "Messages": [
                {"Status": "error", "Errors": [{"ErrorMessage": '"jane" is an invalid email'}]}
            ]
        }

    monkeypatch.setattr(providers, "_http_post_json", rejecting)
    with pytest.raises(providers.ProviderError, match="invalid email"):
        email_service.send_email(to="jane", subject="Hello", body="plain")


def test_mailjet_transport_errors_raise_provider_error(
    mailjet: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    def exploding(url: str, *, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        raise providers.ProviderError("HTTP 401: unauthorized")

    monkeypatch.setattr(providers, "_http_post_json", exploding)
    with pytest.raises(providers.ProviderError, match="401"):
        email_service.send_email(to="jane@example.com", subject="Hello", body="plain")


def test_unconfigured_mailjet_skips_without_calling_out(
    mailjet: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mailjet_api_key", None)
    email_service.send_email(to="jane@example.com", subject="Hello", body="plain")
    assert mailjet == []


def test_http_post_json_maps_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import urllib.error
    import urllib.request

    def failing(request: Any, timeout: int) -> Any:
        raise urllib.error.HTTPError(
            request.full_url, 400, "Bad Request", {}, io.BytesIO(b'{"ErrorMessage":"nope"}')
        )

    monkeypatch.setattr(urllib.request, "urlopen", failing)
    with pytest.raises(providers.ProviderError, match="HTTP 400: .*nope"):
        providers._http_post_json("https://example.invalid/x", headers={}, body={})


def test_mailjet_attaches_calendar_base64(mailjet: list[dict[str, Any]]) -> None:
    import base64

    content = "BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nEND:VCALENDAR\r\n"
    providers.current().send(
        providers.OutboundMessage(
            to="jane@example.com",
            subject="Confirmed",
            text="see attached",
            calendar=providers.CalendarPart(method="REQUEST", content=content),
        )
    )
    entry = mailjet[0]["body"]["Messages"][0]
    assert entry["Attachments"] == [
        {
            "ContentType": "text/calendar",
            "Filename": "invite.ics",
            "Base64Content": base64.b64encode(content.encode()).decode(),
        }
    ]


def test_mailjet_without_calendar_sends_no_attachments(mailjet: list[dict[str, Any]]) -> None:
    providers.current().send(
        providers.OutboundMessage(to="jane@example.com", subject="Plain", text="hi")
    )
    assert "Attachments" not in mailjet[0]["body"]["Messages"][0]


def test_send_email_passes_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[providers.OutboundMessage] = []

    class Capture:
        name = "capture"

        def configured(self) -> bool:
            return True

        def send(self, message: providers.OutboundMessage) -> None:
            sent.append(message)

    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(providers, "current", lambda: Capture())
    part = providers.CalendarPart(method="CANCEL", content="BEGIN:VCALENDAR\r\n")
    email_service.send_email(to="a@b.c", subject="s", body="b", calendar=part)
    assert sent[0].calendar is part
