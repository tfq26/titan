#!/usr/bin/env bash
set -euo pipefail

SERVER_DIR="/home/taufe/tools/agentOrchestrator"
SERVICE_NAME="titan"
SYSTEMD_UNIT="/etc/systemd/system/${SERVICE_NAME}.service"
SECRETS_FILE="/home/taufe/.workbench-secrets.env"
INSTALL_SERVICE=0
ENABLE_SERVICE=0

usage() {
  cat <<USAGE
Usage: $0 [--install-service] [--enable-service]

Prepares the Titan Docker app:
- checks for Docker
- optionally installs the systemd unit
- optionally enables and starts the service
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-service)
      INSTALL_SERVICE=1
      ;;
    --enable-service)
      ENABLE_SERVICE=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

cd "$SERVER_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not on PATH" >&2
  exit 1
fi

if [[ -f "$SECRETS_FILE" ]]; then
  echo "Found shared secrets file: $SECRETS_FILE"
else
  echo "Shared secrets file not found at $SECRETS_FILE"
  echo "Create it before starting the service if your backend commands need secrets."
fi

if [[ "$INSTALL_SERVICE" -eq 1 ]]; then
  sudo install -m 644 "$SERVER_DIR/titan.service" "$SYSTEMD_UNIT"
  sudo systemctl daemon-reload
fi

if [[ "$ENABLE_SERVICE" -eq 1 ]]; then
  sudo systemctl enable --now "$SERVICE_NAME"
  sudo systemctl status "$SERVICE_NAME" --no-pager
fi

echo "Setup complete."
echo "Next steps:"
echo "  1. Export TEMPORAL_WORKER_COMMAND, TEMPORAL_REVIEWER_COMMAND, and TITAN_MODEL_COMMAND in /home/taufe/.workbench-secrets.env"
echo "  2. Start the service with: sudo systemctl enable --now ${SERVICE_NAME}"
