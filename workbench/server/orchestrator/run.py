from __future__ import annotations

from pathlib import Path
import argparse
import asyncio
import os

from .config import OrchestratorConfig
from .temporal_runtime import run_temporal_watch


def load_config(repo_root: Path, args: argparse.Namespace) -> OrchestratorConfig:
    return OrchestratorConfig(
        repo_root=repo_root,
        poll_interval=args.poll_interval,
        temporal_address=os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        temporal_namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
        temporal_task_queue=os.environ.get("TEMPORAL_TASK_QUEUE", "titan-orchestrator"),
        temporal_workflow_id=os.environ.get("TEMPORAL_WORKFLOW_ID", f"titan-queue-{repo_root.name}"),
        worker_command=args.worker_command or os.environ.get("TEMPORAL_WORKER_COMMAND") or None,
        reviewer_command=args.reviewer_command or os.environ.get("TEMPORAL_REVIEWER_COMMAND") or None,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ahamkara Temporal orchestrator")
    parser.add_argument("--repo", default=".", help="repository root")
    parser.add_argument("--watch", action="store_true", help="run the Temporal loop")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--worker-command", default=None)
    parser.add_argument("--reviewer-command", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(args.repo).resolve()
    config = load_config(repo_root, args)

    if not args.watch:
        raise SystemExit("Use --watch to run the Temporal loop.")
    return asyncio.run(run_temporal_watch(config))


if __name__ == "__main__":
    raise SystemExit(main())
