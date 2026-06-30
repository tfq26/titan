"""
Secondary review node.

Reserved for high-escalation tasks. The secondary reviewer (Codex)
inspects the task/report/diff for subtle issues: lifecycle bugs,
threading problems, ownership violations, architecture concerns,
and regression risks.

Returns a recommendation to the primary reviewer, who makes the final call.
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

class SecondaryReviewResult(BaseModel):
    decision: Literal["confirm", "concern", "revise", "blocked"] = Field(
        description="The secondary review recommendation"
    )
    findings: str = Field(
        description="What the secondary reviewer agrees with or disagrees with "
                    "from the primary review. Be specific about what was confirmed "
                    "and what concerns exist."
    )
    risk_check: str = Field(
        description="Deep analysis of subtle behavioral, lifecycle, ownership, "
                    "threading, or architectural concerns. Focus on what the "
                    "primary reviewer may have missed."
    )


# ── System prompt ─────────────────────────────────────────────────────

SECONDARY_REVIEW_SYSTEM = """You are a secondary reviewer (Codex) for a software engineering workbench.

You are the escalation tier. You only see high-risk tasks that passed primary
review. Your job is to catch what the cheaper primary reviewer may have missed.
When you speak about yourself in prose, use your nickname as the identity and
the role name as the job title.

## What To Check

1. **Threading and concurrency**: Are there race conditions, deadlock risks,
   or unsafe shared-state access? Was thread safety considered?

2. **Lifecycle and ownership**: Are resources properly acquired and released?
   Is ownership clear? Are there use-after-free or double-free risks?

3. **Render/present ordering**: If relevant, could the change cause visual
   artifacts, frame drops, or ordering bugs?

4. **State machine integrity**: Could the change introduce invalid state
   transitions or leave the system in an inconsistent state?

5. **Architectural regression**: Does the change undermine existing abstraction
   boundaries? Does it introduce tight coupling where loose coupling existed?

6. **Input/pause/menu state**: If relevant, could the change cause input to
   be routed incorrectly or the pause/menu system to behave unexpectedly?

7. **Edge cases**: What happens on error paths, with empty/null inputs, at
   boundary conditions, or under load?

## Decision Guide

- **confirm**: Primary reviewer assessment is correct. The change looks safe.
  Proceed to completion.
- **concern**: Primary reviewer is mostly correct but there are specific
  concerns the primary reviewer should consider before finalizing. The change
  may still be acceptable with the concerns noted.
- **revise**: The change has issues the primary reviewer missed. The worker
  should revise before this can be accepted.
- **blocked**: The change introduces a serious risk that should block
  completion entirely.

## Rules

- Be specific. Vague concerns are not actionable.
- Do not confirm unless you've actually checked for subtle issues.
- If you find no problems, say so clearly with confidence — don't hedge.
- If the primary reviewer already flagged a concern in their review, note
  whether you agree and whether it was adequately addressed.
- Focus on what matters. Don't flag harmless style preferences as risks."""


# ── Node ──────────────────────────────────────────────────────────────

def secondary_review_node(state: WorkbenchState) -> dict:
    """
    Node: secondary_review

    1. Reads task, worker report, and primary review.
    2. Checks inbox for messages from primary reviewer or human.
    3. Calls the secondary_reviewer LLM (Codex) for deep analysis.
    4. Writes a secondary review note to the project vault.
    5. Returns a recommendation for the primary reviewer's final decision.
    """
    with trace_node("secondary_review", state) as span:
        vault_root = Path(state.get("project_vault_root", ""))
        task_filename = state.get("current_task_filename", "")
        primary_review_path = state.get("primary_review_path", "")
        worker_report_path = state.get("worker_report_path", "")
        thread_id = state.get("discourse_thread_id", "")

        # ── Check inbox for messages ─────────────────────────────────
        if thread_id and vault_root.exists():
            pending = msg.has_pending_messages(vault_root, "secondary_reviewer", thread_id=thread_id)
            if pending:
                logger.info("secondary_reviewer has pending messages in thread %s", thread_id)

        if not vault_root.exists() or not task_filename:
            span.set_output({"decision": "concern", "error": "missing_vault_or_filename"})
            return {
                "current_node": "secondary_review",
                "secondary_review_decision": "concern",
                "human_questions": ["Missing vault root or task filename."],
            }

    # ── Gather review inputs ──────────────────────────────────────────
    primary_review_content = ""
    if primary_review_path:
        pr_path = vault_root / primary_review_path
        if pr_path.exists():
            primary_review_content = pr_path.read_text()

    report_content = ""
    if worker_report_path:
        rp = vault_root.parent.parent / worker_report_path
        if rp.exists():
            report_content = rp.read_text()

    task_content = ""
    task_path = vault_root / "queue-tasks" / "review-needed" / task_filename
    if task_path.exists():
        task_content = task_path.read_text()

    # ── Build prompt ─────────────────────────────────────────────────
    user_prompt = _build_secondary_review_prompt(
        task_content=task_content,
        report_content=report_content,
        primary_review_content=primary_review_content,
    )

    if len(user_prompt) > 40000:
        user_prompt = user_prompt[:40000] + "\n\n... (content truncated for length)"

    # ── Call LLM ──────────────────────────────────────────────────────
    try:
        result = call_llm(
            role="secondary_reviewer",
            system_prompt=SECONDARY_REVIEW_SYSTEM,
            user_prompt=user_prompt,
            output_schema=SecondaryReviewResult,
            fallback=SecondaryReviewResult(
                decision="concern",
                findings="LLM call failed during secondary review.",
                risk_check="Secondary review could not be completed due to model error.",
            ),
            project_policy=state.get("model_policy"),
            project_id=state.get("project_id", ""),
            policy_ctx={
                "escalation_tier": state.get("escalation_tier", ""),
                "task_type": state.get("task_type", ""),
            },
        )
    except ModelPolicyError as e:
        logger.error("Policy denied: %s", e)
        span.set_output({"decision": "blocked", "error": "policy_denied"})
        return {
            "current_node": "secondary_review",
            "secondary_review_decision": "blocked",
            "human_questions": [f"Model policy denied: {e}"],
            "human_approval_required": True,
            "transition_blocked": True,
        }
    except Exception:
        result = SecondaryReviewResult(
            decision="concern",
            findings="LLM call failed with exception.",
            risk_check="Secondary review incomplete.",
        )

    # ── Write review note ─────────────────────────────────────────────
    review_path = _write_secondary_review_note(
        vault_root=vault_root,
        task_filename=task_filename,
        result=result,
        state=state,
    )

    relative_review_path = str(review_path.relative_to(vault_root))

    span.set_output({"decision": result.decision})
    return {
        "current_node": "secondary_review",
        "secondary_review_decision": result.decision,
        "secondary_review_path": relative_review_path,
        "decision_rationale": result.risk_check,
    }


# ── Helpers ───────────────────────────────────────────────────────────

def _build_secondary_review_prompt(
    task_content: str,
    report_content: str,
    primary_review_content: str,
) -> str:
    """Build the secondary review prompt."""
    parts = []

    # Task scope
    if task_content:
        if len(task_content) > 4000:
            task_content = task_content[:4000] + "\n... (truncated)"
        parts.append(f"## Queued Task\n\n{task_content}")

    # Worker report
    if report_content:
        if len(report_content) > 4000:
            report_content = report_content[:4000] + "\n... (truncated)"
        parts.append(f"## Worker Report\n\n{report_content}")
    else:
        parts.append("## Worker Report\n\nNo report provided.")

    # Primary review
    if primary_review_content:
        if len(primary_review_content) > 6000:
            primary_review_content = primary_review_content[:6000] + "\n... (truncated)"
        parts.append(f"## Primary Review\n\n{primary_review_content}")
    else:
        parts.append("## Primary Review\n\nNo primary review available.")

    # Instructions
    parts.append(
        "\n## Instructions\n\n"
        "This is a high-escalation task. The primary reviewer passed it, but "
        "you must check for subtle issues they may have missed. Review the "
        "task, report, and primary review. Produce your recommendation."
    )

    return "\n\n".join(parts)


def _write_secondary_review_note(
    vault_root: Path,
    task_filename: str,
    result: SecondaryReviewResult,
    state: WorkbenchState,
) -> Path:
    """Write the secondary review note to the project vault."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    review_filename = f"review-secondary-{task_filename}"

    review_dir = vault_root / "queue-tasks" / "review-needed"
    review_dir.mkdir(parents=True, exist_ok=True)
    review_path = review_dir / review_filename

    content = f"""---
type: review
status: complete
created: {now}
reviewer_role: secondary
reviewer_model: {state.get("secondary_reviewer_model", "unknown")}
task: {task_filename}
report: {state.get("worker_report_path", "")}
primary_review: {state.get("primary_review_path", "")}
decision: {result.decision}
subsystems: []
---

# Secondary Review

## Task

{task_filename}

## Report

{state.get("worker_report_path", "")}

## Primary Review

{state.get("primary_review_path", "")}

## Decision

{result.decision}

## Findings

{result.findings}

## Risk Check

{result.risk_check}

## Recommendation Back To Primary

Decision: {result.decision}
"""
    review_path.write_text(content)
    return review_path
