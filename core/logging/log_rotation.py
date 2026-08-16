"""Shared bounded log rotation and tail-copy helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_LOG_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_LOG_BACKUP_COUNT = 3
DEFAULT_SCENE_RAW_TAIL_MAX_BYTES = 512 * 1024


def rotated_log_path(path: Path, index: int) -> Path:
    return path.with_name(f"{path.name}.{index}")


def rotate_log_file(
    path: Path,
    *,
    max_bytes: int | None = None,
    backup_count: int | None = None,
) -> dict[str, Any]:
    effective_max_bytes = DEFAULT_LOG_MAX_BYTES if max_bytes is None else max_bytes
    effective_backup_count = DEFAULT_LOG_BACKUP_COUNT if backup_count is None else backup_count
    payload: dict[str, Any] = {
        "path": str(path),
        "maxBytes": int(effective_max_bytes),
        "backupCount": int(effective_backup_count),
        "sizeBytes": 0,
        "rotated": False,
        "backupPath": "",
        "action": "none",
        "errorType": "",
        "errorMessage": "",
    }
    try:
        if int(effective_max_bytes) <= 0 or not path.exists():
            return payload
        size_bytes = int(path.stat().st_size)
        payload["sizeBytes"] = size_bytes
        if size_bytes <= int(effective_max_bytes):
            return payload
        path.parent.mkdir(parents=True, exist_ok=True)
        if int(effective_backup_count) <= 0:
            path.write_text("", encoding="utf-8")
            payload.update({"rotated": True, "action": "truncated"})
            return payload
        for index in range(int(effective_backup_count), 0, -1):
            source = rotated_log_path(path, index)
            if index == int(effective_backup_count):
                if source.exists():
                    source.unlink()
                continue
            target = rotated_log_path(path, index + 1)
            if source.exists():
                source.replace(target)
        backup_path = rotated_log_path(path, 1)
        path.replace(backup_path)
        path.touch()
        payload.update({"rotated": True, "backupPath": str(backup_path), "action": "rotated"})
    except Exception as exc:  # pragma: no cover - platform-specific filesystem race
        payload.update({"errorType": type(exc).__name__, "errorMessage": str(exc)})
    return payload


def read_log_tail_bytes(path: Path, *, max_bytes: int = DEFAULT_SCENE_RAW_TAIL_MAX_BYTES) -> bytes:
    if max_bytes <= 0 or not path.is_file():
        return b""
    try:
        size_bytes = path.stat().st_size
    except OSError:
        return b""
    if size_bytes <= max_bytes:
        return path.read_bytes()
    with path.open("rb") as handle:
        handle.seek(max(0, size_bytes - max_bytes))
        chunk = handle.read()
    if not chunk:
        return b""
    newline = chunk.find(b"\n")
    if newline >= 0:
        return chunk[newline + 1 :]
    return chunk


def write_log_tail_copy(
    source: Path,
    destination: Path,
    *,
    max_bytes: int = DEFAULT_SCENE_RAW_TAIL_MAX_BYTES,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sourcePath": str(source),
        "destinationPath": str(destination),
        "maxBytes": int(max_bytes),
        "sourceSizeBytes": 0,
        "writtenBytes": 0,
        "copied": False,
        "errorType": "",
        "errorMessage": "",
    }
    try:
        if not source.is_file():
            return payload
        payload["sourceSizeBytes"] = int(source.stat().st_size)
        tail = read_log_tail_bytes(source, max_bytes=max_bytes)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(tail)
        payload.update({"writtenBytes": len(tail), "copied": True})
    except Exception as exc:
        payload.update({"errorType": type(exc).__name__, "errorMessage": str(exc)})
    return payload
