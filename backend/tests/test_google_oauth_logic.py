"""Pure-logic tests for the google oauth service (no DB, no network)."""

import base64
import hashlib
import json
import time

import pytest

from app.core.config import settings
from app.services import oauth_google
from app.services.oauth_google import GoogleOAuthError


@pytest.fixture
def google_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")


def _claims(**overrides: object) -> dict[str, object]:
    claims: dict[str, object] = {
        "iss": "https://accounts.google.com",
        "aud": "test-client-id",
        "exp": time.time() + 600,
        "nonce": "nonce-1",
        "sub": "sub-1",
        "email": "person@gmail.com",
        "email_verified": True,
    }
    claims.update(overrides)
    return claims


@pytest.mark.usefixtures("google_configured")
def test_authorization_url_shape() -> None:
    url, state, verifier, nonce = oauth_google.build_authorization_request()
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "code_challenge_method=S256" in url
    assert "prompt=select_account" in url
    assert f"state={state}" in url
    # challenge is derived from the verifier; the verifier itself never leaves us
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    assert challenge in url
    assert verifier not in url
    assert f"nonce={nonce}" in url
    assert "access_type" not in url  # sign-in only: no refresh tokens


@pytest.mark.usefixtures("google_configured")
def test_validate_claims_accepts_good() -> None:
    oauth_google.validate_claims(_claims(), nonce="nonce-1")


@pytest.mark.usefixtures("google_configured")
@pytest.mark.parametrize(
    "bad",
    [
        {"iss": "https://evil.example"},
        {"aud": "other-client"},
        {"exp": time.time() - 10},
        {"nonce": "other"},
        {"sub": None},
        {"email": None},
    ],
)
def test_validate_claims_rejects(bad: dict[str, object]) -> None:
    with pytest.raises(GoogleOAuthError):
        oauth_google.validate_claims(_claims(**bad), nonce="nonce-1")


def test_email_authoritative_gmail() -> None:
    assert oauth_google.email_authoritative(_claims(email="a@GMAIL.com", email_verified=False))


def test_email_authoritative_workspace() -> None:
    assert oauth_google.email_authoritative(_claims(email="a@corp.dev", hd="corp.dev"))


def test_email_not_authoritative_plain_verified() -> None:
    # verified non-gmail without hd: Google explicitly says it is NOT authoritative
    assert not oauth_google.email_authoritative(_claims(email="a@corp.dev"))


def test_decode_claims_roundtrip() -> None:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": "x"}).encode()).rstrip(b"=").decode()
    assert oauth_google._decode_claims(f"h.{payload}.sig") == {"sub": "x"}


def test_decode_claims_garbage() -> None:
    with pytest.raises(GoogleOAuthError):
        oauth_google._decode_claims("not-a-jwt")
