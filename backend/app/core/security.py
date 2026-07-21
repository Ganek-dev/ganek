import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings

SESSION_COOKIE_NAME = "vetd_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 14  # 14 days

_hasher = PasswordHasher()
_serializer = URLSafeTimedSerializer(settings.secret_key, salt="vetd-session")
_quiz_serializer = URLSafeTimedSerializer(settings.secret_key, salt="vetd-quiz")
QUIZ_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


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


def create_quiz_token(attempt_id: uuid.UUID) -> str:
    return _quiz_serializer.dumps(str(attempt_id))


def read_quiz_token(token: str) -> uuid.UUID | None:
    try:
        raw: str = _quiz_serializer.loads(token, max_age=QUIZ_TOKEN_MAX_AGE_SECONDS)
        return uuid.UUID(raw)
    except (BadSignature, SignatureExpired, ValueError):
        return None
