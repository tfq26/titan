---
type: queued-task
status: open
created:
queued_by:
assigned_to:
priority: normal
escalation_tier: low
revision: 0
workflow_intent: task
primary_reviewer:
secondary_reviewer:
subsystems: []
related_feature:
report:
review:
---

# TASK-YYYYMMDD-HHMM-short-name

## Goal

Describe the implementation outcome in one or two sentences.

## Background

Summarize the discussion and link relevant docs or feature briefs.

When the task is handed to a model, the model should speak with its nickname as the visible identity and treat the role as its workflow job title.

## Plan Kickoff

Include this section when `workflow_intent` is `plan_kickoff`.

Start from the existing plan or current-state note, choose the smallest first slice, and hand off only when another role is actually needed.

## First Read

- [Vault README]({{vault_root}}/README.md)
- [Project repo map]({{vault_root}}/01-repo-map.md)
- [Current state]({{vault_root}}/memory/current-state.md)

## Scope

In bounds:

- Item.

Out of bounds:

- Item.

## Likely Files

- `path/to/file`

## Implementation Plan

1. Step.
2. Step.
3. Step.

## Lean Check

- Start with the smallest correct solution.
- Reuse existing code, stdlib, or framework behavior before adding custom code.
- Add dependencies only if the task clearly needs them.
- Avoid abstractions or refactors that do not improve the acceptance bar.

## Acceptance Bar

- Requirement.
- Requirement.

## Review Tier

- `low` — primary reviewer signoff only
- `high` — primary reviewer plus secondary reviewer before final completion

## Validation

Run when relevant:

```sh
# Project-specific validation commands — see project-config.yaml
```

If validation is skipped or fails, explain why in the report.

## Reporting Required

When done or blocked:

1. Write a report using `templates/worker-report.md`.
2. Append the project's subagent master log.
3. Update this task frontmatter `status` and `report:` field.
4. Move this task to `review-needed/` or `blocked/`.
