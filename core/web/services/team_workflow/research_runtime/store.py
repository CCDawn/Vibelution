"""Filesystem store for workflow run metadata (not checkpoint internals)."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_run_store_dir() -> Path:
    override = os.environ.get("VIBELUTION_RESEARCH_WORKFLOW_RUN_STORE", "").strip()
    if override:
        return Path(override)
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")
    return home / "Documents" / "Vibelution" / "data" / "research_workflows" / "runs"


class WorkflowRunStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else default_run_store_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _run_path(self, run_id: str) -> Path:
        return self.root / f"{run_id}.json"

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            run_id = str(payload.get("runId") or f"run-{uuid.uuid4().hex[:12]}")
            record = {
                **payload,
                "runId": run_id,
                "createdAt": payload.get("createdAt") or _utc_now(),
                "updatedAt": _utc_now(),
            }
            path = self._run_path(run_id)
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return record

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        path = self._run_path(run_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def update_run(self, run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = self.get_run(run_id)
            if current is None:
                raise KeyError(run_id)
            next_record = {**current, **patch, "runId": run_id, "updatedAt": _utc_now()}
            self._run_path(run_id).write_text(
                json.dumps(next_record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return next_record

    def list_runs(self, workflow_id: str | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("run-*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if workflow_id and data.get("workflowId") != workflow_id:
                continue
            items.append(data)
        return items

    def append_event(self, run_id: str, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = self.get_run(run_id)
            if current is None:
                raise KeyError(run_id)
            events = list(current.get("events") or [])
            sequence = (events[-1]["sequence"] + 1) if events else 1
            envelope = {
                "eventId": f"evt-{uuid.uuid4().hex[:10]}",
                "sequence": sequence,
                "occurredAt": _utc_now(),
                **event,
            }
            events.append(envelope)
            # Bound event list
            if len(events) > 500:
                events = events[-500:]
            return self.update_run(run_id, {"events": events})

    def append_handoff(self, run_id: str, handoff: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = self.get_run(run_id)
            if current is None:
                raise KeyError(run_id)
            handoffs = list(current.get("handoffs") or [])
            handoffs.append(handoff)
            return self.update_run(run_id, {"handoffs": handoffs})

    def upsert_human_task(self, run_id: str, task: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = self.get_run(run_id)
            if current is None:
                raise KeyError(run_id)
            tasks = list(current.get("humanTasks") or [])
            task_id = str(task.get("taskId") or "")
            replaced = False
            for index, existing in enumerate(tasks):
                if str(existing.get("taskId") or "") == task_id:
                    tasks[index] = {**existing, **task}
                    replaced = True
                    break
            if not replaced:
                tasks.append(task)
            return self.update_run(run_id, {"humanTasks": tasks})

    def put_session_binding(self, run_id: str, node_id: str, binding: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = self.get_run(run_id)
            if current is None:
                raise KeyError(run_id)
            bindings = dict(current.get("sessionBindings") or {})
            bindings[node_id] = binding
            return self.update_run(run_id, {"sessionBindings": bindings})

    def get_session_binding(self, run_id: str, node_id: str) -> dict[str, Any] | None:
        current = self.get_run(run_id)
        if not current:
            return None
        bindings = current.get("sessionBindings") or {}
        value = bindings.get(node_id)
        return value if isinstance(value, dict) else None

    def find_human_task(self, run_id: str, task_id: str) -> dict[str, Any] | None:
        current = self.get_run(run_id)
        if not current:
            return None
        for task in current.get("humanTasks") or []:
            if str(task.get("taskId") or "") == task_id:
                return dict(task)
        return None
