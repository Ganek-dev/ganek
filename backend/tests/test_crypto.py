import pytest

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret


def test_roundtrip() -> None:
    token = encrypt_secret("1//refresh-token-value")
    assert token != "1//refresh-token-value"
    assert decrypt_secret(token) == "1//refresh-token-value"


def test_garbage_returns_none() -> None:
    assert decrypt_secret("not-a-fernet-token") is None


def test_tampered_returns_none() -> None:
    token = encrypt_secret("secret")
    assert decrypt_secret(token[:-2] + "xx") is None


def test_dedicated_encryption_key_decouples_from_signing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G4: with VETD_ENCRYPTION_KEY set, rotating the signing secret must not
    invalidate stored credentials."""
    monkeypatch.setattr(settings, "encryption_key", "dedicated-key")
    token = encrypt_secret("1//refresh-token-value")
    monkeypatch.setattr(settings, "secret_key", "rotated-signing-secret")
    assert decrypt_secret(token) == "1//refresh-token-value"


def test_rotating_encryption_key_invalidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "encryption_key", "key-one")
    token = encrypt_secret("secret")
    monkeypatch.setattr(settings, "encryption_key", "key-two")
    assert decrypt_secret(token) is None


def test_unset_encryption_key_still_derives_from_secret_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "encryption_key", None)
    token = encrypt_secret("secret")
    assert decrypt_secret(token) == "secret"
    monkeypatch.setattr(settings, "secret_key", "rotated")
    assert decrypt_secret(token) is None
