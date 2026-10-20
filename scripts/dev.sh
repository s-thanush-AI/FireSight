#!/usr/bin/env bash
# FireSight local dev launcher.
#
# Starts the FastAPI backend (default :8000) and the Vite frontend (default
# :5173) together. Ctrl-C stops both. No credentials, datasets or model
# weights are required — the app runs in demo mode with simulated fixtures.
#
# Usage:  ./scripts/dev.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${FIRESIGHT_API_PORT:-8000}"
FRONTEND_PORT="${FIRESIGHT_FRONTEND_PORT:-5173}"

export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  echo "error: 'uv' not found on PATH (install: https://docs.astral.sh/uv/)." >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "error: 'npm' not found on PATH." >&2
  exit 1
fi

if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "==> installing frontend dependencies (first run)"
  (cd "$ROOT/frontend" && npm install)
fi

echo "==> syncing backend environment"
(cd "$ROOT/backend" && uv sync --quiet)
# macOS can mark the editable .pth hidden (UF_HIDDEN); Python 3.11 then skips it
# and every `uv sync` recreates the problem. Clear the flag before launching.
if command -v chflags >/dev/null 2>&1; then
  chflags nohidden "$ROOT/backend/.venv/lib/"python*/site-packages/_editable_impl_firesight.pth 2>/dev/null || true
fi

pids=()
cleanup() {
  echo
  echo "==> stopping FireSight"
  for pid in "${pids[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "==> backend  http://127.0.0.1:${BACKEND_PORT}  (api docs at /docs)"
(cd "$ROOT/backend" && uv run firesight serve --host 127.0.0.1 --port "$BACKEND_PORT") &
pids+=($!)

echo "==> frontend http://127.0.0.1:${FRONTEND_PORT}"
(cd "$ROOT/frontend" && npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT") &
pids+=($!)

echo
echo "FireSight is starting. Open http://127.0.0.1:${FRONTEND_PORT}"
echo "Press Ctrl-C to stop."
wait
