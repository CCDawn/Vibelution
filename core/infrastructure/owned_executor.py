"""Thread pools whose admission, futures and physical workers share an owner."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any


class OwnedThreadPoolExecutor:
    """Keep shutdown bounded without mistaking Future completion for thread exit."""

    def __init__(self, max_workers: int, thread_name_prefix: str = "owned-worker") -> None:
        self._max_workers = max_workers
        self._name = thread_name_prefix
        self._lock = threading.RLock()
        self._executor = self._new_executor()
        self._futures: set[Future[Any]] = set()
        self._closed = False
        self._failed: set[str] = set()

    def _new_executor(self) -> ThreadPoolExecutor:
        return ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix=self._name)

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future[Any]:
        with self._lock:
            if self._closed:
                raise RuntimeError(f"{self._name} lifecycle is shutting down")
            future = self._executor.submit(fn, *args, **kwargs)
            self._futures.add(future)
            future.add_done_callback(self._finished)
            return future

    def _finished(self, future: Future[Any]) -> None:
        with self._lock:
            self._futures.discard(future)

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        with self._lock:
            self._closed = True
            executor = self._executor
        try:
            executor.shutdown(wait=wait, cancel_futures=cancel_futures)
            with self._lock:
                self._failed.clear()
        except BaseException as exc:
            with self._lock:
                self._failed.add(type(exc).__name__)
            raise

    def stop_admission(self, *, cancel_futures: bool = True) -> None:
        self.shutdown(wait=False, cancel_futures=cancel_futures)

    def _snapshot_locked(self) -> dict[str, Any]:
        # CPython's executor retains its physical worker handles after shutdown.
        # This check also covers callbacks still running after Future.done().
        threads = [thread.name for thread in self._executor._threads if thread.is_alive()]
        pending = sum(not future.done() for future in self._futures)
        return {
            "closed": self._closed and not pending and not threads and not self._failed,
            "pendingCount": pending,
            "pendingThreads": sorted(threads),
            "failed": sorted(self._failed),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_locked()

    def shutdown_until(self, deadline: float) -> dict[str, Any]:
        self.stop_admission()
        with self._lock:
            threads = tuple(self._executor._threads)
        for thread in threads:
            if thread is threading.current_thread():
                continue
            thread.join(timeout=max(0.0, float(deadline) - time.monotonic()))
        return self.snapshot()

    def begin(self) -> dict[str, Any]:
        with self._lock:
            if not self._closed:
                return {"opened": True, "recreated": False}
            result = self._snapshot_locked()
            if not result["closed"]:
                return {"opened": False, "recreated": False, **result}
            self._executor = self._new_executor()
            self._futures.clear()
            self._failed.clear()
            self._closed = False
            return {"opened": True, "recreated": True}
