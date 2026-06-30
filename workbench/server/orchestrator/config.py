from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OrchestratorConfig:
    repo_root: Path
    poll_interval: float
    temporal_address: str
    temporal_namespace: str
    temporal_task_queue: str
    temporal_workflow_id: str
    worker_command: str | None = None
    reviewer_command: str | None = None
