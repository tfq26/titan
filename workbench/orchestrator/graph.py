"""
LangGraph state graph for the cross-project multi-agent workbench.

Orchestrates the full workflow:
  receive_request → classify → queue → worker → primary_review
    → [secondary_review] → final_decision → complete/revise/blocked

The graph references repo vault artifacts via paths in state.
It does NOT duplicate vault content.
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from .state import WorkbenchState
from .transitions import (
    after_classify_request,
    after_classify_risk,
    after_queue_task,
    after_worker_claim,
    after_worker_execution,
    after_primary_review,
    after_secondary_review,
    after_final_decision,
    after_escalate_to_planner,
    after_block_task,
    after_await_human_approval,
    after_collaborative_discourse,
)
from .nodes import (
    classify_request_node,
    classify_risk_node,
    queue_task_node,
    await_worker_claim_node,
    worker_execution_node,
    primary_review_node,
    secondary_review_node,
    batch_secondary_review_node,
    final_decision_node,
    escalate_to_planner_node,
    block_task_node,
    await_human_approval_node,
    collaborative_discourse_node,
)
from .persistence import get_checkpointer, get_default_db_path


def build_graph() -> StateGraph:
    """Build and return the uncompiled workbench StateGraph."""

    graph = StateGraph(WorkbenchState)

    # ── Register nodes ────────────────────────────────────────────────

    graph.add_node("classify_request", classify_request_node)
    graph.add_node("classify_risk", classify_risk_node)
    graph.add_node("queue_task", queue_task_node)
    graph.add_node("await_worker_claim", await_worker_claim_node)
    graph.add_node("worker_execution", worker_execution_node)
    graph.add_node("primary_review", primary_review_node)
    graph.add_node("secondary_review", secondary_review_node)
    graph.add_node("batch_secondary_review", batch_secondary_review_node)
    graph.add_node("final_decision", final_decision_node)
    graph.add_node("escalate_to_planner", escalate_to_planner_node)
    graph.add_node("block_task", block_task_node)
    graph.add_node("collaborative_discourse", collaborative_discourse_node)
    graph.add_node("await_human_approval", await_human_approval_node)

    # ── Entry point ───────────────────────────────────────────────────

    graph.set_entry_point("classify_request")

    # ── Edges ─────────────────────────────────────────────────────────

    graph.add_conditional_edges(
        "classify_request",
        after_classify_request,
        {
            "classify_risk": "classify_risk",
            "await_human_approval": "await_human_approval",
        },
    )

    graph.add_conditional_edges(
        "classify_risk",
        after_classify_risk,
        {
            "queue_task": "queue_task",
            "collaborative_discourse": "collaborative_discourse",
        },
    )

    graph.add_conditional_edges(
        "queue_task",
        after_queue_task,
        {"await_worker_claim": "await_worker_claim"},
    )

    graph.add_conditional_edges(
        "await_worker_claim",
        after_worker_claim,
        {"worker_execution": "worker_execution"},
    )

    graph.add_conditional_edges(
        "worker_execution",
        after_worker_execution,
        {"primary_review": "primary_review"},
    )

    # ── Review routing ────────────────────────────────────────────────

    graph.add_conditional_edges(
        "primary_review",
        after_primary_review,
        {
            "final_decision": "final_decision",
            "secondary_review": "secondary_review",
            "batch_secondary_review": "batch_secondary_review",
            "queue_task": "queue_task",
            "block_task": "block_task",
        },
    )

    graph.add_conditional_edges(
        "secondary_review",
        after_secondary_review,
        {"final_decision": "final_decision"},
    )

    graph.add_conditional_edges(
        "batch_secondary_review",
        after_secondary_review,
        {"final_decision": "final_decision"},
    )

    # ── Final decision routing ────────────────────────────────────────

    graph.add_conditional_edges(
        "final_decision",
        after_final_decision,
        {
            "end": END,
            "await_human_approval": "await_human_approval",
            "queue_task": "queue_task",
            "escalate_to_planner": "escalate_to_planner",
            "block_task": "block_task",
        },
    )

    graph.add_conditional_edges(
        "escalate_to_planner",
        after_escalate_to_planner,
        {"queue_task": "queue_task"},
    )

    graph.add_conditional_edges(
        "block_task",
        after_block_task,
        {"await_human_approval": "await_human_approval"},
    )

    graph.add_conditional_edges(
        "collaborative_discourse",
        after_collaborative_discourse,
        {
            "queue_task": "queue_task",
            "await_human_approval": "await_human_approval",
        },
    )

    graph.add_conditional_edges(
        "await_human_approval",
        after_await_human_approval,
        {
            "classify_risk": "classify_risk",
            "queue_task": "queue_task",
            "escalate_to_planner": "escalate_to_planner",
            "block_task": "block_task",
            "collaborative_discourse": "collaborative_discourse",
        },
    )

    return graph


def compile_graph(checkpointer=None, use_sqlite: bool = True):
    """
    Compile the workbench graph with persistence.

    Args:
        checkpointer: A LangGraph checkpointer instance. If None, uses
                      the default (SQLite for persistence, MemorySaver
                      as fallback).
        use_sqlite: When True and no checkpointer provided, use SQLite.
                    Set False for smoke tests / in-memory only.

    Returns:
        A compiled LangGraph graph ready for invocation.
    """
    if checkpointer is None:
        checkpointer = get_checkpointer(use_sqlite=use_sqlite)

    graph = build_graph()
    return graph.compile(checkpointer=checkpointer)


# ── Module-level compiled instance ────────────────────────────────────
# Use SQLite by default per architecture decision.
# For in-memory tests, call compile_graph(use_sqlite=False) directly.

app = compile_graph(use_sqlite=True)
