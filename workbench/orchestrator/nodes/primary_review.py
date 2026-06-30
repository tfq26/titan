"""
Primary review node.

The primary reviewer reads the task, worker report, and git diff, then
produces a review decision using the configured primary_reviewer model.

Produces: passes_first_pass | revise | blocked
"""

from ..state import WorkbenchState
from ..llm_client import call_llm
from ..model_policy import ModelPolicyError
from ..tracing import trace_node
from .. import agent_messaging as msg
from .. import human_channel
from pathlib import Path
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)


# ── Structured output schema ──────────────────────────────────────────

class PrimaryReviewResult(BaseModel):
    decision: Literal["passes_first_pass", "revise", "blocked"] = Field(
        description="The review decision"
    )
    findings: str = Field(
        description="Concrete issues found, confirmations, or missing evidence. "
                    "Be specific about what was checked and what was found."
    )
    risks: str = Field(
        description="Anything that may still break or needs follow-up. "
                    "Mention specific subsystems, edge cases, or untested paths."
    )
    scope_check_passed: bool = Field(
        description="True if the diff stayed within the task's stated scope"
    )
    evidence_sufficient: bool = Field(
        description="True if validation evidence supports the report claims"
    )


# ── System prompt ─────────────────────────────────────────────────────

PRIMARY_REVIEW_SYSTEM = """You are a primary reviewer for a software engineering workbench.

Your job is to review a worker's completed implementation against the queued
task. You are the lower-cost default judgment layer. You check for obvious
problems — not subtle architectural risks (those go to secondary review).
When you speak about yourself in prose, use your nickname as the identity and
the role name as the job title.

## Review Questions

Answer these when reviewing:

1. Did the worker stay within the queued task scope?
2. Were any surprising files touched?
3. Were the requested validation commands actually run?
4. Do the validation results support the report claims?
5. Are the known gaps acceptable for completion?

## Decision Guide

- **passes_first_pass**: Scope satisfied, evidence acceptable, no obvious flaws.
  The change looks correct and can proceed.
- **revise**: The change exists but misses scope, quality, or evidence
  requirements. The worker needs to fix something specific.
- **blocked**: Progress depends on user input, access to resources, or
  resolution of an external dependency. The worker cannot fix this alone.

## Rules

- Do not pass a task with missing validation unless the worker explained why.
- Scope violations (unexpected files changed) should usually result in revise.
- If the report makes claims but provides no evidence, that is grounds for revise.
- If the change is reasonable but validation is incomplete, consider revise
  with a specific request rather than blocked.
- Be specific in findings. Say exactly what is wrong or what is missing.
- If everything looks correct, say so clearly — don't hedge without reason."""


# ── Node ──────────────────────────────────────────────────────────────

def primary_review_node(state: WorkbenchState) -> dict:
    """
    Node: primary_review

    1. Reads the queued task, worker report, and git diff.
    2. Checks inbox for worker questions or human input.
    3. Calls the primary_reviewer LLM for structured review.
    4. Writes a review note to the project vault.
    5. Returns the decision for graph routing.
    """
    with trace_node("primary_review", state) as span:
        vault_root = Path(state.get("project_vault_root", ""))
        task_filename = state.get("current_task_filename", "")
        thread_id = state.get("discourse_thread_id", "")

        # ── Check inbox for messages from worker or human ────────────
        _check_reviewer_inbox(vault_root, thread_id)
        worker_report_path = state.get("worker_report_path", "")

        if not vault_root.exists() or not task_filename:
            span.set_output({"decision": "revise", "error": "missing_vault_or_filename"})
            return {
                "current_node": "primary_review",
                "human_questions": ["Missing vault root or task filename."],
                "primary_review_decision": "revise",
            }

        # ── Gather review inputs ──────────────────────────────────────
        task_content = ""
        task_path = vault_root / "queue-tasks" / "review-needed" / task_filename
        if task_path.exists():
            task_content = task_path.read_text()

        report_content = ""
        if worker_report_path:
            report_path = vault_root.parent.parent / worker_report_path
            if report_path.exists():
                report_content = report_path.read_text()

        diff_summary = state.get("git_diff_summary", "")
        escalation_tier = state.get("escalation_tier", "low")
        files_changed = state.get("files_changed", [])

        # ── Build prompt ─────────────────────────────────────────────
        user_prompt = _build_review_prompt(
            task_content=task_content,
            report_content=report_content,
            diff_summary=diff_summary,
            escalation_tier=escalation_tier,
            files_changed=files_changed,
        )

        if len(user_prompt) > 32000:
            user_prompt = user_prompt[:32000] + "\n\n... (content truncated for length)"

        # ── Call LLM ─────────────────────────────────────────────────
        try:
            result = call_llm(
                role="primary_reviewer",
                system_prompt=PRIMARY_REVIEW_SYSTEM,
                user_prompt=user_prompt,
                output_schema=PrimaryReviewResult,
                fallback=PrimaryReviewResult(
                    decision="revise",
                    findings="LLM call failed during primary review. Cannot automatically approve.",
                    risks="Review was not completed due to model error.",
                    scope_check_passed=False,
                    evidence_sufficient=False,
                ),
                project_policy=state.get("model_policy"),
                project_id=state.get("project_id", ""),
                policy_ctx={
                    "escalation_tier": escalation_tier,
                    "task_type": state.get("task_type", ""),
                },
            )
        except ModelPolicyError as e:
            logger.error("Policy denied: %s", e)
            span.set_output({"decision": "blocked", "error": "policy_denied"})
            return {
                "current_node": "primary_review",
                "primary_review_decision": "blocked",
                "primary_review_path": "",
                "decision_rationale": f"Model policy denied: {e}",
                "human_questions": [
                    f"Model policy denied for primary reviewer: {e}",
                    "Check project model_policy configuration.",
                ],
                "human_approval_required": True,
                "transition_blocked": True,
            }
        except Exception:
            result = PrimaryReviewResult(
                decision="revise",
                findings="LLM call failed with exception.",
                risks="Review incomplete.",
                scope_check_passed=False,
                evidence_sufficient=False,
            )

        # ── Write review note ─────────────────────────────────────────
        review_path = _write_review_note(
            vault_root=vault_root,
            task_filename=task_filename,
            result=result,
            escalation_tier=escalation_tier,
            state=state,
        )

        relative_review_path = str(review_path.relative_to(vault_root))

        span.set_output({
            "decision": result.decision,
            "scope_check_passed": result.scope_check_passed,
            "evidence_sufficient": result.evidence_sufficient,
        })
        return {
            "current_node": "primary_review",
            "primary_review_decision": result.decision,
            "primary_review_path": relative_review_path,
            "decision_rationale": result.findings,
        }


# ── Helpers ───────────────────────────────────────────────────────────

def _check_reviewer_inbox(vault_root: Path, thread_id: str) -> None:
    """Check primary reviewer inbox for pending messages."""
    if not thread_id or not vault_root.exists():
        return
    pending = msg.has_pending_messages(vault_root, "primary_reviewer", thread_id=thread_id)
    if pending:
        logger.info("primary_reviewer has pending messages in thread %s", thread_id)


def _build_review_prompt(
    task_content: str,
    report_content: str,
    diff_summary: str,
    escalation_tier: str,
    files_changed: list[str],
) -> str:
    """Build the primary review prompt from vault artifacts."""
    parts = []

    # Task scope
    if task_content:
        if len(task_content) > 6000:
            task_content = task_content[:6000] + "\n... (task truncated)"
        parts.append(f"## Queued Task\n\n{task_content}")

    # Worker report
    if report_content:
        if len(report_content) > 6000:
            report_content = report_content[:6000] + "\n... (report truncated)"
        parts.append(f"## Worker Report\n\n{report_content}")
    else:
        parts.append("## Worker Report\n\nNo report provided.")

    # Files changed
    if files_changed:
        parts.append(f"## Files Changed\n\n" + "\n".join(f"- {f}" for f in files_changed))

    # Git diff
    if diff_summary:
        if len(diff_summary) > 8000:
            diff_summary = diff_summary[:8000] + "\n... (diff truncated)"
        parts.append(f"## Git Diff Summary\n\n{diff_summary}")

    # Escalation context
    parts.append(f"## Review Context\n\nEscalation tier: {escalation_tier}")

    # Instructions
    parts.append(
        "\n## Instructions\n\n"
        "Review the worker's implementation against the task scope and "
        "acceptance bar. Produce your decision, findings, and risk assessment."
    )

    return "\n\n".join(parts)


def _write_review_note(
    vault_root: Path,
    task_filename: str,
    result: PrimaryReviewResult,
    escalation_tier: str,
    state: WorkbenchState,
) -> Path:
    """Write the primary review note to the project vault."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    review_filename = f"review-primary-{task_filename}"

    review_dir = vault_root / "queue-tasks" / "review-needed"
    review_dir.mkdir(parents=True, exist_ok=True)
    review_path = review_dir / review_filename

    content = f"""---
type: review
status: complete
created: {now}
reviewer: workbench-orchestrator
reviewer_role: primary
reviewer_model: {state.get("primary_reviewer_model", "unknown")}
task: {task_filename}
report: {state.get("worker_report_path", "")}
decision: {result.decision}
escalation_tier: {escalation_tier}
scope_check_passed: {str(result.scope_check_passed).lower()}
evidence_sufficient: {str(result.evidence_sufficient).lower()}
subsystems: []
---

# Primary Review

## Task

{task_filename}

## Report

{state.get("worker_report_path", "")}

## Decision

{result.decision}

## Scope Check

{'Passed' if result.scope_check_passed else 'Failed — diff exceeded task scope'}

## Evidence Check

{'Sufficient' if result.evidence_sufficient else 'Insufficient — validation evidence missing or incomplete'}

## Findings

{result.findings}

## Risks

{result.risks}

## Next Action

Decision: {result.decision}
"""
    review_path.write_text(content)
    return review_path
