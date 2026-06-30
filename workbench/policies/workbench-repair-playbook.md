# Workbench Repair Playbook

Status: Active

Use this playbook when the workbench reports drift, queue invariant failures,
missing links, policy denials, or other orchestration errors.

This is a practical self-heal guide for agents and operators. It does not
replace the invariant policies. It tells you how to repair the common failures
they detect.

## First Rule

Before changing anything, identify the authoritative source:

- project-local vault for active task state
- shared vault for reusable policies, templates, routing, and patterns
- orchestrator state only as a coordination cache

If the vault and the graph disagree, the vault wins.

## Repair Workflow

1. Read the error message carefully.
2. Classify the failure class.
3. Re-read the affected vault files.
4. Fix the smallest authoritative source of truth.
5. Re-run drift scan or the relevant workflow step.
6. Confirm the warning or error is gone.

## Common Failure Classes

### `missing_report`

Symptom:

- review note in `review-needed/` has no `report:` link
- drift scan warns that a task is missing a report link

Fix:

- find the worker report if it exists
- if the report exists, add its relative path to the task frontmatter
- if the report does not exist, reconstruct a minimal repair report only when
  necessary for vault consistency, and clearly mark it as reconstructed

Validate:

- the `report:` field is populated
- the report file exists at the linked path
- `scan-drift` no longer flags the task

### `duplicate_location`

Symptom:

- the same task file appears in more than one queue folder

Fix:

- determine which copy is authoritative from the most recent valid state
- keep the authoritative copy
- delete the stale duplicate
- never leave the task in two folders at once

Validate:

- task exists in exactly one queue folder
- queue-state invariant check passes

### `queue_state`

Symptom:

- graph thinks task is in one folder, vault shows another

Fix:

- re-read the queue folders
- update the graph state to match the vault
- if the vault is internally consistent, do not “fix” it by guessing

Validate:

- graph and vault agree
- the task file is in the expected folder

### `revision_mismatch`

Symptom:

- graph revision count differs from task frontmatter revision

Fix:

- trust the vault frontmatter
- update graph state from disk
- if the revision increment was interrupted, repair the file writes before
  continuing

### `policy_denied`

Symptom:

- model invocation is rejected by project policy

Fix:

- inspect the project `model_policy`
- confirm the requested role and model ref are allowed
- confirm required env vars exist
- if the policy is correct, route to human approval or block the task

### `queue_filename_collision`

Symptom:

- a fresh request collides with an existing task filename

Fix:

- allocate a new unique task filename
- keep the duplicate guard in place
- do not reuse the stale filename for a fresh request

Validate:

- the new task filename is unique across queue folders
- fresh requests queue successfully

### `server_connection_failed`

Symptom:

- the Server tab cannot reach the configured health endpoint
- the sync probe fails before posting an event
- the server profile is saved, but connection checks still return an error

Fix:

- confirm the base URL is correct and reachable from this machine
- confirm the health path and events path match the server's real routes
- confirm the auth header name and token format are correct
- if the server expects `Authorization`, make sure the token is either a raw
  token or already prefixed with `Bearer `
- if the server is local, make sure it is running before testing or syncing

Validate:

- `Test Connection` returns a 2xx status
- `Sync Now` returns a 2xx status for both health and events
- the error no longer appears in the Server panel

### `server_sync_rejected`

Symptom:

- health check succeeds, but the events endpoint rejects the probe
- the Server tab shows a 4xx or 5xx response for the sync step

Fix:

- inspect the server's event intake contract
- confirm the events endpoint accepts JSON POST requests
- confirm the server is not rejecting the payload shape
- if the server requires a different event envelope, update the sync payload
  on both sides together

Validate:

- the events endpoint accepts the probe payload
- the probe response becomes 2xx
- the Server panel shows a successful sync result

### `server_snapshot_failed`

Symptom:

- the Server tab cannot upload a vault snapshot backup
- the backup result returns a 4xx or 5xx status

Fix:

- confirm the snapshots endpoint accepts JSON POST requests
- confirm the payload size is reasonable for the server's limits
- if the server expects chunked uploads or a different archive format, adjust
  the backup contract on both sides together
- keep the local vault authoritative even if the backup upload fails

Validate:

- the snapshots endpoint accepts the backup payload
- the Server tab reports a successful snapshot upload

## Repair Commands

Useful commands:

```sh
python -m orchestrator.run -p ahamkara --scan-drift
python -m orchestrator.run -p ahamkara -r "test request"
python -m orchestrator.run -p ahamkara -s <session_id> --resume --human-response "proceed"
```

## When To Stop

Stop and ask for human help if:

- the authoritative copy cannot be identified
- a repair would destroy evidence
- a model policy change is required
- the task belongs to a different project
- the vault is internally inconsistent in a way you cannot safely unwind

## Related

- `policies/vault-graph-conflict-resolution.md`
- `policies/queue-state-invariants.md`
- `policies/review-escalation-policy.md`
- `orchestrator/repair.py`
