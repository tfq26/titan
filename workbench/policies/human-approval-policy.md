# Human Approval Policy

Status: Active

This policy defines when the workbench must pause and ask the human for a
decision rather than proceeding automatically.

## When To Ask

Ask the human for:

- product direction and scope choices
- architecture tradeoffs that affect maintainability
- introduction of new dependencies
- destructive actions (delete file, force-push, drop table, etc.)
- privacy, security, or compliance decisions
- cost decisions above configured thresholds
- final approval on tasks flagged `requires_human_signoff`

## When NOT To Ask

Do not ask the human for:

- which file to read
- whether to write tests
- whether to inspect the diff
- what a compiler error means
- whether to run linting
- which model to use for review

## Approval Checkpoints

The LangGraph orchestrator uses three pre-defined interrupt points:

1. **Before destructive tools** — triggered when the worker requests
   `apply_patch`, `delete_file`, `install_dependency`, `git_push`, or `deploy`.
2. **After classification** — triggered when the classifier is uncertain about
   task_type or risk_level (confidence below threshold).
3. **After secondary review** — triggered when the secondary reviewer flags a
   risk that needs product-owner judgment.

## Checkpoint Timeout

If the human does not respond within 24 hours:
- The task transitions to `blocked/`.
- A note is added to the task file with the pending question.
- The graph checkpoints and can be resumed when the human responds.

## Implementation

Checkpoints use LangGraph's `interrupt()` mechanism. The graph suspends
execution at the interrupt point and resumes when the human provides input
through the configured UI channel.

## Related

- `orchestrator/checkpoints.py` — checkpoint definitions
- `tools/approval-tools.yaml` — tools that require approval
