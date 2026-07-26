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
_status_serializer = URLSafeTimedSerializer(settings.secret_key, salt="vetd-application-status")
STATUS_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 60  # candidates check back late; 60 days
_invite_serializer = URLSafeTimedSerializer(settings.secret_key, salt="vetd-team-invite")
# generous signature window — the invite row's expires_at is the real
# deadline (resend pushes it forward without re-emailing a new token)
INVITE_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_session_token(user_id: uuid.UUID, token_version: int) -> str:
    return _serializer.dumps({"uid": str(user_id), "v": token_version})


def read_session_token(token: str) -> tuple[uuid.UUID, int] | None:
    """Return (user_id, token_version) or None if unusable."""
    try:
        raw = _serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
        if not isinstance(raw, dict):
            return None
        return uuid.UUID(str(raw["uid"])), int(raw["v"])
    except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
        return None


def create_quiz_token(attempt_id: uuid.UUID) -> str:
    return _quiz_serializer.dumps(str(attempt_id))


def read_quiz_token(token: str) -> uuid.UUID | None:
    try:
        raw: str = _quiz_serializer.loads(token, max_age=QUIZ_TOKEN_MAX_AGE_SECONDS)
        return uuid.UUID(raw)
    except (BadSignature, SignatureExpired, ValueError):
        return None


def create_status_token(application_id: uuid.UUID) -> str:
    return _status_serializer.dumps(str(application_id))


def read_status_token(token: str) -> uuid.UUID | None:
    try:
        raw: str = _status_serializer.loads(token, max_age=STATUS_TOKEN_MAX_AGE_SECONDS)
        return uuid.UUID(raw)
    except (BadSignature, SignatureExpired, ValueError):
        return None


def create_invite_token(invite_id: uuid.UUID) -> str:
    return _invite_serializer.dumps(str(invite_id))


def read_invite_token(token: str) -> uuid.UUID | None:
    try:
        raw: str = _invite_serializer.loads(token, max_age=INVITE_TOKEN_MAX_AGE_SECONDS)
        return uuid.UUID(raw)
    except (BadSignature, SignatureExpired, ValueError):
        return None
