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

echo "e2e smoke: OK"
