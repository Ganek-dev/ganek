#!/usr/bin/env bash
# Ganek restore, erasure-aware. Restores a scripts/backup.sh dump (and
# optionally the CV bucket tarball), then REPLAYS ERASURE TOMBSTONES so
# candidates erased after the backup was taken do not come back:
#
#   1. stop the app containers (nothing writes during the restore)
#   2. save the LIVE erasure_tombstones table (the dump may predate them)
#   3. pg_restore the dump, migrate the schema to head
#   4. merge the saved tombstones back in (ON CONFLICT DO NOTHING)
#   5. optionally replace the bucket volume from the tarball
#   6. start the app, run `python -m app.services.tombstones` (replay):
#      every restored row whose id hash has a tombstone is erased again,
#      CV object first.
#
#   scripts/restore.sh backups/ganek-db-<ts>.dump [backups/ganek-cvs-<ts>.tgz]
#   COMPOSE_CMD="docker compose -p other" scripts/restore.sh ...
set -euo pipefail

COMPOSE="${COMPOSE_CMD:-docker compose}"
DUMP="${1:?usage: restore.sh <db.dump> [cvs.tgz]}"
CVS="${2:-}"
[ -f "$DUMP" ] || { echo "no such dump: $DUMP"; exit 2; }
[ -z "$CVS" ] || [ -f "$CVS" ] || { echo "no such bucket tarball: $CVS"; exit 2; }
TOMBSTONES="$(mktemp)"
trap 'rm -f "$TOMBSTONES"' EXIT

echo "--- 1. stopping backend, worker, frontend"
$COMPOSE stop backend worker frontend >/dev/null

echo "--- 2. saving live erasure tombstones"
# --on-conflict-do-nothing (pg >= 12) makes the merge in step 4 idempotent;
# an instance that predates migration 0024 simply has none yet
$COMPOSE exec -T postgres pg_dump -U ganek --data-only --inserts --on-conflict-do-nothing \
  -t erasure_tombstones ganek > "$TOMBSTONES" 2>/dev/null || : > "$TOMBSTONES"

echo "--- 3. restoring $DUMP"
# --clean/--if-exists drop and recreate every object in the dump; errors
# about objects the dump does not know are expected on an older dump
$COMPOSE exec -T postgres pg_restore -U ganek -d ganek --clean --if-exists --no-owner \
  --exit-on-error < "$DUMP"
$COMPOSE start backend >/dev/null
for _ in $(seq 1 30); do
  $COMPOSE exec -T backend /srv/.venv/bin/python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" \
    >/dev/null 2>&1 && break
  sleep 2
done
$COMPOSE exec -T backend uv run alembic upgrade head

echo "--- 4. merging saved tombstones"
if [ -s "$TOMBSTONES" ]; then
  $COMPOSE exec -T postgres psql -U ganek -d ganek -q -v ON_ERROR_STOP=1 < "$TOMBSTONES"
fi

if [ -n "$CVS" ]; then
  echo "--- 5. replacing the cv bucket volume from $CVS"
  VOLUME="$($COMPOSE config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["volumes"]["miniodata"]["name"])')"
  CVS_ABS="$(cd "$(dirname "$CVS")" && pwd)/$(basename "$CVS")"
  $COMPOSE stop minio >/dev/null
  docker run --rm -v "$VOLUME:/data" -v "$CVS_ABS:/backup.tgz:ro" alpine \
    sh -c 'find /data -mindepth 1 -delete && tar xzf /backup.tgz -C /data'
  $COMPOSE start minio >/dev/null
fi

echo "--- 6. starting worker and frontend, replaying erasure tombstones"
$COMPOSE start worker frontend >/dev/null
$COMPOSE exec -T backend uv run python -m app.services.tombstones

echo "restore: done"
