"""
Workbench orchestrator CLI entrypoint.

Usage:
    python -m orchestrator.run --project ahamkara --request "Add dark mode"
    python -m orchestrator.run --project ahamkara --session <session_id> --resume
    python -m orchestrator.run --project ahamkara --scan-drift
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml


def main():
    parser = argparse.ArgumentParser(
        description="Cross-project multi-agent engineering workbench"
    )
    parser.add_argument(
        "--project", "-p",
        required=True,
        help="Project ID (must exist in projects/registry.yaml)",
    )
    parser.add_argument(
        "--request", "-r",
        help="User request string (starts a new workflow session)",
    )
    parser.add_argument(
        "--session", "-s",
        help="Session ID to resume (requires --resume)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an existing session",
    )
    parser.add_argument(
        "--scan-drift",
        action="store_true",
        help="Scan project vault for queue drift and print repair conditions",
    )
    parser.add_argument(
        "--in-memory",
        action="store_true",
        help="Use in-memory checkpointer (ephemeral, for smoke tests)",
    )
    parser.add_argument(
        "--human-response",
        help="Human response for an awaiting checkpoint",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print verbose execution metadata",
    )
    parser.add_argument(
        "--watch", "-w",
        action="store_true",
        help="Start queue filesystem watcher and print events (Ctrl+C to stop)",
    )
    parser.add_argument(
        "--watch-interval",
        type=float,
        default=5.0,
        help="Polling interval in seconds for --watch (default: 5.0)",
    )
    parser.add_argument(
        "--chat",
        action="store_true",
        help="Chat mode: talk to the model group and auto-queue explicit Task blocks",
    )
    parser.add_argument(
        "--role",
        default="worker",
        help="Model role to use for --chat (default: worker)",
    )
    parser.add_argument(
        "--response-mode",
        default="brief",
        choices=["brief", "explain"],
        help="Chat response style (default: brief)",
    )
    parser.add_argument(
        "--chat-context",
        default="",
        help="Optional thread memory hint for chat mode",
    )
    parser.add_argument(
        "--discourse",
        action="store_true",
        help="Discourse mode: run collaborative discussion among agents to flesh out an idea",
    )
    parser.add_argument(
        "--discourse-roles",
        default="",
        help="Comma-separated roles for discourse participants (default: worker,primary_reviewer)",
    )
    parser.add_argument(
        "--json-stream",
        action="store_true",
        help="Emit structured JSON events to stdout (for UI consumption)",
    )
    parser.add_argument(
        "--spec",
        type=str,
        default="",
        help="Path to a specification document to flesh out into a project plan",
    )
    parser.add_argument(
        "--spec-text",
        type=str,
        default="",
        help="Inline specification text (used with --spec or standalone)",
    )

    args = parser.parse_args()

    # ── Resolve paths ─────────────────────────────────────────────────
    vault_root = Path(__file__).resolve().parent.parent
    registry_path = vault_root / "projects" / "registry.yaml"

    if not registry_path.exists():
        print(f"ERROR: Registry not found at {registry_path}", file=sys.stderr)
        sys.exit(1)

    # ── Load registry ─────────────────────────────────────────────────
    with open(registry_path) as f:
        registry = yaml.safe_load(f)

    project_config = None
    for proj in registry.get("projects", []):
        if proj["id"] == args.project:
            project_config = proj
            break

    if project_config is None:
        print(f"ERROR: Project '{args.project}' not found in registry.", file=sys.stderr)
        print(f"Available projects: {[p['id'] for p in registry.get('projects', [])]}",
              file=sys.stderr)
        sys.exit(1)

    # ── Load project-specific config ──────────────────────────────────
    proj_config_path = (
        vault_root / "projects" / args.project / "project-config.yaml"
    )
    proj_overrides = {}
    if proj_config_path.exists():
        with open(proj_config_path) as f:
            proj_overrides = yaml.safe_load(f) or {}

    # ── Validate project model policy ─────────────────────────────────
    model_policy = proj_overrides.get("model_policy", {})
    if model_policy:
        from .model_policy import preflight_check

        warnings = preflight_check(model_policy)
        if warnings:
            print(f"WARNING: Model policy issues for '{args.project}':")
            for w in warnings:
                print(f"  - {w}")
    else:
        print(f"WARNING: Project '{args.project}' has no model_policy. "
              f"All model invocations will be denied.",
              file=sys.stderr)

    # ── Load model routing ────────────────────────────────────────────
    routing_path = vault_root / "model-routing" / "routing.yaml"
    routing = {}
    if routing_path.exists():
        with open(routing_path) as f:
            routing = yaml.safe_load(f)

    model_routing = _extract_model_ids(routing)

    # ── Scan drift mode ───────────────────────────────────────────────
    if args.scan_drift:
        _run_drift_scan(project_config, vault_root)
        return

    # ── Pre-flight drift scan ─────────────────────────────────────────
    if not args.scan_drift and not args.watch:
        _run_preflight_drift_check(project_config, vault_root)

    # ── Watch mode ────────────────────────────────────────────────────
    if args.watch:
        _run_watcher(project_config, args.watch_interval)
        return

    # ── Spec-to-project mode ──────────────────────────────────────────
    if args.spec or args.spec_text:
        _run_spec_pipeline(
            spec_path=args.spec,
            spec_text=args.spec_text or args.request or "",
            project_config=project_config,
            model_policy=model_policy,
            model_routing=model_routing,
        )
        return

    # ── Discourse mode ────────────────────────────────────────────────
    if args.discourse:
        if not args.request:
            print("ERROR: --discourse requires a message via --request/-r", file=sys.stderr)
            sys.exit(1)
        _run_discourse(
            args.request,
            project_config,
            model_policy,
            roles=args.discourse_roles,
            model_routing=model_routing,
            json_stream=args.json_stream,
        )
        return

    # ── Chat mode ─────────────────────────────────────────────────────
    if args.chat:
        if not args.request:
            print("ERROR: --chat requires a message via --request/-r", file=sys.stderr)
            sys.exit(1)
        _run_chat(
            args.request,
            project_config,
            model_policy,
            role=args.role,
            response_mode=args.response_mode,
            chat_context=args.chat_context,
        )
        return

    # ── Validate request vs resume ────────────────────────────────────
    if args.resume and not args.session:
        print("ERROR: --resume requires --session <session_id>", file=sys.stderr)
        sys.exit(1)
    if not args.resume and not args.request:
        print("ERROR: Either --request or --resume is required.", file=sys.stderr)
        sys.exit(1)

    # ── Initialize checkpointer ───────────────────────────────────────
    from .persistence import get_checkpointer

    checkpointer = get_checkpointer(use_sqlite=not args.in_memory)

    # ── Compile graph ─────────────────────────────────────────────────
    from .graph import compile_graph

    graph = compile_graph(checkpointer=checkpointer)

    # ── Build initial state ───────────────────────────────────────────
    session_id = args.session or str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    config = {
        "configurable": {
            "thread_id": session_id,
        }
    }

    # ── Initialize tracing ────────────────────────────────────────────
    try:
        from .tracing import set_run_metadata
        set_run_metadata(session_id, args.project)
    except Exception:
        pass  # tracing is optional

    if args.resume:
        # ── Resume existing session ───────────────────────────────────
        current_state = graph.get_state(config)
        if current_state is None or current_state.values is None:
            print(f"ERROR: No state found for session {session_id}", file=sys.stderr)
            sys.exit(1)

        if args.human_response:
            graph.update_state(
                config,
                {"human_response": args.human_response, "human_approval_required": False},
            )

        if args.verbose:
            _print_state_summary(current_state.values)

        print(f"Resuming session {session_id}...")
        result = graph.invoke(None, config)

    else:
        # ── Start new session ─────────────────────────────────────────
        initial_state = {
            "session_id": session_id,
            "project_id": args.project,
            "project_vault_root": str(Path(project_config["vault_root"]).resolve()),
            "project_repo_root": str(Path(project_config["repo_root"]).resolve()),
            "project_report_root": str(
                Path(project_config.get("report_root", "")).resolve()
                if project_config.get("report_root")
                else ""
            ),
            "user_request": args.request,
            "workflow_intent": "task",
            "revision_count": 0,
            "task_record_path": None,
            "task_snapshot_path": None,
            "task_event_log_path": None,
            "task_context_pack_paths": {},
            "rendered_view_paths": {},
            "worker_report_record_path": None,
            "primary_review_record_path": None,
            "secondary_review_record_path": None,
            "decision_record_path": None,
            "plan_manifest_path": None,
            "plan_id": None,
            "plan_title": None,
            "plan_summary": None,
            "plan_step_index": None,
            "plan_step_total": None,
            "plan_step_title": None,
            "plan_step_goal": None,
            "plan_should_queue_next": False,
            "human_questions": [],
            "human_approval_required": False,
            "files_referenced": [],
            "files_changed": [],
            "tools_called": [],
            "approval_required_tools_called": [],
            "repair_conditions": [],
            "transition_blocked": False,
            "cost_accumulated_usd": 0.0,
            "started_at": now,
            "model_policy": model_policy,
            **model_routing,
        }

        if args.verbose:
            print(f"Starting session {session_id}")
            print(f"Project: {args.project} ({project_config['repo_root']})")
            print(f"Request: {args.request}")
            print(f"Models: worker={model_routing.get('worker_model')}, "
                  f"primary={model_routing.get('primary_reviewer_model')}, "
                  f"secondary={model_routing.get('secondary_reviewer_model')}")

        print(f"Invoking workbench graph (session={session_id})...")
        result = graph.invoke(initial_state, config)

    # ── Print result ──────────────────────────────────────────────────
    if args.verbose:
        _print_state_summary(result)

    decision = result.get("final_decision", "unknown")
    task = result.get("current_task_filename", "unknown")
    questions = result.get("human_questions", [])

    print(f"\nSession: {session_id}")
    print(f"Decision: {decision}")
    print(f"Task: {task}")

    if questions:
        print("\nHuman questions:")
        for q in questions:
            print(f"  - {q}")
        print(f"\nResume with: python -m orchestrator.run -p {args.project} "
              f"-s {session_id} --resume --human-response \"<your response>\"")

    if result.get("transition_blocked"):
        print("\nWARNING: Transition blocked due to repair conditions.")
        repairs = result.get("repair_conditions", [])
        for r in repairs:
            print(f"  - [{r.get('severity', '?')}] {r.get('description', '?')}")


def _extract_model_ids(routing: dict) -> dict:
    """Resolve role → model_ref → nickname for graph state fields.

    State fields store nicknames (human-facing labels), not raw model_ids.
    Nicknames are the primary identity in logs, traces, and review notes.

    supervisor_planner_model maps to secondary_reviewer (Codex) because
    the escalation-fallback planner is the same model as the secondary
    reviewer. Both only activate on escalation — Codex takes a back seat.
    """
    from .llm_client import resolve_role_nickname

    def _nickname(role: str) -> str:
        try:
            return resolve_role_nickname(role)
        except Exception:
            return ""

    return {
        "worker_model": _nickname("worker"),
        "primary_reviewer_model": _nickname("primary_reviewer"),
        "secondary_reviewer_model": _nickname("secondary_reviewer"),
        "classifier_model": _nickname("classifier"),
        "supervisor_planner_model": _nickname("secondary_reviewer"),
        "bookkeeping_reviewer_model": _nickname("bookkeeping_reviewer"),
    }


def _run_drift_scan(project_config: dict, vault_root: Path):
    """Run a queue drift scan on the project vault."""
    from .repair import scan_vault_for_drift

    vault_path = Path(project_config["vault_root"])
    conditions = scan_vault_for_drift(vault_path)

    if not conditions:
        print("No drift detected.")
        return

    print(f"Found {len(conditions)} drift condition(s):\n")
    for c in conditions:
        print(f"  Task: {c.task_filename}")
        print(f"  Type: {c.condition_type}")
        print(f"  Description: {c.description}")
        if c.affected_paths:
            print(f"  Paths: {', '.join(c.affected_paths)}")
        print(f"  Suggested: {c.suggested_action}")
        print()


def _run_preflight_drift_check(project_config: dict, vault_root: Path):
    """Run a pre-flight drift scan. Warns on drift. Blocks if severe."""
    from .repair import scan_vault_for_drift

    vault_path = Path(project_config["vault_root"])
    conditions = scan_vault_for_drift(vault_path)

    if not conditions:
        return

    duplicates = [c for c in conditions if c.condition_type == "duplicate_task"]
    missing_reports = [c for c in conditions if c.condition_type == "missing_report"]

    print(f"\nWARNING: Pre-flight drift scan found {len(conditions)} issue(s) "
          f"in {vault_path}/queue-tasks/:")
    for c in conditions:
        print(f"  [{c.condition_type}] {c.task_filename}: {c.description}")

    if duplicates:
        print(f"\n  {len(duplicates)} duplicate task(s) detected. "
              f"These tasks exist in multiple queue folders simultaneously. "
              f"Fix before running the orchestrator to avoid invariant violations.")
        print(f"  Run: python -m orchestrator.run -p {project_config['project_id']} --scan-drift")

    if missing_reports:
        print(f"  {len(missing_reports)} task(s) in review-needed/ without report links.\n")


def _print_state_summary(state: dict):
    """Print a human-readable state summary."""
    print("\n── State Summary ──")
    for key in (
        "session_id", "project_id", "task_type", "risk_level",
        "workflow_intent", "escalation_tier", "revision_count", "current_node",
        "current_task_filename", "primary_review_decision",
        "secondary_review_decision", "final_decision",
    ):
        val = state.get(key)
        if val:
            print(f"  {key}: {val}")
    print("────────────────────\n")


def _run_watcher(project_config: dict, interval: float):
    """Start the queue filesystem watcher for a project.

    Monitors both queue-tasks/ and machine/human-input/ directories.
    """
    from .watcher import QueueWatcher
    from .human_channel import HumanInputWatcher

    vault_path = Path(project_config["vault_root"])
    watcher = QueueWatcher(vault_root=vault_path, interval=interval)
    human_watcher = HumanInputWatcher(vault_root=vault_path, interval=interval)

    def on_claimed(filename: str):
        print(f"[queue] task_claimed  {filename}")

    def on_completed(filename: str):
        print(f"[queue] task_completed  {filename}")

    def on_queued(filename: str):
        print(f"[queue] task_queued  {filename}")

    def on_human_input(inputs: list[dict]):
        for inp in inputs:
            target = inp.get("to_role", "all")
            msg_type = inp.get("type", "guidance")
            subject = inp.get("subject", "(no subject)")
            print(f"[human-input] to={target} type={msg_type} subject={subject}")

    watcher.on_claimed = on_claimed
    watcher.on_completed = on_completed
    watcher.on_queued = on_queued
    human_watcher.on_input = on_human_input

    print(f"Watching {vault_path}/queue-tasks/ (interval={interval}s)")
    print(f"Watching {vault_path}/machine/human-input/ (interval={interval}s)")
    print("Press Ctrl+C to stop.\n")

    watcher.start()
    human_watcher.start()

    try:
        while watcher.is_running() or human_watcher.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping watchers...")
    finally:
        watcher.stop()
        human_watcher.stop()


def _run_spec_pipeline(
    spec_path: str,
    spec_text: str,
    project_config: dict,
    model_policy: dict,
    model_routing: dict | None = None,
):
    """Run the spec-to-project pipeline.

    Reads a spec document, runs collaborative discourse among agents,
    and produces a plan manifest with queued tasks.
    """
    from .spec_to_project import run_spec_pipeline

    vault_root = Path(project_config["vault_root"])
    model_routing = model_routing or {}

    spec_source = spec_path or "(inline text)"
    print(f"\n╔═══ Spec-to-Project Pipeline ═══════════════════════════════")
    print(f"║  Spec source: {spec_source}")
    print(f"║  Project: {project_config.get('name', project_config['id'])}")
    print(f"╚══════════════════════════════════════════════════════════════\n")

    result = run_spec_pipeline(
        spec_text=spec_text,
        spec_path=spec_path if spec_path else None,
        project_config=project_config,
        model_policy=model_policy,
        model_routing=model_routing,
    )

    if "error" in result:
        print(f"ERROR: {result['error']}")
        return

    print("\n╔═══ Spec Pipeline Complete ══════════════════════════════════")
    print(f"║  Consensus reached: {result.get('consensus_reached', False)}")
    print(f"║  Task count: {result.get('spec_task_count', 0)}")

    summary = result.get("spec_summary", "")
    if summary:
        label = summary[:300] + "..." if len(summary) > 300 else summary
        print(f"║  Summary: {label}")

    plan_manifest = result.get("plan_manifest_path", "")
    if plan_manifest:
        full_path = vault_root / plan_manifest
        print(f"║  Plan manifest: {full_path}")

    queued = result.get("queued_first_task", "")
    if queued:
        print(f"║  First task queued: {queued}")

    summary_path = result.get("spec_summary_path", "")
    if summary_path:
        print(f"║  Summary record: {vault_root / summary_path}")

    print(f"╚══════════════════════════════════════════════════════════════\n")

    tasks = result.get("spec_tasks", [])
    if tasks:
        print(f"\n── Task Breakdown ({len(tasks)} tasks) ──")
        for i, t in enumerate(tasks, 1):
            print(f"  {i}. {t.get('title', 'Untitled')} ({t.get('task_type', 'implementation')})")
            goal = t.get('goal', '')
            if goal:
                print(f"     Goal: {goal[:150]}")

    if not result.get("consensus_reached"):
        print("\nNOTE: Discourse did not reach full consensus. Check the record for unresolved items.")


def _run_discourse(
    request: str,
    project_config: dict,
    model_policy: dict,
    roles: str = "",
    model_routing: dict | None = None,
    json_stream: bool = False,
):
    """Run collaborative discourse mode.

    Triggers a multi-turn discussion among agent roles to flesh out
    an idea, spec, or request into a structured plan.

    When json_stream=True, emits structured JSON events per line on
    stdout for UI consumption (includes token-level streaming).
    """
    if json_stream:
        _run_discourse_json_stream(
            request=request,
            project_config=project_config,
            model_policy=model_policy,
            roles=roles,
            model_routing=model_routing,
        )
        return

    from .nodes.collaborative_discourse import collaborative_discourse_node
    from .llm_client import resolve_role_nickname

    vault_root = Path(project_config["vault_root"])
    model_routing = model_routing or {}

    # Parse override roles
    participant_roles = [r.strip() for r in roles.split(",") if r.strip()]
    if not participant_roles:
        participant_roles = ["worker", "primary_reviewer"]

    nicknames = []
    for role in participant_roles:
        try:
            nicknames.append(resolve_role_nickname(role))
        except Exception:
            nicknames.append(role)

    print(f"\n╔═══ Collaborative Discourse ═══════════════════════════════")
    print(f"║  Request: {request}")
    print(f"║  Participants: {', '.join(f'{r} ({n})' for r, n in zip(participant_roles, nicknames))}")
    print(f"║  Project: {project_config.get('name', project_config['id'])}")
    print(f"╚══════════════════════════════════════════════════════════════\n")

    # Build a minimal state for the discourse node
    state = {
        "project_vault_root": str(vault_root.resolve()),
        "project_id": project_config["id"],
        "user_request": request,
        "task_type": "implementation",
        "workflow_intent": "discussion",
        "escalation_tier": "low",
        "risk_level": "low",
        "model_policy": model_policy,
        "current_node": "collaborative_discourse",
        "worker_model": model_routing.get("worker_model", ""),
        "primary_reviewer_model": model_routing.get("primary_reviewer_model", ""),
        "secondary_reviewer_model": model_routing.get("secondary_reviewer_model", ""),
        "classifier_model": model_routing.get("classifier_model", ""),
        "supervisor_planner_model": model_routing.get("supervisor_planner_model", ""),
        "bookkeeping_reviewer_model": model_routing.get("bookkeeping_reviewer_model", ""),
        "discourse_thread_id": None,
        "discourse_summary": None,
        "discourse_agreements": [],
        "discourse_disagreements": [],
        "discourse_task_breakdown": [],
        "discourse_record_path": None,
        "discourse_consensus_reached": False,
        "discourse_ready_to_queue": True,
        "pending_agent_messages": [],
        "human_input_pending": False,
        "human_input_path": None,
        "human_input_last_checked": None,
    }

    result = collaborative_discourse_node(state)

    print("\n╔═══ Discourse Complete ══════════════════════════════════════")
    print(f"║  Consensus: {result.get('discourse_consensus_reached', False)}")
    print(f"║  Ready to queue: {result.get('discourse_ready_to_queue', False)}")

    summary = result.get("discourse_summary", "")
    if summary:
        print(f"║  Summary: {summary[:200]}..." if len(summary) > 200 else f"║  Summary: {summary}")

    record_path = result.get("discourse_record_path", "")
    if record_path:
        full_path = vault_root / record_path
        print(f"║  Record: {full_path}")

    agreements = result.get("discourse_agreements", [])
    if agreements:
        print(f"\n── Agreements ──")
        for a in agreements:
            print(f"  • {a[:150]}" if len(a) > 150 else f"  • {a}")

    disagreements = result.get("discourse_disagreements", [])
    if disagreements:
        print(f"\n── Disagreements / Risks ──")
        for d in disagreements:
            print(f"  • {d[:150]}" if len(d) > 150 else f"  • {d}")

    tasks = result.get("discourse_task_breakdown", [])
    if tasks:
        print(f"\n── Task Breakdown ({len(tasks)} tasks) ──")
        for t in tasks:
            print(f"  • {t.get('source', '')[:150]}")

    print(f"\n╚══════════════════════════════════════════════════════════════\n")

    if result.get("discourse_ready_to_queue"):
        print("Discussion converged. You can now queue the output as tasks.")
        print(f"  python -m orchestrator.run -p {project_config['id']} -r \"{request}\"")
    else:
        print("Discussion did not fully converge. Check the record and provide input:")
        print(f"  cat {vault_root}/machine/discourse/")


# ── JSON-streaming discourse (for UI consumption) ────────────────────

MAX_DISCOURSE_TURNS = 5
DISCOURSE_CONTEXT_BUDGET_CHARS = 2000
TERMINATION_SIGNAL = "DISCUSSION_COMPLETE"


_PARTICIPANT_PROMPTS = {
    "worker": """You are {nickname}, a worker agent in a collaborative engineering discussion.

Your job is to think through the technical implementation, ask clarifying
questions about scope, identify technical risks, and propose concrete
work breakdowns. When you are ready to proceed to implementation, signal
by saying "{signal}" on its own line.

Rules:
- Focus on feasibility, effort estimation, and implementation approach.
- If scope is unclear, ask the primary reviewer for judgment.
- If you need more info, ask.
- Be specific about subsystems, files, and patterns.
- When you have enough clarity, clearly state "{signal}".
- **YAGNI**: Before proposing any work, ask: "Does this need to exist?" If not, skip it.
- Prefer the simplest thing that works over an extensible framework.
- One-liner > dependency > abstraction layer. Always reach for the minimum viable solution.""",

    "primary_reviewer": """You are {nickname}, a primary reviewer in a collaborative engineering discussion.

Your job is to evaluate scope, judge risk, catch over-engineering, and
ensure the discussion converges on a clear, actionable plan. When you
are satisfied, signal by saying "{signal}" on its own line.

Rules:
- Keep scope tight. Push back on gold-plating.
- Identify acceptance criteria gaps.
- Decide when the plan is ready for queueing.
- When the plan is clear and scoped, state "{signal}".
- **YAGNI enforcer**: Scrutinize every proposed feature. If it's speculative, kill it.
- No "nice to haves". No speculative abstractions with one implementation.
- Prefer stdlib and native platform features over new dependencies.
- If the worker proposes a framework or abstraction layer, demand justification.""",
}


def _json_event(event_type: str, **payload) -> None:
    """Print a single JSON event line to stdout."""
    data = {"type": event_type, **payload}
    sys.stdout.write(json.dumps(data, default=str) + "\n")
    sys.stdout.flush()


def _run_discourse_json_stream(
    *,
    request: str,
    project_config: dict,
    model_policy: dict,
    roles: str = "",
    model_routing: dict | None = None,
) -> None:
    """
    Run discourse with streaming JSON events for the Tauri UI.

    Emits typed JSON events per line:
      discourse_start, turn_start, token, turn_end, discourse_complete
    """
    from .llm_client import call_llm_text_stream, resolve_role_nickname

    model_routing = model_routing or {}
    vault_root = Path(project_config["vault_root"])

    # Parse participants
    participant_roles = [r.strip() for r in roles.split(",") if r.strip()]
    if not participant_roles:
        participant_roles = ["worker", "primary_reviewer"]

    nicknames = {}
    for role in participant_roles:
        try:
            nicknames[role] = resolve_role_nickname(role)
        except Exception:
            nicknames[role] = role

    _json_event(
        "discourse_start",
        participants=",".join(participant_roles),
        nicknames=",".join(nicknames[r] for r in participant_roles),
        request=request,
        project=project_config.get("name", project_config["id"]),
    )

    conversation_history: list[str] = []

    for turn in range(1, MAX_DISCOURSE_TURNS + 1):
        all_done = True

        for role in participant_roles:
            nickname = nicknames.get(role, role)
            system_prompt = _PARTICIPANT_PROMPTS.get(
                role,
                f"You are {nickname}, discussing a task.",
            ).format(nickname=nickname, signal=TERMINATION_SIGNAL)

            # Build user prompt with conversation context
            context = "\n".join(conversation_history[-10:]) if conversation_history else "(no prior discussion)"
            user_prompt = (
                f"## Original Request\n\n{request}\n\n"
                f"## Discussion So Far (Turn {turn})\n\n"
                f"{context}\n\n"
                f"## Your Turn\n\n"
                f"Role: {role} ({nickname})\n"
                f"Turn: {turn}\n\n"
                f"Respond to the discussion. Build on what others have said. "
                f"When you have enough clarity for your role, say \"{TERMINATION_SIGNAL}\" "
                f"on its own line to signal you are ready to proceed."
            )

            _json_event("turn_start", role=role, nickname=nickname, turn=turn)

            try:
                full_text = ""
                token_usage: dict = {}
                for token in call_llm_text_stream(
                    role=role,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    project_policy=model_policy,
                    project_id=project_config["id"],
                    token_usage=token_usage,
                ):
                    full_text += token
                    _json_event("token", role=role, text=token)

                _json_event(
                    "turn_end",
                    role=role, text=full_text,
                    input_tokens=token_usage.get("input_tokens", 0),
                    output_tokens=token_usage.get("output_tokens", 0),
                )

                conversation_history.append(f"[{role}] {full_text.strip()}")

                # Trim context when over budget — keep most recent entries
                total_chars = sum(len(e) for e in conversation_history)
                if total_chars > DISCOURSE_CONTEXT_BUDGET_CHARS:
                    # Keep a summary prefix + the most recent entries
                    # Drop older entries that put us over budget
                    while len(conversation_history) > 2 and sum(len(e) for e in conversation_history) > DISCOURSE_CONTEXT_BUDGET_CHARS:
                        dropped = conversation_history.pop(0)
                    # If still over, trim the oldest entry's text
                    while len(conversation_history) > 1 and sum(len(e) for e in conversation_history) > DISCOURSE_CONTEXT_BUDGET_CHARS:
                        oldest = conversation_history[0]
                        if len(oldest) > 200:
                            conversation_history[0] = oldest[:200] + "... (trimmed)"
                        else:
                            break

                if TERMINATION_SIGNAL in full_text:
                    if role == "primary_reviewer":
                        _json_event("consensus", reached=True)
                        _json_event(
                            "discourse_complete",
                            consensus=True,
                            ready_to_queue=True,
                        )
                        return
                else:
                    all_done = False

            except Exception as e:
                _json_event("token", role=role, text=f"[error: {e}]")
                _json_event("turn_end", role=role, text=f"[error: {e}]")
                all_done = False

        if all_done:
            break

    _json_event("consensus", reached=True)
    _json_event(
        "discourse_complete",
        consensus=True,
        ready_to_queue=True,
    )


def _run_chat(
    request: str,
    project_config: dict,
    model_policy: dict,
    role: str = "worker",
    response_mode: str = "brief",
    chat_context: str = "",
):
    """Direct LLM conversation with optional task queue promotion."""
    from .llm_client import call_llm_text
    from .llm_client import resolve_role_nickname

    vault_root = Path(project_config["vault_root"])
    nickname = resolve_role_nickname(role)
    include_context = not _is_simple_greeting(request)
    context = ""
    if include_context:
        state_file = vault_root / "memory" / "current-state.md"
        if state_file.exists():
            content = state_file.read_text()
            if len(content) > 3000:
                content = content[:3000] + "\n... (truncated)"
            context = f"\n## Project State\n\n{content}"

    intro_guidance = (
        "If this is the first assistant turn in the current thread, introduce yourself once using your nickname. "
        "If thread memory says you have already introduced yourself, do not repeat the introduction. "
        "If the operator explicitly asks for introductions, you may introduce yourself again.\n"
    )
    kickoff_guidance = _build_chat_kickoff_guidance(request, chat_context)

    system_prompt = (
        "You are part of a multi-agent engineering workbench team.\n"
        "You are having a direct conversation with the operator (human product owner).\n"
        "This is a discussion. Do NOT create tasks, queue work, or modify files\n"
        "unless the operator explicitly asks you to, or you are deliberately\n"
        "proposing a concrete next slice in a `Task:` block for automatic queueing.\n"
        "If the thread is ready for the next executable slice, make that slice\n"
        "explicit in the `Task:` block so the workbench can queue it directly.\n"
        "If the work clearly spans multiple slices, use a compact `Plan:` block\n"
        "with one `Task:` subsection per slice so the workbench can queue the\n"
        "sequence automatically. Keep the first slice as small as possible.\n"
        f"Your speaking identity is '{nickname}'. Use that nickname when you refer to yourself.\n"
        f"Your workflow role is '{role}'. Treat the role as your job title and behavior contract.\n"
        f"{intro_guidance}"
        f"{kickoff_guidance}"
        "Be helpful, concise, and technically precise.\n"
        "Write the visible reply in natural Markdown, not raw logs.\n"
        "Prefer short paragraphs, bullets, numbered steps, bold for emphasis, and inline code for names or commands.\n"
        "Do not use tables unless they clearly improve readability.\n"
        "Do not wrap the whole response in a code fence.\n"
        "Match the operator's level of detail.\n"
        "For casual greetings or short acknowledgements, reply in one short sentence, no headings, no bullets, and do not recap project state.\n"
        "For normal technical questions, prefer a two-part shape: a short answer first, then an optional 'Details' section only if it helps.\n"
        "Keep the reply brief unless the operator asks for more detail.\n"
        "If you need another role to take over, end with a short Handoff section after the Markdown reply.\n"
        "Use this exact shape:\n"
        "Handoff:\n"
        "- role_name: one-sentence reason\n"
        "Only include roles that are actually needed.\n"
        "Do not add a handoff for casual greetings.\n"
        "If the conversation has converged on a concrete implementation slice, add a\n"
        "Task:\n"
        "- title: short title\n"
        "- type: implementation | docs | refactor | investigation\n"
        "- goal: one-sentence queueable goal\n"
        "- acceptance:\n"
        "  - concrete check\n"
        "  - concrete check\n"
        "- scope:\n"
        "  - in-bounds detail\n"
        "  - another in-bounds detail\n"
        "Only include this block when the thread is ready to become a queued task.\n"
        "Place it after the Handoff section so the visible reply still reads naturally.\n"
        f"{_chat_response_guidance(response_mode)}"
        f"\nProject: {project_config.get('name', project_config['id'])}\n"
        f"Repo: {project_config['repo_root']}\n"
        f"Your role: {role}\n"
        f"Your nickname: {nickname}\n"
        f"{_chat_role_guidance(role, nickname)}"
    )

    thread_memory = ""
    if chat_context.strip():
        thread_memory = f"\n## Thread Memory\n\n{chat_context.strip()}\n"

    user_prompt = f"{context}{thread_memory}\n\n## Operator\n\n{request}"

    try:
        response = call_llm_text(
            role=role,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            project_policy=model_policy,
            project_id=project_config["id"],
        )
        print(response)
        try:
            from .chat_task import queue_chat_task_from_response

            queue_chat_task_from_response(
                response=response,
                request=request,
                project_config=project_config,
                role=role,
                nickname=nickname,
                response_mode=response_mode,
            )
        except Exception as queue_error:
            print(f"WARNING: Failed to queue chat task: {queue_error}", file=sys.stderr)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def _chat_role_guidance(role: str, nickname: str) -> str:
    """Role-specific chat posture for hybrid free chat + handoff behavior."""
    role = (role or "").strip()
    nickname = (nickname or role or "").strip()

    if role == "worker":
        return (
            "\nRole guidance: You are the most eager responder. "
            "When you finish useful work, proactively hand off to primary_reviewer. "
            "When the task is simple or conversational, stay brief and do not hand off. "
            f"If this is the first turn in a thread, introduce yourself as {nickname}, not as the role name. "
            "After that, do not repeat the introduction unless explicitly asked. "
            "Keep greetings to one short Markdown sentence. "
            "For technical replies, use a short answer first and an optional Details section only when useful. "
            "If the thread has converged on a concrete next slice, you may add a Task block so the workbench can queue it.\n"
        )
    if role == "primary_reviewer":
        return (
            "\nRole guidance: You are less eager than worker. "
            "Only respond when pinged or explicitly addressed. "
            "If the result needs revisions, hand off to worker. "
            "If the result needs deeper scrutiny, hand off to secondary_reviewer. "
            f"If this is the first turn in a thread, introduce yourself as {nickname}, not as the role name. "
            "After that, do not repeat the introduction unless explicitly asked. "
            "Keep greetings to one short Markdown sentence. "
            "For technical replies, use a short answer first and an optional Details section only when useful. "
            "If you can name a clearer next slice, you may add a Task block so the workbench can queue it.\n"
        )
    if role == "secondary_reviewer":
        return (
            "\nRole guidance: You are the least eager responder. "
            "Only respond when pinged, escalated, or explicitly addressed. "
            "If you need changes, hand off to primary_reviewer. "
            f"If this is the first turn in a thread, introduce yourself as {nickname}, not as the role name. "
            "After that, do not repeat the introduction unless explicitly asked. "
            "Keep greetings to one short Markdown sentence. "
            "For technical replies, use a short answer first and an optional Details section only when useful. "
            "Only propose a Task block when escalation has revealed a concrete follow-up slice.\n"
        )
    if role == "classifier":
        return (
            "\nRole guidance: Keep responses short and classification-oriented. "
            "Do not hand off unless the operator explicitly asks. "
            f"If this is the first turn in a thread, introduce yourself as {nickname}, not as the role name. "
            "After that, do not repeat the introduction unless explicitly asked. "
            "Keep greetings to one short Markdown sentence. "
            "For technical replies, use a short answer first and an optional Details section only when useful.\n"
        )
    if role == "bookkeeping_reviewer":
        return (
            "\nRole guidance: Stay concise and bookkeeping-focused. "
            "Hand off only when another role must act. "
            f"If this is the first turn in a thread, introduce yourself as {nickname}, not as the role name. "
            "After that, do not repeat the introduction unless explicitly asked. "
            "Keep greetings to one short Markdown sentence. "
            "For technical replies, use a short answer first and an optional Details section only when useful.\n"
        )
    return ""


def _chat_response_guidance(response_mode: str) -> str:
    """Style guidance for the visible chat response."""
    mode = (response_mode or "brief").strip().lower()
    if mode == "explain":
        return (
            "\nResponse style: explain. Give a fuller explanation than usual. "
            "Start with a direct answer, then expand with reasoning, examples, caveats, "
            "and step-by-step detail when useful. Keep Markdown readable, but do not force brevity.\n"
        )

    return (
        "\nResponse style: brief. Keep answers concise by default. "
        "Use a short answer first, and only add a small Details section if it genuinely helps.\n"
    )


def _build_chat_kickoff_guidance(request: str, chat_context: str = "") -> str:
    from .plan_kickoff import build_plan_kickoff_chat_guidance

    return build_plan_kickoff_chat_guidance(request, chat_context)


def _is_simple_greeting(request: str) -> bool:
    """Detect short conversational openers that should stay very brief."""
    text = request.strip().lower()
    if not text:
        return False

    tokens = text.split()
    if len(tokens) > 4:
        return False

    return bool(re.match(r"^(hi|hello|hey|hiya|yo|good morning|good afternoon|good evening)([!.?]\s*)?$", text))


if __name__ == "__main__":
    main()
