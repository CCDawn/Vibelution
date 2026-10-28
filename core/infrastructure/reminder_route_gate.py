"""Cross-process gate for cooperating project storage and sandbox routing.

It protects only upgraded writers and carries no proof about older programs.
The lock is keyed by the actual project directory and held on one OS thread.
"""
from __future__ import annotations

import os
import threading
from contextlib import ExitStack, contextmanager
from pathlib import Path

from .file_lock import cross_process_file_lock, lock_path_for


@contextmanager
def route_writer_gate(project_root: Path, *, required: bool = False):
    """Order: route gate -> source-file pins -> ledger mutex/other locks.

    Legacy projects without a native identity keep their ordinary behavior;
    a migration reader asking for proof instead fails closed. Contention is
    nonblocking so a route writer never waits on a source sender's mutex.
    """
    root = Path(project_root).resolve()
    identity_file = root / ".vibelution" / "project.json"
    if os.name != "nt" or not identity_file.is_file():
        if required:
            raise RuntimeError("reminder_route_gate_unavailable")
        yield lambda: None
        return
    from core.assistant_runtime.initial_migration_binding import _directory
    from core.assistant_runtime.migration_io import pinned_mutable_file, pinned_target_directory
    initial = _directory(root)
    gate = root / ".vibelution" / "reminder-route-gate"
    stack = ExitStack()
    try:
        stack.enter_context(pinned_target_directory(root / ".vibelution"))
        stack.enter_context(pinned_mutable_file(lock_path_for(gate)))
        stack.enter_context(cross_process_file_lock(gate, timeout=0))
        def check():
            if _directory(root) != initial or not identity_file.is_file():
                raise RuntimeError("reminder_route_gate_changed")
        check()
        yield check
        check()
    finally:
        stack.close()


class HeldRouteGate:
    """Hold the file lock on its owning thread until explicit release."""
    def __init__(self, project_root: Path):
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._error = None
        self._check = None
        self._thread = threading.Thread(target=self._run, args=(project_root,), daemon=True)
        self._thread.start()
        self._ready.wait()
        if self._error is not None:
            raise RuntimeError("reminder_route_gate_unavailable") from self._error

    def _run(self, root):
        try:
            with route_writer_gate(root, required=True) as check:
                self._check = check
                self._ready.set()
                self._stop.wait()
        except BaseException as error:
            self._error = error
            self._ready.set()

    def check(self):
        if self._stop.is_set() or not self._thread.is_alive() or self._error is not None or self._check is None:
            raise RuntimeError("reminder_route_gate_unavailable")
        self._check()

    def release(self):
        if self._stop.is_set():
            raise RuntimeError("reminder_route_gate_unavailable")
        self._stop.set()
        self._thread.join()
        if self._error is not None:
            raise RuntimeError("reminder_route_gate_unavailable") from self._error
