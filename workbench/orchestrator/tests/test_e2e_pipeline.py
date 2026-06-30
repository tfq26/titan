"""
End-to-end pipeline test against the Ahamkara project vault.

Tests the full node pipeline (classify → queue → claim → execute →
primary_review → final_decision) using the real Ahamkara vault
structure but with isolated test artifacts.

Each node is tested as a standalone function that takes state:dict
and returns an update:dict. No LangGraph installation required.

The test uses real vault paths but creates unique test task filenames
in each queue folder so existing tasks are not touched. All test
artifacts are cleaned up after the test run.

Usage:
    cd /Users/taufeeqali/Projects/workbench-vault
    python -m orchestrator.tests.test_e2e_pipeline
"""

from __future__ import annotations

import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure the workbench-vault root is on sys.path
_VAULT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VAULT_ROOT) not in sys.path:
    sys.path.insert(0, str(_VAULT_ROOT))


# ── Test configuration ────────────────────────────────────────────────

AHAMKARA_VAULT = Path("/Users/taufeeqali/Projects/Ahamkara/docs/vault")
AHAMKARA_REPO = Path("/Users/taufeeqali/Projects/Ahamkara")
AHAMKARA_REPORTS = AHAMKARA_REPO / "docs" / "reports" / "subagents"

# Permissive test policy — allows all roles with all model_refs.
# Tests don't go through run.py, so we set the policy directly.
TEST_MODEL_POLICY = {
    "allowed_roles": {
        "worker": ["worker_model"],
        "primary_reviewer": ["primary_reviewer_model"],
        "secondary_reviewer": ["secondary_reviewer_model"],
        "classifier": ["classifier_model"],
        "bookkeeping_reviewer": ["bookkeeping_reviewer_model"],
    },
    "denied_model_refs": [],
    "role_requirements": {
        "secondary_reviewer": {"escalation_tier": "high"},
        "bookkeeping_reviewer": {"task_type": ["docs", "bookkeeping"]},
    },
}

_now = datetime.now(timezone.utc)
TEST_TASK_ID = f"TEST-E2E-{_now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
TEST_TASK_FILENAME = f"TASK-{TEST_TASK_ID}.md"
TEST_PLAN_KICKOFF_FILENAME = f"TASK-PLAN-KICKOFF-{TEST_TASK_ID}.md"
TEST_REPORT_FILENAME = f"report-{TEST_TASK_ID}.md"

PASSED = 0
FAILED = 0


def log(msg: str) -> None:
    print(f"  {msg}")


def ok(msg: str) -> None:
    global PASSED
    PASSED += 1
    print(f"  PASS  {msg}")


def fail(msg: str) -> None:
    global FAILED
    FAILED += 1
    print(f"  FAIL  {msg}")


def cleanup():
    """Remove all test artifacts from the Ahamkara vault and reports."""
    for folder in ["open", "claimed", "review-needed", "completed", "blocked"]:
        queue_dir = AHAMKARA_VAULT / "queue-tasks" / folder
        for f in queue_dir.glob(f"*{TEST_TASK_ID}*"):
            f.unlink()
            log(f"Cleaned up: {f}")

    for f in AHAMKARA_REPORTS.glob(f"*{TEST_TASK_ID}*"):
        f.unlink()
        log(f"Cleaned up: {f}")


# ── State factory ─────────────────────────────────────────────────────

def make_initial_state() -> dict:
    """Build a realistic initial graph state for Ahamkara."""
    return {
        "session_id": f"test-session-{uuid.uuid4().hex[:8]}",
        "project_id": "ahamkara",
        "project_vault_root": str(AHAMKARA_VAULT),
        "project_repo_root": str(AHAMKARA_REPO),
        "project_report_root": str(AHAMKARA_REPORTS),
        "user_request": "Add a simple unit test for the math utility functions in src/common/math_utils.h",
        "task_type": "implementation",
        "workflow_intent": "task",
        "risk_level": "low",
        "escalation_tier": "low",
        "revision_count": 0,
        "current_node": "",
        "current_task_path": "",
        "current_task_filename": TEST_TASK_FILENAME,
        "worker_report_path": "",
        "primary_review_path": "",
        "secondary_review_path": "",
        "worker_model": "test-worker",
        "primary_reviewer_model": "test-primary",
        "secondary_reviewer_model": "test-secondary",
        "classifier_model": "test-classifier",
        "supervisor_planner_model": "test-planner",
        "bookkeeping_reviewer_model": "",
        "model_policy": TEST_MODEL_POLICY,
        "human_questions": [],
        "human_approval_required": False,
        "human_response": "",
        "files_referenced": [],
        "files_changed": ["src/common/math_utils_test.cpp"],
        "git_diff_summary": "+42 lines in math_utils_test.cpp",
        "tools_called": [],
        "approval_required_tools_called": [],
        "primary_review_decision": "",
        "secondary_review_decision": "",
        "final_decision": "",
        "decision_rationale": "",
        "repair_conditions": [],
        "transition_blocked": False,
        "classification_confidence": 0.0,
        "cost_accumulated_usd": 0.0,
        "started_at": "",
        "completed_at": "",
        "messages": [],
    }


# ── Test runners ──────────────────────────────────────────────────────

def test_classify_request():
    """Test: classify_request_node classifies the user request."""
    print("\n── test_classify_request ──")
    from orchestrator.nodes.classify_request import classify_request_node

    state = make_initial_state()
    updates = classify_request_node(state)
    merged = {**state, **updates}

    if merged.get("task_type") in ("implementation", "docs", "refactor", "investigation"):
        ok(f"task_type = {merged['task_type']}")
    else:
        fail(f"unexpected task_type: {merged.get('task_type')}")

    if merged.get("workflow_intent") in ("task", "plan_kickoff"):
        ok(f"workflow_intent = {merged.get('workflow_intent')}")
    else:
        fail(f"unexpected workflow_intent: {merged.get('workflow_intent')}")

    if isinstance(merged.get("classification_confidence"), (int, float)):
        ok(f"confidence = {merged['classification_confidence']}")
    else:
        fail(f"missing or invalid confidence: {merged.get('classification_confidence')}")

    if merged.get("current_node") == "classify_request":
        ok("current_node set correctly")
    else:
        fail(f"current_node = {merged.get('current_node')}")

    return merged


def test_classify_risk(state: dict):
    """Test: classify_risk_node determines risk_level and escalation_tier."""
    print("\n── test_classify_risk ──")
    from orchestrator.nodes.classify_risk import classify_risk_node

    updates = classify_risk_node(state)
    merged = {**state, **updates}

    if merged.get("risk_level") in ("low", "high"):
        ok(f"risk_level = {merged['risk_level']}")
    else:
        fail(f"unexpected risk_level: {merged.get('risk_level')}")

    if merged.get("escalation_tier") in ("low", "high"):
        ok(f"escalation_tier = {merged['escalation_tier']}")
    else:
        fail(f"unexpected escalation_tier: {merged.get('escalation_tier')}")

    # A low-risk "add unit test" task should classify as low
    if merged["risk_level"] == "low" and merged["escalation_tier"] == "low":
        ok("correctly classified as low/low for unit test task")
    else:
        log(f"classified as {merged['risk_level']}/{merged['escalation_tier']} (may be valid depending on model)")

    return merged


def test_queue_task(state: dict):
    """Test: queue_task_node writes a task file to queue-tasks/open/."""
    print("\n── test_queue_task ──")
    from orchestrator.nodes.queue_task import queue_task_node

    updates = queue_task_node(state)
    merged = {**state, **updates}

    task_filename = merged.get("current_task_filename", "")
    task_path_str = merged.get("current_task_path", "")

    if task_filename:
        ok(f"task_filename = {task_filename}")
    else:
        fail("no task_filename set")

    if task_path_str:
        ok(f"task_path = {task_path_str}")
    else:
        fail("no task_path set")

    # Verify the file was written to open/
    open_path = AHAMKARA_VAULT / "queue-tasks" / "open" / task_filename
    if open_path.exists():
        ok(f"task file exists in open/: {open_path.name}")
        content = open_path.read_text()
        if "Add a simple unit test" in content:
            ok("task file contains user request")
        if "queued-task" in content:
            ok("task file has correct frontmatter type")
        if "workflow_intent: task" in content:
            ok("task file records workflow_intent = task")
    else:
        fail(f"task file not found in open/: {open_path}")

    return merged


def test_plan_kickoff_queue_task():
    """Test: plan kickoff tasks include kickoff-specific instructions."""
    print("\n── test_plan_kickoff_queue_task ──")
    from orchestrator.nodes.queue_task import queue_task_node

    state = make_initial_state()
    state["current_task_filename"] = TEST_PLAN_KICKOFF_FILENAME
    state["user_request"] = (
        "Kick off the implementation plan for the current-state snapshot and "
        "coordinate the first slice with the team."
    )
    state["workflow_intent"] = "plan_kickoff"

    updates = queue_task_node(state)
    merged = {**state, **updates}

    task_filename = merged.get("current_task_filename", "")
    open_path = AHAMKARA_VAULT / "queue-tasks" / "open" / task_filename

    if open_path.exists():
        ok(f"plan kickoff task file exists in open/: {open_path.name}")
        content = open_path.read_text()
        if "workflow_intent: plan_kickoff" in content:
            ok("task file records workflow_intent = plan_kickoff")
        else:
            fail("task file missing workflow_intent = plan_kickoff")

        if "## Plan Kickoff" in content:
            ok("task file includes plan kickoff section")
        else:
            fail("task file missing plan kickoff section")
    else:
        fail(f"plan kickoff task file not found in open/: {open_path}")

    return merged


def test_chat_task_bridge():
    """Test: explicit chat Task blocks are promoted into queue-tasks/open/."""
    print("\n── test_chat_task_bridge ──")
    from orchestrator.chat_task import parse_chat_task_proposal, queue_chat_task_from_response

    response = """Here is the smallest executable slice.

Task:
- title: Promote chat task proposals into the queue
- type: implementation
- goal: Auto-create a queue task when chat output includes a structured Task block.
- acceptance:
  - The parser extracts title, goal, and list fields from a chat Task block.
  - A task file is written into queue-tasks/open/.
- scope:
  - orchestrator/chat_task.py
  - orchestrator/run.py
"""

    proposal = parse_chat_task_proposal(response)
    if proposal and proposal.title == "Promote chat task proposals into the queue":
        ok("parsed chat task title")
    else:
        fail(f"unexpected chat task proposal: {proposal}")

    project_config = {
        "id": "ahamkara",
        "vault_root": str(AHAMKARA_VAULT),
        "name": "Ahamkara",
        "repo_root": str(AHAMKARA_REPO),
    }

    task_filename = None
    task_path = None
    try:
        task_filename = queue_chat_task_from_response(
            response=response,
            request="Promote a chat-surfaced slice into the queue.",
            project_config=project_config,
            role="worker",
            nickname="Johnny",
            response_mode="brief",
        )
        if task_filename:
            ok(f"queued chat task filename = {task_filename}")
        else:
            fail("chat task bridge did not create a queued task")
            return

        task_path = AHAMKARA_VAULT / "queue-tasks" / "open" / task_filename
        if task_path.exists():
            ok(f"chat task file exists in open/: {task_path.name}")
            content = task_path.read_text()
            if "queued-task" in content:
                ok("chat task file has queued-task frontmatter")
            if "## Chat Proposal" in content:
                ok("chat task file includes chat proposal appendix")
            if "## Source Request" in content and "Promote a chat-surfaced slice into the queue." in content:
                ok("chat task file records source request")
        else:
            fail(f"chat task file not found in open/: {task_path}")
    finally:
        if task_path and task_path.exists():
            task_path.unlink()
            log(f"Cleaned up: {task_path}")

    return {}


def test_await_worker_claim(state: dict):
    """Test: await_worker_claim_node detects when a task is claimed."""
    print("\n── test_await_worker_claim ──")
    from orchestrator.nodes.await_worker_claim import await_worker_claim_node

    task_filename = state.get("current_task_filename", "")

    # Step 1: Task should be in open/, not yet claimed
    updates = await_worker_claim_node(state)
    questions = updates.get("human_questions", [])
    if any("waiting" in q.lower() for q in questions):
        ok("correctly reports task is waiting to be claimed")
    else:
        fail(f"expected 'waiting' message, got: {questions}")

    # Step 2: Simulate worker claim by moving file to claimed/
    open_path = AHAMKARA_VAULT / "queue-tasks" / "open" / task_filename
    claimed_dir = AHAMKARA_VAULT / "queue-tasks" / "claimed"
    claimed_dir.mkdir(parents=True, exist_ok=True)
    claimed_path = claimed_dir / task_filename
    shutil.move(str(open_path), str(claimed_path))
    log(f"Simulated claim: moved {task_filename} to claimed/")

    # Step 3: Now the claim should be detected
    updates2 = await_worker_claim_node(state)
    questions2 = updates2.get("human_questions", [])
    if not questions2:
        ok("correctly detects claim (no questions)")
    else:
        fail(f"expected no questions after claim, got: {questions2}")

    return state


def test_worker_execution(state: dict):
    """Test: worker_execution_node verifies worker completion."""
    print("\n── test_worker_execution ──")
    from orchestrator.nodes.worker_execution import worker_execution_node
    from orchestrator.nodes.await_worker_claim import await_worker_claim_node

    task_filename = state.get("current_task_filename", "")

    # Step 1: Task in claimed/ but no report → should report not ready
    updates = await_worker_claim_node(state)  # re-check state
    updates2 = worker_execution_node({**state, **updates})
    questions = updates2.get("human_questions", [])
    if any("not been moved" in q.lower() or "has not been moved" in q.lower() for q in questions):
        ok("correctly reports task not yet in review-needed")
    else:
        fail(f"expected 'not been moved' message, got: {questions[:1]}")

    # Step 2: Simulate worker completion: write report, move task to review-needed/
    report_content = f"""---
type: worker-report
status: complete
created: {_now.strftime('%Y-%m-%d %H:%M')}
worker: test-worker
worker_model: test-worker
task: {task_filename}
---

# Worker Report

## Task

{task_filename}

## Summary

Added unit tests for math_utils.h functions. All 12 test cases pass.

## Files Changed

- src/common/math_utils_test.cpp

## Evidence

- Build passes
- Tests pass: 12/12
- git diff: +42 lines in math_utils_test.cpp

## Self-Check

- Stayed within scope: yes
- No surprising files touched: correct
- Validation run: yes, all tests pass

## Next Step

Move task to review-needed/.
"""
    report_path = AHAMKARA_REPORTS / TEST_REPORT_FILENAME
    report_path.write_text(report_content)
    log(f"Wrote report: {report_path.name}")

    # Move task to review-needed/ and update frontmatter with report link
    claimed_path = AHAMKARA_VAULT / "queue-tasks" / "claimed" / task_filename
    review_dir = AHAMKARA_VAULT / "queue-tasks" / "review-needed"
    review_dir.mkdir(parents=True, exist_ok=True)
    review_path = review_dir / task_filename

    task_content = claimed_path.read_text()
    lines = task_content.split("\n")
    new_lines = []
    for line in lines:
        if line.startswith("report:"):
            new_lines.append(f"report: docs/reports/subagents/{TEST_REPORT_FILENAME}")
        elif line.startswith("status:"):
            new_lines.append("status: review-needed")
        else:
            new_lines.append(line)
    review_path.write_text("\n".join(new_lines))
    claimed_path.unlink()
    log(f"Simulated worker completion: {task_filename} → review-needed/")

    # Step 3: Now worker_execution_node should detect completion
    updated_state = {**state, "worker_report_path": f"docs/reports/subagents/{TEST_REPORT_FILENAME}"}
    updates3 = worker_execution_node(updated_state)
    questions3 = updates3.get("human_questions", [])
    if not questions3:
        ok("correctly detects worker completion")
    else:
        fail(f"expected no questions after completion, got: {questions3}")

    if updates3.get("worker_report_path"):
        ok(f"worker_report_path set: {updates3['worker_report_path']}")
    else:
        fail("worker_report_path not set")

    return {**state, **updates3}


def test_primary_review(state: dict):
    """Test: primary_review_node produces a review decision and writes a review note."""
    print("\n── test_primary_review ──")
    from orchestrator.nodes.primary_review import primary_review_node

    task_filename = state.get("current_task_filename", "")

    updates = primary_review_node(state)
    merged = {**state, **updates}

    decision = merged.get("primary_review_decision", "")
    if decision in ("passes_first_pass", "revise", "blocked"):
        ok(f"primary_review_decision = {decision}")
    else:
        fail(f"unexpected primary_review_decision: {decision}")

    review_path_str = merged.get("primary_review_path", "")
    if review_path_str:
        ok(f"primary_review_path = {review_path_str}")
        # Verify the review note exists on disk
        review_full_path = AHAMKARA_VAULT / review_path_str
        if review_full_path.exists():
            ok("review note file exists on disk")
            content = review_full_path.read_text()
            if "Primary Review" in content:
                ok("review note has correct heading")
            if decision in content:
                ok(f"review note contains decision '{decision}'")
        else:
            fail(f"review note file not found: {review_full_path}")
    else:
        fail("no primary_review_path set")

    return merged


def test_final_decision(state: dict):
    """Test: final_decision_node moves the task to the correct folder."""
    print("\n── test_final_decision ──")
    from orchestrator.nodes.final_decision import final_decision_node

    task_filename = state.get("current_task_filename", "")

    # Set the primary review decision explicitly
    test_state = {**state, "primary_review_decision": "passes_first_pass"}

    updates = final_decision_node(test_state)
    merged = {**test_state, **updates}

    decision = merged.get("final_decision", "")
    if decision == "complete":
        ok(f"final_decision = {decision} (expected for low-tier pass)")
    else:
        fail(f"unexpected final_decision: {decision} (expected 'complete' for low-tier pass)")

    # Verify the task moved to completed/
    completed_path = AHAMKARA_VAULT / "queue-tasks" / "completed" / task_filename
    review_path = AHAMKARA_VAULT / "queue-tasks" / "review-needed" / task_filename

    if completed_path.exists():
        ok("task file exists in completed/")
        content = completed_path.read_text()
        if "status: completed" in content:
            ok("task frontmatter updated to 'completed'")
    else:
        fail("task file not found in completed/")

    if review_path.exists():
        fail("stale task copy remains in review-needed/")
    else:
        ok("no stale task copy in review-needed/")

    # Verify queue invariant: task exists in exactly one folder
    found_folders = []
    for folder in ["open", "claimed", "review-needed", "completed", "blocked"]:
        if (AHAMKARA_VAULT / "queue-tasks" / folder / task_filename).exists():
            found_folders.append(folder)

    if len(found_folders) == 1 and found_folders[0] == "completed":
        ok("queue invariant: task in exactly one folder (completed)")
    else:
        fail(f"queue invariant violation: task in {found_folders}")

    return merged


def test_queue_invariants():
    """Test: queue-state-invariants hold after the full pipeline."""
    print("\n── test_queue_invariants ──")
    from orchestrator.repair import scan_vault_for_drift

    # Scan should not return our test task in duplicate
    conditions = scan_vault_for_drift(AHAMKARA_VAULT)
    our_conditions = [c for c in conditions if TEST_TASK_ID in c.task_filename]

    if not our_conditions:
        ok("no drift detected for test task")
    else:
        for c in our_conditions:
            fail(f"drift detected: {c.condition_type} - {c.description}")


def test_revision_escalation():
    """Test: revision escalation promotes tier at revision >= 2."""
    print("\n── test_revision_escalation ──")
    from orchestrator.nodes.classify_risk import classify_risk_node

    base_state = make_initial_state()

    # Revision 0 → should stay low for a simple task
    state0 = {**base_state, "revision_count": 0}
    result0 = classify_risk_node(state0)
    if result0.get("escalation_tier") == "low":
        ok("revision 0 stays low")
    else:
        fail(f"revision 0 escalation_tier = {result0.get('escalation_tier')}")

    # Revision 2 → hard override to high (from revision-escalation policy)
    state2 = {**base_state, "revision_count": 2}
    result2 = classify_risk_node(state2)
    if result2.get("escalation_tier") == "high" and result2.get("risk_level") == "high":
        ok("revision 2 forced to high/high")
    else:
        fail(f"revision 2: risk={result2.get('risk_level')}, tier={result2.get('escalation_tier')}")

    # Revision 3 → also high/high
    state3 = {**base_state, "revision_count": 3}
    result3 = classify_risk_node(state3)
    if result3.get("escalation_tier") == "high" and result3.get("risk_level") == "high":
        ok("revision 3 forced to high/high")
    else:
        fail(f"revision 3: risk={result3.get('risk_level')}, tier={result3.get('escalation_tier')}")


def test_model_policy_enforcement():
    """Test: model_policy correctly allows and denies model invocations."""
    print("\n── test_model_policy ──")
    from orchestrator.model_policy import (
        validate_role_access,
        validate_role_requirements,
        validate_model_invocation,
        ModelPolicyError,
        preflight_check,
    )

    policy = TEST_MODEL_POLICY
    pid = "test-project"

    # ── Allowed access ────────────────────────────────────────────────
    try:
        validate_role_access("worker", "worker_model", policy=policy, project_id=pid)
        ok("worker role with worker_model is allowed")
    except ModelPolicyError as e:
        fail(f"worker should be allowed: {e}")

    try:
        validate_role_access("primary_reviewer", "primary_reviewer_model", policy=policy, project_id=pid)
        ok("primary_reviewer role with primary_reviewer_model is allowed")
    except ModelPolicyError as e:
        fail(f"primary_reviewer should be allowed: {e}")

    # ── Denied: wrong model_ref for role ──────────────────────────────
    try:
        validate_role_access("worker", "primary_reviewer_model", policy=policy, project_id=pid)
        fail("worker with primary_reviewer_model should be denied")
    except ModelPolicyError:
        ok("worker with wrong model_ref correctly denied")

    # ── Denied: role not in policy ────────────────────────────────────
    try:
        validate_role_access("nonexistent_role", "worker_model", policy=policy, project_id=pid)
        fail("nonexistent_role should be denied")
    except ModelPolicyError:
        ok("nonexistent_role correctly denied")

    # ── Denied: no policy at all ─────────────────────────────────────
    try:
        validate_role_access("worker", "worker_model", policy={}, project_id=pid)
        fail("empty policy should deny")
    except ModelPolicyError:
        ok("empty policy correctly denies all")

    # ── Runtime requirements: secondary_reviewer requires escalation_tier=high ──
    validate_role_requirements("secondary_reviewer", {"escalation_tier": "high"}, policy=policy)
    ok("secondary_reviewer with escalation_tier=high passes runtime check")

    try:
        validate_role_requirements("secondary_reviewer", {"escalation_tier": "low"}, policy=policy)
        fail("secondary_reviewer with escalation_tier=low should be denied")
    except ModelPolicyError:
        ok("secondary_reviewer with wrong escalation_tier correctly denied")

    # ── Runtime requirements: bookkeeping_reviewer requires docs/bookkeeping ──
    validate_role_requirements("bookkeeping_reviewer", {"task_type": "docs"}, policy=policy)
    ok("bookkeeping_reviewer with task_type=docs passes runtime check")

    try:
        validate_role_requirements("bookkeeping_reviewer", {"task_type": "implementation"}, policy=policy)
        fail("bookkeeping_reviewer with task_type=implementation should be denied")
    except ModelPolicyError:
        ok("bookkeeping_reviewer with wrong task_type correctly denied")

    # ── Full validation ───────────────────────────────────────────────
    validate_model_invocation(
        "secondary_reviewer",
        "secondary_reviewer_model",
        policy=policy,
        project_id=pid,
        runtime_context={"escalation_tier": "high"},
    )
    ok("full validation passes for valid invocation")

    # ── Preflight check ───────────────────────────────────────────────
    warnings = preflight_check(policy)
    if not warnings:
        ok("preflight check returns no warnings for valid policy")
    else:
        fail(f"preflight returned warnings: {warnings}")


def test_secondary_review_routing():
    """Test: secondary_review_node is only called for high escalation."""
    print("\n── test_secondary_review_routing ──")
    from orchestrator.transitions import after_primary_review

    # Low escalation + passes → final_decision (no secondary)
    state_low = {
        "primary_review_decision": "passes_first_pass",
        "escalation_tier": "low",
    }
    route = after_primary_review(state_low)
    if route == "final_decision":
        ok("low-escalation pass routes to final_decision (no secondary)")
    else:
        fail(f"low pass routed to: {route}")

    # High escalation + passes → secondary_review (per-task)
    state_high = {
        "primary_review_decision": "passes_first_pass",
        "escalation_tier": "high",
    }
    route2 = after_primary_review(state_high)
    if route2 == "secondary_review":
        ok("high-escalation pass routes to secondary_review")
    else:
        fail(f"high pass routed to: {route2}")

    # High escalation + passes + batch_tasks → batch_secondary_review
    state_batch = {
        "primary_review_decision": "passes_first_pass",
        "escalation_tier": "high",
        "batch_tasks": [{"task_filename": "TASK-test.md"}],
    }
    route3 = after_primary_review(state_batch)
    if route3 == "batch_secondary_review":
        ok("high pass with batch_tasks routes to batch_secondary_review")
    else:
        fail(f"batch pass routed to: {route3}")

    # Any escalation + revise → queue_task
    state_revise = {
        "primary_review_decision": "revise",
        "escalation_tier": "low",
    }
    route4 = after_primary_review(state_revise)
    if route4 == "queue_task":
        ok("revise routes back to queue_task")
    else:
        fail(f"revise routed to: {route4}")


def test_planner_escalation():
    """Test: escalate_to_planner_node produces re-scoped task."""
    print("\n── test_planner_escalation ──")
    from orchestrator.nodes.escalate_to_planner import escalate_to_planner_node

    state = make_initial_state()
    state["revision_count"] = 3
    state["current_task_filename"] = "TASK-20260101-1200-failing-task.md"

    updates = escalate_to_planner_node(state)
    merged = {**state, **updates}

    # Check revision_count reset
    if merged.get("revision_count") == 0:
        ok("revision_count reset to 0 after escalation")
    else:
        fail(f"revision_count not reset: {merged.get('revision_count')}")

    # Check user_request contains re-scope marker
    new_request = merged.get("user_request", "")
    if "[RE-SCOPED after 3 revisions]" in new_request:
        ok("user_request contains re-scope marker")
    else:
        fail(f"user_request missing re-scope marker: {new_request[:80]}...")

    # Check decision_rationale set
    if merged.get("decision_rationale"):
        ok(f"decision_rationale set: {merged['decision_rationale'][:60]}...")
    else:
        fail("decision_rationale not set")

    # Check the re-scoped request is different from original
    original = state.get("user_request", "")
    if new_request != original:
        ok("re-scoped request differs from original")
    else:
        fail("re-scoped request identical to original")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    global PASSED, FAILED
    PASSED = 0
    FAILED = 0

    print("=" * 60)
    print("E2E Pipeline Test — Ahamkara Project")
    print(f"Test task ID: {TEST_TASK_ID}")
    print("=" * 60)

    # ── Activate test model policy (baked into state, no global) ─────
    # Policy is passed via state["model_policy"] in make_initial_state().
    # No global set_project_policy call needed.

    # Pre-clean: remove any stale test artifacts from previous crashed runs
    for folder in ["open", "claimed", "review-needed", "completed", "blocked"]:
        queue_dir = AHAMKARA_VAULT / "queue-tasks" / folder
        if queue_dir.exists():
            for f in queue_dir.glob("TASK-TEST-E2E-*"):
                f.unlink()
                log(f"Pre-cleaned stale file: {f}")

    try:
        # Phase 1: Classification
        state = test_classify_request()
        state = test_classify_risk(state)
        test_chat_task_bridge()

        # Phase 2: Queue and claim
        state = test_queue_task(state)
        test_plan_kickoff_queue_task()
        state = test_await_worker_claim(state)

        # Phase 3: Worker execution
        state = test_worker_execution(state)

        # Phase 4: Review
        state = test_primary_review(state)

        # Phase 5: Final decision
        state = test_final_decision(state)

        # Phase 6: Invariants, routing logic, and policy enforcement
        test_queue_invariants()
        test_revision_escalation()
        test_model_policy_enforcement()
        test_secondary_review_routing()
        test_planner_escalation()

    except Exception as exc:
        print(f"\n  ERROR  Unhandled exception: {exc}")
        import traceback
        traceback.print_exc()
        FAILED += 1

    finally:
        print("\n── Cleanup ──")
        cleanup()

    print("\n" + "=" * 60)
    print(f"Results: {PASSED} passed, {FAILED} failed")
    print("=" * 60)

    return FAILED == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
