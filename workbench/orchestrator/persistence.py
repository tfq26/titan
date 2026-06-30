"""
Persistence layer for the workbench orchestrator.

Default: SQLite-backed checkpointing via LangGraph's SqliteSaver.
MemorySaver is available as a fallback for smoke tests.

Architecture decision: long-running graph sessions with checkpoint/resume.
SQLite for local dev, Postgres for shared multi-machine deployment later.
"""

from pathlib import Path
import os


# ── Default database path ─────────────────────────────────────────────

def get_default_db_path() -> str:
    """Return the default SQLite database path for checkpointing."""
    # Store in the workbench-vault root
    vault_root = Path(__file__).resolve().parent.parent
    db_dir = vault_root / ".checkpoints"
    db_dir.mkdir(exist_ok=True)
    return str(db_dir / "workbench-sessions.db")


# ── Checkpointer factory ──────────────────────────────────────────────

def get_checkpointer(use_sqlite: bool = True, db_path: str = None):
    """
    Return a LangGraph checkpointer instance.

    Args:
        use_sqlite: When True, use SqliteSaver (durable). When False,
                    use MemorySaver (ephemeral, for tests).
        db_path: SQLite database path. Defaults to
                 .checkpoints/workbench-sessions.db in the vault root.

    Returns:
        A LangGraph-compatible checkpointer instance.
    """
    if not use_sqlite:
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()

    if db_path is None:
        db_path = get_default_db_path()

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        import sqlite3
        conn = sqlite3.connect(db_path, check_same_thread=False)
        return SqliteSaver(conn)
    except ImportError:
        # Fallback: SqliteSaver may not be installed yet.
        # Use MemorySaver and warn.
        import warnings
        warnings.warn(
            "langgraph.checkpoint.sqlite.SqliteSaver not available. "
            "Falling back to MemorySaver (ephemeral). "
            "Install langgraph with checkpoint support for durable sessions."
        )
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()


def get_postgres_checkpointer(conn_string: str):
    """
    Return a Postgres-backed checkpointer for shared deployment.

    Args:
        conn_string: PostgreSQL connection string.
                     e.g. "postgresql://user:pass@localhost:5432/workbench"

    Returns:
        A LangGraph PostgresSaver instance.
    """
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        return PostgresSaver.from_conn_string(conn_string)
    except ImportError:
        raise ImportError(
            "langgraph.checkpoint.postgres.PostgresSaver not available. "
            "Install langgraph with postgres checkpoint support."
        )
