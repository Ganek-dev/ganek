from fastapi import FastAPI

from app.api import auth, jobs
from app.core.config import settings

app = FastAPI(
    title="Vetd",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": settings.mode}
