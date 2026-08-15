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


# ---------------------------------------------------------------------------
# 提交成功语义：COMMIT 失败注入 / close 排空 / close 超时结算 / 时序


class _FakeCommitError(RuntimeError):
    pass


class _FakeConnection:
    def __init__(self, database: _FakeDatabase) -> None:
        self._database = database
        self.closed = False
        self.executed: list[str] = []

    def execute(self, sql: str) -> None:
        self.executed.append(sql)
        if (
            sql == "COMMIT"
            and self._database.fail_commits_remaining > 0
        ):
            self._database.fail_commits_remaining -= 1
            raise _FakeCommitError("injected commit failure")

    def close(self) -> None:
        self.closed = True


class _FakeDatabase:
    def __init__(self, *, fail_on_open: bool = False, fail_commits: int = 0) -> None:
        self.fail_on_open = fail_on_open
        self.fail_commits_remaining = fail_commits
        self.connections: list[_FakeConnection] = []

    def open_writer(self) -> _FakeConnection:
        if self.fail_on_open:
            raise RuntimeError("injected open_writer failure")
        connection = _FakeConnection(self)
        self.connections.append(connection)
        return connection


def _build_writer(database, **overrides):
    from core.research.workflow.ledger.writer import WorkflowLedgerWriter

    return WorkflowLedgerWriter(
        database,
        queue_size=int(overrides.get("queue_size", 64)),
        enqueue_timeout_ms=int(overrides.get("enqueue_timeout_ms", 100)),
        poll_interval_s=float(overrides.get("poll_interval_s", 0.01)),
    )


def test_commit_failure_fails_whole_batch_and_skips_after_commit() -> None:
    database = _FakeDatabase(fail_commits=1)
    writer = _build_writer(database)
    writer.start()
    try:
        published: list[str] = []

        def first(uow):
            uow.after_commit(lambda: published.append("first"))
            return "first-ok"

        def second(uow):
            uow.after_commit(lambda: published.append("second"))
            return "second-ok"

        def third(uow):
            uow.after_commit(lambda: published.append("third"))
            return "third-ok"

        first_future = writer.submit(first, force_flush=False)
        second_future = writer.submit(second, force_flush=False)
        # force_flush 将 [first, second] 作为一批提交；third 单独一批。
        third_future = writer.submit(third, force_flush=True)

        with pytest.raises(_FakeCommitError):
            first_future.result(timeout=10)
        with pytest.raises(_FakeCommitError):
            second_future.result(timeout=10)
        assert third_future.result(timeout=10) == "third-ok"
        # COMMIT 失败的一批不得执行 after_commit；成功批次执行。
        assert published == ["third"]
    finally:
        writer.close()


def test_close_drains_accepted_queue_in_fifo_order(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    import threading
    import time

    release = threading.Event()
    processed: list[str] = []

    def blocker(uow):
        release.wait(timeout=10)

    store.submit(blocker, force_flush=False)
    time.sleep(0.3)

    for run_id in ("run-a", "run-b"):
        def mutate(uow, run_id=run_id):
            uow.repository.insert_run(build_run_record(run_id=run_id))
            processed.append(run_id)

        store.submit(mutate, force_flush=False)

    close_result: list[bool] = []

    def do_close():
        store.close()
        close_result.append(True)

    closer = threading.Thread(target=do_close)
    closer.start()
    time.sleep(0.2)
    assert not close_result, "close 必须在排空已接收任务后才返回"
    release.set()
    closer.join(timeout=15)
    assert close_result, "close 未返回"
    assert processed == ["run-a", "run-b"]


def test_close_timeout_abandons_blocked_mutation_without_late_commit() -> None:
    from core.research.workflow.ledger import WorkflowLedgerClosedError

    database = _FakeDatabase()
    writer = _build_writer(database, poll_interval_s=0.01)
    writer.start()
    import threading
    import time

    release = threading.Event()
    published: list[str] = []

    def blocker(uow):
        uow.after_commit(lambda: published.append("blocker-committed"))
        release.wait(timeout=30)

    blocked_future = writer.submit(blocker, force_flush=False)
    # 确保 writer 已取走 blocker 并阻塞在 mutation 内。
    time.sleep(0.3)
    writer.close(timeout=0.2)

    # 确定性顺序：close 超时 → 当前批次 Future 已标记失败 → 调用方才释放阻塞。
    with pytest.raises(WorkflowLedgerClosedError):
        blocked_future.result(timeout=1)

    release.set()
    writer._thread.join(timeout=10)
    assert not writer._thread.is_alive()

    commits = [
        sql
        for connection in database.connections
        for sql in connection.executed
        if sql == "COMMIT"
    ]
    assert commits == [], "close 超时后阻塞 mutation 不得执行 late COMMIT"
    assert published == [], "close 超时后不得执行 after_commit callback"


def test_close_wins_race_fails_future_before_commit() -> None:
    """close-wins：close 超时先取得原子边界 → Future 失败、事务不提交、
    after_commit 不执行（check-then-act 竞态已被线性化）。"""
    from core.research.workflow.ledger import WorkflowLedgerClosedError

    database = _FakeDatabase()
    writer = _build_writer(database, poll_interval_s=0.01)
    writer.start()
    import threading
    import time

    entered = threading.Event()
    release = threading.Event()
    published: list[str] = []

    def blocker(uow):
        uow.after_commit(lambda: published.append("blocker-committed"))
        entered.set()
        release.wait(timeout=30)

    blocked_future = writer.submit(blocker, force_flush=False)
    assert entered.wait(timeout=5), "writer 必须已进入 mutation"

    writer.close(timeout=0.2)

    with pytest.raises(WorkflowLedgerClosedError):
        blocked_future.result(timeout=1)

    release.set()
    writer._thread.join(timeout=10)
    assert not writer._thread.is_alive()

    commits = [
        sql
        for connection in database.connections
        for sql in connection.executed
        if sql == "COMMIT"
    ]
    assert commits == [], "close-wins: 事务不得提交"
    assert published == [], "close-wins: after_commit 不得执行"


def test_commit_wins_race_commits_and_settles_success() -> None:
    """commit-wins：writer 已进入 COMMIT 时 close 必须等待 → 事务提交且
    Future 成功，不出现 committed-but-failed。"""
    import threading
    import time

    commit_started = threading.Event()
    allow_commit = threading.Event()

    class _BlockingCommitConnection:
        def __init__(self) -> None:
            self.executed: list[str] = []
            self.closed = False

        def execute(self, sql: str) -> None:
            self.executed.append(sql)
            if sql == "COMMIT":
                commit_started.set()
                allow_commit.wait(timeout=30)

        def close(self) -> None:
            self.closed = True

    class _BlockingCommitDatabase:
        def __init__(self) -> None:
            self.connections: list[_BlockingCommitConnection] = []

        def open_writer(self) -> _BlockingCommitConnection:
            connection = _BlockingCommitConnection()
            self.connections.append(connection)
            return connection

    database = _BlockingCommitDatabase()
    writer = _build_writer(database, poll_interval_s=0.01)
    writer.start()
    try:
        published: list[str] = []

        def mutate(uow):
            uow.after_commit(lambda: published.append("committed"))
            return "ok"

        future = writer.submit(mutate, force_flush=False)
        assert commit_started.wait(timeout=5), "writer 必须已进入 COMMIT"

        close_results: list[bool] = []

        def do_close():
            writer.close(timeout=0.2)
            close_results.append(True)

        closer = threading.Thread(target=do_close)
        closer.start()
        time.sleep(0.3)
        assert not close_results, "close 必须等待在途 COMMIT 完成后再标记超时"

        allow_commit.set()
        closer.join(timeout=10)
        assert close_results, "close 未返回"

        assert future.result(timeout=1) == "ok", "committed-but-failed: Future 不得失败"
        assert published == ["committed"], "commit-wins: after_commit 必须执行"

        commits = [
            sql
            for connection in database.connections
            for sql in connection.executed
            if sql == "COMMIT"
        ]
        assert commits == ["COMMIT"], "commit-wins: 事务必须提交且仅提交一次"
    finally:
        allow_commit.set()
        writer._thread.join(timeout=10)
        writer.close()


def test_close_timeout_settles_remaining_futures(tmp_path: Path) -> None:
    from core.research.workflow.ledger import WorkflowLedgerClosedError
    from core.research.workflow.ledger.database import WorkflowLedgerDatabase

    database = WorkflowLedgerDatabase(
        tmp_path / "ledger.sqlite3", read_pool_capacity=1
    )
    database.initialize()
    writer = _build_writer(database, poll_interval_s=0.01)
    writer.start()
    import threading
    import time

    release = threading.Event()

    def blocker(uow):
        release.wait(timeout=30)

    blocked_future = writer.submit(blocker, force_flush=False)
    time.sleep(0.2)
    queued_future = writer.submit(lambda uow: "queued-ok", force_flush=False)

    writer.close(timeout=0.5)

    with pytest.raises(WorkflowLedgerClosedError):
        blocked_future.result(timeout=1)
    with pytest.raises(WorkflowLedgerClosedError):
        queued_future.result(timeout=1)

    release.set()
    writer._thread.join(timeout=10)
    assert not writer._thread.is_alive()
    database.close()


def test_future_not_done_before_commit(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    import threading
    import time

    release = threading.Event()
    store.submit(lambda uow: release.wait(timeout=10), force_flush=False)
    time.sleep(0.3)

    observed: list[bool] = []

    def first(uow):
        uow.repository.insert_run(build_run_record(run_id="run-timing-a"))
        return "first-ok"

    def second(uow):
        observed.append(first_future.done())
        return "second-ok"

    first_future = store.submit(first, force_flush=False)
    second_future = store.submit(second, force_flush=False)
    release.set()
    try:
        assert first_future.result(timeout=10) == "first-ok"
        assert second_future.result(timeout=10) == "second-ok"
        assert observed == [False], "同一批内前一 mutation 的 Future 不得在 COMMIT 前完成"
    finally:
        store.close()


def test_close_waits_for_in_flight_submit_put_and_settles_accepted_envelope() -> None:
    """submit 已通过 accept 检查后，close 必须等到 put 完成并结算该 envelope。

    回归：put 若在 accept_lock 外，close 会排空空队列并让 writer 退出，
    随后 put 把 future 丢进无消费者队列。
    """
    import queue
    import threading
    import time

    from core.research.workflow.ledger.writer import _Envelope, _WAKEUP

    database = _FakeDatabase()
    writer = _build_writer(database, poll_interval_s=0.01, enqueue_timeout_ms=2000)
    writer.start()
    put_started = threading.Event()
    allow_put = threading.Event()
    original_queue = writer._queue

    def gated_put(item, block=True, timeout=None):
        if item is not _WAKEUP and isinstance(item, _Envelope):
            put_started.set()
            assert allow_put.wait(timeout=30), "test gate did not release put"
        return queue.Queue.put(original_queue, item, block=block, timeout=timeout)

    writer._queue.put = gated_put  # type: ignore[method-assign]
    submit_box: dict[str, object] = {}

    def do_submit() -> None:
        submit_box["future"] = writer.submit(lambda uow: "late-ok", force_flush=False)

    submitter = threading.Thread(target=do_submit, name="late-submit")
    submitter.start()
    assert put_started.wait(timeout=5), "submit 必须已进入 put"

    close_done = threading.Event()

    def do_close() -> None:
        writer.close(timeout=2)
        close_done.set()

    closer = threading.Thread(target=do_close, name="close-during-put")
    closer.start()
    try:
        time.sleep(0.3)
        assert not close_done.is_set(), "close 不得在 in-flight submit.put 完成前返回"
    finally:
        allow_put.set()
        submitter.join(timeout=5)
        closer.join(timeout=10)
    assert close_done.is_set(), "close 未返回"
    future = submit_box.get("future")
    assert future is not None
    assert future.result(timeout=2) == "late-ok"
    writer._thread.join(timeout=5)
    assert not writer._thread.is_alive()


def test_writer_start_failure_exposed_synchronously() -> None:
    from core.research.workflow.ledger import WorkflowLedgerUnavailableError

    database = _FakeDatabase(fail_on_open=True)
    writer = _build_writer(database)
    with pytest.raises(WorkflowLedgerUnavailableError):
        writer.start()
    with pytest.raises(WorkflowLedgerUnavailableError):
        writer.submit(lambda uow: None, force_flush=True)
    writer.close()
    writer._thread.join(timeout=5)
    assert not writer._thread.is_alive()
    # 启动失败后 close 不报错且无残留 pending future。
    assert database.connections == []
