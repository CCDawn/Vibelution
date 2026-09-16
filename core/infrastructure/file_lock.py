"""Cross-process, per-target advisory file locks for local state writes.

The lock is a ``<target>.lock`` sidecar file guarded by a byte-range OS lock
(``msvcrt.locking`` on Windows, ``fcntl.flock`` elsewhere) on top of a
per-path in-process reentrant thread lock. Lock granularity is exactly one
sidecar per target file: writers of unrelated files never contend, and there
is deliberately no global lock.

The seed byte is written only while holding the OS lock. Two processes can
both observe an empty lock file, and a pre-lock write can land in the byte
range another process already locked (Windows maps that lock violation to
``PermissionError``); deferring the seed until the lock is held keeps the
lock owner the only writer. This mirrors ``core/chat/turn_journal.py``.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

DEFAULT_LOCK_TIMEOUT_SECONDS = 30.0
# Deliberately larger than the bounded critical sections it serializes (for
# example the chat-state transaction's 5s store-result plus 5s store-close
# budgets), so a patient waiter converges instead of timing out exactly when a
# slow-but-bounded holder finishes. Still bounded so a pathological holder
# surfaces as TimeoutError instead of hanging forever.
_DEFAULT_POLL_INTERVAL_SECONDS = 0.01


class _ThreadLockEntry:
    __slots__ = ("lock", "users")

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.users = 0


_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, _ThreadLockEntry] = {}
_LOCK_DEPTH = threading.local()


def lock_path_for(path: str | os.PathLike[str]) -> Path:
    """Return the sidecar lock path convention for one target file."""

    target = Path(path)
    return target.with_name(f"{target.name}.lock")


def _path_key(path: Path) -> str:
    try:
        raw = str(path.resolve())
    except OSError:
        raw = str(path)
    return raw.lower() if os.name == "nt" else raw


@contextmanager
def cross_process_file_lock(
    path: str | os.PathLike[str],
    *,
    timeout: float | None = DEFAULT_LOCK_TIMEOUT_SECONDS,
    poll_interval: float = _DEFAULT_POLL_INTERVAL_SECONDS,
    lock_path: str | os.PathLike[str] | None = None,
) -> Iterator[None]:
    """Hold one exclusive per-target lock across threads and processes.

    ``timeout`` bounds the wait for the OS lock; ``None`` blocks indefinitely.
    Same-thread nesting is reentrant. Raises ``TimeoutError`` when the budget
    is exhausted so callers can surface a recognizable contention failure
    instead of hanging.
    """

    sidecar = Path(lock_path) if lock_path is not None else lock_path_for(path)
    key = _path_key(sidecar)
    depth: dict[str, int] = getattr(_LOCK_DEPTH, "counts", {})
    if not hasattr(_LOCK_DEPTH, "counts"):
        _LOCK_DEPTH.counts = depth
    if depth.get(key, 0) > 0:
        depth[key] += 1
        try:
            yield
        finally:
            depth[key] -= 1
            if depth[key] <= 0:
                depth.pop(key, None)
        return

    with _THREAD_LOCKS_GUARD:
        entry = _THREAD_LOCKS.get(key)
        if entry is None:
            entry = _ThreadLockEntry()
            _THREAD_LOCKS[key] = entry
        entry.users += 1
    try:
        with entry.lock:
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            deadline: float | None = None
            if timeout is not None:
                deadline = time.monotonic() + max(0.0, float(timeout))
            handle = _open_locked_sidecar(
                sidecar,
                key=key,
                deadline=deadline,
                poll_interval=poll_interval,
            )
            try:
                _seed_lock_byte(handle)
                depth[key] = 1
                try:
                    yield
                finally:
                    depth.pop(key, None)
            finally:
                _release_os_lock(handle)
                handle.close()
    finally:
        with _THREAD_LOCKS_GUARD:
            entry.users -= 1
            if entry.users == 0 and _THREAD_LOCKS.get(key) is entry:
                _THREAD_LOCKS.pop(key, None)


def _open_locked_sidecar(
    sidecar: Path,
    *,
    key: str,
    deadline: float | None,
    poll_interval: float,
) -> BinaryIO:
    """Open the sidecar and take its OS lock, bounded by one shared deadline.

    The open itself is inside the retry: a freshly created sidecar can be held
    briefly by a file scanner, and an unguarded ``open`` would turn that
    transient contention into an immediate ``PermissionError``.
    """

    while True:
        handle: BinaryIO | None = None
        blocked: OSError | None = None
        try:
            handle = sidecar.open("a+b")
        except OSError as exc:
            blocked = exc
        if handle is not None and _try_lock_handle(handle):
            return handle
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        if deadline is not None and time.monotonic() >= deadline:
            error = TimeoutError(f"Timed out acquiring cross-process file lock: {key}")
            if blocked is not None:
                raise error from blocked
            raise error
        time.sleep(min(max(0.0, poll_interval), 0.25))


def _try_lock_handle(handle: BinaryIO) -> bool:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        return False
    return True


def _seed_lock_byte(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()


def _release_os_lock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


__all__ = ["DEFAULT_LOCK_TIMEOUT_SECONDS", "cross_process_file_lock", "lock_path_for"]
