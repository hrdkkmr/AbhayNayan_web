#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -z "${PYTHON_BIN:-}" ]]; then
  VENV="$ROOT/.venv"
  if [[ ! -x "$VENV/bin/python" ]]; then python3 -m venv "$VENV"; fi
  PYTHON_BIN="$VENV/bin/python"
fi
if ! "$PYTHON_BIN" -c 'import fastapi, pytest' >/dev/null 2>&1; then
  "$PYTHON_BIN" -m pip install -r requirements.txt
fi
if ! command -v npm >/dev/null 2>&1; then
  echo 'Node.js/npm is required for web checks.' >&2
  exit 2
fi

"$PYTHON_BIN" -m compileall -q backend tests
"$PYTHON_BIN" -m pip check
"$PYTHON_BIN" -m pytest -q
npm ci --no-audit --no-fund
npm run test:web
npm run test:ui
npm run check:web
