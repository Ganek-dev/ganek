"""Generic OIDC sign-in endpoints (GANEK_OIDC_*). Browser redirects are
relative paths, as for Google: the browser reaches us through the Next
proxy. See services/oauth_oidc.py for the trust model.

A flow started from a team invite (``start?invite=<token>``) creates the
invited account from the IdP identity instead of signing in, as Google's
invite-accept does."""

import logging
import secrets
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from app.api.auth import _set_session_cookie
from app.api.deps import DbSession
from app.core.config import settings
from app.core.ratelimit import rate_limit
from app.core.security import (
    OIDC_FLOW_COOKIE_NAME,
    OIDC_FLOW_MAX_AGE_SECONDS,
    create_mfa_token,
    create_oidc_flow_token,
    read_oidc_flow_token,
    safe_next_path,
)
from app.services import demo_mode, oauth_oidc
from app.services import invites as invites_service
from app.services import mfa as mfa_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/oidc", tags=["auth"])

_FLOW_COOKIE_PATH = "/api/v1/auth/oidc"


def _require_configured() -> None:
    if not oauth_oidc.configured():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Single sign-on is not configured on this instance",
        )


def _redirect(path: str) -> RedirectResponse:
    response = RedirectResponse(path, status_code=status.HTTP_302_FOUND)
    response.delete_cookie(OIDC_FLOW_COOKIE_NAME, path=_FLOW_COOKIE_PATH)
    return response


@router.get(
    "/start",
    dependencies=[
        rate_limit("auth", lambda: settings.rate_limit_auth_per_minute),
        demo_mode.locked,
    ],
)
async def oidc_start(
    invite: str | None = None,
    next_path: str | None = Query(default=None, alias="next"),
) -> RedirectResponse:
    """Redirect to the IdP. ``next`` follows the Google rule: only a
    same-site /invite/<token> path survives, anything else is dropped.
    ``invite`` (an opaque invite token) makes the callback accept that
    invite for a new account rather than sign in."""
    _require_configured()
    try:
        meta = await oauth_oidc.discover()
    except oauth_oidc.OidcError:
        logger.warning("oidc discovery failed", exc_info=True)
        return _redirect("/login?error=oidc-failed")
    url, state, verifier, nonce = oauth_oidc.build_authorization_request(meta)
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        OIDC_FLOW_COOKIE_NAME,
        create_oidc_flow_token(
            state, verifier, nonce, next_path=safe_next_path(next_path), invite=invite
        ),
        max_age=OIDC_FLOW_MAX_AGE_SECONDS,
        httponly=True,
        # Lax, not Strict: the IdP's redirect back is a cross-site navigation
        samesite="lax",
        secure=settings.cookie_secure,
        path=_FLOW_COOKIE_PATH,
    )
    return response


def oidc_email_matches(claims: dict[str, object], email: str) -> bool:
    """The IdP vouches for the invited address: same email (case-insensitive)
    and marked verified (boolean true, or the string "true" some IdPs send).
    The invite token is the secret here, so the operator's email-domain list,
    which guards linking to existing accounts, does not apply."""
    claimed = claims.get("email")
    verified = claims.get("email_verified")
    return (
        isinstance(claimed, str)
        and claimed.casefold() == email.casefold()
        and (verified is True or verified == "true")
    )


async def _accept_invite_via_oidc(
    db: DbSession, *, invite_token: str, claims: dict[str, object]
) -> RedirectResponse:
    """Invite-accept branch of the callback: the invite decides the company
    and role; the IdP only vouches for the invited email."""
    back = f"/invite/{quote(invite_token, safe='')}"
    invite = await invites_service.invite_by_token(db, invite_token)
    if invite is None:
        return _redirect(f"{back}?error=oidc-invalid")
    if not oidc_email_matches(claims, invite.email):
        return _redirect(f"{back}?error=oidc-email-mismatch")
    try:
        user = await invites_service.accept_invite_oidc(
            db, invite, oidc_issuer=oauth_oidc.issuer(), oidc_sub=str(claims["sub"])
        )
    except invites_service.InviteExpiredError:
        return _redirect(back)  # the page renders its own expired state
    except invites_service.EmailTakenError:
        return _redirect(f"{back}?error=email-taken")
    except invites_service.IdentityLinkedError:
        return _redirect(f"{back}?error=oidc-linked")
    response = _redirect("/admin")
    _set_session_cookie(response, user)
    return response


@router.get("/callback")
async def oidc_callback(request: Request, db: DbSession) -> RedirectResponse:
    _require_configured()
    if request.query_params.get("error") == "access_denied":
        return _redirect("/login")  # cancelled at the IdP: no error banner
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    flow = read_oidc_flow_token(request.cookies.get(OIDC_FLOW_COOKIE_NAME, ""))
    if not code or not state or flow is None or not secrets.compare_digest(state, flow[0]):
        return _redirect("/login?error=oidc-failed")
    try:
        meta = await oauth_oidc.discover()
        claims = await oauth_oidc.exchange_code(meta, code, flow[1])
        oauth_oidc.validate_claims(claims, nonce=flow[2])
    except oauth_oidc.OidcError:
        logger.warning("oidc handshake failed", exc_info=True)
        return _redirect("/login?error=oidc-failed")

    if flow[4] is not None:
        return await _accept_invite_via_oidc(db, invite_token=flow[4], claims=claims)

    next_path = flow[3]
    next_query = f"&next={quote(next_path, safe='')}" if next_path else ""

    resolution, user = await oauth_oidc.resolve_identity(db, claims)
    if resolution is oauth_oidc.Resolution.NO_ACCOUNT:
        return _redirect(f"/login?error=oidc-no-account{next_query}")
    if resolution is oauth_oidc.Resolution.USE_PASSWORD:
        return _redirect(f"/login?error=use-password{next_query}")
    if resolution is oauth_oidc.Resolution.INACTIVE:
        return _redirect(f"/login?error=account-disabled{next_query}")

    assert user is not None
    if mfa_service.enabled(user):
        # the password step was the IdP's; the code step is ours (as for Google)
        mfa_token = create_mfa_token(user.id, user.token_version)
        return _redirect(f"/login?mfa={mfa_token}{next_query}")
    response = _redirect(next_path or "/admin")
    _set_session_cookie(response, user)
    return response
