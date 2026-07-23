from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.ratelimit import rate_limit
from app.core.security import SESSION_COOKIE_NAME, SESSION_MAX_AGE_SECONDS, create_session_token
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, UserOut
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, user: User) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(user.id),
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
    user = await auth_service.authenticate(db, email=payload.email, password=payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    _set_session_cookie(response, user)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
