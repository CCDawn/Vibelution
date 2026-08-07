"""Crash-safe filesystem helpers for workflow run / index JSON."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


class CorruptWorkflowStoreError(Exception):
    """Raised when durable JSON is unreadable; callers must not invent empty state."""

    def __init__(self, path: Path | str, message: str, *, cause: BaseException | None = None):
        self.path = str(path)
        self.cause = cause
        detail = f"{message} path={self.path}"
        super().__init__(detail)


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write via temp file in the same directory, fsync, then os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        # Best-effort directory fsync on POSIX; ignore on Windows.
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (AttributeError, OSError):
            pass
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise
