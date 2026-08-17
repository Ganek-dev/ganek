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
STATUS_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days (G0 minimization decision, was 60)
_invite_serializer = URLSafeTimedSerializer(settings.secret_key, salt="vetd-team-invite")
# generous signature window — the invite row's expires_at is the real
# deadline (resend pushes it forward without re-emailing a new token)
INVITE_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


_password_reset_serializer = URLSafeTimedSerializer(settings.secret_key, salt="vetd-password-reset")
# short-lived: possession of the inbox is the whole proof here
PASSWORD_RESET_MAX_AGE_SECONDS = 60 * 45


def create_password_reset_token(user_id: uuid.UUID, token_version: int) -> str:
    """Carries the CURRENT token_version so a completed reset (or any other
    password change) retires every outstanding reset link at once."""
    return _password_reset_serializer.dumps({"uid": str(user_id), "v": token_version})


def read_password_reset_token(token: str) -> tuple[uuid.UUID, int] | None:
    """Return (user_id, token_version-at-issue) or None if unusable."""
    try:
        raw = _password_reset_serializer.loads(token, max_age=PASSWORD_RESET_MAX_AGE_SECONDS)
        if not isinstance(raw, dict):
            return None
        return uuid.UUID(str(raw["uid"])), int(raw["v"])
    except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
        return None


_google_flow_serializer = URLSafeTimedSerializer(settings.secret_key, salt="vetd-google-oauth")
# state/PKCE verifier/nonce only need to survive the redirect to Google and back
GOOGLE_FLOW_MAX_AGE_SECONDS = 60 * 10
GOOGLE_FLOW_COOKIE_NAME = "vetd_google_flow"
_google_signup_serializer = URLSafeTimedSerializer(settings.secret_key, salt="vetd-google-signup")
# window to type a company name on /setup after Google authenticated the user
GOOGLE_SIGNUP_MAX_AGE_SECONDS = 60 * 15
# the signup token carries sub+email (PII) — it rides an httponly cookie,
# never a URL (browser history / proxy logs), per GDPR G4
GOOGLE_SIGNUP_COOKIE_NAME = "vetd_google_signup"


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


_interview_serializer = URLSafeTimedSerializer(settings.secret_key, salt="vetd-interview")
# candidates may sit on the booking link a while; interview rows gate real access
INTERVIEW_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 60


def create_interview_token(interview_id: uuid.UUID) -> str:
    return _interview_serializer.dumps(str(interview_id))


def read_interview_token(token: str) -> uuid.UUID | None:
    try:
        raw: str = _interview_serializer.loads(token, max_age=INTERVIEW_TOKEN_MAX_AGE_SECONDS)
        return uuid.UUID(raw)
    except (BadSignature, SignatureExpired, ValueError):
        return None


def create_google_flow_token(
    state: str,
    code_verifier: str,
    nonce: str,
    invite: str | None = None,
    calendar_user_id: str | None = None,
) -> str:
    payload: dict[str, str] = {"s": state, "cv": code_verifier, "n": nonce}
    if invite is not None:
        payload["i"] = invite  # opaque team-invite token riding through the oauth flow
    if calendar_user_id is not None:
        payload["u"] = calendar_user_id  # logged-in user connecting their calendar
    return _google_flow_serializer.dumps(payload)


def read_google_flow_token(token: str) -> tuple[str, str, str, str | None, str | None] | None:
    try:
        raw = _google_flow_serializer.loads(token, max_age=GOOGLE_FLOW_MAX_AGE_SECONDS)
        invite = raw.get("i")
        calendar_user_id = raw.get("u")
        return (
            str(raw["s"]),
            str(raw["cv"]),
            str(raw["n"]),
            str(invite) if invite is not None else None,
            str(calendar_user_id) if calendar_user_id is not None else None,
        )
    except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
        return None


def create_google_signup_token(sub: str, email: str) -> str:
    return _google_signup_serializer.dumps({"sub": sub, "email": email})


def read_google_signup_token(token: str) -> tuple[str, str] | None:
    try:
        raw = _google_signup_serializer.loads(token, max_age=GOOGLE_SIGNUP_MAX_AGE_SECONDS)
        return str(raw["sub"]), str(raw["email"])
    except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
        return None
