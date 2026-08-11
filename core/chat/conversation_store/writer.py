"""Bounded single-writer actor for canonical conversation mutations."""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from . import runtime as sqlite3
from .database import ConversationDatabase
from .repository import ConversationUnitOfWork

T = TypeVar("T")
Mutation = Callable[[ConversationUnitOfWork], T]


class ConversationBackpressureError(RuntimeError):
    """The bounded writer queue could not accept more work in time."""


class ConversationWriterClosedError(RuntimeError):
    """A mutation was submitted after writer admission closed."""


@dataclass
class _Envelope(Generic[T]):
    mutation: Mutation[T]
    future: Future[T]
    enqueued_at: float
    force_flush: bool = False


_STOP = object()


class ConversationWriter:
    """Serialize writes, group commits, and publish only after durable commit."""

    def __init__(
        self,
        database: ConversationDatabase,
        *,
        queue_capacity: int = 2048,
        max_batch_size: int = 32,
        max_batch_delay_ms: int = 5,
    ) -> None:
        self._database = database
        self._queue: queue.Queue[_Envelope[Any] | object] = queue.Queue(
            maxsize=max(1, int(queue_capacity))
        )
        self._max_batch_size = max(1, int(max_batch_size))
        self._max_batch_delay_s = max(0, int(max_batch_delay_ms)) / 1000
        self._state_lock = threading.Lock()
        self._metrics_lock = threading.Lock()
        self._ready = threading.Event()
        self._accepting = False
        self._thread: threading.Thread | None = None
        self._startup_error: Exception | None = None
        self._queue_wait_ms: deque[float] = deque(maxlen=512)
        self._committed_mutations = 0
        self._failed_mutations = 0
        self._batch_count = 0
        self._max_batch_observed = 0
        self._max_queue_depth = 0
        self._after_commit_callback_failures = 0

    def start(self, *, timeout: float = 5) -> None:
        with self._state_lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._run,
                name="conversation-store-writer",
                daemon=True,
            )
            self._thread.start()
        if not self._ready.wait(timeout=max(0.1, float(timeout))):
            raise TimeoutError("Conversation writer did not start in time.")
        if self._startup_error is not None:
            raise self._startup_error
        with self._state_lock:
            self._accepting = True

    def submit(
        self,
        mutation: Mutation[T],
        *,
        timeout: float | None = 0.25,
        force_flush: bool = False,
    ) -> Future[T]:
        future: Future[T] = Future()
        envelope = _Envelope(
            mutation=mutation,
            future=future,
            enqueued_at=time.perf_counter(),
            force_flush=force_flush,
        )
        with self._state_lock:
            if not self._accepting:
                raise ConversationWriterClosedError(
                    "Conversation writer is not accepting mutations."
                )
            try:
                if timeout is None:
                    self._queue.put(envelope)
                else:
                    self._queue.put(envelope, timeout=max(0, float(timeout)))
            except queue.Full as exc:
                raise ConversationBackpressureError(
                    "Conversation writer queue is full."
                ) from exc
            depth = self._queue.qsize()
        with self._metrics_lock:
            self._max_queue_depth = max(self._max_queue_depth, depth)
        return future

    def flush(self, *, timeout: float = 5) -> None:
        future = self.submit(
            lambda _unit_of_work: None,
            timeout=timeout,
            force_flush=True,
        )
        future.result(timeout=timeout)

    def close(self, *, timeout: float = 5) -> None:
        with self._state_lock:
            thread = self._thread
            if thread is None:
                return
            self._accepting = False
            try:
                self._queue.put(_STOP, timeout=max(0.1, float(timeout)))
            except queue.Full as exc:
                raise TimeoutError(
                    "Conversation writer queue did not drain before shutdown."
                ) from exc
        thread.join(timeout=max(0.1, float(timeout)))
        if thread.is_alive():
            raise TimeoutError("Conversation writer did not stop in time.")
        with self._state_lock:
            self._thread = None

    def metrics(self) -> dict[str, int | float]:
        with self._metrics_lock:
            waits = sorted(self._queue_wait_ms)
            return {
                "queueDepth": self._queue.qsize(),
                "maxQueueDepth": self._max_queue_depth,
                "committedMutations": self._committed_mutations,
                "failedMutations": self._failed_mutations,
                "batchCount": self._batch_count,
                "maxBatchSize": self._max_batch_observed,
                "queueWaitMsP95": _percentile(waits, 0.95),
                "afterCommitCallbackFailures": self._after_commit_callback_failures,
            }

    def _run(self) -> None:
        try:
            connection = self._database.open_writer()
        except Exception as exc:  # noqa: BLE001 - writer startup must unblock callers.
            self._startup_error = exc
            self._ready.set()
            return
        self._ready.set()
        try:
            while True:
                item = self._queue.get()
                if item is _STOP:
                    self._queue.task_done()
                    break
                batch: list[_Envelope[Any]] = [item]
                stop_after_batch = False
                if not item.force_flush:
                    stop_after_batch = self._fill_batch(batch)
                self._process_batch(connection, batch)
                for _envelope in batch:
                    self._queue.task_done()
                if stop_after_batch:
                    break
        finally:
            connection.close()

    def _fill_batch(self, batch: list[_Envelope[Any]]) -> bool:
        deadline = time.perf_counter() + self._max_batch_delay_s
        while len(batch) < self._max_batch_size:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            try:
                item = self._queue.get(timeout=remaining)
            except queue.Empty:
                break
            if item is _STOP:
                self._queue.task_done()
                return True
            batch.append(item)
            if item.force_flush:
                break
        return False

    def _process_batch(
        self,
        connection: sqlite3.Connection,
        batch: list[_Envelope[Any]],
    ) -> None:
        successful: list[
            tuple[_Envelope[Any], Any, tuple[Callable[[], None], ...]]
        ] = []
        failures: list[tuple[_Envelope[Any], Exception]] = []
        now = time.perf_counter()
        with self._metrics_lock:
            self._batch_count += 1
            self._max_batch_observed = max(self._max_batch_observed, len(batch))
            for envelope in batch:
                self._queue_wait_ms.append((now - envelope.enqueued_at) * 1000)
        try:
            connection.execute("BEGIN IMMEDIATE")
            for index, envelope in enumerate(batch):
                savepoint = f"conversation_mutation_{index}"
                unit_of_work = ConversationUnitOfWork(connection)
                connection.execute(f"SAVEPOINT {savepoint}")
                try:
                    result = envelope.mutation(unit_of_work)
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                    successful.append(
                        (envelope, result, unit_of_work.take_after_commit())
                    )
                except Exception as exc:  # noqa: BLE001 - mutation failures are isolated by savepoint.
                    connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                    failures.append((envelope, exc))
            connection.commit()
        except Exception as exc:  # noqa: BLE001 - every queued future needs a terminal outcome.
            try:
                connection.rollback()
            except sqlite3.Error:
                # The original error is still the useful terminal result for
                # callers; the next writer operation will reopen only in a
                # later recovery phase if SQLite itself remains unhealthy.
                pass
            failures.extend((envelope, exc) for envelope, _result, _callbacks in successful)
            successful.clear()
            settled = {id(envelope) for envelope, _failure in failures}
            failures.extend(
                (envelope, exc)
                for envelope in batch
                if id(envelope) not in settled
            )

        for envelope, result, callbacks in successful:
            for callback in callbacks:
                try:
                    callback()
                except Exception as exc:  # noqa: BLE001 - callbacks are external event sinks.
                    # Persistence has committed. Event publication is repaired by the
                    # later canonical reconcile and must not turn success into a lie.
                    self._record_after_commit_callback_failure(exc)
            envelope.future.set_result(result)
        for envelope, exc in failures:
            envelope.future.set_exception(exc)
        with self._metrics_lock:
            self._committed_mutations += len(successful)
            self._failed_mutations += len(failures)

    def _record_after_commit_callback_failure(self, _exc: Exception) -> None:
        with self._metrics_lock:
            self._after_commit_callback_failures += 1


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, int((len(values) - 1) * quantile)))
    return round(float(values[index]), 3)
