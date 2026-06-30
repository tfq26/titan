# Plan Kickoff Policy

Status: Active

Use this policy when the operator gives the workbench an existing plan,
feature brief, roadmap, or current-state note and expects the team to start
from that material.

## Principle

Plan kickoff is not a separate workflow. It is a kickoff posture layered on top
of the existing queue/review flow.

## When To Kick Off

Use `plan_kickoff` when the request:

- references an implementation plan or feature brief
- asks the team to work from a current-state note
- asks for autonomous execution from a plan
- needs multiple roles to align on the first slice or handoff

## Kickoff Behavior

- Treat the plan, feature brief, or current-state note as the source of truth.
- Start with the smallest executable slice.
- Let the worker speak first when there is concrete work to start.
- Let the primary reviewer follow when there is something concrete to inspect.
- Keep the secondary reviewer out unless the slice is high risk or explicitly
  pinged.
- Use one short kickoff summary plus `Handoff:` when another role is needed.
- Introduce each model once per thread only.
- Do not ask the human to manually sequence the team unless required context is
  missing.

## What This Does Not Change

- Do not skip validation, required tests, safety checks, or review.
- Do not widen scope into a full re-plan.
- Do not bypass queue-state invariants or human approval checkpoints.

## Implementation Notes

- The classifier may set `workflow_intent: plan_kickoff` for plan-oriented
  requests.
- Queued tasks may include a kickoff-specific section.
- Chat responses may treat the request as a kickoff and use `Handoff:`
  to ping the next role.

## Related

- `orchestrator/plan_kickoff.py`
- `templates/queued-task.md`
- `patterns/features/workbench-plan-kickoff-protocol.md`
