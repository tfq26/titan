"""
Project-level model authorization enforcement — stateless, invocation-scoped.

Credentials are machine-level (env vars, secrets file).
Model authorization is project-level (project-config.yaml model_policy).
Policy is passed explicitly with every call — no global singleton.

This module validates that:
1. The role is allowed for the current project.
2. The resolved model_ref is allowed for that role.
3. The model_ref is not in the project's deny list.
4. Runtime role requirements are satisfied (escalation_tier, task_type, etc.).

Usage:
    from .model_policy import ModelPolicyError, validate_model_invocation

    validate_model_invocation(
        role="secondary_reviewer",
        model_ref="secondary_reviewer_model",
        policy=state.get("model_policy", {}),
        project_id=state.get("project_id", ""),
        runtime_context={"escalation_tier": "high"},
    )
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── Error types ───────────────────────────────────────────────────────

class ModelPolicyError(Exception):
    """
    Raised when a model invocation violates the project's model policy.

    This is an AUTHORIZATION failure — distinct from model unavailability
    or provider/API failures. Policy violations indicate the task should
    be blocked or escalated, not retried.
    """

    def __init__(
        self,
        message: str,
        *,
        role: str = "",
        model_ref: str = "",
        project_id: str = "",
    ):
        super().__init__(message)
        self.role = role
        self.model_ref = model_ref
        self.project_id = project_id


# ── Static validation: role + model_ref ───────────────────────────────

def validate_role_access(
    role: str,
    model_ref: str,
    *,
    policy: dict,
    project_id: str = "",
) -> None:
    """
    Validate that the role and model_ref are allowed by the project policy.

    Checks:
    1. A policy is provided.
    2. The role is in allowed_roles.
    3. The resolved model_ref is in the allowed list for this role.
    4. The model_ref is not in denied_model_refs.

    Raises ModelPolicyError if any check fails.
    """
    if not policy:
        raise ModelPolicyError(
            f"No model policy configured for project '{project_id}'. "
            f"Role '{role}' cannot be invoked.",
            role=role, model_ref=model_ref, project_id=project_id,
        )

    allowed_roles = policy.get("allowed_roles", {})

    if role not in allowed_roles:
        available = list(allowed_roles.keys())
        raise ModelPolicyError(
            f"Role '{role}' is not in allowed_roles "
            f"for project '{project_id}'. "
            f"Allowed roles: {available or '(none)'}",
            role=role, model_ref=model_ref, project_id=project_id,
        )

    allowed_refs = allowed_roles[role]
    if not isinstance(allowed_refs, list):
        allowed_refs = [allowed_refs]

    if model_ref not in allowed_refs:
        raise ModelPolicyError(
            f"Model ref '{model_ref}' is not allowed for role '{role}' "
            f"in project '{project_id}'. "
            f"Allowed refs for this role: {allowed_refs}",
            role=role, model_ref=model_ref, project_id=project_id,
        )

    denied_refs = policy.get("denied_model_refs", [])
    if model_ref in denied_refs:
        raise ModelPolicyError(
            f"Model ref '{model_ref}' is explicitly denied "
            f"for project '{project_id}'.",
            role=role, model_ref=model_ref, project_id=project_id,
        )


# ── Runtime validation: role requirements ─────────────────────────────

def validate_role_requirements(
    role: str,
    runtime_context: dict,
    *,
    policy: dict,
) -> None:
    """
    Validate runtime role requirements against the current execution context.

    Checks role_requirements from the project policy:
    - escalation_tier must match (e.g. secondary_reviewer requires 'high')
    - task_type must be in an allowed list

    Raises ModelPolicyError if a requirement is not met.
    """
    if not policy:
        return

    requirements = policy.get("role_requirements", {}).get(role, {})
    if not requirements:
        return

    required_tier = requirements.get("escalation_tier")
    if required_tier:
        actual_tier = runtime_context.get("escalation_tier", "")
        if actual_tier != required_tier:
            raise ModelPolicyError(
                f"Role '{role}' requires escalation_tier='{required_tier}' "
                f"but current tier is '{actual_tier}'. "
                f"This role cannot be invoked at this escalation level.",
                role=role,
            )

    required_task_types = requirements.get("task_type")
    if required_task_types:
        if not isinstance(required_task_types, list):
            required_task_types = [required_task_types]
        actual_task_type = runtime_context.get("task_type", "")
        if actual_task_type not in required_task_types:
            raise ModelPolicyError(
                f"Role '{role}' requires task_type in {required_task_types} "
                f"but current task_type is '{actual_task_type}'.",
                role=role,
            )


# ── Full validation ───────────────────────────────────────────────────

def validate_model_invocation(
    role: str,
    model_ref: str,
    *,
    policy: dict,
    project_id: str = "",
    runtime_context: Optional[dict] = None,
) -> None:
    """
    Full stateless validation: static access check + runtime requirements.

    Raises ModelPolicyError on any policy violation.
    """
    validate_role_access(
        role, model_ref,
        policy=policy, project_id=project_id,
    )

    if runtime_context:
        validate_role_requirements(
            role, runtime_context,
            policy=policy,
        )


# ── Preflight check ───────────────────────────────────────────────────

def preflight_check(project_policy: dict) -> list[str]:
    """
    Check whether a policy is structurally valid.

    Returns a list of warnings (empty list = valid).
    """
    warnings: list[str] = []

    if not project_policy:
        warnings.append("No model_policy defined — all roles are denied.")
        return warnings

    allowed_roles = project_policy.get("allowed_roles", {})
    if not allowed_roles:
        warnings.append("allowed_roles is empty — no roles can be invoked.")

    denied = project_policy.get("denied_model_refs", [])
    for role, refs in allowed_roles.items():
        if not isinstance(refs, list):
            refs = [refs]
        for ref in refs:
            if ref in denied:
                warnings.append(
                    f"Model ref '{ref}' for role '{role}' is in both "
                    f"allowed_roles AND denied_model_refs — it will be denied."
                )

    requirements = project_policy.get("role_requirements", {})
    for role, reqs in requirements.items():
        if role not in allowed_roles:
            warnings.append(
                f"Role '{role}' has role_requirements but is not in allowed_roles."
            )
        if reqs.get("escalation_tier") and reqs["escalation_tier"] not in ("low", "high"):
            warnings.append(
                f"Role '{role}' has invalid escalation_tier requirement: "
                f"'{reqs['escalation_tier']}' (must be 'low' or 'high')."
            )

    return warnings
