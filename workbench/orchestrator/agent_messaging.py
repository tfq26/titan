"""
Agent message bus for the workbench.

Durable, file-based async messaging between agent roles.
Messages are stored as YAML+Markdown files in the project vault at:

    {vault_root}/machine/messages/{thread_id}/

This makes all agent-to-agent communication inspectable by humans
in any text editor or Obsidian.

Message types:
  - question:       Agent asks another agent for information or guidance
  - answer:         Agent responds to a question
  - review_request: Agent asks a reviewer to look at something early
  - review_response: Reviewer responds to a review request
  - info:           Informational message (no response expected)
  - blocking:       Agent is blocked and needs another agent's input
  - decision:       Agent announces a decision
  - clarification:  Agent asks for clarification on a previous message
"""

from __future__ import annotations

import uuid
import yaml
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Literal

import logging

logger = logging.getLogger(__name__)

# ── Message types ──────────────────────────────────────────────────────

MessageType = Literal[
    "question",
    "answer",
    "review_request",
    "review_response",
    "info",
    "blocking",
    "decision",
    "clarification",
]

# ── Message schema ─────────────────────────────────────────────────────

MESSAGE_FIELDS = [
    "message_id",
    "from_role",
    "to_role",
    "type",
    "subject",
    "thread_id",
    "status",
    "timestamp",
    "in_reply_to",
]

VALID_TYPES = frozenset({
    "question", "answer", "review_request", "review_response",
    "info", "blocking", "decision", "clarification",
})


# ── Path helpers ───────────────────────────────────────────────────────

def _messages_root(vault_root: Path) -> Path:
    return vault_root / "machine" / "messages"


def _thread_dir(vault_root: Path, thread_id: str) -> Path:
    return _messages_root(vault_root) / thread_id


def _generate_message_id() -> str:
    return f"MSG-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _ensure_thread_dir(vault_root: Path, thread_id: str) -> Path:
    d = _thread_dir(vault_root, thread_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Core API ───────────────────────────────────────────────────────────

def send_message(
    vault_root: str | Path,
    *,
    from_role: str,
    to_role: str,
    msg_type: MessageType,
    subject: str,
    body: str,
    thread_id: str,
    in_reply_to: Optional[str] = None,
) -> str:
    """Send a message from one role to another.

    Args:
        vault_root: Path to the project vault root.
        from_role: Sending role (e.g. "worker", "primary_reviewer").
        to_role: Receiving role.
        msg_type: Type of message.
        subject: Short subject line.
        body: Message body (Markdown).
        thread_id: Conversation thread identifier.
        in_reply_to: Optional message_id this is replying to.

    Returns:
        The generated message_id.
    """
    vault = Path(vault_root)
    msg_type = str(msg_type).strip().lower()
    if msg_type not in VALID_TYPES:
        raise ValueError(
            f"Invalid message type '{msg_type}'. "
            f"Valid types: {', '.join(sorted(VALID_TYPES))}"
        )

    message_id = _generate_message_id()
    timestamp = datetime.now(timezone.utc).isoformat()
    thread_dir = _ensure_thread_dir(vault, thread_id)

    # Frontmatter (YAML)
    frontmatter = {
        "message_id": message_id,
        "from_role": from_role,
        "to_role": to_role,
        "type": msg_type,
        "subject": subject,
        "thread_id": thread_id,
        "status": "unread",
        "timestamp": timestamp,
    }
    if in_reply_to:
        frontmatter["in_reply_to"] = in_reply_to

    # File content: YAML frontmatter + Markdown body
    content = (
        "---\n"
        + yaml.dump(frontmatter, sort_keys=False, default_flow_style=False).strip()
        + "\n---\n\n"
        + body.strip()
        + "\n"
    )

    # Write as .msg file
    msg_path = thread_dir / f"{message_id}.msg"
    msg_path.write_text(content, encoding="utf-8")

    logger.info(
        "message_bus send id=%s from=%s to=%s type=%s thread=%s",
        message_id, from_role, to_role, msg_type, thread_id,
    )
    return message_id


def poll_inbox(
    vault_root: str | Path,
    role: str,
    *,
    thread_id: Optional[str] = None,
    include_read: bool = False,
    max_messages: int = 50,
) -> list[dict]:
    """Poll the inbox for a given role.

    Args:
        vault_root: Path to the project vault root.
        role: Role whose inbox to check.
        thread_id: Optional thread filter. If None, checks all threads.
        include_read: If True, includes already-read messages.
        max_messages: Maximum messages to return.

    Returns:
        List of message dicts, newest first.
    """
    vault = Path(vault_root)
    root = _messages_root(vault)
    if not root.exists():
        return []

    messages: list[dict] = []

    if thread_id:
        thread_paths = [root / thread_id]
    else:
        thread_paths = sorted(
            [p for p in root.iterdir() if p.is_dir()],
            reverse=True,
        )

    for tdir in thread_paths:
        if not tdir.exists():
            continue
        for msg_file in sorted(tdir.glob("*.msg"), reverse=True):
            msg = _read_message_file(msg_file)
            if msg is None:
                continue
            if msg.get("to_role", "").lower() != role.lower():
                continue
            if not include_read and msg.get("status") == "read":
                continue
            messages.append(msg)
            if len(messages) >= max_messages:
                break
        if len(messages) >= max_messages:
            break

    return messages


def get_thread(
    vault_root: str | Path,
    thread_id: str,
    *,
    max_messages: int = 200,
) -> list[dict]:
    """Get all messages in a thread, oldest first (chronological order).

    Args:
        vault_root: Path to the project vault root.
        thread_id: Thread identifier.
        max_messages: Maximum messages to return.

    Returns:
        List of message dicts in chronological order.
    """
    vault = Path(vault_root)
    tdir = _thread_dir(vault, thread_id)
    if not tdir.exists():
        return []

    messages: list[dict] = []
    for msg_file in sorted(tdir.glob("*.msg")):
        msg = _read_message_file(msg_file)
        if msg is not None:
            messages.append(msg)
            if len(messages) >= max_messages:
                break

    return messages


def mark_read(vault_root: str | Path, message_id: str) -> bool:
    """Mark a single message as read by its message_id.

    Scans all threads for the message.

    Args:
        vault_root: Path to the project vault root.
        message_id: The message ID to mark as read.

    Returns:
        True if found and marked, False if not found.
    """
    vault = Path(vault_root)
    root = _messages_root(vault)
    if not root.exists():
        return False

    for tdir in root.iterdir():
        if not tdir.is_dir():
            continue
        msg_path = tdir / f"{message_id}.msg"
        if msg_path.exists():
            return _update_message_status(msg_path, "read")
    return False


def mark_all_read(
    vault_root: str | Path,
    role: str,
    *,
    thread_id: Optional[str] = None,
) -> int:
    """Mark all unread messages for a role as read.

    Args:
        vault_root: Path to the project vault root.
        role: Role whose messages to mark.
        thread_id: Optional thread filter.

    Returns:
        Count of messages marked as read.
    """
    unread = poll_inbox(vault_root, role, thread_id=thread_id)
    count = 0
    for msg in unread:
        mid = msg.get("message_id", "")
        if mid and mark_read(vault_root, mid):
            count += 1
    return count


def get_unread_count(
    vault_root: str | Path,
    role: str,
    *,
    thread_id: Optional[str] = None,
) -> int:
    """Count unread messages for a role.

    Args:
        vault_root: Path to the project vault root.
        role: Role whose unread count to check.
        thread_id: Optional thread filter.

    Returns:
        Number of unread messages.
    """
    return len(poll_inbox(vault_root, role, thread_id=thread_id))


def has_pending_messages(
    vault_root: str | Path,
    role: str,
    *,
    thread_id: Optional[str] = None,
) -> bool:
    """Check if a role has any unread messages.

    More efficient than get_unread_count for existence checks.
    """
    return len(poll_inbox(vault_root, role, thread_id=thread_id, max_messages=1)) > 0


# ── Internal helpers ───────────────────────────────────────────────────

def _read_message_file(path: Path) -> Optional[dict]:
    """Read a .msg file and return its parsed content as a dict.

    Returns None if the file is malformed.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    # Parse YAML frontmatter
    if not content.startswith("---"):
        return None

    try:
        end_idx = content.index("\n---", 3)
    except ValueError:
        return None

    fm_text = content[3:end_idx].strip()
    try:
        metadata = yaml.safe_load(fm_text)
    except yaml.YAMLError:
        return None

    if not isinstance(metadata, dict):
        return None

    # Extract body (everything after the closing ---)
    body = content[end_idx + 4:].strip()

    return {
        **metadata,
        "body": body,
    }


def _update_message_status(path: Path, new_status: str) -> bool:
    """Update the status field in a message file's frontmatter."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False

    if not content.startswith("---"):
        return False

    try:
        end_idx = content.index("\n---", 3)
    except ValueError:
        return False

    fm_text = content[3:end_idx].strip()
    try:
        metadata = yaml.safe_load(fm_text)
    except yaml.YAMLError:
        return False

    if not isinstance(metadata, dict):
        return False

    old_status = metadata.get("status", "")
    if old_status == new_status:
        return True  # Already in desired state

    metadata["status"] = new_status
    body = content[end_idx + 4:].strip()

    new_content = (
        "---\n"
        + yaml.dump(metadata, sort_keys=False, default_flow_style=False).strip()
        + "\n---\n\n"
        + body
        + "\n"
    )

    path.write_text(new_content, encoding="utf-8")
    return True
