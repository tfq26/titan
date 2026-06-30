# System Capability Inventory

Everything listed here is something the **system should do autonomously**. If it's being done by a human or an AI assistant manually, that's a gap — the system should own it.

## Task Lifecycle

- **Task creation**: The system should create tasks via spec-to-project discourse, GitHub Issues sync, or discovery auto-queue. Manual task file writing is a gap.
- **Task claiming**: `worktree_executor._claim_task` — moves from `open/` → `claimed/` with timestamp.
- **Implementation**: `_generate_implementation` — LLM generates code in an isolated git worktree with validation retry loop (max 3 attempts).
- **AI code review**: `_run_ai_review()` — after validation passes, generates git diff and calls `primary_reviewer` role LLM for structured review (PASS/FAIL with issues). Failed reviews feed into the retry loop.
- **Validation**: `_run_validation` — runs build/test commands from project config after writing files, before committing.
- **Committing**: `_commit_and_push` — commits changes with proper message format (summary + attribution + task ID). Configures GITHUB_TOKEN for HTTPS auth.
- **PR creation**: `_open_draft_pr` — opens draft PR via `gh` CLI with task description as PR body.
- **Completion**: Moves task to `review-needed/` with branch/PR/SHA metadata in frontmatter.
- **Failure**: Moves to `blocked/` with error reason and cleans up worktree.

## Vault Documentation

- **Seed detection**: `WorktreeExecutor.needs_seeding()` — checks if vault lacks essential docs (repo map, features, systems).
- **Auto-queuing**: `ensure_vault_seeded()` — creates a discovery task in `open/` that tells the LLM to explore and write vault docs. Idempotent — won't create duplicates.
- **Discovery tasks**: Processed through the normal pipeline — LLM explores the project, writes `01-repo-map.md`, creates vault subdirectories, commits, and opens a PR.
- **Context loading**: `_load_vault_context()` — reads vault docs and passes them to the LLM on every task execution. The vault is the project's persistent memory.

## Daemon / Server

- **run_worker.py**: Long-running daemon that polls the queue, processes tasks, and syncs with GitHub Issues. Accepts `--project`, `--interval`, and `--max-workers` args.
- **Auto-seeding**: On startup, the worker checks if the vault needs seeding and auto-queues a discovery task before processing other tasks.
- **Crash recovery**: `recover_stale_tasks()` + `cleanup_orphaned_worktrees()` + `recover()` — scans `claimed/` for stale tasks (missing worktree or timed out) and moves them back to `open/`. Removes orphaned worktree directories. Runs on every worker startup.
- **Concurrency**: `--max-workers` flag (`-j`) controls parallel task processing via `ThreadPoolExecutor`. Defaults to 1 (serial). Handles task claim arbitration to prevent duplicate processing.
- **Health check**: `run_worker.py` writes `.worker-heartbeat` every 30s. `server/health.py` checks for heartbeat existence and freshness (exit 0=OK, 1=missing, 2=stale).
- **Task scheduling**: `orchestrator/scheduler.py` — `TaskScheduler` daemon thread reads `schedules:` from project config. Supports cron expressions (via croniter), `interval_hours`, and `interval_days`. Writes scheduled tasks to `open/` with `type: scheduled` and `escalation_tier: low`.
- **Cost tracking**: `orchestrator/cost_tracker.py` — `CostTracker` per task records token usage from each LLM call. Estimates USD cost using model pricing table. Enforces `cost_limits` from `routing.yaml` per role (raises `BudgetExceededError`). Logs cost summary on task completion.

## Model Routing

- **Role resolution**: `routing.yaml` maps roles (worker, reviewer, classifier) to model configs (provider, model_id, env vars).
- **Policy enforcement**: `model_policy.py` validates role access per project — allowed roles, allowed model refs, deny lists, escalation tier requirements.
- **Env validation**: `llm_client._validate_env_vars` — checks required API keys and base URLs before any LLM call.

## GitHub Integration

- **Issue sync**: `GitHubQueueSync` maps queue state transitions to GitHub Issue operations (create, label, comment, close).
- **Issue→Task creation**: `GitHubIssueSource` polls GitHub Issues with a configurable label filter. `create_tasks_from_issues()` converts issues to task files in `open/`. Deduplicates by issue number in frontmatter.
- **PR workflow**: Draft PRs are opened by the executor when GITHUB_TOKEN is configured. PR body includes task description and execution summary.
- **PR watcher**: `orchestrator/pr_watcher.py` — `PRWatcher` background daemon polls `review-needed/` tasks and checks PR state via `gh pr view`. On merged: moves to `completed/`, deletes remote branch, removes worktree. On closed unmerged: moves to `blocked/`.
- **Auto-merge low-risk PRs**: `PRWatcher._try_auto_merge()` — when PR is OPEN (not draft), task has low `escalation_tier` or `type` is docs/bookkeeping/scheduled/vault-discovery, and CI passes → enables auto-merge via `gh pr merge --squash --auto`.
- **Review-ready webhook**: When a task moves to `review-needed/`, a webhook POST is sent to the configured URL with task metadata, PR URL, and summary.
- **Blocked-task webhook**: When a task moves to `blocked/`, a webhook POST is sent. The task file also gets a `block_reason` field in frontmatter and a `<!-- BLOCKED: ... -->` marker in the body.
- **Commit attribution**: Every commit includes `Co-Authored-By: Oz <oz-agent@warp.dev>`.

## CI/CD

- **GitHub Actions**: `.github/workflows/ci.yml` runs Python lint, TypeScript build check, and Rust check on every push.

## What The System Should NOT Do

- **Manual repo maps**: Creating vault documentation by hand. The discovery task should do this.
- **Manual task files**: Writing task markdown files directly. Tasks come from discourse, GitHub Issues, or auto-detection.
- **Manual testing**: Running the executor via one-off Python scripts to verify it works. The CI pipeline or worker daemon handles this.
- **Manual cleanup**: Removing stale worktrees, branches, or queue artifacts. Recovery logic on startup handles this.
- **Manual cost tracking**: Monitoring LLM spend per task manually. The CostTracker logs and enforces budgets automatically.
- **Manual PR review queue management**: Moving merged/closed PRs between queue states. The PRWatcher handles this.
