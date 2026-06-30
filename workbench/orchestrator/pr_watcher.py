"""
Background daemon that polls PR status for tasks in review-needed/.

Detects when a PR referenced by a task in review-needed/ is merged or
closed on GitHub. On merge: moves the task to completed/, deletes the
remote branch, and removes the git worktree. On close (unmerged):
moves the task to blocked/.

Usage:
    from .pr_watcher import PRWatcher

    watcher = PRWatcher(vault_root=..., repo_root=..., interval=120.0)
    watcher.start()
    # ...
    watcher.stop()
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _run_gh(
    args: list[str],
    *,
    repo_full: str,
    token: str = "",
    timeout: int = 30,
) -> Optional[str]:
    """Run a gh CLI command. Returns stdout or None on failure."""
    import subprocess
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token

    full_args = ["gh", "-R", repo_full] + args
    try:
        result = subprocess.run(
            full_args,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.warning(
                "gh command failed: %s\nstderr: %s",
                " ".join(full_args),
                result.stderr.strip(),
            )
            return None
        return result.stdout
    except subprocess.TimeoutExpired:
        logger.warning("gh command timed out: %s", " ".join(full_args))
        return None
    except Exception as e:
        logger.warning("gh command error: %s", e)
        return None


def _run_git(args: list[str], cwd: Path, *, timeout: int = 60, check: bool = True) -> Optional[subprocess.CompletedProcess]:
    """Run a git command."""
    try:
        return subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )
    except Exception:
        return None


def _parse_task_frontmatter(path: Path) -> dict[str, str]:
    """Parse YAML frontmatter from a task markdown file."""
    text = path.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not fm_match:
        return {}
    raw = fm_match.group(1)
    fields: dict[str, str] = {}
    current_key: str | None = None
    current_value: list[str] = []

    def flush():
        nonlocal current_key, current_value
        if current_key is not None:
            fields[current_key] = "\n".join(current_value).strip()
        current_key = None
        current_value = []

    for line in raw.splitlines():
        if line.startswith(" ") or line.startswith("\t"):
            if current_key is not None:
                current_value.append(line)
            continue
        if ":" in line:
            flush()
            key, _, val = line.partition(":")
            current_key = key.strip()
            current_value = [val.strip()]
    flush()
    return fields


def _update_frontmatter_field(path: Path, key: str, value: str) -> None:
    """Update a single YAML frontmatter field in a task file."""
    text = path.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
    if not fm_match:
        return
    fm_body = fm_match.group(1)
    rest = text[fm_match.end():]

    lines = fm_body.splitlines()
    replacement = f"{key}: {value}" if value else f"{key}:"
    updated = False
    for i, line in enumerate(lines):
        if re.match(rf"^{re.escape(key)}:\s*", line):
            lines[i] = replacement
            updated = True
            break
    if not updated:
        lines.append(replacement)

    new_text = f"---\n" + "\n".join(lines) + f"\n---\n" + rest.lstrip("\n")
    path.write_text(new_text, encoding="utf-8")


def _extract_issue_number(url: str) -> Optional[int]:
    """Extract a GitHub issue number from a PR URL."""
    m = re.search(r"/pull/(\d+)", url)
    if m:
        return int(m.group(1))
    return None


class PRWatcher:
    """
    Background daemon that polls PR status for tasks in review-needed/.

    Checks each task that has a pr_url in its frontmatter:
    - If merged → move to completed/, clean up branches and worktree
    - If closed without merge → move to blocked/
    """

    def __init__(
        self,
        vault_root: str | Path,
        repo_root: str | Path,
        *,
        interval: float = 120.0,
        gh_token: str = "",
        repo_full: str = "",
        auto_cleanup: bool = True,
        auto_merge: bool = False,
    ):
        self.vault_root = Path(vault_root).resolve()
        self.repo_root = Path(repo_root).resolve()
        self.interval = interval
        self.gh_token = gh_token or os.environ.get("GITHUB_TOKEN", "")
        self.repo_full = repo_full
        self.auto_cleanup = auto_cleanup
        self.auto_merge = auto_merge
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._check_gh: Optional[bool] = None

    @property
    def review_needed_dir(self) -> Path:
        return self.vault_root / "queue-tasks" / "review-needed"

    @property
    def completed_dir(self) -> Path:
        return self.vault_root / "queue-tasks" / "completed"

    @property
    def blocked_dir(self) -> Path:
        return self.vault_root / "queue-tasks" / "blocked"

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background polling thread."""
        if self._running:
            logger.warning("PRWatcher already running")
            return
        if not self.repo_full:
            logger.warning("PRWatcher: no repo_full configured, skipping")
            return
        if not self._is_gh_available():
            logger.warning("PRWatcher: gh CLI not available, skipping")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="pr-watcher",
        )
        self._thread.start()
        logger.info(
            "PRWatcher started (interval=%.0fs, repo=%s, auto_cleanup=%s)",
            self.interval, self.repo_full, self.auto_cleanup,
        )

    def stop(self) -> None:
        """Stop the background thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.interval + 2)
        logger.info("PRWatcher stopped")

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    # ── Polling loop ──────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        """Background polling loop."""
        while self._running:
            try:
                self._poll_once()
            except Exception:
                logger.exception("PRWatcher poll error")

            deadline = time.time() + self.interval
            while self._running and time.time() < deadline:
                time.sleep(0.5)

    def _poll_once(self) -> None:
        """Check all tasks in review-needed/ for PR status changes."""
        if not self.review_needed_dir.exists():
            return

        for task_file in sorted(self.review_needed_dir.iterdir()):
            if not task_file.is_file() or task_file.suffix != ".md" or task_file.name == "README.md":
                continue

            try:
                fm = _parse_task_frontmatter(task_file)
                pr_url = fm.get("pr_url", "")
                if not pr_url:
                    continue

                pr_number = _extract_issue_number(pr_url)
                if pr_number is None:
                    continue

                self._check_pr_status(task_file, pr_number, fm)
            except Exception as e:
                logger.warning("PRWatcher error checking %s: %s", task_file.name, e)

    def _check_pr_status(self, task_file: Path, pr_number: int, fm: dict) -> None:
        """Check a single PR's status and handle accordingly."""
        result = _run_gh(
            ["pr", "view", str(pr_number), "--json", "state,mergedAt,mergeCommit,closed,isDraft"],
            repo_full=self.repo_full,
            token=self.gh_token,
        )
        if result is None:
            return

        try:
            pr_data = json.loads(result)
        except json.JSONDecodeError:
            logger.warning("Failed to parse PR #%d JSON", pr_number)
            return

        state = pr_data.get("state", "")
        is_merged = pr_data.get("mergedAt") is not None
        is_draft = pr_data.get("isDraft", False)

        if state == "MERGED" or is_merged:
            self._handle_pr_merged(task_file, pr_number, pr_data)
        elif state == "CLOSED":
            self._handle_pr_closed(task_file, pr_number, pr_data)
        elif self.auto_merge and not is_draft:
            # OPEN and not draft — try auto-merge for low-risk tasks
            self._try_auto_merge(task_file, pr_number, pr_data, fm)
        # else: still DRAFT — no action

    # ── Handlers ──────────────────────────────────────────────────────

    def _handle_pr_merged(self, task_file: Path, pr_number: int, pr_data: dict) -> None:
        """Move a merged PR's task to completed/ and clean up."""
        logger.info("PR #%d merged — finalizing task %s", pr_number, task_file.name)

        branch = _parse_task_frontmatter(task_file).get("branch", f"feature/{task_file.stem}")

        # Move to completed/
        self.completed_dir.mkdir(parents=True, exist_ok=True)
        dst = self.completed_dir / task_file.name
        if dst.exists():
            dst.unlink()
        shutil.move(str(task_file), str(dst))
        _update_frontmatter_field(dst, "status", "completed")
        _update_frontmatter_field(dst, "merged_at", pr_data.get("mergedAt", ""))
        _update_frontmatter_field(dst, "pr_closed", "merged")

        logger.info("Task %s moved to completed/ (PR #%d merged)", task_file.name, pr_number)

        # Auto-cleanup: delete remote branch and worktree
        if self.auto_cleanup:
            self._cleanup_task(dst, branch)

    def _handle_pr_closed(self, task_file: Path, pr_number: int, pr_data: dict) -> None:
        """Move a closed (unmerged) PR's task to blocked/."""
        logger.info("PR #%d closed without merge — blocking task %s", pr_number, task_file.name)

        self.blocked_dir.mkdir(parents=True, exist_ok=True)
        dst = self.blocked_dir / task_file.name
        if dst.exists():
            dst.unlink()
        shutil.move(str(task_file), str(dst))
        _update_frontmatter_field(dst, "status", "blocked")
        _update_frontmatter_field(dst, "block_reason", "PR closed without merge")
        _update_frontmatter_field(dst, "blocked_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        _update_frontmatter_field(dst, "pr_closed", "closed")

        logger.info("Task %s moved to blocked/ (PR #%d closed)", task_file.name, pr_number)

    def _cleanup_task(self, task_path: Path, branch: str) -> None:
        """Delete the remote branch and remove the git worktree."""
        # Read worktree path from frontmatter
        fm = _parse_task_frontmatter(task_path)
        worktree_path_str = fm.get("worktree_path", "")

        # Delete remote branch
        if branch:
            result = _run_gh(
                ["api", f"repos/{self.repo_full}/git/refs/heads/{branch}", "--method", "DELETE"],
                repo_full=self.repo_full,
                token=self.gh_token,
            )
            if result is not None:
                logger.info("Deleted remote branch: %s", branch)
            else:
                # Fallback: try git push --delete
                push_result = _run_git(
                    ["push", "origin", "--delete", branch],
                    cwd=self.repo_root, check=False,
                )
                if push_result and push_result.returncode == 0:
                    logger.info("Deleted remote branch via git push: %s", branch)
                else:
                    logger.warning("Could not delete remote branch: %s", branch)

        # Remove git worktree
        if worktree_path_str:
            wt_path = Path(worktree_path_str)
            if wt_path.exists():
                _run_git(["worktree", "remove", str(wt_path)], cwd=self.repo_root, check=False)
                if wt_path.exists():
                    try:
                        shutil.rmtree(str(wt_path))
                    except Exception as e:
                        logger.warning("Failed to remove worktree dir %s: %s", wt_path, e)
                logger.info("Removed worktree: %s", worktree_path_str)

    def _try_auto_merge(self, task_file: Path, pr_number: int, pr_data: dict, fm: dict) -> None:
        """Auto-merge an open PR if the task is low-risk and CI passes."""
        escalation = fm.get("escalation_tier", "").lower()
        task_type = fm.get("type", "").lower()

        # Only auto-merge low-escalation tasks
        low_risk_types = {"docs", "bookkeeping", "scheduled", "vault-discovery"}
        if escalation not in ("", "low") and task_type not in low_risk_types:
            return

        # Check CI status
        result = _run_gh(
            ["pr", "view", str(pr_number), "--json", "statusCheckRollup,mergeStateStatus"],
            repo_full=self.repo_full,
            token=self.gh_token,
        )
        if result is None:
            return

        try:
            check_data = json.loads(result)
        except json.JSONDecodeError:
            return

        # Verify all status checks pass
        rollup = check_data.get("statusCheckRollup", [])
        ci_pass = all(
            c.get("conclusion") == "SUCCESS"
            for c in rollup
            if c.get("status") in ("COMPLETED",)
        )
        if not ci_pass:
            logger.info(
                "PR #%d: cannot auto-merge — CI checks not all passing", pr_number,
            )
            return

        # Enable auto-merge via gh CLI
        merge_result = _run_gh(
            ["pr", "merge", str(pr_number), "--squash", "--auto"],
            repo_full=self.repo_full,
            token=self.gh_token,
        )
        if merge_result is not None:
            logger.info(
                "PR #%d: auto-merge enabled (task=%s, type=%s)",
                pr_number, task_file.name, task_type,
            )
            _update_frontmatter_field(task_file, "auto_merge_enabled", "true")
        else:
            logger.warning(
                "PR #%d: failed to enable auto-merge for task=%s",
                pr_number, task_file.name,
            )

    # ── Helpers ───────────────────────────────────────────────────────

    def _is_gh_available(self) -> bool:
        """Check if gh CLI is available."""
        if self._check_gh is not None:
            return self._check_gh
        import shutil
        self._check_gh = shutil.which("gh") is not None
        if not self._check_gh:
            logger.warning("gh CLI not found. PRWatcher requires 'gh' to be installed.")
        return self._check_gh
