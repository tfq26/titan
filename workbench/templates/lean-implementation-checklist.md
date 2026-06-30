---
type: lean-implementation-checklist
status: active
---

# Lean Implementation Checklist

Use this as a compact prompt artifact for workers and reviewers.

## YAGNI Ladder

1. Does this need to exist?
2. Can the existing codebase already do it?
3. Can the language standard library do it?
4. Can the platform or framework do it?
5. Can an already-installed dependency do it?
6. Can this be solved with less code?
7. Only then write the minimum new code that works.

## Worker Questions

- Did I choose the smallest correct solution?
- Did I reuse existing code or existing platform behavior where possible?
- Did I avoid introducing a new abstraction for one call site?
- Did I avoid new dependencies unless they were clearly justified?
- Did I stay inside the queued task scope?
- Did I preserve validation, safety, and required error handling?

## Reviewer Questions

- Is this more complex than the acceptance bar requires?
- Is there a wrapper or abstraction that adds no clear value?
- Did the change introduce a dependency that was not necessary?
- Would a smaller targeted edit satisfy the task?
- Did the worker explain why a simpler path was chosen?

## Exceptions

Lean implementation does not excuse skipping:

- validation
- required tests
- security checks
- data safety
- necessary error handling
- required architecture work
