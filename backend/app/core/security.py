import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings

SESSION_COOKIE_NAME = "vetd_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 14  # 14 days

_hasher = PasswordHasher()
_serializer = URLSafeTimedSerializer(settings.secret_key, salt="vetd-session")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_session_token(user_id: uuid.UUID) -> str:
    return _serializer.dumps(str(user_id))


def read_session_token(token: str) -> uuid.UUID | None:
    try:
        raw: str = _serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
        return uuid.UUID(raw)
    except (BadSignature, SignatureExpired, ValueError):
        return None
