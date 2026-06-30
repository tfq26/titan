# Lean Implementation Policy

Status: Active

Use this policy when planning, implementing, or reviewing queued work.
It is a YAGNI-first discipline for writing the smallest correct solution that
still satisfies the queued task, validation requirements, and safety checks.

## Core Principle

Prefer the least moving parts that fully satisfy the task.

This ladder is conceptually informed by Ponytail's "lazy, not negligent"
implementation style: minimize code and abstractions, but do not skip
correctness, validation, or safety.

The order of preference is:

1. Does this need to exist at all?
2. Can the existing codebase already do it?
3. Can the language standard library do it?
4. Can the platform or framework do it?
5. Can an already-installed dependency do it?
6. Can the solution be smaller or simpler?
7. Only then write the minimum new code that works.

This is lazy, not negligent:

- do not skip validation
- do not skip required tests
- do not skip security checks
- do not skip data-safety handling
- do not skip required error handling
- do not skip clearly required architecture work

## What To Prefer

- reuse existing functions, helpers, and patterns before adding abstractions
- use stdlib or built-in framework features before custom utilities
- avoid wrapper layers around a simple native API unless they add clear value
- avoid new dependencies unless the task materially benefits from them
- keep changes tightly scoped to the queued acceptance bar
- keep the implementation obvious enough that the next reviewer can read it fast

## What To Avoid

- premature abstraction
- generic helper layers for one call site
- wrapper code around stdlib or platform behavior with no added value
- broad refactors when a smaller targeted change satisfies the task
- new dependencies without a concrete payoff
- speculative hooks, flags, or indirection that are not needed yet

## Worker Behavior

Workers should:

- check for an existing no-code or smaller-code solution first
- prefer reuse over new abstraction
- prefer stdlib or platform features over custom code
- avoid adding dependencies unless the queued task clearly needs them
- stay tightly inside the task scope
- mention in the report when a simpler path was intentionally chosen

## Reviewer Behavior

Reviewers should flag:

- unnecessary abstraction
- avoidable wrapper code
- dependency additions that are not clearly justified
- broad refactors when the queued bar could be met with less change
- complexity that does not improve correctness, safety, or maintainability

Use `revise` when complexity increased without helping the acceptance bar.

## Decision Ladder

When a solution starts to grow, pause and ask:

1. What is the smallest correct change?
2. What existing code already solves this?
3. What built-in feature solves this?
4. What dependency already installed solves this?
5. What can be removed without hurting the acceptance bar?

If the answer is "nothing can be removed," keep going.
If the answer is "this is already solved elsewhere," reuse it.

## Related

- `templates/lean-implementation-checklist.md`
- `policies/review-escalation-policy.md`
- `policies/queue-state-invariants.md`
