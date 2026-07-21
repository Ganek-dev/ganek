import smtplib
from email.message import EmailMessage

import pytest

from app.core.config import settings
from app.services import email as email_service


class FakeSMTP:
    sent: list[EmailMessage] = []
    logins: list[tuple[str, str]] = []
    starttls_calls = 0

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host = host
        self.port = port

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def starttls(self) -> None:
        FakeSMTP.starttls_calls += 1

    def login(self, user: str, password: str) -> None:
        FakeSMTP.logins.append((user, password))

    def send_message(self, message: EmailMessage) -> None:
        FakeSMTP.sent.append(message)


@pytest.fixture(autouse=True)
def _reset_fake() -> None:
    FakeSMTP.sent = []
    FakeSMTP.logins = []
    FakeSMTP.starttls_calls = 0


def test_noop_without_smtp_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "smtp_host", None)
    # must not raise, must not attempt a connection
    email_service.send_email(to="x@example.com", subject="s", body="b")


def test_sends_via_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(settings, "smtp_user", "mailer")
    monkeypatch.setattr(settings, "smtp_password", "hunter2")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    email_service.send_application_received(
        to="jane@example.com",
        candidate_name="Jane",
        job_title="Backend Engineer",
        company_name="Acme",
    )

    assert len(FakeSMTP.sent) == 1
    message = FakeSMTP.sent[0]
    assert message["To"] == "jane@example.com"
    assert message["Subject"] == "Application received — Backend Engineer at Acme"
    assert "Hi Jane," in message.get_content()
    assert "Backend Engineer position at Acme" in message.get_content()
    assert FakeSMTP.logins == [("mailer", "hunter2")]
    assert FakeSMTP.starttls_calls == 1


def test_transport_errors_are_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")

    class ExplodingSMTP(FakeSMTP):
        def send_message(self, message: EmailMessage) -> None:
            raise smtplib.SMTPException("boom")

    monkeypatch.setattr(smtplib, "SMTP", ExplodingSMTP)
    # send_application_received must never raise
    email_service.send_application_received(
        to="jane@example.com", candidate_name="J", job_title="T", company_name="C"
    )
