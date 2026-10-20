from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_prefix="GANEK_", env_file=".env", extra="ignore")

    version: str = "0.1.0"  # the Sentry release tag; keep in step with the FastAPI title
    mode: Literal["single", "multi"] = "single"
    secret_key: str = "change-me"  # noqa: S105 - default triggers a critical startup warning
    # Separate key for encrypting stored third-party secrets (Google refresh
    # tokens). Unset → derived from secret_key, so rotating the signing secret
    # also invalidates stored credentials; set it to decouple the two.
    encryption_key: str | None = None
    database_url: str = "postgresql+asyncpg://ganek:ganek@localhost:5432/ganek"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str = "http://localhost:9000"
    # Endpoint candidates' browsers can reach (presigned URLs are signed
    # against this host). Defaults to s3_endpoint_url.
    s3_public_endpoint_url: str | None = None
    s3_bucket: str = "ganek-cvs"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"  # noqa: S105

    # Origin candidates reach the frontend on (quiz links in emails are built
    # against this base).
    public_base_url: str = "http://localhost:3000"

    # Google sign-in (feature is off while unset). Redirect override for
    # setups where the admin origin differs from public_base_url.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_url: str | None = None

    # Outbound transport (services/email_providers.py): smtp (default) or
    # mailjet (HTTPS API, EU-hosted; its events feed the suppression list)
    email_provider: Literal["smtp", "mailjet"] = "smtp"
    mailjet_api_key: str | None = None
    mailjet_secret_key: str | None = None

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    email_from: str = "no-reply@localhost"

    cookie_secure: bool = False  # set true behind HTTPS in production
    questions_dir: str | None = None  # explicit question-bank path (auto-detected otherwise)
    cv_max_size_mb: int = 10
    rate_limit_enabled: bool = True
    trust_proxy_headers: bool = True  # browser traffic arrives via the Next proxy
    rate_limit_auth_per_minute: int = 10
    rate_limit_apply_per_minute: int = 5
    rate_limit_upload_per_minute: int = 10
    rate_limit_quiz_per_minute: int = 60
    rate_limit_public_per_minute: int = 120
    lockout_enabled: bool = True
    lockout_max_attempts: int = 10
    lockout_window_seconds: int = 900  # 15 min
    quiz_network_grace_seconds: int = 2
    quiz_start_ttl_hours: int = 24
    # Per-tenant abuse guards (0 = off). Counted by app/services/quotas.py
    # in Redis fixed windows (in-process fallback), surfaced on
    # GET /company/usage and the admin banner.
    quota_emails_per_day: int = 500
    quota_applications_per_hour: int = 100
    quota_active_jobs: int = 50
    # Logging: "text" keeps the human-readable default; "json" emits one
    # object per line for log shippers. Every line carries the request id.
    log_format: Literal["text", "json"] = "text"
    log_level: str = "INFO"
    # Optional error reporting. Unset = nothing is initialised and nothing
    # leaves the box. Events are scrubbed (emails, tokens, CV names, cookies)
    # before they are sent; see app/core/observability.py.
    sentry_dsn: str | None = None
    sentry_environment: str | None = None
    sentry_traces_sample_rate: float = 0.0


settings = Settings()
