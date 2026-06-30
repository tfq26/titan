"""
Human Side-Channel for agent workbench.

Allows the human to intervene at any point during agent execution,
not just at designated await_human_approval checkpoints.

The human writes Markdown files into {vault_root}/machine/human-input/.
Agents check this directory before/after their main work and process
any pending instructions.

Input file format:
  ---
  to_role: worker          # Which role this is for (or "all")
  type: guidance           # guidance | answer | redirect | abort | info
  subject: Short subject
  ---
  Your message body here in Markdown.

The system processes and archives input files so they are not processed twice.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable, Optional

from . import agent_messaging as msg

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────

VALID_INPUT_TYPES = frozenset({"guidance", "answer", "redirect", "abort", "info"})


# ── Path helpers ────────────────────────────────────────────────────────

def human_input_dir(vault_root: str | Path) -> Path:
    return Path(vault_root) / "machine" / "human-input"


def processed_dir(vault_root: str | Path) -> Path:
    d = human_input_dir(vault_root) / ".processed"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Read and process human input ────────────────────────────────────────

def check_for_human_input(
    vault_root: str | Path,
    *,
    role: str = "",
    max_inputs: int = 10,
) -> list[dict]:
    """Check for pending human intervention files.

    Args:
        vault_root: Path to the project vault root.
        role: If set, only return inputs targeting this role.
        max_inputs: Maximum input files to process.

    Returns:
        List of parsed human input dicts.
    """
    vault = Path(vault_root)
    hdir = human_input_dir(vault)
    if not hdir.exists():
        return []

    inputs: list[dict] = []

    for f in sorted(hdir.glob("*.md"), reverse=False)[:max_inputs]:
        parsed = _parse_human_input_file(f)
        if parsed is None:
            continue

        # Filter by role if specified
        target = parsed.get("to_role", "all").lower().strip()
        if role and target not in (role.lower(), "all", ""):
            # Leave the file for the intended recipient
            continue

        # Archive the processed file
        archive_path = processed_dir(vault) / f"{f.stem}-{int(time.time())}.md"
        try:
            f.rename(archive_path)
        except OSError:
            # Fallback: copy and delete
            try:
                archive_path.write_text(f.read_text(), encoding="utf-8")
                f.unlink()
            except OSError:
                continue

        parsed["_archived_path"] = str(archive_path)
        inputs.append(parsed)

    return inputs


def send_human_input_to_message_bus(
    vault_root: str | Path,
    inputs: list[dict],
    *,
    thread_id: str,
    from_role: str = "human",
) -> int:
    """Forward processed human inputs to the agent message bus.

    Args:
        vault_root: Path to the project vault root.
        inputs: List of parsed human input dicts (from check_for_human_input).
        thread_id: Message bus thread ID.
        from_role: Which role the messages appear to come from.

    Returns:
        Number of messages sent.
    """
    count = 0
    for inp in inputs:
        target = inp.get("to_role", "all")
        msg_type_str = str(inp.get("type", "guidance")).lower().strip()
        if msg_type_str not in msg.VALID_TYPES:
            msg_type_str = "info"

        subject = inp.get("subject", f"Human input ({inp.get('type', 'guidance')})")
        body = inp.get("body", inp.get("message", ""))

        # If targeted at a specific role, send directly to them
        if target and target != "all":
            msg.send_message(
                vault_root,
                from_role=from_role,
                to_role=target,
                msg_type=msg_type_str,
                subject=subject,
                body=body,
                thread_id=thread_id,
            )
        else:
            # Send to all roles
            msg.send_message(
                vault_root,
                from_role=from_role,
                to_role="all",
                msg_type=msg_type_str,
                subject=subject,
                body=body,
                thread_id=thread_id,
            )
        count += 1

    return count


def has_pending_human_input(
    vault_root: str | Path,
    *,
    role: str = "",
) -> bool:
    """Quick check if any human input files exist.

    More efficient than check_for_human_input for existence checks.
    """
    hdir = human_input_dir(vault_root)
    if not hdir.exists():
        return False
    return any(f.suffix == ".md" for f in hdir.iterdir() if f.is_file())


def human_abort_requested(
    vault_root: str | Path,
    *,
    role: str = "",
) -> bool:
    """Check if the human has requested an abort."""
    inputs = check_for_human_input(vault_root, role=role, max_inputs=5)
    return any(i.get("type") == "abort" for i in inputs)


def write_human_input(
    vault_root: str | Path,
    *,
    to_role: str = "all",
    msg_type: str = "guidance",
    subject: str = "",
    body: str,
) -> str:
    """Write a human input file (useful for programmatic/testing usage).

    Args:
        vault_root: Path to the project vault root.
        to_role: Target role ("all", "worker", "primary_reviewer", etc.)
        msg_type: Type of input (guidance, answer, redirect, abort, info)
        subject: Short subject line.
        body: Message body in Markdown.

    Returns:
        Path to the written file as a string.
    """
    vault = Path(vault_root)
    hdir = human_input_dir(vault)
    hdir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"human-input-{timestamp}.md"
    filepath = hdir / filename

    content = "---\n"
    if to_role:
        content += f"to_role: {to_role}\n"
    content += f"type: {msg_type}\n"
    if subject:
        content += f"subject: {subject}\n"
    content += f"timestamp: {timestamp}\n"
    content += "---\n\n"
    content += body.strip() + "\n"

    filepath.write_text(content, encoding="utf-8")
    logger.info("human_channel wrote input file: %s (to=%s, type=%s)", filepath, to_role, msg_type)
    return str(filepath)


# ── Watcher integration ────────────────────────────────────────────────

class HumanInputWatcher:
    """A background watcher that polls the human-input directory and dispatches callbacks."""

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
        self._last_check: dict[str, float] = {}

        # Callback: called when human input is detected
        self.on_input: Optional[Callable[[list[dict]], None]] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="human-input-watcher")
        self._thread.start()
        logger.info("HumanInputWatcher started (interval=%.1fs)", self.interval)

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.interval + 2)
        logger.info("HumanInputWatcher stopped")

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def _poll_loop(self) -> None:
        while self._running:
            try:
                if has_pending_human_input(self.vault_root):
                    inputs = check_for_human_input(self.vault_root, max_inputs=10)
                    if inputs and self.on_input:
                        try:
                            self.on_input(inputs)
                        except Exception:
                            logger.exception("HumanInputWatcher callback error")
            except Exception:
                logger.exception("HumanInputWatcher poll error")

            deadline = time.time() + self.interval
            while self._running and time.time() < deadline:
                time.sleep(0.5)


# ── Internal helpers ───────────────────────────────────────────────────

def _parse_human_input_file(path: Path) -> Optional[dict]:
    """Parse a human input .md file into a structured dict."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    result: dict = {
        "to_role": "all",
        "type": "guidance",
        "subject": "",
        "body": content,
        "message": content,
    }

    if content.startswith("---"):
        try:
            end_idx = content.index("\n---", 3)
            fm_text = content[3:end_idx].strip()
            import yaml
            try:
                metadata = yaml.safe_load(fm_text) or {}
                if isinstance(metadata, dict):
                    for key in ("to_role", "type", "subject", "message"):
                        if key in metadata:
                            result[key] = metadata[key]
            except Exception:
                pass

            # Body is everything after the closing ---
            body = content[end_idx + 4:].strip()
            result["body"] = body
            if "message" not in metadata or not metadata.get("message"):
                result["message"] = body
        except ValueError:
            pass

    return result
