"""
Await human approval node.

A LangGraph checkpoint. The graph suspends here via interrupt() and waits
for human input through the configured UI channel (LangGraph Studio, CLI
prompt, or custom frontend).

When the human responds, the graph resumes from this node with
human_response set in the state.
"""

from ..state import WorkbenchState
from ..tracing import trace_node


def await_human_approval_node(state: WorkbenchState) -> dict:
    """
    Node: await_human_approval

    LangGraph checkpoint node. Suspend and wait for human input.

    Uses LangGraph's interrupt() mechanism:
    - The graph pauses execution here.
    - The human provides input through the configured UI channel.
    - The graph resumes with human_response set.
    - If no response, the graph stays suspended (no timeout at this level).
    """
    with trace_node("await_human_approval", state) as span:
        human_questions = state.get("human_questions", [])
        has_response = bool(state.get("human_response", ""))

        if not has_response and human_questions:
            # Suspend the graph and wait for human input.
            # LangGraph's interrupt() raises a GraphInterrupt exception
            # that is caught by the framework. When the human responds,
            # the graph re-enters this node with human_response set.
            try:
                from langgraph.types import interrupt
                interrupt({"questions": human_questions})
            except ImportError:
                # LangGraph not installed — pass through gracefully.
                # The graph will loop back through this node via
                # the conditional edge until human_response is set.
                pass

        span.set_output({
            "awaiting_response": not has_response,
            "question_count": len(human_questions),
        })
        return {
            "current_node": "await_human_approval",
            "human_questions": human_questions,
            "human_approval_required": not has_response,
        }
