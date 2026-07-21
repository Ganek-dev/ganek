import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth, jobs, public
from app.core.config import settings
from app.services.storage import ensure_bucket_async

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
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

app.include_router(auth.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(public.router, prefix="/api/v1")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": settings.mode}
