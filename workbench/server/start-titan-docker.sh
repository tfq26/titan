#!/usr/bin/env sh
set -eu

SERVER_DIR="/home/taufe/tools/agentOrchestrator"
IMAGE_NAME="titan:latest"

cd "$SERVER_DIR"

./start-temporal.sh

docker build -t "$IMAGE_NAME" .

if [ -f /home/taufe/.workbench-secrets.env ]; then
  # shellcheck disable=SC1090
  . /home/taufe/.workbench-secrets.env
fi

: "${TEMPORAL_WORKER_COMMAND:?set TEMPORAL_WORKER_COMMAND before starting titan}"
: "${TEMPORAL_REVIEWER_COMMAND:?set TEMPORAL_REVIEWER_COMMAND before starting titan}"

exec docker run --rm \
  --name titan \
  --network host \
  -v "$SERVER_DIR:$SERVER_DIR" \
  -w "$SERVER_DIR" \
  -e TEMPORAL_ADDRESS="${TEMPORAL_ADDRESS:-localhost:7233}" \
  -e TEMPORAL_NAMESPACE="${TEMPORAL_NAMESPACE:-default}" \
  -e TEMPORAL_TASK_QUEUE="${TEMPORAL_TASK_QUEUE:-titan-orchestrator}" \
  -e TEMPORAL_WORKFLOW_ID="${TEMPORAL_WORKFLOW_ID:-titan-queue-agentorchestrator}" \
  -e TEMPORAL_WORKER_COMMAND="$TEMPORAL_WORKER_COMMAND" \
  -e TEMPORAL_REVIEWER_COMMAND="$TEMPORAL_REVIEWER_COMMAND" \
  -e TITAN_MODEL_COMMAND="${TITAN_MODEL_COMMAND:-}" \
  "$IMAGE_NAME"
