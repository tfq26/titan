"""Shared helpers for plan-oriented kickoff behavior.

Plan kickoff is not a separate workflow. It is a posture used when the
operator provides an existing plan, feature brief, or current-state note and
expects the workbench to begin from that source of truth.
"""

from __future__ import annotations

PLAN_KICKOFF_CUES = (
    "plan kickoff",
    "kick off the plan",
    "kickoff the plan",
    "kickoff",
    "implementation plan",
    "work from the plan",
    "start from the plan",
    "read the plan",
    "feature brief",
    "current-state",
    "current state",
    "plan is available",
    "plan available",
    "roadmap",
)


def looks_like_plan_kickoff(text: str) -> bool:
    """Heuristically detect whether a request is asking for kickoff."""
    normalized = " ".join((text or "").lower().split())
    return any(cue in normalized for cue in PLAN_KICKOFF_CUES)


def build_plan_kickoff_prompt_hint(user_request: str) -> str:
    """Return a short prompt hint when the request looks plan-oriented."""
    if not looks_like_plan_kickoff(user_request):
        return ""

    return (
        "\n## Kickoff Hint\n\n"
        "This request appears to be a plan kickoff request. "
        "If the operator wants the team to start from an existing plan, feature brief, "
        "or current-state note, set `workflow_intent` to `plan_kickoff` and keep the "
        "first slice as small as possible."
    )


def build_plan_kickoff_chat_guidance(request: str, chat_context: str = "") -> str:
    """Return extra chat guidance when the conversation is kickoff-oriented."""
    if not looks_like_plan_kickoff(f"{request}\n{chat_context}"):
        return ""

    return (
        "\nPlan kickoff guidance: Treat this message as kickoff, not generic chat. "
        "Use the plan or current-state note as the source of truth. "
        "Start with the smallest executable slice, then hand off to the next role "
        "only when it is actually needed. "
        "If the work naturally spans multiple slices, emit a compact `Plan:` block "
        "with one `Task:` subsection per slice so the workbench can queue the "
        "sequence automatically. "
        "Worker should be the most eager to act; primary reviewer should follow "
        "only when there is something concrete to review; secondary reviewer should "
        "stay out unless explicitly pinged or the work is high risk. "
        "Do not repeat introductions once the thread already knows who is speaking.\n"
    )


def build_plan_kickoff_task_section() -> str:
    """Return the kickoff section inserted into queued tasks."""
    return """## Plan Kickoff

This task begins from an existing plan, feature brief, or current-state note.
Treat those docs as the source of truth and start the smallest executable slice.

Kickoff order:

1. Read the plan and current-state notes first.
2. Identify the first slice that can move the plan forward without widening scope.
3. If another role needs to review or unblock the slice, ping it in chat with a
   short `Handoff:` section instead of asking the human to coordinate the team.
4. Keep introductions to a single first turn in the thread.
5. Once the kickoff slice is clear, proceed through the normal implementation,
   validation, and review flow.

Worker should start the kickoff slice. Primary reviewer should follow when the
worker has something concrete to inspect. Secondary reviewer should stay out
unless the task is high risk or explicitly escalated.
"""
