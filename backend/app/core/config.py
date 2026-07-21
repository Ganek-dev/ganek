from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_prefix="VETD_", env_file=".env", extra="ignore")

    mode: Literal["single", "multi"] = "single"
    secret_key: str = "change-me"  # noqa: S105 - overridden in prod, validated below
    database_url: str = "postgresql+asyncpg://vetd:vetd@localhost:5432/vetd"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str = "http://localhost:9000"
    # Endpoint candidates' browsers can reach (presigned URLs are signed
    # against this host). Defaults to s3_endpoint_url.
    s3_public_endpoint_url: str | None = None
    s3_bucket: str = "vetd-cvs"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"  # noqa: S105

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    email_from: str = "no-reply@localhost"

    cookie_secure: bool = False  # set true behind HTTPS in production
    cv_max_size_mb: int = 10
    quiz_network_grace_seconds: int = 2


settings = Settings()
