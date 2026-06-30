#!/usr/bin/env sh
set -eu

ROLE="${1:-}"
if [ -z "$ROLE" ]; then
  echo "Usage: $0 <worker|reviewer>" >&2
  exit 2
fi

shift || true

export TITAN_ROLE="$ROLE"
export TITAN_REPO_ROOT="${AHAMKARA_REPO_ROOT:-$(pwd)}"
export TITAN_PROMPT="${AHAMKARA_PROMPT:-}"
export TITAN_FILES="${AHAMKARA_FILES:-}"

if [ -z "${TITAN_MODEL_COMMAND:-}" ]; then
  echo "TITAN_MODEL_COMMAND is not set." >&2
  echo "Set it to the command that should process the prompt for role: $ROLE" >&2
  echo "Example: export TITAN_MODEL_COMMAND=\"python3 /home/taufe/tools/agentOrchestrator/bin/demo-model.py\"" >&2
  exit 2
fi

exec sh -lc "$TITAN_MODEL_COMMAND" <<EOF
$TITAN_PROMPT
EOF
