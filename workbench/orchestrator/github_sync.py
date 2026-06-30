"""
GitHub Issues synchronization layer for the workbench queue.

Bidirectionally syncs the file-based task queue with GitHub Issues.
The file queue is the source of truth; issues are a mirror.

Mapping:
  Queue state          →  GitHub Issue state
  ─────────────────────────────────────────────
  open/                →  label: "task", open
  claimed/             →  label: "in-progress", open, assignee
  review-needed/       →  label: "needs-review", open
  completed/           →  closed, label: "completed"
  blocked/             →  label: "blocked", open

Usage:
    from .github_sync import GitHubQueueSync, GitHubIssueSource
    sync = GitHubQueueSync(owner="myorg", repo="myrepo", token="ghp_...")
    sync.on_task_queued("TASK-20260628-0110-collision.md")

    # Optional: poll GitHub Issues to auto-create queue tasks
    source = GitHubIssueSource(sync, label="task", interval=60.0)
    source.start()
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class GitHubQueueSync:
    """
    Syncs file-based queue tasks with GitHub Issues.

    Uses the `gh` CLI for all GitHub operations (lighter dependency than
    PyGithub). Falls back gracefully if gh is not installed or no token
    is configured.
    """

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str = "",
        *,
        vault_root: str | Path,
        label_prefix: str = "",
    ):
        self.owner = owner
        self.repo = repo
        self.repo_full = f"{owner}/{repo}"
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.vault_root = Path(vault_root).resolve()
        self.label_prefix = label_prefix
        self._gh_available: Optional[bool] = None

    # ── Public hooks (called by watcher callbacks) ──────────────────────

    def on_task_queued(self, task_filename: str) -> Optional[int]:
        """
        Call when a task is added to the open/ queue.
        Creates a corresponding GitHub Issue.
        Returns the issue number, or None on failure.
        """
        task_path = self.vault_root / "queue-tasks" / "open" / task_filename
        if not task_path.exists():
            task_path = self.vault_root / "queue-tasks" / "claimed" / task_filename
        if not task_path.exists():
            task_path = self.vault_root / "queue-tasks" / "review-needed" / task_filename
        if not task_path.exists():
            logger.warning("github_sync task not found: %s", task_filename)
            return None

        title = self._build_issue_title(task_path)
        body = self._build_issue_body(task_path)
        labels = self._label("task")

        result = self._gh(
            ["issue", "create", "--title", title, "--label", labels],
            input_text=body,
        )
        if result is None:
            return None

        issue_url = result.strip()
        issue_number = self._extract_issue_number(issue_url)
        if issue_number:
            self._update_task_issue_ref(task_filename, issue_number)
            logger.info("github_sync created issue #%d for task=%s", issue_number, task_filename)
        return issue_number

    def on_task_claimed(self, task_filename: str) -> None:
        """Call when a task is claimed. Updates the issue to in-progress."""
        issue_number = self._task_issue_number(task_filename)
        if issue_number is None:
            return

        self._gh([
            "issue", "edit", str(issue_number),
            "--add-label", self._label("in-progress"),
            "--remove-label", self._label("task"),
        ])

        self._gh([
            "issue", "comment", str(issue_number),
            "--body", "🤖 **Agent claimed this task** — working on implementation in an isolated worktree.",
        ])

        logger.info("github_sync claimed issue #%d for task=%s", issue_number, task_filename)

    def on_task_completed(self, task_filename: str, pr_url: str = "") -> None:
        """Call when a task moves to review-needed. Updates the issue."""
        issue_number = self._task_issue_number(task_filename)
        if issue_number is None:
            return

        body = "🤖 **Agent completed implementation** — ready for review.\n\n"
        if pr_url:
            body += f"📝 **Pull Request**: {pr_url}\n"

        self._gh(["issue", "comment", str(issue_number), "--body", body])
        self._gh([
            "issue", "edit", str(issue_number),
            "--add-label", self._label("needs-review"),
            "--remove-label", self._label("in-progress"),
        ])

        logger.info("github_sync review-needed issue #%d for task=%s", issue_number, task_filename)

    def on_task_finalized(self, task_filename: str) -> None:
        """Call when a task reaches completed/. Closes the issue."""
        issue_number = self._task_issue_number(task_filename)
        if issue_number is None:
            return

        self._gh(["issue", "comment", str(issue_number), "--body", "✅ **Task completed** — closing issue."])
        self._gh(["issue", "close", str(issue_number)])
        self._gh([
            "issue", "edit", str(issue_number),
            "--add-label", self._label("completed"),
        ])

        logger.info("github_sync closed issue #%d for task=%s", issue_number, task_filename)

    def on_task_blocked(self, task_filename: str, reason: str = "") -> None:
        """Call when a task moves to blocked/. Updates the issue."""
        issue_number = self._task_issue_number(task_filename)
        if issue_number is None:
            return

        body = "🚫 **Task blocked**\n\n"
        if reason:
            body += f"Reason: {reason}\n"
        body += "\nBlocked tasks need human intervention to resolve."

        self._gh(["issue", "comment", str(issue_number), "--body", body])
        self._gh([
            "issue", "edit", str(issue_number),
            "--add-label", self._label("blocked"),
            "--remove-label", self._label("in-progress"),
        ])

        logger.info("github_sync blocked issue #%d for task=%s", issue_number, task_filename)

    # ── Issue source (Issue → Task) ──────────────────────────────────────

    def poll_new_issues(self, *, label: str = "task", since_issue: int = 0) -> list[dict]:
        """Fetch open issues with the given label, returning those with number > since_issue."""
        result = self._gh([
            "issue", "list",
            "--label", self._label(label),
            "--state", "open",
            "--json", "number,title,body,createdAt,url",
        ])
        if result is None:
            return []
        try:
            issues = json.loads(result)
        except json.JSONDecodeError:
            logger.warning("Failed to parse gh issue list JSON")
            return []
        issues.sort(key=lambda i: i["number"])
        return [i for i in issues if i["number"] > since_issue]

    def last_imported_issue_number(self) -> int:
        """Return the highest issue number already imported."""
        ref_dir = self.vault_root / "queue-tasks" / ".issue-refs"
        if not ref_dir.exists():
            return 0
        max_n = 0
        for f in ref_dir.iterdir():
            if f.is_file() and f.name.startswith("imported-"):
                try:
                    n = int(f.name.removeprefix("imported-"))
                    if n > max_n:
                        max_n = n
                except ValueError:
                    pass
        return max_n

    def mark_issue_imported(self, issue_number: int) -> None:
        """Record that an issue has been converted to a queue task."""
        ref_dir = self.vault_root / "queue-tasks" / ".issue-refs"
        ref_dir.mkdir(parents=True, exist_ok=True)
        marker = ref_dir / f"imported-{issue_number}"
        marker.write_text("", encoding="utf-8")

    def create_task_from_issue(self, issue: dict) -> Optional[str]:
        """Create a task file in open/ from a GitHub Issue dict.

        Returns the task filename, or None on failure.
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        issue_n = issue["number"]
        title = issue.get("title", "").strip()
        body = issue.get("body", "").strip()

        safe_title = re.sub(r"[^a-zA-Z0-9_-]+", "-", title.lower())[:60]
        safe_title = safe_title.strip("-")
        date_str = now.strftime("%Y%m%d")
        task_filename = f"TASK-{date_str}-gh-{issue_n}-{safe_title}.md"

        open_path = self.vault_root / "queue-tasks" / "open" / task_filename
        if open_path.exists():
            logger.info("Task file already exists for issue #%d: %s", issue_n, task_filename)
            return task_filename

        priority = "medium"
        escalation = "low"
        labels = issue.get("labels", [])
        for lbl in labels:
            lbl_name = lbl.get("name", "").lower() if isinstance(lbl, dict) else str(lbl).lower()
            if "priority-high" in lbl_name or "critical" in lbl_name:
                priority = "high"
                escalation = "high"
            elif "priority-low" in lbl_name or "low-priority" in lbl_name:
                priority = "low"

        task_type = self._determine_task_type(labels, body)

        content = (
            f"---\n"
            f"type: {task_type}\n"
            f"status: open\n"
            f"created: {date_str}\n"
            f"queued_by: github-issue\n"
            f"assigned_to: worker\n"
            f"priority: {priority}\n"
            f"escalation_tier: {escalation}\n"
            f"github_issue: {issue_n}\n"
            f"---\n"
            f"# {title}\n"
            f"\n"
            f"{body}\n"
            f"\n"
            f"---\n"
            f"_Imported from GitHub Issue #{issue_n}_\n"
        )

        open_dir = self.vault_root / "queue-tasks" / "open"
        open_dir.mkdir(parents=True, exist_ok=True)
        open_path.write_text(content, encoding="utf-8")

        self._update_task_issue_ref(task_filename, issue_n)

        logger.info(
            "Created task from GitHub Issue #%d: %s (priority=%s)",
            issue_n, task_filename, priority,
        )
        return task_filename

    def _determine_task_type(self, labels: list, body: str) -> str:
        """Determine task type from labels and body content."""
        label_names = []
        for lbl in labels:
            name = lbl.get("name", "").lower() if isinstance(lbl, dict) else str(lbl).lower()
            label_names.append(name)

        for label in label_names:
            if "bug" in label or "fix" in label:
                return "bugfix"
            if "feature" in label or "enhancement" in label:
                return "feature"
            if "docs" in label or "documentation" in label:
                return "docs"
            if "refactor" in label:
                return "refactor"

        body_lower = body.lower()
        if "bug" in body_lower or "fix" in body_lower:
            return "bugfix"
        if "feature" in body_lower or "new" in body_lower:
            return "feature"
        return "task"

    # ── Helpers ─────────────────────────────────────────────────────────

    def _gh(
        self, args: list[str], *, input_text: str = ""
    ) -> Optional[str]:
        """Run a gh CLI command. Returns stdout or None on failure."""
        if not self._check_gh():
            return None

        import subprocess
        env = os.environ.copy()
        if self.token:
            env["GH_TOKEN"] = self.token

        full_args = ["gh", "-R", self.repo_full] + args
        result = subprocess.run(
            full_args,
            capture_output=True,
            text=True,
            input=input_text,
            env=env,
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning(
                "gh command failed: %s\nstderr: %s",
                " ".join(full_args),
                result.stderr.strip(),
            )
            return None
        return result.stdout

    def _check_gh(self) -> bool:
        """Check if gh CLI is available."""
        if self._gh_available is not None:
            return self._gh_available

        import shutil
        self._gh_available = shutil.which("gh") is not None
        if not self._gh_available:
            logger.warning(
                "gh CLI not found. GitHub Issues sync requires 'gh' to be installed."
            )
        return self._gh_available

    def _label(self, name: str) -> str:
        """Build a label name, optionally prefixed."""
        if self.label_prefix:
            return f"{self.label_prefix}{name}"
        return name

    def _build_issue_title(self, task_path: Path) -> str:
        """Build a descriptive issue title from the task file."""
        content = task_path.read_text(encoding="utf-8")
        fm_match = re.match(r"^---\n.*?\n---\n?", content, re.DOTALL)
        rest = content[fm_match.end():] if fm_match else content

        for line in rest.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") and not stripped.startswith("## Goal") and len(stripped) < 120:
                return stripped.lstrip("#").strip()
            if stripped and not stripped.startswith("#") and len(stripped) > 20:
                return stripped[:100]
        return f"Task: {task_path.stem}"

    def _build_issue_body(self, task_path: Path) -> str:
        """Build the issue body from the full task file content."""
        content = task_path.read_text(encoding="utf-8")
        fm_match = re.match(r"^---\n.*?\n---\n?", content, re.DOTALL)
        body = content[fm_match.end():].strip() if fm_match else content
        return (
            f"{body}\n\n"
            f"---\n"
            f"_Synced from workbench queue: `{task_path.name}`_\n"
        )

    def _extract_issue_number(self, url_or_text: str) -> Optional[int]:
        """Extract issue number from a GitHub URL or text."""
        m = re.search(rf"https://github\.com/{re.escape(self.repo_full)}/issues/(\d+)", url_or_text)
        if m:
            return int(m.group(1))
        m = re.search(r"#(\d+)", url_or_text)
        if m:
            return int(m.group(1))
        return None

    def _task_issue_ref_path(self, task_filename: str) -> Path:
        """Path to store the issue reference for a task."""
        ref_dir = self.vault_root / "queue-tasks" / ".issue-refs"
        ref_dir.mkdir(parents=True, exist_ok=True)
        return ref_dir / f"{task_filename}.issue"

    def _task_issue_number(self, task_filename: str) -> Optional[int]:
        """Read the stored issue number for a task."""
        ref_path = self._task_issue_ref_path(task_filename)
        if not ref_path.exists():
            return None
        try:
            return int(ref_path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return None

    def _update_task_issue_ref(self, task_filename: str, issue_number: int) -> None:
        """Store the issue number reference for a task."""
        ref_path = self._task_issue_ref_path(task_filename)
        ref_path.write_text(str(issue_number), encoding="utf-8")


# ── Issue source runner ──────────────────────────────────────────────


class GitHubIssueSource:
    """
    Background thread that polls GitHub Issues and creates queue tasks.

    Detects new issues labeled with a configurable label (default: "task")
    and converts them to task files in the open/ queue directory.
    """

    def __init__(
        self,
        sync: GitHubQueueSync,
        *,
        label: str = "task",
        interval: float = 60.0,
    ):
        self.sync = sync
        self.label = label
        self.interval = interval
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        """Start the background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="issue-source",
        )
        self._thread.start()
        logger.info(
            "GitHubIssueSource started (label=%s, interval=%.0fs, repo=%s)",
            self.label, self.interval, self.sync.repo_full,
        )

    def stop(self) -> None:
        """Stop the background thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.interval + 2)
        logger.info("GitHubIssueSource stopped")

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def _poll_loop(self) -> None:
        """Background polling loop."""
        while self._running:
            try:
                self._poll_once()
            except Exception:
                logger.exception("GitHubIssueSource poll error")

            deadline = time.time() + self.interval
            while self._running and time.time() < deadline:
                time.sleep(0.5)

    def _poll_once(self) -> None:
        """Single poll: fetch new issues and create tasks."""
        last = self.sync.last_imported_issue_number()
        issues = self.sync.poll_new_issues(label=self.label, since_issue=last)

        if not issues:
            return

        logger.info(
            "Issue source found %d new issue(s) since #%d",
            len(issues), last,
        )

        for issue in issues:
            issue_n = issue["number"]

            ref_dir = self.sync.vault_root / "queue-tasks" / ".issue-refs"
            marker = ref_dir / f"imported-{issue_n}"
            if marker.exists():
                continue

            task_file = self.sync.create_task_from_issue(issue)
            if task_file:
                self.sync.mark_issue_imported(issue_n)
