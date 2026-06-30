---
type: review
status: draft
created:
reviewer_role: secondary
reviewer_model:
task:
report:
primary_review:
decision:
subsystems: []
---

# Secondary Review

## Task

Link the queued task being reviewed.

## Report

Link the worker report being reviewed.

## Primary Review

Link the primary review note that passed this on.

## Decision

One of:

- `confirm` — primary reviewer assessment is correct, proceed
- `concern` — primary reviewer assessment is mostly correct but has concerns
  noted below
- `revise` — the change needs revision before it can be accepted
- `blocked` — the change should be blocked for the reasons below

## Findings

What the secondary reviewer agrees with or disagrees with.

When you describe yourself in prose, use the model nickname as the visible identity and the role as the job title.

## Risk Check

Subtle behavioral, lifecycle, ownership, or architectural concerns.

## Lean Check

- Did the implementation add unnecessary complexity?
- Is there an avoidable abstraction, wrapper, or dependency?
- Could the queued task have been satisfied with a smaller change?
- Does any extra structure clearly improve safety, correctness, or maintainability?

## Recommendation Back To Primary

What the primary reviewer should do next.
