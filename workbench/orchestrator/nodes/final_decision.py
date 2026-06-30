"""
Final decision node.

Makes the final decision after all reviews are complete, updates queue
state via atomic file moves, and enforces invariants.
"""

from ..state import WorkbenchState
from ..repair import verify_vault_transition
from ..plan_sequences import (
    extract_plan_metadata_from_task_content,
    has_next_plan_step,
    load_plan_manifest,
)
from ..tracing import trace_node
from pathlib import Path
from datetime import datetime
import shutil


def final_decision_node(state: WorkbenchState) -> dict:
    """
    Node: final_decision

    Makes the final decision and updates queue state.
    Primary reviewer owns the final decision even after secondary review.
    """
    with trace_node("final_decision", state) as span:
        vault_root = Path(state.get("project_vault_root", ""))
        task_filename = state.get("current_task_filename", "")

        if not vault_root.exists() or not task_filename:
            span.set_output({"decision": "revise", "error": "missing_vault_or_filename"})
            return {
                "current_node": "final_decision",
                "final_decision": "revise",
                "human_questions": ["Missing vault root or task filename."],
            }

        task_path = vault_root / "queue-tasks" / "review-needed" / task_filename
        task_content = task_path.read_text() if task_path.exists() else ""
        plan_metadata = extract_plan_metadata_from_task_content(task_content)

    final = _determine_final_decision(state)
    source_folder = "review-needed"
    target_folder = _decision_to_folder(final)

    if final == "verify":
        # Task stays in review-needed. Do not move it.
        # Surface secondary concerns for the primary reviewer to resolve.
        _update_task_frontmatter(vault_root, task_filename, target_folder, final, state)
        plan_updates = _plan_state_updates(
            vault_root=vault_root,
            plan_metadata=plan_metadata,
            final_decision=final,
        )
        span.set_output({"decision": "verify", "target_folder": "review-needed"})
        return {
            "current_node": "final_decision",
            "final_decision": "verify",
            "human_questions": [
                f"Secondary review returned 'concern' for task {task_filename}. "
                f"Primary reviewer must review the concerns and explicitly "
                f"complete, revise, or block the task."
            ],
            "human_approval_required": True,
            **plan_updates,
        }

    _atomic_move_task(vault_root, task_filename, source_folder, target_folder)

    ok, errors = verify_vault_transition(
        vault_root, task_filename, target_folder, source_folder
    )
    if not ok:
        span.set_output({"decision": "blocked", "transition_error": True})
        return {
            "current_node": "final_decision",
            "final_decision": "blocked",
            "human_questions": errors,
            "transition_blocked": True,
        }

    _update_task_frontmatter(vault_root, task_filename, target_folder, final, state)

    plan_updates = _plan_state_updates(
        vault_root=vault_root,
        plan_metadata=plan_metadata,
        final_decision=final,
    )

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    span.set_output({"decision": final, "target_folder": target_folder})
    return {
        "current_node": "final_decision",
        "final_decision": final,
        "completed_at": now if final == "complete" else state.get("completed_at"),
        **plan_updates,
    }


def _determine_final_decision(state: WorkbenchState) -> str:
    tier = state.get("escalation_tier", "low")
    primary_decision = state.get("primary_review_decision", "revise")
    secondary_decision = state.get("secondary_review_decision", "")

    if primary_decision == "blocked":
        return "blocked"
    if primary_decision == "revise":
        return "revise"

    if tier == "low":
        return "complete" if primary_decision == "passes_first_pass" else "revise"

    # High escalation
    if primary_decision == "passes_first_pass":
        if secondary_decision == "confirm":
            return "complete"
        if secondary_decision == "concern":
            return "verify"       # Primary reviewer must explicitly resolve concerns
        if secondary_decision == "revise":
            return "revise"
        if secondary_decision == "blocked":
            return "blocked"
        return "complete"

    return "revise"


def _decision_to_folder(decision: str) -> str:
    return {
        "complete": "completed",
        "revise": "open",
        "blocked": "blocked",
        "verify": "review-needed",   # stays put, primary reviewer resolves
    }.get(decision, "open")


def _plan_state_updates(
    *,
    vault_root: Path,
    plan_metadata: dict,
    final_decision: str,
) -> dict:
    if not plan_metadata:
        return {}

    manifest_path = str(plan_metadata.get("plan_manifest_path", "")).strip()
    if not manifest_path:
        return {}

    manifest = load_plan_manifest(vault_root, manifest_path)
    if not manifest:
        return {}

    step_index = _to_int(plan_metadata.get("plan_step_index"))
    step_total = _to_int(plan_metadata.get("plan_step_total")) or len(manifest.get("tasks") or [])
    should_queue_next = final_decision == "complete" and has_next_plan_step(manifest, step_index)

    updates = {
        "plan_manifest_path": manifest_path,
        "plan_id": str(manifest.get("plan_id", "")).strip() or plan_metadata.get("plan_id"),
        "plan_title": str(manifest.get("title", "")).strip() or plan_metadata.get("plan_title"),
        "plan_summary": str(manifest.get("summary", "")).strip() or plan_metadata.get("plan_summary"),
        "plan_step_index": step_index or plan_metadata.get("plan_step_index"),
        "plan_step_total": step_total or plan_metadata.get("plan_step_total"),
        "plan_step_title": plan_metadata.get("plan_step_title"),
        "plan_step_goal": plan_metadata.get("plan_step_goal"),
        "plan_should_queue_next": should_queue_next,
    }

    return updates


def _to_int(value: object) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _atomic_move_task(
    vault_root: Path, task_filename: str, source_folder: str, target_folder: str
) -> None:
    queue_root = vault_root / "queue-tasks"
    source_path = queue_root / source_folder / task_filename
    target_dir = queue_root / target_folder
    target_path = target_dir / task_filename
    target_dir.mkdir(parents=True, exist_ok=True)

    if not source_path.exists():
        raise RuntimeError(f"Source task not found: {source_path}")

    shutil.copy2(source_path, target_path)
    if not target_path.exists():
        raise RuntimeError(f"Failed to copy task to {target_path}")

    source_path.unlink()
    if source_path.exists():
        if target_path.exists():
            target_path.unlink()
        raise RuntimeError(f"Failed to delete source task: {source_path}")


def _update_task_frontmatter(
    vault_root: Path,
    task_filename: str,
    target_folder: str,
    decision: str,
    state: WorkbenchState,
) -> None:
    queue_root = vault_root / "queue-tasks"
    task_path = queue_root / target_folder / task_filename
    if not task_path.exists():
        return

    content = task_path.read_text()
    lines = content.split("\n")
    new_lines = []
    for line in lines:
        if line.startswith("status:"):
            if decision == "verify":
                new_lines.append("status: review-needed  # verify — secondary review concerns pending")
            else:
                new_lines.append(f"status: {target_folder.rstrip('/')}")
        elif line.startswith("review:"):
            review_path = state.get("primary_review_path", "")
            new_lines.append(f"review: {review_path}")
        elif line.startswith("report:"):
            report_path = state.get("worker_report_path", "")
            if report_path:
                new_lines.append(f"report: {report_path}")
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
    task_path.write_text("\n".join(new_lines))
