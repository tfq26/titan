# Vault-Graph Conflict Resolution Policy

Status: Active

This policy defines what happens when the LangGraph in-memory state disagrees
with the project-local vault filesystem state.

## Core Rule

**Project-local vault artifacts are authoritative for active engineering state.**

LangGraph state is a coordination cache — a transient working copy that tracks
paths, decisions, and routing metadata. The vault files on disk are the durable
source of truth for:

- queue state (which folder a task lives in)
- task frontmatter (status, revision, report link, review link)
- worker report existence and content
- primary review existence and content
- secondary review existence and content

## Project-Local vs Shared-Vault Authority

This workbench has two vault layers. Their authority scopes are different:

| Layer | Authoritative For | NOT Authoritative For |
|---|---|---|
| **Project-local vault** (`docs/vault/`) | Active queue state, task frontmatter, worker reports, review notes, feature briefs, system maps, validation commands, project-specific standing instructions | Reusable templates, cross-project policies, model routing config |
| **Shared vault** (`workbench-vault/`) | Canonical templates, workflow policies, escalation rules, model routing config, portable feature patterns, evaluation configs | Any project's active queue state, task files, reports, or reviews |

**Rule**: If a shared-vault policy and project-local operational state appear
to conflict, task execution MUST follow the project-local vault state. The
conflict must be surfaced as a repair condition. The shared vault is
authoritative for templates, policies, and patterns only — not for active
execution state.

This means:
- A task file in a project's `queue-tasks/open/` is the truth about that task's
  state, regardless of what the shared vault's policy documents claim.
- If a project's local validation commands differ from the shared template's
  suggestions, the project-local commands win.
- If a project overrides a model routing entry in `project-config.yaml`, that
  override wins over the shared `routing.yaml`.

## Conflict Resolution Order

When graph state and vault state disagree:

1. **Stop the transition.** Do not proceed with a state mutation while the
   conflict is unresolved.

2. **Re-read vault files.** The graph must re-derive its internal state from the
   vault filesystem:
   - Task path: verified by checking which queue folder contains the task file
   - Report path: verified by reading task frontmatter `report:` field
   - Review path: verified by reading task frontmatter `review:` field
   - Revision count: verified by reading task frontmatter `revision:` field
   - Queue state: verified by `find` across all queue folders

3. **If vault is internally consistent, update graph state to match.** The
   vault wins. The graph adopts the vault's version of truth.

4. **If vault itself is inconsistent (drift detected), raise a repair
   condition.** The orchestrator must not attempt to auto-resolve vault drift.
   It must:
   - Log the specific inconsistency with file paths
   - Block further transitions on the affected task
   - Emit a repair condition that a human or repair tool must address
   - Optionally move the task to `blocked/` with a drift note

## Specific Conflict Scenarios

### Queue state conflict

Graph says task is in `review-needed/`, but filesystem shows it in `open/`.

- Resolution: vault wins. Update `current_task_path` to match vault.
- Check: is the graph chasing a stale path? Log this so the operator can
  investigate whether a previous transition was incomplete.

### Report path conflict

Graph has `worker_report_path` set, but the task frontmatter shows no report
link or a different path.

- Resolution: vault wins. Update graph's `worker_report_path` to match.
- Additional check: does the reported path actually point to an existing file?
  If not, the task may be in an invalid state (report linked but missing).

### Revision count conflict

Graph has `revision_count: 2`, but task frontmatter says `revision: 1`.

- Resolution: vault wins. Update `revision_count` to match.
- Log: was a transition interrupted? The graph may have incremented its count
  without completing the vault write. The lower vault number is correct.

### Duplicate task locations

Task file exists in both `open/` and `review-needed/` simultaneously.

- This is vault drift (violation of queue-state invariants).
- Raise repair condition immediately.
- Do not guess which copy is correct.
- Block the task and ask for human repair.

## Pre-Transition Validation Hook

Before every state-mutating node runs, validate the graph state against the
vault for the task it is about to touch:

```
validate_graph_vs_vault(task_filename) → (ok, conflicts[])
```

If conflicts exist, the node must abort and return the conflict list.

This hook is implemented in `orchestrator/repair.py`.

## Post-Transition Verification

After every state-mutating node runs, verify that the vault correctly reflects
the intended change:

```
verify_vault_transition(task_filename, expected_folder, expected_frontmatter) → (ok, errors[])
```

If verification fails, attempt rollback. If rollback fails, log the error and
block the task.

## Related

- `policies/queue-state-invariants.md` — invariant definitions
- `orchestrator/repair.py` — validation and repair hooks
