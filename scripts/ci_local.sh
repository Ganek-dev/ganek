#!/usr/bin/env bash
# Mirror the GitHub CI pipeline locally (ci.yml + e2e.yml) so pushes go
# green on the first try. Stages run cheap-first, keep going on failure,
# and end with a summary table:
#
#   questions — question-bank validation
#   audit     — pip-audit + pnpm audit (advisory, like CI's continue-on-error)
#   frontend  — pnpm lint / typecheck / test / build under Node 22 (via nvm)
#   backend   — ruff check/format + mypy + pytest on py3.12 AND py3.14,
#               each leg against fresh throwaway postgres+minio containers
#               (CI-faithful; never touches the dev stack or its data)
#   e2e       — compose smoke + Playwright golden paths on a scratch
#               `-p vetd-e2e` stack with the mandatory volume override;
#               stops a running dev stack first and restores it after
#
# Usage:
#   scripts/ci_local.sh                    # full pipeline
#   scripts/ci_local.sh backend e2e        # just these stages
#   scripts/ci_local.sh --python 3.14 backend
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHONS="3.12 3.14"
NODE_MAJOR=22
VENV_BASE="${VETD_CI_VENVS:-$HOME/.cache/vetd-ci}"
PG_CTR=vetd-ci-postgres
PG_PORT=55433
MINIO_CTR=vetd-ci-minio
MINIO_PORT=9100
E2E_COMPOSE="docker compose --env-file .env.example -p vetd-e2e -f docker-compose.yml -f docker-compose.e2e.yml"

STAGES=""
while [ $# -gt 0 ]; do
  case "$1" in
    --python) PYTHONS="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    questions|audit|frontend|backend|e2e) STAGES="$STAGES $1"; shift ;;
    *) echo "unknown argument: $1 (see --help)"; exit 2 ;;
  esac
done
[ -n "$STAGES" ] || STAGES="questions audit frontend backend e2e"

RESULTS=""
banner() { printf -- "\n=== %s ===\n" "$1"; }
record() { RESULTS="$RESULTS$1=$2\n"; }

# --- cleanup ---------------------------------------------------------------
STOPPED_DEV=0
E2E_UP=0
cleanup() {
  docker rm -f "$PG_CTR" "$MINIO_CTR" >/dev/null 2>&1 || true
  if [ "$E2E_UP" = 1 ]; then $E2E_COMPOSE down -v >/dev/null 2>&1 || true; fi
  if [ "$STOPPED_DEV" = 1 ]; then
    echo "restoring dev stack..."
    docker compose up -d >/dev/null 2>&1 || echo "WARN: could not restart dev stack"
    STOPPED_DEV=0
  fi
}
trap cleanup EXIT INT TERM

# --- helpers ---------------------------------------------------------------
node22_path() {
  # Prepend CI's Node major to PATH via nvm; fall back to system node loudly.
  export NVM_DIR="$HOME/.nvm"
  if [ -s "$NVM_DIR/nvm.sh" ]; then
    # nvm is unbound-variable-unsafe; relax -u while sourcing/using it
    set +u
    . "$NVM_DIR/nvm.sh"
    nvm install "$NODE_MAJOR" >/dev/null 2>&1
    NODE_DIR="$(dirname "$(nvm which "$NODE_MAJOR")")"
    set -u
    export PATH="$NODE_DIR:$PATH"
    export COREPACK_ENABLE_DOWNLOAD_PROMPT=0
    corepack enable >/dev/null 2>&1 || true
  else
    echo "WARN: nvm not found — using system $(node -v); CI runs Node $NODE_MAJOR"
  fi
  echo "using node $(node -v)"
}

wait_stack() {
  local i
  for i in $(seq 1 60); do
    if curl -fsS http://localhost:8000/api/health >/dev/null 2>&1 \
       && curl -fsS -o /dev/null http://localhost:3000 2>/dev/null; then
      echo "stack is up"
      return 0
    fi
    sleep 5
  done
  echo "stack did not become healthy in time"
  $E2E_COMPOSE ps
  $E2E_COMPOSE logs --tail 100
  return 1
}

start_backend_services() {
  docker rm -f "$PG_CTR" "$MINIO_CTR" >/dev/null 2>&1 || true
  docker run -d --rm --name "$PG_CTR" \
    -e POSTGRES_USER=vetd -e POSTGRES_PASSWORD=vetd -e POSTGRES_DB=vetd_test \
    -p "127.0.0.1:$PG_PORT:5432" postgres:16-alpine >/dev/null
  docker run -d --rm --name "$MINIO_CTR" \
    -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin \
    -p "127.0.0.1:$MINIO_PORT:9000" minio/minio:latest server /data >/dev/null
  local i
  for i in $(seq 1 30); do
    if docker exec "$PG_CTR" pg_isready -U vetd >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "throwaway postgres did not become ready"
  return 1
}

# --- stages ----------------------------------------------------------------
stage_questions() {
  (cd backend && uv run --frozen python ../questions/validate.py)
}

stage_audit() {
  # Advisory, mirroring CI's continue-on-error audit job: report, never gate.
  local rc=0
  (
    cd backend \
      && UV_PROJECT_ENVIRONMENT="$VENV_BASE/venv-audit" uv sync --frozen -q \
      && UV_PROJECT_ENVIRONMENT="$VENV_BASE/venv-audit" uv run --frozen --with pip-audit pip-audit
  ) || rc=1
  (
    node22_path
    cd frontend && pnpm audit --audit-level high
  ) || rc=1
  if [ "$rc" = 1 ]; then
    echo "AUDIT: findings above (advisory — CI does not gate on this either)"
    return 42 # distinct code: recorded as ADVISORY, not FAIL
  fi
}

stage_frontend() {
  (
    node22_path
    cd frontend \
      && pnpm install --frozen-lockfile \
      && pnpm lint \
      && pnpm typecheck \
      && pnpm test \
      && pnpm build
  )
}

stage_backend() {
  local py rc=0
  for py in $PYTHONS; do
    banner "backend leg: python $py"
    # fresh services per leg, exactly like CI's per-job postgres/minio
    start_backend_services || return 1
    (
      cd backend
      export UV_PROJECT_ENVIRONMENT="$VENV_BASE/venv-$py"
      export VETD_DATABASE_URL="postgresql+asyncpg://vetd:vetd@localhost:$PG_PORT/vetd_test"
      export VETD_S3_ENDPOINT_URL="http://localhost:$MINIO_PORT"
      export VETD_S3_BUCKET=vetd-cvs-test
      uv sync --python "$py" --frozen -q \
        && uv run --frozen ruff check . \
        && uv run --frozen ruff format --check . \
        && uv run --frozen mypy app \
        && uv run --frozen pytest
    ) || rc=1
    docker rm -f "$PG_CTR" "$MINIO_CTR" >/dev/null 2>&1 || true
    if [ "$rc" = 1 ]; then return 1; fi
  done
  return 0
}

stage_e2e() {
  if [ -n "$(docker compose ps --status running -q 2>/dev/null)" ]; then
    echo "stopping dev stack (will restore afterwards)..."
    docker compose stop >/dev/null 2>&1
    STOPPED_DEV=1
  fi
  E2E_UP=1
  local rc=0
  {
    $E2E_COMPOSE up -d --build \
      && wait_stack \
      && bash scripts/e2e_smoke.sh http://localhost:3000
  } || rc=1
  if [ "$rc" = 0 ]; then
    # browser job runs on its own fresh stack in CI — recreate (images cached)
    banner "e2e: playwright golden paths (fresh stack)"
    {
      $E2E_COMPOSE down -v >/dev/null 2>&1
      $E2E_COMPOSE up -d \
        && wait_stack \
        && (
          node22_path
          cd frontend \
            && pnpm exec playwright install chromium \
            && pnpm e2e
        )
    } || rc=1
  fi
  $E2E_COMPOSE down -v >/dev/null 2>&1 || true
  E2E_UP=0
  if [ "$STOPPED_DEV" = 1 ]; then
    echo "restoring dev stack..."
    docker compose up -d >/dev/null 2>&1 || echo "WARN: could not restart dev stack"
    STOPPED_DEV=0
  fi
  return "$rc"
}

# --- run -------------------------------------------------------------------
OVERALL=0
for s in $STAGES; do
  banner "stage: $s"
  t0=$(date +%s)
  rc=0
  "stage_$s" || rc=$?
  dt=$(( $(date +%s) - t0 ))
  if [ "$rc" = 0 ]; then
    record "$s" "PASS (${dt}s)"
  elif [ "$rc" = 42 ]; then
    record "$s" "ADVISORY (${dt}s)"
  else
    record "$s" "FAIL (${dt}s)"
    OVERALL=1
  fi
done

banner "summary"
printf -- "$RESULTS" | column -t -s '='
[ "$OVERALL" = 0 ] && echo "ci_local: OK" || echo "ci_local: FAILURES above"
exit "$OVERALL"
