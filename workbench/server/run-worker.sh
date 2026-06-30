#!/usr/bin/env bash
set -euo pipefail

# ── Workbench Worker Daemon ──────────────────────────────────────────
# Runs the queue watcher, worktree executor, and GitHub Issues sync
# as an autonomous server-side agent loop.
#
# Usage:
#   ./server/run-worker.sh --project ahamkara [--interval 10]
#
# Environment:
#   GITHUB_TOKEN       (required for PR creation and issue sync)
#   WORKBENCH_REGISTRY (optional, path to override registry.yaml)
# ──────────────────────────────────────────────────────────────────────

SERVER_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SECRETS_FILE="${SECRETS_FILE:-/home/taufe/.workbench-secrets.env}"
PROJECT=""
POLL_INTERVAL=10.0

usage() {
    cat <<USAGE
Usage: $0 --project <project_id> [--interval <seconds>]

Options:
  --project   Project ID from projects/registry.yaml (required)
  --interval  Queue polling interval in seconds (default: 10)
USAGE
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project) PROJECT="$2"; shift 2 ;;
        --interval) POLL_INTERVAL="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

if [[ -z "$PROJECT" ]]; then
    echo "ERROR: --project is required" >&2
    usage
fi

# ── Load secrets if available ─────────────────────────────────────────
if [[ -f "$SECRETS_FILE" ]]; then
    echo "Loading secrets from $SECRETS_FILE"
    set -a
    # shellcheck source=/dev/null
    source "$SECRETS_FILE"
    set +a
fi

# ── Activate virtualenv ───────────────────────────────────────────────
if [[ -d "$SERVER_DIR/.venv" ]]; then
    # shellcheck disable=SC1091
    source "$SERVER_DIR/.venv/bin/activate"
fi

cd "$SERVER_DIR"

echo "Starting Workbench worker daemon"
echo "  Project:  $PROJECT"
echo "  Interval: ${POLL_INTERVAL}s"
echo "  Server:   $SERVER_DIR"
echo ""

# Start the autonomous worker loop.
# server/run_worker.py handles watcher + executor + GitHub sync integration.
exec python3 -m server.run_worker \
    --project "$PROJECT" \
    --interval "$POLL_INTERVAL"
