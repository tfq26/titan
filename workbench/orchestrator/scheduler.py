"""
Cron-based task scheduler for recurring queue tasks.

Reads a `schedules:` section from project-config.yaml and creates task
files in queue-tasks/open/ when their cron expressions fire. Tracks
last-fire via marker files in .issue-refs/ to avoid duplicates.

Usage:
    from .scheduler import TaskScheduler

    schedules = [
        {
            "id": "weekly-dep-update",
            "cron": "0 9 * * 1",
            "title": "Update dependencies",
            "description": "Check for outdated deps and update.",
        }
    ]
    sched = TaskScheduler(vault_root=..., schedules=schedules, interval=60.0)
    sched.start()
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from croniter import croniter
    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False
    logger.warning("croniter not available — cron-based schedules disabled. pip install croniter")


def _sanitize_id(name: str) -> str:
    """Sanitize a schedule ID to a safe filename fragment."""
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-")[:80]


class TaskScheduler:
    """
    Background daemon that creates queue tasks on a cron schedule.

    Each schedule entry supports:
      - cron:   Standard 5-field cron expression (requires croniter)
      - interval_hours: Simple hourly interval (no deps needed)
      - interval_days:  Simple daily interval (no deps needed)

    A schedule fires at most once per window. The last-fire time is
    stored in .issue-refs/schedule-<id> as an ISO timestamp.
    """

    def __init__(
        self,
        vault_root: str | Path,
        schedules: list[dict],
        *,
        interval: float = 60.0,
        project_id: str = "",
    ):
        self.vault_root = Path(vault_root).resolve()
        self.schedules = schedules
        self.interval = interval
        self.project_id = project_id
        self._thread: Optional[threading.Thread] = None
        self._running = False

    @property
    def ref_dir(self) -> Path:
        return self.vault_root / "queue-tasks" / ".issue-refs"

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        if not self.schedules:
            logger.info("TaskScheduler: no schedules configured, skipping")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="task-scheduler",
        )
        self._thread.start()
        logger.info(
            "TaskScheduler started (%d schedule(s), interval=%.0fs)",
            len(self.schedules), self.interval,
        )

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.interval + 2)
        logger.info("TaskScheduler stopped")

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    # ── Polling loop ──────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while self._running:
            try:
                self._poll_once()
            except Exception:
                logger.exception("TaskScheduler poll error")

            deadline = time.time() + self.interval
            while self._running and time.time() < deadline:
                time.sleep(0.5)

    def _poll_once(self) -> None:
        """Check each schedule and fire if due."""
        now = datetime.now(timezone.utc)

        for sched in self.schedules:
            try:
                self._check_schedule(sched, now)
            except Exception as e:
                logger.warning(
                    "TaskScheduler error checking schedule '%s': %s",
                    sched.get("id", "?"), e,
                )

    def _check_schedule(self, sched: dict, now: datetime) -> None:
        """Check if a single schedule should fire now."""
        sid = sched.get("id", "")
        if not sid:
            return

        cron_expr = sched.get("cron", "")
        interval_hours = sched.get("interval_hours", 0)
        interval_days = sched.get("interval_days", 0)

        if not cron_expr and not interval_hours and not interval_days:
            logger.debug("Schedule '%s': no trigger configured, skipping", sid)
            return

        # Read last-fire timestamp
        last_fire = self._read_last_fire(sid)

        if cron_expr:
            if not HAS_CRONITER:
                logger.warning("Schedule '%s' uses cron but croniter not installed", sid)
                return
            try:
                # Get the next fire time after last_fire
                base = last_fire if last_fire else now
                cron = croniter(cron_expr, base)
                next_fire = cron.get_next(datetime)
                if now >= next_fire:
                    self._fire_schedule(sched, now)
            except (ValueError, OverflowError) as e:
                logger.warning("Schedule '%s' cron parse error: %s", sid, e)

        elif interval_hours > 0:
            if last_fire is None:
                self._fire_schedule(sched, now)
            else:
                elapsed = (now - last_fire).total_seconds()
                if elapsed >= interval_hours * 3600:
                    self._fire_schedule(sched, now)

        elif interval_days > 0:
            if last_fire is None:
                self._fire_schedule(sched, now)
            else:
                elapsed = (now - last_fire).total_seconds()
                if elapsed >= interval_days * 86400:
                    self._fire_schedule(sched, now)

    # ── Task creation ───────────────────────────────────────────────

    def _fire_schedule(self, sched: dict, now: datetime) -> None:
        """Create a task file for the schedule and update last-fire."""
        sid = sched["id"]
        date_str = now.strftime("%Y%m%d")
        safe_id = _sanitize_id(sid)
        task_filename = f"TASK-{date_str}-scheduled-{safe_id}.md"

        title = sched.get("title", f"Scheduled task: {sid}")
        description = sched.get("description", "")
        priority = sched.get("priority", "medium")

        # Build task content
        content = (
            f"---\n"
            f"type: scheduled\n"
            f"status: open\n"
            f"created: {date_str}\n"
            f"queued_by: scheduler\n"
            f"assigned_to: worker\n"
            f"priority: {priority}\n"
            f"escalation_tier: low\n"
            f"schedule_id: {sid}\n"
            f"---\n"
            f"# {title}\n"
            f"\n"
            f"{description}\n"
            f"\n"
            f"---\n"
            f"_Auto-created by TaskScheduler ({sid})_\n"
        )

        open_dir = self.vault_root / "queue-tasks" / "open"
        open_dir.mkdir(parents=True, exist_ok=True)
        task_path = open_dir / task_filename

        if task_path.exists():
            logger.info(
                "Schedule '%s' task already exists: %s", sid, task_filename,
            )
        else:
            task_path.write_text(content, encoding="utf-8")
            logger.info(
                "Schedule '%s' fired: created task %s", sid, task_filename,
            )

        # Update last-fire
        self._write_last_fire(sid, now)

    # ── Last-fire tracking ──────────────────────────────────────────

    def _last_fire_path(self, schedule_id: str) -> Path:
        safe = _sanitize_id(schedule_id)
        return self.ref_dir / f"schedule-{safe}"

    def _read_last_fire(self, schedule_id: str) -> Optional[datetime]:
        path = self._last_fire_path(schedule_id)
        if not path.exists():
            return None
        try:
            return datetime.fromisoformat(path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return None

    def _write_last_fire(self, schedule_id: str, dt: datetime) -> None:
        path = self._last_fire_path(schedule_id)
        self.ref_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(dt.isoformat(), encoding="utf-8")
