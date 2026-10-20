#!/usr/bin/env bash
# End-to-end smoke test against a running Ganek stack (default: compose on localhost).
# Exercises the auth flow through the FRONTEND proxy so cookies + rewrites are covered.
set -euo pipefail

BASE="${1:-http://localhost:3000}"
JAR="$(mktemp)"
BODY="$(mktemp)"
EMAIL="admin@smoke-e2e.dev"
PASSWORD="super-secret-password"

step() { printf -- "--- %s\n" "$1"; }

expect() {
  local want="$1"
  shift
  local got
  got=$(curl -s -o "$BODY" -w "%{http_code}" -b "$JAR" -c "$JAR" "$@")
  if [ "$got" != "$want" ]; then
    echo "FAIL: expected HTTP $want, got $got"
    cat "$BODY"
    exit 1
  fi
}

step "backend health via frontend proxy"
expect 200 "$BASE/api/health"

step "wait for migrations (schema-backed endpoint stops 500ing)"
# /api/health is DB-free, so "stack is up" can beat the migrate container —
# registering into a schemaless database 500s (bit ci_local twice 2026-08-17)
for _ in $(seq 1 40); do
  schema_status=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/v1/public/company")
  case "$schema_status" in
    5*) sleep 3 ;;
    *) break ;;
  esac
done
if [ "${schema_status:-500}" -ge 500 ]; then
  echo "FAIL: schema never became ready (last status $schema_status)"
  exit 1
fi

step "unauthenticated /me is 401"
expect 401 "$BASE/api/v1/auth/me"

step "register first company (single-mode setup)"
expect 201 -X POST -H 'Content-Type: application/json' \
  -d "{\"company_name\":\"Smoke Test Co\",\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" \
  "$BASE/api/v1/auth/register"

step "session cookie from register works"
expect 200 "$BASE/api/v1/auth/me"

step "single mode: second registration is refused"
expect 409 -X POST -H 'Content-Type: application/json' \
  -d '{"company_name":"Another Co","email":"other@smoke-e2e.dev","password":"another-password-123"}' \
  "$BASE/api/v1/auth/register"

step "logout clears the session"
expect 204 -X POST "$BASE/api/v1/auth/logout"
expect 401 "$BASE/api/v1/auth/me"

step "login works and restores the session"
expect 200 -X POST -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" \
  "$BASE/api/v1/auth/login"
expect 200 "$BASE/api/v1/auth/me"

step "every response carries X-Request-ID and an inbound one is honoured"
RID=$(curl -s -o /dev/null -D - "$BASE/api/health" | tr -d '\r' | awk 'tolower($1)=="x-request-id:" {print $2}')
if [ -z "$RID" ]; then
  echo "FAIL: no X-Request-ID response header"; exit 1
fi
ECHOED=$(curl -s -o /dev/null -D - -H 'X-Request-ID: smoke-trace-1' "$BASE/api/health" | tr -d '\r' | awk 'tolower($1)=="x-request-id:" {print $2}')
if [ "$ECHOED" != "smoke-trace-1" ]; then
  echo "FAIL: inbound X-Request-ID not echoed (got '$ECHOED')"; exit 1
fi
COMPOSE="${COMPOSE_CMD:-docker compose}"
if [ -n "$($COMPOSE ps -q backend 2>/dev/null)" ]; then
  sleep 1
  if ! $COMPOSE logs backend --tail 200 2>/dev/null | grep -q "\[smoke-trace-1\] uvicorn.access"; then
    echo "FAIL: backend access log line does not carry the request id"
    $COMPOSE logs backend --tail 20; exit 1
  fi
fi

step "deep health needs a session (the proxy is not loopback to the backend)"
DEEP_ANON=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/health/deep")
if [ "$DEEP_ANON" != "401" ]; then
  echo "FAIL: anonymous deep health returned $DEEP_ANON, expected 401"; exit 1
fi

step "deep health is all green (postgres, redis, s3) and the worker is alive"
expect 200 "$BASE/api/health/deep"
python3 - "$BODY" <<'PY'
import json, sys
body = json.load(open(sys.argv[1]))
assert body["status"] == "ok", body
assert body["failing"] == [], body
assert all(c["ok"] for c in body["checks"].values()), body
assert set(body["checks"]) == {"postgres", "redis", "s3"}, body
assert body["worker"]["seen_at"], "worker heartbeat missing: %r" % body["worker"]
PY

step "admin creates and publishes a job"
expect 201 -X POST -H 'Content-Type: application/json' \
  -d '{"title":"Smoke Test Engineer","location":"Remote","remote_policy":"remote","tags":["python","smoke"],"description_md":"You will **test** things."}' \
  "$BASE/api/v1/jobs"
JOB_ID=$(python3 -c "import json,sys; print(json.load(open('$BODY'))['id'])")
expect 200 -X POST "$BASE/api/v1/jobs/$JOB_ID/publish"

step "published job is on the public API; a draft is not"
expect 201 -X POST -H 'Content-Type: application/json' \
  -d '{"title":"Hidden Draft Role"}' "$BASE/api/v1/jobs"
expect 200 "$BASE/api/v1/public/company"
if ! grep -q "smoke-test-engineer" "$BODY"; then
  echo "FAIL: published job missing from public company page"; cat "$BODY"; exit 1
fi
if grep -q "hidden-draft-role" "$BODY"; then
  echo "FAIL: draft job leaked to public company page"; cat "$BODY"; exit 1
fi

step "SSR careers page renders the company (single mode)"
HOME_HTML=$(curl -fsS "$BASE/")
if ! echo "$HOME_HTML" | grep -q "Smoke Test Co"; then
  echo "FAIL: / did not render the company name (SSR/BACKEND_URL broken?)"
  exit 1
fi

step "SSR careers page lists the published job and its detail page renders"
if ! echo "$HOME_HTML" | grep -q "Smoke Test Engineer"; then
  echo "FAIL: / did not render the published job"; exit 1
fi
if echo "$HOME_HTML" | grep -q "Hidden Draft Role"; then
  echo "FAIL: / rendered a draft job"; exit 1
fi
DETAIL_HTML=$(curl -fsS "$BASE/jobs/smoke-test-engineer")
if ! echo "$DETAIL_HTML" | grep -q "application/ld+json"; then
  echo "FAIL: job detail page missing JobPosting JSON-LD"; exit 1
fi

step "candidate uploads a CV and applies"
expect 200 -X POST "$BASE/api/v1/public/company/jobs/smoke-test-engineer/apply/upload-url"
UPLOAD_URL=$(python3 -c "import json; print(json.load(open('$BODY'))['upload_url'])")
OBJECT_KEY=$(python3 -c "import json; print(json.load(open('$BODY'))['object_key'])")
printf '%%PDF-1.4 smoke cv' > /tmp/smoke-cv.pdf
# presigned POST: policy fields first, the file last (S3 ignores fields after
# it). One "--form-string" + "k=v" pair per line into an array: no eval, so
# base64 policy values and the ";type=" file hint stay literal (bash 3.2 ok).
FORM_ARGS=()
while IFS= read -r line; do FORM_ARGS+=("$line"); done < <(
  python3 -c "import json; t=json.load(open('$BODY')); [print('--form-string') or print(k + '=' + v) for k, v in t['upload_fields'].items()]"
)
if ! curl -fsS "${FORM_ARGS[@]}" -F 'file=@/tmp/smoke-cv.pdf;type=application/pdf' "$UPLOAD_URL" -o /dev/null; then
  echo "FAIL: presigned CV upload failed (is minio's public endpoint reachable?)"; exit 1
fi

step "the bucket refuses a CV above the size cap (policy, not the app)"
head -c 11000000 /dev/zero > /tmp/smoke-huge.pdf
HUGE_CODE=$(curl -s -o /dev/null -w '%{http_code}' "${FORM_ARGS[@]}" -F 'file=@/tmp/smoke-huge.pdf;type=application/pdf' "$UPLOAD_URL")
if [ "$HUGE_CODE" != "400" ]; then
  echo "FAIL: 11 MB upload returned $HUGE_CODE, expected 400 (EntityTooLarge)"; exit 1
fi
expect 201 -X POST -H 'Content-Type: application/json' \
  -d "{\"name\":\"Smoke Candidate\",\"email\":\"candidate@smoke-e2e.dev\",\"cv_object_key\":\"$OBJECT_KEY\",\"cv_filename\":\"cv.pdf\"}" \
  "$BASE/api/v1/public/company/jobs/smoke-test-engineer/apply"

step "duplicate application is refused"
expect 409 -X POST -H 'Content-Type: application/json' \
  -d "{\"name\":\"Smoke Candidate\",\"email\":\"candidate@smoke-e2e.dev\",\"cv_object_key\":\"$OBJECT_KEY\",\"cv_filename\":\"cv.pdf\"}" \
  "$BASE/api/v1/public/company/jobs/smoke-test-engineer/apply"

step "rate limiting kicks in on auth (redis-backed)"
RL_CODE=0
for i in $(seq 1 12); do
  RL_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H 'Content-Type: application/json' \
    -d '{"email":"bruteforce@smoke-e2e.dev","password":"wrong-password-x"}' \
    "$BASE/api/v1/auth/login")
  if [ "$RL_CODE" = "429" ]; then break; fi
done
if [ "$RL_CODE" != "429" ]; then
  echo "FAIL: 12 bad logins never hit the rate limit (last: $RL_CODE)"; exit 1
fi

step "backup, erase, restore: the erased candidate stays erased (tombstones)"
# COMPOSE_CMD as below; CI and the release smoke use the default project
COMPOSE="${COMPOSE_CMD:-docker compose}"
if [ -n "$($COMPOSE ps -q postgres 2>/dev/null)" ]; then
  BK_DIR="$(mktemp -d)"
  COMPOSE_CMD="$COMPOSE" bash scripts/backup.sh "$BK_DIR" >/dev/null
  expect 200 "$BASE/api/v1/applications"
  APP_ID=$(python3 -c "import json,sys; d=json.load(open('$BODY')); items=d if isinstance(d, list) else d['items']; print(items[0]['id'])")
  expect 200 -X POST "$BASE/api/v1/applications/$APP_ID/erase-candidate"
  COMPOSE_CMD="$COMPOSE" bash scripts/restore.sh "$BK_DIR"/ganek-db-*.dump "$BK_DIR"/ganek-cvs-*.tgz >/dev/null
  for _ in $(seq 1 30); do
    curl -fsS -o /dev/null "$BASE/api/health" 2>/dev/null && curl -fsS -o /dev/null -b "$JAR" "$BASE/api/v1/auth/me" 2>/dev/null && break
    sleep 2
  done
  expect 200 "$BASE/api/v1/applications"
  if python3 -c "import json,sys; d=json.load(open('$BODY')); items=d if isinstance(d, list) else d['items']; sys.exit(0 if any(i['id']=='$APP_ID' for i in items) else 1)"; then
    echo "FAIL: the erased application came back after restore"; cat "$BODY"; exit 1
  fi
  rm -rf "$BK_DIR"
else
  echo "(skipped: no compose project reachable from here)"
fi

step "deep health names redis when it is down (503)"
# COMPOSE_CMD lets ci_local point at its -p ganek-e2e project; CI and the
# release smoke run against the default project from the repo root.
COMPOSE="${COMPOSE_CMD:-docker compose}"
if $COMPOSE ps -q redis >/dev/null 2>&1 && [ -n "$($COMPOSE ps -q redis 2>/dev/null)" ]; then
  $COMPOSE stop redis >/dev/null
  expect 503 "$BASE/api/health/deep"
  if ! python3 -c "import json,sys; b=json.load(open(sys.argv[1])); assert b['failing']==['redis'], b" "$BODY"; then
    echo "FAIL: deep health did not single out redis"; cat "$BODY"; $COMPOSE start redis >/dev/null; exit 1
  fi
  $COMPOSE start redis >/dev/null
  for _ in $(seq 1 20); do
    DEEP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -b "$JAR" "$BASE/api/health/deep")
    [ "$DEEP_CODE" = "200" ] && break
    sleep 2
  done
  if [ "$DEEP_CODE" != "200" ]; then
    echo "FAIL: deep health did not recover after redis restart (last: $DEEP_CODE)"; exit 1
  fi

  step "every long-running service reports healthy (compose healthchecks)"
  # six services carry a healthcheck; migrate is a one-shot and has none
  for _ in $(seq 1 40); do
    PS=$($COMPOSE ps --format '{{.Service}} {{.Health}}' 2>/dev/null)
    NOT_YET=$(printf '%s\n' "$PS" | grep -c -E "unhealthy|starting" || true)
    HEALTHY=$(printf '%s\n' "$PS" | grep -c " healthy" || true)
    if [ "$NOT_YET" = 0 ] && [ "$HEALTHY" -ge 6 ]; then break; fi
    sleep 3
  done
  if [ "${NOT_YET:-1}" != 0 ] || [ "${HEALTHY:-0}" -lt 6 ]; then
    echo "FAIL: not every service is healthy:"; printf '%s\n' "$PS"; exit 1
  fi
else
  echo "(skipped: no compose project with a redis service reachable from here)"
fi

echo "e2e smoke: OK"
