"""
Plan sequence helpers for autonomous kickoff and task chaining.

These helpers turn a conversational plan into a durable machine record:
- a plan manifest stored in the project vault
- ordered task slices with preallocated filenames
- compact metadata that can travel with each queued task
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional
import re
import uuid

import yaml


@dataclass
class ChatTaskProposal:
    title: str = ""
    goal: str = ""
    task_type: str = "implementation"
    acceptance: list[str] = field(default_factory=list)
    scope: list[str] = field(default_factory=list)


@dataclass
class PlanSequenceProposal:
    title: str = ""
    summary: str = ""
    tasks: list[ChatTaskProposal] = field(default_factory=list)


def parse_chat_task_proposal(text: str) -> Optional[ChatTaskProposal]:
    """Parse an explicit `Task:` block from chat output."""
    lines = (text or "").splitlines()
    task_started = False
    task_lines: list[str] = []

    for line in lines:
        compact = line.strip()

        if not task_started and _is_task_marker(compact):
            task_started = True
            continue

        if task_started:
            if _is_handoff_marker(compact) or _is_plan_marker(compact):
                break
            task_lines.append(line)

    if not task_started:
        return None

    return _parse_task_lines(task_lines)


def parse_chat_plan_proposal(text: str) -> Optional[PlanSequenceProposal]:
    """Parse a plan block that contains one or more `Task:` sections."""
    lines = (text or "").splitlines()
    has_plan_marker = any(_is_plan_marker(line.strip()) for line in lines)
    task_markers = sum(1 for line in lines if _is_task_marker(line.strip()))

    if not has_plan_marker and task_markers < 2:
        return None

    plan_started = not has_plan_marker
    plan_lines: list[str] = []
    task_blocks: list[list[str]] = []
    current_task: list[str] = []
    in_task_block = False

    for line in lines:
        compact = line.strip()

        if not plan_started and _is_plan_marker(compact):
            plan_started = True
            continue

        if not plan_started:
            continue

        if _is_handoff_marker(compact):
            break

        if _is_task_marker(compact):
            if current_task:
                task_blocks.append(current_task)
                current_task = []
            in_task_block = True
            continue

        if in_task_block:
            current_task.append(line)
        else:
            plan_lines.append(line)

    if current_task:
        task_blocks.append(current_task)

    if not task_blocks:
        return None

    proposal = PlanSequenceProposal()
    _parse_plan_lines(plan_lines, proposal)

    for block in task_blocks:
        task = _parse_task_lines(block)
        if task:
            proposal.tasks.append(task)

    if not proposal.tasks:
        return None

    if not proposal.title and proposal.tasks[0].title:
        proposal.title = proposal.tasks[0].title

    return proposal


def materialize_plan_manifest(
    *,
    vault_root: Path,
    project_id: str,
    source_request: str,
    source_role: str,
    source_nickname: str,
    response_mode: str,
    proposal: PlanSequenceProposal,
) -> tuple[str, list[str], str]:
    """Write a plan manifest and return its relative path, task filenames, and id."""
    if not proposal.tasks:
        raise ValueError("Plan sequence proposal must include at least one task.")

    plan_id = _generate_plan_id(project_id)
    task_filenames = _allocate_task_filenames(
        vault_root=vault_root,
        project_id=project_id,
        count=len(proposal.tasks),
    )
    manifest = {
        "schema": "workbench.plan-sequence.v1",
        "plan_id": plan_id,
        "project_id": project_id,
        "title": proposal.title,
        "summary": proposal.summary,
        "source_request": source_request,
        "source_role": source_role,
        "source_nickname": source_nickname,
        "response_mode": response_mode,
        "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "task_count": len(proposal.tasks),
        "task_filenames": task_filenames,
        "tasks": [
            {
                "index": index + 1,
                "filename": task_filenames[index],
                "title": task.title,
                "goal": task.goal,
                "task_type": task.task_type,
                "acceptance": task.acceptance,
                "scope": task.scope,
            }
            for index, task in enumerate(proposal.tasks)
        ],
    }

    manifest_path = vault_root / "machine" / "plans" / f"{plan_id}.yaml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return str(manifest_path.relative_to(vault_root)), task_filenames, plan_id


def load_plan_manifest(vault_root: Path, manifest_path: str) -> dict:
    """Load a previously written plan manifest."""
    path = Path(manifest_path)
    if not path.is_absolute():
        path = vault_root / manifest_path
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def plan_step_for_index(manifest: dict, step_index: int) -> Optional[dict]:
    """Return the 1-based plan step payload, or None if out of range."""
    tasks = manifest.get("tasks") or []
    if step_index < 1 or step_index > len(tasks):
        return None
    step = tasks[step_index - 1]
    return step if isinstance(step, dict) else None


def has_next_plan_step(manifest: dict, step_index: int) -> bool:
    """Return True when another queued slice remains after this step."""
    tasks = manifest.get("tasks") or []
    return 1 <= step_index < len(tasks)


def extract_plan_metadata_from_task_content(task_content: str) -> dict:
    """Read plan metadata from task frontmatter."""
    frontmatter = _parse_frontmatter(task_content)
    if not frontmatter:
        return {}

    metadata: dict[str, object] = {}

    plan_manifest = str(frontmatter.get("plan_manifest", "")).strip()
    if plan_manifest:
        metadata["plan_manifest_path"] = plan_manifest

    for source_key, target_key in (
        ("plan_id", "plan_id"),
        ("plan_title", "plan_title"),
        ("plan_summary", "plan_summary"),
        ("plan_step_title", "plan_step_title"),
        ("plan_step_goal", "plan_step_goal"),
    ):
        value = str(frontmatter.get(source_key, "")).strip()
        if value:
            metadata[target_key] = value

    step_index = _coerce_int(frontmatter.get("plan_step_index"))
    if step_index:
        metadata["plan_step_index"] = step_index

    step_total = _coerce_int(frontmatter.get("plan_step_total"))
    if step_total:
        metadata["plan_step_total"] = step_total

    return metadata


def resolve_plan_sequence_context(vault_root: Path, state: Mapping[str, object]) -> dict:
    """
    Resolve the active plan step from state and the stored manifest.

    When ``plan_should_queue_next`` is true, this returns the next step in the
    manifest. Otherwise it returns the current step so revisions can reuse the
    same plan slice metadata.
    """
    manifest_path = str(
        state.get("plan_manifest_path")
        or state.get("plan_manifest")
        or ""
    ).strip()
    if not manifest_path:
        return {}

    manifest = load_plan_manifest(vault_root, manifest_path)
    if not manifest:
        return {}

    current_index = _coerce_int(state.get("plan_step_index")) or 0
    should_queue_next = bool(state.get("plan_should_queue_next", False))
    step_index = current_index + 1 if should_queue_next and current_index else (current_index or 1)

    step = plan_step_for_index(manifest, step_index)
    if not step:
        return {}

    tasks = manifest.get("tasks") or []
    step_total = _coerce_int(manifest.get("task_count")) or len(tasks)

    context: dict[str, object] = {
        "plan_manifest_path": manifest_path,
        "plan_id": str(manifest.get("plan_id", "")).strip(),
        "plan_title": str(manifest.get("title", "")).strip(),
        "plan_summary": str(manifest.get("summary", "")).strip(),
        "plan_step_index": step_index,
        "plan_step_total": step_total,
        "plan_step_title": str(step.get("title", "")).strip(),
        "plan_step_goal": str(step.get("goal", "")).strip(),
        "plan_step_task_type": str(step.get("task_type", "")).strip() or "implementation",
        "plan_step_filename": str(step.get("filename", "")).strip(),
        "workflow_intent": "plan_kickoff",
    }

    step_goal = str(step.get("goal", "")).strip()
    if step_goal:
        context["user_request"] = step_goal

    return context


def build_plan_sequence_section(plan_metadata: Mapping[str, object]) -> str:
    """Render a compact plan-section block for queued task markdown."""
    if not plan_metadata:
        return ""

    manifest_path = str(
        plan_metadata.get("plan_manifest_path")
        or plan_metadata.get("plan_manifest")
        or ""
    ).strip()
    plan_id = str(plan_metadata.get("plan_id", "")).strip()
    plan_title = str(plan_metadata.get("plan_title", "")).strip()
    plan_summary = str(plan_metadata.get("plan_summary", "")).strip()
    plan_step_index = _coerce_int(plan_metadata.get("plan_step_index"))
    plan_step_total = _coerce_int(plan_metadata.get("plan_step_total"))
    plan_step_title = str(plan_metadata.get("plan_step_title", "")).strip()
    plan_step_goal = str(plan_metadata.get("plan_step_goal", "")).strip()
    plan_step_filename = str(plan_metadata.get("plan_step_filename", "")).strip()

    lines: list[str] = ["## Plan Sequence"]

    if plan_title:
        lines.append(f"- Plan: {plan_title}")
    if plan_id:
        lines.append(f"- Plan ID: {plan_id}")
    if plan_summary:
        lines.append(f"- Summary: {plan_summary}")
    if plan_step_index and plan_step_total:
        lines.append(f"- Step: {plan_step_index} of {plan_step_total}")
    elif plan_step_index:
        lines.append(f"- Step: {plan_step_index}")
    if plan_step_title:
        lines.append(f"- Step title: {plan_step_title}")
    if plan_step_goal:
        lines.append(f"- Step goal: {plan_step_goal}")
    if plan_step_filename:
        lines.append(f"- Filename: {plan_step_filename}")
    if manifest_path:
        lines.append(f"- Manifest: {manifest_path}")

    lines.extend(
        [
            "",
            "Treat this slice as one step in the larger plan manifest.",
            "When this slice is complete, write the report, keep scope tight, and let the orchestrator queue the next step only if one remains.",
        ]
    )

    return "\n".join(lines)


def _generate_plan_id(project_id: str) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    return f"PLAN-{timestamp}-{suffix}-{project_id}"


def _allocate_task_filenames(
    *,
    vault_root: Path,
    project_id: str,
    count: int,
) -> list[str]:
    from .nodes.queue_task import _allocate_task_filename

    filenames: list[str] = []
    for _ in range(count):
        filenames.append(_allocate_task_filename(vault_root, project_id, session_id=""))
    return filenames


def _is_task_marker(line: str) -> bool:
    return bool(re.match(r"^(task(?:\s+\d+)?(?:\s+proposal)?):?\s*$", line, flags=re.IGNORECASE))


def _is_plan_marker(line: str) -> bool:
    return bool(re.match(r"^plan(?:\s+proposal)?\s*:?\s*$", line, flags=re.IGNORECASE))


def _is_handoff_marker(line: str) -> bool:
    return bool(re.match(r"^handoff:?\s*$", line, flags=re.IGNORECASE))


def _parse_plan_lines(lines: list[str], proposal: PlanSequenceProposal) -> None:
    saw_content = False
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        key_match = re.match(r"^[-*]?\s*([A-Za-z0-9 _-]+?)\s*:\s*(.*)$", line)
        if key_match:
            key = key_match.group(1).strip().lower().replace(" ", "_")
            value = key_match.group(2).strip()
            saw_content = True
            if key in {"title", "plan_title", "name"}:
                proposal.title = value
            elif key in {"summary", "objective", "overview"}:
                proposal.summary = value
            elif not proposal.title and value:
                proposal.title = value
            elif not proposal.summary and value:
                proposal.summary = value
            continue
        if not proposal.title:
            proposal.title = line
            saw_content = True
            continue
        if not proposal.summary:
            proposal.summary = line
            saw_content = True

    if not saw_content:
        return


def _parse_task_lines(lines: list[str]) -> Optional[ChatTaskProposal]:
    proposal = ChatTaskProposal()
    current_list: Optional[str] = None
    saw_content = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        key_match = re.match(r"^[-*]?\s*([A-Za-z0-9 _-]+?)\s*:\s*(.*)$", line)
        if key_match:
            key = key_match.group(1).strip().lower().replace(" ", "_")
            value = key_match.group(2).strip()
            saw_content = True
            current_list = None

            if key in {"type", "task_type"}:
                proposal.task_type = value or proposal.task_type
            elif key == "title":
                proposal.title = value
            elif key in {"goal", "objective", "summary"}:
                proposal.goal = value
            elif key == "acceptance":
                current_list = "acceptance"
                if value:
                    proposal.acceptance.append(value)
            elif key == "scope":
                current_list = "scope"
                if value:
                    proposal.scope.append(value)
            else:
                if not proposal.goal and value:
                    proposal.goal = value
            continue

        bullet_match = re.match(r"^[-*]\s+(.*)$", line)
        if bullet_match and current_list:
            saw_content = True
            getattr(proposal, current_list).append(bullet_match.group(1).strip())
            continue

        if not proposal.title:
            proposal.title = line
            saw_content = True
            continue

        if not proposal.goal:
            proposal.goal = line
            saw_content = True
            continue

    if not saw_content:
        return None

    if not proposal.goal:
        proposal.goal = proposal.title

    return proposal


def _parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from a Markdown file."""
    if not content.startswith("---"):
        return {}

    try:
        end_idx = content.index("\n---", 3)
    except ValueError:
        return {}

    fm_text = content[3:end_idx].strip()
    try:
        data = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return {}

    return data if isinstance(data, dict) else {}


def _coerce_int(value: object) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0
