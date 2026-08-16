from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.ratelimit import rate_limit
from app.core.security import SESSION_COOKIE_NAME, SESSION_MAX_AGE_SECONDS, create_session_token
from app.models import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    UserOut,
)
from app.services import auth as auth_service

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
async def register(payload: RegisterRequest, response: Response, db: DbSession) -> User:
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
    _set_session_cookie(response, user)
    return user


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
