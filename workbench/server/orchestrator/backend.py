from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shlex
import subprocess


@dataclass(frozen=True)
class BackendRunResult:
    returncode: int
    stdout: str
    stderr: str


def run_backend_command(
    command: str,
    *,
    repo_root: Path,
    prompt: str,
    files: list[Path],
) -> BackendRunResult:
    command = command.strip()
    if not command:
        raise RuntimeError("No backend command configured for this Temporal activity")

    cmd = shlex.split(command)
    env = os.environ.copy()
    env["AHAMKARA_REPO_ROOT"] = str(repo_root)
    env["AHAMKARA_PROMPT"] = prompt
    env["AHAMKARA_FILES"] = os.pathsep.join(str(path) for path in files)

    proc = subprocess.run(
        cmd,
        cwd=repo_root,
        text=True,
        capture_output=True,
        input=prompt,
        env=env,
        check=False,
    )
    return BackendRunResult(proc.returncode, proc.stdout, proc.stderr)
