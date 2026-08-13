"""Background pump that leases the research-workflow outbox in production.

``WorkflowCommandService`` commits ``graph_dispatch`` then calls ``wake_worker``.
Tests drain that outbox with ``runtime.run_workers_once()``. Production used to
pass no wake callback and never started a loop, so UI-accepted start_node
commands stayed ``pending`` with ``attempt_count=0``.

The pump thread is the only place that runs LangGraph / adapters. ``wake()``
only sets an Event so the Ledger writer / HTTP thread never invokes the graph.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class WorkflowOutboxPump:
    def __init__(self, *, idle_poll_s: float = 1.0, batch_limit: int = 8) -> None:
        self._idle_poll_s = max(0.05, float(idle_poll_s))
        self._batch_limit = max(1, int(batch_limit))
        self._runtime: Any | None = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def wake(self) -> None:
        self._wake.set()

    def attach(self, runtime: Any) -> None:
        with self._lock:
            self._runtime = runtime
            if self._thread is not None and self._thread.is_alive():
                self.wake()
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="vibelution-workflow-outbox",
                daemon=True,
            )
            self._thread.start()
        self.wake()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=15)
        with self._lock:
            self._runtime = None
            self._thread = None

    def _loop(self) -> None:
        logger.info("research workflow outbox pump started")
        try:
            while not self._stop.is_set():
                self._wake.wait(timeout=self._idle_poll_s)
                self._wake.clear()
                if self._stop.is_set():
                    break
                self._drain()
        finally:
            logger.info("research workflow outbox pump stopped")

    def _drain(self) -> None:
        runtime = self._runtime
        if runtime is None:
            return
        try:
            while not self._stop.is_set():
                handled = int(runtime.run_workers_once(limit=self._batch_limit) or 0)
                if handled <= 0:
                    break
        except Exception:
            logger.exception("research workflow outbox pump iteration failed")
            self._stop.wait(timeout=0.5)
