"""
Hades REST API client for Workbench integration.

Workbench calls Hades as its code intelligence engine over HTTP.
Hades handles project exploration, file selection, code generation,
validation, and retry. Workbench handles worktree management, commits,
PR creation, and the review pipeline.

Usage:
    from .hades_client import HadesClient

    client = HadesClient("http://localhost:9876")
    result = client.execute_task("Add health check endpoint")
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import Optional

logger = logging.getLogger(__name__)


class HadesError(Exception):
    """Raised when the Hades API returns an error."""
    pass


class HadesClient:
    """Client for the Hades daemon REST API (/api/v1/)."""

    def __init__(self, base_url: str = "http://localhost:9876", timeout: int = 600):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ── Endpoints ───────────────────────────────────────────────────────

    def execute_task(self, task: str, worktree_path: Optional[str] = None) -> dict:
        """POST /api/v1/execute-task

        Run the full CoderAgent pipeline on a task.
        When worktree_path is set, Hades writes files into that directory.
        Returns the AgentResult dict with success, summary, actions_taken, mutations_applied.
        """
        body: dict = {"task": task}
        if worktree_path:
            body["worktree_path"] = worktree_path
        return self._post("/api/v1/execute-task", body)

    def ingest(self, project_root: str) -> dict:
        """POST /api/v1/ingest

        Ingest a project directory into the code graph.
        Returns file/node/edge counts.
        """
        return self._post("/api/v1/ingest", {"project_root": project_root})

    def query_nodes(
        self,
        node_type: Optional[str] = None,
        name: Optional[str] = None,
        language: Optional[str] = None,
        path: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> dict:
        """GET /api/v1/query/nodes

        Query the code graph with optional filters.
        Returns {"nodes": [...], "total": N}.
        """
        params = {}
        if node_type:
            params["node_type"] = node_type
        if name:
            params["name"] = name
        if language:
            params["language"] = language
        if path:
            params["path"] = path
        if limit is not None:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)

        qs = "&".join(f"{k}={urllib.request.quote(v)}" for k, v in params.items())
        url = f"/api/v1/query/nodes?{qs}" if qs else "/api/v1/query/nodes"
        return self._get(url)

    def get_children(self, node_id: str) -> dict:
        """GET /api/v1/query/nodes/{id}/children

        Get child nodes of a parent (e.g., functions/types within a file).
        Returns {"nodes": [...], "total": N}.
        """
        return self._get(f"/api/v1/query/nodes/{node_id}/children")

    # ── HTTP helpers ────────────────────────────────────────────────────

    def _post(self, path: str, body: dict) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._request(req)

    def _get(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, method="GET")
        return self._request(req)

    def _request(self, req: urllib.request.Request) -> dict:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(error_body)
                msg = detail.get("error", error_body)
            except (json.JSONDecodeError, AttributeError):
                msg = error_body
            raise HadesError(f"Hades API error {e.code} on {req.full_url}: {msg}") from e
        except urllib.error.URLError as e:
            raise HadesError(f"Hades API unreachable at {req.full_url}: {e.reason}") from e
        except Exception as e:
            raise HadesError(f"Hades request failed: {e}") from e
