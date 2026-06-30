#!/bin/bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

SECRETS="$(dirname "$ROOT")/.workbench-secrets.env"
if [ -f "$SECRETS" ]; then
    echo "Loading secrets from $SECRETS"
    set -a
    source "$SECRETS"
    set +a
else
    echo "No secrets file found at $SECRETS (models will show missing env vars)"
fi

if [ ! -d ".venv" ]; then
    echo "Creating Python venv..."
    python3 -m venv .venv
fi

if ! .venv/bin/python3 -c "import yaml" 2>/dev/null; then
    echo "Installing Python dependencies..."
    .venv/bin/pip install -r requirements.txt
fi

if [ ! -d "ui/node_modules" ]; then
    echo "Installing npm dependencies..."
    (cd ui && npm install)
fi

export WORKBENCH_ROOT="$ROOT"

echo "Starting Workbench Console..."
echo "  Workbench root: $ROOT"
echo "  Python:         $(. .venv/bin/activate && which python3)"
echo ""
echo "  First launch compiles the Rust backend — this can take a few minutes."
echo ""

cd ui
npm run tauri dev
