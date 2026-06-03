#!/usr/bin/env bash
# Fail if voice/SMS handler or receptionist prompt changed without call-flow doc update.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BASE="${1:-origin/main}"
if ! git rev-parse --verify "$BASE" >/dev/null 2>&1; then
  BASE="HEAD~1"
fi

CODE_CHANGED="$(git diff --name-only "$BASE"...HEAD -- \
  backend/prompts/receptionist.py \
  backend/main.py \
  backend/voice/ 2>/dev/null || true)"

DOC_CHANGED="$(git diff --name-only "$BASE"...HEAD -- docs/call-flow-v1.md 2>/dev/null || true)"

if [ -n "$CODE_CHANGED" ] && [ -z "$DOC_CHANGED" ]; then
  echo "call-flow contract: behavior code changed but docs/call-flow-v1.md was not updated in this diff."
  echo "Changed paths:"
  echo "$CODE_CHANGED"
  exit 1
fi

echo "call-flow contract: OK"
