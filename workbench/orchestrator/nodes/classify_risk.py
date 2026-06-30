"""
Classify risk level and escalation tier for a queued task.

Determines risk_level (low/high) and escalation_tier (low/high) using
the configured classifier model (routing.yaml), guided by the review
escalation policy.

Revision-based escalation is applied as a hard override before the LLM call:
  revision >= 3 → high/high
  revision >= 2 → high/high
"""

from ..state import WorkbenchState
from ..llm_client import call_llm
from ..model_policy import ModelPolicyError
from ..tracing import trace_node
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)


# ── Structured output schema ──────────────────────────────────────────

class RiskClassification(BaseModel):
    risk_level: Literal["low", "high"] = Field(
        description="The assessed risk level: 'low' for routine/safe changes, "
                    "'high' for changes that could hide subtle regressions"
    )
    escalation_tier: Literal["low", "high"] = Field(
        description="The review escalation tier. Must match risk_level unless "
                    "revision count overrides it."
    )
    rationale: str = Field(
        description="One or two sentences explaining why this risk level was chosen"
    )


# ── System prompt ─────────────────────────────────────────────────────

CLASSIFY_RISK_SYSTEM = """You are a risk classifier for a software engineering workbench.

Classify the risk level and escalation tier for the task described below.

## Risk Levels

**low risk** — Use for:
- docs and reporting tasks
- queue hygiene and bookkeeping
- small scoped refactors with low behavioral risk
- obvious bug fixes with narrow blast radius
- simple config or naming cleanup

**high risk** — Use for:
- frame lifecycle and shutdown behavior
- render/present ordering
- threading and ownership changes
- input routing and pause/menu state
- shared engine/runtime abstractions
- tasks likely to hide subtle regressions even if they compile
- security, authentication, or cryptographic changes
- database schema changes or migrations

## Rules

- escalation_tier must match risk_level (they are the same value for initial
  classification; revision count overrides them later).
- If the task type is "docs" or "investigation", default to low risk unless
  the investigation touches high-risk subsystems.
- If the task mentions multiple high-risk keywords from the list above,
  classify as high risk.
- When uncertain, err toward low risk — the revision escalation policy will
  promote to high after repeated failures anyway."""


# ── Node ──────────────────────────────────────────────────────────────

def classify_risk_node(state: WorkbenchState) -> dict:
    """
    Node: classify_risk

    Classifies risk_level and escalation_tier:
    1. Hard override: revision >= 2 forces high/high.
    2. LLM call for initial classification on revision 0 or 1.
    """
    with trace_node("classify_risk", state) as span:
        task_type = state.get("task_type", "implementation")
        user_request = state.get("user_request", "")
        revision_count = state.get("revision_count", 0)
        vault_root = state.get("project_vault_root", "")

        # ── Hard override: revision-based escalation ──────────────────
        if revision_count >= 3:
            span.set_output({"risk_level": "high", "escalation_tier": "high", "override": "revision>=3"})
            return {
                "risk_level": "high",
                "escalation_tier": "high",
                "current_node": "classify_risk",
            }
        if revision_count >= 2:
            span.set_output({"risk_level": "high", "escalation_tier": "high", "override": "revision>=2"})
            return {
                "risk_level": "high",
                "escalation_tier": "high",
                "current_node": "classify_risk",
            }

        # ── LLM classification for initial risk ──────────────────────
        subsystems_context = _gather_subsystem_context(vault_root)
        user_prompt = _build_risk_prompt(
            user_request, task_type, subsystems_context
        )

        try:
            result = call_llm(
                role="classifier",
                system_prompt=CLASSIFY_RISK_SYSTEM,
                user_prompt=user_prompt,
                output_schema=RiskClassification,
                fallback=RiskClassification(
                    risk_level="low",
                    escalation_tier="low",
                    rationale="LLM call failed, defaulting to low risk",
                ),
                project_policy=state.get("model_policy"),
                project_id=state.get("project_id", ""),
                policy_ctx={
                    "task_type": task_type,
                },
            )
        except ModelPolicyError as e:
            logger.error("Policy denied: %s", e)
            span.set_output({"error": "policy_denied"})
            return {
                "risk_level": "high",
                "escalation_tier": "high",
                "human_questions": [f"Model policy denied: {e}"],
                "transition_blocked": True,
                "current_node": "classify_risk",
            }
        except Exception:
            result = RiskClassification(
                risk_level="low",
                escalation_tier="low",
                rationale="LLM call failed with exception",
            )

        updates = {
            "risk_level": result.risk_level,
            "escalation_tier": result.escalation_tier,
            "current_node": "classify_risk",
        }
        span.set_output({"risk_level": result.risk_level, "escalation_tier": result.escalation_tier})
        return updates


# ── Helpers ───────────────────────────────────────────────────────────

def _gather_subsystem_context(vault_root: str) -> str:
    """Read system maps relevant to risk classification."""
    if not vault_root:
        return ""
    systems_dir = Path(vault_root) / "systems"
    if not systems_dir.exists():
        return ""
    parts = []
    for f in sorted(systems_dir.glob("*.md")):
        if f.name != "README.md":
            content = f.read_text()
            if len(content) > 1500:
                content = content[:1500] + "\n... (truncated)"
            parts.append(f"### {f.stem}\n\n{content}")
    return "\n\n".join(parts) if parts else ""


def _build_risk_prompt(
    user_request: str, task_type: str, subsystems_context: str
) -> str:
    """Build the risk classification prompt."""
    parts = [
        f"## Task Type\n\n{task_type}",
        f"## User Request\n\n{user_request}",
    ]

    if subsystems_context:
        parts.append(f"## Relevant Subsystems\n\n{subsystems_context}")

    parts.append(
        "\n## Instructions\n\n"
        "Classify the risk level and escalation tier for this task."
    )

    return "\n\n".join(parts)
