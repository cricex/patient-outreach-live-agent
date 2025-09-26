#!/usr/bin/env bash
# start.sh — bootstrap the FastAPI application for local development
# Requires: bash, uvicorn (Windows) or gunicorn + uvicorn worker (Unix)
# Usage: start.sh (honors ../.env and ../.venv when present)
set -euo pipefail

# Load environment variables from .env file
# shellcheck disable=SC1091
. "$(dirname "$0")/load_env.sh"

# Use Gunicorn on Unix-like platforms; fall back to uvicorn on Windows where
# gunicorn's fcntl dependency is unavailable.
platform=$(uname | tr '[:upper:]' '[:lower:]')

if [[ "$platform" == *"mingw"* || "$platform" == *"msys"* || "$platform" == *"cygwin"* ]]; then
  # Prefer the project local virtual environment explicitly to avoid PATH / activation drift
  VENV_PY="../.venv/Scripts/python.exe"
  if [[ -f "$VENV_PY" ]]; then
    echo "[start.sh] Using venv interpreter $VENV_PY" >&2
    exec "$VENV_PY" -m uvicorn app.main:app \
      --host 0.0.0.0 \
      --port "${WEBSITES_PORT:-8000}"
  else
    echo "[start.sh] WARNING: ../.venv/Scripts/python.exe not found; falling back to global python" >&2
    command -v python >/dev/null 2>&1 || { echo "python not found in PATH" >&2; exit 127; }
    exec python -m uvicorn app.main:app \
      --host 0.0.0.0 \
      --port "${WEBSITES_PORT:-8000}"
  fi
else
  exec gunicorn app.main:app \
    -k uvicorn.workers.UvicornWorker \
    -b 0.0.0.0:${WEBSITES_PORT:-8000} \
    -w 2 \
    --timeout 120 \
    --graceful-timeout 20 \
    --access-logfile - \
    --error-logfile -
fi