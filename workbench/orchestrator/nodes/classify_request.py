"""
Classify the user request into a task_type and workflow_intent.

Reads the user request from state, gathers project vault context, and
classifies the request using the configured classifier model (routing.yaml).

Task types: implementation | docs | refactor | investigation
Workflow intents: task | plan_kickoff
"""

from ..state import WorkbenchState
from ..llm_client import call_llm
from ..model_policy import ModelPolicyError
from ..plan_kickoff import build_plan_kickoff_prompt_hint, looks_like_plan_kickoff
from ..tracing import trace_node
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)


# ── Structured output schema ──────────────────────────────────────────

class TaskClassification(BaseModel):
    task_type: Literal["implementation", "docs", "refactor", "investigation"] = Field(
        description="The classified task type"
    )
    workflow_intent: Literal["task", "plan_kickoff"] = Field(
        description="Whether this is a normal task or a kickoff request for an existing plan"
    )
    confidence: float = Field(
        description="Confidence 0.0-1.0. Use 0.7+ when the classification is clear, "
                    "below 0.5 when highly uncertain. Low confidence triggers "
                    "a human-approval checkpoint."
    )
    rationale: str = Field(
        description="One-sentence explanation of why this classification was chosen"
    )


# ── System prompt ─────────────────────────────────────────────────────

CLASSIFY_REQUEST_SYSTEM = """You are a task classifier for a software engineering workbench.

Classify the user's request into exactly one of these task types:

- **implementation**: Writing new code, adding features, fixing bugs, building
  functionality. Involves creating or modifying source files.
- **docs**: Writing or updating documentation, READMEs, guides, comments.
  Does not change runtime behavior.
- **refactor**: Restructuring existing code without changing external behavior.
  Renaming, extracting functions, moving files, cleaning up.
- **investigation**: Debugging, researching, finding root causes, understanding
  behavior. May involve reading code but not changing it.

Classify the workflow intent into exactly one of these values:

- **task**: A normal request that should proceed through the usual queue flow.
- **plan_kickoff**: The operator is asking the workbench to start from an
  existing plan, feature brief, roadmap, or current-state note. This is not a
  different task type; it is a kickoff posture for the first reply and queued
  task instructions.

Rules:
- If the request asks to both investigate AND implement, classify as implementation.
- If the request is plan-oriented, set workflow_intent to plan_kickoff even if
  the underlying task_type is implementation.
- If the request is ambiguous, choose the most likely type and set confidence < 0.7.
- Be conservative with confidence: only assign 0.9+ when the request is unambiguous."""


# ── Node ──────────────────────────────────────────────────────────────

def classify_request_node(state: WorkbenchState) -> dict:
    """
    Node: classify_request

    Classifies the user's request into a task_type using the configured
    classifier model. Low confidence triggers a human-approval checkpoint.
    """
    with trace_node("classify_request", state) as span:
        user_request = state.get("user_request", "")
        vault_root = state.get("project_vault_root", "")

        if not user_request.strip():
            updates = {
                "task_type": "implementation",
                "workflow_intent": "task",
                "classification_confidence": 0.3,
                "human_questions": ["User request is empty. Please describe the task."],
                "human_approval_required": True,
                "current_node": "classify_request",
            }
            span.set_output({
                "task_type": "implementation",
                "workflow_intent": "task",
                "confidence": 0.3,
                "empty_request": True,
            })
            return updates

        context = _gather_classification_context(vault_root)
        kickoff_hint = build_plan_kickoff_prompt_hint(user_request)
        user_prompt = _build_classification_prompt(user_request, context, kickoff_hint)

        try:
            result = call_llm(
                role="classifier",
                system_prompt=CLASSIFY_REQUEST_SYSTEM,
                user_prompt=user_prompt,
                output_schema=TaskClassification,
                fallback=TaskClassification(
                    task_type="implementation",
                    workflow_intent="task",
                    confidence=0.3,
                    rationale="LLM call failed, defaulting to implementation",
                ),
                project_policy=state.get("model_policy"),
                project_id=state.get("project_id", ""),
                policy_ctx={
                    "task_type": state.get("task_type", ""),
                },
            )
        except ModelPolicyError as e:
            logger.error("Policy denied: %s", e)
            span.set_output({
                "error": "policy_denied",
                "role": e.role,
                "workflow_intent": "task",
            })
            return {
                "task_type": "implementation",
                "workflow_intent": "task",
                "classification_confidence": 0.1,
                "human_questions": [
                    f"Model policy denied: {e}",
                    "Task cannot proceed. Check project model_policy configuration.",
                ],
                "human_approval_required": True,
                "transition_blocked": True,
                "current_node": "classify_request",
            }
        except Exception:
            result = TaskClassification(
                task_type="implementation",
                workflow_intent="task",
                confidence=0.3,
                rationale="LLM call failed with exception",
            )

        if looks_like_plan_kickoff(user_request) and result.workflow_intent != "plan_kickoff":
            result.workflow_intent = "plan_kickoff"

        # ── Spec detection: long, structured requests get discussion intent ─
        if _looks_like_spec(user_request):
            result.workflow_intent = "discussion"
            spec_type = _detect_spec_task_type(user_request)
            if spec_type:
                result.task_type = spec_type
            if result.confidence > 0.3:
                result.confidence = max(0.3, result.confidence - 0.2)

        human_questions = []
        if result.confidence < 0.7:
            human_questions = [
                f"Low confidence classification ({result.confidence:.2f}). "
                f"Predicted: {result.task_type} / {result.workflow_intent}. "
                f"Rationale: {result.rationale}. Is this correct?"
            ]

        updates = {
            "task_type": result.task_type,
            "workflow_intent": result.workflow_intent,
            "classification_confidence": result.confidence,
            "human_questions": human_questions,
            "human_approval_required": result.confidence < 0.7,
            "current_node": "classify_request",
        }
        span.set_output({
            "task_type": result.task_type,
            "workflow_intent": result.workflow_intent,
            "confidence": result.confidence,
        })
        return updates


# ── Helpers ───────────────────────────────────────────────────────────

def _gather_classification_context(vault_root: str) -> str:
    """Read relevant vault files to provide project context."""
    context_parts = []

    features_readme = Path(vault_root) / "features" / "README.md"
    if features_readme.exists():
        content = features_readme.read_text()
        if len(content) > 2000:
            content = content[:2000] + "\n... (truncated)"
        context_parts.append(f"## Project Features\n\n{content}")

    current_state = Path(vault_root) / "memory" / "current-state.md"
    if current_state.exists():
        content = current_state.read_text()
        if len(content) > 2000:
            content = content[:2000] + "\n... (truncated)"
        context_parts.append(f"## Current Project State\n\n{content}")

    return "\n\n".join(context_parts) if context_parts else ""


def _looks_like_spec(request: str) -> bool:
    """Detect if a request looks like a spec document rather than a simple task."""
    if not request or len(request) < 500:
        return False

    lines = request.strip().split("\n")
    header_count = sum(1 for l in lines if l.strip().startswith("#"))
    list_count = sum(1 for l in lines if l.strip().startswith("-") or l.strip().startswith("*"))
    section_keywords = sum(
        1 for l in lines
        if any(kw in l.lower() for kw in ["overview", "background", "scope",
                                          "requirements", "specification",
                                          "architecture", "design", "acceptance",
                                          "goal", "objective", "features",
                                          "subsystems", "implementation"])
    )

    return (
        (header_count >= 3 and list_count >= 5)
        or (section_keywords >= 4 and len(lines) >= 20)
        or len(request) >= 2000
    )


def _detect_spec_task_type(request: str) -> str:
    """Detect the primary task type from a spec document."""
    lower = request.lower()
    type_scores = {
        "implementation": lower.count("implement") + lower.count("feature") + lower.count("build"),
        "refactor": lower.count("refactor") + lower.count("restructure") + lower.count("rewrite"),
        "docs": lower.count("document") + lower.count("readme") + lower.count("doc"),
        "investigation": lower.count("investigat") + lower.count("research") + lower.count("explore"),
    }
    best = max(type_scores, key=type_scores.get)  # type: ignore[arg-type]
    return best if type_scores[best] > 0 else "implementation"


def _build_classification_prompt(user_request: str, context: str, kickoff_hint: str = "") -> str:
    """Build the user prompt for classification."""
    parts = [f"## User Request\n\n{user_request}"]

    if context:
        parts.append(context)

    if kickoff_hint:
        parts.append(kickoff_hint)

    parts.append(
        "\n## Instructions\n\n"
        "Classify this request into one task type, one workflow intent, and provide your confidence."
    )

    return "\n\n".join(parts)
