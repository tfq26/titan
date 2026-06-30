"""
Server-side autonomous worker loop.

Wires the queue watcher, worktree executor, and GitHub Issues sync
into a long-running daemon that processes tasks autonomously.

Usage:
    python3 -m server.run_worker --project ahamkara [--max-workers 2] [--interval 10]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("run_worker")


def _send_webhook(webhook_url: str, payload: dict) -> None:
    """POST a JSON payload to the configured webhook."""
    import urllib.request
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info("Webhook notification sent to %s", webhook_url)
    except Exception as e:
        logger.warning("Webhook notification failed: %s", e)


def main() -> int:
    parser = argparse.ArgumentParser(description="Workbench autonomous worker daemon")
    parser.add_argument(
        "--project", "-p", required=True,
        help="Project ID from projects/registry.yaml",
    )
    parser.add_argument(
        "--interval", type=float, default=10.0,
        help="Queue polling interval in seconds (default: 10)",
    )
    parser.add_argument(
        "--max-workers", type=int, default=1,
        help="Maximum number of tasks to execute concurrently (default: 1)",
    )
    args = parser.parse_args()

    if args.max_workers < 1:
        logger.error("--max-workers must be >= 1")
        return 1

    vault_root = Path(__file__).resolve().parent.parent
    registry_path = vault_root / "projects" / "registry.yaml"
    override_path = vault_root / "projects" / "server-registry.yaml"

    registry_file = override_path if override_path.exists() else registry_path
    if not registry_file.exists():
        logger.error("Registry not found at %s", registry_file)
        return 1

    import yaml
    with open(registry_file) as f:
        registry = yaml.safe_load(f) or {}

    project_config = None
    for proj in registry.get("projects", []):
        if proj["id"] == args.project:
            project_config = proj
            break

    if project_config is None:
        logger.error("Project '%s' not found in %s", args.project, registry_file)
        return 1

    # Resolve paths
    repo_root = Path(project_config["repo_root"]).resolve()
    vault_root_resolved = Path(project_config["vault_root"]).resolve()

    # Load project config for github and notifications
    proj_config_path = vault_root_resolved.parent.parent / "projects" / args.project / "project-config.yaml"
    proj_overrides = {}
    if proj_config_path.exists():
        with open(proj_config_path) as f:
            proj_overrides = yaml.safe_load(f) or {}

    github_config = proj_overrides.get("github", {})
    base_branch = github_config.get("base_branch", "develop")
    sync_issues = github_config.get("sync_issues", False)

    notifications_config = proj_overrides.get("notifications", {})
    blocked_webhook: Optional[str] = notifications_config.get("blocked_webhook", "") or None

    sync_from_issues = github_config.get("sync_from_issues", False)
    issue_task_label = github_config.get("issue_task_label", "task")
    issue_poll_interval = github_config.get("issue_poll_interval", 60.0)

    pr_watch_interval = github_config.get("pr_watch_interval", 120.0)
    auto_cleanup = github_config.get("auto_cleanup", True)
    auto_merge_low_risk = github_config.get("auto_merge_low_risk", False)

    review_webhook: Optional[str] = notifications_config.get("review_webhook", "") or None

    from orchestrator.github_sync import GitHubIssueSource
    from orchestrator.pr_watcher import PRWatcher
    from orchestrator.scheduler import TaskScheduler
    from orchestrator.watcher import QueueWatcher
    from orchestrator.worktree_executor import WorktreeExecutor

    executor = WorktreeExecutor(
        repo_root=repo_root,
        vault_root=vault_root_resolved,
        project_config=proj_overrides,
        base_branch=base_branch,
    )

    # Thread pool for concurrent task execution
    pool = ThreadPoolExecutor(max_workers=args.max_workers)
    logger.info(
        "Using %d worker thread(s) for task execution", args.max_workers,
    )

    # Set up GitHub sync if configured
    github_sync = None
    if sync_issues and github_config.get("repo"):
        from orchestrator.github_sync import GitHubQueueSync
        github_sync = GitHubQueueSync(
            owner=github_config["repo"].split("/")[0],
            repo=github_config["repo"].split("/")[1],
            vault_root=vault_root_resolved,
            label_prefix=github_config.get("label_prefix", ""),
        )
        logger.info("GitHub Issues sync enabled for %s", github_config["repo"])

    watcher = QueueWatcher(vault_root=vault_root_resolved, interval=args.interval)

    # ── Issue source (GitHub Issue → Task) ──────────────────────────

    issue_source: Optional[GitHubIssueSource] = None
    if sync_from_issues and github_sync:
        issue_source = GitHubIssueSource(
            sync=github_sync,
            label=issue_task_label,
            interval=issue_poll_interval,
        )
        issue_source.start()

    # ── Heartbeat (health check) ────────────────────────────────────

    import threading as _thr
    heartbeat_file = vault_root_resolved / ".worker-heartbeat"

    def _heartbeat_loop():
        while True:
            try:
                heartbeat_file.write_text(
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    encoding="utf-8",
                )
            except Exception:
                logger.exception("Heartbeat write failed")
            time.sleep(30)

    heartbeat_thread = _thr.Thread(target=_heartbeat_loop, daemon=True, name="heartbeat")
    heartbeat_thread.start()
    logger.info("Heartbeat started (file=%s, interval=30s)", heartbeat_file)

    # ── Task Scheduler (cron-based recurring tasks) ─────────────────

    task_scheduler: Optional[TaskScheduler] = None
    schedules = proj_overrides.get("schedules", [])
    if schedules:
        task_scheduler = TaskScheduler(
            vault_root=vault_root_resolved,
            schedules=schedules,
            interval=60.0,
            project_id=args.project,
        )
        task_scheduler.start()

    # ── PR Watcher (detect merges, auto-cleanup) ────────────────────

    pr_watcher: Optional[PRWatcher] = None
    if github_config.get("repo"):
        repo_full = github_config["repo"]
        pr_watcher = PRWatcher(
            vault_root=vault_root_resolved,
            repo_root=repo_root,
            interval=pr_watch_interval,
            repo_full=repo_full,
            auto_cleanup=auto_cleanup,
            auto_merge=auto_merge_low_risk,
        )
        pr_watcher.start()

    # ── Wire callbacks ──────────────────────────────────────────────

    def on_task_queued(filename: str) -> None:
        """Submit a task to the thread pool for execution."""
        def _run():
            logger.info("Task queued: %s — starting worktree execution", filename)
            result = executor.execute_task(filename)
            if result.success:
                logger.info(
                    "Task completed: %s branch=%s pr=%s",
                    filename, result.branch, result.pr_url,
                )
            else:
                logger.error("Task failed: %s error=%s", filename, result.error)

        pool.submit(_run)

    def on_task_claimed(filename: str) -> None:
        if github_sync:
            github_sync.on_task_claimed(filename)

    def on_task_completed(filename: str) -> None:
        """Handle task completed: sync to GitHub + send review-ready notification."""
        review_path = vault_root_resolved / "queue-tasks" / "review-needed" / filename
        pr_url = ""
        if review_path.exists():
            from orchestrator.worktree_executor import _parse_task_frontmatter
            fm = _parse_task_frontmatter(review_path)
            pr_url = fm.get("pr_url", "")

        if github_sync:
            github_sync.on_task_completed(filename, pr_url=pr_url)

        # Send review-ready webhook notification
        if review_webhook and pr_url:
            payload = {
                "event": "task_review_ready",
                "project": args.project,
                "task": filename,
                "pr_url": pr_url,
            }
            pool.submit(_send_webhook, review_webhook, payload)
            logger.info(
                "Review-ready webhook queued for task=%s pr=%s",
                filename, pr_url,
            )

    def on_task_finalized(filename: str) -> None:
        if github_sync:
            github_sync.on_task_finalized(filename)

    def on_task_blocked(filename: str) -> None:
        """Handle blocked task: sync to GitHub + send webhook notification."""
        blocked_path = vault_root_resolved / "queue-tasks" / "blocked" / filename
        reason = ""
        if blocked_path.exists():
            from orchestrator.worktree_executor import _parse_task_frontmatter
            fm = _parse_task_frontmatter(blocked_path)
            reason = fm.get("block_reason", "")

        # Loud stderr marker for log monitoring
        print(
            f"!!! BLOCKED !!! task={filename} reason={reason}",
            file=sys.stderr,
        )

        if github_sync:
            github_sync.on_task_blocked(filename, reason=reason)

        if blocked_webhook:
            payload = {
                "event": "task_blocked",
                "project": args.project,
                "task": filename,
                "reason": reason,
                "blocked_at": fm.get("blocked_at", "") if blocked_path.exists() else "",
            }
            pool.submit(_send_webhook, blocked_webhook, payload)

    watcher.on_queued = on_task_queued
    watcher.on_claimed = on_task_claimed
    watcher.on_completed = on_task_completed
    watcher.on_finalized = on_task_finalized
    watcher.on_blocked = on_task_blocked

    # Run startup recovery: crash recovery + vault seeding
    recovery = executor.recover()
    if recovery["recovered_tasks"]:
        logger.info(
            "Recovered %d stale task(s) back to open/",
            recovery["recovered_tasks"],
        )
    if recovery["cleaned_worktrees"]:
        logger.info(
            "Cleaned up %d orphaned worktree(s)",
            recovery["cleaned_worktrees"],
        )
    if recovery["discovery_queued"]:
        logger.info(
            "Auto-queued vault discovery task: %s",
            recovery["discovery_task"],
        )

    logger.info(
        "Starting autonomous worker for project=%s repo=%s",
        args.project, repo_root,
    )

    try:
        watcher.start()
        # Block until interrupted
        while watcher.is_running():
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down worker...")
    finally:
        watcher.stop()
        if task_scheduler:
            task_scheduler.stop()
        if pr_watcher:
            pr_watcher.stop()
        if issue_source:
            issue_source.stop()
        pool.shutdown(wait=True)

    logger.info("Worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
