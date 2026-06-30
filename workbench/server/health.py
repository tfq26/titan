"""
Health check script for the workbench worker.

Checks that the worker's heartbeat file is fresh. Designed to be called
from a systemd timer, cron job, or monitoring agent.

Exit codes:
  0 — Worker is alive (heartbeat fresh)
  1 — Heartbeat file missing
  2 — Heartbeat stale (worker likely crashed)
"""
import sys
import time
from pathlib import Path

MAX_AGE_SECONDS = 120  # Allow 4 missed heartbeats (30s interval)


def main() -> int:
    vault_root = Path(__file__).resolve().parent.parent
    heartbeat_path = vault_root / ".worker-heartbeat"

    if not heartbeat_path.exists():
        print("HEALTH: CRITICAL — Heartbeat file missing", file=sys.stderr)
        return 1

    try:
        content = heartbeat_path.read_text(encoding="utf-8").strip()
        last_beat = time.mktime(time.strptime(content, "%Y-%m-%dT%H:%M:%SZ"))
        age = time.time() - last_beat

        if age > MAX_AGE_SECONDS:
            print(
                f"HEALTH: CRITICAL — Heartbeat stale ({age:.0f}s > {MAX_AGE_SECONDS}s max)",
                file=sys.stderr,
            )
            return 2

        print(f"HEALTH: OK — Last heartbeat {age:.0f}s ago")
        return 0

    except (ValueError, OSError) as e:
        print(f"HEALTH: ERROR — Could not read heartbeat: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
