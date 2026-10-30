#!/usr/bin/env bash
# Start the API with the environment loaded. Run from anywhere.
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { echo "No .env found. Copy .env.example to .env first."; exit 1; }
[ -d .venv ] || { echo "No .venv found. Run 'make install' from the project root."; exit 1; }

source .venv/bin/activate
set -a && . ./.env && set +a
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
