from __future__ import annotations

from pathlib import Path
import threading

import pytest

import core.infrastructure.file_lock as file_lock
from core.infrastructure.file_lock import (
    cross_process_file_lock,
    locked_sidecar,
)


def test_locked_sidecar_seeds_first_byte_only_after_lock_acquisition(
    tmp_path, monkeypatch
):
    """The lock-file seed write must never run before the lock is held.

    Two processes can both observe an empty lock file; on Windows a pre-lock
    write can land in the byte range another process already locked, which
    surfaces as PermissionError (lock violation) and aborts the append.
    """

    sidecar = tmp_path / "target.lock"
    events: list[str] = []
    real_try_lock = file_lock._try_lock_handle
    real_open = file_lock.Path.open

    class _SpyLockHandle:
        def __init__(self, handle):
            self._handle = handle

        def __getattr__(self, name):
            return getattr(self._handle, name)

        def write(self, data):
            events.append("write")
            return self._handle.write(data)

        def __enter__(self):
            self._handle.__enter__()
            return self

        def __exit__(self, *exc_info):
            return self._handle.__exit__(*exc_info)

    def spy_open(path_self, mode="r", **kwargs):
        return _SpyLockHandle(real_open(path_self, mode, **kwargs))

    def spy_try_lock(handle):
        acquired = real_try_lock(handle)
        events.append("locked" if acquired else "lock-busy")
        return acquired

    monkeypatch.setattr(file_lock.Path, "open", spy_open)
    monkeypatch.setattr(file_lock, "_try_lock_handle", spy_try_lock)

    with locked_sidecar(tmp_path / "target") as handle:
        events.append("critical-section")

    assert events.count("write") == 1
    assert "locked" in events
    assert "critical-section" in events
    assert events.index("write") > events.index("locked")
    assert sidecar.stat().st_size == 1


def test_locked_sidecar_and_cross_process_lock_share_sidecar_semantics(tmp_path):
    target = tmp_path / "target.bin"
    sidecar = target.with_name(f"{target.name}.lock")

    with locked_sidecar(target):
        assert sidecar.exists()
        assert sidecar.stat().st_size == 1

    with cross_process_file_lock(target):
        assert sidecar.stat().st_size == 1

    # Sequential holders reuse the same sidecar without stale seed bytes.
    with locked_sidecar(target, lock_path=sidecar):
        assert sidecar.stat().st_size == 1


def test_locked_sidecar_times_out_while_another_process_holds_the_lock(tmp_path):
    target = tmp_path / "contended.bin"
    blocker = locked_sidecar(target)
    blocker.__enter__()
    try:
        with pytest.raises(TimeoutError):
            with locked_sidecar(target, timeout=0.05):
                pass
    finally:
        blocker.__exit__(None, None, None)

    # The lock is free again after the holder releases it.
    with locked_sidecar(target, timeout=1.0):
        pass


def test_cross_process_file_lock_depth_is_reentrant_per_thread(tmp_path):
    target = tmp_path / "reentrant.bin"
    with cross_process_file_lock(target, timeout=1.0):
        with cross_process_file_lock(target, timeout=1.0):
            pass


def test_cross_process_file_lock_timeout_includes_another_thread(tmp_path):
    target = tmp_path / "thread-contention.bin"
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def contend():
        started.set()
        try:
            with cross_process_file_lock(target, timeout=0.05):
                pass
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    with cross_process_file_lock(target):
        worker = threading.Thread(target=contend, daemon=True)
        worker.start()
        assert started.wait(timeout=2)
        timed_out_while_held = finished.wait(timeout=1)
    worker.join(timeout=2)

    assert timed_out_while_held, "Thread contention must honor the lock timeout."
    assert not worker.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], TimeoutError)
    with cross_process_file_lock(target, timeout=0):
        pass


def test_cross_process_lock_passes_only_remaining_budget_to_os(tmp_path, monkeypatch):
    from contextlib import contextmanager

    target = tmp_path / "shared-budget.bin"
    clock = [100.0]
    budgets: list[float | None] = []

    class ThreadLock:
        def acquire(self, **kwargs):
            clock[0] += 0.4
            return True

        def release(self):
            pass

        def __enter__(self):
            self.acquire()

        def __exit__(self, *args):
            self.release()

    @contextmanager
    def os_lock(*args, timeout, **kwargs):
        budgets.append(timeout)
        yield

    entry = file_lock._ThreadLockEntry()
    entry.lock = ThreadLock()
    monkeypatch.setitem(file_lock._THREAD_LOCKS, file_lock._path_key(file_lock.lock_path_for(target)), entry)
    monkeypatch.setattr(file_lock.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(file_lock, "_locked_sidecar", os_lock)

    with cross_process_file_lock(target, timeout=0.5):
        pass

    assert budgets == [pytest.approx(0.1)]
