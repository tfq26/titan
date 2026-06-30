from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from .config import OrchestratorConfig
from .queue_dispatch import dispatch_once
from .task_state import QueuePaths, ensure_queue_dirs

try:  # pragma: no cover - optional dependency during packaging
    from temporalio import activity  # type: ignore
    from temporalio import workflow  # type: ignore
except Exception:  # pragma: no cover - fallback if dependency is missing
    activity = None
    workflow = None


@dataclass(frozen=True)
class TemporalRuntimeConfig:
    address: str
    namespace: str
    task_queue: str
    workflow_id: str


def temporal_config_from_env(repo_name: str) -> TemporalRuntimeConfig:
    import os

    return TemporalRuntimeConfig(
        address=os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
        task_queue=os.environ.get("TEMPORAL_TASK_QUEUE", "titan-orchestrator"),
        workflow_id=os.environ.get("TEMPORAL_WORKFLOW_ID", f"titan-queue-{repo_name}"),
    )


def _load_temporal_runtime():
    try:
        from temporalio import client, exceptions, workflow  # type: ignore
        from temporalio.worker import Worker  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("temporalio is not installed") from exc
    return client, exceptions, workflow, Worker


if activity is not None:
    @activity.defn
    def dispatch_once_activity(
        payload: dict[str, object],
    ) -> bool:
        config = _build_activity_config(payload)
        paths = QueuePaths(config.repo_root)
        ensure_queue_dirs(paths)
        return dispatch_once(config, paths)
else:  # pragma: no cover - package import fallback
    def dispatch_once_activity(
        payload: dict[str, object],
    ) -> bool:
        return False


def _build_activity_config(
    payload: dict[str, object],
) -> OrchestratorConfig:
    repo_root = str(payload["repo_root"])
    repo_path = Path(repo_root)
    temporal_runtime = temporal_config_from_env(repo_path.name)
    worker_command = payload.get("worker_command")
    reviewer_command = payload.get("reviewer_command")
    return OrchestratorConfig(
        repo_root=repo_path,
        poll_interval=float(payload["poll_interval"]),
        temporal_address=temporal_runtime.address,
        temporal_namespace=temporal_runtime.namespace,
        temporal_task_queue=temporal_runtime.task_queue,
        temporal_workflow_id=temporal_runtime.workflow_id,
        worker_command=str(worker_command) if worker_command is not None else None,
        reviewer_command=str(reviewer_command) if reviewer_command is not None else None,
    )


if workflow is not None:
    @workflow.defn
    class QueueLoopWorkflow:
        @workflow.run
        async def run(
            self,
            payload: dict[str, object],
        ) -> None:
            poll_interval = float(payload["poll_interval"])
            while True:
                did_work = await workflow.execute_activity(
                    dispatch_once_activity,
                    payload,
                    start_to_close_timeout=timedelta(minutes=30),
                )
                if not did_work:
                    await workflow.sleep(poll_interval)
else:  # pragma: no cover - package import fallback
    class QueueLoopWorkflow:  # type: ignore[no-redef]
        pass


async def run_temporal_watch(config: OrchestratorConfig) -> int:
    client, exceptions, workflow_mod, Worker = _load_temporal_runtime()
    temporal_config = TemporalRuntimeConfig(
        address=config.temporal_address,
        namespace=config.temporal_namespace,
        task_queue=config.temporal_task_queue,
        workflow_id=config.temporal_workflow_id,
    )

    temporal_client = await client.Client.connect(
        temporal_config.address,
        namespace=temporal_config.namespace,
    )

    try:
        await temporal_client.start_workflow(
            QueueLoopWorkflow.run,
            {
                "repo_root": str(config.repo_root),
                "poll_interval": config.poll_interval,
                "worker_command": config.worker_command,
                "reviewer_command": config.reviewer_command,
            },
            id=temporal_config.workflow_id,
            task_queue=temporal_config.task_queue,
        )
    except exceptions.WorkflowAlreadyStartedError:
        pass

    with ThreadPoolExecutor(max_workers=4) as activity_executor:
        worker = Worker(
            temporal_client,
            task_queue=temporal_config.task_queue,
            workflows=[QueueLoopWorkflow],
            activities=[dispatch_once_activity],
            activity_executor=activity_executor,
        )
        await worker.run()
    return 0
