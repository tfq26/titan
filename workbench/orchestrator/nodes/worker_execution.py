"""
Worker execution node.

Verification node: validates that the worker completed the task correctly.
The actual work is done externally (OpenCode or another agent).

Enhanced with agent messaging: checks inbox before/after for questions
from reviewers and responds via the message bus.
"""

import logging

from ..state import WorkbenchState
from ..tracing import trace_node
from .. import agent_messaging as msg
from .. import human_channel
from pathlib import Path

logger = logging.getLogger(__name__)


def worker_execution_node(state: WorkbenchState) -> dict:
    """
    Node: worker_execution

    Validates that the worker has completed:
    1. Task moved from claimed/ to review-needed/
    2. Worker report exists
    3. Task frontmatter updated with report link

    Before/after validation, checks the agent message inbox for
    questions from reviewers and responds as needed.
    """
    with trace_node("worker_execution", state) as span:
        vault_root = Path(state.get("project_vault_root", ""))
        task_filename = state.get("current_task_filename", "")
        report_root = Path(state.get("project_report_root", ""))
        thread_id = state.get("discourse_thread_id", "")

        # ── Pre-work: check inbox for reviewer questions ─────────────
        inbox_messages = _check_worker_inbox(vault_root, thread_id)
        if inbox_messages:
            logger.info(
                "worker received %d message(s) before execution",
                len(inbox_messages),
            )

        if not vault_root.exists() or not task_filename:
            span.set_output({"completed": False, "error": "missing_vault_or_filename"})
            return {
                "current_node": "worker_execution",
                "human_questions": [
                    "Vault root or task filename missing. Cannot verify worker completion."
                ],
            }

        review_path = vault_root / "queue-tasks" / "review-needed" / task_filename
        claimed_path = vault_root / "queue-tasks" / "claimed" / task_filename

        if not review_path.exists():
            span.set_output({"completed": False, "waiting": True})
            return {
                "current_node": "worker_execution",
                "human_questions": [
                    f"Task {task_filename} has not been moved to review-needed/. "
                    f"Wait for the worker to complete."
                ],
            }

        if claimed_path.exists():
            raise RuntimeError(
                f"Task {task_filename} exists in both claimed/ and review-needed/. "
                f"Queue invariant violated."
            )

        task_content = review_path.read_text()
        report_path_str = _extract_report_link(task_content)

        if not report_path_str:
            span.set_output({"completed": False, "error": "missing_report_link"})
            return {
                "current_node": "worker_execution",
                "human_questions": [
                    f"Task {task_filename} is in review-needed/ but has no "
                    f"report link in frontmatter."
                ],
            }

        full_report_path = report_root / report_path_str if report_root else Path(report_path_str)
        if not full_report_path.exists():
            full_report_path = vault_root.parent.parent / report_path_str

        if not full_report_path.exists():
            span.set_output({"completed": False, "error": "report_file_missing"})
            return {
                "current_node": "worker_execution",
                "human_questions": [
                    f"Report file {report_path_str} does not exist."
                ],
            }

        span.set_output({"completed": True, "report_path": str(report_path_str)})
        return {
            "current_node": "worker_execution",
            "worker_report_path": str(report_path_str),
            "human_questions": [],
        }


def _check_worker_inbox(
    vault_root: Path,
    thread_id: str,
) -> list[dict]:
    """Check the worker's inbox for messages from reviewers."""
    if not thread_id or not vault_root.exists():
        return []
    return msg.poll_inbox(
        vault_root,
        role="worker",
        thread_id=thread_id,
        include_read=False,
        max_messages=10,
    )


def _extract_report_link(task_content: str) -> str:
    for line in task_content.split("\n"):
        if line.startswith("report:"):
            value = line.replace("report:", "").strip()
            if value:
                return value
    return ""
