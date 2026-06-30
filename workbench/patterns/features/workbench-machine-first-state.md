---
type: portable-feature
source_project: workbench-vault
feature: machine-first workbench state
reusable_level: shared
date_added: 2026-06-17
---

# Workbench Machine-First State

## Problem

Markdown queue files are excellent for humans, but they are too expensive to
carry as the canonical coordination format for every task, report, review,
decision, and workflow event.

The workbench needs a repo-native machine record layer that is:

- structured enough for deterministic tooling
- small enough for role-specific context packs
- durable enough for cross-project reuse
- still visible in the repo for humans and agents

## Reusable Parts

- Canonical machine records for tasks, reports, reviews, decisions, event logs,
  and snapshots.
- Role-specific context packs derived from the canonical records.
- Rendered Markdown views generated from machine state rather than edited as the
  source of truth.
- Explicit invariants and failure classes that let the orchestrator detect
  drift without reading broad narrative notes.
- Event-log plus snapshot architecture for replayable history with compact
  current state.

## Recommended Directory Shape

Project-local vault:

```text
docs/vault/
  queue-tasks/
    open/
    claimed/
    review-needed/
    completed/
    blocked/
  machine/
    tasks/
    reports/
    reviews/
    decisions/
    event-log/
    snapshots/
    context-packs/
  views/
    tasks/
    reports/
    reviews/
    decisions/
```

Suggested shared-vault support:

```text
workbench-vault/
  patterns/features/workbench-machine-first-state.md
  policies/structured-state-invariants.md
  policies/failure-classes.md
  templates/rendered-views/
```

## Canonical Machine Formats

### Task

Use a structured YAML record with stable fields:

```yaml
schema: workbench.task.v1
task_id: TASK-20260617-1200-foo
project_id: ahamkara
status: open
revision: 0
task_type: implementation
risk_level: low
escalation_tier: low
summary: Short objective
scope:
  in_bounds: []
  out_of_bounds: []
acceptance:
  - requirement
links:
  report: null
  reviews: []
  decision: null
```

### Report

Use YAML for the report body and structured metadata:

```yaml
schema: workbench.report.v1
report_id: REPORT-...
task_id: TASK-...
worker_role: worker
worker_model: worker
files_changed: []
validation:
  commands: []
  passed: true
summary: Short implementation summary
gaps: []
```

### Review

Use YAML with role-specific result fields:

```yaml
schema: workbench.review.v1
review_id: REVIEW-...
task_id: TASK-...
review_role: primary
reviewer_model: primary-reviewer
decision: revise
findings: Short evidence-backed notes
risks: []
secondary_handoff: null
```

### Decision

Use a small YAML decision record:

```yaml
schema: workbench.decision.v1
decision_id: DEC-...
task_id: TASK-...
outcome: complete
decided_by: primary-reviewer
reason: Why this was accepted or blocked
```

### Event Log

Use append-only JSONL for event history:

```json
{"schema":"workbench.event.v1","event_type":"task.created","task_id":"TASK-...","actor_role":"classifier","timestamp":"2026-06-17T17:00:00Z"}
```

Why JSONL here:

- append-only and easy to stream
- friendly to replay and audit
- compact enough for per-task history

## Snapshot Model

Use a compact YAML snapshot as the current truth for the active task slice.
Snapshots should be derived from the event log and machine records rather than
edited by hand.

Snapshot contents should include:

- current status
- current revision
- latest record pointers
- hashes or versions for key records
- current queue position
- active failure class, if any

## Role-Specific Context Packs

Each role should receive a short derived pack rather than the full vault.

Suggested packs:

- `classifier`: request, project context, policy constraints
- `worker`: task, snapshot, file targets, validation commands
- `primary-reviewer`: task, report, diff summary, review criteria
- `secondary-reviewer`: task, report, primary review, snapshot, risk cues
- `escalation-fallback`: revision history, failed decisions, compressed review history

Context packs should be:

- generated from the canonical records
- small by default
- role-specific
- hash-addressable so they can be traced in LangSmith

## Rendered Human Views

Rendered Markdown views should be produced from the machine records, not used as
the canonical source.

Recommended views:

- queue task summary view
- worker report summary view
- review summary view
- decision summary view
- task timeline view

Rules for rendered views:

- safe for humans to open directly in Obsidian
- stable enough for links and review comments
- regenerate on each state-changing write
- never hand-edit if the machine record is authoritative

## LangGraph State References

LangGraph state should keep pointers, not duplicate content.

Recommended references:

- `task_record_path`
- `task_snapshot_path`
- `task_event_log_path`
- `task_context_pack_paths`
- `rendered_view_paths`
- `worker_report_record_path`
- `primary_review_record_path`
- `secondary_review_record_path`
- `decision_record_path`

The graph should use these pointers to:

1. fetch the narrowest possible context for each role
2. write an event when state changes
3. regenerate the matching human view
4. keep the queue file compatible during migration

## Failure Classes

Use a bounded set of failure classes instead of ad hoc prose.

Recommended classes:

- `vault-drift`
- `record-schema-invalid`
- `snapshot-stale`
- `view-stale`
- `policy-denied`
- `model-denied`
- `human-approval-required`
- `external-blocked`
- `review-conflict`
- `queue-invariant-violation`

Each failure class should map to one of:

- retry
- revise
- block
- human approval

## Migration Strategy

1. Dual-write machine records and rendered Markdown views.
2. Make LangGraph read the machine record first, then fall back to the view.
3. Keep project-local queue files intact during the transition.
4. Replace broad Markdown prompts with role-specific context packs.
5. Move event history into append-only logs.
6. Keep the human review workflow on top of rendered views, not raw machine blobs.

## Implementation Phases

### Phase 1

- Add record schemas.
- Add pointer fields to graph state.
- Dual-write task, report, review, and decision records.

### Phase 2

- Add event logs and snapshots.
- Introduce role-specific context pack generation.
- Trim prompts to context packs.

### Phase 3

- Treat rendered views as generated artifacts.
- Add stronger invariants and failure-class routing.
- Reduce direct Markdown parsing to fallback-only behavior.

## Project-Specific vs Reusable

### Project-specific

- exact folder names
- project report root
- validation commands
- project policy allowlists

### Reusable

- record schemas
- event/snapshot model
- context-pack derivation
- rendered-view strategy
- failure-class taxonomy

## Known Trap

The easiest mistake is to dual-write a machine record and a Markdown view but
let the Markdown copy silently drift. The fix is to make the machine record the
writer-owned source of truth and regenerate the view deterministically every
time.
