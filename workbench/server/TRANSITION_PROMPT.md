# Transition Prompt

You are now working in `/Users/taufeeqali/Projects/workbench-vault/server`.

Use this folder as the server-side orchestration home for the Ahamkara/workbench workflow.

Your responsibilities:
- read and update task files from the shared queue
- use `orchestrator/` as the Python entrypoint package
- run `python3 -m orchestrator.run --watch` from `/home/taufe/tools/agentOrchestrator`
- keep Temporal as the durable outer loop
- treat Docker as the packaging/runtime layer on the server
- use backend commands only if they are configured in the environment
- write task reports and queue updates on the server-side files only
- avoid local-only state; this is the shared server context

Working rules:
- keep the repo source-of-truth in git
- prefer server-side docs and reports over local copies
- if a backend command fails, requeue or fail safely instead of stranding tasks
- keep prompts short and task-specific

Useful startup context:
- the shared secrets file may live at `/home/taufe/.workbench-secrets.env`
- the container is started by `start-titan-docker.sh`
- the role wrappers live in `bin/`
- the orchestrator setup notes are in `orchestrator-server-setup.md`

When resuming work, first inspect:
1. the open queue
2. the claimed/review-needed queue
3. the latest subagent reports
4. the server setup note

Then continue the loop without waiting for extra prompting unless a human decision is required.
