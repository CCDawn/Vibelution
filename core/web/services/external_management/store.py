"""Bounded private records, with native cross-process admission locks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import cross_process_file_lock


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, kind: str, key: str) -> Path:
        return self.root / kind / (digest(key) + ".json")

    def lock(self, kind: str, key: str):
        return cross_process_file_lock(self.path(kind, key).with_suffix(".lock"), timeout=5)

    def read(self, path: Path) -> dict | None:
        try:
            with path.open("rb") as handle:
                content = handle.read(64 * 1024 + 1)
        except FileNotFoundError:
            return None
        if len(content) > 64 * 1024:
            raise TypeError("Invalid management record")
        value = json.loads(content)
        if not isinstance(value, dict):
            raise TypeError("Invalid management record")
        return value

    def write(self, path: Path, value: dict) -> None:
        if len(json.dumps(value, ensure_ascii=False).encode()) > 64 * 1024:
            raise ValueError("Management record exceeds limit")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write_json(path, value, strict_replace=True)
        path.chmod(0o600)
