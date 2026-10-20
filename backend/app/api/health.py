"""Deep health probe. Mounted at /api/health/deep, outside /api/v1: it is
an operator endpoint, not tenant API, and the shallow /api/health in
app.main stays exactly as it is (DB-free)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.deps import DbSession
from app.core.security import SESSION_COOKIE_NAME, read_session_token
from app.services import health as health_service

router = APIRouter(tags=["health"])

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _allow_deep_health(request: Request) -> None:
    """Loopback peers (compose healthchecks, an operator on the box) and
    holders of a validly signed session cookie.

    The cookie check is signature-only, no user lookup: the gate has to
    keep working while Postgres is the thing that is down. The response
    carries dependency status only, never tenant data, so a revoked but
    well-signed session learning that Redis is up is acceptable.
    """
    peer = request.client.host if request.client else None
    if peer in _LOOPBACK:
        return
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token and read_session_token(token) is not None:
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


@router.get("/health/deep", dependencies=[Depends(_allow_deep_health)])
async def deep_health(db: DbSession, response: Response) -> dict[str, Any]:
    healthy, body = await health_service.deep_status(db)
    response.headers["Cache-Control"] = "no-store"
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return body
