"""Small per-lifespan owner for startup tasks and their worker threads."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


def remaining_seconds(deadline: float) -> float:
    return max(0.0, float(deadline) - time.monotonic())


async def run_sync_bounded(
    callback: Callable[..., Any],
    *args: Any,
    deadline_at: float,
    name: str,
    **kwargs: Any,
) -> tuple[bool, Any | None]:
    """Run one sync owner off-loop and wait only until the shared deadline."""

    result: dict[str, Any] = {}
    finished = threading.Event()

    def _run() -> None:
        try:
            result["value"] = callback(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - returned to the async owner
            result["error"] = exc
        finally:
            finished.set()

    worker = threading.Thread(target=_run, name=name, daemon=True)
    worker.start()
    while not finished.is_set():
        remaining = remaining_seconds(deadline_at)
        if remaining <= 0:
            logger.error("Shutdown owner exceeded the shared deadline: %s", name)
            return False, None
        await asyncio.sleep(min(0.02, remaining))

    error = result.get("error")
    if error is not None:
        raise error
    return True, result.get("value")


@dataclass(eq=False)
class _Worker:
    name: str
    stop_requested: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None
    failure_recorded: bool = False
    thread: threading.Thread | None = None
    task: asyncio.Task[Any] | None = None


class StartupJobGroup:
    """Track lifespan-owned async jobs and bounded sync workers."""

    def __init__(self) -> None:
        self._stop_requested = threading.Event()
        self._workers: set[_Worker] = set()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._failed_owner_count = 0
        self._shutdown_deadline: float | None = None

    def should_stop(self) -> bool:
        return self._stop_requested.is_set()

    def start_thread(
        self,
        name: str,
        callback: Callable[..., Any],
        *args: Any,
        stop_keyword: str | None = None,
        **kwargs: Any,
    ) -> asyncio.Task[Any]:
        worker = _Worker(name=name, stop_requested=self._stop_requested)
        self._workers.add(worker)
        loop = asyncio.get_running_loop()

        def _run() -> None:
            try:
                if stop_keyword:
                    worker.result = callback(
                        *args,
                        **kwargs,
                        **{stop_keyword: self._stop_requested.is_set},
                    )
                else:
                    worker.result = callback(*args, **kwargs)
            except BaseException as exc:  # noqa: BLE001 - delivered through the task
                worker.error = exc
            finally:
                worker.finished.set()
                try:
                    loop.call_soon_threadsafe(self._retire_worker, worker)
                except RuntimeError:
                    # The lifespan loop may already be gone if the worker only
                    # exits after the hard-exit watchdog deadline.
                    pass

        worker.thread = threading.Thread(target=_run, name=name, daemon=True)

        async def _wait_for_worker() -> Any:
            try:
                # Preserve the event-loop scheduling boundary of a startup
                # task: creating the owner must not start CPU/import work
                # before the lifespan has yielded to Uvicorn.
                if self.should_stop():
                    worker.finished.set()
                    raise asyncio.CancelledError
                worker.thread.start()
                # The callback signals its result before the Python thread
                # actually exits. Keep the awaitable owned until both finish,
                # so sequential jobs cannot accumulate completed live threads.
                while not worker.finished.is_set() or worker.thread.is_alive():
                    await asyncio.sleep(0.02)
            except asyncio.CancelledError:
                self._stop_requested.set()
                while (
                    (not worker.finished.is_set() or worker.thread.is_alive())
                    and self._shutdown_deadline is not None
                    and remaining_seconds(self._shutdown_deadline) > 0
                ):
                    await asyncio.sleep(0.02)
                raise
            except BaseException as exc:  # noqa: BLE001 - thread-start failure belongs to this owner
                worker.error = exc
                worker.finished.set()
            if worker.error is not None:
                raise worker.error
            return worker.result

        worker.task = asyncio.create_task(_wait_for_worker(), name=name)
        self._track_task(worker.task, worker=worker)
        return worker.task

    def start_async(self, name: str, awaitable: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(awaitable, name=name)
        self._track_task(task)
        return task

    def _track_task(
        self, task: asyncio.Task[Any], *, worker: _Worker | None = None
    ) -> None:
        self._tasks.add(task)

        def _retire(completed: asyncio.Task[Any]) -> None:
            self._tasks.discard(completed)
            if worker is not None:
                self._retire_worker(worker)
                if not completed.cancelled():
                    # Worker failures are counted from worker.error by
                    # _retire_worker. Consume the Task exception as well so
                    # an unawaited owner does not emit asyncio's
                    # "Task exception was never retrieved" warning.
                    try:
                        completed.exception()
                    except BaseException:  # noqa: BLE001 - retirement must not leak callback errors
                        pass
                return
            if completed.cancelled():
                return
            try:
                error = completed.exception()
            except BaseException as exc:  # noqa: BLE001 - retain only bounded failure state
                error = exc
            if error is not None:
                self._failed_owner_count += 1
                logger.warning(
                    "Startup owner failed (%s: %s).",
                    completed.get_name(),
                    type(error).__name__,
                )

        task.add_done_callback(_retire)

    def _retire_worker(self, worker: _Worker) -> None:
        if worker.thread is not None and worker.thread.is_alive():
            asyncio.get_running_loop().call_soon(self._retire_worker, worker)
            return
        self._workers.discard(worker)
        if worker.error is not None and not worker.failure_recorded:
            self._failed_owner_count += 1
            logger.warning("Startup worker failed (%s: %s).", worker.name, type(worker.error).__name__)
            worker.failure_recorded = True
        if worker.task is not None and worker.task.done():
            worker.error = None
            worker.result = None

    async def run_sync(
        self,
        name: str,
        callback: Callable[..., Any],
        *args: Any,
        stop_keyword: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run sync work on a tracked daemon worker from an async owner."""

        if self.should_stop():
            raise asyncio.CancelledError
        task = self.start_thread(
            name,
            callback,
            *args,
            stop_keyword=stop_keyword,
            **kwargs,
        )
        return await task

    def request_stop(self) -> None:
        self._stop_requested.set()

    async def shutdown(self, *, deadline: float) -> dict[str, Any]:
        self._shutdown_deadline = deadline
        self.request_stop()
        tasks = tuple(self._tasks)
        for task in tasks:
            if not task.done():
                task.cancel()

        pending: set[asyncio.Task[Any]] = {task for task in tasks if not task.done()}
        while pending:
            remaining = remaining_seconds(deadline)
            if remaining <= 0:
                break
            try:
                _, pending = await asyncio.wait(pending, timeout=min(0.05, remaining))
            except asyncio.CancelledError:
                # A repeated cancellation must not prevent joining the owners.
                self.request_stop()
                continue

        pending_names = sorted(task.get_name() for task in pending)
        while remaining_seconds(deadline) > 0:
            for worker in tuple(self._workers):
                if worker.thread is None or not worker.thread.is_alive():
                    self._retire_worker(worker)
            unfinished = any(
                worker.thread is not None and worker.thread.is_alive()
                for worker in self._workers
            )
            if not unfinished:
                break
            try:
                await asyncio.sleep(min(0.02, remaining_seconds(deadline)))
            except asyncio.CancelledError:
                self.request_stop()
        try:
            # Flush task done callbacks queued by the worker/task joins above.
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            self.request_stop()
        unfinished_workers = sorted(
            worker.name
            for worker in self._workers
            if worker.thread is not None and worker.thread.is_alive()
        )
        failed_owner_count = self._failed_owner_count
        if pending_names or unfinished_workers or failed_owner_count:
            logger.error(
                "Startup owners did not close cleanly (tasks=%s workers=%s failed=%s).",
                pending_names,
                unfinished_workers,
                failed_owner_count,
            )
        return {
            "closed": not pending_names and not unfinished_workers and not failed_owner_count,
            "pendingTasks": pending_names,
            "pendingWorkers": unfinished_workers,
            "failedOwnerCount": failed_owner_count,
        }
