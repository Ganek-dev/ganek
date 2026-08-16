"""Symmetric encryption for stored third-party secrets (Google refresh tokens).

Fernet with a key derived from VETD_ENCRYPTION_KEY when set, else from
VETD_SECRET_KEY. Without the dedicated key, rotating the app secret
invalidates stored credentials (users just reconnect); with it, the
signing secret rotates freely and only rotating the encryption key
itself forces reconnects.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    material = settings.encryption_key or settings.secret_key
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None
