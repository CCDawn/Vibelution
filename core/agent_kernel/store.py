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

# Process-wide index snapshot cache.  ``service._store()`` constructs a fresh
# KernelJsonlStore per call, so a per-instance cache would never hit; the
# cache is shared across instances and keyed by resolved index file path.
# Each entry pairs the file signature a snapshot was validated against
# ((st_mtime_ns, st_size)) with the parsed index dict itself.
_INDEX_CACHE: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
_INDEX_CACHE_LOCK = threading.Lock()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _index_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


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
        """Return the materialized index snapshot, cached by file signature.

        Cache contract (save-side takeover): on a signature hit the cached
        dict is returned shared, not copied.  Read paths must treat the
        returned snapshot as read-only and copy leaves before exposing them
        (all current kernel readers do: ``dict(...)`` / ``list(...)`` at the
        boundary).  The kernel runtime loop is the only in-place mutator, it
        runs under its own lock, and it refreshes the cache through
        save_index, so the shared snapshot keeps tracking the persisted
        file.  Callers that mutate the snapshot without saving back own the
        resulting staleness.
        """

        cache_key = str(self.index_path)
        signature = _index_signature(self.index_path)
        if signature is not None:
            with _INDEX_CACHE_LOCK:
                cached = _INDEX_CACHE.get(cache_key)
            if cached is not None and cached[0] == signature:
                return cached[1]
        # Stat before read: a concurrent atomic replace can only make the
        # recorded signature older than the content (next load re-parses),
        # never serve a stale snapshot under a fresh signature.
        index = self._parse_index_file()
        if signature is not None:
            with _INDEX_CACHE_LOCK:
                _INDEX_CACHE[cache_key] = (signature, index)
        return index

    def _parse_index_file(self) -> dict[str, Any]:
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
        # Shallow top-level copy: normalization below must not leak into the
        # caller's dict, but nested values are serialized synchronously by
        # the only writer thread (under its own lock), so a full deepcopy of
        # an unboundedly growing index is pure write amplification.
        index = dict(payload)
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
                # Compact separators: the index is machine-read only
                # (json.loads), and pretty-printing a many-MB snapshot
                # multiplies the per-event write cost.  Key order stays
                # deterministic via sort_keys.
                json.dump(index, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
            os.replace(temp_path, self.index_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        signature = _index_signature(self.index_path)
        if signature is not None:
            with _INDEX_CACHE_LOCK:
                _INDEX_CACHE[str(self.index_path)] = (signature, index)
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
