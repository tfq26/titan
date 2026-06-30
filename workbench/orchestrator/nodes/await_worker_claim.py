"""
Wait for a worker to claim the queued task.

Phase 1: Manual/UI trigger. The human tells a worker to check the queue.
Phase 2: Filesystem polling watcher on queue state transitions.
Phase 3: Webhook/event integration if OpenCode provides a reliable mechanism.
"""

from ..state import WorkbenchState
from ..tracing import trace_node
from pathlib import Path


def await_worker_claim_node(state: WorkbenchState) -> dict:
    """
    Node: await_worker_claim

    Verifies that the task has been moved from open/ to claimed/.
    If not yet claimed, the graph checkpoints here.
    """
    with trace_node("await_worker_claim", state) as span:
        vault_root = Path(state.get("project_vault_root", ""))
        task_filename = state.get("current_task_filename", "")

        if not task_filename:
            span.set_output({"claimed": False, "error": "missing_filename"})
            return {
                "current_node": "await_worker_claim",
                "human_questions": ["Task filename is missing. Cannot check claim status."],
            }

        open_path = vault_root / "queue-tasks" / "open" / task_filename
        claimed_path = vault_root / "queue-tasks" / "claimed" / task_filename

        task_claimed = claimed_path.exists()
        task_still_open = open_path.exists()

        if task_claimed and not task_still_open:
            span.set_output({"claimed": True})
            return {"current_node": "await_worker_claim", "human_questions": []}
        elif task_claimed and task_still_open:
            raise RuntimeError(
                f"Task {task_filename} exists in both open/ and claimed/. "
                f"Queue invariant violated."
            )
        else:
            span.set_output({"claimed": False, "waiting": True})
            return {
                "current_node": "await_worker_claim",
                "human_questions": [
                    f"Task {task_filename} is waiting in open/. "
                    f"Tell a worker to check the queue."
                ],
            }


def is_task_claimed(state: WorkbenchState) -> bool:
    """Check if a task has been claimed without modifying state."""
    vault_root = Path(state.get("project_vault_root", ""))
    task_filename = state.get("current_task_filename", "")
    if not task_filename or not vault_root.exists():
        return False
    claimed_path = vault_root / "queue-tasks" / "claimed" / task_filename
    open_path = vault_root / "queue-tasks" / "open" / task_filename
    return claimed_path.exists() and not open_path.exists()
