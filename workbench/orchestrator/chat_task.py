"""
Helpers for turning explicit chat task or plan proposals into queued files.

Chat remains a discussion surface, but when a model deliberately emits a
`Task:` block or a multi-slice `Plan:` block, we can materialize that proposal
into the canonical queue so the work starts from conversation instead of
manual copy/paste.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .nodes.queue_task import _allocate_task_filename, _build_task_markdown
from .plan_kickoff import looks_like_plan_kickoff
from .plan_sequences import (
    ChatTaskProposal,
    PlanSequenceProposal,
    materialize_plan_manifest,
    parse_chat_plan_proposal,
    parse_chat_task_proposal,
)


def queue_chat_task_from_response(
    *,
    response: str,
    request: str,
    project_config: dict,
    role: str,
    nickname: str,
    response_mode: str,
) -> Optional[str]:
    """Queue a task or plan proposal extracted from a chat response."""
    vault_root = Path(project_config["vault_root"])
    project_id = project_config["id"]

    plan_proposal = parse_chat_plan_proposal(response)
    if plan_proposal and len(plan_proposal.tasks) > 1:
        return _queue_plan_sequence_from_response(
            plan_proposal=plan_proposal,
            request=request,
            project_config=project_config,
            role=role,
            nickname=nickname,
            response_mode=response_mode,
        )

    proposal = parse_chat_task_proposal(response)
    if proposal is None:
        return None

    workflow_intent = (
        "plan_kickoff"
        if looks_like_plan_kickoff(f"{request}\n{proposal.goal}\n{proposal.title}")
        else "task"
    )
    task_filename = _allocate_task_filename(vault_root, project_id, session_id="")
    task_goal = proposal.goal or proposal.title or request

    base_task = _build_task_markdown(
        task_filename=task_filename,
        user_request=task_goal,
        task_type=proposal.task_type or "implementation",
        workflow_intent=workflow_intent,
        escalation_tier="low",
        risk_level="low",
        revision_count=0,
        vault_root=vault_root,
        state={},
    )

    appendix = _build_chat_appendix(
        proposal=proposal,
        request=request,
        role=role,
        nickname=nickname,
        response_mode=response_mode,
    )

    open_dir = vault_root / "queue-tasks" / "open"
    open_dir.mkdir(parents=True, exist_ok=True)
    task_path = open_dir / task_filename
    task_path.write_text(
        base_task + ("\n\n" + appendix if appendix else ""),
        encoding="utf-8",
    )
    return task_filename


def _queue_plan_sequence_from_response(
    *,
    plan_proposal: PlanSequenceProposal,
    request: str,
    project_config: dict,
    role: str,
    nickname: str,
    response_mode: str,
) -> Optional[str]:
    if not plan_proposal.tasks:
        return None

    vault_root = Path(project_config["vault_root"])
    project_id = project_config["id"]

    manifest_path, task_filenames, plan_id = materialize_plan_manifest(
        vault_root=vault_root,
        project_id=project_id,
        source_request=request,
        source_role=role,
        source_nickname=nickname,
        response_mode=response_mode,
        proposal=plan_proposal,
    )

    first_task = plan_proposal.tasks[0]
    first_task_filename = task_filenames[0]
    plan_metadata = {
        "plan_manifest_path": manifest_path,
        "plan_id": plan_id,
        "plan_title": plan_proposal.title,
        "plan_summary": plan_proposal.summary,
        "plan_step_index": 1,
        "plan_step_total": len(plan_proposal.tasks),
        "plan_step_title": first_task.title,
        "plan_step_goal": first_task.goal,
        "plan_step_filename": first_task_filename,
    }

    base_task = _build_task_markdown(
        task_filename=first_task_filename,
        user_request=first_task.goal or first_task.title or request,
        task_type=first_task.task_type or "implementation",
        workflow_intent="plan_kickoff",
        escalation_tier="low",
        risk_level="low",
        revision_count=0,
        vault_root=vault_root,
        state=plan_metadata,
        plan_metadata=plan_metadata,
    )

    appendix = _build_chat_appendix(
        proposal=first_task,
        request=request,
        role=role,
        nickname=nickname,
        response_mode=response_mode,
        plan_metadata=plan_metadata,
    )

    open_dir = vault_root / "queue-tasks" / "open"
    open_dir.mkdir(parents=True, exist_ok=True)
    task_path = open_dir / first_task_filename
    task_path.write_text(
        base_task + ("\n\n" + appendix if appendix else ""),
        encoding="utf-8",
    )
    return first_task_filename


def _build_chat_appendix(
    *,
    proposal: ChatTaskProposal,
    request: str,
    role: str,
    nickname: str,
    response_mode: str,
    plan_metadata: dict | None = None,
) -> str:
    lines: list[str] = []

    if proposal.title or proposal.task_type:
        lines.append("## Chat Proposal")
        if proposal.title:
            lines.append(f"- Title: {proposal.title}")
        if proposal.task_type:
            lines.append(f"- Type: {proposal.task_type}")

    if proposal.acceptance:
        if lines:
            lines.append("")
        lines.append("### Acceptance")
        for item in proposal.acceptance:
            lines.append(f"- {item}")

    if proposal.scope:
        if lines:
            lines.append("")
        lines.append("### Scope Notes")
        for item in proposal.scope:
            lines.append(f"- {item}")

    if plan_metadata:
        if lines:
            lines.append("")
        lines.append("## Plan Source")
        if plan_metadata.get("plan_title"):
            lines.append(f"- Plan: {plan_metadata['plan_title']}")
        if plan_metadata.get("plan_id"):
            lines.append(f"- Plan ID: {plan_metadata['plan_id']}")
        if plan_metadata.get("plan_step_index") and plan_metadata.get("plan_step_total"):
            lines.append(
                f"- Step: {plan_metadata['plan_step_index']} of {plan_metadata['plan_step_total']}"
            )
        if plan_metadata.get("plan_manifest_path"):
            lines.append(f"- Manifest: {plan_metadata['plan_manifest_path']}")

    if lines:
        lines.append("")

    lines.extend(
        [
            "## Chat Source",
            f"- Role: {role}",
            f"- Nickname: {nickname}",
            f"- Response mode: {response_mode}",
            "",
            "## Source Request",
            request,
        ]
    )

    return "\n".join(lines)
