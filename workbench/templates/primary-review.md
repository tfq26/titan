---
type: review
status: draft
created:
reviewer:
reviewer_role: primary
reviewer_model:
task:
report:
decision:
escalation_tier:
secondary_review:
subsystems: []
---

# Primary Review

## Task

Link the queued task being reviewed.

## Report

Link the worker report being reviewed.

## Decision

One of:

- `complete` — scope satisfied, evidence acceptable, no further action needed
- `verify` — implementation may be right, but proof is incomplete
- `revise` — change misses scope, quality, or evidence requirements
- `blocked` — progress depends on user input, access, or unresolved external
  state

## Escalation Tier

`low` or `high`

## Scope Check

Did the diff stay within the queued task scope?

## Evidence Checked

- `git status`
- `git diff`
- validation commands
- report contents
- relevant docs/tests

## Lean Check

- Was the solution smaller than necessary?
- Were existing code, stdlib, or platform features reused where possible?
- Were any new abstractions or dependencies actually justified?
- Would a narrower change satisfy the acceptance bar?

## Findings

Concrete issues, confirmations, or missing evidence.

When you describe yourself in prose, use the model nickname as the visible identity and the role as the job title.

## Validation Assessment

What was actually validated, and what still is not proven.

## Secondary Review Handoff (High Escalation Only)

If this is a `high` escalation task and the first pass succeeds, link the
secondary review note and note what should be examined.

## Risks

Anything that may still break or needs follow-up.

## Next Action

Exactly what should happen next:

- move to `completed/`
- move back to `open/` with revision note
- move to `blocked/`
- request secondary review
- request more verification
