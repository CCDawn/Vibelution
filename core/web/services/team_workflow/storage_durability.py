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

# Without LongPathsEnabled the Win32 layer rejects any path >= 260 with
# FileNotFoundError errno 2 even when every component exists; deep live
# run directories already sit within ~30 chars of that ceiling.
_WINDOWS_EXTENDED_LENGTH_PREFIX = "\\\\?\\"
_WINDOWS_LONG_PATH_THRESHOLD = 248


def _windows_extended_length_path(path: Path) -> Path:
    """Lift ``path`` past MAX_PATH with the ``\\\\?\\`` prefix when needed.

    Drive-letter absolute paths only: UNC paths need the ``\\\\?\\UNC\\``
    form and are left untouched. Short paths round-trip unchanged so
    existing lock identities stay byte-stable.
    """
    text = str(path)
    if (
        _IS_WINDOWS
        and len(text) >= _WINDOWS_LONG_PATH_THRESHOLD
        and text[1:3] == ":\\"
        and not text.startswith(_WINDOWS_EXTENDED_LENGTH_PREFIX)
    ):
        return Path(_WINDOWS_EXTENDED_LENGTH_PREFIX + text)
    return path


@contextlib.contextmanager
def inter_process_lock(store_path: Path, *, timeout_s: float = 10.0) -> Iterator[None]:
    """Blocking cross-process lock keyed on ``<store>.lock``.

    OS file locks release when the owning process dies, so a crashed
    writer cannot leave a stale lock behind.
    """
    lock_path = _windows_extended_length_path(
        store_path.with_name(store_path.name + ".lock")
    )
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


def append_record(
    path: Path,
    record: dict,
    *,
    ascii: bool = False,
    timeout_s: float = 30.0,
) -> None:
    """True O(1) durable append: lock, write one line, flush, fsync.

    The store family grew out of a whole-file-replace append whose cost was
    O(file) per record — a 7 MB meeting ledger paid a 7 MB rewrite for every
    appended row.  This primitive writes only the new line inside the same
    inter-process lock, so append cost stays O(line) while cross-process
    serialization is unchanged (a locked append can never lose a record the
    way the old unlocked read-modify-write race did).

    The trade versus whole-file replace is a crash window of at most one
    torn line (``os.replace`` could never tear the file); the tolerant
    readers already quarantine such lines to ``<store>.corrupt``, so a torn
    line degrades to losing that one in-flight record, never the store.

    ``ascii`` selects ``ensure_ascii=True`` for stores whose historical
    format escaped non-ASCII (``team_knowledge``); everything else uses the
    canonical ``ensure_ascii=False, sort_keys=True`` line format, which is
    byte-identical to the previous whole-file append output.
    """
    line = (
        json.dumps(
            record,
            ensure_ascii=bool(ascii),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with inter_process_lock(path, timeout_s=timeout_s):
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


def rewrite_records(path: Path, records: list[dict]) -> None:
    """Locked whole-file replace for compaction, quarantine and cleanup.

    Writers that genuinely need read-modify-write semantics (collapse
    superseded copies, drop quarantined lines) rewrite through this single
    primitive so every mutation of a store serializes on the same lock an
    :func:`append_record` takes — an append racing a compaction can never
    be lost to a stale snapshot.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with inter_process_lock(path):
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                for record in records:
                    handle.write(
                        json.dumps(
                            record,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)


def transform_records(
    path: Path,
    transform,
) -> list[dict]:
    """Locked read-transform-rewrite for compaction and cleanup.

    A compaction that reads outside the lock can lose a racing append (it
    rewrites from a stale snapshot).  This primitive holds the same
    inter-process lock :func:`append_record` takes across the whole
    read-compute-rewrite sequence, so a concurrent append either lands
    before the read (kept) or after the rewrite (kept) — never dropped.
    ``transform`` receives the tolerant-read records and returns the
    records to keep; the return value lists what was written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with inter_process_lock(path):
        records = read_jsonl_tolerant(path) if path.exists() else []
        kept = list(transform(records) or [])
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                for record in kept:
                    handle.write(
                        json.dumps(
                            record,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
    return kept


def append_jsonl_locked(path: Path, record: dict) -> None:
    """Canonical locked append; see :func:`append_record`.

    Historical name kept for the existing call sites (meeting rounds, the
    hypothesis chain store, driver work): the whole-file re-read that used
    to live here fixed the cross-process lost-update race, and the locked
    true append preserves exactly that guarantee at O(line) cost.
    """
    append_record(path, record)


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
