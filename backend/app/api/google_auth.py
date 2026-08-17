"""Google sign-in endpoints. Browser redirects are relative paths — the
browser talks to us through the Next proxy, so /login etc. resolve to the
frontend origin. See services/oauth_google.py for the flow's trust model."""

import logging
import secrets
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from app.api.auth import _set_session_cookie
from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.ratelimit import rate_limit
from app.core.security import (
    GOOGLE_FLOW_COOKIE_NAME,
    GOOGLE_FLOW_MAX_AGE_SECONDS,
    GOOGLE_SIGNUP_COOKIE_NAME,
    GOOGLE_SIGNUP_MAX_AGE_SECONDS,
    create_google_flow_token,
    create_google_signup_token,
    read_google_flow_token,
    read_google_signup_token,
)
from app.models import User
from app.schemas.auth import GoogleSignupPending, GoogleSignupRequest, UserOut
from app.services import auth as auth_service
from app.services import google_calendar, oauth_google
from app.services import invites as invites_service
from app.services import outbox as outbox_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/google", tags=["auth"])

_FLOW_COOKIE_PATH = "/api/v1/auth/google"


def _require_configured() -> None:
    if not oauth_google.configured():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Google sign-in is not configured on this instance",
        )


def _redirect(path: str) -> RedirectResponse:
    response = RedirectResponse(path, status_code=status.HTTP_302_FOUND)
    response.delete_cookie(GOOGLE_FLOW_COOKIE_NAME, path=_FLOW_COOKIE_PATH)
    return response


@router.get(
    "/start", dependencies=[rate_limit("auth", lambda: settings.rate_limit_auth_per_minute)]
)
async def google_start(invite: str | None = None) -> RedirectResponse:
    _require_configured()
    url, state, verifier, nonce = oauth_google.build_authorization_request()
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        GOOGLE_FLOW_COOKIE_NAME,
        create_google_flow_token(state, verifier, nonce, invite=invite),
        max_age=GOOGLE_FLOW_MAX_AGE_SECONDS,
        httponly=True,
        # Lax, not Strict: Google's redirect back is a cross-site navigation
        samesite="lax",
        secure=settings.cookie_secure,
        path=_FLOW_COOKIE_PATH,
    )
    return response


async def _accept_invite_via_google(
    db: DbSession, *, invite_token: str, claims: dict[str, object]
) -> RedirectResponse:
    """Invite-accept branch of the callback: the invite decides the workspace;
    Google only vouches for the invited email (must match, must be verified)."""
    invite = await invites_service.invite_by_token(db, invite_token)
    if invite is None:
        return _redirect(f"/invite/{invite_token}?error=google-invalid")
    email_matches = str(claims.get("email", "")).casefold() == invite.email.casefold()
    if not email_matches or not claims.get("email_verified"):
        return _redirect(f"/invite/{invite_token}?error=google-email-mismatch")
    try:
        user = await invites_service.accept_invite_google(db, invite, str(claims["sub"]))
    except invites_service.InviteExpiredError:
        return _redirect(f"/invite/{invite_token}")  # page renders its own expired state
    except invites_service.EmailTakenError:
        return _redirect(f"/invite/{invite_token}?error=email-taken")
    response = _redirect("/admin")
    _set_session_cookie(response, user)
    return response


@router.get(
    "/calendar/connect",
    dependencies=[rate_limit("auth", lambda: settings.rate_limit_auth_per_minute)],
)
async def google_calendar_connect(user: CurrentUser) -> RedirectResponse:
    """Incremental-auth consent for Calendar access (offline → refresh token)."""
    _require_configured()
    url, state, verifier, nonce = oauth_google.build_authorization_request(calendar=True)
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        GOOGLE_FLOW_COOKIE_NAME,
        create_google_flow_token(state, verifier, nonce, calendar_user_id=str(user.id)),
        max_age=GOOGLE_FLOW_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path=_FLOW_COOKIE_PATH,
    )
    return response


async def _connect_calendar_via_google(
    db: DbSession, *, user_id: str, claims: dict[str, object], refresh_token: str | None
) -> RedirectResponse:
    """Calendar-connect branch of the callback: the session user was captured
    in the flow cookie; the Google account must be (or become) theirs."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return _redirect("/admin/account?calendar=failed")
    user = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if user is None or not user.is_active:
        return _redirect("/admin/account?calendar=failed")
    sub = str(claims["sub"])
    if user.google_sub is not None and user.google_sub != sub:
        return _redirect("/admin/account?calendar=wrong-account")
    if refresh_token is None:
        # consent flow completed without offline grant — retry needs prompt=consent
        return _redirect("/admin/account?calendar=failed")
    if user.google_sub is None:
        sub_taken = (
            await db.execute(
                select(func.count())
                .select_from(User)
                .where(User.google_sub == sub, User.id != user.id)
            )
        ).scalar_one()
        if sub_taken:
            return _redirect("/admin/account?calendar=wrong-account")
        user.google_sub = sub
    await google_calendar.store_credentials(
        db, user, refresh_token=refresh_token, google_email=str(claims["email"])
    )
    return _redirect("/admin/account?calendar=connected")


@router.get("/callback")
async def google_callback(request: Request, db: DbSession) -> RedirectResponse:
    _require_configured()
    if request.query_params.get("error") == "access_denied":
        return _redirect("/login")  # user cancelled on Google's screen: no error banner
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    flow = read_google_flow_token(request.cookies.get(GOOGLE_FLOW_COOKIE_NAME, ""))
    if not code or not state or flow is None or not secrets.compare_digest(state, flow[0]):
        return _redirect("/login?error=google-failed")
    try:
        claims, refresh_token = await oauth_google.exchange_code_full(code, flow[1])
        oauth_google.validate_claims(claims, nonce=flow[2])
    except oauth_google.GoogleOAuthError:
        logger.warning("google oauth handshake failed", exc_info=True)
        return _redirect("/login?error=google-failed")

    if flow[4] is not None:
        return await _connect_calendar_via_google(
            db, user_id=flow[4], claims=claims, refresh_token=refresh_token
        )

    if flow[3] is not None:
        return await _accept_invite_via_google(db, invite_token=flow[3], claims=claims)

    resolution, user = await oauth_google.resolve_identity(db, claims)
    if resolution is oauth_google.Resolution.SIGNUP:
        # sub+email stay out of the URL (browser history / proxy logs): the
        # signed token rides an httponly cookie and /setup?google=pending
        # learns the email via GET /signup/pending.
        token = create_google_signup_token(str(claims["sub"]), str(claims["email"]))
        response = _redirect("/setup?google=pending")
        response.set_cookie(
            GOOGLE_SIGNUP_COOKIE_NAME,
            token,
            max_age=GOOGLE_SIGNUP_MAX_AGE_SECONDS,
            httponly=True,
            samesite="lax",
            secure=settings.cookie_secure,
            path=_FLOW_COOKIE_PATH,
        )
        return response
    if resolution is oauth_google.Resolution.USE_PASSWORD:
        return _redirect("/login?error=use-password")
    if resolution is oauth_google.Resolution.INACTIVE:
        return _redirect("/login?error=account-disabled")

    assert user is not None
    if resolution is oauth_google.Resolution.LINKED:
        await outbox_service.queue_email(
            db,
            kind="google_linked",
            company_id=user.company_id,
            to=user.email,
            ref=str(user.id),
            company_name=user.company.name,
        )
    response = _redirect("/admin")
    _set_session_cookie(response, user)
    return response


@router.get(
    "/signup/pending",
    response_model=GoogleSignupPending,
    dependencies=[rate_limit("auth", lambda: settings.rate_limit_auth_per_minute)],
)
async def google_signup_pending(request: Request) -> GoogleSignupPending:
    """Which Google account the pending signup is for — /setup shows this
    instead of decoding the token client-side (the token stays in the
    httponly cookie)."""
    _require_configured()
    data = read_google_signup_token(request.cookies.get(GOOGLE_SIGNUP_COOKIE_NAME, ""))
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This Google signup session has expired — sign in with Google again",
        )
    return GoogleSignupPending(email=data[1])


@router.post(
    "/signup",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[rate_limit("auth", lambda: settings.rate_limit_auth_per_minute)],
)
async def google_signup(
    payload: GoogleSignupRequest, request: Request, response: Response, db: DbSession
) -> User:
    _require_configured()
    data = read_google_signup_token(request.cookies.get(GOOGLE_SIGNUP_COOKIE_NAME, ""))
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This Google signup session has expired — sign in with Google again",
        )
    sub, email = data
    try:
        user = await auth_service.register_company_google(
            db, company_name=payload.company_name, email=email, google_sub=sub
        )
    except auth_service.RegistrationClosedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration is closed on this instance",
        ) from None
    except auth_service.EmailTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from None
    response.delete_cookie(GOOGLE_SIGNUP_COOKIE_NAME, path=_FLOW_COOKIE_PATH)
    _set_session_cookie(response, user)
    return user
