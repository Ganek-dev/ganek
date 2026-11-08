---
title: Configuration
description: Every Ganek environment variable, grouped, with defaults.
sidebar: { order: 2 }
---

Ganek reads its settings from environment variables, in the compose stack via the `.env` file next to `docker-compose.yml`. `.env.example` in the repository is the source of truth; this page groups the same settings with their defaults. Commented-out lines in the example are optional.

## Core

| Variable | Default | What it does |
|---|---|---|
| `GANEK_MODE` | `single` | `single` for a self-hosted instance with one company; `multi` for the hosted product (public signup, quotas, captcha). |
| `GANEK_SECRET_KEY` | change it | Signs session tokens and the capability links in candidate emails. `openssl rand -hex 32`. Rotating it signs everyone out. |
| `GANEK_ENCRYPTION_KEY` | derived from the secret key | Encrypts stored 2FA secrets and webhook signing secrets. Set it separately (`openssl rand -hex 32`) so the two keys rotate independently; rotating this one means recruiters re-enrol their authenticator. |
| `POSTGRES_PASSWORD` | `ganek` | Password of the bundled Postgres. Change it before exposing anything. |
| `GANEK_DATABASE_URL` | bundled Postgres | `postgresql+asyncpg://user:pass@host:5432/ganek` for an external server. Use a database dedicated to Ganek. |
| `GANEK_REDIS_URL` | `redis://localhost:6379/0` (compose: `redis://redis:6379/0`) | Redis for rate limits, quotas and the worker queue. |
| `GANEK_QUESTIONS_DIR` | auto-detected | Explicit path of the question bank. Unset finds the repo's `questions/` directory or `/srv/questions` in the image. |

## Object storage (CVs)

| Variable | Default | What it does |
|---|---|---|
| `GANEK_S3_ENDPOINT_URL` | `http://localhost:9000` (compose: `http://minio:9000`) | S3 endpoint the backend talks to. |
| `GANEK_S3_BUCKET` | `ganek-cvs` | Bucket for uploaded CVs. |
| `GANEK_S3_ACCESS_KEY`, `GANEK_S3_SECRET_KEY` | `minioadmin` | Credentials the backend uses. Change both. |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | `minioadmin` | Root credentials of the bundled MinIO. Change both. |
| `GANEK_S3_PUBLIC_ENDPOINT_URL` | unset | Public origin candidates upload to (presigned POST). Must be reachable from the browser. It is baked into the frontend's Content Security Policy at build time, so rebuild the frontend image after changing it. |
| `GANEK_CV_MAX_SIZE_MB` | `10` | Upload size limit; only PDF files are accepted. |

## Public URL and Google sign-in

| Variable | Default | What it does |
|---|---|---|
| `GANEK_PUBLIC_BASE_URL` | `http://localhost:3000` | The candidate-facing origin, for example `https://jobs.example.com`. Quiz, status and interview links in emails use it; the frontend builds the sitemap and Open Graph URLs from it. Set it as soon as the instance has a hostname. |
| `GANEK_GOOGLE_CLIENT_ID`, `GANEK_GOOGLE_CLIENT_SECRET` | unset | Google sign-in. Create an OAuth web client in Google Cloud Console; only the `openid email` scope is requested. |
| `GANEK_GOOGLE_REDIRECT_URL` | `${GANEK_PUBLIC_BASE_URL}/api/v1/auth/google/callback` | Override the redirect URI registered with Google. |

## Email

Emails are skipped with a warning while no provider is configured. The recruiter checklist shows the state.

| Variable | Default | What it does |
|---|---|---|
| `GANEK_EMAIL_PROVIDER` | `smtp` | `smtp` for any relay, or `mailjet` for the HTTPS API (EU-hosted; its bounce and complaint events feed the suppression list). |
| `GANEK_SMTP_HOST`, `GANEK_SMTP_PORT`, `GANEK_SMTP_USER`, `GANEK_SMTP_PASSWORD` | unset, port `587` | The SMTP relay. |
| `GANEK_SMTP_STARTTLS` | `true` | Disable only for a local plaintext catcher such as Mailhog. |
| `GANEK_EMAIL_FROM` | `no-reply@localhost` | Sender address, for example `jobs@example.com`. Set up SPF, DKIM and DMARC for its domain (see [Self-hosting](/self-hosting/#email-deliverability)). |
| `GANEK_MAILJET_API_KEY`, `GANEK_MAILJET_SECRET_KEY` | unset | Mailjet only: the REST API key pair. |

Interview invites travel as a calendar file in the booking, reschedule and cancellation emails. SMTP sends it as a proper calendar part, so Outlook, Gmail and Apple Calendar update the event in place on a reschedule or cancel. Mailjet carries it as a plain attachment: recipients add it to their calendar, and a later change arrives as a new file.

| Variable | Default | What it does |
|---|---|---|
| `GANEK_EMAIL_WEBHOOK_SECRET` | unset | Basic-auth password the provider presents on its bounce and complaint webhook (`https://ganek:<secret>@host/api/v1/email/webhooks/mailjet`). Unset means webhooks are off. |

## Signup challenge (multi mode)

| Variable | Default | What it does |
|---|---|---|
| `GANEK_CAPTCHA_ENABLED` | `false` | Self-hosted proof-of-work challenge (ALTCHA, no third party) on signup, apply and request-new-link. Only shown in `multi` mode. |
| `GANEK_CAPTCHA_SECRET` | unset | HMAC key for the challenge; any long random string. Required when enabled. |
| `GANEK_CAPTCHA_MAX_NUMBER` | `100000` | Proof-of-work ceiling the widget brute-forces; lower it for slower phones. |
| `GANEK_CAPTCHA_TTL_SECONDS` | `600` | How long a solved challenge stays valid. |

## Job page views

| Variable | Default | Meaning |
| --- | --- | --- |
| `GANEK_SSR_SECRET` | unset | Optional. Page views are counted when the frontend's server render says a load is one (no cookie, no script, no identifier; see the [GDPR guide](/compliance/self-hosting-gdpr-guide/)). Those headers can be sent by anyone who calls the API directly, so the counters are advisory. Set the same long random string on the backend and the frontend and only loads that carry it count; anything else is served as usual and not counted. |

## Logging and error reporting

| Variable | Default | What it does |
|---|---|---|
| `GANEK_LOG_FORMAT` | `text` | `json` writes one object per line for log shippers. Every line carries the request id, also returned as the `X-Request-ID` header (an inbound one is honoured). |
| `GANEK_LOG_LEVEL` | `INFO` | Standard Python levels. |
| `GANEK_SENTRY_DSN` | unset | Optional error reporting to Sentry or a self-hosted Sentry/GlitchTip. Unset means nothing leaves the box. Events are scrubbed (emails, capability tokens, CV file names, cookies). Setting this makes your Sentry host a processor: list it in your records (see the [GDPR guide](/compliance/self-hosting-gdpr-guide/)). |
| `GANEK_SENTRY_ENVIRONMENT` | unset | Environment tag; the Sentry SDK assumes `production` when it is unset. |
| `GANEK_SENTRY_TRACES_SAMPLE_RATE` | `0` | Performance tracing stays off by default. |

## Cookies and proxies

| Variable | Default | What it does |
|---|---|---|
| `GANEK_COOKIE_SECURE` | `false` | Session cookies are sent over HTTPS only. Set it to `true` in production behind TLS; the default only suits plain-HTTP local development. |
| `GANEK_TRUST_PROXY_HEADERS` | `true` | Read the client IP from `X-Forwarded-For`. Keep the backend behind a trusted proxy, or clients can spoof their IP and dodge the rate limits. |

## Rate limits and quotas

Per-IP, per-minute limits are Redis-backed with an in-memory fallback.

| Variable | Default |
|---|---|
| `GANEK_RATE_LIMIT_ENABLED` | `true` |
| `GANEK_RATE_LIMIT_AUTH_PER_MINUTE` | `10` |
| `GANEK_RATE_LIMIT_APPLY_PER_MINUTE` | `5` |
| `GANEK_RATE_LIMIT_UPLOAD_PER_MINUTE` | `10` |
| `GANEK_RATE_LIMIT_QUIZ_PER_MINUTE` | `60` |
| `GANEK_RATE_LIMIT_PUBLIC_PER_MINUTE` | `120` |

Login lockout and quiz timing:

| Variable | Default | What it does |
|---|---|---|
| `GANEK_LOCKOUT_ENABLED` | `true` | After `GANEK_LOCKOUT_MAX_ATTEMPTS` failed logins or 2FA codes for one account inside the window, further attempts are refused until the window passes. |
| `GANEK_LOCKOUT_MAX_ATTEMPTS` | `10` | Failed attempts allowed per window. |
| `GANEK_LOCKOUT_WINDOW_SECONDS` | `900` | Lockout window, 15 minutes. |
| `GANEK_QUIZ_NETWORK_GRACE_SECONDS` | `2` | Answers that arrive this long after a question's deadline still count, to absorb network jitter. |
| `GANEK_QUIZ_START_TTL_HOURS` | `24` | A quiz link must be started within this many hours of being issued. |

Per-tenant abuse guards (`0` turns one off). Admins see the counters on the usage endpoint and as a banner from 80% of a limit.

| Variable | Default | What it limits |
|---|---|---|
| `GANEK_QUOTA_EMAILS_PER_DAY` | `500` | Emails queued per day. |
| `GANEK_QUOTA_APPLICATIONS_PER_HOUR` | `100` | Application attempts per hour; the public apply endpoint answers 429 past it. |
| `GANEK_QUOTA_ACTIVE_JOBS` | `50` | Jobs published at once; publishing past it answers 409. |

## Operator plane (hosted instances)

| Variable | Default | What it does |
|---|---|---|
| `GANEK_SUPERADMIN_USER_IDS` | empty | Comma-separated user ids allowed on `/api/v1/ops`: list tenants, suspend one with a reason, unsuspend it. Every call is logged. Empty, or a caller not on the list, gets a 404. A suspended tenant's careers pages answer 503 without saying why; its users see the reason when they sign in, and its sessions and API keys are refused until it is unsuspended. The tenant's activity feed records both events, without naming the operator. |
