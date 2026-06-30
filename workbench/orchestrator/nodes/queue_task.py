"""
Queue a task in the project vault.

Writes a TASK-*.md file to the project vault's queue-tasks/open/ directory
using the canonical queued-task template. Enforces queue-state invariants.
When the request is a plan kickoff, the task includes kickoff-specific
coordination instructions but still uses the same queue/review flow.
"""

from ..state import WorkbenchState
from ..repair import validate_graph_vs_vault, Conflict
from ..plan_kickoff import build_plan_kickoff_task_section
from ..plan_sequences import build_plan_sequence_section, resolve_plan_sequence_context
from ..tracing import trace_node
from pathlib import Path
from datetime import datetime
import shutil
import uuid


def queue_task_node(state: WorkbenchState) -> dict:
    """
    Node: queue_task

    Writes a new task file into the project vault's queue-tasks/open/ folder.
    If this is a revision (revision_count > 0), the task is re-queued with
    updated frontmatter.
    """
    with trace_node("queue_task", state) as span:
        vault_root = Path(state.get("project_vault_root", ""))
        user_request = state.get("user_request", "")
        task_type = state.get("task_type", "implementation")
        workflow_intent = state.get("workflow_intent", "task")
        escalation_tier = state.get("escalation_tier", "low")
        risk_level = state.get("risk_level", "low")
        revision_count = state.get("revision_count", 0)
        project_id = state.get("project_id", "unknown")
        session_id = state.get("session_id", "")
        plan_context = resolve_plan_sequence_context(vault_root, state)

        if not vault_root.exists():
            raise FileNotFoundError(f"Project vault root not found: {vault_root}")

        task_filename = state.get("current_task_filename", "")
        if plan_context:
            user_request = str(plan_context.get("user_request", user_request))
            task_type = str(plan_context.get("plan_step_task_type", task_type))
            workflow_intent = str(plan_context.get("workflow_intent", workflow_intent))
            task_filename = str(plan_context.get("plan_step_filename", "")) or task_filename

        is_revision = revision_count > 0 and bool(task_filename)

        if not task_filename:
            task_filename = _allocate_task_filename(
                vault_root=vault_root,
                project_id=project_id,
                session_id=session_id,
            )

        # ── Pre-transition validation ─────────────────────────────────
        if is_revision:
            conflicts = validate_graph_vs_vault(
                vault_root=vault_root,
                task_filename=task_filename,
                expected_queue_state="review-needed",
                expected_revision=revision_count - 1,
            )
            if conflicts:
                updates = {
                    "repair_conditions": [_conflict_to_dict(c) for c in conflicts],
                    "transition_blocked": True,
                    "human_questions": [
                        f"Vault-graph conflict detected before revision queue: "
                        f"{conflicts[0].description}"
                    ],
                }
                span.set_output({"queued": False, "conflict": True})
                return updates

        # ── Enforce: task must not exist in another state folder ──────
        _enforce_single_instance(vault_root, task_filename, is_revision)

        # ── Build and write task ──────────────────────────────────────
        task_content = _build_task_markdown(
            task_filename=task_filename,
            user_request=user_request,
            task_type=task_type,
            workflow_intent=workflow_intent,
            escalation_tier=escalation_tier,
            risk_level=risk_level,
            revision_count=revision_count + (1 if is_revision else 0),
            vault_root=vault_root,
            state=state,
            plan_metadata=plan_context or None,
        )

        open_dir = vault_root / "queue-tasks" / "open"
        open_dir.mkdir(parents=True, exist_ok=True)
        task_path = open_dir / task_filename
        task_path.write_text(task_content)

        if not task_path.exists():
            raise RuntimeError(f"Failed to write task file: {task_path}")

        if is_revision:
            _cleanup_revision_copies(vault_root, task_filename)

        relative_task_path = str(task_path.relative_to(vault_root))

        span.set_output({"task_filename": task_filename, "queued": True, "is_revision": is_revision})
        return {
            "current_task_path": relative_task_path,
            "current_task_filename": task_filename,
            "workflow_intent": workflow_intent,
            "plan_manifest_path": plan_context.get("plan_manifest_path") if plan_context else state.get("plan_manifest_path"),
            "plan_id": plan_context.get("plan_id") if plan_context else state.get("plan_id"),
            "plan_title": plan_context.get("plan_title") if plan_context else state.get("plan_title"),
            "plan_summary": plan_context.get("plan_summary") if plan_context else state.get("plan_summary"),
            "plan_step_index": plan_context.get("plan_step_index") if plan_context else state.get("plan_step_index"),
            "plan_step_total": plan_context.get("plan_step_total") if plan_context else state.get("plan_step_total"),
            "plan_step_title": plan_context.get("plan_step_title") if plan_context else state.get("plan_step_title"),
            "plan_step_goal": plan_context.get("plan_step_goal") if plan_context else state.get("plan_step_goal"),
            "current_node": "queue_task",
        }


def _generate_task_filename(project_id: str) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:4]
    return f"TASK-{timestamp}-{suffix}-{project_id}.md"


def _allocate_task_filename(vault_root: Path, project_id: str, session_id: str) -> str:
    """
    Allocate a queue filename that does not already exist in any state folder.

    Fresh requests should never fail just because a previous task used a similar
    timestamp. We keep the filename human-readable, then retry until it is free.
    """
    for _ in range(32):
        task_filename = _generate_task_filename(project_id)
        if session_id:
            # Prefer a session-scoped name when available, but keep the
            # timestamped prefix for readability in the queue board.
            parts = task_filename.removesuffix(".md").split("-")
            # TASK-YYYYMMDD-HHMMSS-uuid-project -> TASK-YYYYMMDD-HHMMSS-uuid-session-project
            if len(parts) >= 5:
                parts.insert(-1, session_id[:8])
                task_filename = "-".join(parts) + ".md"
        if not _task_exists_anywhere(vault_root, task_filename):
            return task_filename

    raise RuntimeError(
        f"Unable to allocate a unique task filename for project {project_id}. "
        f"Queue may contain too many conflicting names."
    )


def _task_exists_anywhere(vault_root: Path, task_filename: str) -> bool:
    queue_root = vault_root / "queue-tasks"
    for folder in ["open", "claimed", "review-needed", "completed", "blocked"]:
        if (queue_root / folder / task_filename).exists():
            return True
    return False


def _enforce_single_instance(
    vault_root: Path, task_filename: str, is_revision: bool
) -> None:
    state_folders = ["open", "claimed", "review-needed", "completed", "blocked"]
    queue_root = vault_root / "queue-tasks"
    for folder in state_folders:
        candidate = queue_root / folder / task_filename
        if candidate.exists():
            if is_revision and folder == "review-needed":
                continue
            raise RuntimeError(
                f"Task {task_filename} already exists in {folder}/. "
                f"Queue invariant violated."
            )


def _cleanup_revision_copies(vault_root: Path, task_filename: str) -> None:
    review_dir = vault_root / "queue-tasks" / "review-needed"
    stale = review_dir / task_filename
    if stale.exists():
        stale.unlink()


def _build_task_markdown(
    task_filename: str,
    user_request: str,
    task_type: str,
    workflow_intent: str,
    escalation_tier: str,
    risk_level: str,
    revision_count: int,
    vault_root: Path,
    state: WorkbenchState,
    plan_metadata: dict | None = None,
) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    plan_metadata = _plan_metadata_from_state(state, plan_metadata)
    plan_frontmatter = _build_plan_frontmatter(plan_metadata)
    plan_section = build_plan_sequence_section(plan_metadata)
    return f"""---
type: queued-task
status: open
created: {now}
queued_by: workbench-orchestrator
assigned_to: worker
priority: normal
escalation_tier: {escalation_tier}
risk_level: {risk_level}
revision: {revision_count}
workflow_intent: {workflow_intent}
primary_reviewer:
secondary_reviewer:
subsystems: []
related_feature:
report:
review:
{plan_frontmatter}
---

# {task_filename.replace('.md', '')}

## Goal

{user_request}

## Scope

In bounds:

- Implement the goal described above.

Out of bounds:

- Changes not required by the goal.

## Background

Task classified as `{task_type}` with `{escalation_tier}` escalation tier.
Workflow intent: `{workflow_intent}`.

When speaking in chat or reports, use the model nickname from routing as the
human-facing identity. Keep the role label for the workflow job title.

## First Read

- [Vault README]({vault_root}/README.md)
- [Repo map]({vault_root}/01-repo-map.md)
- [Current state]({vault_root}/memory/current-state.md)

{plan_section}

{_build_plan_kickoff_if_needed(workflow_intent)}

## Implementation Plan

1. Read relevant source files and system maps.
2. Implement the change.
3. Run validation.
4. Write a worker report.
5. Move task to `review-needed/`.

## Acceptance Bar

- Change implements the goal.
- Validation passes (or explanation of why not).
- Worker report is written.

## Review Tier

- `{escalation_tier}` — {'primary reviewer signoff only' if escalation_tier == 'low' else 'primary reviewer plus secondary reviewer'}

## Validation

Run project-specific validation commands (see project-config.yaml).

## Reporting Required

When done or blocked:

1. Write a report using the worker-report template.
2. Update this task frontmatter `status` and `report:` field.
3. Move this task to `review-needed/` or `blocked/`.
"""


def _build_plan_kickoff_if_needed(workflow_intent: str) -> str:
    if workflow_intent != "plan_kickoff":
        return ""
    return build_plan_kickoff_task_section()


def _plan_metadata_from_state(
    state: WorkbenchState,
    plan_metadata: dict | None = None,
) -> dict:
    metadata = dict(plan_metadata or {})
    for state_key, target_key in (
        ("plan_manifest_path", "plan_manifest_path"),
        ("plan_id", "plan_id"),
        ("plan_title", "plan_title"),
        ("plan_summary", "plan_summary"),
        ("plan_step_index", "plan_step_index"),
        ("plan_step_total", "plan_step_total"),
        ("plan_step_title", "plan_step_title"),
        ("plan_step_goal", "plan_step_goal"),
        ("plan_step_filename", "plan_step_filename"),
    ):
        value = state.get(state_key)
        if value not in (None, "", 0):
            metadata[target_key] = value
    return metadata


def _build_plan_frontmatter(plan_metadata: dict) -> str:
    if not plan_metadata:
        return ""

    lines: list[str] = []
    for frontmatter_key, metadata_key in (
        ("plan_manifest", "plan_manifest_path"),
        ("plan_id", "plan_id"),
        ("plan_title", "plan_title"),
        ("plan_summary", "plan_summary"),
        ("plan_step_index", "plan_step_index"),
        ("plan_step_total", "plan_step_total"),
        ("plan_step_title", "plan_step_title"),
        ("plan_step_goal", "plan_step_goal"),
    ):
        value = plan_metadata.get(metadata_key)
        if value not in (None, "", 0):
            lines.append(f"{frontmatter_key}: {value}")

    if not lines:
        return ""

    return "\n".join(lines)


def _conflict_to_dict(c: Conflict) -> dict:
    return {
        "type": c.conflict_type,
        "description": c.description,
        "task": c.task_filename,
        "severity": c.severity,
    }
