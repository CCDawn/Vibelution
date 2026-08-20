"""Durable JSONL storage primitives for team workflow stores.

Audit findings this module closes:

- **Cross-process lost updates.** Every store wrote with atomic
  temp-file replace, but the read-modify-write sequence was guarded only
  by an in-process ``threading`` lock. Two processes (backend plus any
  second writer) each replayed their append on top of a stale snapshot and
  the last replace silently dropped the other's records. All mutations now
  serialize on an inter-process lock file next to the store.

- **Single corrupt line bricked team state.``_read_jsonl`` raised on the
  first malformed line, so one torn write made every chain-state read fail
  forever. Reads now quarantine corrupt lines to ``<store>.corrupt`` and
  continue; the store is rewritten without them so quarantining is
  idempotent and the bad payload stays recoverable on the side.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

_IS_WINDOWS = os.name == "nt"


@contextlib.contextmanager
def inter_process_lock(store_path: Path, *, timeout_s: float = 10.0) -> Iterator[None]:
    """Blocking cross-process lock keyed on ``<store>.lock``.

    OS file locks release when the owning process dies, so a crashed
    writer cannot leave a stale lock behind.
    """
    lock_path = store_path.with_name(store_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                if _IS_WINDOWS:
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
        try:
            yield
        finally:
            if _IS_WINDOWS:
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def append_jsonl_locked(path: Path, record: dict) -> None:
    """Atomic append that re-reads under the inter-process lock.

    The re-read inside the lock is the fix: concurrent writers append on
    top of the *current* snapshot instead of a pre-lock stale one, so no
    record is silently dropped.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    with inter_process_lock(path):
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(existing)
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)


def read_jsonl_tolerant(path: Path) -> list[dict]:
    """Read records, quarantining corrupt lines instead of raising.

    Bad lines move to ``<store>.corrupt`` (append) and are removed from the
    store under the lock, so a repeat read does not re-quarantine them.
    Returns ``[]`` for a missing store.
    """
    if not path.exists():
        return []
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    records: list[dict] = []
    corrupt: list[str] = []
    for line in raw_lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            corrupt.append(line)
            continue
        if not isinstance(payload, dict):
            corrupt.append(line)
            continue
        records.append(payload)
    if not corrupt:
        return records
    quarantine_path = path.with_name(path.name + ".corrupt")
    with inter_process_lock(path):
        with quarantine_path.open("a", encoding="utf-8") as handle:
            for line in corrupt:
                handle.write(line + "\n")
        kept = "\n".join(
            line for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and line not in corrupt
        )
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                if kept:
                    handle.write(kept + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
    return records
