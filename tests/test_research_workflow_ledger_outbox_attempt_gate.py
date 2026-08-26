"""Outbox lease attempt gate — an action whose worker process dies (or whose
lease keeps expiring) never reaches the workers' transient-exhaustion branch,
so the ledger itself must stop re-leasing it after MAX lease attempts and
mark it failed exactly once instead of looping forever."""

from __future__ import annotations

import concurrent.futures
import json
from dataclasses import replace
from pathlib import Path

import pytest

from core.research.workflow.ledger import WorkflowLedgerStore
from core.research.workflow.ledger import outbox as outbox_api
from core.research.workflow.ledger.repository import MAX_OUTBOX_LEASE_ATTEMPTS
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    OutboxRecord,
    build_command_record,
    build_outbox_record,
    build_run_record,
    open_ledger_store,
)


def _outbox_record(
    action_id: str,
    *,
    run_id: str = "run-test",
    command_id: str = "cmd-1",
    action_kind: str = "graph_dispatch",
    attempt_count: int = 0,
) -> OutboxRecord:
    return replace(
        build_outbox_record(
            action_id,
            run_id=run_id,
            command_id=command_id,
            action_kind=action_kind,
            available_at_ms=1000,
        ),
        attempt_count=attempt_count,
    )


def _seed(store: WorkflowLedgerStore, *records: OutboxRecord) -> None:
    def mutate(uow):
        uow.repository.insert_run(build_run_record())
        commands = {record.command_id for record in records}
        for index, command_id in enumerate(sorted(commands)):
            uow.repository.insert_command(
                build_command_record(
                    command_id=command_id,
                    idempotency_key=f"cmd-key-{index}",
                )
            )
        for record in records:
            uow.repository.insert_outbox(record)

    store.submit(mutate, force_flush=True).result(timeout=10)


def _get_action(store: WorkflowLedgerStore, action_id: str) -> OutboxRecord:
    record = store.read(lambda repo: repo.get_outbox(action_id))
    assert record is not None
    return record


def test_rows_below_gate_lease_normally(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed(
            store,
            _outbox_record("act-fresh"),
            _outbox_record("act-almost", attempt_count=MAX_OUTBOX_LEASE_ATTEMPTS - 1),
        )
        first = outbox_api.lease_ready_actions(
            store, owner="w1", now_ms=2000, lease_ms=1000
        )
        # 恰好在闸值下方的行仍然可以正常被领取一次。
        assert {item.action_id for item in first} == {"act-fresh", "act-almost"}
        assert all(item.attempt_count <= MAX_OUTBOX_LEASE_ATTEMPTS for item in first)

        expired = outbox_api.lease_ready_actions(
            store, owner="w2", now_ms=4000, lease_ms=1000
        )
        # 此时 act-almost 已到闸值、act-fresh 才第 2 次：只有后者继续被领。
        assert [item.action_id for item in expired] == ["act-fresh"]
    finally:
        store.close()


def test_exhausted_row_fails_once_with_problem_json(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed(store, _outbox_record("act-poison"))
        # 模拟反复崩溃 / 租约超时：每轮正常领取后不 ack，等租约过期再领。
        now_ms = 1000
        for round_index in range(MAX_OUTBOX_LEASE_ATTEMPTS):
            leased = outbox_api.lease_ready_actions(
                store, owner=f"w{round_index}", now_ms=now_ms, lease_ms=1000
            )
            assert [item.action_id for item in leased] == ["act-poison"]
            assert leased[0].attempt_count == round_index + 1
            now_ms += 2000

        exhausted = outbox_api.lease_ready_actions(
            store, owner="w-next", now_ms=now_ms + 2000, lease_ms=1000
        )
        assert exhausted == []

        record = _get_action(store, "act-poison")
        assert record.status == "failed"
        assert record.attempt_count == MAX_OUTBOX_LEASE_ATTEMPTS
        assert record.lease_owner is None and record.lease_expires_at_ms is None
        assert store.list_pending_outbox() == []
        problem = json.loads(str(record.last_problem_json))
        assert problem["code"] == "lease_attempt_exhausted"
        assert problem["maxLeaseAttempts"] == MAX_OUTBOX_LEASE_ATTEMPTS
    finally:
        store.close()


def test_failure_marking_is_idempotent(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed(store, _outbox_record("act-poison", attempt_count=MAX_OUTBOX_LEASE_ATTEMPTS))
        assert outbox_api.lease_ready_actions(
            store, owner="w-first", now_ms=2000, lease_ms=1000
        ) == []
        marked = _get_action(store, "act-poison")
        assert marked.status == "failed"

        repeats = [
            outbox_api.lease_ready_actions(
                store, owner=f"w-{index}", now_ms=3000 + index, lease_ms=1000
            )
            for index in range(4)
        ]
        assert all(batch == [] for batch in repeats)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            batches = [
                future.result()
                for future in [
                    pool.submit(
                        outbox_api.lease_ready_actions,
                        store,
                        owner=f"c-{index}",
                        now_ms=5000,
                        lease_ms=1000,
                    )
                    for index in range(8)
                ]
            ]
        assert all(batch == [] for batch in batches)

        again = _get_action(store, "act-poison")
        # 标记恰好一次：重复与并发扫描都不改写终态证据。
        assert again.status == marked.status
        assert again.updated_at_ms == marked.updated_at_ms
        assert again.last_problem_json == marked.last_problem_json
    finally:
        store.close()


def test_live_lease_at_gate_survives_until_expiry(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed(store, _outbox_record("act-busy", attempt_count=MAX_OUTBOX_LEASE_ATTEMPTS - 1))
        held = outbox_api.lease_ready_actions(
            store, owner="w-live", now_ms=1000, lease_ms=5000
        )
        assert len(held) == 1 and held[0].attempt_count == MAX_OUTBOX_LEASE_ATTEMPTS

        during = outbox_api.lease_ready_actions(
            store, owner="w-other", now_ms=4000, lease_ms=1000
        )
        assert during == []
        live = _get_action(store, "act-busy")
        # 活租约不被闸值提前拆毁，守卫语义保持。
        assert live.status == "leased"
        assert live.lease_owner == "w-live"

        outbox_api.lease_ready_actions(store, owner="w-other", now_ms=8000, lease_ms=1000)
        failed = _get_action(store, "act-busy")
        assert failed.status == "failed"
        assert failed.last_problem_json is not None
        assert json.loads(failed.last_problem_json)["code"] == "lease_attempt_exhausted"
    finally:
        store.close()


def test_sweep_respects_action_kind_filter(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed(
            store,
            _outbox_record("act-graph", action_kind="graph_dispatch", attempt_count=MAX_OUTBOX_LEASE_ATTEMPTS),
            _outbox_record("act-adp", action_kind="adapter_dispatch", attempt_count=MAX_OUTBOX_LEASE_ATTEMPTS),
        )
        outbox_api.lease_ready_actions(
            store,
            owner="adp-worker",
            now_ms=2000,
            lease_ms=1000,
            action_kinds=("adapter_dispatch",),
        )
        assert _get_action(store, "act-adp").status == "failed"
        # 未请求的 kind 不被本次扫描标失败。
        assert _get_action(store, "act-graph").status == "pending"
    finally:
        store.close()


def test_invalid_max_attempts_rejected(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed(store, _outbox_record("act-x"))
        def mutate(uow):
            return uow.repository.lease_outbox_actions(
                owner="w", now_ms=FIXED_NOW_MS, lease_ms=1000, max_attempts=0
            )

        with pytest.raises(ValueError):
            store.submit(mutate, force_flush=True).result(timeout=10)
        assert _get_action(store, "act-x").status == "pending"
    finally:
        store.close()
