---
type: portable-feature
source_project: workbench-vault
feature: plan kickoff protocol
reusable_level: shared
date_added: 2026-06-19
---

# Plan Kickoff Protocol

## Problem

Plan-oriented requests were being handled like generic chat or generic task
intake, which caused repeated introductions, too much narration, and weak role
handoffs.

## Pattern

Keep the existing queue/review flow, but add a kickoff posture:

- classify request intent as task vs plan kickoff
- treat the plan, feature brief, or current-state note as the source of truth
- start with the smallest executable slice
- have the eager role respond first, then hand off to the next needed role
- preserve one-time introductions and short Markdown replies
- keep raw output available only as fallback

## Invariants

- Plan kickoff does not create a new workflow.
- It does not replace queue/review, validation, or human approval.
- It does not ask the human to coordinate role order.
- It produces a concrete first slice, not a broad re-plan.

## Common Failure Modes

- Restating the entire plan instead of choosing the first slice.
- Reintroducing the same model on every turn.
- Skipping handoffs and making one role do everything.
- Treating kickoff as open-ended brainstorming.

## Validation Checklist

- A plan-oriented request triggers kickoff guidance.
- The first reply is short and concrete.
- The next needed model is pinged with `Handoff:`.
- The queued task carries kickoff-specific instructions when applicable.
- The thread does not repeat introductions after the first turn.

## Project-Specific Assumptions

- The workbench already has role routing and chat relay.
- The project vault already contains plan/current-state docs.
- The coordinator can derive kickoff intent without a separate planner service.

## Reusable Parts

- Kickoff-intent detection.
- One-time introduction discipline.
- Eager worker / less eager reviewer cascade.
- Handoff-based role pinging.

## Do Not Blindly Copy

- File paths, model nicknames, and role labels.
- The exact plan/current-state document names.
- Any project-specific escalation thresholds.
