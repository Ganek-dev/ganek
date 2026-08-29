#!/usr/bin/env bash
# One-time dev-data migration for the vetd → ganek rename: copies the named
# volumes to their new names, renames the postgres role/db and the minio
# bucket inside the copies. The old vetd-* volumes are never modified — they
# stay behind as backups until you `docker volume rm` them yourself.
#
# Usage: POSTGRES_PASSWORD=... scripts/migrate_dev_data_ganek.sh
# (POSTGRES_PASSWORD defaults to "ganek", matching docker-compose.yml)
set -euo pipefail

PG_OLD=vetd-postgres-data PG_NEW=ganek-postgres-data
MINIO_OLD=vetd-minio-data MINIO_NEW=ganek-minio-data
PG_IMAGE=postgres:16-alpine # must match docker-compose.yml
NEW_PASSWORD="${POSTGRES_PASSWORD:-ganek}"

copy_volume() {
  local from=$1 to=$2
  docker volume inspect "$from" >/dev/null 2>&1 || { echo "skip: $from does not exist"; return 1; }
  if docker volume inspect "$to" >/dev/null 2>&1; then
    echo "skip: $to already exists (remove it first to re-run)"; return 1
  fi
  docker volume create "$to" >/dev/null
  docker run --rm -v "$from":/from:ro -v "$to":/to alpine sh -c 'cp -a /from/. /to/'
  echo "copied $from -> $to"
}

echo "== stopping the old vetd compose project (its volumes are kept) =="
docker compose -p vetd down --remove-orphans 2>/dev/null || true

if copy_volume "$PG_OLD" "$PG_NEW"; then
  echo "== renaming postgres role+db vetd -> ganek in the copy =="
  docker run -d --name ganek-migrate-pg -v "$PG_NEW":/var/lib/postgresql/data "$PG_IMAGE" >/dev/null
  trap 'docker rm -f ganek-migrate-pg >/dev/null 2>&1 || true' EXIT
  for _ in $(seq 1 30); do
    docker exec ganek-migrate-pg pg_isready -U vetd >/dev/null 2>&1 && break
    sleep 1
  done
  # vetd is the bootstrap superuser: it cannot be dropped or reassigned,
  # but it CAN be renamed (SCRAM passwords survive a rename). Rename via a
  # temporary admin role since a role can't rename itself.
  docker exec ganek-migrate-pg psql -U vetd -d postgres -v ON_ERROR_STOP=1 \
    -c "CREATE ROLE ganek_mig_tmp LOGIN SUPERUSER PASSWORD 'tmp';" \
    -c "ALTER DATABASE vetd RENAME TO ganek;"
  docker exec ganek-migrate-pg psql -U ganek_mig_tmp -d postgres -v ON_ERROR_STOP=1 \
    -c "ALTER ROLE vetd RENAME TO ganek;" \
    -c "ALTER ROLE ganek PASSWORD '$NEW_PASSWORD';"
  docker exec ganek-migrate-pg psql -U ganek -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP ROLE ganek_mig_tmp;"
  docker rm -f ganek-migrate-pg >/dev/null
  trap - EXIT
  echo "postgres role+db renamed"
fi

if copy_volume "$MINIO_OLD" "$MINIO_NEW"; then
  echo "== renaming minio bucket vetd-cvs -> ganek-cvs in the copy =="
  docker run --rm -v "$MINIO_NEW":/data alpine sh -c '
    if [ -d /data/vetd-cvs ]; then mv /data/vetd-cvs /data/ganek-cvs; fi
    if [ -d /data/.minio.sys/buckets/vetd-cvs ]; then
      mv /data/.minio.sys/buckets/vetd-cvs /data/.minio.sys/buckets/ganek-cvs
    fi'
  echo "minio bucket renamed"
fi

echo "== done — next steps =="
echo "  1. update .env: VETD_* keys -> GANEK_*, bucket vetd-cvs -> ganek-cvs,"
echo "     POSTGRES_PASSWORD to the value used above"
echo "  2. docker compose up -d          # now runs as project 'ganek'"
echo "  3. reattach helpers, e.g.: docker network connect ganek_default vetd-mailpit"
echo "  old volumes kept as backup — remove later with:"
echo "     docker volume rm $PG_OLD $MINIO_OLD"
