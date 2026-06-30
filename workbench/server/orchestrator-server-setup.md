# Orchestrator Server Setup

Status: Draft

This note describes the simplest server-side setup for the repo-local
orchestrator loop.

## Goal

Run one always-on process on the server that watches the Ahamkara queue,
keeps the queue moving with Temporal, and leaves the actual worker/reviewer
execution behind a generic backend hook.

## What This Setup Uses

- repo-local queue files under `docs/vault/queue-tasks/`
- repo-local reports under `docs/reports/subagents/`
- a small Python orchestrator loop in `orchestrator/`
- Temporal for the durable watch loop
- a Dockerfile for packaging the server as a container
- a Docker Compose file for Temporal itself
- optional worker/reviewer backend commands supplied by the environment

## Why This Is The Simplest Option

- no separate web service is required
- no database is required
- no GitHub webhook is required for the first pass
- Git stays the source of truth
- Temporal handles the durable queue loop

## Required Machine Setup

On the server, install:

- `git`
- `python3`
- `temporalio`
- `docker`

If you want to provide worker/reviewer backend commands through the shell,
make sure the shared secrets file exists at:

```sh
/home/taufe/.workbench-secrets.env
```

Then source it before starting the orchestrator:

```sh
source /home/taufe/.workbench-secrets.env
```

## Recommended Startup Flow

1. Clone the repo on the server.
2. Check out the branch you want the agents to work on.
3. Install the project dependencies needed by the Temporal worker backend and the repo.
4. Start the orchestrator in watch mode.

Example:

```sh
cd /home/taufe/tools/agentOrchestrator
source /home/taufe/.workbench-secrets.env
export TEMPORAL_WORKER_COMMAND="your-worker-command"
export TEMPORAL_REVIEWER_COMMAND="your-reviewer-command"
python3 -m orchestrator.run --watch
```

## How The Loop Works

1. The orchestrator scans `docs/vault/queue-tasks/open/`.
2. It claims one task and sends it to the worker backend command.
3. The worker backend implements the task, writes the report, and moves the
   task to `review-needed/` or `blocked/`.
4. The orchestrator sees `review-needed/` and sends it to the reviewer backend
   command.
5. The reviewer accepts the task, sends it back to `open/`, or blocks it.

## Backend Hooks

The orchestrator is the listener. Temporal does not execute task work by
itself. Instead, the server loop watches the queue and launches whatever
worker/reviewer backend command you configure.

Set `TEMPORAL_WORKER_COMMAND` and `TEMPORAL_REVIEWER_COMMAND` before launch.
Those commands receive the prompt on stdin and the task context in the
`AHAMKARA_PROMPT`, `AHAMKARA_REPO_ROOT`, and `AHAMKARA_FILES` environment
variables.

For a fast test setup, use:

```sh
export TEMPORAL_WORKER_COMMAND="/home/taufe/tools/agentOrchestrator/bin/worker.sh"
export TEMPORAL_REVIEWER_COMMAND="/home/taufe/tools/agentOrchestrator/bin/reviewer.sh"
export TITAN_MODEL_COMMAND="/home/taufe/tools/agentOrchestrator/bin/demo-model.py"
```

## Temporal Only

There is no LangGraph, LangSmith, or OpenCode dependency in this server
package. Temporal owns the durable orchestration loop, and the backend command
is the only swap point.

## Systemd Setup

The server folder includes:

- [Dockerfile](./Dockerfile)
- [docker-compose.temporal.yml](./docker-compose.temporal.yml)
- [bin/run-agent.sh](./bin/run-agent.sh)
- [bin/worker.sh](./bin/worker.sh)
- [bin/reviewer.sh](./bin/reviewer.sh)
- [bin/demo-model.py](./bin/demo-model.py)
- [start-temporal.sh](./start-temporal.sh)
- [start-titan.sh](./start-titan.sh)
- [start-titan-docker.sh](./start-titan-docker.sh)
- [setup-titan.sh](./setup-titan.sh)
- [titan.service](./titan.service)

Run the setup script first:

```sh
cd /home/taufe/tools/agentOrchestrator
./setup-titan.sh
```

Then install and enable the service with:

```sh
sudo cp /home/taufe/tools/agentOrchestrator/titan.service /etc/systemd/system/titan.service
sudo systemctl daemon-reload
sudo systemctl enable --now titan
```

Check status with:

```sh
sudo systemctl status titan
sudo journalctl -u titan -f
```

The Docker wrapper will source the shared secrets file, pass the env vars into
the container, ensure Temporal is up with `docker compose`, and then start
`python3 -m orchestrator.run --watch` inside the image.

Temporal UI is optional and is published on `http://localhost:8081` when
started with:

```sh
docker compose -f /home/taufe/tools/agentOrchestrator/docker-compose.temporal.yml --profile ui up -d temporal-ui
```

## Next Step

Point `TEMPORAL_WORKER_COMMAND` and `TEMPORAL_REVIEWER_COMMAND` at the backend
commands you want Temporal to run, and set `TITAN_MODEL_COMMAND` to the actual
model runtime you want the wrappers to execute.
