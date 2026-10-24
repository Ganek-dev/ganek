#!/usr/bin/env bash
# Ganek demo workspace: ACME Ganek with jobs, applicants and completed
# quizzes, for a first look at the admin UI, for screenshots, and for the
# public demo. Runs the seed inside the backend image of a running compose
# stack, so it needs no local Python. Everyone in it is fictional; candidate
# addresses end in @example.com.
#
#   scripts/dev_seed.sh            # create if missing, otherwise leave alone
#   scripts/dev_seed.sh --reset    # delete and rebuild the demo company
#   GANEK_DEMO_PASSWORD=... scripts/dev_seed.sh --reset
#   COMPOSE_CMD="docker compose -p other" scripts/dev_seed.sh
#
# Afterwards: log in as erika@acme.example (password ganek-demo-1 unless
# you set GANEK_DEMO_PASSWORD); the careers page is at /c/acme. In single
# mode "/" serves the oldest company, which is this one on a fresh database.
set -euo pipefail

COMPOSE_CMD="${COMPOSE_CMD:-docker compose}"
PASSWORD="${GANEK_DEMO_PASSWORD:-}"

exec ${COMPOSE_CMD} exec -T \
  ${PASSWORD:+-e GANEK_DEMO_PASSWORD="$PASSWORD"} \
  backend uv run python -m app.services.demo_seed "$@"
