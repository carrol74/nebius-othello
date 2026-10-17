#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"

if [[ ! -x backend/.venv/bin/python ]]; then
  echo "Backend virtual environment is missing. Run in backend/: uv sync --extra dev"
  exit 1
fi

if ! backend/.venv/bin/python -c 'import dotenv; import nemothello.config; import uvicorn' >/dev/null 2>&1; then
  echo "Backend dependencies are missing. Run in backend/: uv sync --extra dev"
  exit 1
fi

exec backend/.venv/bin/python scripts/start_local.py "$@"
