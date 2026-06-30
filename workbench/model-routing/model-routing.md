# Model Routing

Status: Active

This note explains the role-to-model mapping strategy. The actual
configuration lives in `routing.yaml` — edit that file to change
assignments. That file is the single source of truth.

## Naming Principle

**Roles are stable. Endpoint implementations are replaceable.
Vendor names are configuration detail, not workflow identity.**

- Model registry keys are role-oriented (`worker_model`, `primary_reviewer_model`).
- Nicknames are role-oriented (`worker`, `primary-reviewer`).
- Env var names are role-oriented (`PRIMARY_REVIEWER_BASE_URL`).
- `model_id` is the only vendor-specific field — and it is backend config only.

This means you can swap the backend for the primary reviewer from one
OpenAI-compatible endpoint to another without renaming anything in the
workflow, docs, traces, or review notes.

## Configuration Schema

`routing.yaml` has three sections:

### models — Model Registry

A flat registry of model configurations. Keys are role-oriented.

| Field | Required | Description |
|---|---|---|
| `provider` | Yes | `anthropic`, `openai`, `openai_compatible`, or `google` |
| `model_id` | Yes | Backend model identifier (vendor-specific; may be `kimi-k2.7-code`, `gemini-2.5-flash`, etc.) |
| `nickname` | Yes | Primary human-facing identity used in logs, traces, review notes, and routing summaries. Role-oriented, not vendor-specific. |
| `api_key_env` | Yes | Environment variable that holds the API key |
| `base_url_env` | `openai_compatible` only | Environment variable for custom endpoint URL |
| `temperature` | No | 0.0–1.0 |
| `max_tokens` | No | Max output tokens |
| `description` | No | Human-readable description |

### roles — Role Assignments

Each workflow role references a model via `model_ref`.

| Field | Required | Description |
|---|---|---|
| `model_ref` | Yes | Key from the `models` registry |
| `description` | No | Human-readable description |

### cost_limits — Per-Role Cost Caps

Maximum USD cost per task invocation for each role.

## Resolution Path

```
role (e.g. "primary_reviewer")
  → model_ref (e.g. "primary_reviewer_model")
    → model config (nickname: "primary-reviewer", provider: "openai_compatible", ...)
      → LangChain chat model client
```

## Nickname Semantics

`nickname` is the **primary human-facing identity** for a role's model.
It appears in:
- Log output (every LLM call)
- LangSmith traces (model label)
- Review note frontmatter (`reviewer_model` field)
- Graph state fields (`worker_model`, `primary_reviewer_model`, etc.)
- CLI verbose output

In chat-facing prompts and rendered conversation, the nickname should be the
name the model uses for itself. The role stays as the job title and routing
contract.

`model_id` is backend execution config only — the raw string sent to the
provider API. It should not appear in human-facing output.

## Defined Roles

| Role | Nickname | Activation | Purpose |
|---|---|---|---|
| `worker` | `worker` | Every task | Executes queued implementation tasks |
| `primary_reviewer` | `primary-reviewer` | Every task | First-pass review, routine supervision, final queue-state decisions |
| `classifier` | `classifier` | Every task | Intake triage: task type and risk classification |
| `secondary_reviewer` | `secondary-reviewer` | High-escalation only | Deep review for high-risk tasks |
| `escalation_fallback` | `secondary-reviewer` | Revision >= 3 only | Re-scopes or rewrites tasks after repeated failure |
| `bookkeeping_reviewer` | `bookkeeping-reviewer` | Optional | Ultra-cheap review for docs and bookkeeping |

## Cost Strategy

- **Routine work is cheap.** Worker and primary reviewer use cost-effective
  models. Most tasks never touch the escalation model.
- **Stronger model gates on risk.** The secondary reviewer only activates when
  escalation_tier == high AND primary review passes. The escalation fallback
  only activates after 3+ failed revisions.
- **Escalation model takes a back seat.** It is reserved for escalation only:
  secondary review of high-risk tasks and revision-fallback replanning.
  It is NOT the default planner for routine work.

## Role Distinction

Five roles — each has exactly one primary responsibility. Do not blur them.

- **Classifier** (`classifier`): Intake classification only. Reads the
  user request and project context, returns task_type + risk_level +
  escalation_tier. Does NOT review worker output. Does NOT plan implementation.
- **Worker** (`worker`): Implements one queued task slice within scope.
  Writes a completion report. Does NOT make review or acceptance decisions.
- **Primary Reviewer** (`primary-reviewer`): Post-worker judgment. Checks
  scope, catches obvious flaws, validates evidence, decides low-tier completion,
  escalates high-tier tasks to secondary review. Owns the final queue-state
  transition. Does NOT re-plan tasks.
- **Secondary Reviewer** (`secondary-reviewer`): High-risk deep review only.
  Activated when escalation_tier == high AND primary review passes. Checks
  for lifecycle, threading, ownership, and architecture issues. Provides a
  recommendation — does NOT own the final decision.
- **Escalation Fallback** (`secondary-reviewer`): Revision >= 3 replanning only.
  Activated when cheaper loops have failed three times. Re-scopes or rewrites
  the task. Does NOT participate in routine classification or review.

The secondary reviewer and escalation fallback share a model but activate
at different triggers. The classifier and primary reviewer are separate roles
with different responsibilities — the classifier does not review, the primary
reviewer does not classify.

## OpenAI-Compatible Endpoints

Models with `provider: openai_compatible` use `ChatOpenAI` with a custom
`base_url` and `api_key`. Configure using role-oriented env var names:

```yaml
models:
  primary_reviewer_model:
    provider: openai_compatible
    base_url_env: PRIMARY_REVIEWER_BASE_URL   # env var for endpoint URL
    api_key_env: PRIMARY_REVIEWER_API_KEY      # env var for API key
    model_id: kimi-k2.7-code                  # current backend (replaceable)
    nickname: primary-reviewer                 # stable identity
```

Set the env vars before running:
```sh
export PRIMARY_REVIEWER_BASE_URL="https://api.moonshot.cn/v1"
export PRIMARY_REVIEWER_API_KEY="sk-..."
```

## Env Vars Required

| Env Var | Used By |
|---|---|
| `GOOGLE_API_KEY` | Worker, classifier, bookkeeping reviewer |
| `PRIMARY_REVIEWER_BASE_URL` | Primary reviewer (openai_compatible endpoint) |
| `PRIMARY_REVIEWER_API_KEY` | Primary reviewer |
| `OPENAI_API_KEY` | Secondary reviewer / escalation fallback |

## Escalation Guidance

- `low` escalation: worker → primary reviewer → complete
- `high` escalation: worker → primary reviewer → secondary reviewer → complete
- revision >= 3: escalate_to_planner → re-queued task

## Per-Project Overrides

If a project needs different model assignments, add a `model-routing` section
to its `project-config.yaml`. The orchestrator merges project overrides on top
of this base config.

## Related

- `routing.yaml` — canonical model assignments
- `policies/review-escalation-policy.md` — when to escalate
- `policies/revision-escalation-policy.md` — revision-count rules
- `policies/vault-graph-conflict-resolution.md` — authority rules
