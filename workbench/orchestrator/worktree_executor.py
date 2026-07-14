"""
Git worktree executor for autonomous agent task execution.

Creates isolated git worktrees for each queued task, runs an LLM-powered
agent to implement the task inside that worktree, commits the changes,
pushes the branch, and opens a draft PR.

Usage:
    from .worktree_executor import WorktreeExecutor

    executor = WorktreeExecutor(
        repo_root="/path/to/repo",
        vault_root="/path/to/vault",
        project_config={...},
    )
    result = executor.execute_task(task_filename="TASK-...")
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Helpers ─────────────────────────────────────────────────────────────


def _run_git(
    args: list[str],
    cwd: Path,
    *,
    timeout: int = 120,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def _run_gh(
    args: list[str],
    *,
    cwd: Path,
    timeout: int = 60,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a gh CLI command."""
    return subprocess.run(
        ["gh"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


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
    rest = text[fm_match.end() :]

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


# ── WorktreeExecutor ───────────────────────────────────────────────────


class WorktreeExecutionResult:
    """Result of a worktree-based task execution."""

    def __init__(
        self,
        *,
        success: bool,
        branch: str = "",
        pr_url: str = "",
        worktree_path: str = "",
        commit_sha: str = "",
        error: str = "",
        summary: str = "",
    ):
        self.success = success
        self.branch = branch
        self.pr_url = pr_url
        self.worktree_path = worktree_path
        self.commit_sha = commit_sha
        self.error = error
        self.summary = summary


class WorktreeExecutor:
    """
    Executes queued tasks in isolated git worktrees.

    Lifecycle per task:
      1. Create git worktree from base branch
      2. Use LLM to generate implementation
      3. Write files in the worktree
      4. Commit and push to origin
      5. Open draft PR
      6. Move task to review-needed/
      7. Clean up worktree reference

    The executor assumes it's running in a CI/server environment where
    git credentials are available (either via SSH keys or GITHUB_TOKEN).
    """

    def __init__(
        self,
        repo_root: str | Path,
        vault_root: str | Path,
        project_config: dict,
        *,
        base_branch: str = "develop",
        llm_role: str = "worker",
        gh_token: Optional[str] = None,
        hades_url: Optional[str] = None,
    ):
        self.repo_root = Path(repo_root).resolve()
        self.vault_root = Path(vault_root).resolve()
        self.project_config = project_config
        self.base_branch = base_branch
        self.llm_role = llm_role
        self.gh_token = gh_token or os.environ.get("GITHUB_TOKEN", "")
        self.hades_url = hades_url

        self._worktrees_dir = self.repo_root.parent / ".worktrees"

    # ── Public API ──────────────────────────────────────────────────────

    def execute_task(self, task_filename: str) -> WorktreeExecutionResult:
        """
        Execute a single task in an isolated git worktree.

        The task must exist in the open/ queue directory.
        On success, the task is moved to review-needed/ with branch/PR info.
        """
        task_path = self.vault_root / "queue-tasks" / "open" / task_filename
        if not task_path.exists():
            return WorktreeExecutionResult(
                success=False,
                error=f"Task file not found in open/: {task_filename}",
            )

        task_id = _sanitize_id(task_filename.replace(".md", ""))
        branch = f"feature/{task_id}"

        logger.info("worktree_executor starting task=%s branch=%s", task_id, branch)

        try:
            # 1. Claim the task
            claimed_task = self._claim_task(task_path)
            if claimed_task is None:
                return WorktreeExecutionResult(
                    success=False,
                    error=f"Could not claim task: {task_filename}",
                )

            # 2. Create worktree
            worktree_path = self._create_worktree(task_id, branch)
            if worktree_path is None:
                self._move_to_blocked(
                    claimed_task, "Failed to create git worktree"
                )
                return WorktreeExecutionResult(
                    success=False, error="Failed to create git worktree",
                )

            # 3. Generate implementation via LLM
            task_content = claimed_task.read_text(encoding="utf-8")
            impl_result = self._generate_implementation(task_content, worktree_path)

            if not impl_result["success"]:
                self._cleanup_worktree(worktree_path)
                self._move_to_blocked(
                    claimed_task, f"Agent execution failed: {impl_result.get('error', '')}"
                )
                return WorktreeExecutionResult(
                    success=False,
                    error=impl_result.get("error", "Agent execution failed"),
                    worktree_path=str(worktree_path),
                )

            # 4. Commit and push
            commit_result = self._commit_and_push(
                worktree_path, branch, impl_result["summary"]
            )
            if not commit_result["success"]:
                self._cleanup_worktree(worktree_path)
                self._move_to_blocked(
                    claimed_task, f"Git commit/push failed: {commit_result.get('error', '')}"
                )
                return WorktreeExecutionResult(
                    success=False,
                    error=commit_result.get("error", "Git push failed"),
                    worktree_path=str(worktree_path),
                )

            # 5. Open draft PR
            pr_url = self._open_draft_pr(
                worktree_path, task_filename, impl_result["summary"]
            )

            # 6. Update task frontmatter and move to review-needed
            self._update_task_metadata(
                claimed_task, branch, pr_url, str(worktree_path),
                commit_result.get("commit_sha", ""),
            )
            self._move_to_review_needed(claimed_task)

            # 7. Clean up worktree (keep filesystem worktree, remove git record later)
            # Keep the worktree directory for traceability — clean up on merge

            logger.info(
                "worktree_executor completed task=%s branch=%s pr=%s",
                task_id, branch, pr_url,
            )

            return WorktreeExecutionResult(
                success=True,
                branch=branch,
                pr_url=pr_url,
                worktree_path=str(worktree_path),
                commit_sha=commit_result.get("commit_sha", ""),
                summary=impl_result["summary"],
            )

        except Exception as e:
            logger.exception("worktree_executor error for task=%s", task_filename)
            return WorktreeExecutionResult(
                success=False,
                error=str(e),
            )

    # ── Queue operations ────────────────────────────────────────────────

    def _claim_task(self, task_path: Path) -> Optional[Path]:
        """Move a task from open/ to claimed/."""
        claimed_dir = self.vault_root / "queue-tasks" / "claimed"
        claimed_dir.mkdir(parents=True, exist_ok=True)
        dst = claimed_dir / task_path.name
        if dst.exists():
            dst.unlink()
        shutil.move(str(task_path), str(dst))
        _update_frontmatter_field(dst, "status", "claimed")
        _update_frontmatter_field(
            dst, "claimed_at", datetime.now(timezone.utc).isoformat()
        )
        return dst

    def _move_to_review_needed(self, task_path: Path) -> Path:
        """Move a task from claimed/ to review-needed/."""
        review_dir = self.vault_root / "queue-tasks" / "review-needed"
        review_dir.mkdir(parents=True, exist_ok=True)
        dst = review_dir / task_path.name
        if dst.exists():
            dst.unlink()
        shutil.move(str(task_path), str(dst))
        _update_frontmatter_field(dst, "status", "review-needed")
        _update_frontmatter_field(
            dst, "completed_at", datetime.now(timezone.utc).isoformat()
        )
        return dst

    def _move_to_blocked(self, task_path: Path, reason: str) -> Path:
        """Move a task to blocked/ with an error reason."""
        blocked_dir = self.vault_root / "queue-tasks" / "blocked"
        blocked_dir.mkdir(parents=True, exist_ok=True)
        dst = blocked_dir / task_path.name
        if dst.exists():
            dst.unlink()
        shutil.move(str(task_path), str(dst))
        _update_frontmatter_field(dst, "status", "blocked")
        _update_frontmatter_field(dst, "block_reason", reason[:200])
        _update_frontmatter_field(
            dst, "blocked_at", datetime.now(timezone.utc).isoformat()
        )
        return dst

    # ── Git operations ──────────────────────────────────────────────────

    def _create_worktree(self, task_id: str, branch: str) -> Optional[Path]:
        """Create an isolated git worktree for the task."""
        self._worktrees_dir.mkdir(parents=True, exist_ok=True)
        worktree_path = self._worktrees_dir / f"w-{task_id}"

        if worktree_path.exists():
            logger.info("worktree already exists at %s, reusing", worktree_path)
            return worktree_path

        # Create or verify the base branch exists locally
        result = _run_git(
            ["rev-parse", "--verify", f"origin/{self.base_branch}"],
            cwd=self.repo_root,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                "Base branch origin/%s not found, falling back to HEAD",
                self.base_branch,
            )
            base_ref = "HEAD"
        else:
            base_ref = f"origin/{self.base_branch}"

        # Create the worktree
        result = _run_git(
            ["worktree", "add", "-b", branch, str(worktree_path), base_ref],
            cwd=self.repo_root,
            check=False,
        )
        if result.returncode != 0:
            # Branch may already exist from a previous attempt
            result = _run_git(
                ["worktree", "add", str(worktree_path), branch],
                cwd=self.repo_root,
                check=False,
            )
            if result.returncode != 0:
                logger.error(
                    "Failed to create worktree: %s",
                    result.stderr.strip() or result.stdout.strip(),
                )
                return None

        logger.info("created worktree at %s (branch=%s)", worktree_path, branch)
        return worktree_path

    def _commit_and_push(
        self, worktree_path: Path, branch: str, summary: str
    ) -> dict:
        """Commit all changes in the worktree and push to origin."""
        try:
            # Stage all changes
            result = _run_git(
                ["add", "-A"], cwd=worktree_path, check=False,
            )
            if result.returncode != 0:
                return {"success": False, "error": f"git add failed: {result.stderr.strip()}"}

            # Check if there are changes to commit
            result = _run_git(
                ["diff", "--cached", "--quiet"], cwd=worktree_path, check=False,
            )
            if result.returncode == 0:
                return {
                    "success": True,
                    "commit_sha": "",
                    "error": "No changes to commit",
                }

            # Commit
            commit_msg = _build_commit_message(summary, branch)
            result = _run_git(
                ["commit", "-m", commit_msg], cwd=worktree_path, check=False,
            )
            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"git commit failed: {result.stderr.strip()}",
                }

            # Get commit SHA
            sha_result = _run_git(
                ["rev-parse", "HEAD"], cwd=worktree_path, check=False,
            )
            commit_sha = sha_result.stdout.strip() if sha_result.returncode == 0 else ""

            # Configure remote URL with GITHUB_TOKEN if pushing via HTTPS
            if self.gh_token:
                remote_result = _run_git(
                    ["remote", "get-url", "origin"], cwd=worktree_path, check=False,
                )
                if remote_result.returncode == 0:
                    remote_url = remote_result.stdout.strip()
                    if remote_url.startswith("https://"):
                        # Inject token into URL: https://x-access-token:{token}@github.com/...
                        authed_url = re.sub(
                            r"^https://",
                            f"https://x-access-token:{self.gh_token}@",
                            remote_url,
                        )
                        _run_git(
                            ["remote", "set-url", "origin", authed_url],
                            cwd=worktree_path, check=False,
                        )
                        logger.info("Configured git remote with GITHUB_TOKEN auth")

            # Push
            push_result = _run_git(
                ["push", "-u", "origin", branch], cwd=worktree_path,
                timeout=300, check=False,
            )
            if push_result.returncode != 0:
                return {
                    "success": False,
                    "error": f"git push failed: {push_result.stderr.strip()}",
                    "commit_sha": commit_sha,
                }

            return {"success": True, "commit_sha": commit_sha, "error": ""}

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Git operation timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _open_draft_pr(
        self, worktree_path: Path, task_filename: str, summary: str
    ) -> str:
        """Open a draft PR via the gh CLI."""
        if not self.gh_token:
            logger.warning("No GITHUB_TOKEN set, skipping PR creation")
            return ""

        title = f"[{task_filename}] {summary[:72]}" if summary else f"Task: {task_filename}"
        body = self._build_pr_body(task_filename, summary)

        result = _run_gh(
            [
                "pr", "create",
                "--draft",
                "--title", title,
                "--body", body,
                "--base", self.base_branch,
            ],
            cwd=worktree_path,
            check=False,
        )
        if result.returncode != 0:
            logger.warning("gh pr create failed: %s", result.stderr.strip())
            return ""
        return result.stdout.strip()

    # ── Vault seeding ────────────────────────────────────────────────────

    def needs_seeding(self) -> bool:
        """Check if the project vault is missing essential docs.

        Returns True if the vault root exists but has no repo map and no
        content in features/, systems/, or memory/ directories.
        """
        if not self.vault_root or not self.vault_root.exists():
            return True  # Vault doesn't exist yet

        # Check for repo map or any top-level seed docs
        for f in self.vault_root.iterdir():
            if f.is_file() and f.suffix == ".md":
                if f.name.startswith("00-") or f.name.startswith("01-") or f.name == "README.md":
                    return False

        # Check content directories
        for subdir_name in ("features", "systems", "memory"):
            subdir = self.vault_root / subdir_name
            if subdir.is_dir():
                try:
                    if any(f.suffix == ".md" for f in subdir.iterdir()):
                        return False
                except (PermissionError, OSError):
                    pass

        return True

    def ensure_vault_seeded(self) -> Optional[str]:
        """Auto-queue a vault discovery task if the vault needs seeding.

        Creates a discovery task in open/ that tells the LLM to explore
        the project and write vault documentation (repo map, system docs).

        Returns the task filename if a new task was created, None otherwise.
        """
        if not self.needs_seeding():
            return None

        open_dir = self.vault_root / "queue-tasks" / "open"
        open_dir.mkdir(parents=True, exist_ok=True)

        # Check if a discovery task already exists
        for f in open_dir.iterdir():
            if f.is_file() and f.suffix == ".md" and "discovery" in f.name.lower():
                logger.info("Discovery task already queued: %s", f.name)
                return None

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y%m%d")
        task_filename = f"TASK-{date_str}-vault-discovery.md"
        task_path = open_dir / task_filename

        content = (
            f"---\n"
            f"type: vault-discovery\n"
            f"status: open\n"
            f"created: {date_str}\n"
            f"queued_by: system\n"
            f"assigned_to: worker\n"
            f"priority: high\n"
            f"escalation_tier: low\n"
            f"---\n"
            f"# TASK-{date_str}-vault-discovery\n"
            f"\n"
            f"## Goal\n"
            f"\n"
            f"Explore the project repository and produce vault documentation: "
            f"a repo map describing the project structure, key files, "
            f"architecture, conventions, and subsystems.\n"
            f"\n"
            f"## Scope\n"
            f"\n"
            f"In bounds:\n"
            f"- Read the project's source tree, config files, and dependencies\n"
            f"- Create `docs/vault/01-repo-map.md` with the project overview\n"
            f"- Create subdirectories `docs/vault/features/`, `docs/vault/systems/`, `docs/vault/memory/`\n"
            f"\n"
            f"Out of bounds:\n"
            f"- No code changes outside the vault\n"
            f"- No feature implementation\n"
            f"\n"
            f"## Acceptance Criteria\n"
            f"\n"
            f"- [ ] `docs/vault/01-repo-map.md` exists with project structure, stack, and conventions\n"
            f"- [ ] Vault subdirectories exist (features/, systems/, memory/)\n"
            f"- [ ] No source code was modified\n"
        )
        task_path.write_text(content, encoding="utf-8")
        logger.info("Auto-queued vault discovery task: %s", task_filename)
        return task_filename

    # ── Crash recovery ────────────────────────────────────────────────────

    def recover_stale_tasks(self) -> int:
        """Scan claimed/ for stale tasks and move them back to open/.

        A task is stale if:
        - It has a worktree_path in frontmatter but that path no longer exists
        - It has no worktree_path and was claimed >5 minutes ago
          (process likely died before creating the worktree)

        Returns the number of recovered tasks.
        """
        claimed_dir = self.vault_root / "queue-tasks" / "claimed"
        if not claimed_dir.exists():
            return 0

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        cutoff_seconds = 300  # 5 minutes
        recovered = 0

        for task_file in sorted(claimed_dir.iterdir()):
            if not task_file.is_file() or task_file.suffix != ".md":
                continue

            try:
                fm = _parse_task_frontmatter(task_file)
                worktree_path_str = fm.get("worktree_path", "")
                claimed_at_str = fm.get("claimed_at", "")

                stale = False

                if worktree_path_str:
                    # Has a worktree_path — check if it still exists
                    wt_path = Path(worktree_path_str)
                    if not wt_path.exists():
                        stale = True
                        logger.info(
                            "Stale claimed task %s: worktree %s missing",
                            task_file.name, worktree_path_str,
                        )
                elif claimed_at_str:
                    # No worktree_path — check age
                    try:
                        claimed_dt = datetime.fromisoformat(claimed_at_str)
                        age = (now - claimed_dt).total_seconds()
                        if age > cutoff_seconds:
                            stale = True
                            logger.info(
                                "Stale claimed task %s: claimed %.0fs ago, no worktree created",
                                task_file.name, age,
                            )
                    except ValueError:
                        # Can't parse timestamp — treat as stale
                        stale = True
                else:
                    # No worktree_path and no claimed_at — definitely stale
                    stale = True
                    logger.info(
                        "Stale claimed task %s: no worktree_path or claimed_at",
                        task_file.name,
                    )

                if stale:
                    self._move_to_open(task_file)
                    recovered += 1

            except Exception as e:
                logger.warning("Failed to check task %s: %s", task_file.name, e)

        if recovered:
            logger.info("Recovered %d stale task(s) back to open/ queue", recovered)
        else:
            logger.info("No stale tasks found in claimed/")
        return recovered

    def cleanup_orphaned_worktrees(self) -> int:
        """Scan .worktrees/ for orphaned directories and remove them.

        A worktree directory is orphaned if no claimed task references it.

        Returns the number of cleaned-up directories.
        """
        if not self._worktrees_dir.exists():
            return 0

        # Collect all worktree paths still referenced in claimed/
        claimed_dir = self.vault_root / "queue-tasks" / "claimed"
        active_paths: set[str] = set()
        if claimed_dir.exists():
            for task_file in claimed_dir.iterdir():
                if task_file.is_file() and task_file.suffix == ".md":
                    fm = _parse_task_frontmatter(task_file)
                    wt = fm.get("worktree_path", "")
                    if wt:
                        active_paths.add(str(Path(wt).resolve()))

        cleaned = 0
        for entry in list(self._worktrees_dir.iterdir()):
            if not entry.is_dir():
                continue
            resolved = str(entry.resolve())
            if resolved not in active_paths:
                logger.info("Removing orphaned worktree: %s", entry.name)
                try:
                    _run_git(["worktree", "remove", resolved], cwd=self.repo_root, check=False)
                    if entry.exists():
                        shutil.rmtree(resolved)
                    cleaned += 1
                except Exception as e:
                    logger.warning("Failed to remove worktree %s: %s", entry.name, e)

        if cleaned:
            logger.info("Cleaned up %d orphaned worktree(s)", cleaned)
        else:
            logger.info("No orphaned worktrees found")
        return cleaned

    def recover(self) -> dict:
        """Run all recovery operations on startup.

        Returns a dict with counts of recovered tasks, cleaned worktrees,
        and whether a discovery task was queued.
        """
        recovered_tasks = self.recover_stale_tasks()
        cleaned_worktrees = self.cleanup_orphaned_worktrees()
        discovery_task = self.ensure_vault_seeded()

        result = {
            "recovered_tasks": recovered_tasks,
            "cleaned_worktrees": cleaned_worktrees,
            "discovery_queued": discovery_task is not None,
            "discovery_task": discovery_task or "",
        }
        logger.info("Recovery complete: %s", result)
        return result

    def _move_to_open(self, task_path: Path) -> Path:
        """Move a task back to open/ from any other state."""
        open_dir = self.vault_root / "queue-tasks" / "open"
        open_dir.mkdir(parents=True, exist_ok=True)
        dst = open_dir / task_path.name
        if dst.exists():
            dst.unlink()
        shutil.move(str(task_path), str(dst))
        _update_frontmatter_field(dst, "status", "open")
        _update_frontmatter_field(dst, "recovered_at", datetime.now(timezone.utc).isoformat())
        logger.info("Moved task back to open/: %s", task_path.name)
        return dst

    # ── LLM / Hades integration ────────────────────────────────────────

    def _generate_implementation(
        self, task_content: str, worktree_path: Path
    ) -> dict:
        """Call the LLM to generate code, write files, and validate.

        Retry loop:
          1. Call LLM/Hades to generate code (with previous error context on retries)
          2. Write files from the response (LLM path only — Hades writes its own)
          3. Run validation  (build/test commands from project config)
          4. If validation passes → run AI review
          5. If review passes → return success
          6. If validation or review fails and retries remain → feed error back
          7. After max retries → return failed with last error

        When self.hades_url is set, delegates to Hades' CoderAgent (Rust)
        instead of calling the LLM directly. Hades handles exploration, planning,
        code generation, file writing, and its own test validation internally.

        The direct LLM path expects code blocks in the format:
        ```language path=relative/file/path.ext
        ...code...
        ```
        """
        try:
            from .llm_client import call_llm_text
            from .model_policy import ModelPolicyError
            from .cost_tracker import CostTracker, BudgetExceededError

            project_id = self.project_config.get("id", self.project_config.get("project_id", ""))
            model_policy = self.project_config.get("model_policy", {})

            # Cost tracking for this task
            cost_tracker = CostTracker(self.vault_root)
            task_filename = str(worktree_path).rsplit("/", 1)[-1].replace("w-", "")
            cost_tracker.set_task_id(task_filename)

            # Load vault context once per task
            vault_context = self._load_vault_context()

            # ── Hades path ───────────────────────────────────────────────
            if self.hades_url:
                return self._generate_implementation_with_hades(
                    task_content=task_content,
                    worktree_path=worktree_path,
                    cost_tracker=cost_tracker,
                )

            # ── Direct LLM path ──────────────────────────────────────────
            # Explore once
            explore_result = self._explore_project(worktree_path, vault_context, cost_tracker)
            logger.info("LLM exploration: %s", explore_result[:300])

            max_attempts = 3
            last_error = ""

            for attempt in range(1, max_attempts + 1):
                logger.info("Implementation attempt %d/%d", attempt, max_attempts)

                result = self._call_llm_for_implementation(
                    task_content=task_content,
                    worktree_path=worktree_path,
                    project_overview=explore_result[:500],
                    vault_context=vault_context,
                    prev_error=last_error,
                    project_id=project_id,
                    model_policy=model_policy,
                    cost_tracker=cost_tracker,
                )

                # Handle LLM-level failures
                if not result.get("llm_ok", False):
                    return {
                        "success": False,
                        "summary": result.get("summary", ""),
                        "error": result.get("error", "LLM call failed"),
                        "raw": result.get("raw", ""),
                        "written_files": [],
                    }

                raw_output = result["raw"]

                # Write files
                written_files = self._write_files_from_output(raw_output, worktree_path)
                summary = _extract_post_block_summary(raw_output) or "Task implementation"

                # Check if LLM reported blocked
                if _detect_blocked(raw_output):
                    logger.warning("LLM reported task as blocked")
                    return {
                        "success": False,
                        "summary": summary,
                        "error": "LLM reported task cannot be completed: " + summary,
                        "raw": raw_output,
                        "written_files": written_files,
                    }

                # Check if files were written
                if not written_files:
                    logger.warning("LLM returned no parseable file blocks")
                    return {
                        "success": False,
                        "summary": summary,
                        "error": "LLM did not produce any file output — implementation could not be written",
                        "raw": raw_output,
                        "written_files": written_files,
                    }

                # Run validation
                validation = self._run_validation(worktree_path)
                if validation["success"]:
                    logger.info("Validation passed on attempt %d/%d", attempt, max_attempts)
                    # Run AI code review
                    review = self._run_ai_review(task_content, worktree_path, cost_tracker)
                    if review["passed"]:
                        logger.info("AI review passed on attempt %d/%d", attempt, max_attempts)
                        if review["notes"]:
                            summary = summary + "\n\n### Review Notes\n\n" + review["notes"]
                        return {
                            "success": True,
                            "summary": summary,
                            "raw": raw_output,
                            "error": "",
                            "written_files": written_files,
                        }
                    # Review found issues — feed into retry loop
                    last_error = f"AI Review FAILED:\n{review['issues']}"
                    logger.warning(
                        "AI review failed on attempt %d/%d: %.200s",
                        attempt, max_attempts, last_error,
                    )
                    if attempt < max_attempts:
                        _run_git(["checkout", "--", "."], cwd=worktree_path, check=False)
                        _run_git(["clean", "-fd"], cwd=worktree_path, check=False)
                    continue

                # Validation failed — retry with error context
                last_error = validation["output"]
                logger.warning(
                    "Validation failed on attempt %d/%d: %.200s",
                    attempt, max_attempts, last_error,
                )

                if attempt < max_attempts:
                    # Revert files so the next attempt starts clean
                    _run_git(["checkout", "--", "."], cwd=worktree_path, check=False)
                    # Clean untracked files the LLM may have created
                    _run_git(["clean", "-fd"], cwd=worktree_path, check=False)

            # Out of retries
            logger.error("All %d attempts failed — last validation error: %.200s", max_attempts, last_error)
            return {
                "success": False,
                "summary": summary,
                "error": f"Validation failed after {max_attempts} attempts: {last_error[:500]}",
                "raw": raw_output,
                "written_files": written_files,
            }

        except ModelPolicyError as e:
            logger.error("Model policy denied: %s", e)
            return {"success": False, "error": f"Model policy denied: {e}", "summary": ""}
        except BudgetExceededError as e:
            logger.error("Budget exceeded: %s", e)
            return {"success": False, "error": str(e), "summary": ""}
        except Exception as e:
            logger.exception("Implementation execution failed")
            return {"success": False, "error": str(e), "summary": ""}
        finally:
            total_cost = cost_tracker.get_total_cost() if 'cost_tracker' in dir() else 0
            if total_cost > 0:
                logger.info("Cost summary for %s:\n%s", cost_tracker._task_id, cost_tracker.summary())

    def _generate_implementation_with_hades(
        self,
        task_content: str,
        worktree_path: Path,
        cost_tracker,
    ) -> dict:
        """Delegate implementation to Hades' CoderAgent.

        Hades handles exploration, planning, code generation, file writing,
        and its own test validation internally (with up to 3 retries).
        Workbench then runs its own validation (build/test) and AI review
        as a safety net on top of what Hades produced.
        """
        from .hades_client import HadesClient, HadesError
        from .cost_tracker import BudgetExceededError

        try:
            logger.info("Delegating implementation to Hades at %s", self.hades_url)

            client = HadesClient(self.hades_url)
            result = client.execute_task(
                task=task_content,
                worktree_path=str(worktree_path),
            )

            if not result.get("success"):
                logger.error("Hades task execution failed: %s", result.get("summary", ""))
                return {
                    "success": False,
                    "summary": result.get("summary", ""),
                    "error": f"Hades agent failed: {result.get('summary', 'unknown error')}",
                    "raw": "",
                    "written_files": [],
                }

            summary = result.get("summary", "Task implementation (via Hades)")
            actions = result.get("actions_taken", [])
            files_count = len([a for a in actions if a.get("action_type") == "write_file"])
            logger.info(
                "Hades succeeded: %s (%d file mutations)",
                summary[:100], files_count,
            )

            # Run Workbench's validation (build/test commands from project config)
            validation = self._run_validation(worktree_path)
            if not validation["success"]:
                logger.warning(
                    "Workbench validation failed after Hades success: %.200s",
                    validation["output"],
                )
                return {
                    "success": False,
                    "summary": summary,
                    "error": f"Validation failed after Hades implementation: {validation['output'][:500]}",
                    "raw": "",
                    "written_files": [a.get("target", "") for a in actions],
                }

            logger.info("Workbench validation passed for Hades-generated changes")

            # Run AI review
            review = self._run_ai_review(task_content, worktree_path, cost_tracker)
            if not review["passed"]:
                logger.warning(
                    "AI review failed after Hades implementation: %.200s",
                    review.get("issues", ""),
                )
                return {
                    "success": False,
                    "summary": summary,
                    "error": f"AI review failed after Hades implementation: {review['issues'][:500]}",
                    "raw": "",
                    "written_files": [a.get("target", "") for a in actions],
                }

            logger.info("AI review passed for Hades-generated changes")
            return {
                "success": True,
                "summary": summary,
                "raw": "",
                "error": "",
                "written_files": [a.get("target", "") for a in actions],
            }

        except HadesError as e:
            logger.error("Hades API error: %s", e)
            return {"success": False, "error": str(e), "summary": ""}
        except BudgetExceededError:
            raise
        except Exception as e:
            logger.exception("Hades execution failed")
            return {"success": False, "error": str(e), "summary": ""}

    def _explore_project(self, worktree_path: Path, vault_context: str,
                         cost_tracker=None) -> str:
        """Ask the LLM to explore the project structure once."""
        from .llm_client import call_llm_text
        from .cost_tracker import BudgetExceededError
        project_id = self.project_config.get("id", self.project_config.get("project_id", ""))
        vault_section = (
            f"\n\n## Vault Documentation\n\n{vault_context}\n\n"
            if vault_context else ""
        )
        explore_prompt = (
            f"## Working Directory\n\n{worktree_path}\n\n"
            f"First, explore this project. List what you find — what language, framework, "
            f"directory structure, and existing patterns you see. Keep it brief (3-5 lines)."
            f"{vault_section}"
        )

        token_usage = {}
        result = call_llm_text(
            role=self.llm_role,
            system_prompt="You are exploring a codebase before implementing a task. Be brief.",
            user_prompt=explore_prompt,
            project_policy=None,
            project_id=project_id,
            token_usage=token_usage,
        )

        if cost_tracker is not None and token_usage:
            cost_tracker.record(self.llm_role, token_usage)
            cost_tracker.check_budget(self.llm_role)

        return result

    def _load_vault_context(self) -> str:
        """Read vault documentation and return as a structured context block.

        Reads top-level *.md docs and configured subdirectories (features/,
        systems/, memory/) from the vault root. Excludes operational dirs
        (queue-tasks, machine, templates, skills, workflows, control, team).

        Returns an empty string if no vault docs exist or no vault_root is set.
        """
        if not self.vault_root or not self.vault_root.exists():
            return ""

        vault_cfg = self.project_config.get("vault", {})
        # Directories to scan for documentation content
        content_dirs = ["features", "systems", "memory"]
        # Also pull dirs explicitly listed in vault config under common keys
        for key in ("features", "systems", "memory"):
            val = vault_cfg.get(key)
            if val and val not in content_dirs:
                content_dirs.append(val)

        docs: list[tuple[str, str]] = []  # (source_label, content)
        seen = 0
        max_files = 15
        max_total_chars = 4000

        # Top-level docs
        try:
            for f in sorted(self.vault_root.iterdir()):
                if f.is_file() and f.suffix == ".md" and seen < max_files:
                    if f.name in ("README.md",) or f.name.startswith("00-"):
                        docs.append((f.name, f.read_text(encoding="utf-8")[:800]))
                        seen += 1
        except PermissionError:
            pass

        # Content subdirectories
        for subdir_name in content_dirs:
            subdir = self.vault_root / subdir_name
            if not subdir.is_dir():
                continue
            try:
                for f in sorted(subdir.iterdir()):
                    if f.is_file() and f.suffix == ".md" and seen < max_files:
                        rel = f"{subdir_name}/{f.name}"
                        docs.append((rel, f.read_text(encoding="utf-8")[:800]))
                        seen += 1
            except PermissionError:
                pass

        if not docs:
            return ""

        parts: list[str] = []
        total = 0
        for label, content in docs:
            block = f"### {label}\n\n{content.strip()}\n"
            total += len(block)
            if total > max_total_chars and parts:
                parts.append("*(remaining vault docs truncated)*")
                break
            parts.append(block)

        result = "\n".join(parts)
        logger.info("Loaded vault context: %d docs, %d chars", len(docs), len(result))
        return result

    def _call_llm_for_implementation(
        self,
        task_content: str,
        worktree_path: Path,
        project_overview: str,
        vault_context: str,
        prev_error: str,
        project_id: str,
        model_policy: dict,
        cost_tracker=None,
    ) -> dict:
        """Call the LLM to generate implementation code.

        On retry (prev_error is non-empty), appends the validation error
        so the LLM can fix the issues.
        """
        from .llm_client import call_llm_text

        fix_guide = ""
        if prev_error:
            fix_guide = (
                f"\n\n## Previous attempt validation errors\n\n"
                f"The previous attempt failed validation with these errors:\n"
                f"```\n{prev_error[:1500]}\n```\n\n"
                f"Please fix the issues above and re-output ALL modified files completely. "
                f"Do not just describe the fix — output the corrected file contents."
            )

        vault_section = (
            f"\n\n## Vault Documentation\n\n{vault_context}\n\n"
            if vault_context else ""
        )

        system_prompt = (
            "You are a senior software engineer implementing a task.\n"
            "The task file describes the goal, scope, and acceptance criteria.\n"
            "The working directory is an isolated git worktree cloned from the project.\n"
            "Below is Vault Documentation — architectural context written by the team. "
            "Use it to understand the project's design intent, conventions, and constraints.\n\n"
            "Your job:\n"
            "1. Read the task file carefully.\n"
            "2. Implement the changes needed to satisfy the task.\n"
            "3. Output each file as a code block with the file path in the opening fence:\n"
            '   ```<language> path=<relative/file/path>\n'
            "   ...file contents...\n"
            "   ```\n"
            "4. After all file blocks, write a brief summary of what was changed.\n\n"
            "Rules:\n"
            "- Output the COMPLETE content for each file you create or modify.\n"
            "- Use relative paths from the working directory root.\n"
            "- Stay within the task scope. Do not add features outside scope.\n"
            "- Do not modify unrelated files.\n"
            "- Follow the project's existing conventions and coding style.\n"
            "- If the task CANNOT be completed (missing info, blocked), explain why clearly.\n"
            "- The Vault Documentation takes precedence over general knowledge "
            "when describing project conventions and architecture.\n"
        )

        user_prompt = (
            f"## Task File Content\n\n{task_content}\n\n"
            f"## Working Directory\n\n{worktree_path}\n\n"
            f"## Project Overview\n\n{project_overview}\n\n"
            f"{vault_section}"
            f"Implement the changes described in the task. "
            f"Output each modified or created file with its relative path.\n"
            f"Then provide a brief summary of what was implemented."
            f"{fix_guide}"
        )

        try:
            token_usage = {}
            result = call_llm_text(
                role=self.llm_role,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                project_policy=model_policy,
                project_id=project_id,
                token_usage=token_usage,
            )

            if cost_tracker is not None and token_usage:
                cost_tracker.record(self.llm_role, token_usage)
                cost_tracker.check_budget(self.llm_role)

            return {"llm_ok": True, "raw": result}
        except Exception as e:
            return {"llm_ok": False, "error": str(e)}

    def _run_validation(self, worktree_path: Path) -> dict:
        """Run build/test validation commands from project config.

        Returns {"success": True/False, "output": "..."} where output
        is the combined stderr/stdout on failure.
        """
        validation_config = self.project_config.get("validation", {})

        commands: list[tuple[str, str]] = []
        build_cmd = validation_config.get("build", "").strip()
        test_cmd = validation_config.get("test", "").strip()
        if build_cmd:
            commands.append(("build", build_cmd))
        if test_cmd:
            commands.append(("test", test_cmd))

        if not commands:
            logger.info("No validation commands configured — skipping")
            return {"success": True, "output": ""}

        outputs: list[str] = []
        for name, cmd in commands:
            logger.info("Running validation step '%s': %s", name, cmd)
            try:
                result = subprocess.run(
                    cmd, shell=True, cwd=worktree_path,
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0:
                    error = (result.stderr.strip() or result.stdout.strip())[:1000]
                    logger.warning("Validation '%s' failed (exit %d)", name, result.returncode)
                    return {
                        "success": False,
                        "output": f"[{name}] failed (exit {result.returncode}):\n{error}",
                    }
                outputs.append(f"[{name}] ok")
                logger.info("Validation '%s' passed", name)
            except subprocess.TimeoutExpired:
                return {"success": False, "output": f"[{name}] timed out after 120s"}
            except FileNotFoundError:
                return {"success": False, "output": f"[{name}] command not found: {cmd}"}
            except Exception as e:
                return {"success": False, "output": f"[{name}] error: {e}"}

        return {"success": True, "output": "\n".join(outputs)}

    def _run_ai_review(self, task_content: str, worktree_path: Path,
                        cost_tracker=None) -> dict:
        """Run AI code review using the primary_reviewer role.

        Generates git diff of changes since the base branch, then asks the
        LLM to review against the task's acceptance criteria.

        Returns {"passed": True/False, "issues": "...", "notes": "..."}
        Review is skipped gracefully if the diff is empty or the LLM call fails.
        """
        from .llm_client import call_llm_text
        from .cost_tracker import BudgetExceededError

        # Get git diff
        try:
            stat_result = _run_git(
                ["diff", f"origin/{self.base_branch}...HEAD", "--stat"],
                cwd=worktree_path, check=False,
            )
            stat = stat_result.stdout.strip()[:1000]
            diff_result = _run_git(
                ["diff", f"origin/{self.base_branch}...HEAD"],
                cwd=worktree_path, check=False,
            )
            diff = diff_result.stdout.strip()[:8000]
        except Exception as e:
            logger.warning("Failed to get git diff for review: %s", e)
            return {"passed": True, "issues": "", "notes": "Review skipped: could not get diff"}

        if not diff:
            return {"passed": True, "issues": "", "notes": "No changes detected"}

        # Extract task body (strip frontmatter)
        fm_match = re.match(r"^---\n.*?\n---\n?", task_content, re.DOTALL)
        task_body = task_content[fm_match.end():].strip() if fm_match else task_content

        vault_context = self._load_vault_context()
        vault_section = (
            f"\n\n## Vault Documentation\n\n{vault_context}\n\n"
            if vault_context else ""
        )

        user_prompt = (
            f"## Task Description\n\n{task_body}\n\n"
            f"## Changes (diff stats)\n\n{stat}\n\n"
            f"## Full Diff\n\n```diff\n{diff}\n```\n\n"
            f"{vault_section}"
            f"Review the implementation against the task's scope and acceptance criteria. "
            f"Check that:\n"
            f"- All acceptance criteria in the task are satisfied\n"
            f"- The changes stay within scope (no unrelated changes)\n"
            f"- The implementation follows the project's conventions\n\n"
            f"Respond with exactly:\n"
            f"REVIEW: PASS or FAIL\n"
            f"ISSUES:\n"
            f"- (list specific issues if FAIL — be precise: file, line, what's wrong)\n"
            f"- (leave empty if PASS)\n"
            f"NOTES:\n"
            f"- (any general observations)\n"
        )

        try:
            model_policy = self.project_config.get("model_policy", {})
            project_id = self.project_config.get("id", self.project_config.get("project_id", ""))

            token_usage = {}
            response = call_llm_text(
                role="primary_reviewer",
                system_prompt=(
                    "You are a senior code reviewer. Review the implementation against "
                    "the task's acceptance criteria. Be thorough but concise. "
                    "Focus on correctness, scope compliance, and conventions."
                ),
                user_prompt=user_prompt,
                project_policy=model_policy,
                project_id=project_id,
                token_usage=token_usage,
            )

            if cost_tracker is not None and token_usage:
                cost_tracker.record("primary_reviewer", token_usage)
                cost_tracker.check_budget("primary_reviewer")

        except BudgetExceededError:
            raise
        except Exception as e:
            logger.warning("AI review call failed: %s", e)
            return {"passed": True, "issues": "", "notes": f"Review skipped: {e}"}

        # Parse response
        lines = response.strip().splitlines()
        passed = False
        current_section = ""
        issue_lines: list[str] = []
        note_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("REVIEW:"):
                passed = "PASS" in stripped.upper()
            elif stripped.startswith("ISSUES:"):
                current_section = "issues"
            elif stripped.startswith("NOTES:"):
                current_section = "notes"
            elif current_section == "issues" and stripped and stripped.startswith("-"):
                issue_lines.append(stripped)
            elif current_section == "notes" and stripped and stripped.startswith("-"):
                note_lines.append(stripped)

        issues = "\n".join(issue_lines)
        notes = "\n".join(note_lines)

        logger.info(
            "AI review: %s (%d issue(s))",
            "PASS" if passed else "FAIL",
            len(issue_lines),
        )

        return {"passed": passed, "issues": issues, "notes": notes}

    def _write_files_from_output(self, output: str, worktree_path: Path) -> list[str]:
        """Parse LLM output for code blocks with file paths and write them.

        Parses blocks in the format:
        ```lang path=relative/path.ext
        content
        ```

        Returns a list of written file paths (relative to worktree).
        """
        written: list[str] = []
        # Pattern: ```<lang> path=<filepath>  ...  ```
        pattern = re.compile(
            r'```\w*\s+path=(\S+)\s*\n(.*?)```',
            re.DOTALL,
        )
        for match in pattern.finditer(output):
            raw_path = match.group(1).strip()
            content = match.group(2)
            if not raw_path or not content:
                continue
            # Sanitize path — strip quotes and leading slashes
            file_path = raw_path.strip("'\"")
            if file_path.startswith("/"):
                file_path = file_path.lstrip("/")

            full_path = worktree_path / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            written.append(file_path)
            logger.info("Wrote file: %s (%d bytes)", file_path, len(content))

        # Fallback: try parsing ```<lang>:<path> or ## File: path patterns
        if not written:
            fallback_pattern = re.compile(
                r'```(\w+)\n#+(?:\s*File:?)?\s*(\S+)\n(.*?)```',
                re.DOTALL,
            )
            for match in fallback_pattern.finditer(output):
                raw_path = match.group(2).strip()
                content = match.group(3)
                if not raw_path or not content:
                    continue
                file_path = raw_path.strip("'\"")
                if file_path.startswith("/"):
                    file_path = file_path.lstrip("/")
                full_path = worktree_path / file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content, encoding="utf-8")
                written.append(file_path)
                logger.info("Wrote file (fallback): %s (%d bytes)", file_path, len(content))

        if not written:
            logger.warning("No parseable file blocks found in LLM output")
            logger.debug("LLM output was:\n%s", output[:2000])

        return written

    # ── Helpers ─────────────────────────────────────────────────────────

    def _update_task_metadata(
        self,
        task_path: Path,
        branch: str,
        pr_url: str,
        worktree_path: str,
        commit_sha: str,
    ) -> None:
        """Write branch/PR metadata into the task frontmatter."""
        _update_frontmatter_field(task_path, "branch", branch)
        _update_frontmatter_field(task_path, "pr_url", pr_url)
        _update_frontmatter_field(task_path, "worktree_path", worktree_path)
        if commit_sha:
            _update_frontmatter_field(task_path, "commit_sha", commit_sha)

    def _cleanup_worktree(self, worktree_path: Path) -> None:
        """Remove a worktree and its directory."""
        try:
            _run_git(["worktree", "remove", str(worktree_path)], cwd=self.repo_root)
        except Exception:
            pass
        try:
            if worktree_path.exists():
                shutil.rmtree(str(worktree_path))
        except Exception:
            pass

    def _build_pr_body(self, task_filename: str, summary: str) -> str:
        """Build the PR body from the task and execution summary."""
        task_path = self.vault_root / "queue-tasks" / "review-needed" / task_filename
        task_description = ""
        if task_path.exists():
            content = task_path.read_text(encoding="utf-8")
            # Extract everything after frontmatter
            fm_match = re.match(r"^---\n.*?\n---\n?", content, re.DOTALL)
            if fm_match:
                task_description = content[fm_match.end() :].strip()

        lines = [
            f"## Summary\n\n{summary}\n",
        ]
        if task_description:
            lines.append(f"## Task\n\n{task_description}\n")
        lines.append(
            "---\n"
            f"_Generated by Workbench orchestration agent._\n"
            f"_Task: `{task_filename}`_\n"
        )
        return "\n".join(lines)

    def get_open_tasks(self) -> list[Path]:
        """List all tasks currently in the open queue."""
        open_dir = self.vault_root / "queue-tasks" / "open"
        if not open_dir.exists():
            return []
        return sorted(
            p for p in open_dir.iterdir()
            if p.is_file() and p.suffix == ".md" and p.name != "README.md"
        )

    def get_claimed_tasks(self) -> list[Path]:
        """List all tasks currently in the claimed queue."""
        claimed_dir = self.vault_root / "queue-tasks" / "claimed"
        if not claimed_dir.exists():
            return []
        return sorted(
            p for p in claimed_dir.iterdir()
            if p.is_file() and p.suffix == ".md" and p.name != "README.md"
        )


# ── Module-level helpers ───────────────────────────────────────────────


def _sanitize_id(name: str) -> str:
    """Sanitize a task filename to a valid git branch name."""
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
    sanitized = re.sub(r"-+", "-", sanitized)
    sanitized = sanitized.strip("-")
    # Truncate to avoid overly long branch names
    return sanitized[:80]


def _extract_summary(text: str) -> str:
    """Extract a brief summary from LLM output."""
    lines = text.strip().splitlines()
    # Take the first non-empty line as summary
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) > 10:
            return stripped[:200]
    return ""


def _build_commit_message(summary: str, branch: str) -> str:
    """Build a commit message with summary and attribution."""
    return (
        f"{summary[:72]}\n\n"
        f"Task: {branch.removeprefix('feature/')}\n"
        f"Co-Authored-By: Workbench Agent <agent@workbench.dev>"
    )


def _extract_post_block_summary(text: str) -> str:
    """Extract summary from LLM output.

    Strips all fenced code blocks (```...```) and returns the last prose line
    that looks like a summary sentence. This is more robust than only looking
    after the final code block fence, because code content may contain inline
    backticks that confuse position-based extraction.
    """
    # Remove all fenced code blocks
    cleaned = re.sub(r'(?s)```.*?```\s*', '', text).strip()
    if not cleaned:
        return ""

    lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
    # Take the last meaningful prose line (LLM typically puts summary at the end)
    prose = [l for l in lines if len(l) > 10]
    if prose:
        return prose[-1][:200]
    return ""


def _detect_blocked(text: str) -> bool:
    """Detect if the LLM reported the task as blocked or blocked."""
    lower = text.lower()
    # Check for clear blocked statements
    blocked_phrases = [
        "cannot be completed",
        "cannot complete",
        "unable to complete",
        "task is blocked",
        "task cannot be",
        "missing required information",
        "not enough context",
    ]
    for phrase in blocked_phrases:
        if phrase in lower:
            # Make sure it's not negated
            sentences = lower.split(".")
            for s in sentences:
                if phrase in s and not any(
                    neg in s for neg in ["not blocked", "no blockers", "can proceed"]
                ):
                    return True
    return False
