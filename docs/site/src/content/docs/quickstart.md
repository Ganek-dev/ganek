---
title: Quickstart
description: Run Ganek on your own machine or server with Docker Compose.
sidebar: { order: 1 }
---

Ganek ships as a Docker Compose stack: a FastAPI backend, a Next.js frontend, a background worker, Postgres, Redis and MinIO for CV storage. Everything runs on your machine; nothing phones home.

## Requirements

- Docker with Compose v2 (`docker compose version` works).
- About 2 GB of RAM for the full stack.
- x86-64 or arm64 (Apple Silicon, Graviton and Raspberry Pi 5 all work; the compose stack builds the images from source).

## Start the stack

```bash
git clone https://github.com/ganek-dev/ganek && cd ganek
cp .env.example .env        # edit as needed, see Configuration
docker compose up
```

On the first start the `migrate` service applies the database migrations and seeds the open question bank, then the app comes up. Open <http://localhost:3000> and follow the setup wizard: it creates your company and the first admin account.

Ports on the host:

| Service | Address | Notes |
|---|---|---|
| Frontend | `localhost:3000` | the only port you need |
| Backend API | `127.0.0.1:8000` | bound to localhost; keep it behind the frontend or a proxy |
| MinIO | `127.0.0.1:9000`, console `9001` | localhost only; candidates upload through the presigned endpoint you configure |

Postgres and Redis are not published on the host.

## Pre-built images

Every release publishes `ghcr.io/ganek-dev/ganek-backend` and `ghcr.io/ganek-dev/ganek-frontend` tagged with the version (`0.3.0`) and `latest`. Pin a version tag in production and read the [upgrade notes](/self-hosting/#upgrades) before moving.

## Your own database

Ganek expects a database of its own. The bundled Postgres has an isolated volume and no published port. If you point Ganek at an existing server instead, create a dedicated database for it and set `GANEK_DATABASE_URL`; do not share a database with another application.

## Next

- [Configuration](/configuration/): every environment variable with its default.
- [Self-hosting](/self-hosting/): the production checklist, reverse proxy, upgrades, backups.
- [Compliance pack](/compliance/): what to do before your first candidate.
