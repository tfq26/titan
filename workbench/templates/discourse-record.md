---
type: discourse-record
status: consensus | incomplete | aborted
created: {{datetime}}
thread_id: {{thread_id}}
participants: [{{participants}}]
total_turns: {{turns}}
consensus_reached: true | false
ready_to_queue: true | false
project_id: {{project_id}}
---

# Discourse Record

## Request

{{original_request}}

## Participants

{{participant_names}}

## Status

- Turns: {{turns}}
- Consensus: {{consensus_status}}
- Ready to queue: {{queue_status}}

## Summary

<!-- Briefly describe what the discussion concluded -->

## Agreements

- <!-- What the agents agreed on -->

## Disagreements / Risks

- <!-- Where opinions diverged or risks were identified -->

## Task Breakdown

### Task 1

- Title: <!-- Short title -->
- Type: <!-- implementation | docs | refactor | investigation -->
- Goal: <!-- One-sentence queueable goal -->
- Acceptance:
  - <!-- Concrete check -->
  - <!-- Concrete check -->
- Scope:
  - <!-- In-bounds detail -->
  - <!-- Another in-bounds detail -->

### Task 2 (if applicable)

- ...

## Key Decisions

- <!-- Decision 1 -->
- <!-- Decision 2 -->

## Notes for Implementation

- <!-- Anything the worker should know before starting -->
