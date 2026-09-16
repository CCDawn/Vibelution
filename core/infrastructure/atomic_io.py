"""Shared atomic file-write helpers for local workspace state."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable
from os import PathLike
from pathlib import Path
from typing import Any

from core.infrastructure.file_lock import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    cross_process_file_lock,
)


DEFAULT_RETRY_TIMEOUT_SECONDS = 5.0
DEFAULT_FALLBACK_TIMEOUT_SECONDS = 5.0
_DEFAULT_RETRY_DELAY_BASE_SECONDS = 0.05


def atomic_write_text(
    path: str | PathLike[str],
    text: str,
    *,
    retry_timeout_seconds: float = DEFAULT_RETRY_TIMEOUT_SECONDS,
    fallback_timeout_seconds: float = DEFAULT_FALLBACK_TIMEOUT_SECONDS,
    lock_timeout_seconds: float | None = DEFAULT_LOCK_TIMEOUT_SECONDS,
    ensure_parent_dir: bool = True,
    ensure_fsync: bool = True,
    on_retry: Callable[[int, str], None] | None = None,
) -> None:
    """Write text via temp-file replace, with Windows-friendly lock retries.

    Writers are serialized per target file across threads and processes via a
    ``<target>.lock`` sidecar; the lock granularity is exactly one file, so
    unrelated writes never contend. Within that lock, a blocked replacement is
    retried for ``retry_timeout_seconds`` (readers that opened the target
    before the write do not take the lock, so ``PermissionError`` can still
    surface transiently on Windows).

    If temp-file creation or final replacement stays blocked, this falls back to
    an in-place write. That fallback is intentionally narrow: it prevents data
    loss during local disk or antivirus races, while callers that need strict
    all-or-nothing semantics should keep their own stricter helper.
    """

    target = Path(path)
    if ensure_parent_dir:
        target.parent.mkdir(parents=True, exist_ok=True)
    with cross_process_file_lock(target, timeout=lock_timeout_seconds):
        temp_path = _write_temp_file(target, text, ensure_fsync=ensure_fsync)
        if temp_path is None:
            _retry_in_place_write(target, text, timeout_seconds=fallback_timeout_seconds)
            return
        try:
            try:
                _replace_with_retry(
                    target,
                    temp_path,
                    timeout_seconds=retry_timeout_seconds,
                    on_retry=on_retry,
                )
            except OSError:
                _retry_in_place_write(target, text, timeout_seconds=fallback_timeout_seconds)
            if ensure_fsync:
                _fsync_parent_dir(target.parent)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass


def atomic_write_json(
    path: str | PathLike[str],
    payload: dict[str, Any] | list[Any],
    *,
    indent: int | None = 2,
    sort_keys: bool = False,
    ensure_ascii: bool = False,
    **write_options: Any,
) -> None:
    """Serialize and atomically write a JSON object or list."""

    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=ensure_ascii, indent=indent, sort_keys=sort_keys),
        **write_options,
    )


def _write_temp_file(target: Path, text: str, *, ensure_fsync: bool) -> Path | None:
    fd = -1
    temp_name = ""
    try:
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            fd = -1
            handle.write(text)
            if ensure_fsync:
                handle.flush()
                os.fsync(handle.fileno())
        return Path(temp_name)
    except OSError:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
        return None


def _replace_with_retry(
    target: Path,
    temp_path: Path,
    *,
    timeout_seconds: float,
    on_retry: Callable[[int, str], None] | None = None,
) -> None:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    attempt = 0
    last_error: PermissionError | None = None
    while True:
        try:
            os.replace(temp_path, target)
            return
        except PermissionError as exc:
            last_error = exc
            attempt += 1
            if on_retry is not None:
                try:
                    on_retry(attempt, type(exc).__name__)
                except Exception:
                    pass
            if time.monotonic() >= deadline:
                break
            time.sleep(_retry_delay(attempt))
    if last_error is not None:
        raise last_error


def _retry_in_place_write(target: Path, text: str, *, timeout_seconds: float) -> None:
    deadline: float | None = None
    attempt = 0
    while True:
        try:
            target.write_text(text, encoding="utf-8")
            return
        except OSError as exc:
            attempt += 1
            if deadline is None:
                deadline = time.monotonic() + max(0.0, timeout_seconds)
            if time.monotonic() >= deadline:
                raise exc
            time.sleep(_retry_delay(attempt))


def _retry_delay(attempt: int) -> float:
    return min(_DEFAULT_RETRY_DELAY_BASE_SECONDS * max(1, attempt), 0.25)


def _fsync_parent_dir(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
