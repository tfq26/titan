#!/usr/bin/env bash
set -euo pipefail

SERVER_DIR="/home/taufe/tools/agentOrchestrator"
SECRETS_FILE="/home/taufe/.workbench-secrets.env"

cd "$SERVER_DIR"

if [[ -f "$SECRETS_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$SECRETS_FILE"
fi

if [[ -d "$SERVER_DIR/.venv" ]]; then
  # shellcheck disable=SC1091
  source "$SERVER_DIR/.venv/bin/activate"
fi

: "${TEMPORAL_WORKER_COMMAND:?set TEMPORAL_WORKER_COMMAND before starting titan}"
: "${TEMPORAL_REVIEWER_COMMAND:?set TEMPORAL_REVIEWER_COMMAND before starting titan}"

exec python3 -m orchestrator.run --watch "$@"
