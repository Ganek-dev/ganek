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
