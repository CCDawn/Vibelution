"""Bounded single writer for the Workflow Ledger (spec 7.1/13.1).

All formal mutations flow through ``submit(..., force_flush=True)``. The
writer thread owns one connection and commits each batch inside
``BEGIN IMMEDIATE``; per-envelope savepoints isolate failures. Futures are
staged and only settle after the enclosing COMMIT succeeds. after-commit
callbacks only run after a successful commit. ``close()`` stops accepting
new work, drains every accepted envelope in FIFO order, and settles the
remaining futures explicitly when the drain times out.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, InvalidStateError
from typing import Any

from .errors import (
    WorkflowLedgerBackpressureError,
    WorkflowLedgerClosedError,
    WorkflowLedgerUnavailableError,
)
from .unit_of_work import WorkflowLedgerUnitOfWork

DEFAULT_QUEUE_SIZE = 2048
DEFAULT_ENQUEUE_TIMEOUT_MS = 250
DEFAULT_CLOSE_TIMEOUT_S = 10.0
DEFAULT_START_TIMEOUT_S = 30.0
DEFAULT_FLUSH_TIMEOUT_S = 30.0

_WAKEUP = object()


class _Envelope:
    __slots__ = ("fn", "force_flush", "future", "settled")

    def __init__(self, fn: Callable[[WorkflowLedgerUnitOfWork], Any], force_flush: bool) -> None:
        self.fn = fn
        self.force_flush = force_flush
        self.future: Future[Any] = Future()
        self.settled = False


def _closed_error(detail: str) -> WorkflowLedgerClosedError:
    return WorkflowLedgerClosedError(detail)


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
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=max(1, queue_size))
        self._enqueue_timeout_s = max(0.001, enqueue_timeout_ms / 1000)
        self._poll_interval_s = poll_interval_s
        self._closed = False
        self._accepting = True
        self._accept_lock = threading.Lock()
        self._drain_requested = threading.Event()
        self._abandoned = threading.Event()
        self._startup_error: BaseException | None = None
        self._startup_gate = threading.Event()
        self._condition = threading.Condition()
        self._outstanding = 0
        self._current_group: list[_Envelope] = []
        self._thread = threading.Thread(target=self._run, name="workflow-ledger-writer", daemon=True)

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Start the writer thread and fail synchronously when it cannot open
        a writer connection (no silently pending futures)."""
        self._thread.start()
        if not self._startup_gate.wait(timeout=DEFAULT_START_TIMEOUT_S):
            self._abandoned.set()
            if self._startup_error is None:
                raise WorkflowLedgerUnavailableError(
                    "workflow ledger writer did not open its connection in time"
                )
        if self._startup_error is not None:
            raise self._startup_public_error()

    def _startup_public_error(self) -> WorkflowLedgerUnavailableError:
        return WorkflowLedgerUnavailableError(
            f"workflow ledger writer failed to start: {self._startup_error}"
        )

    def submit(self, fn: Callable[[WorkflowLedgerUnitOfWork], Any], *, force_flush: bool = False) -> Future:
        if self._startup_error is not None:
            raise self._startup_public_error()
        with self._accept_lock:
            if not self._accepting:
                raise WorkflowLedgerClosedError("workflow ledger writer is closed")
            envelope = _Envelope(fn, force_flush)
            with self._condition:
                self._outstanding += 1
        try:
            self._queue.put(envelope, timeout=self._enqueue_timeout_s)
        except queue.Full as exc:
            with self._condition:
                self._outstanding = max(0, self._outstanding - 1)
            raise WorkflowLedgerBackpressureError(
                "workflow ledger writer queue is full; mutation rejected"
            ) from exc
        if force_flush:
            self._flush_until(envelope)
        return envelope.future

    def flush(self, timeout: float = DEFAULT_FLUSH_TIMEOUT_S) -> None:
        """Block until every accepted envelope is settled (maintenance/close paths)."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._outstanding > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                self._condition.wait(timeout=remaining)

    def close(self, timeout: float = DEFAULT_CLOSE_TIMEOUT_S) -> None:
        with self._accept_lock:
            if self._closed:
                return
            self._closed = True
            self._accepting = False
        self._drain_requested.set()
        try:
            self._queue.put_nowait(_WAKEUP)
        except queue.Full:
            pass
        self._thread.join(timeout=max(0.0, timeout))
        if self._thread.is_alive():
            self._abandoned.set()
            self._settle_remaining(
                WorkflowLedgerClosedError(
                    "workflow ledger writer closed before pending mutations were committed"
                )
            )

    def _flush_until(self, envelope: _Envelope) -> None:
        deadline = time.monotonic() + DEFAULT_FLUSH_TIMEOUT_S
        while not envelope.future.done():
            if time.monotonic() > deadline:
                self._settle(
                    envelope,
                    error=WorkflowLedgerClosedError(
                        "workflow ledger flush timed out; mutation outcome unknown"
                    ),
                )
                return
            time.sleep(self._poll_interval_s)

    # ------------------------------------------------------------ settling

    def _settle(
        self,
        envelope: _Envelope,
        *,
        result: Any = None,
        error: BaseException | None = None,
    ) -> None:
        """Exactly-once settlement of an envelope future (guarded by a lock)."""
        with self._condition:
            if envelope.settled:
                return
            try:
                if error is not None:
                    envelope.future.set_exception(error)
                else:
                    envelope.future.set_result(result)
            except InvalidStateError:
                pass
            envelope.settled = True
            self._outstanding = max(0, self._outstanding - 1)
            self._condition.notify_all()

    def _settle_remaining(self, error: BaseException) -> None:
        group = self._current_group
        self._current_group = []
        items = [envelope for envelope in group if not envelope.settled]
        while True:
            try:
                envelope = self._queue.get_nowait()
            except queue.Empty:
                break
            if envelope is _WAKEUP:
                continue
            items.append(envelope)
        for envelope in items:
            self._settle(envelope, error=error)

    # ------------------------------------------------------------------ run

    def _run(self) -> None:
        try:
            connection = self._database.open_writer()
        except BaseException as exc:
            self._startup_error = exc
            self._startup_gate.set()
            self._settle_remaining(
                WorkflowLedgerUnavailableError(
                    f"workflow ledger writer failed to start: {exc}"
                )
            )
            return
        self._startup_gate.set()
        try:
            self._drain_loop(connection)
        except BaseException as exc:
            if not isinstance(exc, Exception):
                exc = RuntimeError(str(exc))
            self._settle_remaining(exc)
        finally:
            try:
                connection.close()
            except Exception:
                pass

    def _drain_loop(self, connection: Any) -> None:
        while True:
            if self._abandoned.is_set():
                self._settle_remaining(
                    WorkflowLedgerClosedError(
                        "workflow ledger writer abandoned during close"
                    )
                )
                return
            try:
                envelope = self._queue.get(timeout=self._poll_interval_s)
            except queue.Empty:
                envelope = None
            if envelope is None or envelope is _WAKEUP:
                if (
                    self._drain_requested.is_set()
                    and self._queue.empty()
                    and not self._current_group
                ):
                    return
                continue
            self._current_group = [envelope]
            while not envelope.force_flush:
                try:
                    next_envelope = self._queue.get_nowait()
                except queue.Empty:
                    break
                if next_envelope is _WAKEUP:
                    continue
                self._current_group.append(next_envelope)
                if next_envelope.force_flush:
                    break
            try:
                self._process_batch(connection, self._current_group)
            finally:
                self._current_group = []
            if self._drain_requested.is_set() and self._queue.empty():
                return

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
        staged: list[tuple[_Envelope, Any]] = []
        callbacks: list[Callable[[], None]] = []
        connection.execute("BEGIN IMMEDIATE")
        try:
            for index, envelope in enumerate(group):
                if self._abandoned.is_set():
                    raise WorkflowLedgerClosedError(
                        "workflow ledger writer closed before the mutation committed"
                    )
                savepoint = f"workflow_ledger_mutation_{index}"
                connection.execute(f"SAVEPOINT {savepoint}")
                uow = WorkflowLedgerUnitOfWork(connection)
                try:
                    result = envelope.fn(uow)
                    if self._abandoned.is_set():
                        raise WorkflowLedgerClosedError(
                            "workflow ledger writer closed before the mutation committed"
                        )
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                    staged.append((envelope, result))
                    callbacks.extend(uow.take_after_commit())
                except Exception as exc:
                    connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                    self._settle(envelope, error=exc)
            if self._abandoned.is_set():
                raise WorkflowLedgerClosedError(
                    "workflow ledger writer closed before the mutation committed"
                )
            connection.execute("COMMIT")
        except Exception as exc:
            try:
                connection.execute("ROLLBACK")
            except Exception:
                pass
            for envelope in group:
                self._settle(envelope, error=exc)
            return
        for envelope, result in staged:
            self._settle(envelope, result=result)
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass
