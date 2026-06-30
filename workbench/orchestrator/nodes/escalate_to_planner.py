"""
Escalate to supervisor/planner node.

Triggered when revision_count >= 3. The escalation-fallback model
(secondary_reviewer / Codex) re-scopes or rewrites the task instead
of continuing the revise loop.

The supervisor/planner is conceptually distinct from the primary reviewer.
This node uses the same model as the secondary reviewer but at a different
trigger (revision exhaustion vs high escalation tier).
"""

from ..state import WorkbenchState
from ..llm_client import call_llm_text
from ..model_policy import ModelPolicyError
from ..tracing import trace_node
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


# ── System prompt ─────────────────────────────────────────────────────

PLANNER_SYSTEM = """You are an escalation-fallback planner for a software engineering workbench.

A task has failed review THREE OR MORE TIMES. Cheaper worker/reviewer loops
have not been able to complete it. Your job is to re-scope, rewrite, or split
the task so it can succeed.

## What To Do

1. Read the original task request and the review feedback.
2. Identify WHY the task keeps failing:
   - Is the scope too broad?
   - Are the requirements unclear?
   - Is there a fundamental design conflict?
   - Did the worker misunderstand what was needed?
3. Re-scope the task: make it narrower, clearer, or split into sub-tasks.
4. Produce a rewritten implementation request that a worker can follow.

## Output

Write a clear, scoped implementation request. Include:
- A concise goal statement (1-2 sentences)
- Concrete scope (what is in bounds, what is out of bounds)
- The likely files or subsystems involved
- An acceptance bar (how to know when it's done)

## Rules

- Make the task SMALLER and CLEARER than the original.
- Focus on one deliverable. Do not create a multi-phase epic.
- If the original was ambiguous, add explicit constraints.
- If the original was too large, narrow it to the smallest useful slice.
- Respond with ONLY the re-scoped task description — no preamble, no commentary."""


# ── Node ──────────────────────────────────────────────────────────────

def escalate_to_planner_node(state: WorkbenchState) -> dict:
    """
    Node: escalate_to_planner

    1. Gathers task history from vault and state.
    2. Calls the escalation-fallback model (Codex) via call_llm_text.
    3. Produces a re-scoped user_request for queue_task to write.
    """
    with trace_node("escalate_to_planner", state) as span:
        task_filename = state.get("current_task_filename", "")
        revision_count = state.get("revision_count", 0)
        original_request = state.get("user_request", "")
        vault_root = Path(state.get("project_vault_root", ""))
        project_id = state.get("project_id", "")

        # ── Gather review history from vault ──────────────────────────
        review_history = _gather_review_history(vault_root, task_filename)
        decision_rationale = state.get("decision_rationale", "")

        # ── Build prompt ─────────────────────────────────────────────
        user_prompt = _build_planner_prompt(
            original_request=original_request,
            revision_count=revision_count,
            review_history=review_history,
            decision_rationale=decision_rationale,
        )

        if len(user_prompt) > 16000:
            user_prompt = user_prompt[:16000] + "\n\n... (truncated)"

        # ── Call escalation-fallback model ───────────────────────────
        try:
            re_scoped = call_llm_text(
                role="secondary_reviewer",
                system_prompt=PLANNER_SYSTEM,
                user_prompt=user_prompt,
                fallback=(
                    f"[RE-SCOPED after {revision_count} revisions] "
                    f"Original request: {original_request}. "
                    f"Scope narrowed — implement only the core deliverable. "
                    f"Validation required. Report required."
                ),
                project_policy=state.get("model_policy"),
                project_id=project_id,
                policy_ctx={
                    "escalation_tier": state.get("escalation_tier", ""),
                    "task_type": state.get("task_type", ""),
                },
            )
        except ModelPolicyError as e:
            logger.error("Policy denied: %s", e)
            span.set_output({"error": "policy_denied", "escalated": False})
            return {
                "current_node": "escalate_to_planner",
                "human_questions": [
                    f"Planner escalation blocked by model policy: {e}",
                ],
                "human_approval_required": True,
                "transition_blocked": True,
            }
        except Exception:
            logger.exception("Planner LLM call failed")
            re_scoped = (
                f"[RE-SCOPED after {revision_count} revisions] "
                f"Original request: {original_request}. "
                f"Planner LLM call failed. Task re-queued with original scope."
            )

        span.set_output({
            "revision_count_before_reset": revision_count,
            "escalated": True,
            "re_scoped_length": len(re_scoped),
        })

        return {
            "current_node": "escalate_to_planner",
            "revision_count": 0,
            "task_type": "implementation",
            "user_request": (
                f"[RE-SCOPED after {revision_count} revisions]\n\n{re_scoped}"
            ),
            "decision_rationale": (
                f"Escalated to planner after {revision_count} "
                f"failed revisions. Task has been re-scoped."
            ),
        }


# ── Helpers ───────────────────────────────────────────────────────────

def _gather_review_history(vault_root: Path, task_filename: str) -> str:
    """Read review notes from the vault for this task."""
    if not vault_root.exists() or not task_filename:
        return ""

    parts = []

    # Check review-needed/ for review notes
    review_dir = vault_root / "queue-tasks" / "review-needed"
    if review_dir.exists():
        for pattern in [f"review-primary-{task_filename}", f"review-secondary-{task_filename}"]:
            review_path = review_dir / pattern
            if review_path.exists():
                content = review_path.read_text()
                if len(content) > 3000:
                    content = content[:3000] + "\n... (truncated)"
                parts.append(content)

    # Also check for task files that may have been revised
    for folder in ["review-needed", "open", "claimed"]:
        task_path = vault_root / "queue-tasks" / folder / task_filename
        if task_path.exists() and folder != "review-needed":
            # We already have the review-needed task content from state
            pass

    return "\n\n---\n\n".join(parts) if parts else ""


def _build_planner_prompt(
    original_request: str,
    revision_count: int,
    review_history: str,
    decision_rationale: str,
) -> str:
    """Build the planner prompt with task history."""
    parts = [
        f"## Original Request\n\n{original_request}",
        f"\n## Revision History\n\nThis task has been revised {revision_count} times and failed review each time.",
    ]

    if decision_rationale:
        parts.append(f"\n## Most Recent Review Feedback\n\n{decision_rationale}")

    if review_history:
        parts.append(f"\n## Review History From Vault\n\n{review_history}")

    parts.append(
        "\n## Instructions\n\n"
        "Re-scope this task so a worker can successfully implement it. "
        "Make it narrower, clearer, and more specific than the original. "
        "Write the re-scoped request below."
    )

    return "\n\n".join(parts)
