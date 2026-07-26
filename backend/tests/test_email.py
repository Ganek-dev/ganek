import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

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


def _invite_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "to": "marta@example.com",
        "candidate_name": "Marta",
        "job_title": "Senior Frontend Engineer",
        "company_name": "Northwind Robotics",
        "brand_primary": "#3d5afe",
        "quiz_url": "https://jobs.example.com/quiz/tok123",
        "question_count": 12,
        "seconds_per_question": 25,
        "expires_at": datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
    }
    kwargs.update(overrides)
    return kwargs


def _sent_parts(message: EmailMessage) -> tuple[str, str]:
    plain = message.get_body(preferencelist=("plain",))
    html = message.get_body(preferencelist=("html",))
    assert plain is not None and html is not None, "invite must be multipart/alternative"
    return str(plain.get_content()), str(html.get_content())


def test_quiz_invite_renders_link_details_and_branding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    email_service.send_quiz_invite(**_invite_kwargs())

    assert len(FakeSMTP.sent) == 1
    message = FakeSMTP.sent[0]
    assert message["To"] == "marta@example.com"
    assert message["Subject"] == "Your Northwind Robotics assessment — one step left"
    text, html = _sent_parts(message)
    for part in (text, html):
        assert "https://jobs.example.com/quiz/tok123" in part
        assert "Marta" in part
        assert "Senior Frontend Engineer" in part
        assert "12" in part  # question count
        assert "25s" in part  # per-question timer
        assert "one attempt" in part
        assert "Jul 31" in part  # link validity from expires_at
    assert "#3d5afe" in html  # brand top bar + CTA
    assert "Sent by vetd on behalf of Northwind Robotics" in html


def test_quiz_invite_defaults_brand_and_omits_timer_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    email_service.send_quiz_invite(**_invite_kwargs(brand_primary=None, seconds_per_question=None))

    text, html = _sent_parts(FakeSMTP.sent[0])
    assert "#18181b" in html  # default brand
    assert "per question" not in text
    assert "per question" not in html


def test_quiz_invite_transport_errors_are_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")

    class ExplodingSMTP(FakeSMTP):
        def send_message(self, message: EmailMessage) -> None:
            raise smtplib.SMTPException("boom")

    monkeypatch.setattr(smtplib, "SMTP", ExplodingSMTP)
    email_service.send_quiz_invite(**_invite_kwargs())  # must not raise


def test_stage_advance_renders_branding_and_team_signoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    email_service.send_stage_advance(
        to="marta@example.com",
        candidate_name="Marta",
        job_title="Senior Frontend Engineer",
        company_name="Northwind Robotics",
        brand_primary="#3d5afe",
    )

    message = FakeSMTP.sent[0]
    assert message["Subject"] == "Next step: interviews at Northwind Robotics"
    text, html = _sent_parts(message)
    for part in (text, html):
        assert "Good news, Marta" in part
        assert "Senior Frontend Engineer" in part
        assert "move you to interviews" in part
        assert "hiring team" in part
    assert "#3d5afe" in html
    assert "Sent by vetd on behalf of Northwind Robotics" in html


def test_rejection_renders_neutral_with_assessment_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    email_service.send_rejection(
        to="tomas@example.com",
        candidate_name="Tomas",
        job_title="Backend Engineer (Python)",
        company_name="Northwind Robotics",
        careers_url="https://jobs.example.com/c/northwind-robotics",
        completed_assessment=True,
    )

    message = FakeSMTP.sent[0]
    assert message["Subject"] == "Your application to Northwind Robotics"
    text, html = _sent_parts(message)
    for part in (text, html):
        assert "Thank you, Tomas" in part
        assert "Backend Engineer (Python)" in part
        assert "won't be moving forward" in part
        assert "a real person reviewed it" in part
        assert "https://jobs.example.com/c/northwind-robotics" in part
    # neutral gray top bar — a rejection never carries brand accents
    assert "#d4d4d8" in html


def test_rejection_omits_assessment_line_without_completed_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    email_service.send_rejection(
        to="tomas@example.com",
        candidate_name="Tomas",
        job_title="Backend Engineer (Python)",
        company_name="Northwind Robotics",
        careers_url="https://jobs.example.com/c/northwind-robotics",
        completed_assessment=False,
    )

    text, html = _sent_parts(FakeSMTP.sent[0])
    assert "a real person reviewed it" not in text
    assert "a real person reviewed it" not in html


def test_stage_emails_swallow_transport_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")

    class ExplodingSMTP(FakeSMTP):
        def send_message(self, message: EmailMessage) -> None:
            raise smtplib.SMTPException("boom")

    monkeypatch.setattr(smtplib, "SMTP", ExplodingSMTP)
    email_service.send_stage_advance(
        to="a@b.c", candidate_name="A", job_title="T", company_name="C", brand_primary=None
    )
    email_service.send_rejection(
        to="a@b.c",
        candidate_name="A",
        job_title="T",
        company_name="C",
        careers_url="https://x.example",
        completed_assessment=False,
    )


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
