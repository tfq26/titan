"""
Block task node.

Moves a task to the blocked/ folder when it cannot proceed without
human input, access to external resources, or resolution of dependencies.
"""

from ..state import WorkbenchState
from ..tracing import trace_node
from pathlib import Path
from datetime import datetime
import shutil


def block_task_node(state: WorkbenchState) -> dict:
    """
    Node: block_task

    Moves the task from its current folder to blocked/ and prepares
    human questions for resolution.
    """
    with trace_node("block_task", state) as span:
        vault_root = Path(state.get("project_vault_root", ""))
        task_filename = state.get("current_task_filename", "")

        if not vault_root.exists() or not task_filename:
            span.set_output({"blocked": False, "error": "missing_vault_or_filename"})
            return {
                "current_node": "block_task",
                "human_questions": ["Missing vault root or task filename."],
            }

        current_folder = _find_task_folder(vault_root, task_filename)
        if not current_folder:
            span.set_output({"blocked": False, "error": "task_not_found"})
            return {
                "current_node": "block_task",
                "human_questions": [
                    f"Task {task_filename} not found in any queue folder."
                ],
            }

        _move_to_blocked(vault_root, task_filename, current_folder)

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        span.set_output({"blocked": True, "from_folder": current_folder})
        return {
            "current_node": "block_task",
            "human_questions": state.get("human_questions", [
                f"Task {task_filename} has been blocked. Review and provide input."
            ]),
            "human_approval_required": True,
            "final_decision": "blocked",
            "completed_at": now,
        }


def _find_task_folder(vault_root: Path, task_filename: str) -> str:
    state_folders = ["open", "claimed", "review-needed", "completed", "blocked"]
    queue_root = vault_root / "queue-tasks"
    for folder in state_folders:
        if (queue_root / folder / task_filename).exists():
            return folder
    return ""


def _move_to_blocked(
    vault_root: Path, task_filename: str, current_folder: str
) -> None:
    queue_root = vault_root / "queue-tasks"
    source = queue_root / current_folder / task_filename
    target_dir = queue_root / "blocked"
    target = target_dir / task_filename
    target_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(source, target)
    if not target.exists():
        raise RuntimeError(f"Failed to copy task to blocked/: {target}")
    source.unlink()
    if source.exists():
        if target.exists():
            target.unlink()
        raise RuntimeError(f"Failed to delete source task: {source}")

    content = target.read_text()
    lines = content.split("\n")
    new_lines = []
    for line in lines:
        if line.startswith("status:"):
            new_lines.append("status: blocked")
        else:
            new_lines.append(line)
    target.write_text("\n".join(new_lines))
