#!/usr/bin/env bash
# Repo Analysis Tool — one-command start.
# Installs backend deps, builds the frontend, then serves everything on one port.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8000}"

# 1. Preflight: if this port is already taken, say so clearly instead of
#    letting uvicorn crash with "address already in use".
if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/api/repos" 2>/dev/null | grep -q '"repos"'; then
  echo "==> Repo Analysis Tool is already running at http://127.0.0.1:$PORT"
  echo "    Open it in your browser, or start a second copy on another port:"
  echo "      PORT=8001 $0"
  exit 0
fi
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$PORT "; then
  echo "==> Port $PORT is already in use by another process (not the RAT server)." >&2
  echo "    Stop that process first, or start on another port:" >&2
  echo "      PORT=8001 $0" >&2
  exit 1
fi

# 2. Python dependencies (fastapi, uvicorn, python-multipart).
if ! python3 -c "import fastapi, uvicorn, multipart" >/dev/null 2>&1; then
  echo "==> Installing backend dependencies"
  python3 -m pip install -r "$ROOT/backend/requirements.txt"
fi

# 3. Frontend build, served by the API (set RAT_REBUILD=1 to force).
if [ ! -f "$ROOT/frontend/dist/index.html" ] || [ "${RAT_REBUILD:-0}" = "1" ]; then
  echo "==> Building frontend"
  (cd "$ROOT/frontend" && npm install --no-audit --no-fund && npm run build)
fi

# 4. Run.
echo "==> Repo Analysis Tool: http://127.0.0.1:$PORT"
cd "$ROOT/backend"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
