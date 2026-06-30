"""
Human approval checkpoints for the workbench LangGraph.

Uses LangGraph's interrupt() mechanism to pause execution at
pre-defined gates and resume when the human provides input.
"""

from typing import Optional
from .state import WorkbenchState

# ── Checkpoint definitions ────────────────────────────────────────────

CHECKPOINT_BEFORE_DESTRUCTIVE = "before_destructive_tool"
CHECKPOINT_AFTER_CLASSIFY = "after_classify_low_confidence"
CHECKPOINT_AFTER_SECONDARY_REVIEW = "after_secondary_review_risk_flag"

# ── Destructive tools that require approval ───────────────────────────

DESTRUCTIVE_TOOLS = [
    "apply_patch",
    "delete_file",
    "install_dependency",
    "modify_env",
    "git_push",
    "deploy",
    "force_push",
    "database_migration",
    "drop_table",
]

# ── Checkpoint timeout (seconds) ──────────────────────────────────────

TIMEOUT_SECONDS = 86400  # 24 hours


# ── Checkpoint logic ──────────────────────────────────────────────────

def requires_destructive_approval(tool_name: str) -> bool:
    """Check if a tool call requires human approval before execution."""
    return tool_name in DESTRUCTIVE_TOOLS


def prepare_destructive_approval_checkpoint(
    state: WorkbenchState, tool_name: str
) -> dict:
    """Prepare the state for a destructive-tool interrupt."""
    return {
        "interrupt_type": CHECKPOINT_BEFORE_DESTRUCTIVE,
        "tool": tool_name,
        "task": state.get("current_task_path", ""),
        "files_affected": state.get("files_changed", []),
        "session_id": state.get("session_id", ""),
    }


def prepare_classify_checkpoint(state: WorkbenchState) -> dict:
    """Prepare state for a low-confidence classification interrupt."""
    return {
        "interrupt_type": CHECKPOINT_AFTER_CLASSIFY,
        "user_request": state.get("user_request", ""),
        "predicted_task_type": state.get("task_type", ""),
        "predicted_risk_level": state.get("risk_level", ""),
        "confidence": state.get("classification_confidence", 0.0),
        "session_id": state.get("session_id", ""),
    }


def prepare_secondary_review_risk_checkpoint(state: WorkbenchState) -> dict:
    """Prepare state for a secondary-review risk-flag interrupt."""
    return {
        "interrupt_type": CHECKPOINT_AFTER_SECONDARY_REVIEW,
        "task": state.get("current_task_path", ""),
        "secondary_review_decision": state.get("secondary_review_decision", ""),
        "session_id": state.get("session_id", ""),
    }
