---
title: Self-hosting
description: Production checklist, reverse proxy, upgrades, backups and restore, email deliverability, scaling.
sidebar: { order: 3 }
---

Candidate personal data lives in your Ganek instance, so the production checklist is also a GDPR checklist. The [compliance pack](/compliance/) covers the controller side; this page covers the box.

## Production checklist

- **HTTPS everywhere.** Terminate TLS at your reverse proxy and keep `GANEK_COOKIE_SECURE=true`. Quiz, status and interview links are bearer tokens; plain HTTP exposes them.
- **Backend behind the proxy.** The default compose binds port 8000 to `127.0.0.1`. Keep it that way, or publish it only behind a proxy. `GANEK_TRUST_PROXY_HEADERS` reads `X-Forwarded-For`; a directly reachable backend lets clients spoof their IP and dodge the rate limits.
- **Change every default credential.** `POSTGRES_PASSWORD`, `GANEK_S3_ACCESS_KEY`, `GANEK_S3_SECRET_KEY`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, and a fresh `GANEK_SECRET_KEY` plus `GANEK_ENCRYPTION_KEY`.
- **MinIO stays private.** The console and API bind to localhost. Candidates only need the presigned-upload origin in `GANEK_S3_PUBLIC_ENDPOINT_URL`.
- **Redis.** The compose network keeps it internal. Any other topology needs `requirepass` (`redis://:password@host:6379/0`); job payloads reference candidate data.
- **Email over TLS.** Keep `GANEK_SMTP_STARTTLS=true` for anything beyond a local catcher; candidate names and links transit email.
- **Encryption at rest.** The app sets no S3 server-side-encryption headers. Enable encryption on the storage layer (MinIO KMS or SSE, disk encryption, or a provider that encrypts by default), and on the Postgres volume.
- **Set `GANEK_PUBLIC_BASE_URL`** so emails and the sitemap carry the right origin.

## Reverse proxy

Route the public hostname to the frontend on port 3000. The frontend proxies `/api/*` to the backend, so a single upstream is enough. Pass `X-Forwarded-For` and `X-Forwarded-Proto` through. If candidates upload to a separate hostname, route that to MinIO (port 9000) and set `GANEK_S3_PUBLIC_ENDPOINT_URL` to it, then rebuild the frontend image so its Content Security Policy allows the origin.

## Upgrades

1. Read the release notes on GitHub. A release that adds a migration says so.
2. Back up first (below).
3. `git pull` (or bump the pinned image tag in your compose file), then `docker compose up --build -d`. The `migrate` service applies pending migrations before the app starts; nothing runs migrations by hand.
4. Do not downgrade across a migration. Restore the backup instead.

The backend exposes `GET /api/health` for your uptime checks.

## Backups and restore

`scripts/backup.sh [dir]` writes a Postgres custom-format dump and a tarball of the CV bucket volume into one directory. `scripts/restore.sh <db.dump> [cvs.tgz]` restores both.

The restore is erasure-aware: it keeps the live erasure tombstones, restores, migrates, merges the tombstones back and replays them, so candidates erased after the backup was taken stay erased. Two rules follow from the GDPR side:

- Keep the backup rotation window at or below your configured retention period.
- Never restore erased candidates by hand; completing the rotation completes the erasure.

The [GDPR guide](/compliance/self-hosting-gdpr-guide/) has the policy wording for your records.

## Email deliverability

Candidate emails (quiz invites, status updates, interview invites) only help when they land. For the sender domain in `GANEK_EMAIL_FROM`:

- Publish SPF for your relay or for Mailjet, sign with DKIM, and add a DMARC record.
- With `GANEK_EMAIL_PROVIDER=mailjet`, set `GANEK_EMAIL_WEBHOOK_SECRET` and point Mailjet's event webhook at `https://ganek:<secret>@your-host/api/v1/email/webhooks/mailjet`. Bounced and complained addresses go on a suppression list and are skipped from then on; the email trail on each application shows the state.
- Switching provider makes the provider a processor. Record it, see the GDPR guide.

## Scaling

The worker handles emails, reminders and the nightly retention purge. Run as many worker containers as you like: cron jobs are deduplicated across replicas. Interview booking takes a database advisory lock per interviewer, so concurrent candidates cannot double-book a slot. Postgres on the box is fine at launch scale; move it to a managed EU provider only when you want managed, not for performance.

## Logs

Every backend log line carries the request id, returned to the client as `X-Request-ID`. `GANEK_LOG_FORMAT=json` is for log shippers. Optional Sentry reporting is scrubbed before sending and off until you set a DSN; nothing leaves the box otherwise.
