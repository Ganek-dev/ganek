#!/usr/bin/env bash
# End-to-end smoke test against a running Vetd stack (default: compose on localhost).
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
if ! curl -fsS -X PUT -H 'Content-Type: application/pdf' --data-binary @/tmp/smoke-cv.pdf "$UPLOAD_URL" -o /dev/null; then
  echo "FAIL: presigned CV upload failed (is minio's public endpoint reachable?)"; exit 1
fi
expect 201 -X POST -H 'Content-Type: application/json' \
  -d "{\"name\":\"Smoke Candidate\",\"email\":\"candidate@smoke-e2e.dev\",\"cv_object_key\":\"$OBJECT_KEY\",\"cv_filename\":\"cv.pdf\"}" \
  "$BASE/api/v1/public/company/jobs/smoke-test-engineer/apply"

step "duplicate application is refused"
expect 409 -X POST -H 'Content-Type: application/json' \
  -d "{\"name\":\"Smoke Candidate\",\"email\":\"candidate@smoke-e2e.dev\",\"cv_object_key\":\"$OBJECT_KEY\",\"cv_filename\":\"cv.pdf\"}" \
  "$BASE/api/v1/public/company/jobs/smoke-test-engineer/apply"

echo "e2e smoke: OK"
