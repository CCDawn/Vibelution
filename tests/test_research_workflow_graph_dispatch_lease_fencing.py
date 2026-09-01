"""Lease-fencing regressions for graph dispatch terminal paths."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from pathlib import Path

from core.research.workflow.challenge_cup_runtime import (
    GraphDispatch,
    GraphDispatchResult,
)
from core.research.workflow.contracts import ExecutionReceipt
from core.research.workflow.ledger import outbox as outbox_api
from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
    GraphDispatchWorker,
)
from tests._support.graph_helpers import GraphHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_outbox_record,
)


def _worker(harness: GraphHarness) -> GraphDispatchWorker:
    return GraphDispatchWorker(
        store=harness.commands.store,
        coordinator=harness.coordinator,
        owner_id="graph-worker-stale",
        now_provider=lambda: FIXED_NOW_MS + 1300,
    )


def _realtime_worker(
    harness: GraphHarness, *, owner: str, lease_ms: int
) -> GraphDispatchWorker:
    """Worker on the real clock so sub-second leases can actually expire."""
    return GraphDispatchWorker(
        store=harness.commands.store,
        coordinator=harness.coordinator,
        owner_id=owner,
        lease_ms=lease_ms,
        now_provider=lambda: int(time.time() * 1000),
    )


def _take_over_graph_lease(
    harness: GraphHarness,
    *,
    node_id: str,
    dispatch_kind: str = "start",
    receipt: ExecutionReceipt | None = None,
):
    harness.seed(status="running")
    harness.enqueue_graph_dispatch(
        "run-test",
        node_id,
        1,
        dispatch_kind=dispatch_kind,
        receipt=receipt,
    )
    first = outbox_api.lease_ready_actions(
        harness.commands.store,
        owner="graph-worker-old",
        now_ms=FIXED_NOW_MS + 1000,
        lease_ms=100,
        action_kinds=("graph_dispatch",),
    )
    assert len(first) == 1
    second = outbox_api.lease_ready_actions(
        harness.commands.store,
        owner="graph-worker-new",
        now_ms=FIXED_NOW_MS + 1200,
        lease_ms=5000,
        action_kinds=("graph_dispatch",),
    )
    assert len(second) == 1
    return first[0], second[0]


def _insert_adapter_outbox(harness: GraphHarness, node_run_id: str) -> None:
    def mutate(uow):
        uow.repository.insert_outbox(
            replace(
                build_outbox_record(
                    "adapter-current-owner",
                    run_id="run-test",
                    command_id="cmd-driver",
                    action_kind="adapter_dispatch",
                    available_at_ms=FIXED_NOW_MS + 1000,
                    idempotency_key="adapter:current-owner",
                ),
                node_run_id=node_run_id,
            )
        )

    harness.commands.store.submit(mutate, force_flush=True).result(timeout=10)


def _dispatch(action) -> GraphDispatch:
    return GraphDispatch.from_payload(json.loads(action.payload_json))


def test_stale_mark_blocked_does_not_mutate_reclaimed_graph_state(
    tmp_path: Path,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        stale, current = _take_over_graph_lease(
            harness,
            node_id="source_finding",
        )
        dispatch = _dispatch(stale)
        _insert_adapter_outbox(harness, dispatch.node_run_id)

        _worker(harness)._mark_blocked(dispatch=dispatch, action=stale, detail="stale lease")

        graph_row = harness.commands.store.read(
            lambda repo: repo.get_outbox(current.action_id)
        )
        adapter_row = harness.commands.store.read(
            lambda repo: repo.get_outbox("adapter-current-owner")
        )
        attempt = harness.commands.store.latest_attempt("run-test", "source_finding")
        run = harness.commands.store.get_run("run-test")
        assert graph_row is not None
        assert graph_row.status == "leased"
        assert graph_row.lease_owner == "graph-worker-new"
        assert adapter_row is not None and adapter_row.status == "pending"
        assert attempt is not None and attempt.status == "starting"
        assert run is not None and run.status == "running"
    finally:
        harness.close()


def test_stale_mark_attempt_outcome_does_not_cancel_reclaimed_outboxes(
    tmp_path: Path,
) -> None:
    receipt = ExecutionReceipt(
        action_id="receipt-source-finding",
        node_run_id="nr-run-test-source_finding-a1",
        outcome="failed",
        artifact_receipt_ids=(),
        execution_anchor_id=None,
        budget_receipt_id=None,
        problem=None,
        completed_at_ms=FIXED_NOW_MS,
    )
    harness = GraphHarness(tmp_path)
    try:
        stale, current = _take_over_graph_lease(
            harness,
            node_id="source_finding",
            dispatch_kind="resume_action",
            receipt=receipt,
        )
        dispatch = _dispatch(stale)
        _insert_adapter_outbox(harness, dispatch.node_run_id)

        _worker(harness)._mark_attempt_outcome(action=stale, dispatch=dispatch)

        graph_row = harness.commands.store.read(
            lambda repo: repo.get_outbox(current.action_id)
        )
        adapter_row = harness.commands.store.read(
            lambda repo: repo.get_outbox("adapter-current-owner")
        )
        attempt = harness.commands.store.latest_attempt("run-test", "source_finding")
        run = harness.commands.store.get_run("run-test")
        assert graph_row is not None
        assert graph_row.status == "leased"
        assert graph_row.lease_owner == "graph-worker-new"
        assert adapter_row is not None and adapter_row.status == "pending"
        assert attempt is not None and attempt.status == "starting"
        assert run is not None and run.status == "running"
    finally:
        harness.close()


def test_stale_upstream_accept_does_not_advance_attempt_or_handoff(
    tmp_path: Path,
) -> None:
    receipt = ExecutionReceipt(
        action_id="receipt-source-finding",
        node_run_id="nr-run-test-source_finding-a1",
        outcome="succeeded",
        artifact_receipt_ids=(),
        execution_anchor_id=None,
        budget_receipt_id=None,
        problem=None,
        completed_at_ms=FIXED_NOW_MS,
    )
    harness = GraphHarness(tmp_path)
    try:
        stale, current = _take_over_graph_lease(
            harness,
            node_id="source_finding",
            dispatch_kind="resume_action",
            receipt=receipt,
        )
        dispatch = _dispatch(stale)

        def seed_handoff(uow):
            uow.repository.insert_handoff(
                handoff_id="ho-stale-accept",
                run_id="run-test",
                edge_id="e_find_extract",
                from_node_run_id=dispatch.node_run_id,
                to_node_id="source_extraction",
                to_node_run_id=None,
                gate_kind="auto",
                input_snapshot_hash="a" * 64,
                offered_at_ms=FIXED_NOW_MS,
            )
            uow.repository.update_handoff_status(
                "ho-stale-accept",
                "ready",
                FIXED_NOW_MS,
            )

        harness.commands.store.submit(
            seed_handoff,
            force_flush=True,
        ).result(timeout=10)
        result = GraphDispatchResult(
            dispatch_kind="resume_action",
            pending_action=None,
            next_node_ids=(),
            checkpoint_id="checkpoint-stale",
            state={},
        )

        committed = _worker(harness)._commit_upstream_accept(
            stale,
            dispatch,
            result,
        )

        graph_row = harness.commands.store.read(
            lambda repo: repo.get_outbox(current.action_id)
        )
        attempt = harness.commands.store.latest_attempt("run-test", "source_finding")
        handoff = harness.commands.store.read(
            lambda repo: repo.get_handoff_by_from_node(
                "run-test",
                dispatch.node_run_id,
            )
        )
        assert committed is False
        assert graph_row is not None
        assert graph_row.status == "leased"
        assert graph_row.lease_owner == "graph-worker-new"
        assert attempt is not None and attempt.status == "starting"
        assert handoff is not None and handoff[8] == "ready"
    finally:
        harness.close()


# ---------------------------------------------------------------------------
# B2 invoke heartbeat: a LangGraph invoke can outlive the 30s outbox lease.
# The worker now renews the lease every lease_ms/3 while the invoke runs
# (Temporal-style heartbeat), so the lease can no longer expire mid-invoke;
# a failed renewal (lease reclaimed by another owner) aborts local progress
# and the commit-point owner CAS keeps the ledger fenced.
# ---------------------------------------------------------------------------


def _steal_lease(harness: GraphHarness, action_id: str, new_owner: str) -> None:
    """External takeover: another worker re-owns the lease directly."""

    def steal(uow):
        uow.repository.execute(
            """
            UPDATE outbox_actions
            SET lease_owner = ?, lease_expires_at_ms = ?
            WHERE action_id = ?
            """,
            (new_owner, int(time.time() * 1000) + 60_000, action_id),
        )

    harness.commands.store.submit(steal, force_flush=True).result(timeout=10)


def _completed_start_result(checkpoint_id: str) -> GraphDispatchResult:
    return GraphDispatchResult(
        dispatch_kind="start",
        pending_action=None,
        next_node_ids=(),
        checkpoint_id=checkpoint_id,
        state={},
        completed=True,
    )


def test_invoke_heartbeat_keeps_lease_alive_past_single_window(
    tmp_path: Path,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed(status="running")
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)

        def mark_dispatching(uow):
            # dispatching → succeeded is the legal commit transition; the
            # seeded attempt starts at "starting".
            uow.repository.update_attempt_status(
                "nr-run-test-source_finding-a1",
                "dispatching",
                int(time.time() * 1000),
            )

        harness.commands.store.submit(
            mark_dispatching, force_flush=True
        ).result(timeout=10)
        leased = outbox_api.lease_ready_actions(
            harness.commands.store,
            owner="graph-worker-beat",
            now_ms=int(time.time() * 1000),
            lease_ms=400,
            action_kinds=("graph_dispatch",),
        )
        assert len(leased) == 1
        action = leased[0]
        dispatch = _dispatch(action)
        worker = _realtime_worker(
            harness, owner="graph-worker-beat", lease_ms=400
        )

        release_invoke = threading.Event()

        def slow_start(_dispatch: GraphDispatch) -> GraphDispatchResult:
            # Simulate a long LangGraph invoke far past the 400ms lease.
            assert release_invoke.wait(timeout=10)
            return _completed_start_result("ckpt-beat")

        worker._start_or_recover = slow_start  # type: ignore[method-assign]

        failures: list[BaseException] = []

        def run_handle() -> None:
            try:
                worker._handle(action)
            except BaseException as exc:  # noqa: BLE001 - surfaced below
                failures.append(exc)

        thread = threading.Thread(target=run_handle, name="handle-under-test")
        thread.start()
        # Stay blocked past the original 400ms lease window (heartbeat
        # interval is 400/3 ≈ 133ms, so several renewals must have fired).
        time.sleep(0.6)
        stolen = outbox_api.lease_ready_actions(
            harness.commands.store,
            owner="graph-worker-new",
            now_ms=int(time.time() * 1000),
            lease_ms=5000,
            action_kinds=("graph_dispatch",),
        )
        # The heartbeat kept the lease un-expirable: no second worker can
        # reclaim the action mid-invoke.
        assert stolen == []
        release_invoke.set()
        thread.join(timeout=10)
        assert failures == []

        row = harness.commands.store.read(
            lambda repo: repo.get_outbox(action.action_id)
        )
        # ack's owner + expiry CAS passed: the lease was live at commit.
        assert row is not None and row.status == "succeeded"
    finally:
        harness.close()


def test_reclaimed_lease_aborts_invoke_and_commit(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed(status="running")
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        leased = outbox_api.lease_ready_actions(
            harness.commands.store,
            owner="graph-worker-victim",
            now_ms=int(time.time() * 1000),
            lease_ms=600,
            action_kinds=("graph_dispatch",),
        )
        assert len(leased) == 1
        action = leased[0]
        dispatch = _dispatch(action)
        worker = _realtime_worker(
            harness, owner="graph-worker-victim", lease_ms=600
        )

        invoke_entered = threading.Event()
        release_invoke = threading.Event()

        def slow_start(_dispatch: GraphDispatch) -> GraphDispatchResult:
            invoke_entered.set()
            assert release_invoke.wait(timeout=10)
            return _completed_start_result("ckpt-stolen")

        worker._start_or_recover = slow_start  # type: ignore[method-assign]

        thread = threading.Thread(
            target=worker._handle,
            args=(action,),
            name="handle-under-test",
        )
        thread.start()
        assert invoke_entered.wait(timeout=5)

        _steal_lease(harness, action.action_id, "graph-worker-new")
        # Wait past one heartbeat interval (600/3 = 200ms): the next renewal
        # must observe the takeover and set the lost signal.
        time.sleep(0.4)
        release_invoke.set()
        thread.join(timeout=10)

        row = harness.commands.store.read(
            lambda repo: repo.get_outbox(action.action_id)
        )
        assert row is not None
        assert row.status == "leased"
        assert row.lease_owner == "graph-worker-new"
        attempt = harness.commands.store.latest_attempt(
            "run-test", "source_finding"
        )
        assert attempt is not None and attempt.status == "starting"
        run = harness.commands.store.get_run("run-test")
        assert run is not None and run.status == "running"
    finally:
        harness.close()


def test_invoke_skipped_when_lease_lost_before_invoke(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed(status="running")
        harness.enqueue_graph_dispatch("run-test", "source_finding", 1)
        leased = outbox_api.lease_ready_actions(
            harness.commands.store,
            owner="graph-worker-victim",
            now_ms=int(time.time() * 1000),
            lease_ms=30_000,
            action_kinds=("graph_dispatch",),
        )
        assert len(leased) == 1
        action = leased[0]
        dispatch = _dispatch(action)
        _steal_lease(harness, action.action_id, "graph-worker-new")

        worker = _realtime_worker(
            harness, owner="graph-worker-victim", lease_ms=30_000
        )
        invoked = threading.Event()

        def must_not_invoke(_dispatch: GraphDispatch) -> GraphDispatchResult:
            invoked.set()
            raise AssertionError("invoke must not run on a lost lease")

        worker._start_or_recover = must_not_invoke  # type: ignore[method-assign]

        worker._handle(action)

        assert not invoked.is_set()
        row = harness.commands.store.read(
            lambda repo: repo.get_outbox(action.action_id)
        )
        assert row is not None
        assert row.status == "leased"
        assert row.lease_owner == "graph-worker-new"
    finally:
        harness.close()
