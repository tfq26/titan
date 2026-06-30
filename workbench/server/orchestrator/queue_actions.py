from __future__ import annotations

from pathlib import Path
import sys

from .backend import run_backend_command
from .task_state import (
    QueuePaths,
    current_report_link,
    current_review_link,
    list_tasks,
    move_task,
    resolve_task_reference,
    revision_count,
    set_status,
)


WORKER_PROMPT = """You are the worker for the Ahamkara repo-local queue.

Follow the attached task file as the source of truth.
Work only within the task scope.
If you finish implementation, update the task frontmatter and move it to review-needed.
If you cannot continue, move it to blocked and explain why in the report.
Always write a structured subagent report and append the master log.
Do not invent unrelated work when the queue is empty.
"""


REVIEWER_PROMPT = """You are the reviewer for the Ahamkara repo-local queue.

Read the attached task and linked worker report.
Review the diff and validation evidence against the acceptance bar.
If the work is acceptable, move the task to completed.
If it needs changes, move it back to open and increment revision.
If it is blocked, move it to blocked.
Write the review note in the task file.
"""


def claim_open_task(paths: QueuePaths) -> Path | None:
    tasks = list_tasks(paths.open_dir)
    if not tasks:
        return None
    task_path = tasks[0]
    move_task(task_path, paths.claimed_dir)
    claimed_path = paths.claimed_dir / task_path.name
    from .task_state import set_status

    set_status(claimed_path, "claimed")
    return claimed_path


def process_worker_once(config, paths: QueuePaths) -> bool:
    task_path = claim_open_task(paths)
    if task_path is None:
        return False

    prompt = "\n".join(
        [
            WORKER_PROMPT,
            f"Task file: {task_path}",
            f"Task report link: {current_report_link(task_path) or '(none)'}",
            f"Review link: {current_review_link(task_path) or '(none)'}",
        ]
    )

    result = run_backend_command(
        config.worker_command or "",
        repo_root=config.repo_root,
        files=[task_path],
        prompt=prompt,
    )
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        requeued_path = move_task(task_path, paths.open_dir)
        set_status(requeued_path, "open")
        print(
            f"Worker backend failed for {task_path.name}; moved task back to open.",
            file=sys.stderr,
        )
        return False
    return True


def process_review_once(config, paths: QueuePaths) -> bool:
    tasks = list_tasks(paths.review_needed_dir)
    if not tasks:
        return False
    task_path = tasks[0]
    report_path = resolve_task_reference(task_path, current_report_link(task_path))
    prompt = "\n".join(
        [
            REVIEWER_PROMPT,
            f"Task file: {task_path}",
            f"Worker report: {report_path or '(none)'}",
            f"Revision: {revision_count(task_path)}",
        ]
    )
    files = [task_path]
    if report_path is not None and report_path.exists():
        files.append(report_path)

    result = run_backend_command(
        config.reviewer_command or "",
        repo_root=config.repo_root,
        files=files,
        prompt=prompt,
    )
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode == 0
