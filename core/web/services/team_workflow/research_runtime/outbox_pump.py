"""Background pump that leases the research-workflow outbox in production.

``WorkflowCommandService`` commits ``graph_dispatch`` then calls ``wake_worker``.
Tests drain that outbox with ``runtime.run_workers_once()``. Production used to
pass no wake callback and never started a loop, so UI-accepted start_node
commands stayed ``pending`` with ``attempt_count=0``.

Since the Challenge Cup 10-concurrency plan (B3) the pump runs a fixed pool of
N dispatch worker threads (Temporal-style fixed task-queue pollers; default 10,
``VIBELUTION_WORKFLOW_WORKERS`` override via ``runtime_factory``). Each worker
loops claim (outbox lease CAS via ``runtime.claim_and_run_one``) -> execute ->
commit and never prefetches a second action: the lease shards actions between
workers, the B2 heartbeat keeps each lease alive during long invokes, and all
ledger writes funnel through the single writer queue. graph/adapter dispatch
parallelize; fork / receipt / delivery / event / cancel-cleanup and the repair
sweeps stay on ONE serial maintenance thread (their sequence-conflict checks
are not designed for concurrent rewrites of the same run, and the fork worker
writes the checkpoint store that the B4 task owns).

The pump threads are the only places that run LangGraph / adapters.
``wake()`` only releases a semaphore token, so the Ledger writer / HTTP thread
never invokes the graph.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_WORKERS = 10


class WorkflowOutboxPump:
    def __init__(
        self,
        *,
        idle_poll_s: float = 1.0,
        batch_limit: int = 8,
        workers: int = DEFAULT_WORKERS,
    ) -> None:
        self._idle_poll_s = max(0.05, float(idle_poll_s))
        self._batch_limit = max(1, int(batch_limit))
        self._workers = max(1, int(workers))
        self._runtime: Any | None = None
        # One token per wake: each token lets one idle worker run one extra
        # claim pass. Unlike the old single-thread Event this keeps the wake
        # semantics correct with multiple idle workers — every release wakes
        # exactly one claimant (``Event.set`` + ``clear`` would let N-1
        # workers miss the signal), and per-action after-commit hooks keep
        # releasing tokens so a burst of commits keeps the pool saturated.
        self._wake = threading.Semaphore(0)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

    @property
    def worker_count(self) -> int:
        """Configured dispatch worker threads (the maintenance thread is extra)."""
        return self._workers

    @property
    def threads(self) -> tuple[threading.Thread, ...]:
        with self._lock:
            return tuple(self._threads)

    def wake(self) -> None:
        self._wake.release()

    def attach(self, runtime: Any) -> None:
        with self._lock:
            self._runtime = runtime
            if any(thread.is_alive() for thread in self._threads):
                self.wake()
                return
            self._stop.clear()
            self._threads = [
                threading.Thread(
                    target=self._worker_loop,
                    name=f"vibelution-workflow-outbox-{index}",
                    daemon=True,
                )
                for index in range(self._workers)
            ]
            self._threads.append(
                threading.Thread(
                    target=self._maintenance_loop,
                    name="vibelution-workflow-outbox-maintenance",
                    daemon=True,
                )
            )
            for thread in self._threads:
                thread.start()
        self.wake()

    def stop(self, timeout: float = 15.0) -> None:
        """Broadcast stop and join the pool with a bounded total wait.

        B1 keeps this drain inside the singleton lifecycle lock, so the wait
        must stay bounded: workers finish their CURRENT action and exit; a
        worker stuck in a long invoke cannot be interrupted mid-flight, and
        its remaining commits fail closed on the closed ledger store (B2
        owner-CAS fencing), so a leftover daemon thread cannot corrupt state.
        """
        self._stop.set()
        # Broadcast: enough tokens for every worker to wake immediately.
        for _ in range(self._workers + 1):
            self._wake.release()
        current = threading.current_thread()
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._lock:
            threads = list(self._threads)
        for thread in threads:
            if thread is current or not thread.is_alive():
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)
        with self._lock:
            self._runtime = None
            self._threads = []

    def _worker_loop(self) -> None:
        logger.info("research workflow outbox pump worker started")
        try:
            while not self._stop.is_set():
                self._wake.acquire(timeout=self._idle_poll_s)
                if self._stop.is_set():
                    break
                self._drain_until_idle()
        finally:
            logger.info("research workflow outbox pump worker stopped")

    def _drain_until_idle(self) -> None:
        runtime = self._runtime
        if runtime is None:
            return
        try:
            while not self._stop.is_set():
                # Claim-as-you-run: lease exactly ONE action, execute it,
                # only then claim the next. No prefetch, no hoarding.
                if not runtime.claim_and_run_one():
                    break
        except Exception:
            logger.exception("research workflow outbox pump iteration failed")
            self._stop.wait(timeout=0.5)

    def _maintenance_loop(self) -> None:
        logger.info("research workflow outbox maintenance started")
        try:
            while not self._stop.is_set():
                runtime = self._runtime
                maintenance = getattr(runtime, "run_maintenance_once", None)
                if maintenance is not None:
                    try:
                        maintenance(limit=self._batch_limit)
                    except Exception:
                        logger.exception(
                            "research workflow outbox maintenance iteration failed"
                        )
                        self._stop.wait(timeout=0.5)
                self._stop.wait(timeout=self._idle_poll_s)
        finally:
            logger.info("research workflow outbox maintenance stopped")
