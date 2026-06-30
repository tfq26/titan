"""
LangGraph state shape for the cross-project workbench.

State is intentionally compact. It stores pointers to vault artifacts
rather than duplicating their content. The repo vault remains the primary
human-readable working memory layer.
"""

from typing import TypedDict, Literal, Optional, Annotated

try:
    from langgraph.graph.message import add_messages
except ImportError:
    # Fallback for environments without langgraph (e.g. unit tests).
    # The messages field is not used outside of LangGraph graph execution.
    def add_messages(existing: list, new: list) -> list:
        return new


class WorkbenchState(TypedDict):
    # ── Session identity ──────────────────────────────────────────────
    session_id: str
    project_id: str
    project_vault_root: str
    project_repo_root: str
    project_report_root: str

    # ── Request and classification ────────────────────────────────────
    user_request: str
    task_type: str               # "implementation" | "docs" | "refactor" | "investigation"
    workflow_intent: str         # "task" | "plan_kickoff"
    risk_level: Literal["low", "high"]
    escalation_tier: Literal["low", "high"]
    revision_count: int          # 0-based; incremented on each revise

    # ── Current workflow position ─────────────────────────────────────
    current_node: str
    current_task_path: Optional[str]       # relative path from vault_root
    current_task_filename: Optional[str]   # TASK-YYYYMMDD-HHMM-short-name.md
    task_record_path: Optional[str]
    task_snapshot_path: Optional[str]
    task_event_log_path: Optional[str]
    task_context_pack_paths: dict[str, str]
    rendered_view_paths: dict[str, str]
    worker_report_path: Optional[str]
    worker_report_record_path: Optional[str]
    primary_review_path: Optional[str]
    primary_review_record_path: Optional[str]
    secondary_review_path: Optional[str]
    secondary_review_record_path: Optional[str]
    decision_record_path: Optional[str]

    # ── Plan sequence metadata ──────────────────────────────────────
    plan_manifest_path: Optional[str]
    plan_id: Optional[str]
    plan_title: Optional[str]
    plan_summary: Optional[str]
    plan_step_index: Optional[int]
    plan_step_total: Optional[int]
    plan_step_title: Optional[str]
    plan_step_goal: Optional[str]
    plan_should_queue_next: bool

    # ── Collaborative discourse ───────────────────────────────────────
    discourse_thread_id: Optional[str]
    discourse_summary: Optional[str]
    discourse_agreements: list[str]
    discourse_disagreements: list[str]
    discourse_task_breakdown: list[dict]
    discourse_record_path: Optional[str]
    discourse_consensus_reached: bool
    discourse_ready_to_queue: bool

    # ── Agent messaging ───────────────────────────────────────────────
    pending_agent_messages: list[dict]

    # ── Human side-channel ────────────────────────────────────────────
    human_input_pending: bool
    human_input_path: Optional[str]
    human_input_last_checked: Optional[str]

    # ── Routing ───────────────────────────────────────────────────────
    # Populated from routing.yaml at graph init. Stores nicknames
    # (human-facing labels), not raw backend model_ids.
    worker_model: str
    primary_reviewer_model: str
    secondary_reviewer_model: Optional[str]
    classifier_model: str
    supervisor_planner_model: str           # escalation fallback (revision >= 3), NOT default planner
    bookkeeping_reviewer_model: Optional[str]

    # ── Human interaction ─────────────────────────────────────────────
    human_questions: list[str]
    human_approval_required: bool
    human_response: Optional[str]

    # ── Evidence tracking ─────────────────────────────────────────────
    files_referenced: list[str]
    files_changed: list[str]
    git_diff_summary: Optional[str]

    # ── Tool call audit ───────────────────────────────────────────────
    tools_called: list[str]
    approval_required_tools_called: list[str]

    # ── Decision ──────────────────────────────────────────────────────
    primary_review_decision: Optional[str]     # "passes_first_pass" | "revise" | "blocked"
    secondary_review_decision: Optional[str]    # "confirm" | "concern" | "revise" | "blocked"
    final_decision: Optional[Literal["complete", "revise", "blocked", "verify"]]
    decision_rationale: Optional[str]

    # ── Repair tracking ───────────────────────────────────────────────
    repair_conditions: list[dict]           # drift/conflict conditions found
    transition_blocked: bool                # set when repair is needed

    # ── Messages (LangGraph standard) ─────────────────────────────────
    messages: Annotated[list, add_messages]

    # ── Metadata ──────────────────────────────────────────────────────
    classification_confidence: Optional[float]
    cost_accumulated_usd: float
    started_at: Optional[str]
    completed_at: Optional[str]
