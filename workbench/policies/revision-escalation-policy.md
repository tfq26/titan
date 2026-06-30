# Revision Escalation Policy

Status: Active

Use this policy to prevent cheap reviewers or workers from looping indefinitely.

## Revision Count Rules

- revision `0` → normal worker retry allowed
- revision `1` → normal worker retry allowed with a concrete review note
- revision `2` → escalate review or planning strength
- revision `3+` → stronger planner should take over, re-scope, or rewrite the
  task

## Escalation Suggestions

- `low` escalation tasks:
  after 2 failed reviews, promote to `high`
- `high` escalation tasks:
  after 2 failed reviews, require secondary review if not already used
- after 3 failed reviews:
  route to stronger planner/supervisor and rewrite the task

## Rule

Every review that sends a task back to `open/` must increment `revision`.

## LangGraph Integration

The LangGraph state tracks `revision_count`. On each `revise` transition:

1. `revision_count` is incremented.
2. At revision 2, `escalation_tier` auto-promotes from `low` to `high`.
3. At revision 3+, the graph routes to the planner node instead of looping back
   to the worker.
4. The task file frontmatter is updated with `revision: N` to keep the vault
   consistent.

## Related

- `policies/review-escalation-policy.md` — escalation tier definitions
- `model-routing/routing.yaml` — which models handle which roles
