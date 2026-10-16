#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"

if [[ ! -x backend/.venv/bin/python ]]; then
  echo "缺少后端虚拟环境。请在 backend 目录执行：uv sync --extra dev"
  exit 1
fi

if ! backend/.venv/bin/python -c 'import dotenv; import nemothello.config; import uvicorn' >/dev/null 2>&1; then
  echo "后端依赖尚未就绪。请在 backend 目录执行：uv sync --extra dev"
  exit 1
fi

exec backend/.venv/bin/python scripts/start_local.py "$@"
