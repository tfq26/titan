# Cross-Project Multi-Agent Engineering Workbench

Status: Active

## What This Is

A production-style multi-agent software engineering workbench that helps humans
collaborate with AI agents across multiple projects using a disciplined,
repo-native workflow.

## Architecture

```
Shared Vault (this repo)
├── orchestrator/     → LangGraph orchestration graph + CLI entrypoint
├── model-routing/    → role-to-model configuration (production policy)
├── policies/         → canonical workflow policies (9 files)
├── templates/        → canonical note templates (10 files)
├── patterns/         → cross-project reusable knowledge
├── evaluation/       → LangSmith eval configs + datasets
└── tools/            → MCP-compatible tool definitions

Project-Local Vaults (per project)
└── docs/vault/
    ├── features/     → project-specific feature briefs
    ├── systems/      → project-specific system maps
    ├── memory/       → project-specific state, decisions, traps
    ├── queue-tasks/  → active task queue (open/claimed/.../blocked)
    └── ...
```

## Workflow

```
receive_request → classify → queue → worker → primary_review
    → [secondary_review] → final_decision → complete/revise/blocked
```

Plan-oriented requests can be tagged as `plan_kickoff`, which keeps the same
queue/review flow but adds kickoff-specific instructions for the first slice
and role handoffs.

Chat turns can also surface a concrete next slice as a `Task:` block; when the
response includes one, the workbench promotes it into `queue-tasks/open/` so
conversation can turn into executable work without manual copy/paste.
When a chat response needs multiple slices, it can emit a `Plan:` block with
multiple `Task:` sections. The workbench stores that as a plan manifest, queues
the first slice, and advances the remaining slices one at a time as each slice
finishes.

## Design Principles

1. **Repo-first state, platform-second orchestration.** The repo vault is the
   primary human-readable working memory layer. LangGraph references vault
   artifacts, it does not hide them.
2. **Explicit workflow over free-form debate.** Agents follow a defined loop with
   end conditions.
3. **Human is product owner, not micro-manager.** Ask for meaningful decisions
   only.
4. **Separate execution from judgment.** One worker owns implementation. Review
   is a separate pass.
5. Cross-project reuse focuses on patterns, not blind copy-paste.
6. **Canonical machine state should outlive rendered Markdown.** Markdown stays
   valuable as a human view, but structured records should become the source of
   truth for task, report, review, decision, and event coordination.

## Role Model

Five roles — no more. Each has a single responsibility.

| Role | Responsibility | Activation | Nickname |
|---|---|---|---|
| Classifier | Intake classification only: task_type, risk_level, escalation_tier | Every request | `classifier` |
| Worker | Implements one queued task slice, writes report | Every task | `worker` |
| Primary Reviewer | Post-worker judgment, final queue-state decision | Every completed task | `primary-reviewer` |
| Secondary Reviewer | High-risk deep review: lifecycle, threading, architecture | escalation_tier == high | `secondary-reviewer` |
| Escalation Fallback | Revision >= 3 replanning: re-scope or rewrite task | revision_count >= 3 | `secondary-reviewer` |

The classifier does not review. The primary reviewer does not plan.
The escalation fallback does not classify. Roles are distinct — do not
conflate them, even if two share the same model instance.

Roles are stable. Endpoint implementations are replaceable.
Vendor names are configuration detail, not workflow identity.
Nicknames are the human-facing identity in logs, traces, and review notes.
model_id is backend config only.

## Model Authorization

Credentials are machine-level (env vars). Model authorization is project-level.

Each project's `project-config.yaml` defines a `model_policy` that controls
which models the project can use. Before any LLM invocation, the orchestrator
validates:

1. The role is in `allowed_roles` for the project.
2. The resolved `model_ref` is in the allowed list for that role.
3. The `model_ref` is not in `denied_model_refs`.
4. Runtime `role_requirements` (escalation_tier, task_type) are satisfied.

Enforcement lives in `orchestrator/model_policy.py`. Failures raise a
`ModelPolicyError`, which is caught by the LLM fallback path — the graph
does not crash, it returns the safe fallback decision instead.

## Getting Started

### For Agents

1. Read `AGENTS.md`.
2. Read `policies/review-escalation-policy.md` and `policies/queue-state-invariants.md`.
3. Read `policies/lean-implementation-policy.md` for the YAGNI-first ladder.
4. Read `policies/plan-kickoff-policy.md` when starting from an existing plan.
5. Read `policies/workbench-repair-playbook.md` when repairing drift or queue errors.
6. Check `model-routing/routing.yaml` for current model assignments.
7. Look up `projects/registry.yaml` for managed projects.

### For Humans

1. Add projects to `projects/registry.yaml`.
2. Configure model routing in `model-routing/routing.yaml`.
3. Run the orchestrator:
   ```
   python -m orchestrator.run -p ahamkara -r "Your request here"
   ```
4. Configure a private server connection from the app's `Server` tab.
   The connection file is stored locally at `~/.workbench-console/server-config.json`
   and the auth token is stored in the OS keychain. Neither is written into the vault.
   The tab can test the health endpoint, send a small sync probe, and upload a
   vault snapshot backup to the configured snapshots endpoint. The local vault
   remains authoritative; the server is a backup mirror, not the primary source
   of truth.
5. Use the `Chat` tab's `New Chat` button to archive the current thread and start
   a fresh one for the selected project. The `Resume` tab lists archived chats
   across all projects.
6. Scan for queue drift:
   ```
   python -m orchestrator.run -p ahamkara --scan-drift
   ```
7. Resume a session:
   ```
   python -m orchestrator.run -p ahamkara -s <session_id> --resume
   ```

## Key Files

| File | Purpose |
|---|---|
| `projects/registry.yaml` | All managed projects |
| `model-routing/routing.yaml` | Role-to-model mapping (production config) |
| `orchestrator/run.py` | CLI entrypoint |
| `orchestrator/graph.py` | LangGraph state graph |
| `orchestrator/state.py` | State shape (TypedDict) |
| `orchestrator/persistence.py` | SQLite checkpointer (default) |
| `orchestrator/repair.py` | Drift detection and repair hooks |
| `orchestrator/transitions.py` | Conditional edge logic |
| `orchestrator/model_policy.py` | Project-level model authorization enforcement |
| `orchestrator/watcher.py` | Filesystem polling watcher for queue state transitions |
| `orchestrator/plan_kickoff.py` | Shared kickoff-intent heuristics and prompt fragments |
| `orchestrator/plan_sequences.py` | Shared plan-manifest helpers, multi-slice task parsing, and queued slice metadata |
| `orchestrator/nodes/batch_secondary_review.py` | Opt-in batch secondary review for grouped tasks |
| `orchestrator/tracing.py` | LangSmith trace spans (zero-overhead when disabled) |
| `orchestrator/tests/test_e2e_pipeline.py` | End-to-end pipeline test (50 tests) |
| `policies/lean-implementation-policy.md` | YAGNI-first / lean implementation policy |
| `policies/plan-kickoff-policy.md` | Plan kickoff posture for plan-oriented requests |
| `policies/workbench-repair-playbook.md` | Self-heal playbook for common workbench errors |
| `templates/lean-implementation-checklist.md` | Compact worker/reviewer prompt artifact |
| `templates/workbench-repair-note.md` | Compact repair note template |
| `policies/*.md` | Workflow policies (9 files) |
| `templates/*.md` | Canonical note templates (10 files) |
| `patterns/INDEX.md` | Cross-project pattern index |

## Implementation Status

| Phase | Status | What's Done | What's Stubbed | What's Remaining |
|---|---|---|---|---|
| **0: Vault extraction** | Done | Shared vault created; all templates, policies, registry, and model routing extracted from Ahamkara. Project-local vs shared boundary defined. | — | — |
| **1: Graph skeleton** | Implemented | Full 11-node StateGraph, all conditional edges, state TypedDict, persistence layer (SQLite), repair/drift detection, CLI entrypoint, LLM-backed classify, review, and planner-escalation nodes, node-level LangSmith tracing, filesystem polling watcher, invocation-scoped project model policy enforcement, E2E test harness (50 tests). | — | Real LangGraph interrupt() in await_human_approval. |
| **2: Review + escalation** | Implemented | Review routing (primary → secondary → final), revision escalation (0→1→2→3+), queue invariant enforcement, verify decision for secondary concerns, atomic vault moves, drift detection. | — | Automatic pre-flight drift scan on graph init. |
| **3: Checkpoints + observability** | Scaffolded | Checkpoint definitions exist; `interrupt()` implemented in await_human_approval (activates when LangGraph is installed); LangSmith trace spans wired into all 12 nodes and LLM calls; human-approval node wired in graph. | — | Create evaluation runs from datasets. |
| **4: Cross-project + triggers** | Partially implemented | Cross-project context policy; batch secondary review node + template (opt-in); filesystem polling watcher; model policy enforcement; pattern index; pre-flight drift scan on graph init; second project (Libra) registered; third project (Blitz) scaffolded. | — | Cross-project pattern lookup tooling; add vault structure to Libra. |
