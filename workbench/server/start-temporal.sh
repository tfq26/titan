#!/usr/bin/env sh
set -eu

SERVER_DIR="/home/taufe/tools/agentOrchestrator"
COMPOSE_FILE="$SERVER_DIR/docker-compose.temporal.yml"

cd "$SERVER_DIR"

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "docker compose is not available" >&2
  exit 1
fi

$COMPOSE -f "$COMPOSE_FILE" up -d

for _ in $(seq 1 60); do
  if python3 - <<'PY'
import socket
sock = socket.socket()
sock.settimeout(1)
try:
    sock.connect(("127.0.0.1", 7233))
except OSError:
    raise SystemExit(1)
else:
    raise SystemExit(0)
finally:
    sock.close()
PY
  then
    exit 0
  fi
  sleep 1
done

echo "Temporal did not become ready on 127.0.0.1:7233" >&2
exit 1
