---
type: portable-feature
source_project: workbench-vault
feature: plan sequence manifest
reusable_level: shared
date_added: 2026-06-20
---

# Plan Sequence Manifest

## Problem

Plan-oriented conversations often need more than one executable slice. If the
workbench only promotes the first slice, the rest of the plan gets lost in chat
prose or needs manual re-entry later.

## Pattern

Let the assistant emit a compact `Plan:` block with multiple `Task:` sections.
The workbench should:

- write a durable plan manifest in the project vault
- queue the first slice immediately
- keep the remaining slices in the manifest
- advance to the next slice automatically after completion

## Invariants

- Markdown remains the human view, not the canonical plan state.
- The plan manifest is repo-native and file-backed.
- Only the next executable slice is queued at a time.
- A completed slice may trigger the next slice, but never rewrites the whole plan.

## Common Failure Modes

- Treating a multi-slice plan like a one-off task and losing later steps.
- Queueing every slice at once so the plan can run out of order.
- Hiding plan metadata only in chat prose so the queue cannot continue.
- Letting a rendered summary become the source of truth instead of the manifest.

## Validation Checklist

- A `Plan:` block with multiple `Task:` sections creates a manifest file.
- The first slice is written to `queue-tasks/open/`.
- The task frontmatter records the plan manifest and slice index.
- Completing the current slice allows the next slice to be queued automatically.

## Project-Specific Assumptions

- The project already has repo-native queue folders.
- Chat responses can be parsed before they are rendered in the UI.
- The orchestrator owns queue-state transitions and can read the manifest later.

## Reusable Parts

- Manifest-backed plan storage.
- Preallocated task filenames for ordered slices.
- Slice metadata carried in task frontmatter.
- Automatic advancement after completion.

## Do Not Blindly Copy

- The exact plan manifest path.
- The number of slices a project should allow.
- Any project-specific review or escalation rules.
