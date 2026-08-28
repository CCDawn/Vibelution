"""Cross-run handoff delivery: at-least-once event_publish + idempotent parent.

Covers Task 3's durable cross-run boundary:
- boundary ①: child terminal commit left a pending ``event_publish`` row; the
  worker delivers it to the parent and the parent absorbs exactly once;
- boundary ②: a worker crashed while holding the lease; once the lease
  expires another worker re-leases and delivers once;
- boundary ③: the parent-side write landed but the ACK was lost; redelivery
  dedupes on the deterministic event id without a second parent event;
- undecodable payloads and exhausted lease attempts dead-letter with
  ``reconciliation_required`` on the producing child run;
- a failed/cancelled child never fakes a handoff (``blocked`` is not
  terminal).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.web.services.team_workflow.research_runtime.event_publish_worker import (
    EventPublishWorker,
)
from core.web.services.team_workflow.research_runtime.knowledge_sideflow_service import (
    absorb_knowledge_result,
    record_knowledge_sideflow_child_failure,
)
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS
from tests.test_knowledge_sideflow_run import (
    _accept_handoff,
    _invoke,
    _invocation_row,
    _outbox_rows,
    _seed_parent,
    _walk_child_to_handoff,
)


@pytest.fixture(autouse=True)
def _isolated_registry():
    from core.research.workflow.definition_registry import reset_registry_for_tests

    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


def _child_with_pending_event(tmp_path: Path):
    """Drive a child to its terminal commit; returns (harness, ids, payload)."""
    harness = _make_harness(tmp_path)
    _seed_parent(harness)
    result = _invoke(harness)
    child_run_id = result["childRunId"]
    pending = _walk_child_to_handoff(harness, child_run_id)
    _accept_handoff(harness, child_run_id, pending)
    rows = _outbox_rows(harness, child_run_id, "event_publish")
    assert len(rows) == 1 and rows[0][1] == "pending"
    payload = json.loads(rows[0][2])
    return harness, result, child_run_id, payload


def _make_harness(tmp_path: Path):
    from tests._support.graph_helpers import GraphHarness

    return GraphHarness(tmp_path)


def _parent_absorbed_events(harness, parent_run_id: str = "run-parent"):
    return [
        event
        for event in harness.commands.store.list_events(parent_run_id)
        if event.event_type == "knowledge_result_absorbed"
    ]


def _outbox_status(harness, action_id: str):
    record = harness.commands.store.submit(
        lambda uow: uow.repository.get_outbox(action_id),
        force_flush=True,
    ).result(timeout=10)
    assert record is not None
    return record


def _event_publish_action_id(harness, child_run_id: str) -> str:
    rows = _outbox_rows(harness, child_run_id, "event_publish")
    assert len(rows) == 1
    return str(rows[0][0])


def test_boundary_1_worker_delivers_pending_event_to_parent(tmp_path: Path) -> None:
    harness, result, child_run_id, payload = _child_with_pending_event(tmp_path)
    try:
        store = harness.commands.store
        parent_before = store.get_run("run-parent")
        attempts_before = store.submit(
            lambda uow: uow.repository.list_attempts("run-parent"),
            force_flush=True,
        ).result(timeout=10)
        readiness_calls: list[int] = []
        worker = EventPublishWorker(
            store=store,
            now_provider=lambda: FIXED_NOW_MS + 1000,
            notify_readiness=lambda: readiness_calls.append(1),
        )
        handled = worker.run_once()
        assert handled == 1

        action_id = _event_publish_action_id(harness, child_run_id)
        assert _outbox_status(harness, action_id).status == "succeeded"

        absorbed = _parent_absorbed_events(harness)
        assert len(absorbed) == 1
        event_payload = json.loads(absorbed[0].payload_json)
        assert event_payload["invocationId"] == result["invocation"].invocation_id
        assert event_payload["producerRunId"] == child_run_id
        assert event_payload["consumerRunId"] == "run-parent"
        assert event_payload["packageContentHash"] == payload["packageContentHash"]

        # The consumer appends ONE event and never rewrites parent progress.
        parent_after = store.get_run("run-parent")
        assert parent_after.run_version == parent_before.run_version
        assert parent_after.status == parent_before.status
        assert parent_after.active_node_id == parent_before.active_node_id
        assert (
            store.submit(
                lambda uow: uow.repository.list_attempts("run-parent"),
                force_flush=True,
            ).result(timeout=10)
            == attempts_before
        )

        invocation = _invocation_row(harness, result["invocation"].invocation_id)
        assert invocation.status == "completed"
        assert invocation.handoff_state == "accepted"
        assert readiness_calls == [1]
    finally:
        harness.close()


def test_boundary_2_expired_lease_is_released_and_delivered_once(
    tmp_path: Path,
) -> None:
    harness, result, child_run_id, _payload = _child_with_pending_event(tmp_path)
    try:
        store = harness.commands.store

        # Worker A leases the action and crashes before delivering.
        def crash_lease(uow):
            return uow.repository.lease_outbox_actions(
                owner="crashed-worker",
                now_ms=FIXED_NOW_MS + 5000,
                lease_ms=30_000,
                action_kinds=("event_publish",),
            )

        leased = store.submit(crash_lease, force_flush=True).result(timeout=10)
        assert len(leased) == 1
        action_id = _event_publish_action_id(harness, child_run_id)
        assert _outbox_status(harness, action_id).status == "leased"
        assert _parent_absorbed_events(harness) == []

        # Worker B starts while worker A's lease is still live: no steal, no
        # duplicate delivery.
        live_worker = EventPublishWorker(
            store=store,
            now_provider=lambda: FIXED_NOW_MS + 1000,
        )
        assert live_worker.run_once() == 0
        assert _parent_absorbed_events(harness) == []

        # The lease expires; worker B re-leases and delivers exactly once.
        recovered_worker = EventPublishWorker(
            store=store,
            now_provider=lambda: FIXED_NOW_MS + 40_000,
        )
        assert recovered_worker.run_once() == 1
        assert _outbox_status(harness, action_id).status == "succeeded"
        assert len(_parent_absorbed_events(harness)) == 1

        invocation = _invocation_row(harness, result["invocation"].invocation_id)
        assert invocation.status == "completed"
    finally:
        harness.close()


def test_boundary_3_redelivery_after_missing_ack_dedupes(tmp_path: Path) -> None:
    harness, result, child_run_id, payload = _child_with_pending_event(tmp_path)
    try:
        store = harness.commands.store

        # Consumer write landed, then the worker died before the ACK: the
        # parent event exists while the outbox row is still pending.
        first = absorb_knowledge_result(
            store,
            payload,
            now_provider=lambda: FIXED_NOW_MS + 1000,
        )
        assert first["status"] == "absorbed"
        assert len(_parent_absorbed_events(harness)) == 1
        action_id = _event_publish_action_id(harness, child_run_id)
        assert _outbox_status(harness, action_id).status == "pending"

        # Redelivery re-leases, hits the deterministic event id, and ACKs.
        worker = EventPublishWorker(
            store=store,
            now_provider=lambda: FIXED_NOW_MS + 2000,
        )
        assert worker.run_once() == 1
        assert _outbox_status(harness, action_id).status == "succeeded"
        assert len(_parent_absorbed_events(harness)) == 1

        # A fully manual duplicate stays inert too.
        replay = absorb_knowledge_result(
            store,
            payload,
            now_provider=lambda: FIXED_NOW_MS + 3000,
        )
        assert replay["status"] == "already_absorbed"
        assert replay["dedupKey"] == first["dedupKey"]
        assert len(_parent_absorbed_events(harness)) == 1
    finally:
        harness.close()


def test_exhausted_delivery_attempts_dead_letter_with_reconciliation(
    tmp_path: Path,
) -> None:
    harness, result, child_run_id, _payload = _child_with_pending_event(tmp_path)
    try:
        store = harness.commands.store
        action_id = _event_publish_action_id(harness, child_run_id)
        clock = {"now": FIXED_NOW_MS + 1000}

        def broken_deliver(payload_dict):
            raise RuntimeError("parent sink unavailable")

        worker = EventPublishWorker(
            store=store,
            now_provider=lambda: clock["now"],
            deliver=broken_deliver,
        )
        status = "pending"
        for _ in range(24):
            worker.run_once()
            record = _outbox_status(harness, action_id)
            status = record.status
            if status == "failed":
                break
            # Requeue backs off 5s per attempt; step past it each round.
            clock["now"] += 10_000
        assert status == "failed"
        problem = json.loads(record.last_problem_json or "{}")
        assert problem["code"] == "event_publish_dead_lettered"

        # The child keeps its correct terminal status; the reconciliation
        # surface is the invocation record.
        child = store.get_run(child_run_id)
        assert child.status == "succeeded"
        invocation = _invocation_row(harness, result["invocation"].invocation_id)
        assert invocation.status == "completed"
        reconciliation = json.loads(invocation.error_json or "{}")
        assert reconciliation["code"] == "event_publish_dead_lettered"
        assert _parent_absorbed_events(harness) == []
    finally:
        harness.close()


def test_child_failure_marks_invocation_failed_without_publishing(
    tmp_path: Path,
) -> None:
    harness = _make_harness(tmp_path)
    try:
        _seed_parent(harness)
        result = _invoke(harness)
        child_run_id = result["childRunId"]
        store = harness.commands.store

        def mutate_blocked(uow):
            return record_knowledge_sideflow_child_failure(
                uow, run_id=child_run_id, outcome="blocked", now_ms=FIXED_NOW_MS + 5
            )

        store.submit(mutate_blocked, force_flush=True).result(timeout=10)
        # blocked is deliberately non-terminal: the operator can still repair.
        invocation = _invocation_row(harness, result["invocation"].invocation_id)
        assert invocation.status not in {"failed", "cancelled"}
        assert _outbox_rows(harness, child_run_id, "event_publish") == []

        def mutate_failed(uow):
            return record_knowledge_sideflow_child_failure(
                uow, run_id=child_run_id, outcome="failed", now_ms=FIXED_NOW_MS + 6
            )

        store.submit(mutate_failed, force_flush=True).result(timeout=10)
        invocation = _invocation_row(harness, result["invocation"].invocation_id)
        assert invocation.status == "failed"
        error = json.loads(invocation.error_json or "{}")
        assert error["code"] == "knowledge_sideflow_child_failed"
        assert error["outcome"] == "failed"
        assert _outbox_rows(harness, child_run_id, "event_publish") == []
        assert _parent_absorbed_events(harness) == []
    finally:
        harness.close()
