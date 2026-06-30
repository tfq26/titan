from __future__ import annotations

from .queue_actions import process_review_once, process_worker_once
from .task_state import QueuePaths


def dispatch_once(config, paths: QueuePaths) -> bool:
    did_work = process_review_once(config, paths)
    if did_work:
        return True
    return process_worker_once(config, paths)
