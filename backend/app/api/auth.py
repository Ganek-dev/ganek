from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.ratelimit import rate_limit
from app.core.security import (
    EMAIL_VERIFY_MAX_AGE_SECONDS,
    PASSWORD_RESET_MAX_AGE_SECONDS,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    create_email_verify_token,
    create_password_reset_token,
    create_session_token,
    read_email_verify_token,
    read_password_reset_token,
)
from app.models import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UserOut,
    VerifyEmailRequest,
)
from app.services import auth as auth_service
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
        verify_url=f"{settings.public_base_url.rstrip('/')}/verify?token={token}",
        expires_days=EMAIL_VERIFY_MAX_AGE_SECONDS // 86400,
    )


@router.post(
    "/login",
    response_model=UserOut,
    dependencies=[rate_limit("auth", lambda: settings.rate_limit_auth_per_minute)],
)
async def login(payload: LoginRequest, response: Response, db: DbSession) -> User:
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
    _set_session_cookie(response, user)
    return user


@router.get("/providers")
async def providers() -> dict[str, bool | str]:
    """Which optional sign-in methods this instance has configured, and its
    deployment mode (single = careers at the instance root)."""
    return {
        "google": bool(settings.google_client_id and settings.google_client_secret),
        "mode": settings.mode,
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
    dependencies=[rate_limit("auth", lambda: settings.rate_limit_auth_per_minute)],
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
        reset_url=f"{settings.public_base_url.rstrip('/')}/reset?token={token}",
        brand_primary=(company.theme or {}).get("primary_color"),
        expires_minutes=PASSWORD_RESET_MAX_AGE_SECONDS // 60,
    )


@router.post(
    "/reset-password",
    response_model=UserOut,
    dependencies=[rate_limit("auth", lambda: settings.rate_limit_auth_per_minute)],
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


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
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
