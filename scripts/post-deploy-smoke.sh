#!/usr/bin/env bash
# Post-deploy smoke checks — run after Render/Vercel deploy.
set -euo pipefail

API_URL="${API_URL:-https://nuvatra-voice.onrender.com}"
FRONTEND_URL="${FRONTEND_URL:-https://www.call-surge.com}"
CLERK_JWKS_URL="${CLERK_JWKS_URL:-https://clerk.call-surge.com/.well-known/jwks.json}"

echo "== Health: ${API_URL}/api/health"
body="$(curl -sf "${API_URL}/api/health")"
echo "$body" | grep -q '"status"'
echo "$body" | grep -q '"database":"ok"' || echo "WARN: database not ok in health response"

echo "== Frontend: ${FRONTEND_URL}"
curl -sf -o /dev/null -w "HTTP %{http_code}\n" "${FRONTEND_URL}/"

echo "== Clerk JWKS: ${CLERK_JWKS_URL}"
curl -sfI "${CLERK_JWKS_URL}" | head -1 | grep -q "200"

echo "OK — post-deploy smoke passed"
