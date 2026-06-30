"""
Batch secondary review node.

Opt-in batch mode for when the primary reviewer explicitly groups
multiple related high-escalation tasks. Reads a batch handoff note
(written using secondary-review-batch.md template) from the vault,
reviews each included task individually, and produces per-task
secondary review notes.

The default is per-task secondary review. Batch is only used when
the primary reviewer writes a batch handoff file and passes its
path through state.
"""

from ..state import WorkbenchState
from ..llm_client import call_llm
from ..model_policy import ModelPolicyError
from ..tracing import trace_node
from pathlib import Path
from datetime import datetime, timezone
from typing import Literal, Optional
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)


# ── Structured output schema ──────────────────────────────────────────

class BatchSecondaryResult(BaseModel):
    task_filename: str = Field(description="The task file being reviewed")
    decision: Literal["confirm", "concern", "revise", "blocked"] = Field(
        description="Per-task secondary review recommendation"
    )
    findings: str = Field(description="Task-specific findings")
    risk_check: str = Field(description="Task-specific risk analysis")


class BatchReviewOutput(BaseModel):
    results: list[BatchSecondaryResult] = Field(
        description="One result per task in the batch"
    )
    shared_risks: str = Field(
        description="Risks shared across all tasks in the batch"
    )


# ── System prompt ─────────────────────────────────────────────────────

BATCH_SECONDARY_SYSTEM = """You are a batch secondary reviewer for a software engineering workbench.

You are reviewing multiple related high-escalation tasks that passed primary
review. These tasks were grouped together because they share a subsystem or
risk profile.

## What To Check (per task)

1. Threading and concurrency risks
2. Lifecycle and ownership issues
3. Architectural regression
4. State machine integrity
5. Edge cases and error paths

## Output

Produce one result per task with:
- decision: confirm, concern, revise, or blocked
- findings: task-specific observations
- risk_check: task-specific risks

Also include shared_risks: any risk that applies to the entire batch.

## Rules

- Be specific per task. Generic findings are not actionable.
- If a task is fine, confirm it clearly.
- If one task's issues affect another, note the cross-task dependency."""


# ── Node ──────────────────────────────────────────────────────────────

def batch_secondary_review_node(state: WorkbenchState) -> dict:
    """
    Node: batch_secondary_review

    Reads batch tasks from state["batch_tasks"] and reviews each one.
    Writes individual secondary review notes to the project vault.

    Expects state["batch_tasks"] to be a list of dicts:
      [{"task_filename": "...", "report_path": "...", "primary_review_path": "..."}]
    """
    with trace_node("batch_secondary_review", state) as span:
        vault_root = Path(state.get("project_vault_root", ""))
        project_id = state.get("project_id", "")
        batch_tasks = state.get("batch_tasks", [])

        if not batch_tasks:
            span.set_output({"reviewed": 0, "error": "empty_batch"})
            return {
                "current_node": "batch_secondary_review",
                "human_questions": ["Batch secondary review requested but no tasks provided."],
                "secondary_review_decision": "concern",
            }

        # ── Gather content for each task ──────────────────────────────
        task_contexts = []
        for bt in batch_tasks:
            ctx = _gather_task_context(vault_root, bt)
            if ctx:
                task_contexts.append(ctx)

        if not task_contexts:
            span.set_output({"reviewed": 0, "error": "no_context_loaded"})
            return {
                "current_node": "batch_secondary_review",
                "human_questions": ["Could not load context for any batch task."],
                "secondary_review_decision": "concern",
            }

        # ── Build batch prompt ────────────────────────────────────────
        user_prompt = _build_batch_prompt(task_contexts)

        if len(user_prompt) > 60000:
            user_prompt = user_prompt[:60000] + "\n\n... (truncated)"

        # ── Call secondary reviewer ───────────────────────────────────
        try:
            result = call_llm(
                role="secondary_reviewer",
                system_prompt=BATCH_SECONDARY_SYSTEM,
                user_prompt=user_prompt,
                output_schema=BatchReviewOutput,
                fallback=BatchReviewOutput(
                    results=[
                        BatchSecondaryResult(
                            task_filename=ctx["task_filename"],
                            decision="concern",
                            findings="LLM call failed during batch review.",
                            risk_check="Batch review could not be completed.",
                        )
                        for ctx in task_contexts
                    ],
                    shared_risks="Batch review failed due to model error.",
                ),
                project_policy=state.get("model_policy"),
                project_id=project_id,
                policy_ctx={
                    "escalation_tier": state.get("escalation_tier", "high"),
                    "task_type": state.get("task_type", ""),
                },
            )
        except ModelPolicyError as e:
            logger.error("Policy denied: %s", e)
            span.set_output({"error": "policy_denied"})
            return {
                "current_node": "batch_secondary_review",
                "secondary_review_decision": "blocked",
                "human_questions": [f"Batch review blocked by model policy: {e}"],
                "human_approval_required": True,
                "transition_blocked": True,
            }
        except Exception:
            logger.exception("Batch secondary review LLM call failed")
            result = BatchReviewOutput(
                results=[
                    BatchSecondaryResult(
                        task_filename=ctx["task_filename"],
                        decision="concern",
                        findings="LLM call failed with exception.",
                        risk_check="Batch review incomplete.",
                    )
                    for ctx in task_contexts
                ],
                shared_risks="Batch review failed with exception.",
            )

        # ── Write per-task review notes ───────────────────────────────
        review_paths = []
        for r in result.results:
            review_path = _write_batch_review_note(
                vault_root=vault_root,
                result=r,
                shared_risks=result.shared_risks,
                state=state,
            )
            review_paths.append(str(review_path.relative_to(vault_root)))

        # ── Aggregate decisions ───────────────────────────────────────
        # If any task is blocked → batch is blocked
        # If any task is revise → batch is revise
        # If any task is concern → batch is concern
        # Otherwise → confirm
        decisions = [r.decision for r in result.results]
        if "blocked" in decisions:
            aggregate = "blocked"
        elif "revise" in decisions:
            aggregate = "revise"
        elif "concern" in decisions:
            aggregate = "concern"
        else:
            aggregate = "confirm"

        span.set_output({
            "reviewed": len(result.results),
            "aggregate_decision": aggregate,
            "shared_risks": result.shared_risks,
        })

        return {
            "current_node": "batch_secondary_review",
            "secondary_review_decision": aggregate,
            "secondary_review_path": review_paths[0] if review_paths else "",
            "batch_review_paths": review_paths,
            "decision_rationale": result.shared_risks,
        }


# ── Helpers ───────────────────────────────────────────────────────────

def _gather_task_context(
    vault_root: Path, batch_task: dict
) -> Optional[dict]:
    """Read task, report, and primary review for one batch task."""
    task_filename = batch_task.get("task_filename", "")
    report_path = batch_task.get("report_path", "")
    primary_review = batch_task.get("primary_review_path", "")

    if not task_filename:
        return None

    ctx = {"task_filename": task_filename}

    # Task content
    task_path = vault_root / "queue-tasks" / "review-needed" / task_filename
    if task_path.exists():
        content = task_path.read_text()
        if len(content) > 3000:
            content = content[:3000] + "\n... (truncated)"
        ctx["task_content"] = content
    else:
        ctx["task_content"] = "(task file not found)"

    # Report content
    if report_path:
        rp = vault_root.parent.parent / report_path
        if rp.exists():
            content = rp.read_text()
            if len(content) > 2000:
                content = content[:2000] + "\n... (truncated)"
            ctx["report_content"] = content
        else:
            ctx["report_content"] = "(report not found)"
    else:
        ctx["report_content"] = "(no report path)"

    # Primary review
    if primary_review:
        prp = vault_root / primary_review
        if prp.exists():
            content = prp.read_text()
            if len(content) > 2000:
                content = content[:2000] + "\n... (truncated)"
            ctx["primary_review"] = content
        else:
            ctx["primary_review"] = "(primary review not found)"
    else:
        ctx["primary_review"] = "(no primary review path)"

    return ctx


def _build_batch_prompt(task_contexts: list[dict]) -> str:
    """Build the batch review prompt from task contexts."""
    parts = [
        f"## Batch Review — {len(task_contexts)} Tasks\n",
        "These tasks were grouped because they share a subsystem or risk profile.",
    ]

    for i, ctx in enumerate(task_contexts, 1):
        parts.append(
            f"### Task {i}: {ctx['task_filename']}\n\n"
            f"**Task**:\n{ctx.get('task_content', 'N/A')}\n\n"
            f"**Worker Report**:\n{ctx.get('report_content', 'N/A')}\n\n"
            f"**Primary Review**:\n{ctx.get('primary_review', 'N/A')}\n"
        )

    parts.append(
        "\n## Instructions\n\n"
        "Review each task and produce per-task decisions, findings, and risk checks. "
        "Also identify any risks shared across the entire batch."
    )

    return "\n".join(parts)


def _write_batch_review_note(
    vault_root: Path,
    result: BatchSecondaryResult,
    shared_risks: str,
    state: WorkbenchState,
) -> Path:
    """Write a per-task secondary review note in batch context."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    review_filename = f"review-secondary-batch-{result.task_filename}"

    review_dir = vault_root / "queue-tasks" / "review-needed"
    review_dir.mkdir(parents=True, exist_ok=True)
    review_path = review_dir / review_filename

    content = f"""---
type: review
status: complete
created: {now}
reviewer_role: secondary
reviewer_model: {state.get("secondary_reviewer_model", "unknown")}
task: {result.task_filename}
batch_review: true
decision: {result.decision}
shared_risks: {shared_risks[:200]}
subsystems: []
---

# Secondary Review (Batch)

## Task

{result.task_filename}

## Decision

{result.decision}

## Findings

{result.findings}

## Risk Check

{result.risk_check}

## Shared Batch Risks

{shared_risks}

## Recommendation Back To Primary

Decision: {result.decision}
"""
    review_path.write_text(content)
    return review_path
