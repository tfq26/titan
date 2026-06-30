"""
Spec-to-Project Pipeline.

Turns a specification document, idea, or high-level request into
actionable queued tasks via multi-agent collaborative discourse.

Flow:
  1. Read the spec (from a file path or inline text)
  2. Trigger collaborative discourse among worker + primary_reviewer
  3. Parse discourse output into a structured task breakdown
  4. Produce a plan manifest (via plan_sequences helpers)
  5. Queue the first task automatically
  6. Return the results for reporting

Usage (from run.py):
    from .spec_to_project import run_spec_pipeline
    result = run_spec_pipeline(spec_path="/path/to/spec.md", project_config=...)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
import uuid

from .nodes.collaborative_discourse import collaborative_discourse_node
from .nodes.queue_task import _allocate_task_filename, _build_task_markdown
from .plan_sequences import (
    PlanSequenceProposal,
    ChatTaskProposal,
    materialize_plan_manifest,
)

logger = logging.getLogger(__name__)


# ── Public API ─────────────────────────────────────────────────────────

def run_spec_pipeline(
    *,
    spec_text: str,
    spec_path: Optional[str] = None,
    project_config: dict,
    model_policy: dict,
    model_routing: dict | None = None,
) -> dict:
    """Run the spec-to-project pipeline.

    Args:
        spec_text: The specification content (can be combined with spec_path).
        spec_path: Optional path to a spec file. If provided, content is
                   prepended to spec_text.
        project_config: Project configuration from registry.
        model_policy: Project model policy dict.
        model_routing: Resolved model nicknames dict.

    Returns:
        Dict with pipeline results:
            spec_summary: str
            spec_tasks: list[dict]
            plan_manifest_path: str (or empty)
            queued_first_task: str (filename, or empty)
            discourse_record_path: str (or empty)
            discourse_thread_id: str
    """
    vault_root = Path(project_config["vault_root"])
    model_routing = model_routing or {}

    # ── Read spec content ────────────────────────────────────────────
    full_spec = spec_text or ""
    if spec_path:
        spec_file = Path(spec_path)
        if spec_file.exists():
            file_content = spec_file.read_text(encoding="utf-8")
            full_spec = file_content + "\n\n" + full_spec if full_spec else file_content
            logger.info("spec_to_project read spec from %s (%d chars)", spec_path, len(file_content))
        else:
            logger.warning("spec_to_project spec file not found: %s", spec_path)

    if not full_spec.strip():
        return {"error": "No spec content provided", "spec_summary": "", "spec_tasks": []}

    # ── Run collaborative discourse ──────────────────────────────────
    thread_id = f"spec-{uuid.uuid4().hex[:8]}"
    discourse_state = _build_discourse_state(
        spec=full_spec,
        project_config=project_config,
        model_policy=model_policy,
        model_routing=model_routing,
        thread_id=thread_id,
    )

    logger.info("spec_to_project starting collaborative discourse (thread=%s)", thread_id)
    discourse_result = collaborative_discourse_node(discourse_state)

    summary = discourse_result.get("discourse_summary", "")
    agreements = discourse_result.get("discourse_agreements", [])
    disagreements = discourse_result.get("discourse_disagreements", [])
    task_breakdown = discourse_result.get("discourse_task_breakdown", [])
    consensus = discourse_result.get("discourse_consensus_reached", False)
    ready = discourse_result.get("discourse_ready_to_queue", True)
    record_path = discourse_result.get("discourse_record_path", "")

    # ── Build task breakdown from discourse output ───────────────────
    tasks = _parse_tasks_from_discourse(
        task_breakdown=task_breakdown,
        spec=full_spec,
        agreements=agreements,
    )

    # ── If tasks were produced, materialize a plan manifest ──────────
    plan_manifest_path = ""
    queued_first_task = ""

    if tasks:
        plan_proposal = _tasks_to_plan_proposal(tasks, summary)
        if plan_proposal:
            try:
                manifest_path, filenames, plan_id = materialize_plan_manifest(
                    vault_root=vault_root,
                    project_id=project_config["id"],
                    source_request=full_spec[:2000],
                    source_role="spec_to_project",
                    source_nickname="orchestrator",
                    response_mode="brief",
                    proposal=plan_proposal,
                )
                plan_manifest_path = manifest_path
                if filenames:
                    queued_first_task = filenames[0]
                logger.info(
                    "spec_to_project created plan manifest: %s (%d tasks)",
                    manifest_path, len(tasks),
                )
            except Exception as e:
                logger.error("spec_to_project failed to create plan manifest: %s", e)

    # ── Write spec summary to vault ──────────────────────────────────
    summary_record = _write_spec_summary(
        vault_root=vault_root,
        spec=full_spec,
        thread_id=thread_id,
        summary=summary,
        tasks=tasks,
        consensus=consensus,
        plan_manifest=plan_manifest_path,
    )

    result = {
        "spec_summary": summary,
        "spec_agreements": agreements,
        "spec_disagreements": disagreements,
        "spec_tasks": tasks,
        "spec_task_count": len(tasks),
        "plan_manifest_path": plan_manifest_path,
        "queued_first_task": queued_first_task,
        "discourse_record_path": record_path,
        "discourse_thread_id": thread_id,
        "spec_summary_path": str(summary_record.relative_to(vault_root)) if summary_record else "",
        "consensus_reached": consensus,
        "ready_to_queue": ready,
    }

    logger.info(
        "spec_to_project complete: %d tasks, plan=%s, consensus=%s",
        len(tasks), plan_manifest_path or "(none)", consensus,
    )
    return result


# ── Internal helpers ───────────────────────────────────────────────────

def _build_discourse_state(
    *,
    spec: str,
    project_config: dict,
    model_policy: dict,
    model_routing: dict,
    thread_id: str,
) -> dict:
    """Build a minimal WorkbenchState for the collaborative_discourse node."""
    vault_root = Path(project_config["vault_root"]).resolve()
    return {
        "project_vault_root": str(vault_root),
        "project_id": project_config["id"],
        "user_request": spec,
        "task_type": "implementation",
        "workflow_intent": "discussion",
        "escalation_tier": "low",
        "risk_level": "low",
        "model_policy": model_policy,
        "current_node": "collaborative_discourse",
        "worker_model": model_routing.get("worker_model", ""),
        "primary_reviewer_model": model_routing.get("primary_reviewer_model", ""),
        "secondary_reviewer_model": model_routing.get("secondary_reviewer_model", ""),
        "classifier_model": model_routing.get("classifier_model", ""),
        "supervisor_planner_model": model_routing.get("supervisor_planner_model", ""),
        "bookkeeping_reviewer_model": model_routing.get("bookkeeping_reviewer_model", ""),
        "discourse_thread_id": thread_id,
        "discourse_summary": None,
        "discourse_agreements": [],
        "discourse_disagreements": [],
        "discourse_task_breakdown": [],
        "discourse_record_path": None,
        "discourse_consensus_reached": False,
        "discourse_ready_to_queue": True,
        "pending_agent_messages": [],
        "human_input_pending": False,
        "human_input_path": None,
        "human_input_last_checked": None,
    }


def _parse_tasks_from_discourse(
    *,
    task_breakdown: list[dict],
    spec: str,
    agreements: list[str],
) -> list[dict]:
    """Parse discourse task breakdown into structured task proposals.

    Each task dict has: title, goal, task_type, acceptance, scope.
    """
    if not task_breakdown:
        # Generate at least one fallback task from the spec
        return [
            {
                "title": "Implement specification",
                "goal": spec[:500],
                "task_type": "implementation",
                "acceptance": [
                    "Spec scope is covered",
                    "Validation passes",
                    "Worker report written",
                ],
                "scope": [
                    "Implement what is described in the spec",
                    "Do not add features outside spec scope",
                ],
            }
        ]

    tasks: list[dict] = []
    for entry in task_breakdown:
        source = entry.get("source", "")
        task = {
            "title": _extract_title(source) or "Task from spec",
            "goal": source[:500],
            "task_type": "implementation",
            "acceptance": [
                "Implementation matches the spec for this task",
                "Validation passes",
            ],
            "scope": [
                "In-scope as described",
                "No scope creep outside this task definition",
            ],
        }
        # Try to extract more structure
        if "type:" in source.lower():
            for line in source.split("\n"):
                lower = line.lower().strip()
                if lower.startswith("type:"):
                    t = line.split(":", 1)[1].strip().lower()
                    if t in ("implementation", "docs", "refactor", "investigation"):
                        task["task_type"] = t

        tasks.append(task)

    return tasks


def _extract_title(source: str) -> str:
    """Extract a task title from discourse output."""
    for line in source.split("\n"):
        line = line.strip()
        if line.startswith("Task:") or line.startswith("task:"):
            return line.split(":", 1)[1].strip()[:100]
        if line.startswith("#") and len(line) < 120:
            return line.lstrip("#").strip()
    return ""


def _tasks_to_plan_proposal(
    tasks: list[dict],
    summary: str,
) -> Optional[PlanSequenceProposal]:
    """Convert parsed task dicts into a PlanSequenceProposal."""
    if not tasks:
        return None

    proposal = PlanSequenceProposal(
        title=summary[:200] if summary else "Spec implementation plan",
        summary=summary[:500] if summary else "",
    )

    for t in tasks:
        proposal.tasks.append(
            ChatTaskProposal(
                title=t.get("title", "Task")[:100],
                goal=t.get("goal", "")[:500],
                task_type=t.get("task_type", "implementation"),
                acceptance=t.get("acceptance", ["Validation passes"]),
                scope=t.get("scope", ["In scope as described"]),
            )
        )

    return proposal


def _write_spec_summary(
    *,
    vault_root: Path,
    spec: str,
    thread_id: str,
    summary: str,
    tasks: list[dict],
    consensus: bool,
    plan_manifest: str,
) -> Optional[Path]:
    """Write a spec summary record to the vault."""
    spec_dir = vault_root / "machine" / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    record_path = spec_dir / f"spec-summary-{thread_id}.md"

    tasks_str = ""
    for i, t in enumerate(tasks, 1):
        tasks_str += (
            f"### Task {i}: {t.get('title', 'Untitled')}\n\n"
            f"- Type: {t.get('task_type', 'implementation')}\n"
            f"- Goal: {t.get('goal', '')[:200]}\n"
        )
        acceptance = t.get("acceptance", [])
        if acceptance:
            tasks_str += "- Acceptance:\n"
            for a in acceptance:
                tasks_str += f"  - {a}\n"
        scope = t.get("scope", [])
        if scope:
            tasks_str += "- Scope:\n"
            for s in scope:
                tasks_str += f"  - {s}\n"
        tasks_str += "\n"

    content = f"""---
type: spec-summary
created: {now}
thread_id: {thread_id}
consensus_reached: {str(consensus).lower()}
plan_manifest: {plan_manifest or ""}
task_count: {len(tasks)}
---

# Spec Summary

## Original Spec

{spec[:3000]}{'... (truncated)' if len(spec) > 3000 else ''}

## Discourse Summary

{summary or 'No summary produced.'}

## Task Breakdown ({len(tasks)} tasks)

{tasks_str or 'No tasks were produced from the discourse.'}

## Plan Manifest

{plan_manifest or 'Not created (discourse did not produce actionable tasks).'}
"""
    record_path.write_text(content, encoding="utf-8")
    logger.info("spec_to_project summary written to %s", record_path)
    return record_path
