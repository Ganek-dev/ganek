import logging
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
    assert "Sent by Ganek on behalf of Northwind Robotics" in html


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


def test_privacy_footer_names_controller_and_links_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M5.6 G1: candidate emails carry the controller identity + notice link."""
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    email_service.send_quiz_invite(
        **_invite_kwargs(
            controller_name="Northwind Robotics Sp. z o.o.",
            privacy_url="https://jobs.example.com/c/northwind/privacy",
        )
    )

    text, html = _sent_parts(FakeSMTP.sent[0])
    assert "Privacy & your data: https://jobs.example.com/c/northwind/privacy" in text
    assert "Sent by Ganek on behalf of Northwind Robotics Sp. z o.o." in html
    assert 'href="https://jobs.example.com/c/northwind/privacy"' in html
    assert ">privacy notice</a>" in html


def test_privacy_footer_absent_when_not_wired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    email_service.send_quiz_invite(**_invite_kwargs())

    text, html = _sent_parts(FakeSMTP.sent[0])
    assert "Privacy & your data" not in text
    assert "privacy notice" not in html
    # footer falls back to the display name
    assert "Sent by Ganek on behalf of Northwind Robotics" in html


def test_quiz_invite_transport_errors_propagate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Since the outbox (M5.7 H4) senders RAISE — the worker owns retry."""
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")

    class ExplodingSMTP(FakeSMTP):
        def send_message(self, message: EmailMessage) -> None:
            raise smtplib.SMTPException("boom")

    monkeypatch.setattr(smtplib, "SMTP", ExplodingSMTP)
    with pytest.raises(smtplib.SMTPException):
        email_service.send_quiz_invite(**_invite_kwargs())


def test_quiz_reminder_renders_expiry_and_link(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    email_service.send_quiz_reminder(
        to="marta@example.com",
        candidate_name="Marta",
        job_title="Senior Frontend Engineer",
        company_name="Northwind Robotics",
        brand_primary="#3d5afe",
        quiz_url="https://jobs.example.com/quiz/tok123",
        expires_at=datetime(2026, 7, 31, 18, 0, tzinfo=UTC),
        days_left=2,
    )

    message = FakeSMTP.sent[0]
    assert message["Subject"] == "Your assessment link expires in 2 days"
    text, html = _sent_parts(message)
    for part in (text, html):
        assert "Still in — 2 days left" in part
        assert "Senior Frontend Engineer" in part
        assert "https://jobs.example.com/quiz/tok123" in part
        assert "Jul 31" in part
        assert "stops working" in part  # never claims the application auto-closes
    assert "#3d5afe" in html


def test_quiz_reminder_singular_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    email_service.send_quiz_reminder(
        to="marta@example.com",
        candidate_name="Marta",
        job_title="T",
        company_name="C",
        brand_primary=None,
        quiz_url="https://x.example/quiz/t",
        expires_at=datetime(2026, 7, 31, 18, 0, tzinfo=UTC),
        days_left=1,
    )

    message = FakeSMTP.sent[0]
    assert message["Subject"] == "Your assessment link expires in 1 day"
    text, _ = _sent_parts(message)
    assert "Still in — 1 day left" in text


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
    assert "Sent by Ganek on behalf of Northwind Robotics" in html


def test_stage_advance_links_status_page_when_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    email_service.send_stage_advance(
        to="marta@example.com",
        candidate_name="Marta",
        job_title="T",
        company_name="C",
        brand_primary=None,
        status_url="https://jobs.example.com/application/status-tok",
    )

    text, html = _sent_parts(FakeSMTP.sent[0])
    assert "https://jobs.example.com/application/status-tok" in text
    assert "https://jobs.example.com/application/status-tok" in html
    assert "application status" in html


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


def test_stage_and_confirmation_transport_errors_propagate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")

    class ExplodingSMTP(FakeSMTP):
        def send_message(self, message: EmailMessage) -> None:
            raise smtplib.SMTPException("boom")

    monkeypatch.setattr(smtplib, "SMTP", ExplodingSMTP)
    with pytest.raises(smtplib.SMTPException):
        email_service.send_stage_advance(
            to="a@b.c", candidate_name="A", job_title="T", company_name="C", brand_primary=None
        )
    with pytest.raises(smtplib.SMTPException):
        email_service.send_rejection(
            to="a@b.c",
            candidate_name="A",
            job_title="T",
            company_name="C",
            careers_url="https://x.example",
            completed_assessment=False,
        )
    with pytest.raises(smtplib.SMTPException):
        email_service.send_application_received(
            to="jane@example.com", candidate_name="J", job_title="T", company_name="C"
        )


def test_transport_failure_logs_nothing_here(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """M5.6 G4 continues to hold under the outbox: this module no longer
    logs failures at all (nothing to leak an address into) — the worker's
    failure line carries the outbox row id, never the recipient."""
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")

    class ExplodingSMTP(FakeSMTP):
        def send_message(self, message: EmailMessage) -> None:
            raise smtplib.SMTPException("boom")

    monkeypatch.setattr(smtplib, "SMTP", ExplodingSMTP)
    with caplog.at_level(logging.INFO, logger="app.services.email"):
        with pytest.raises(smtplib.SMTPException):
            email_service.send_quiz_invite(
                **_invite_kwargs(ref="11111111-2222-3333-4444-555555555555")
            )

    assert "marta@example.com" not in caplog.text
    assert caplog.text == ""


def test_smtp_unconfigured_skip_log_hides_address(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "smtp_host", None)
    with caplog.at_level(logging.INFO, logger="app.services.email"):
        email_service.send_email(to="x@example.com", subject="s", body="b", ref="ref-1")

    assert "x@example.com" not in caplog.text
    assert "ref=ref-1" in caplog.text


def test_send_google_linked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    email_service.send_google_linked(to="user@gmail.com", company_name="Acme")

    assert len(FakeSMTP.sent) == 1
    message = FakeSMTP.sent[0]
    assert message["To"] == "user@gmail.com"
    assert "Google" in message["Subject"]
    plain = message.get_body(preferencelist=("plain",))
    assert plain is not None
    assert "change your password" in str(plain.get_content()).lower()


def test_send_interview_invite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    email_service.send_interview_invite(
        to="marta@x.dev",
        candidate_name="Marta",
        job_title="Backend Engineer",
        company_name="Acme",
        duration_minutes=45,
        booking_url="https://jobs.example.com/interview/tok",
        brand_primary="#3b82f6",
    )

    assert len(FakeSMTP.sent) == 1
    message = FakeSMTP.sent[0]
    assert "Pick a time" in message["Subject"]
    plain = message.get_body(preferencelist=("plain",))
    assert plain is not None
    text = str(plain.get_content())
    assert "45-minute" in text
    assert "https://jobs.example.com/interview/tok" in text


def test_send_interview_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    email_service.send_interview_cancelled(
        to="marta@x.dev",
        candidate_name="Marta",
        job_title="Backend Engineer",
        company_name="Acme",
    )
    assert len(FakeSMTP.sent) == 1
    assert "cancelled" in FakeSMTP.sent[0]["Subject"]
