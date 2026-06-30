#!/usr/bin/env python3
from __future__ import annotations

import os
import sys


def main() -> int:
    role = os.environ.get("TITAN_ROLE", "worker")
    repo_root = os.environ.get("TITAN_REPO_ROOT", "")
    files = os.environ.get("TITAN_FILES", "")
    prompt = sys.stdin.read()

    print(f"[demo-model] role={role}")
    print(f"[demo-model] repo_root={repo_root}")
    print(f"[demo-model] files={files}")
    print()
    print("This is a demo backend. Replace TITAN_MODEL_COMMAND with your real model command.")
    print("Prompt preview:")
    print(prompt[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
