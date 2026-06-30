"""
Temp-vault tests for plan sequence helpers.

These tests avoid touching the real project vaults. They verify that a
multi-slice `Plan:` block can become a manifest, queue the first slice, and
advance to the next slice after completion.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from orchestrator.chat_task import queue_chat_task_from_response
from orchestrator.nodes.final_decision import final_decision_node
from orchestrator.nodes.queue_task import queue_task_node
from orchestrator.plan_sequences import (
    load_plan_manifest,
    materialize_plan_manifest,
    parse_chat_plan_proposal,
)
from orchestrator.transitions import after_final_decision


PASSED = 0
FAILED = 0


def ok(msg: str) -> None:
    global PASSED
    PASSED += 1
    print(f"  PASS  {msg}")


def fail(msg: str) -> None:
    global FAILED
    FAILED += 1
    print(f"  FAIL  {msg}")


def make_vault_root(tmp_root: Path) -> Path:
    vault_root = tmp_root / "vault"
    for folder in ["open", "claimed", "review-needed", "completed", "blocked"]:
        (vault_root / "queue-tasks" / folder).mkdir(parents=True, exist_ok=True)
    (vault_root / "machine" / "plans").mkdir(parents=True, exist_ok=True)
    (vault_root / "README.md").write_text("# Temp Vault\n", encoding="utf-8")
    (vault_root / "01-repo-map.md").write_text("# Repo Map\n", encoding="utf-8")
    (vault_root / "memory").mkdir(parents=True, exist_ok=True)
    (vault_root / "memory" / "current-state.md").write_text("# Current State\n", encoding="utf-8")
    return vault_root


def make_state(vault_root: Path) -> dict:
    return {
        "session_id": "test-session",
        "project_id": "demo",
        "project_vault_root": str(vault_root),
        "project_repo_root": str(vault_root.parent / "repo"),
        "project_report_root": "",
        "user_request": "Start from the plan and keep going until it is done.",
        "task_type": "implementation",
        "workflow_intent": "plan_kickoff",
        "risk_level": "low",
        "escalation_tier": "low",
        "revision_count": 0,
        "current_node": "",
        "current_task_path": "",
        "current_task_filename": "",
        "task_record_path": None,
        "task_snapshot_path": None,
        "task_event_log_path": None,
        "task_context_pack_paths": {},
        "rendered_view_paths": {},
        "worker_report_path": "",
        "worker_report_record_path": None,
        "primary_review_path": "",
        "primary_review_record_path": None,
        "secondary_review_path": "",
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
        "human_response": "",
        "files_referenced": [],
        "files_changed": [],
        "git_diff_summary": "",
        "tools_called": [],
        "approval_required_tools_called": [],
        "primary_review_decision": "passes_first_pass",
        "secondary_review_decision": "confirm",
        "final_decision": "",
        "decision_rationale": "",
        "repair_conditions": [],
        "transition_blocked": False,
        "classification_confidence": 1.0,
        "cost_accumulated_usd": 0.0,
        "started_at": "",
        "completed_at": "",
        "messages": [],
    }


def test_parse_and_manifest(vault_root: Path) -> None:
    print("\n── test_parse_and_manifest ──")
    response = """We should split this into a plan.

Plan:
- title: Autonomy plan
- summary: Queue slices one at a time.
Task:
- title: Slice one
- goal: Create the manifest and queue the first slice.
- acceptance:
  - The manifest exists.
Task:
- title: Slice two
- goal: Advance the next step after completion.
- acceptance:
  - The next slice queues automatically.
"""

    proposal = parse_chat_plan_proposal(response)
    if proposal and len(proposal.tasks) == 2:
        ok("parsed two plan slices")
    else:
        fail(f"unexpected plan proposal: {proposal}")
        return

    manifest_path, filenames, plan_id = materialize_plan_manifest(
        vault_root=vault_root,
        project_id="demo",
        source_request="Start from the plan.",
        source_role="worker",
        source_nickname="Johnny",
        response_mode="brief",
        proposal=proposal,
    )

    manifest = load_plan_manifest(vault_root, manifest_path)
    if manifest.get("plan_id") == plan_id:
        ok("loaded manifest by plan id")
    else:
        fail("manifest did not round-trip plan id")

    if manifest.get("task_filenames") == filenames:
        ok("manifest preserved task filenames")
    else:
        fail("manifest task filenames mismatch")


def test_queue_and_continue(vault_root: Path) -> None:
    print("\n── test_queue_and_continue ──")
    response = """We should split this into a plan.

Plan:
- title: Autonomy plan
- summary: Queue slices one at a time.
Task:
- title: Slice one
- goal: Create the manifest and queue the first slice.
- acceptance:
  - The manifest exists.
Task:
- title: Slice two
- goal: Advance the next step after completion.
- acceptance:
  - The next slice queues automatically.
"""

    proposal = parse_chat_plan_proposal(response)
    assert proposal is not None
    manifest_path, filenames, plan_id = materialize_plan_manifest(
        vault_root=vault_root,
        project_id="demo",
        source_request="Start from the plan.",
        source_role="worker",
        source_nickname="Johnny",
        response_mode="brief",
        proposal=proposal,
    )

    state = make_state(vault_root)
    state.update(
        {
            "plan_manifest_path": manifest_path,
            "plan_id": plan_id,
            "plan_title": proposal.title,
            "plan_summary": proposal.summary,
            "plan_step_index": 1,
            "plan_step_total": len(proposal.tasks),
            "plan_step_title": proposal.tasks[0].title,
            "plan_step_goal": proposal.tasks[0].goal,
        }
    )

    updates = queue_task_node(state)
    merged = {**state, **updates}
    first_task = filenames[0]
    open_path = vault_root / "queue-tasks" / "open" / first_task

    if open_path.exists():
        ok("queued first slice into open/")
    else:
        fail("first slice was not queued")
        return

    content = open_path.read_text(encoding="utf-8")
    if "plan_manifest:" in content and "plan_step_index: 1" in content:
        ok("first slice carries plan frontmatter")
    else:
        fail("first slice is missing plan frontmatter")

    review_path = vault_root / "queue-tasks" / "review-needed" / first_task
    shutil.move(str(open_path), str(review_path))
    merged["current_task_filename"] = first_task
    merged["primary_review_decision"] = "passes_first_pass"
    merged["secondary_review_decision"] = "confirm"

    decision_updates = final_decision_node(merged)
    merged = {**merged, **decision_updates}

    if merged.get("plan_should_queue_next"):
        ok("final decision marked the plan as having a next slice")
    else:
        fail("final decision did not mark plan continuation")

    if after_final_decision(merged) == "queue_task":
        ok("transition routes back to queue_task for the next slice")
    else:
        fail("transition did not route back to queue_task")

    next_updates = queue_task_node(merged)
    next_merged = {**merged, **next_updates}
    second_task = filenames[1]
    next_open_path = vault_root / "queue-tasks" / "open" / second_task

    if next_open_path.exists():
        ok("queued the next slice automatically")
    else:
        fail("next slice was not queued")

    if next_merged.get("current_task_filename") == second_task:
        ok("state advanced to the next plan slice")
    else:
        fail("state did not advance to the next plan slice")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault_root(Path(tmp))
        test_parse_and_manifest(vault_root)
        test_queue_and_continue(vault_root)

    print(f"\nPassed: {PASSED}")
    print(f"Failed: {FAILED}")
    raise SystemExit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
