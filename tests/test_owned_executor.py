import time
from threading import Event

import pytest

from core.infrastructure.owned_executor import OwnedThreadPoolExecutor


def test_owned_pool_keeps_running_work_unclosed_and_blocks_reopen():
    pool = OwnedThreadPoolExecutor(max_workers=1, thread_name_prefix="test-owned-pool")
    entered, release = Event(), Event()
    future = pool.submit(lambda: (entered.set(), release.wait(2)))
    try:
        assert entered.wait(1)
        queued = pool.submit(lambda: "must not run")
        result = pool.shutdown_until(time.monotonic() + 0.02)
        assert result["closed"] is False
        assert result["pendingCount"] == 1
        assert result["pendingThreads"]
        assert queued.cancelled()
        assert pool.begin()["opened"] is False
        with pytest.raises(RuntimeError):
            pool.submit(lambda: None)
    finally:
        release.set()
        future.result(timeout=1)
        assert pool.shutdown_until(time.monotonic() + 1)["closed"] is True
    assert pool.begin()["opened"] is True
    assert pool.submit(lambda: "new lifecycle").result(timeout=1) == "new lifecycle"
    pool.shutdown(wait=True)


def test_owned_pool_waits_for_worker_tail_after_future_finishes():
    pool = OwnedThreadPoolExecutor(max_workers=1, thread_name_prefix="test-owned-tail")
    callback_started, release = Event(), Event()
    future = pool.submit(lambda: "done")
    # A done callback runs in the executor thread after Future.result can return.
    def block_callback(_future):
        callback_started.set()
        release.wait(2)

    blocker = Event()
    future = pool.submit(lambda: blocker.wait(2))
    future.add_done_callback(block_callback)
    blocker.set()
    try:
        assert callback_started.wait(1)
        assert future.done()
        result = pool.shutdown_until(time.monotonic() + 0.02)
        assert result["closed"] is False
        assert result["pendingThreads"]
    finally:
        release.set()
        assert pool.shutdown_until(time.monotonic() + 1)["closed"] is True
