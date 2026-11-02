#!/usr/bin/env bash
# ==============================================================================
# BlockSync — One-Command Local Start (macOS & Linux)
# Starts FastAPI backend and Vite frontend concurrently with clean exit handling.
# ==============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

# 1. Resolve Python interpreter
if [[ -f "$REPO_DIR/venv/bin/python" ]]; then
  PYTHON_BIN="$REPO_DIR/venv/bin/python"
elif [[ -f "$REPO_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$REPO_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "Error: Python 3 not found. Please create a virtual environment: python3 -m venv venv" >&2
  exit 1
fi

# 2. Check Node & Frontend dependencies
if ! command -v npm >/dev/null 2>&1; then
  echo "Error: npm not found. Please install Node.js (v18+) to run the frontend." >&2
  exit 1
fi

if [[ ! -d "$REPO_DIR/frontend/node_modules" ]]; then
  echo "==> Installing frontend dependencies..."
  (cd "$REPO_DIR/frontend" && npm install)
fi

# 3. Configure local development environment
export BLOCKSYNC_DEMO_MODE="${BLOCKSYNC_DEMO_MODE:-true}"
if [[ -z "${PYJWT_SECRET:-}" ]]; then
  export PYJWT_SECRET="$("$PYTHON_BIN" -c "import secrets; print(secrets.token_hex(32))")"
fi

echo "================================================================="
echo "  Starting BlockSync Local Environment"
echo "  Backend:  FastAPI  (port 8000, reload enabled)"
echo "  Frontend: Vite     (port 5173)"
echo "  Demo Mode: $BLOCKSYNC_DEMO_MODE"
echo "  Press Ctrl+C to stop all services cleanly."
echo "================================================================="

# 4. Process cleanup trap
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo ""
  echo "==> Shutting down BlockSync services..."
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
  echo "==> All services stopped."
}
trap cleanup INT TERM EXIT

# 5. Launch Backend
"$PYTHON_BIN" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload &
BACKEND_PID=$!

# Wait briefly for backend port
sleep 1

# 6. Launch Frontend
(cd "$REPO_DIR/frontend" && npm run dev) &
FRONTEND_PID=$!

# Wait for both processes
wait
