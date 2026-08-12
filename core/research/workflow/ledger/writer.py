"""Bounded single writer for the Workflow Ledger (spec 7.1/13.1).

All formal mutations flow through ``submit(..., force_flush=True)``. The
writer thread owns one connection and commits each batch inside
``BEGIN IMMEDIATE``; per-envelope savepoints isolate failures. after-commit
callbacks only run after the enclosing commit.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

from .errors import WorkflowLedgerBackpressureError, WorkflowLedgerClosedError
from .unit_of_work import WorkflowLedgerUnitOfWork

DEFAULT_QUEUE_SIZE = 2048
DEFAULT_ENQUEUE_TIMEOUT_MS = 250


class _Envelope:
    __slots__ = ("fn", "force_flush", "future")

    def __init__(self, fn: Callable[[WorkflowLedgerUnitOfWork], Any], force_flush: bool) -> None:
        self.fn = fn
        self.force_flush = force_flush
        self.future: Future[Any] = Future()


class WorkflowLedgerWriter:
    def __init__(
        self,
        database: Any,
        *,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        enqueue_timeout_ms: int = DEFAULT_ENQUEUE_TIMEOUT_MS,
        poll_interval_s: float = 0.05,
    ) -> None:
        self._database = database
        self._queue: queue.Queue[_Envelope | None] = queue.Queue(maxsize=max(1, queue_size))
        self._enqueue_timeout_s = max(0.001, enqueue_timeout_ms / 1000)
        self._poll_interval_s = poll_interval_s
        self._closed = False
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="workflow-ledger-writer", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def submit(self, fn: Callable[[WorkflowLedgerUnitOfWork], Any], *, force_flush: bool = False) -> Future:
        if self._closed:
            raise WorkflowLedgerClosedError("workflow ledger writer is closed")
        envelope = _Envelope(fn, force_flush)
        try:
            self._queue.put(envelope, timeout=self._enqueue_timeout_s)
        except queue.Full as exc:
            raise WorkflowLedgerBackpressureError(
                "workflow ledger writer queue is full; mutation rejected"
            ) from exc
        if force_flush:
            self._flush_until(envelope)
        return envelope.future

    def flush(self) -> None:
        """Block until the queue is drained (used by maintenance/close paths)."""
        sentinel: _Envelope | None = None
        self._queue.put(sentinel)
        # sentinel is never consumed as work; wait until queue drains past it.
        deadline = time.monotonic() + 30.0
        while not self._queue.empty() and time.monotonic() < deadline:
            time.sleep(self._poll_interval_s)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_event.set()
        try:
            self._queue.put(None, timeout=5.0)
        except queue.Full:
            # Worker is busy processing or draining; it re-checks the stop
            # event after the current batch, so the wake-up is not needed.
            pass
        self._thread.join(timeout=10.0)

    def _flush_until(self, envelope: _Envelope) -> None:
        deadline = time.monotonic() + 30.0
        while not envelope.future.done():
            if envelope.future.cancelled():
                return
            if time.monotonic() > deadline:
                return
            time.sleep(self._poll_interval_s)

    # ------------------------------------------------------------------ run

    def _run(self) -> None:
        connection = self._database.open_writer()
        try:
            while not self._stop_event.is_set():
                envelope = self._queue.get()
                if envelope is None:
                    break
                batch: list[_Envelope] = [envelope]
                while not self._queue.empty() and not envelope.force_flush:
                    next_envelope = self._queue.get_nowait()
                    if next_envelope is None:
                        self._stop_event.set()
                        break
                    batch.append(next_envelope)
                    if next_envelope.force_flush:
                        break
                self._process_batch(connection, batch)
        finally:
            try:
                connection.close()
            except Exception:
                pass

    def _process_batch(self, connection: Any, batch: list[_Envelope]) -> None:
        group: list[_Envelope] = []
        for envelope in batch:
            if envelope.force_flush and group:
                self._commit_group(connection, group)
                group = []
            group.append(envelope)
            if envelope.force_flush:
                self._commit_group(connection, group)
                group = []
        if group:
            self._commit_group(connection, group)

    def _commit_group(self, connection: Any, group: list[_Envelope]) -> None:
        committed: list[tuple[_Envelope, WorkflowLedgerUnitOfWork]] = []
        connection.execute("BEGIN IMMEDIATE")
        try:
            for index, envelope in enumerate(group):
                savepoint = f"workflow_ledger_mutation_{index}"
                connection.execute(f"SAVEPOINT {savepoint}")
                uow = WorkflowLedgerUnitOfWork(connection)
                try:
                    envelope.future.set_result(envelope.fn(uow))
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                    committed.append((envelope, uow))
                except Exception as exc:
                    connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                    envelope.future.set_exception(exc)
            connection.execute("COMMIT")
        except Exception as exc:
            try:
                connection.execute("ROLLBACK")
            except Exception:
                pass
            for envelope in group:
                if not envelope.future.done():
                    envelope.future.set_exception(exc)
            return
        for envelope, uow in committed:
            for callback in uow.take_after_commit():
                try:
                    callback()
                except Exception:
                    pass
