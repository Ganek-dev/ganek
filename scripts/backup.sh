#!/usr/bin/env bash
# Ganek backup: a Postgres custom-format dump plus a tarball of the CV
# bucket's data volume, both into one directory. Erasure-aware restore is
# scripts/restore.sh; the policy is docs/compliance/self-hosting-gdpr-guide.md
# ("Backups and erasure").
#
#   scripts/backup.sh [output-dir]          # default ./backups
#   COMPOSE_CMD="docker compose -p other" scripts/backup.sh
#
# Encrypt the output and keep the rotation window at or below your retention
# period: completing the rotation is what completes an erasure for backups.
set -euo pipefail

COMPOSE="${COMPOSE_CMD:-docker compose}"
OUT="${1:-./backups}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT"
OUT_ABS="$(cd "$OUT" && pwd)"

echo "--- database -> $OUT/ganek-db-$TS.dump"
$COMPOSE exec -T postgres pg_dump -U ganek -Fc ganek > "$OUT_ABS/ganek-db-$TS.dump"

# The bucket is a single-node MinIO data directory; a tar of the volume
# restores cleanly into the same MinIO version. Read through a throwaway
# container so the running service is never touched.
VOLUME="$($COMPOSE config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["volumes"]["miniodata"]["name"])')"
echo "--- cv bucket ($VOLUME) -> $OUT/ganek-cvs-$TS.tgz"
docker run --rm -v "$VOLUME:/data:ro" -v "$OUT_ABS:/backup" alpine \
  tar czf "/backup/ganek-cvs-$TS.tgz" -C /data .

echo "backup: $OUT/ganek-db-$TS.dump $OUT/ganek-cvs-$TS.tgz"
