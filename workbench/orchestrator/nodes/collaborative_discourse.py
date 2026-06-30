"""
Collaborative Discourse Node.

Runs a structured multi-turn discussion among designated agent roles.
Used when the classifier flags ambiguity, the human requests discussion,
or the spec-to-project pipeline triggers it.

Flow:
  1. Gather participants (default: worker + primary_reviewer)
  2. For each turn (max 5), call each participant's LLM in sequence
  3. Each participant sees: the full conversation history + their role prompt
  4. After each turn, check termination conditions
  5. Write a discourse record to vault/machine/discourse/
  6. Return structured output for graph state

Termination conditions:
  - Consensus reached (all participants agree on next steps)
  - Max turns exceeded (default 5)
  - Human intervention file found
  - "ready to queue" signal from any participant
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
import uuid
import logging

from ..state import WorkbenchState
from ..llm_client import call_llm_text
from ..model_policy import ModelPolicyError
from ..tracing import trace_node
from .. import agent_messaging as msg

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────

MAX_TURNS = 5
DEFAULT_PARTICIPANTS = ["worker", "primary_reviewer"]

TERMINATION_SIGNAL = "DISCUSSION_COMPLETE"


# ── System prompts per role ─────────────────────────────────────────────

def _participant_system_prompt(role: str, nickname: str) -> str:
    prompts = {
        "worker": f"""You are {nickname}, a worker agent in a collaborative engineering discussion.

Your job is to think through the technical implementation, ask clarifying
questions about scope, identify technical risks, and propose concrete
work breakdowns. When you are ready to proceed to implementation, signal
by saying "{TERMINATION_SIGNAL}" on its own line.

Rules:
- Focus on feasibility, effort estimation, and implementation approach.
- If scope is unclear, ask the primary reviewer for judgment.
- If you need more info, ask.
- Be specific about subsystems, files, and patterns.
- When you have enough clarity, clearly state "{TERMINATION_SIGNAL}". """,

        "primary_reviewer": f"""You are {nickname}, a primary reviewer in a collaborative engineering discussion.

Your job is to evaluate scope, judge risk, catch over-engineering, and
ensure the discussion converges on a clear, actionable plan. When you
are satisfied, signal by saying "{TERMINATION_SIGNAL}" on its own line.

Rules:
- Keep scope tight. Push back on gold-plating.
- Identify acceptance criteria gaps.
- Decide when the plan is ready for queueing.
- When the plan is clear and scoped, state "{TERMINATION_SIGNAL}". """,

        "secondary_reviewer": f"""You are {nickname}, a secondary reviewer (escalation tier) in a collaborative discussion.

You are the least eager speaker. Only join when the discussion involves
high-risk or complex changes. You focus on architecture, lifecycle,
threading, and regression risks. Only speak when you see a genuine risk.

Rules:
- Stay silent unless there is a real concern.
- If you have no concerns, just say "No concerns from secondary review."
- Do not block progress unless there is a genuine architectural issue.""",

        "classifier": f"""You are {nickname}, a classifier in a collaborative discussion.

Your job is to set scope boundaries: what task type this is
(implementation | docs | refactor | investigation), what risk level,
and what subsystems are involved. Keep your input brief and focused
on scope definition.""",

        "bookkeeping_reviewer": f"""You are {nickname}, a bookkeeping reviewer in a collaborative discussion.

You focus on documentation needs, changelog entries, migration notes,
and any bookkeeping required. Speak only when relevant.""",
    }
    return prompts.get(role, f"You are {nickname}, discussing a task.")


# ── Node ────────────────────────────────────────────────────────────────

def collaborative_discourse_node(state: WorkbenchState) -> dict:
    """
    Node: collaborative_discourse

    Runs multi-turn discussion among configured agent roles to converge
    on a shared understanding of the task, scope, and approach.

    Returns updates to graph state with discourse results.
    """
    with trace_node("collaborative_discourse", state) as span:
        vault_root = Path(state.get("project_vault_root", ""))
        user_request = state.get("user_request", "")
        project_id = state.get("project_id", "unknown")
        project_policy = state.get("model_policy")

        if not vault_root.exists():
            span.set_output({"error": "missing_vault_root"})
            return _error_updates("Project vault root not found.")

        if not user_request.strip():
            span.set_output({"error": "empty_request"})
            return _error_updates("User request is empty. Nothing to discuss.")

        # ── Resolve participants ──────────────────────────────────────
        participants = DEFAULT_PARTICIPANTS.copy()
        escalation_tier = state.get("escalation_tier", "low")
        if escalation_tier == "high":
            participants.append("secondary_reviewer")

        # ── Create discussion thread ──────────────────────────────────
        thread_id = f"discourse-{uuid.uuid4().hex[:8]}"
        discourse_dir = vault_root / "machine" / "discourse"
        discourse_dir.mkdir(parents=True, exist_ok=True)

        conversation_history = []
        turn = 0
        consensus_reached = False
        final_summary = ""
        final_agreements: list[str] = []
        final_disagreements: list[str] = []
        task_breakdown: list[dict] = []
        ready_to_queue = False

        # ── Kickoff message ───────────────────────────────────────────
        msg.send_message(
            vault_root,
            from_role="orchestrator",
            to_role="all",
            msg_type="info",
            subject="Discussion started",
            body=f"# Discussion: {state.get('task_type', 'implementation')}\n\n{user_request}",
            thread_id=thread_id,
        )
        conversation_history.append(
            f"[orchestrator] Discussion started for: {user_request}"
        )

        # ── Discussion turns ──────────────────────────────────────────
        while turn < MAX_TURNS and not consensus_reached and not ready_to_queue:
            turn += 1

            # Check for human intervention
            human_input = _check_human_input(vault_root, thread_id)
            if human_input:
                conversation_history.append(
                    f"[human] {human_input['message']}"
                )
                if human_input.get("type") == "abort":
                    logger.info("discourse aborted by human intervention")
                    break

            for role in participants:
                nickname = _resolve_nickname(role)
                system_prompt = _participant_system_prompt(role, nickname)

                # Build context from conversation history
                context = "\n".join(conversation_history[-10:])  # Last 10 messages
                user_prompt = _build_discourse_prompt(
                    role=role,
                    nickname=nickname,
                    user_request=user_request,
                    context=context,
                    turn=turn,
                )

                try:
                    response = call_llm_text(
                        role=role,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        fallback="[error] LLM call failed during discourse.",
                        project_policy=project_policy,
                        project_id=project_id,
                    )
                except ModelPolicyError as e:
                    logger.error("Policy denied discourse participant %s: %s", role, e)
                    response = f"[policy denied] Cannot participate: {e}"
                except Exception as e:
                    logger.error("Discourse LLM error for %s: %s", role, e)
                    response = f"[error] LLM error: {e}"

                # Store in conversation history
                conversation_history.append(f"[{role}] {response.strip()}")

                # Send to message bus
                msg.send_message(
                    vault_root,
                    from_role=role,
                    to_role="all",
                    msg_type="info",
                    subject=f"Turn {turn} response",
                    body=response.strip(),
                    thread_id=thread_id,
                )

                # Check for termination signal
                if TERMINATION_SIGNAL in response:
                    logger.info(
                        "discourse participant %s signaled ready at turn %d",
                        role, turn,
                    )
                    if role in ("primary_reviewer", "worker"):
                        ready_to_queue = True
                        if role == "primary_reviewer":
                            consensus_reached = True

                # Check for explicit consensus
                if "CONSENSUS" in response.upper():
                    consensus_reached = True

            # Check for human intervention between turns
            human_input = _check_human_input(vault_root, thread_id)
            if human_input:
                conversation_history.append(
                    f"[human] {human_input['message']}"
                )

        # ── Parse results ─────────────────────────────────────────────-
        final_summary, final_agreements, final_disagreements, task_breakdown = (
            _parse_discourse_results(conversation_history)
        )

        # ── Write discourse record ────────────────────────────────────-
        record = _write_discourse_record(
            discourse_dir=discourse_dir,
            user_request=user_request,
            thread_id=thread_id,
            participants=participants,
            turns=turn,
            consensus_reached=consensus_reached,
            ready_to_queue=ready_to_queue,
            conversation_history=conversation_history,
            summary=final_summary,
            agreements=final_agreements,
            disagreements=final_disagreements,
            task_breakdown=task_breakdown,
            state=state,
        )

        span.set_output({
            "turns": turn,
            "consensus_reached": consensus_reached,
            "ready_to_queue": ready_to_queue,
        })

        return {
            "current_node": "collaborative_discourse",
            "discourse_thread_id": thread_id,
            "discourse_summary": final_summary,
            "discourse_agreements": final_agreements,
            "discourse_disagreements": final_disagreements,
            "discourse_task_breakdown": task_breakdown,
            "discourse_record_path": str(record.relative_to(vault_root)) if record else "",
            "discourse_consensus_reached": consensus_reached,
            "discourse_ready_to_queue": ready_to_queue,
        }


# ── Helpers ─────────────────────────────────────────────────────────────

def _build_discourse_prompt(
    *,
    role: str,
    nickname: str,
    user_request: str,
    context: str,
    turn: int,
) -> str:
    return (
        f"## Original Request\n\n{user_request}\n\n"
        f"## Discussion So Far (Turn {turn})\n\n"
        f"{context}\n\n"
        f"## Your Turn\n\n"
        f"Role: {role} ({nickname})\n"
        f"Turn: {turn}\n\n"
        f"Respond to the discussion. Build on what others have said. "
        f"When you have enough clarity for your role, say \"{TERMINATION_SIGNAL}\" "
        f"on its own line to signal you are ready to proceed."
    )


def _check_human_input(
    vault_root: Path,
    thread_id: str,
) -> Optional[dict]:
    """Check for human intervention files in machine/human-input/."""
    human_dir = vault_root / "machine" / "human-input"
    if not human_dir.exists():
        return None

    for f in sorted(human_dir.glob("*.md")):
        try:
            content = f.read_text(encoding="utf-8")
        except OSError:
            continue

        # Parse minimal frontmatter
        intervention = {"message": content, "type": "guidance"}
        if content.startswith("---"):
            try:
                end = content.index("\n---", 3)
                fm = content[3:end].strip()
                for line in fm.split("\n"):
                    if ":" in line:
                        key, val = line.split(":", 1)
                        intervention[key.strip().lower()] = val.strip()
            except ValueError:
                pass

        # Archive the input file
        archive_dir = human_dir / ".processed"
        archive_dir.mkdir(parents=True, exist_ok=True)
        f.rename(archive_dir / f.name)

        return intervention

    return None


def _parse_discourse_results(
    history: list[str],
) -> tuple[str, list[str], list[str], list[dict]]:
    """Parse discourse conversation into structured results.

    Returns (summary, agreements, disagreements, task_breakdown).
    """
    summary_lines: list[str] = []
    agreements: list[str] = []
    disagreements: list[str] = []
    tasks: list[dict] = []

    for line in history:
        lower = line.lower()

        if "summary" in lower or "conclusion" in lower:
            summary_lines.append(line)

        if "agree" in lower or "consensus" in lower:
            agreements.append(line)

        if "disagree" in lower or "concern" in lower or "risk" in lower:
            disagreements.append(line)

        if "task:" in lower or "breakdown" in lower:
            tasks.append({"source": line})

    summary = "\n".join(summary_lines) if summary_lines else (
        "Discussion completed. See discourse record for full transcript."
    )

    return summary, agreements, disagreements, tasks


def _write_discourse_record(
    *,
    discourse_dir: Path,
    user_request: str,
    thread_id: str,
    participants: list[str],
    turns: int,
    consensus_reached: bool,
    ready_to_queue: bool,
    conversation_history: list[str],
    summary: str,
    agreements: list[str],
    disagreements: list[str],
    task_breakdown: list[dict],
    state: WorkbenchState,
) -> Path:
    """Write a discourse record to the vault."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    record_filename = f"discourse-{thread_id}.md"
    record_path = discourse_dir / record_filename

    participants_str = ", ".join(participants)
    agreements_str = "\n".join(f"- {a}" for a in agreements) if agreements else "- None recorded"
    disagreements_str = "\n".join(f"- {d}" for d in disagreements) if disagreements else "- None"
    tasks_str = "\n".join(
        f"- {t.get('source', '')}" for t in task_breakdown
    ) if task_breakdown else "- No task breakdown produced"

    history_str = "\n\n".join(conversation_history)

    content = f"""---
type: discourse-record
status: {"consensus" if consensus_reached else "incomplete"}
created: {now}
thread_id: {thread_id}
participants: [{participants_str}]
total_turns: {turns}
consensus_reached: {str(consensus_reached).lower()}
ready_to_queue: {str(ready_to_queue).lower()}
workflow_intent: {state.get("workflow_intent", "task")}
project_id: {state.get("project_id", "unknown")}
---

# Discourse Record

## Request

{user_request}

## Participants

{participants_str}

## Status

| Measure | Value |
|---|---|
| Turns | {turns} |
| Consensus | {consensus_reached} |
| Ready to queue | {ready_to_queue} |

## Summary

{summary}

## Agreements

{agreements_str}

## Disagreements / Risks

{disagreements_str}

## Task Breakdown

{tasks_str}

## Full Transcript

{history_str}
"""
    record_path.write_text(content, encoding="utf-8")
    logger.info("discourse record written to %s", record_path)
    return record_path


def _resolve_nickname(role: str) -> str:
    """Resolve a role to its nickname from routing config."""
    try:
        from ..llm_client import resolve_role_nickname
        return resolve_role_nickname(role)
    except Exception:
        return role


def _error_updates(message: str) -> dict:
    return {
        "current_node": "collaborative_discourse",
        "human_questions": [message],
        "discourse_summary": "",
        "discourse_agreements": [],
        "discourse_disagreements": [],
        "discourse_task_breakdown": [],
        "discourse_consensus_reached": False,
        "discourse_ready_to_queue": True,
    }
