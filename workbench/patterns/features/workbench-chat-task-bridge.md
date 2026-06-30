---
type: portable-feature
source_project: workbench-vault
feature: chat task bridge
reusable_level: shared
date_added: 2026-06-19
---

# Chat Task Bridge

## Problem

Chat threads often reach a concrete next slice before the operator is ready to
manually create a task. If the workbench leaves that slice in prose, the queue
stays empty and the team loses the handoff.

## Pattern

Keep chat as a natural discussion surface, but let the assistant emit a
structured `Task:` block when the thread converges on executable work.

- The visible reply stays human-readable Markdown.
- The `Task:` block is parsed separately and promoted into `queue-tasks/open/`.
- The task file becomes the canonical queue item.
- The chat transcript can keep a compact "queued task" cue, but not the raw
  structured block.

## Invariants

- Chat does not become the canonical state store.
- The queue remains repo-native and file-backed.
- Automatic promotion only happens when the response includes a structured task
  proposal.
- The human still sees the queue item and can inspect or edit it like any other
  task.

## Common Failure Modes

- Leaving the task proposal buried in prose so no queue item is created.
- Rendering the raw structured block back into the visible transcript.
- Auto-creating tasks from casual chat that has not converged on a slice.
- Refreshing the queue too late, so the UI looks empty after the handoff.

## Validation Checklist

- A chat response with a `Task:` block creates a task file in `queue-tasks/open/`.
- The visible chat reply reads naturally without exposing the raw task block.
- The queue board refreshes soon after the chat turn completes.
- A response without a `Task:` block does not create a queue item.

## Project-Specific Assumptions

- The project already has queue folders and a chat relay path.
- Role routing supplies a stable nickname for the speaker.
- The operator wants task creation to emerge from conversation rather than a
  separate copy/paste step.

## Reusable Parts

- Structured `Task:` parsing from assistant output.
- Automatic promotion into the repo-native queue.
- Compact visible cues instead of raw machine blocks.
- Fast queue refresh after chat-to-task conversion.

## Do Not Blindly Copy

- The exact chat prompt wording.
- Project-specific queue filenames or paths.
- Any assumption that all chat should create tasks.
