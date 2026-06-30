# Review Escalation Policy

Status: Active

Use this policy to decide whether a queued task needs only primary review or a
two-tier primary-plus-secondary review.

## Role Model

The system uses exactly five roles. Do not invent new ones.

- **Classifier**: Intake classification only. Determines task_type, risk_level,
  and escalation_tier from the user request. Does NOT review worker output.
  Does NOT plan implementation. Ultra-cheap model, runs on every request.
- **Worker**: Implements one queued task slice. Stays within scope. Writes
  a completion report. Cheap coding model.
- **Primary Reviewer**: Post-worker judgment and final queue-state decision.
  Checks scope, catches obvious flaws, validates evidence. Decides low-tier
  completion. Escalates high-tier tasks to secondary review. Owns the final
  queue-state transition. Runs on every completed task.
- **Secondary Reviewer**: High-risk deep review only. Activated when
  escalation_tier == high AND primary review passes. Checks for subtle
  lifecycle, threading, ownership, and architecture issues. Provides a
  recommendation to the primary reviewer — does NOT own the final decision.
- **Escalation Fallback**: Revision >= 3 replanning only. Activated when
  cheaper loops have failed three times. Re-scopes or rewrites the task.
  Does NOT participate in routine classification or review.
- **Human**: Product owner, risk arbiter, architecture tiebreaker.

These are distinct roles. The classifier does not review. The primary
reviewer does not plan. The escalation fallback does not classify.
Routine work (classifier + worker + primary reviewer) uses cost-effective
models. The secondary reviewer and escalation fallback use a stronger model
reserved for escalation only — it takes a back seat.

## Escalation Tiers

- `low` — primary reviewer signoff is enough
- `high` — primary reviewer does the first pass; if it clears obvious flaws, a
  stronger secondary reviewer inspects the change before final completion

## Lean Review Heuristic

Use the lean-implementation policy as a default review lens:

- flag avoidable abstraction
- flag wrapper code around stdlib or platform behavior
- flag dependency additions that are not clearly justified
- flag broad refactors when a smaller change would satisfy the queue task

Use `revise` when complexity increased without helping the acceptance bar.

## Low Escalation

Use `low` for:

- docs and reporting tasks
- queue hygiene and bookkeeping
- small scoped refactors with low behavioral risk
- obvious bug fixes with narrow blast radius
- simple config or naming cleanup

## High Escalation

Use `high` for:

- frame lifecycle and shutdown behavior
- render/present ordering
- threading and ownership changes
- input routing and pause/menu state
- shared engine/runtime abstractions
- tasks likely to hide subtle regressions even if they compile

## Reviewer Roles

- `primary reviewer`:
  lower-cost default judgment layer (`primary-reviewer`).
  Checks scope, obvious flaws, validation evidence, and whether the task
  is ready for deeper review. Owns the final queue-state transition.
  Runs on every completed task.
- `secondary reviewer`:
  escalation-only (Codex in production). Checks the diff or report after
  primary review passes it forward for high-tier tasks. Provides
  recommendation; does not own the final decision. NOT invoked for
  routine work.
- `bookkeeping reviewer` (optional):
  ultra-cheap (`gemini-bookkeeping`); handles docs and bookkeeping
  when configured. When not configured, primary reviewer handles these.

## Two-Tier Flow

For `high` escalation tasks:

1. Worker completes task and writes report.
2. Primary reviewer reviews first.
3. If obvious flaws exist, send back `revise` without escalation.
4. If the change looks sound, write a secondary-review handoff note.
5. Secondary reviewer reviews the diff/report.
6. Primary reviewer records the final decision after reading secondary feedback.

## Batch Secondary Review

For several related `high` escalation tasks, the primary reviewer may prepare a
single batch handoff using `secondary-review-batch.md`. Batch review is opt-in
only. The default is per-task secondary review.

## Related

- `policies/revision-escalation-policy.md` — revision-count escalation rules
- `policies/queue-state-invariants.md` — queue consistency rules
- `policies/vault-graph-conflict-resolution.md` — authority rules
- `model-routing/routing.yaml` — current model assignments per role
