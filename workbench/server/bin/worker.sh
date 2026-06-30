#!/usr/bin/env sh
set -eu

exec "$(dirname "$0")/run-agent.sh" worker
