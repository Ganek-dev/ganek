"""Generic OpenID Connect sign-in (Keycloak, Authentik, Okta, Entra ID...):
server-side authorization code flow with PKCE + state + nonce, configured
per instance (GANEK_OIDC_*), endpoints taken from the issuer's discovery
document.

Identity is keyed on (issuer, sub). Email is only a one-time linking
heuristic, honoured when the IdP marks the address verified AND its domain
is one the operator listed in GANEK_OIDC_EMAIL_DOMAINS: a generic IdP may
allow self-registration with any address, and trusting email_verified
alone is the classic OIDC account-takeover hole.

An unknown identity gets no account from a plain sign-in (no signup); a
flow started from a team invite creates the invited account instead (see
api/oidc_auth.py).

As with Google, the ID token arrives over our direct TLS channel to the
token endpoint, so its signature is not re-verified (OIDC Core 3.1.3.7
rule 6); iss/aud/azp/exp/nonce are validated instead.
"""

import base64
import enum
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime
from urllib.parse import urlencode, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import urls
from app.core.config import settings
from app.models import User

_DISCOVERY_TTL_SECONDS = 60 * 60
_discovery_cache: dict[str, tuple[float, "ProviderMetadata"]] = {}


class OidcError(Exception):
    """Any reason the OIDC handshake cannot be trusted or completed."""


class Resolution(enum.StrEnum):
    LOGIN = "login"
    LINKED = "linked"
    NO_ACCOUNT = "no_account"
    USE_PASSWORD = "use_password"  # noqa: S105 - a routing verdict, not a credential
    INACTIVE = "inactive"


class ProviderMetadata:
    def __init__(self, issuer: str, authorization_endpoint: str, token_endpoint: str) -> None:
        self.issuer = issuer
        self.authorization_endpoint = authorization_endpoint
        self.token_endpoint = token_endpoint


def configured() -> bool:
    return bool(settings.oidc_issuer and settings.oidc_client_id and settings.oidc_client_secret)


def issuer() -> str:
    return (settings.oidc_issuer or "").rstrip("/")


def email_domains() -> set[str]:
    return {
        d.strip().casefold().lstrip("@")
        for d in settings.oidc_email_domains.split(",")
        if d.strip()
    }


def _https_or_local(url: object) -> bool:
    """Endpoints must be https; plain http only for a local test IdP."""
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.hostname:
        return True
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}


def parse_discovery(doc: object) -> ProviderMetadata:
    """Validate a discovery document against the configured issuer."""
    if not isinstance(doc, dict):
        raise OidcError("discovery document is not an object")
    if str(doc.get("issuer", "")).rstrip("/") != issuer():
        raise OidcError("discovery issuer does not match the configured issuer")
    auth = doc.get("authorization_endpoint")
    token = doc.get("token_endpoint")
    if not _https_or_local(auth) or not _https_or_local(token):
        raise OidcError("discovery endpoints missing or not https")
    assert isinstance(auth, str) and isinstance(token, str)
    return ProviderMetadata(str(doc["issuer"]), auth, token)


async def discover() -> ProviderMetadata:
    """The issuer's endpoints, cached for an hour per issuer."""
    key = issuer()
    cached = _discovery_cache.get(key)
    if cached is not None and cached[0] > time.monotonic():
        return cached[1]
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(f"{key}/.well-known/openid-configuration")
        except httpx.HTTPError as exc:
            raise OidcError("discovery endpoint unreachable") from exc
    if resp.status_code != 200:
        raise OidcError(f"discovery failed with {resp.status_code}")
    try:
        doc = resp.json()
    except ValueError:
        raise OidcError("discovery document is not JSON") from None
    meta = parse_discovery(doc)
    _discovery_cache[key] = (time.monotonic() + _DISCOVERY_TTL_SECONDS, meta)
    return meta


def build_authorization_request(meta: ProviderMetadata) -> tuple[str, str, str, str]:
    """Return (authorization_url, state, code_verifier, nonce). Only
    ``openid email`` is requested (GDPR minimization, as for Google)."""
    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    nonce = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    params = {
        "client_id": settings.oidc_client_id,
        "redirect_uri": urls.oidc_redirect_uri(),
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    sep = "&" if "?" in meta.authorization_endpoint else "?"
    return f"{meta.authorization_endpoint}{sep}{urlencode(params)}", state, code_verifier, nonce


def _decode_claims(id_token: str) -> dict[str, object]:
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        raise OidcError("malformed id_token") from None
    if not isinstance(claims, dict):
        raise OidcError("malformed id_token payload")
    return claims


async def exchange_code(meta: ProviderMetadata, code: str, code_verifier: str) -> dict[str, object]:
    """Trade the authorization code for the ID token's claims."""
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(
                meta.token_endpoint,
                data={
                    "code": code,
                    "client_id": settings.oidc_client_id,
                    "client_secret": settings.oidc_client_secret,
                    "redirect_uri": urls.oidc_redirect_uri(),
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
            )
        except httpx.HTTPError as exc:
            raise OidcError("token endpoint unreachable") from exc
    if resp.status_code != 200:
        raise OidcError(f"token exchange failed with {resp.status_code}")
    try:
        data = resp.json()
    except ValueError:
        raise OidcError("token response is not JSON") from None
    id_token = data.get("id_token") if isinstance(data, dict) else None
    if not isinstance(id_token, str):
        raise OidcError("no id_token in token response")
    return _decode_claims(id_token)


def validate_claims(claims: dict[str, object], *, nonce: str) -> None:
    if str(claims.get("iss", "")).rstrip("/") != issuer():
        raise OidcError("unexpected issuer")
    aud = claims.get("aud")
    client_id = settings.oidc_client_id
    if isinstance(aud, list):
        if client_id not in aud:
            raise OidcError("unexpected audience")
        # OIDC Core 3.1.3.7 rules 4-5: several audiences need azp = us
        if len(aud) > 1 and claims.get("azp") != client_id:
            raise OidcError("unexpected authorized party")
    elif aud != client_id:
        raise OidcError("unexpected audience")
    if "azp" in claims and claims.get("azp") != client_id:
        raise OidcError("unexpected authorized party")
    exp = claims.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, int | float) or exp < time.time():
        raise OidcError("id_token expired")
    if not isinstance(claims.get("nonce"), str) or not secrets.compare_digest(
        str(claims["nonce"]), nonce
    ):
        raise OidcError("nonce mismatch")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise OidcError("id_token missing sub")


def email_linkable(claims: dict[str, object]) -> bool:
    """Whether a first sign-in may link to the account with this email:
    the IdP says verified (a real boolean true, or the string "true" some
    IdPs send) and the domain is one the operator trusts this IdP for."""
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email:
        return False
    verified = claims.get("email_verified")
    if verified is not True and verified != "true":
        return False
    return email.rsplit("@", 1)[1].casefold() in email_domains()


async def resolve_identity(
    db: AsyncSession, claims: dict[str, object]
) -> tuple[Resolution, User | None]:
    """Map validated claims onto a local account. Commits on LOGIN/LINKED."""
    iss = issuer()
    sub = str(claims["sub"])
    user = (
        await db.execute(
            select(User)
            .options(selectinload(User.company))
            .where(User.oidc_issuer == iss, User.oidc_sub == sub)
        )
    ).scalar_one_or_none()
    if user is not None:
        if not user.is_active:
            return Resolution.INACTIVE, None
        user.last_login_at = datetime.now(UTC)
        await db.commit()
        return Resolution.LOGIN, user

    email = claims.get("email")
    if not isinstance(email, str):
        return Resolution.NO_ACCOUNT, None
    by_email = (
        await db.execute(
            select(User).options(selectinload(User.company)).where(User.email == email)
        )
    ).scalar_one_or_none()
    if by_email is None:
        return Resolution.NO_ACCOUNT, None
    if not email_linkable(claims):
        return Resolution.USE_PASSWORD, None
    if not by_email.is_active:
        return Resolution.INACTIVE, None
    if by_email.oidc_sub is not None:
        # already linked to another subject at this (or an older) issuer:
        # never silently re-point an identity
        return Resolution.USE_PASSWORD, None
    by_email.oidc_issuer = iss
    by_email.oidc_sub = sub
    by_email.last_login_at = datetime.now(UTC)
    await db.commit()
    return Resolution.LINKED, by_email
