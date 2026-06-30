# Queue State Invariants

Status: Active

Use these invariants to keep the queue trustworthy across all projects.

## Core Rule

One task file must exist in exactly one state folder at a time:

- `open/`
- `claimed/`
- `review-needed/`
- `completed/`
- `blocked/`

No task should appear in multiple state folders at once.

## Required Transitions

- `open` → `claimed`
- `claimed` → `review-needed`
- `claimed` → `blocked`
- `review-needed` → `completed`
- `review-needed` → `open`
- `review-needed` → `blocked`
- `blocked` → `open`

## File Rules

- Preserve the same task filename across all states.
- Update task frontmatter `status` whenever the folder state changes.
- Keep one current `report:` link and one current `review:` link.
- Do not leave stale copies behind in previous folders.

## Atomic Move Rule

When moving a task between folders:
1. Write the updated file to the target folder.
2. Verify the target file exists with correct contents.
3. Delete the source file.
4. Verify the source file no longer exists.

If any step fails, roll back and log the error. Never leave a task in two
folders.

## LangGraph Integration

The orchestrator MUST validate these invariants before and after every queue
state transition:
- Pre-transition: the task exists in exactly one expected folder.
- Post-transition: the task exists in exactly one new folder and not in the old.
- If the invariant check fails, abort the transition and log the violation.

No queue transition is considered valid unless the corresponding vault file
move/update succeeds.

## Related

- `policies/review-escalation-policy.md` — when review escalates
- `policies/revision-escalation-policy.md` — revision-count rules
