import uuid

from app.core.security import (
    create_google_flow_token,
    create_google_signup_token,
    create_interview_token,
    create_session_token,
    hash_password,
    read_google_flow_token,
    read_google_signup_token,
    read_interview_token,
    read_session_token,
    verify_password,
)
from app.services.slugs import slugify


def test_password_hash_roundtrip() -> None:
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong password", h)


def test_verify_rejects_garbage_hash() -> None:
    assert not verify_password("anything", "not-a-valid-argon2-hash")


def test_session_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token = create_session_token(user_id, 0)
    assert read_session_token(token) == (user_id, 0)


def test_session_token_rejects_tampering() -> None:
    token = create_session_token(uuid.uuid4(), 2)
    # flip the FIRST signature char: every bit of it lands in the decoded
    # signature. The last char is unusable for this — base64 discards its
    # low bits, so tokens ending in A–D survive an A↔B flip (1-in-16 flake)
    head, _, sig = token.rpartition(".")
    tampered = f"{head}.{'A' if sig[0] != 'A' else 'B'}{sig[1:]}"
    assert read_session_token(tampered) is None
    assert read_session_token("completely-bogus") is None


def test_slugify() -> None:
    assert slugify("Acme Inc.") == "acme-inc"
    assert slugify("  Über  Cool GmbH!  ") == "ber-cool-gmbh"
    assert slugify("!!!") == "item"
    assert len(slugify("x" * 300)) <= 64


def test_google_flow_token_roundtrip() -> None:
    token = create_google_flow_token("state1", "verifier1", "nonce1")
    assert read_google_flow_token(token) == ("state1", "verifier1", "nonce1", None, None)


def test_google_flow_token_carries_invite() -> None:
    token = create_google_flow_token("state1", "verifier1", "nonce1", invite="inv-token")
    assert read_google_flow_token(token) == ("state1", "verifier1", "nonce1", "inv-token", None)


def test_google_flow_token_carries_calendar_user() -> None:
    token = create_google_flow_token("state1", "verifier1", "nonce1", calendar_user_id="uid-1")
    assert read_google_flow_token(token) == ("state1", "verifier1", "nonce1", None, "uid-1")


def test_google_flow_token_garbage() -> None:
    assert read_google_flow_token("garbage") is None


def test_google_signup_token_roundtrip() -> None:
    token = create_google_signup_token("sub-123", "person@gmail.com")
    assert read_google_signup_token(token) == ("sub-123", "person@gmail.com")


def test_google_signup_token_garbage() -> None:
    assert read_google_signup_token("") is None


def test_interview_token_roundtrip() -> None:
    interview_id = uuid.uuid4()
    token = create_interview_token(interview_id)
    assert read_interview_token(token) == interview_id


def test_interview_token_garbage() -> None:
    assert read_interview_token("garbage") is None
