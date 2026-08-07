"""Durable indexes for idempotency and cross-run lookups (filesystem)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .atomic_fs import CorruptWorkflowStoreError, atomic_write_text


class DurableWorkflowIndex:
    """Persists idempotency keys outside process memory."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._path = self.root / "idempotency.json"
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CorruptWorkflowStoreError(
                self._path, "corrupt idempotency index JSON", cause=exc
            ) from exc
        except OSError as exc:
            raise CorruptWorkflowStoreError(
                self._path, "unreadable idempotency index", cause=exc
            ) from exc
        if not isinstance(data, dict):
            raise CorruptWorkflowStoreError(self._path, "idempotency index must be a JSON object")
        return data

    def _save(self, data: dict[str, Any]) -> None:
        atomic_write_text(self._path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    def get_run_id(self, key: str) -> str | None:
        if not key:
            return None
        with self._lock:
            value = self._load().get(key)
            return str(value) if value else None

    def put_run_id(self, key: str, run_id: str) -> None:
        if not key:
            return
        with self._lock:
            data = self._load()
            data[key] = run_id
            self._save(data)
