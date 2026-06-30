"""
Workbench orchestrator package.

Exports key symbols for external use and for the run.py CLI entrypoint.
"""

from .state import WorkbenchState

# Graph compilation requires langgraph. Make it optional so unit tests
# and individual node imports work without the full langgraph install.
try:
    from .graph import build_graph, compile_graph
except ImportError:
    build_graph = None   # type: ignore
    compile_graph = None  # type: ignore

from .llm_client import (
    call_llm,
    call_llm_text,
    resolve_role_nickname,
    resolve_role_model_id,
)

__all__ = [
    "WorkbenchState",
    "build_graph",
    "compile_graph",
    "call_llm",
    "call_llm_text",
    "resolve_role_nickname",
    "resolve_role_model_id",
]
