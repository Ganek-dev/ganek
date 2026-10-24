from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core import challenge, urls
from app.core.config import settings
from app.core.ratelimit import rate_limit
from app.core.security import (
    EMAIL_VERIFY_MAX_AGE_SECONDS,
    PASSWORD_RESET_MAX_AGE_SECONDS,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    create_email_verify_token,
    create_mfa_token,
    create_password_reset_token,
    create_session_token,
    read_email_verify_token,
    read_mfa_token,
    read_password_reset_token,
    verify_password,
)
from app.models import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MfaCodeRequest,
    MfaDisableRequest,
    MfaEnrolOut,
    MfaRecoveryCodesOut,
    MfaVerifyRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UserOut,
    VerifyEmailRequest,
)
from app.services import auth as auth_service
from app.services import demo_mode
from app.services import mfa as mfa_service
from app.services import outbox as outbox_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, user: User) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(user.id, user.token_version),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[rate_limit("auth", lambda: settings.rate_limit_auth_per_minute)],
)
async def register(payload: RegisterRequest, response: Response, db: DbSession) -> UserOut:
    await challenge.require(payload.altcha)
    try:
        user = await auth_service.register_company_admin(
            db,
            company_name=payload.company_name,
            email=payload.email,
            password=payload.password,
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
    if not user.is_active:
        # multi-mode signup awaiting verification: no session until the
        # inbox click — the company is inert and sweepable meanwhile
        await _queue_verification_email(db, user)
        out = UserOut.model_validate(user)
        out.pending_verification = True
        return out
    _set_session_cookie(response, user)
    return UserOut.model_validate(user)


async def _queue_verification_email(db: DbSession, user: User) -> None:
    from sqlalchemy import select as _select

    from app.models import Company

    company = (await db.execute(_select(Company).where(Company.id == user.company_id))).scalar_one()
    token = create_email_verify_token(user.id)
    await outbox_service.queue_email(
        db,
        kind="email_verification",
        company_id=company.id,
        to=user.email,
        ref=str(user.id),
        company_name=company.name,
        verify_url=urls.email_verify_url(company, token),
        expires_days=EMAIL_VERIFY_MAX_AGE_SECONDS // 86400,
    )


@router.post(
    "/login",
    response_model=UserOut,
    dependencies=[rate_limit("auth", lambda: settings.rate_limit_auth_per_minute)],
)
async def login(payload: LoginRequest, response: Response, db: DbSession) -> UserOut:
    try:
        user = await auth_service.authenticate(db, email=payload.email, password=payload.password)
    except auth_service.AccountLockedError:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account temporarily locked after repeated failed logins",
        ) from None
    except auth_service.EmailUnverifiedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verify your email first — check your inbox for the activation link",
        ) from None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    if mfa_service.enabled(user):
        # first factor passed; no cookie until the code is right
        return _mfa_challenge(user)
    _set_session_cookie(response, user)
    return UserOut.model_validate(user)


def _mfa_challenge(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.mfa_required = True
    out.mfa_token = create_mfa_token(user.id, user.token_version)
    return out


@router.post(
    "/mfa",
    response_model=UserOut,
    dependencies=[rate_limit("auth", lambda: settings.rate_limit_auth_per_minute)],
)
async def mfa_verify(payload: MfaVerifyRequest, response: Response, db: DbSession) -> User:
    """Login step two (card A6): the authenticator code or a recovery code."""
    parsed = read_mfa_token(payload.mfa_token)
    user = await db.get(User, parsed[0]) if parsed is not None else None
    if user is None or not user.is_active or parsed is None or user.token_version != parsed[1]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in again to continue"
        )
    try:
        await mfa_service.verify(db, user, payload.code)
    except mfa_service.MfaLockedError:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Too many wrong codes; try again in a few minutes",
        ) from None
    except mfa_service.MfaError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong code") from None
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    _set_session_cookie(response, user)
    return user


@router.post("/mfa/enrol", response_model=MfaEnrolOut, dependencies=[demo_mode.locked])
async def mfa_enrol(db: DbSession, user: CurrentUser) -> MfaEnrolOut:
    """Start enrolment: a pending secret for the authenticator app."""
    try:
        secret, uri = await mfa_service.begin(db, user)
    except mfa_service.MfaError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Two-factor authentication is already on"
        ) from None
    return MfaEnrolOut(secret=secret, otpauth_uri=uri)


@router.post("/mfa/confirm", response_model=MfaRecoveryCodesOut, dependencies=[demo_mode.locked])
async def mfa_confirm(
    payload: MfaCodeRequest, db: DbSession, user: CurrentUser
) -> MfaRecoveryCodesOut:
    """Turn it on once the app shows a valid code; the recovery codes come
    back exactly once."""
    try:
        codes = await mfa_service.confirm(db, user, payload.code)
    except mfa_service.WrongCodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That code is not right; try the next one",
        ) from None
    except mfa_service.MfaError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Start enrolment first"
        ) from None
    return MfaRecoveryCodesOut(recovery_codes=codes)


@router.post(
    "/mfa/disable", status_code=status.HTTP_204_NO_CONTENT, dependencies=[demo_mode.locked]
)
async def mfa_disable(payload: MfaDisableRequest, db: DbSession, user: CurrentUser) -> None:
    """Re-authenticate with the password (or a code, for Google-only
    accounts), then drop the factor."""
    if not mfa_service.enabled(user):
        return
    ok = False
    if payload.password is not None and user.password_hash is not None:
        ok = verify_password(payload.password, user.password_hash)
    elif payload.code is not None:
        try:
            await mfa_service.verify(db, user, payload.code)
            ok = True
        except mfa_service.MfaError:
            ok = False
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Re-authentication failed"
        )
    await mfa_service.disable(db, user)


@router.post(
    "/sign-out-everywhere",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[demo_mode.locked],
)
async def sign_out_everywhere(response: Response, db: DbSession, user: CurrentUser) -> None:
    """Retire every session for this account; the caller keeps this one
    (re-issued with the new version)."""
    await mfa_service.sign_out_everywhere(db, user)
    _set_session_cookie(response, user)


@router.get("/providers")
async def providers() -> dict[str, bool | str | dict[str, int]]:
    """Which optional sign-in methods this instance has configured, its
    deployment mode (single = careers at the instance root) and the
    per-tenant limits the signup page lists under "what you get" (card B3;
    0 = that guard is off). Public on purpose: the same numbers already
    leak through the 429/409 responses on apply and publish."""
    return {
        "google": bool(settings.google_client_id and settings.google_client_secret),
        "mode": settings.mode,
        "demo": settings.demo_mode,
        "limits": {
            "active_jobs": settings.quota_active_jobs,
            "applications_per_hour": settings.quota_applications_per_hour,
            "emails_per_day": settings.quota_emails_per_day,
        },
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user


@router.post(
    "/verify-email",
    response_model=UserOut,
    dependencies=[rate_limit("auth", lambda: settings.rate_limit_auth_per_minute)],
)
async def verify_email(payload: VerifyEmailRequest, response: Response, db: DbSession) -> User:
    """Activate a pending multi-mode signup and log its admin in."""
    user_id = read_email_verify_token(payload.token)
    if user_id is not None:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None:
            if user.is_active:
                _set_session_cookie(response, user)
                return user  # double-click / stale tab: already verified is fine
            if await auth_service.is_pending_verification(db, user):
                await auth_service.verify_email(db, user)
                _set_session_cookie(response, user)
                return user
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="This verification link is invalid or has expired — request a new one",
    )


@router.post(
    "/resend-verification",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[rate_limit("auth", lambda: settings.rate_limit_auth_per_minute)],
)
async def resend_verification(payload: ForgotPasswordRequest, db: DbSession) -> None:
    """Always 204 — reveals nothing about which signups exist."""
    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if user is None or user.is_active or not await auth_service.is_pending_verification(db, user):
        return
    await _queue_verification_email(db, user)


@router.post(
    "/forgot-password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        rate_limit("auth", lambda: settings.rate_limit_auth_per_minute),
        demo_mode.locked,
    ],
)
async def forgot_password(payload: ForgotPasswordRequest, db: DbSession) -> None:
    """Always 204 — the response must not reveal whether an account exists.

    The one true dropped ball of D5 (13c): until now a locked-out
    single-mode admin had no recovery but SQL.
    """
    resolved = await auth_service.password_reset_target(db, email=payload.email)
    if resolved is None:
        return
    user, company = resolved
    token = create_password_reset_token(user.id, user.token_version)
    await outbox_service.queue_email(
        db,
        kind="password_reset",
        company_id=company.id,
        to=user.email,
        ref=str(user.id),
        company_name=company.name,
        reset_url=urls.password_reset_url(company, token),
        brand_primary=(company.theme or {}).get("primary_color"),
        expires_minutes=PASSWORD_RESET_MAX_AGE_SECONDS // 60,
    )


@router.post(
    "/reset-password",
    response_model=UserOut,
    dependencies=[
        rate_limit("auth", lambda: settings.rate_limit_auth_per_minute),
        demo_mode.locked,
    ],
)
async def reset_password(payload: ResetPasswordRequest, response: Response, db: DbSession) -> User:
    """Completes a reset and logs the user in. The token embeds the
    token_version it was issued against, so it is single-use: set_password
    bumps the version, retiring this link, its siblings, and every
    existing session in one move."""
    parsed = read_password_reset_token(payload.token)
    if parsed is not None:
        user_id, version = parsed
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is not None and user.is_active and user.token_version == version:
            await auth_service.set_password(db, user, new_password=payload.new_password)
            _set_session_cookie(response, user)
            return user
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="This reset link is invalid or has expired — request a new one",
    )


@router.post(
    "/change-password", status_code=status.HTTP_204_NO_CONTENT, dependencies=[demo_mode.locked]
)
async def change_password(
    payload: ChangePasswordRequest, response: Response, db: DbSession, user: CurrentUser
) -> None:
    ok = await auth_service.change_password(
        db,
        user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect"
        )
    # re-issue this session with the new version so the caller stays logged in
    _set_session_cookie(response, user)
