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

# Load server-only settings from .env (gitignored). Variables already set in the shell win; values are never printed.
if [[ -f "$ROOT/.env" ]]; then
  while IFS='=' read -r name value; do
    [[ "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ && -n "$value" && -z "${!name:-}" ]] || continue
    value="${value%$'\r'}"; value="${value%\"}"; value="${value#\"}"
    export "$name=$value"
  done < <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "$ROOT/.env")
fi
export PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
export ABHAYNAYAN_DB_PATH="${ABHAYNAYAN_DB_PATH:-$ROOT/backend/data/abhaynayan.sqlite3}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
cd "$ROOT"
exec "$PYTHON" -m uvicorn app.main:app --app-dir backend --host "$HOST" --port "$PORT"
