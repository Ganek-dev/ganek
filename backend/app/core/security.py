import re
import uuid
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings

SESSION_COOKIE_NAME = "ganek_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 14  # 14 days

_hasher = PasswordHasher()
_serializer = URLSafeTimedSerializer(settings.secret_key, salt="ganek-session")
_quiz_serializer = URLSafeTimedSerializer(settings.secret_key, salt="ganek-quiz")
QUIZ_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
_status_serializer = URLSafeTimedSerializer(settings.secret_key, salt="ganek-application-status")
STATUS_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days (G0 minimization decision, was 60)
_invite_serializer = URLSafeTimedSerializer(settings.secret_key, salt="ganek-team-invite")
# recruiter-made link to an unpublished job page (spec job posts v2 5.3);
# internal, not a candidate-facing promise
_preview_serializer = URLSafeTimedSerializer(settings.secret_key, salt="ganek-job-preview")
PREVIEW_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
# generous signature window - the invite row's expires_at is the real
# deadline (resend pushes it forward without re-emailing a new token)
INVITE_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


_password_reset_serializer = URLSafeTimedSerializer(
    settings.secret_key, salt="ganek-password-reset"
)
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


_mfa_serializer = URLSafeTimedSerializer(settings.secret_key, salt="ganek-mfa-step")
# the window between a correct password and the authenticator code
MFA_TOKEN_MAX_AGE_SECONDS = 60 * 5


def create_mfa_token(user_id: uuid.UUID, token_version: int) -> str:
    """Proof that the first factor passed moments ago (card A6). Carries
    token_version so a sign-out-everywhere in between retires it."""
    return _mfa_serializer.dumps({"uid": str(user_id), "v": token_version})


def read_mfa_token(token: str) -> tuple[uuid.UUID, int] | None:
    try:
        raw = _mfa_serializer.loads(token, max_age=MFA_TOKEN_MAX_AGE_SECONDS)
        if not isinstance(raw, dict):
            return None
        return uuid.UUID(str(raw["uid"])), int(raw["v"])
    except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
        return None


_email_verify_serializer = URLSafeTimedSerializer(settings.secret_key, salt="ganek-email-verify")
# generous: signup + inbox + coming back later; the 7-day unverified-company
# sweep is the real deadline
EMAIL_VERIFY_MAX_AGE_SECONDS = 60 * 60 * 24 * 3


def create_email_verify_token(user_id: uuid.UUID) -> str:
    return _email_verify_serializer.dumps(str(user_id))


def read_email_verify_token(token: str) -> uuid.UUID | None:
    try:
        raw: str = _email_verify_serializer.loads(token, max_age=EMAIL_VERIFY_MAX_AGE_SECONDS)
        return uuid.UUID(raw)
    except (BadSignature, SignatureExpired, ValueError):
        return None


_google_flow_serializer = URLSafeTimedSerializer(settings.secret_key, salt="ganek-google-oauth")
# state/PKCE verifier/nonce only need to survive the redirect to Google and back
GOOGLE_FLOW_MAX_AGE_SECONDS = 60 * 10
GOOGLE_FLOW_COOKIE_NAME = "ganek_google_flow"
_google_signup_serializer = URLSafeTimedSerializer(settings.secret_key, salt="ganek-google-signup")
# window to type a company name on /setup after Google authenticated the user
GOOGLE_SIGNUP_MAX_AGE_SECONDS = 60 * 15
# the signup token carries sub+email (PII) - it rides an httponly cookie,
# never a URL (browser history / proxy logs), per GDPR G4
GOOGLE_SIGNUP_COOKIE_NAME = "ganek_google_signup"
_oidc_flow_serializer = URLSafeTimedSerializer(settings.secret_key, salt="ganek-oidc")
# same lifetime as Google's: state/PKCE/nonce only cross one IdP round trip
OIDC_FLOW_MAX_AGE_SECONDS = 60 * 10
OIDC_FLOW_COOKIE_NAME = "ganek_oidc_flow"


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


def create_preview_token(job_id: uuid.UUID) -> str:
    return _preview_serializer.dumps(str(job_id))


def read_preview_token(token: str) -> uuid.UUID | None:
    try:
        raw: str = _preview_serializer.loads(token, max_age=PREVIEW_TOKEN_MAX_AGE_SECONDS)
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


_interview_serializer = URLSafeTimedSerializer(settings.secret_key, salt="ganek-interview")
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


# Same rule as the frontend's safeNext (lib/home.ts): only a team-invite page,
# so a sign-in link can never send anyone off-site.
_SAFE_NEXT_RE = re.compile(r"/invite/[A-Za-z0-9._~-]+")


def safe_next_path(value: str | None) -> str | None:
    """``value`` when it is a same-site team-invite path, else None."""
    if value and _SAFE_NEXT_RE.fullmatch(value):
        return value
    return None


def create_google_flow_token(
    state: str,
    code_verifier: str,
    nonce: str,
    invite: str | None = None,
    next_path: str | None = None,
) -> str:
    payload: dict[str, str] = {"s": state, "cv": code_verifier, "n": nonce}
    if invite is not None:
        payload["i"] = invite  # opaque team-invite token riding through the oauth flow
    if next_path is not None:
        payload["x"] = next_path  # where to land after sign-in (safe_next_path checked)
    return _google_flow_serializer.dumps(payload)


def read_google_flow_token(
    token: str,
) -> tuple[str, str, str, str | None, str | None] | None:
    try:
        raw = _google_flow_serializer.loads(token, max_age=GOOGLE_FLOW_MAX_AGE_SECONDS)
        invite = raw.get("i")
        next_path = raw.get("x")
        return (
            str(raw["s"]),
            str(raw["cv"]),
            str(raw["n"]),
            str(invite) if invite is not None else None,
            safe_next_path(str(next_path)) if next_path is not None else None,
        )
    except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
        return None


def create_oidc_flow_token(
    state: str, code_verifier: str, nonce: str, next_path: str | None = None
) -> str:
    payload: dict[str, str] = {"s": state, "cv": code_verifier, "n": nonce}
    if next_path is not None:
        payload["x"] = next_path  # where to land after sign-in (safe_next_path checked)
    return _oidc_flow_serializer.dumps(payload)


def read_oidc_flow_token(token: str) -> tuple[str, str, str, str | None] | None:
    """(state, code_verifier, nonce, next_path); next is re-checked on read."""
    try:
        raw = _oidc_flow_serializer.loads(token, max_age=OIDC_FLOW_MAX_AGE_SECONDS)
        next_path = raw.get("x")
        return (
            str(raw["s"]),
            str(raw["cv"]),
            str(raw["n"]),
            safe_next_path(str(next_path)) if next_path is not None else None,
        )
    except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError, AttributeError):
        return None


def create_google_signup_token(sub: str, email: str) -> str:
    return _google_signup_serializer.dumps({"sub": sub, "email": email})


def read_google_signup_token(token: str) -> tuple[str, str] | None:
    try:
        raw = _google_signup_serializer.loads(token, max_age=GOOGLE_SIGNUP_MAX_AGE_SECONDS)
        return str(raw["sub"]), str(raw["email"])
    except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
        return None


_impersonation_serializer = URLSafeTimedSerializer(settings.secret_key, salt="ganek-impersonation")
# operator plane (card "Operator plane"): an impersonation lasts one hour,
# then the operator's own session is what the cookie jar falls back to
IMPERSONATION_COOKIE_NAME = "ganek_impersonation"
IMPERSONATION_MAX_AGE_SECONDS = 60 * 60


class ImpersonationClaim:
    """Who is looking (the operator, by session) as whom (the tenant user),
    and when the signature was made (the one-hour clock starts there)."""

    def __init__(
        self,
        operator_id: uuid.UUID,
        operator_version: int,
        user_id: uuid.UUID,
        user_version: int,
        issued_at: datetime,
    ) -> None:
        self.operator_id = operator_id
        self.operator_version = operator_version
        self.user_id = user_id
        self.user_version = user_version
        self.issued_at = issued_at

    @property
    def expires_at(self) -> datetime:
        return self.issued_at + timedelta(seconds=IMPERSONATION_MAX_AGE_SECONDS)


def create_impersonation_token(
    operator_id: uuid.UUID, operator_version: int, user_id: uuid.UUID, user_version: int
) -> str:
    """Both token versions ride along: the operator signing out everywhere,
    or the tenant user changing their password, ends the impersonation."""
    return _impersonation_serializer.dumps(
        {"op": str(operator_id), "ov": operator_version, "uid": str(user_id), "v": user_version}
    )


def read_impersonation_token(token: str) -> ImpersonationClaim | None:
    try:
        raw, issued = _impersonation_serializer.loads(
            token, max_age=IMPERSONATION_MAX_AGE_SECONDS, return_timestamp=True
        )
        if not isinstance(raw, dict):
            return None
        return ImpersonationClaim(
            uuid.UUID(str(raw["op"])),
            int(raw["ov"]),
            uuid.UUID(str(raw["uid"])),
            int(raw["v"]),
            issued if issued.tzinfo else issued.replace(tzinfo=UTC),
        )
    except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
        return None
