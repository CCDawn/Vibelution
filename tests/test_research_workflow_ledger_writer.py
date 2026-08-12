"""T1 RED: Ledger writer — single writer, transactions, backpressure,
after-commit visibility (commit 前不发布)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.ledger import WorkflowLedgerBackpressureError
from tests._support.workflow_ledger_helpers import (
    build_command_record,
    build_event_record,
    build_run_record,
    open_ledger_store,
)


def test_submit_commits_atomically(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        def mutate(uow):
            uow.repository.insert_run(build_run_record())
            uow.repository.insert_event(build_event_record(sequence=1))

        store.submit(mutate, force_flush=True).result(timeout=10)
        run = store.get_run("run-test")
        assert run is not None
        assert store.latest_event_sequence("run-test") == 1
    finally:
        store.close()


def test_failed_envelope_rolls_back_entire_group(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        def bad(uow):
            uow.repository.insert_run(build_run_record(run_id="run-bad"))
            raise ValueError("boom")

        with pytest.raises(ValueError):
            store.submit(bad, force_flush=True).result(timeout=10)
        assert store.get_run("run-bad") is None
    finally:
        store.close()


def test_savepoint_isolates_single_failure_within_batch(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        def ok(uow):
            uow.repository.insert_run(build_run_record(run_id="run-ok"))

        def bad(uow):
            raise ValueError("boom")

        ok_future = store.submit(ok, force_flush=False)
        bad_future = store.submit(bad, force_flush=False)
        flush_future = store.submit(
            lambda uow: uow.repository.insert_run(build_run_record(run_id="run-flush")),
            force_flush=True,
        )
        ok_future.result(timeout=10)
        with pytest.raises(ValueError):
            bad_future.result(timeout=10)
        flush_future.result(timeout=10)
        assert store.get_run("run-ok") is not None
        assert store.get_run("run-flush") is not None
    finally:
        store.close()


def test_after_commit_only_runs_after_commit(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        published: list[str] = []

        def mutate(uow):
            uow.repository.insert_run(build_run_record())
            assert published == [], "after-commit 不得在事务内执行"
            uow.after_commit(lambda: published.append("run-test"))

        store.submit(mutate, force_flush=True).result(timeout=10)
        assert published == ["run-test"]
    finally:
        store.close()


def test_after_commit_skipped_on_failure(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        published: list[str] = []

        def mutate(uow):
            uow.after_commit(lambda: published.append("should-not-run"))
            raise ValueError("boom")

        with pytest.raises(ValueError):
            store.submit(mutate, force_flush=True).result(timeout=10)
        assert published == []
    finally:
        store.close()


def test_writer_queue_backpressure(tmp_path: Path) -> None:
    store = open_ledger_store(
        tmp_path / "ledger.sqlite3",
        queue_size=2,
        enqueue_timeout_ms=50,
    )
    try:
        import threading
        import time

        release = threading.Event()

        def blocker(uow):
            release.wait(timeout=5)

        first = store.submit(blocker, force_flush=False)
        second = store.submit(blocker, force_flush=False)
        time.sleep(0.3)
        # worker 已被 blocker 占用；剩余队列容量 2，第 3 个提交必须 backpressure。
        store.submit(
            lambda uow: uow.repository.insert_run(build_run_record(run_id="run-late-1")),
            force_flush=False,
        )
        store.submit(
            lambda uow: uow.repository.insert_run(build_run_record(run_id="run-late-2")),
            force_flush=False,
        )
        with pytest.raises(WorkflowLedgerBackpressureError):
            store.submit(
                lambda uow: uow.repository.insert_run(build_run_record(run_id="run-late-3")),
                force_flush=False,
            )
        release.set()
        first.result(timeout=10)
        second.result(timeout=10)
    finally:
        store.close()


def test_command_and_event_same_transaction(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        def mutate(uow):
            uow.repository.insert_run(build_run_record(run_version=1))
            uow.repository.insert_command(build_command_record())
            uow.repository.insert_event(build_event_record(sequence=1))

        store.submit(mutate, force_flush=True).result(timeout=10)
        command = store.get_command_by_idempotency("run-test", "key-1")
        assert command is not None
        assert command.status == "accepted"
    finally:
        store.close()
