import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.api import (
    applications,
    auth,
    company,
    jobs,
    public,
    questionnaires,
    questions,
    stats,
    users,
)
from app.core.config import settings
from app.services.storage import ensure_bucket_async

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.secret_key == "change-me":  # noqa: S105
        message = (
            "VETD_SECRET_KEY is the default value — sessions and quiz tokens are "
            "forgeable. Set a real secret: openssl rand -hex 32"
        )
        if settings.mode == "multi":
            # a hosted (multi-tenant) instance must never boot forgeable
            raise RuntimeError(message)
        logger.critical(message)
    try:
        await ensure_bucket_async()
    except Exception:  # noqa: BLE001 - S3 is optional at boot (e.g. DB-less tests)
        logger.warning("could not ensure S3 bucket; CV uploads will fail", exc_info=True)
    yield


app = FastAPI(
    title="Vetd",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.include_router(applications.router, prefix="/api/v1")


@app.middleware("http")
async def security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if request.url.path.startswith("/api/v1"):
        # API responses carry per-user data; never let shared caches keep them
        response.headers.setdefault("Cache-Control", "no-store")
    return response


app.include_router(auth.router, prefix="/api/v1")
app.include_router(company.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(public.router, prefix="/api/v1")
app.include_router(questionnaires.router, prefix="/api/v1")
app.include_router(questions.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": settings.mode}
