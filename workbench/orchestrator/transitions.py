"""
Conditional edge logic for the workbench LangGraph.

Each function returns the name of the next node. These are used as
conditional edge functions in graph.py.
"""

from .state import WorkbenchState


def after_classify_request(state: WorkbenchState) -> str:
    """After classification, if confidence is low, ask human."""
    if state.get("classification_confidence", 1.0) < 0.7:
        return "await_human_approval"
    return "classify_risk"


def after_classify_risk(state: WorkbenchState) -> str:
    """After risk classification, proceed to queue or collaborative discourse."""
    # Route to collaborative discourse if:
    # - workflow_intent is ambiguous, OR
    # - classification confidence was low, OR
    # - the user explicitly requested discussion
    needs_discourse = (
        state.get("workflow_intent", "") in ("", "discussion")
        or (state.get("classification_confidence", 1.0) or 1.0) < 0.5
        or state.get("discourse_ready_to_queue") is False
    )
    if needs_discourse:
        return "collaborative_discourse"
    return "queue_task"


def after_queue_task(state: WorkbenchState) -> str:
    """After queuing, wait for a worker to claim the task."""
    return "await_worker_claim"


def after_worker_claim(state: WorkbenchState) -> str:
    """Once the task is claimed, proceed to worker execution."""
    return "worker_execution"


def after_worker_execution(state: WorkbenchState) -> str:
    """After worker finishes, proceed to primary review."""
    return "primary_review"


def after_primary_review(state: WorkbenchState) -> str:
    """
    Primary review decision routing.

    Low escalation + passes  → final_decision (complete)
    Low escalation + revise  → queue_task (increment revision)
    Low escalation + blocked → block_task
    High escalation + passes + batch → batch_secondary_review
    High escalation + passes → secondary_review
    High escalation + revise → queue_task (increment revision)
    High escalation + blocked → block_task
    """
    decision = state.get("primary_review_decision", "")
    tier = state.get("escalation_tier", "low")
    batch_tasks = state.get("batch_tasks", [])

    if decision == "blocked":
        return "block_task"

    if decision == "revise":
        return "queue_task"

    if decision == "passes_first_pass":
        if tier == "high":
            if batch_tasks:
                return "batch_secondary_review"
            return "secondary_review"
        else:
            return "final_decision"

    return "final_decision"


def after_secondary_review(state: WorkbenchState) -> str:
    """After secondary review, return to primary for final decision."""
    return "final_decision"


def after_final_decision(state: WorkbenchState) -> str:
    """
    Final decision routing.

    complete → END
    complete + plan continuation → queue_task
    verify   → await_human_approval (primary reviewer resolves secondary concerns)
    revise + revision_count < 3 → queue_task (increment revision)
    revise + revision_count >= 3 → escalate_to_planner
    blocked → block_task
    """
    decision = state.get("final_decision", "complete")
    revisions = state.get("revision_count", 0)

    if decision == "complete":
        if state.get("plan_should_queue_next"):
            return "queue_task"
        return "end"

    if decision == "verify":
        return "await_human_approval"

    if decision == "revise":
        if revisions >= 3:
            return "escalate_to_planner"
        else:
            return "queue_task"

    if decision == "blocked":
        return "block_task"

    return "end"


def after_escalate_to_planner(state: WorkbenchState) -> str:
    """After planner re-scopes, queue the rewritten task."""
    return "queue_task"


def after_collaborative_discourse(state: WorkbenchState) -> str:
    """After collaborative discourse, route to queue or human approval."""
    if state.get("discourse_ready_to_queue"):
        return "queue_task"
    return "await_human_approval"


def after_block_task(state: WorkbenchState) -> str:
    """After blocking, wait for human input."""
    return "await_human_approval"


def after_await_human_approval(state: WorkbenchState) -> str:
    """After human responds, determine where to resume."""
    human_response = state.get("human_response", "")
    current_node = state.get("current_node", "")

    if human_response == "proceed":
        if current_node == "await_human_approval_after_classify":
            return "classify_risk"
        if current_node == "await_human_approval_after_blocked":
            return "queue_task"
        if "discourse" in (current_node or ""):
            return "collaborative_discourse"
        return "classify_risk"

    if human_response == "abort":
        return "block_task"

    if human_response == "discuss":
        return "collaborative_discourse"

    return "escalate_to_planner"


