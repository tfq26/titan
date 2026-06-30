# Pattern Index

Status: Active

Searchable index of cross-project reusable knowledge extracted from
project vaults into portable notes.

## How To Use

When facing a problem in your project:
1. Search this index for relevant patterns.
2. Read the linked portable-feature note.
3. Check the `project_specific` vs `reusable_parts` sections.
4. Adapt the pattern to your project — do not blindly copy.

## How To Add

When extracting a pattern from a project:
1. Use `templates/portable-feature.md`.
2. Write the note to `patterns/features/{source-project}-{feature-name}.md`.
3. Add an entry to this index.

## Portable Features

<!-- Add entries as patterns are extracted -->

| Pattern | Source Project | Feature | Reusable Level | Date Added |
|---|---|---|---|---|
| Workbench machine-first state | workbench-vault | Structured task/report/review records, snapshots, context packs, and rendered views | shared | 2026-06-17 |
| Native project folder picker | workbench-vault | Let operators choose a project folder through the desktop file picker instead of typing a repo path | shared | 2026-06-18 |
| Local server connection profile | workbench-vault | Persisted machine-local server URL, auth, health-check, sync-probe, and vault snapshot backup settings for private workbench sync | shared | 2026-06-18 |
| Cross-project chat archive index | workbench-vault | Archive each project chat thread locally and list previous chats across projects from a single resume view | shared | 2026-06-19 |
| Plan kickoff protocol | workbench-vault | Kickoff posture for plan-oriented requests: smallest first slice, eager worker, and explicit handoffs | shared | 2026-06-19 |
| Chat task bridge | workbench-vault | Let chat responses emit structured Task blocks that are auto-promoted into queue-tasks/open/ | shared | 2026-06-19 |
| Plan sequence manifest | workbench-vault | Emit multi-slice Plan blocks into a reusable manifest that auto-queues the first slice and advances the rest after completion | shared | 2026-06-20 |

## Known Traps

<!-- Cross-project traps that have bitten multiple projects -->

| Trap | Description | Source Projects | Date Added |
|---|---|---|---|
| Markdown view drift | A rendered Markdown copy can silently diverge from the canonical machine record unless regeneration is deterministic and writer-owned | workbench-vault | 2026-06-17 |

## Review Heuristics

<!-- Reusable review-check questions extracted from past reviews -->

| Heuristic | Description | Source | Date Added |
|---|---|---|---|
| (none yet) | | | |
