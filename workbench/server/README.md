# Workbench Server — Autonomous Agent Execution

This directory contains everything needed to deploy the Workbench orchestrator
on a server where agents run autonomously in isolated git worktrees.

## Architecture

The server runs three coordinated processes:

1. **Queue watcher** — polls `queue-tasks/{open,claimed,review-needed,completed,blocked}/`
   for state transitions and dispatches events to the worktree executor and
   GitHub Issues sync.

2. **Worktree executor** — when a task appears in `open/`, the executor:
   - Claims the task (moves to `claimed/`)
   - Creates an isolated git worktree (`git worktree add`)
   - Runs an LLM-powered agent to implement the task inside the worktree
   - Commits changes, pushes the branch to origin
   - Opens a draft PR
   - Moves the task to `review-needed/`

3. **GitHub Issues sync** — mirrors the file-based queue state to GitHub Issues:
   - `open/` → issue with `task` label
   - `claimed/` → `in-progress` label
   - `review-needed/` → `needs-review` label + PR link comment
   - `completed/` → issue closed
   - `blocked/` → `blocked` label

## Prerequisites

On the server, install:

- `git` (with SSH deploy key or HTTPS token configured for the target repo)
- `gh` CLI (authenticated: `gh auth login`)
- `python3` (3.11+)
- `docker` (optional, for containerized deployment)

## Setup

### 1. Clone the repo

```sh
git clone git@github.com:taufeeqali/workbench-vault.git /home/taufe/tools/agentOrchestrator
cd /home/taufe/tools/agentOrchestrator
```

### 2. Create environment

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure secrets

Create a `.workbench-secrets.env` file:

```sh
export GOOGLE_API_KEY="your-google-api-key"
export GITHUB_TOKEN="your-github-token-with-repo-and-issues-scope"
export PRIMARY_REVIEWER_BASE_URL="https://your-endpoint-here"
export PRIMARY_REVIEWER_API_KEY="your-key-here"
export OPENAI_API_KEY="your-openai-key-here"
```

Source it before running:

```sh
set -a && source .workbench-secrets.env
```

### 4. Fix project paths

The `projects/registry.yaml` contains local machine paths. On the server,
override them with symlinks or environment-specific config. Example:

```sh
# Create a server-registry.yaml that overrides paths
cp projects/registry.yaml projects/server-registry.yaml
# Edit server-registry.yaml to fix paths
export WORKBENCH_REGISTRY=projects/server-registry.yaml
```

## Running

### Start the worker daemon

```sh
./server/run-worker.sh --project ahamkara
```

This runs a loop that:
- Watches the queue
- Executes tasks in git worktrees
- Syncs with GitHub Issues
- Reports progress

### Run as a systemd service

```sh
sudo cp server/titan.service /etc/systemd/system/titan.service
sudo systemctl daemon-reload
sudo systemctl enable --now titan
```

Check status:

```sh
sudo systemctl status titan
sudo journalctl -u titan -f
```

## Git Worktree Layout

Worktrees are created in `.worktrees/` next to the repo root:

```
/home/taufe/tools/
├── agentOrchestrator/     ← main repo checkout
└── .worktrees/
    └── w-TASK-20260628-0110/   ← per-task worktree
```

Branch naming: `feature/{task-id}`

When a task's PR merges, clean up with:

```sh
git worktree remove ../.worktrees/w-{task-id}
git branch -d feature/{task-id}
```

## Files

| File | Purpose |
|------|---------|
| `run-worker.sh` | Main worker loop — watcher + executor + GitHub sync |
| `titan.service` | Systemd unit for running as a daemon |
| `Dockerfile` | Container packaging (optional) |
| `bin/` | Helper scripts (demo model, worker/reviewer wrappers) |
| `orchestrator/` | (Archived) Legacy Temporal-based server code |

## Migration from Temporal

The previous server setup used Temporal for durable orchestration. The new
approach replaces Temporal with a simpler watcher + worktree executor pattern.
Temporal-specific files remain in `server/orchestrator/` for reference but
are no longer the active deployment path.
