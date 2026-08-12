"""P1-7 RED: reader handle leak on close (Windows WinError 32).

A read-only query holds a pooled reader connection. store.close() must
close every pooled reader so the SQLite file can be deleted immediately
(the Launcher restart / test cleanup / migration path). Closing twice is
idempotent, and the store can be reopened at the same path.
"""

from __future__ import annotations

import threading
from pathlib import Path

from tests._support.workflow_ledger_helpers import (
    build_event_record,
    build_run_record,
    open_ledger_store,
)


def test_close_releases_pooled_reader_connections(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    store = open_ledger_store(path)
    store.submit(
        lambda uow: uow.repository.insert_run(build_run_record()),
        force_flush=True,
    ).result(timeout=10)

    # 触发多个线程的 pooled reader 连接。
    barrier = threading.Barrier(4)
    errors: list[BaseException] = []

    def read() -> None:
        try:
            barrier.wait(timeout=10)
            for _ in range(5):
                store.get_run("run-test")
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=read) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors
    assert store.latest_event_sequence("run-test") == 0

    store.close()

    # Windows: 没有进程句柄占用时文件可删除；不满足则证明句柄泄漏。
    unlink_error: BaseException | None = None
    try:
        path.unlink()
    except OSError as exc:  # pragma: no cover - WinError 32 leak signal
        unlink_error = exc
    assert unlink_error is None, f"file still locked after close: {unlink_error}"


def test_close_is_idempotent_and_store_can_reopen(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    store = open_ledger_store(path)
    store.submit(
        lambda uow: uow.repository.insert_run(build_run_record(run_id="run-a")),
        force_flush=True,
    ).result(timeout=10)
    store.get_run("run-a")
    store.close()
    store.close()

    reopened = open_ledger_store(path)
    try:
        assert reopened.get_run("run-a") is not None
        reopened.submit(
            lambda uow: uow.repository.insert_event(
                build_event_record(sequence=1, run_id="run-a")
            ),
            force_flush=True,
        ).result(timeout=10)
        assert reopened.latest_event_sequence("run-a") == 1
    finally:
        reopened.close()


def test_close_after_only_reader_access_then_reopen_writes(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    store = open_ledger_store(path, read_pool_capacity=1)
    store.submit(
        lambda uow: uow.repository.insert_run(build_run_record(run_id="run-r")),
        force_flush=True,
    ).result(timeout=10)
    store.get_run("run-r")
    store.close()

    path.unlink()
    assert not path.exists()

    store = open_ledger_store(path)
    try:
        store.submit(
            lambda uow: uow.repository.insert_run(build_run_record(run_id="run-w")),
            force_flush=True,
        ).result(timeout=10)
        assert store.get_run("run-w") is not None
    finally:
        store.close()
