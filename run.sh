#!/usr/bin/env bash
# One-command setup and launch: ./run.sh   (add --no-model to skip the Hugging Face download and run in Cache mode)
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  echo "→ Creating virtual environment"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

stamp=".venv/.requirements.sha"
want="$(shasum requirements.txt | cut -d' ' -f1)"
if [ ! -f "$stamp" ] || [ "$(cat "$stamp")" != "$want" ]; then
  echo "→ Installing Python packages (first run only)"
  pip install -q --upgrade pip
  pip install -q -r requirements.txt
  echo "$want" > "$stamp"
fi

if [ ! -f data/cabi.duckdb ]; then
  echo "→ Generating synthetic SAP-shaped data"
  python -m backend.datagen
fi

if [ "${1:-}" != "--no-model" ]; then
  python scripts/download_model.py || echo "  (model not available: the app will use cached answers)"
fi

echo "→ Starting CABI on http://127.0.0.1:8000"
( sleep 7; command -v open >/dev/null && open "http://127.0.0.1:8000" ) >/dev/null 2>&1 &
exec python -m backend.app
