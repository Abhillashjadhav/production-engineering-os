#!/usr/bin/env bash
# Local built-artifact preview (PD-V3-14): no Docker daemon exists locally, so
# the preview runs the SAME production artifacts as processes — frontend via
# `next build` + `next start`, backend via uvicorn — then executes the full
# browser suite against them and records digest-bound evidence. The
# containerized path (docker-compose.yml) runs in CI where a daemon exists.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PRODUCT="$ROOT/products/pm-evals-web"
PYTHON="${E2E_PYTHON:-$ROOT/.venv/bin/python}"

echo "== building the production frontend =="
(cd "$PRODUCT/frontend" && npx next build)
BUILD_ID="$(cat "$PRODUCT/frontend/.next/BUILD_ID")"

echo "== starting the built artifacts as processes =="
# exec inside the subshells so $! is the SERVER pid, not a wrapper — a
# wrapper-only kill leaves servers alive holding stdout open forever
(cd "$PRODUCT/backend" && PYTHONPATH=src exec "$PYTHON" -m uvicorn pm_evals_api.app:app \
  --host 127.0.0.1 --port 8000) &
BACKEND_PID=$!
(cd "$PRODUCT/frontend" && exec ./node_modules/.bin/next start --hostname 127.0.0.1 --port 3000) &
FRONTEND_PID=$!
stop_servers() {
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap stop_servers EXIT

for _ in $(seq 1 30); do
  curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break
  sleep 1
done
for _ in $(seq 1 30); do
  curl -fsS http://127.0.0.1:3000 >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://127.0.0.1:8000/api/health >/dev/null
curl -fsS http://127.0.0.1:3000 >/dev/null
echo "== preview is up (backend 8000, frontend 3000, BUILD_ID $BUILD_ID) =="

echo "== running the browser suite against the running preview =="
(cd "$PRODUCT/e2e" && E2E_EXTERNAL_SERVERS=1 npx playwright test)

echo "== recording digest-bound preview evidence =="
"$PYTHON" "$PRODUCT/scripts/preview_evidence.py" record \
  --kind local_preview \
  --build-id "$BUILD_ID" \
  --out "$PRODUCT/preview-evidence.json" \
  --journeys a11y=passed keyboard=passed responsive=passed journeys=passed
"$PYTHON" "$PRODUCT/scripts/preview_evidence.py" verify \
  --path "$PRODUCT/preview-evidence.json"
echo "== preview verified =="
