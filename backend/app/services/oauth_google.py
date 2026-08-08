"""Google sign-in: server-side OIDC authorization code flow (PKCE + state + nonce).

Identity is keyed on the ID token's stable `sub` claim. Email is only a
one-time linking heuristic, honoured solely when Google is authoritative
for the address (@gmail.com, or Workspace-verified via `hd`).

The ID token arrives over our direct TLS channel to Google's token
endpoint, so its signature is deliberately not re-verified (OIDC Core
3.1.3.7 rule 6); iss/aud/exp/nonce are validated instead. If a
browser-delivered token path (One Tap) is ever added, that path MUST do
full JWKS verification.
"""

import base64
import enum
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import User

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
_VALID_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}


class GoogleOAuthError(Exception):
    """Any reason the Google handshake cannot be trusted or completed."""


class Resolution(enum.StrEnum):
    LOGIN = "login"
    LINKED = "linked"
    SIGNUP = "signup"
    USE_PASSWORD = "use_password"  # noqa: S105 - a routing verdict, not a credential
    INACTIVE = "inactive"


def configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def redirect_uri() -> str:
    if settings.google_redirect_url:
        return settings.google_redirect_url
    return f"{settings.public_base_url}/api/v1/auth/google/callback"


CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


def build_authorization_request(*, calendar: bool = False) -> tuple[str, str, str, str]:
    """Return (authorization_url, state, code_verifier, nonce).

    calendar=True is the incremental-auth consent for Calendar access:
    offline access forces a refresh token (prompt=consent re-issues one on
    reconnect), and include_granted_scopes folds in the sign-in grant.
    """
    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    nonce = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    if calendar:
        params["scope"] = f"openid email {CALENDAR_SCOPE}"
        params["access_type"] = "offline"
        params["prompt"] = "consent"
        params["include_granted_scopes"] = "true"
    return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}", state, code_verifier, nonce


def _decode_claims(id_token: str) -> dict[str, object]:
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        raise GoogleOAuthError("malformed id_token") from None
    if not isinstance(claims, dict):
        raise GoogleOAuthError("malformed id_token payload")
    return claims


async def exchange_code(code: str, code_verifier: str) -> dict[str, object]:
    """Trade the authorization code for the ID token's claims."""
    claims, _ = await exchange_code_full(code, code_verifier)
    return claims


async def exchange_code_full(code: str, code_verifier: str) -> tuple[dict[str, object], str | None]:
    """Like exchange_code, but also returns the refresh token when Google
    issues one (offline/calendar consents only)."""
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": redirect_uri(),
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
            )
        except httpx.HTTPError as exc:
            raise GoogleOAuthError("token endpoint unreachable") from exc
    if resp.status_code != 200:
        raise GoogleOAuthError(f"token exchange failed with {resp.status_code}")
    data = resp.json()
    id_token = data.get("id_token")
    if not isinstance(id_token, str):
        raise GoogleOAuthError("no id_token in token response")
    refresh_token = data.get("refresh_token")
    return _decode_claims(id_token), (refresh_token if isinstance(refresh_token, str) else None)


def validate_claims(claims: dict[str, object], *, nonce: str) -> None:
    if claims.get("iss") not in _VALID_ISSUERS:
        raise GoogleOAuthError("unexpected issuer")
    if claims.get("aud") != settings.google_client_id:
        raise GoogleOAuthError("unexpected audience")
    exp = claims.get("exp")
    if not isinstance(exp, int | float) or exp < time.time():
        raise GoogleOAuthError("id_token expired")
    if claims.get("nonce") != nonce:
        raise GoogleOAuthError("nonce mismatch")
    if not isinstance(claims.get("sub"), str) or not isinstance(claims.get("email"), str):
        raise GoogleOAuthError("id_token missing sub/email")


def email_authoritative(claims: dict[str, object]) -> bool:
    """Whether Google vouches for ownership of this address.

    Google's own rule: gmail.com, or email_verified with a Workspace hd
    claim. A merely "verified" third-party address is NOT authoritative.
    """
    email = str(claims.get("email", "")).casefold()
    if email.endswith("@gmail.com"):
        return True
    return bool(claims.get("email_verified")) and bool(claims.get("hd"))


async def resolve_identity(
    db: AsyncSession, claims: dict[str, object]
) -> tuple[Resolution, User | None]:
    """Map validated claims onto a local account. Commits on LOGIN/LINKED."""
    sub = str(claims["sub"])
    email = str(claims["email"])
    user = (
        await db.execute(
            select(User).options(selectinload(User.company)).where(User.google_sub == sub)
        )
    ).scalar_one_or_none()
    if user is not None:
        if not user.is_active:
            return Resolution.INACTIVE, None
        user.last_login_at = datetime.now(UTC)
        await db.commit()
        return Resolution.LOGIN, user

    by_email = (
        await db.execute(
            select(User).options(selectinload(User.company)).where(User.email == email)
        )
    ).scalar_one_or_none()
    if by_email is None:
        return Resolution.SIGNUP, None
    if not email_authoritative(claims):
        return Resolution.USE_PASSWORD, None
    if not by_email.is_active:
        return Resolution.INACTIVE, None
    by_email.google_sub = sub
    by_email.last_login_at = datetime.now(UTC)
    await db.commit()
    return Resolution.LINKED, by_email
