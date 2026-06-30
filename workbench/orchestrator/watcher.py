"""
Filesystem polling watcher for worker-claim detection.

Monitors the project vault's queue-tasks/open/ and queue-tasks/claimed/
directories and emits events when a task transitions between states.

Phase 2 implementation: polling-based watcher using os.stat / path mtime.
Phase 3 (future): filesystem event hooks (watchdog / inotify).

Usage:
    from .watcher import QueueWatcher

    watcher = QueueWatcher(vault_root="/path/to/vault", interval=5.0)
    watcher.on_claimed = lambda task: print(f"Task claimed: {task}")
    watcher.start()
    # ... wait for events ...
    watcher.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class QueueWatcher:
    """
    Polls the queue-tasks directories for state transitions.

    Detects:
    - Task moved from open/ to claimed/ (worker picked it up)
    - Task moved from claimed/ to review-needed/ (worker completed)
    - New task appeared in open/ (supervisor queued something)

    Callbacks are called from the watcher's background thread.
    """

    def __init__(
        self,
        vault_root: str | Path,
        *,
        interval: float = 5.0,
    ):
        self.vault_root = Path(vault_root)
        self.interval = interval
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._last_state: dict[str, dict[str, str]] = {}  # filename → folder

        # Callbacks
        self.on_claimed: Optional[Callable[[str], None]] = None
        self.on_completed: Optional[Callable[[str], None]] = None
        self.on_queued: Optional[Callable[[str], None]] = None
        self.on_blocked: Optional[Callable[[str], None]] = None
        self.on_finalized: Optional[Callable[[str], None]] = None

    @property
    def queue_root(self) -> Path:
        return self.vault_root / "queue-tasks"

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the watcher in a background daemon thread."""
        if self._running:
            logger.warning("QueueWatcher already running")
            return

        self._running = True
        self._last_state = self._snapshot_state()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="queue-watcher")
        self._thread.start()
        logger.info("QueueWatcher started (interval=%.1fs, vault=%s)", self.interval, self.vault_root)

    def stop(self) -> None:
        """Stop the watcher. Blocks until the background thread exits."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.interval + 2)
        logger.info("QueueWatcher stopped")

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    # ── Polling loop ──────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        """Background polling loop. Runs until stop() is called."""
        while self._running:
            try:
                current = self._snapshot_state()
                transitions = self._detect_transitions(self._last_state, current)
                self._last_state = current

                for transition in transitions:
                    self._dispatch(transition)

            except Exception:
                logger.exception("QueueWatcher poll error")

            # Sleep in small increments so stop() is responsive
            deadline = time.time() + self.interval
            while self._running and time.time() < deadline:
                time.sleep(0.5)

    # ── State snapshot ────────────────────────────────────────────────

    def _snapshot_state(self) -> dict[str, dict[str, str]]:
        """Build a snapshot of which tasks are in which folders.

        Returns: {filename: {"folder": "open", "mtime": 12345}}
        """
        snapshot: dict[str, dict[str, str]] = {}

        folders = ["open", "claimed", "review-needed", "completed", "blocked"]

        for folder in folders:
            folder_path = self.queue_root / folder
            if not folder_path.exists():
                continue

            for f in folder_path.iterdir():
                if f.is_file() and f.name.endswith(".md") and f.name != "README.md":
                    try:
                        stat = f.stat()
                        snapshot[f.name] = {
                            "folder": folder,
                            "mtime": str(int(stat.st_mtime)),
                        }
                    except OSError:
                        pass

        return snapshot

    # ── Transition detection ──────────────────────────────────────────

    def _detect_transitions(
        self,
        previous: dict[str, dict[str, str]],
        current: dict[str, dict[str, str]],
    ) -> list[dict]:
        """Compare two snapshots and detect state transitions."""
        transitions: list[dict] = []

        all_filenames = set(previous.keys()) | set(current.keys())

        for filename in all_filenames:
            prev = previous.get(filename, {})
            curr = current.get(filename, {})

            prev_folder = prev.get("folder", "")
            curr_folder = curr.get("folder", "")

            # New task appeared
            if not prev_folder and curr_folder:
                transitions.append({
                    "type": "task_queued",
                    "filename": filename,
                    "folder": curr_folder,
                })
                continue

            # Task disappeared (deleted or moved — will appear elsewhere)
            if prev_folder and not curr_folder:
                transitions.append({
                    "type": "task_removed",
                    "filename": filename,
                    "from_folder": prev_folder,
                })
                continue

            # Task moved between folders
            if prev_folder != curr_folder:
                trans_type = "task_moved"
                if prev_folder == "open" and curr_folder == "claimed":
                    trans_type = "task_claimed"
                elif prev_folder == "claimed" and curr_folder == "review-needed":
                    trans_type = "task_completed"
                elif curr_folder == "blocked":
                    trans_type = "task_blocked"
                elif curr_folder == "completed":
                    trans_type = "task_finalized"

                transitions.append({
                    "type": trans_type,
                    "filename": filename,
                    "from_folder": prev_folder,
                    "to_folder": curr_folder,
                })

        return transitions

    # ── Dispatch ──────────────────────────────────────────────────────

    def _dispatch(self, transition: dict) -> None:
        """Dispatch a transition to the appropriate callback."""
        ttype = transition["type"]
        filename = transition["filename"]

        logger.info(
            "QueueWatcher event: %s file=%s",
            ttype, filename,
        )

        if ttype == "task_claimed" and self.on_claimed:
            try:
                self.on_claimed(filename)
            except Exception:
                logger.exception("QueueWatcher on_claimed callback error")

        elif ttype == "task_completed" and self.on_completed:
            try:
                self.on_completed(filename)
            except Exception:
                logger.exception("QueueWatcher on_completed callback error")

        elif ttype == "task_queued" and self.on_queued:
            try:
                self.on_queued(filename)
            except Exception:
                logger.exception("QueueWatcher on_queued callback error")

        elif ttype == "task_blocked" and self.on_blocked:
            try:
                self.on_blocked(filename)
            except Exception:
                logger.exception("QueueWatcher on_blocked callback error")

        elif ttype == "task_finalized" and self.on_finalized:
            try:
                self.on_finalized(filename)
            except Exception:
                logger.exception("QueueWatcher on_finalized callback error")

    # ── Convenience: blocking wait ────────────────────────────────────

    def wait_for_claim(self, task_filename: str, timeout: float = 300.0) -> bool:
        """
        Block until a specific task is claimed or timeout expires.

        Returns True if the task was claimed, False on timeout.
        """
        claimed_path = self.queue_root / "claimed" / task_filename
        open_path = self.queue_root / "open" / task_filename
        deadline = time.time() + timeout

        while time.time() < deadline:
            if claimed_path.exists() and not open_path.exists():
                return True
            time.sleep(1.0)

        return False

    def wait_for_completion(self, task_filename: str, timeout: float = 600.0) -> bool:
        """
        Block until a specific task moves to review-needed/ or timeout expires.

        Returns True if completed, False on timeout.
        """
        review_path = self.queue_root / "review-needed" / task_filename
        claimed_path = self.queue_root / "claimed" / task_filename
        deadline = time.time() + timeout

        while time.time() < deadline:
            if review_path.exists() and not claimed_path.exists():
                return True
            if review_path.exists():  # Moved but stale in claimed
                time.sleep(0.5)
                if not claimed_path.exists():
                    return True
            time.sleep(2.0)

        return False
