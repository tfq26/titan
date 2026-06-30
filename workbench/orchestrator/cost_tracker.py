"""
Cost tracking and budget enforcement for LLM calls.

Tracks accumulated spend per task role and enforces budgets from
routing.yaml's cost_limits section. Works with call_llm_text by
recording token usage after each call.

Model pricing (USD per 1K tokens):
  If a model is not in the table, defaults are used based on provider.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# USD per 1K tokens (input, output) for known models
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-3-5-sonnet": (3.0, 15.0),
    "claude-3-5-haiku": (0.8, 4.0),
    "claude-opus-4-5": (15.0, 75.0),
    # OpenAI
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    "o4-mini": (1.1, 4.4),
    # Google
    "gemini-2.5-flash-lite": (0.015, 0.06),
    "gemini-3-flash-preview": (0.04, 0.15),
    "gemini-3.1-flash-lite": (0.075, 0.30),
    "gemini-3.1-pro-preview": (0.50, 2.0),
    # Generic fallbacks
    "anthropic_default": (8.0, 24.0),
    "openai_default": (2.0, 8.0),
    "openai_compatible_default": (0.50, 2.0),
    "google_default": (0.50, 1.5),
}

PROVIDER_DEFAULTS = {
    "anthropic": "anthropic_default",
    "openai": "openai_default",
    "openai_compatible": "openai_compatible_default",
    "google": "google_default",
}


def _estimate_cost(model_id: str, provider: str, in_tokens: int, out_tokens: int) -> float:
    """Estimate cost in USD for a given number of tokens."""
    # Try exact model match, then provider default
    pricing = MODEL_PRICING.get(model_id)
    if pricing is None:
        default_key = PROVIDER_DEFAULTS.get(provider)
        pricing = MODEL_PRICING.get(default_key, (0.50, 2.0))

    in_price_per_k, out_price_per_k = pricing
    cost = (in_tokens / 1000) * in_price_per_k + (out_tokens / 1000) * out_price_per_k
    return cost


def _load_cost_limits(vault_root: Path) -> dict[str, float]:
    """Read cost_limits from routing.yaml."""
    routing_path = vault_root / "model-routing" / "routing.yaml"
    if not routing_path.exists():
        return {}
    try:
        import yaml
        with open(routing_path) as f:
            routing = yaml.safe_load(f) or {}
        limits = routing.get("cost_limits", {})
        result = {}
        for role, cfg in limits.items():
            max_cost = cfg.get("max_cost_per_task_usd", 0) if isinstance(cfg, dict) else 0
            if max_cost > 0:
                result[role] = max_cost
        return result
    except Exception as e:
        logger.warning("Failed to load cost limits: %s", e)
        return {}


class CostTracker:
    """
    Tracks accumulated LLM spend per role for a single task.

    Usage:
        tracker = CostTracker(vault_root)
        tracker.set_task_id("TASK-123")
        token_usage = {}
        call_llm_text(..., token_usage=token_usage)
        tracker.record("worker", token_usage)
        tracker.check_budget("worker")  # raises if exceeded
    """

    def __init__(self, vault_root: str | Path):
        self.vault_root = Path(vault_root)
        self._task_id: str = ""
        # {role: {"in_tokens": 0, "out_tokens": 0, "call_count": 0, "cost": 0.0}}
        self._ledger: dict[str, dict] = {}
        self._cost_limits = _load_cost_limits(self.vault_root)

    def set_task_id(self, task_id: str) -> None:
        self._task_id = task_id

    def record(self, role: str, token_usage: dict) -> None:
        """Record token usage from an LLM call for a role."""
        if role not in self._ledger:
            self._ledger[role] = {"in_tokens": 0, "out_tokens": 0, "call_count": 0, "cost": 0.0}

        entry = self._ledger[role]
        in_tokens = token_usage.get("input_tokens", 0) or token_usage.get("input", 0)
        out_tokens = token_usage.get("output_tokens", 0) or token_usage.get("output", 0)

        entry["in_tokens"] += in_tokens
        entry["out_tokens"] += out_tokens
        entry["call_count"] += 1

        # Estimate cost — we don't have model_id here, so we use the role
        # (the caller should have already passed token_usage from the response)
        # We'll estimate with a generic price
        cost = _estimate_cost("", "", in_tokens, out_tokens)
        entry["cost"] += cost

        logger.debug(
            "CostTracker[%s] role=%s +%din +%dout (cost=%.6f, total=%.4f)",
            self._task_id, role, in_tokens, out_tokens, cost, entry["cost"],
        )

    def record_call(
        self, role: str, model_id: str, provider: str, in_tokens: int, out_tokens: int
    ) -> None:
        """Record a fully-specified call (with model_id for accurate pricing)."""
        if role not in self._ledger:
            self._ledger[role] = {"in_tokens": 0, "out_tokens": 0, "call_count": 0, "cost": 0.0}

        entry = self._ledger[role]
        entry["in_tokens"] += in_tokens
        entry["out_tokens"] += out_tokens
        entry["call_count"] += 1

        cost = _estimate_cost(model_id, provider, in_tokens, out_tokens)
        entry["cost"] += cost

        logger.debug(
            "CostTracker[%s] role=%s model=%s +%din +%dout ($%.6f, total=$%.4f)",
            self._task_id, role, model_id, in_tokens, out_tokens, cost, entry["cost"],
        )

    def get_role_cost(self, role: str) -> float:
        """Get accumulated cost for a role in USD."""
        entry = self._ledger.get(role, {})
        return entry.get("cost", 0.0)

    def get_total_cost(self) -> float:
        """Get total accumulated cost across all roles in USD."""
        return sum(e["cost"] for e in self._ledger.values())

    def check_budget(self, role: str) -> None:
        """Raise if the role has exceeded its budget."""
        budget = self._cost_limits.get(role, 0.0)
        if budget <= 0:
            return  # No budget configured for this role
        spent = self.get_role_cost(role)
        if spent >= budget:
            logger.warning(
                "CostTracker[%s] role=%s budget exceeded: $%.4f >= $%.4f",
                self._task_id, role, spent, budget,
            )
            raise BudgetExceededError(
                f"Role '{role}' budget (${budget:.4f}) exceeded: spent ${spent:.4f} "
                f"on task {self._task_id}"
            )

    def budget_remaining(self, role: str) -> float:
        """Return remaining budget for a role in USD (0 if exceeded or unset)."""
        budget = self._cost_limits.get(role, 0.0)
        if budget <= 0:
            return 0.0
        spent = self.get_role_cost(role)
        return max(0.0, budget - spent)

    def summary(self) -> str:
        """Return a human-readable cost summary."""
        parts = [f"Cost summary for {self._task_id}:"]
        for role, entry in sorted(self._ledger.items()):
            parts.append(
                f"  {role}: {entry['call_count']} call(s), "
                f"{entry['in_tokens']} in / {entry['out_tokens']} out, "
                f"${entry['cost']:.4f}"
            )
        parts.append(f"  TOTAL: ${self.get_total_cost():.4f}")
        return "\n".join(parts)


class BudgetExceededError(Exception):
    """Raised when a role's cost budget has been exceeded."""
    pass
