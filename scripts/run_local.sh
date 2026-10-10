#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
PYTHON="$VENV/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-python3}"
  "$PYTHON_BIN" -m venv "$VENV"
fi
if ! "$PYTHON" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
  "$PYTHON" -m pip install -r "$ROOT/requirements.txt"
fi

export PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
export ABHAYNAYAN_DB_PATH="${ABHAYNAYAN_DB_PATH:-$ROOT/backend/data/abhaynayan.sqlite3}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
cd "$ROOT"
exec "$PYTHON" -m uvicorn app.main:app --app-dir backend --host "$HOST" --port "$PORT"
