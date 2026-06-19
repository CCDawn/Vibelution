"""Append-only JSONL store for the Agent Kernel MVP."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


KERNEL_STORE_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class KernelJsonlStore:
    """Small append-only JSONL store plus a materialized index snapshot."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()

    def path_for(self, stream: str) -> Path:
        return self.root / f"{stream}.jsonl"

    @property
    def index_path(self) -> Path:
        return self.root / "index.json"

    def append(self, stream: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = deepcopy(payload)
        path = self.path_for(stream)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def read_stream(self, stream: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        path = self.path_for(stream)
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        if limit is None:
            return rows
        try:
            bounded = max(1, int(limit))
        except (TypeError, ValueError):
            bounded = 1
        return rows[-bounded:]

    def load_index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return _default_index()
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _default_index()
        if not isinstance(payload, dict):
            return _default_index()
        index = _default_index()
        index.update(payload)
        return index

    def save_index(self, payload: dict[str, Any]) -> dict[str, Any]:
        index = deepcopy(payload)
        index["version"] = KERNEL_STORE_VERSION
        index["updatedAt"] = utc_now_iso()
        index.setdefault("eventsById", {})
        index.setdefault("tasksById", {})
        index.setdefault("taskIdsByIdempotencyKey", {})
        index.setdefault("executionsById", {})
        index.setdefault("outcomesById", {})
        index.setdefault("proposalIdsByOutcomeId", {})
        index.setdefault("proposalsById", {})
        index.setdefault("recentEventIds", [])
        index.setdefault("recentTaskIds", [])
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=f".{self.index_path.name}.", dir=str(self.index_path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(index, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temp_path, self.index_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        return index


def _default_index() -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "version": KERNEL_STORE_VERSION,
        "updatedAt": now,
        "eventsById": {},
        "tasksById": {},
        "taskIdsByIdempotencyKey": {},
        "executionsById": {},
        "outcomesById": {},
        "proposalIdsByOutcomeId": {},
        "proposalsById": {},
        "recentEventIds": [],
        "recentTaskIds": [],
    }
