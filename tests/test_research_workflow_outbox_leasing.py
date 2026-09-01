"""T3 RED: outbox leasing — atomic lease, single-flight, expiry re-lease,
requeue / fail / ack transitions."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.ledger import WorkflowLedgerStore
from core.research.workflow.ledger import outbox as outbox_api
from tests._support.workflow_ledger_helpers import (
    build_outbox_record,
    build_run_record,
    open_ledger_store,
)


def _seed_outbox(store: WorkflowLedgerStore, run_id: str = "run-test", count: int = 3) -> list[str]:
    from tests._support.workflow_ledger_helpers import build_command_record

    def mutate(uow):
        uow.repository.insert_run(build_run_record(run_id=run_id))
        for index in range(count):
            command_id = f"cmd-{index}"
            uow.repository.insert_command(
                build_command_record(
                    command_id=command_id,
                    run_id=run_id,
                    idempotency_key=f"cmd-key-{index}",
                )
            )
            uow.repository.insert_outbox(
                build_outbox_record(
                    action_id=f"act-{index}",
                    run_id=run_id,
                    command_id=command_id,
                    idempotency_key=f"outbox:{index}",
                    available_at_ms=1000,
                )
            )

    store.submit(mutate, force_flush=True).result(timeout=10)
    return [f"act-{index}" for index in range(count)]


def test_lease_claims_atomically(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        action_ids = _seed_outbox(store)
        leased = outbox_api.lease_ready_actions(
            store, owner="worker-1", now_ms=1000, limit=8
        )
        assert {item.action_id for item in leased} == set(action_ids)
        for item in leased:
            assert item.status == "leased"
            assert item.lease_owner == "worker-1"
            assert item.attempt_count == 1
        # 已领取的不能被再次领取。
        again = outbox_api.lease_ready_actions(store, owner="worker-2", now_ms=1000, limit=8)
        assert again == []
    finally:
        store.close()


def test_lease_respects_limit_and_kind_filter(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_outbox(store, count=4)
        leased = outbox_api.lease_ready_actions(store, owner="w", now_ms=1000, limit=2)
        assert len(leased) == 2
        graph = outbox_api.lease_ready_actions(
            store,
            owner="w2",
            now_ms=1000,
            limit=8,
            action_kinds=("adapter_dispatch",),
        )
        assert graph == []
    finally:
        store.close()


def test_lease_prioritizes_foreground_and_caps_background_sideflow(
    tmp_path: Path,
) -> None:
    """A sideflow backlog cannot take the foreground worker capacity."""

    from core.research.workflow.knowledge_sideflow_definition import (
        KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
    )
    from tests._support.workflow_ledger_helpers import build_command_record

    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        def mutate(uow) -> None:
            uow.repository.insert_run(
                build_run_record(
                    run_id="run-foreground",
                    workflow_id="challenge-cup-research",
                )
            )
            uow.repository.insert_run(
                build_run_record(
                    run_id="run-background",
                    workflow_id=KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
                    parent_run_id="run-foreground",
                )
            )
            for index in range(8):
                command_id = f"cmd-background-{index}"
                uow.repository.insert_command(
                    build_command_record(
                        command_id=command_id,
                        run_id="run-background",
                        idempotency_key=command_id,
                    )
                )
                uow.repository.insert_outbox(
                    build_outbox_record(
                        action_id=f"a-background-{index:03d}",
                        run_id="run-background",
                        command_id=command_id,
                        available_at_ms=1000,
                    )
                )
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-foreground",
                    run_id="run-foreground",
                    idempotency_key="cmd-foreground",
                )
            )
            # Alphabetically last on purpose: the historical FIFO query
            # chooses a-background-* before this foreground action.
            uow.repository.insert_outbox(
                build_outbox_record(
                    action_id="z-foreground",
                    run_id="run-foreground",
                    command_id="cmd-foreground",
                    available_at_ms=1000,
                )
            )

        store.submit(mutate, force_flush=True).result(timeout=10)
        leased = outbox_api.lease_ready_actions(
            store,
            owner="worker",
            now_ms=1000,
            limit=8,
            action_kinds=("graph_dispatch",),
            background_workflow_ids=(KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,),
            background_limit=2,
        )

        assert leased[0].action_id == "z-foreground"
        assert [item.run_id for item in leased].count("run-background") == 2
        assert len(leased) == 3
    finally:
        store.close()


def test_expired_lease_is_releasable(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_outbox(store, count=1)
        first = outbox_api.lease_ready_actions(
            store, owner="w1", now_ms=1000, lease_ms=100
        )
        assert len(first) == 1
        blocked = outbox_api.lease_ready_actions(store, owner="w2", now_ms=1050, lease_ms=100)
        assert blocked == []
        released = outbox_api.lease_ready_actions(store, owner="w2", now_ms=1100, lease_ms=100)
        assert len(released) == 1
        assert released[0].attempt_count == 2
    finally:
        store.close()


def test_ack_requires_lease_owner(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_outbox(store, count=1)
        outbox_api.lease_ready_actions(store, owner="w1", now_ms=1000)
        assert outbox_api.ack_action(store, "act-0", "wrong-owner", 2000) is False
        assert outbox_api.ack_action(store, "act-0", "w1", 2000) is True
        record = store.get_command_by_idempotency("run-test", "x")
        assert record is None
    finally:
        store.close()


def test_lease_can_be_renewed_only_by_current_owner(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_outbox(store, count=1)
        outbox_api.lease_ready_actions(store, owner="w1", now_ms=1000, lease_ms=100)
        assert outbox_api.renew_lease(
            store, "act-0", "w1", now_ms=1050, lease_ms=200
        ) is True
        assert outbox_api.renew_lease(
            store, "act-0", "wrong-owner", now_ms=1100, lease_ms=200
        ) is False
        blocked = outbox_api.lease_ready_actions(
            store, owner="w2", now_ms=1150, lease_ms=100
        )
        assert blocked == []
        released = outbox_api.lease_ready_actions(
            store, owner="w2", now_ms=1250, lease_ms=100
        )
        assert len(released) == 1
    finally:
        store.close()


def test_requeue_with_retry_delay(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_outbox(store, count=1)
        outbox_api.lease_ready_actions(store, owner="w1", now_ms=1000)
        assert outbox_api.requeue_action(
            store, "act-0", "w1", 1000, retry_at_ms=5000, problem_json='{"code":"transient"}'
        )
        not_yet = outbox_api.lease_ready_actions(store, owner="w2", now_ms=3000)
        assert not_yet == []
        ready = outbox_api.lease_ready_actions(store, owner="w2", now_ms=5000)
        assert len(ready) == 1
        assert ready[0].attempt_count == 2
    finally:
        store.close()


def test_fail_marks_action_failed(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_outbox(store, count=1)
        outbox_api.lease_ready_actions(store, owner="w1", now_ms=1000)
        assert outbox_api.fail_action(
            store, "act-0", "w1", 1000, problem_json='{"code":"non_recoverable"}'
        )
        assert store.list_pending_outbox() == []
    finally:
        store.close()


def test_lease_is_atomic_under_concurrency(tmp_path: Path) -> None:
    import concurrent.futures

    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        action_ids = _seed_outbox(store, count=10)

        def lease(worker: int):
            return outbox_api.lease_ready_actions(
                store, owner=f"w{worker}", now_ms=1000, limit=10
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = [future.result() for future in [pool.submit(lease, i) for i in range(8)]]

        claimed = {item.action_id for batch in results for item in batch}
        assert claimed == set(action_ids)
        assert sum(len(batch) for batch in results) == 10
        # 每个 action 恰好被领取一次（单写入者串行化 + 条件 UPDATE）。
        counts: dict[str, int] = {}
        for batch in results:
            for item in batch:
                counts[item.action_id] = counts.get(item.action_id, 0) + 1
        assert all(count == 1 for count in counts.values())
    finally:
        store.close()
