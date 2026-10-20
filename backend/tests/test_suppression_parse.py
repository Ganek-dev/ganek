"""Pure-logic tests for the suppression helpers: address hashing and the
Mailjet event format (board card A7)."""

from app.services import suppression


def test_hash_normalises_case_and_whitespace() -> None:
    assert suppression.hash_email("  Jane@Example.COM ") == suppression.hash_email(
        "jane@example.com"
    )
    assert len(suppression.hash_email("x@y.z")) == 64
    assert "jane" not in suppression.hash_email("jane@example.com")


def test_parse_mailjet_accepts_one_event_or_a_batch() -> None:
    single = {"event": "spam", "email": "a@example.com", "source": "JMRPP"}
    assert [e.reason for e in suppression.parse_mailjet(single)] == ["complaint"]
    batch = [single, {"event": "unsub", "email": "b@example.com"}]
    assert [e.reason for e in suppression.parse_mailjet(batch)] == ["complaint", "unsubscribe"]


def test_parse_mailjet_hard_bounce_suppresses_soft_bounce_only_annotates() -> None:
    hard = {
        "event": "bounce",
        "email": "a@example.com",
        "hard_bounce": True,
        "error": "user unknown",
        "CustomID": "row-1",
    }
    soft = {"event": "bounce", "email": "a@example.com", "hard_bounce": False, "error": "full"}
    events = suppression.parse_mailjet([hard, soft])
    assert events[0].reason == "bounce"
    assert events[0].detail == "user unknown"
    assert events[0].outbox_id == "row-1"
    assert events[1].reason is None
    assert events[1].detail == "full"


def test_parse_mailjet_blocked_only_for_recipient_side_errors() -> None:
    recipient = {"event": "blocked", "email": "a@example.com", "error_related_to": "recipient"}
    content = {"event": "blocked", "email": "a@example.com", "error_related_to": "content"}
    events = suppression.parse_mailjet([recipient, content])
    assert [e.reason for e in events] == ["blocked", None]


def test_parse_mailjet_ignores_delivery_events_and_junk() -> None:
    payload = [
        {"event": "sent", "email": "a@example.com"},
        {"event": "open", "email": "a@example.com"},
        {"event": "spam"},  # no address
        "not-an-object",
        42,
    ]
    assert suppression.parse_mailjet(payload) == []
    assert suppression.parse_mailjet({"unexpected": True}) == []
