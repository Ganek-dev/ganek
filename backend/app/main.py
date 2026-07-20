from fastapi import FastAPI

from app.core.config import settings

app = FastAPI(
    title="Vetd",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": settings.mode}


# M0: wire routers here as they are built, e.g.
# from app.api import auth, companies, jobs, applications, quiz, public
# app.include_router(auth.router, prefix="/api/v1")
