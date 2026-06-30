# Workbench Vault — AGENTS.md

## Scope

This file applies to every file under `/Projects/workbench-vault/`.

## Purpose

This is the shared vault for the cross-project multi-agent engineering
workbench. It holds canonical templates, policies, orchestration code,
model routing config, and cross-project reusable patterns.

Project-specific memory, tasks, reports, and reviews live in each
project's local vault (e.g., `Ahamkara/docs/vault/`).

## Rules

- Keep notes in plain Markdown that works in GitHub, terminals, and Obsidian.
- Use Obsidian wiki links only for links between vault notes.
- Do not store secrets, credentials, private tokens, or machine-specific paths.
- Update `patterns/INDEX.md` when adding a new portable feature or known trap.
- Model routing changes must be made in `model-routing/routing.yaml`, not in
  the markdown policy file.
- Orchestrator code changes must keep the graph in `orchestrator/graph.py`
  consistent with the node implementations in `orchestrator/nodes/`.
- Test the graph end-to-end after any transition logic change.

## Agent Start Path

Before working with the workbench, read:

1. `README.md`
2. `model-routing/routing.yaml`
3. `policies/review-escalation-policy.md`
4. `policies/queue-state-invariants.md`
5. `policies/vault-graph-conflict-resolution.md`
6. `policies/human-approval-policy.md`
7. `policies/cross-project-context-policy.md`

## When Adding A Project

1. Add an entry to `projects/registry.yaml`.
2. Create `projects/{project_id}/project-config.yaml` with project-specific
   subsystems, validation commands, and vault paths.
3. Ensure the project has a `docs/vault/` structure with at minimum:
   - `README.md`
   - `00-start-here.md`
   - `01-repo-map.md`
   - `memory/current-state.md`
   - `queue-tasks/{open,claimed,review-needed,completed,blocked}/`
