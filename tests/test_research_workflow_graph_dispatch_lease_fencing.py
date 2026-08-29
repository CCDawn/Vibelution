"""Lease-fencing regressions for graph dispatch terminal paths."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from core.research.workflow.challenge_cup_runtime import GraphDispatch
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
