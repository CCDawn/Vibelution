"""Challenge Cup 10-parallel acceptance (plan D2, runtime-scene).

Drives TEN main-workflow runs concurrently through the REAL production
pieces: the Workflow Ledger store (single writer), the real command
service (run_version CAS + outbox commit), the real ``WorkflowOutboxPump``
with 10 dispatch workers (B3), the real graph-dispatch worker with the B2
lease heartbeat, and the real checkpoint wiring. Only the LangGraph
invoke (``coordinator.snapshot`` / ``coordinator.start_attempt``) is
faked — with realistic 50-200ms LLM-magnitude latency and a deterministic
all-ten-arrived handshake, so genuine overlap is proven rather than raced
(no sleep-based speed contests).

Plan D2 (docs/plans/2026-09-02-challenge-cup-10-parallel-concurrency-plan.md §D2)
assertions, all as repeatable asserts:
1. no cross-run leakage: every outbox row / attempt / event carries only
   its own runId and node identity (zero cross-over across the 10 runs);
2. zero double execution: each action has exactly one executor — one
   invoke per run, one attempt row per run, one graph outbox row per run;
3. zero ``database is locked`` failures anywhere in the run (log capture
   + outbox problem scan);
4. real concurrency: the ten graph invokes genuinely overlapped (peak
   >= 2 is the floor; the all-ten handshake is the deterministic proof);
5. projection consistency: the store read side (run row, latest_attempt,
   event stream) agrees with the committed ledger state (command accepted
   run_version, contiguous per-run event sequences, attempt rows).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from core.web.services.team_workflow.research_runtime.outbox_pump import (
    WorkflowOutboxPump,
)

RUN_COUNT = 10
ENTRY_NODE_ID = "source_finding"

_DEFINITION_LOCK = threading.Lock()
_DEFINITION_IDENTITY: Any = None


def _registered_definition_identity() -> Any:
    """Register the canonical challenge-cup definition once (idempotent)."""
    global _DEFINITION_IDENTITY
    with _DEFINITION_LOCK:
        if _DEFINITION_IDENTITY is None:
            from core.research.workflow.definition import (
                build_challenge_cup_workflow_definition,
            )
            from core.research.workflow.definition_registry import register_or_resolve

            _DEFINITION_IDENTITY = register_or_resolve(
                build_challenge_cup_workflow_definition()
            )
        return _DEFINITION_IDENTITY


def _input_snapshot(run_id: str, workflow_version_id: str) -> dict[str, Any]:
    return {
        "teamId": "research-team",
        "projectId": "challenge-sci-096",
        "questionId": "SCI-096",
        "workflowVersionId": workflow_version_id,
        "researchBriefHash": "b" * 64,
        "datasetRefs": [],
        "metricContract": {},
        "constraintSnapshot": {},
        "competitionRuleRef": "rule",
        "competitionRuleVersion": "1",
        "trackAndRubricSnapshot": {},
        "researchObjectiveContract": {"question": f"How to win? ({run_id})"},
        "sourcePolicy": {},
        "budgetPolicy": {
            "stageBudgets": {
                "knowledge_collection": {"tokens": 1000, "toolCalls": 5}
            }
        },
        "stopPolicy": {},
        "environmentSnapshotRef": "env-1",
        "modelRoutingPolicy": {},
        "evaluationContract": {},
        "agentBindingSnapshot": [
            {
                "snapshotId": f"snap:{run_id}:{ENTRY_NODE_ID}",
                "nodeId": ENTRY_NODE_ID,
                "agentId": "agent-real-1",
                "roleKey": "source_finder",
            }
        ],
        "createdBy": "u-1",
        "createdAt": "2026-08-12T00:00:00Z",
        "snapshotHash": "c" * 64,
    }


def _seed_run(store: Any, run_id: str) -> None:
    """Seed one ``created`` run + its run_created event (B3 helper shape)."""
    from dataclasses import replace

    from tests._support.workflow_ledger_helpers import (
        build_event_record,
        build_run_record,
    )

    identity = _registered_definition_identity()
    record = replace(
        build_run_record(
            run_id=run_id,
            workflow_id=identity.workflowId,
            workflow_version_id=identity.workflowVersionId,
            last_event_sequence=1,
            created_at_ms=int(time.time() * 1000),
        ),
        structure_hash=identity.structureHash,
        input_snapshot_json=json.dumps(
            _input_snapshot(run_id, identity.workflowVersionId),
            ensure_ascii=False,
        ),
    )

    def mutate(uow: Any) -> None:
        uow.repository.insert_run(record)
        uow.repository.insert_event(
            build_event_record(
                sequence=1,
                run_id=run_id,
                event_type="run_created",
                event_id=f"evt-created-{run_id}",
            )
        )

    store.submit(mutate, force_flush=True).result(timeout=10)


def _rows(store: Any, sql: str, params: tuple = ()) -> list[tuple]:
    return list(store.read(lambda repo: repo.execute(sql, params).fetchall()))


def _wait_until(predicate, *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


class _LockedErrorCapture(logging.Handler):
    """Capture WARNING+ messages (incl. exception text) for a locked-DB scan."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())
        if record.exc_info and record.exc_info[1] is not None:
            self.messages.append(str(record.exc_info[1]))

    def locked_failures(self) -> list[str]:
        markers = ("database is locked", "database table is locked")
        return [
            message
            for message in self.messages
            if any(marker in message for marker in markers)
        ]


def _submit_start_command(runtime: Any, run_id: str, index: int) -> Any:
    from core.research.workflow.contracts import (
        ActorRef,
        CommandRequest,
        WorkflowCommandKind,
    )
    from core.web.services.team_workflow.research_runtime.operator_authorization import (
        server_operator_scope,
    )

    request = CommandRequest(
        command_id=f"cmd-{run_id}",
        run_id=run_id,
        team_id="research-team",
        command=WorkflowCommandKind.START_NODE,
        node_id=ENTRY_NODE_ID,
        expected_run_version=1,
        idempotency_key=f"ui:parallel-acceptance-{index}",
        payload={},
        requested_by=ActorRef("user", "u-1"),
        requested_at_ms=1_750_000_000_000,
    )
    with server_operator_scope("u-1", roles=("operator",)):
        return runtime.command_service.submit(request)


def test_ten_parallel_runs_advance_concurrently_without_crosstalk(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from core.research.workflow.challenge_cup_runtime import (
        GraphDispatchResult,
        build_pending_action,
    )
    from core.web.services.team_workflow.research_runtime import readiness_providers
    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        WORKFLOW_WORKERS_ENV,
        build_workflow_runtime,
    )

    monkeypatch.delenv(WORKFLOW_WORKERS_ENV, raising=False)
    monkeypatch.setattr(
        readiness_providers,
        "is_agent_resolvable",
        lambda agent_id: bool(agent_id),
    )

    pump = WorkflowOutboxPump(workers=RUN_COUNT, idle_poll_s=0.05)
    runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite3", wake_worker=pump.wake
    )

    stats_lock = threading.Lock()
    concurrency = {"active": 0, "max": 0}
    invoke_counts: dict[str, int] = {}
    all_ten_entered = threading.Event()
    release_invoke = threading.Event()

    def fake_snapshot(_run_id: str, _workflow_version_id: str = "") -> dict:
        return {"values": {}, "nextNodeIds": [], "checkpointId": ""}

    def fake_start(dispatch: Any) -> GraphDispatchResult:
        run_id = str(dispatch.run_id)
        with stats_lock:
            concurrency["active"] += 1
            concurrency["max"] = max(
                concurrency["max"], concurrency["active"]
            )
            invoke_counts[run_id] = invoke_counts.get(run_id, 0) + 1
            if concurrency["active"] >= RUN_COUNT:
                all_ten_entered.set()
                # Release the ten in-flight invokes as soon as all ten
                # arrived (the handshake must prove overlap, not add wait).
                release_invoke.set()
        try:
            # Deterministic all-ten handshake (B3's two-run handshake scaled
            # up): hold every in-flight invoke together so a genuine ten-way
            # overlap is proven. Bounded, so if the pump serialized instead,
            # the handshake times out and assertion 4 fails with evidence
            # instead of the test hanging.
            release_invoke.wait(timeout=15)
            # Realistic LLM-magnitude latency (plan D2: no zero-delay mocks);
            # per-run stagger 50..200ms keeps the interleave non-trivial.
            index = int(run_id.rsplit("-", 1)[-1])
            time.sleep(0.05 + (index % 4) * 0.05)
            state = {
                "run_id": run_id,
                "active_node_id": dispatch.node_id,
                "active_attempt": dispatch.attempt,
                "node_attempts": {dispatch.node_id: dispatch.attempt},
                "input_snapshot_hash": dispatch.input_snapshot_hash,
                "binding_snapshot_id": dispatch.binding_snapshot_id,
                "budget_policy_hash": dispatch.budget_policy_hash,
            }
            return GraphDispatchResult(
                dispatch_kind="start",
                pending_action=build_pending_action(
                    state, dispatch.node_id
                ),
                next_node_ids=(dispatch.node_id,),
                checkpoint_id="ckpt-acceptance",
                state=state,
            )
        finally:
            release_invoke.set()
            with stats_lock:
                concurrency["active"] -= 1

    monkeypatch.setattr(runtime.coordinator, "snapshot", fake_snapshot)
    monkeypatch.setattr(runtime.coordinator, "start_attempt", fake_start)
    # The graph commit creates one adapter_dispatch per run (the handoff to
    # the first LLM-wait node); the adapter executor needs a real agent
    # backend, so keep it idle — D2 asserts the OWNERSHIP of those rows,
    # not their execution (same wiring as the B3 pump test).
    monkeypatch.setattr(
        runtime.adapter_worker, "run_claim_one", lambda: False
    )

    run_ids = [f"run-parallel-{index:02d}" for index in range(RUN_COUNT)]
    for run_id in run_ids:
        _seed_run(runtime.store, run_id)

    log_capture = _LockedErrorCapture()
    root_logger = logging.getLogger()
    root_logger.addHandler(log_capture)
    try:
        for index, run_id in enumerate(run_ids):
            receipt = _submit_start_command(runtime, run_id, index)
            assert receipt.status == "accepted"

        pump.attach(runtime)

        def all_settled() -> bool:
            for run_id in run_ids:
                graph_rows = _rows(
                    runtime.store,
                    "SELECT status FROM outbox_actions "
                    "WHERE run_id = ? AND action_kind = 'graph_dispatch'",
                    (run_id,),
                )
                if {str(row[0]) for row in graph_rows} != {"succeeded"}:
                    return False
                attempt = runtime.store.latest_attempt(
                    run_id, ENTRY_NODE_ID
                )
                if attempt is None or attempt.status == "starting":
                    return False
            return True

        assert _wait_until(all_settled, timeout=30), (
            "all ten runs' graph dispatches must settle"
        )

        # ------------------------------------------------------------------
        # Assertion 1 — no cross-run leakage: every attempt / outbox row /
        # event carries only its own runId, node identity zero cross-over.
        # ------------------------------------------------------------------
        expected_run_ids = set(run_ids)
        attempt_rows = _rows(
            runtime.store,
            "SELECT run_id, node_id, node_run_id FROM node_attempts",
        )
        assert len(attempt_rows) == RUN_COUNT, attempt_rows
        for row_run_id, row_node_id, row_node_run_id in attempt_rows:
            assert row_run_id in expected_run_ids, row_run_id
            assert row_node_id == ENTRY_NODE_ID
            assert row_node_run_id == (
                f"nr-{row_run_id}-{ENTRY_NODE_ID}-a1"
            ), row_node_run_id

        outbox_rows = _rows(
            runtime.store,
            "SELECT run_id, action_kind, node_run_id, payload_json "
            "FROM outbox_actions",
        )
        graph_outbox = [row for row in outbox_rows if row[1] == "graph_dispatch"]
        adapter_outbox = [
            row for row in outbox_rows if row[1] == "adapter_dispatch"
        ]
        assert len(graph_outbox) == RUN_COUNT, graph_outbox
        assert len(adapter_outbox) == RUN_COUNT, adapter_outbox
        for row_run_id, _kind, row_node_run_id, payload_json in graph_outbox:
            payload = json.loads(payload_json)
            assert payload["runId"] == row_run_id, payload
            assert payload["nodeId"] == ENTRY_NODE_ID, payload
            assert row_node_run_id == payload["nodeRunId"]
            assert row_node_run_id.startswith(f"nr-{row_run_id}-"), payload
        for row_run_id, _kind, row_node_run_id, _payload in adapter_outbox:
            assert row_run_id in expected_run_ids
            assert row_node_run_id.startswith(f"nr-{row_run_id}-"), (
                row_node_run_id
            )

        event_run_ids = {
            str(row[0])
            for row in _rows(runtime.store, "SELECT run_id FROM workflow_events")
        }
        assert event_run_ids == expected_run_ids, event_run_ids

        # ------------------------------------------------------------------
        # Assertion 2 — zero double execution: one executor per action.
        # ------------------------------------------------------------------
        assert invoke_counts == {run_id: 1 for run_id in run_ids}, (
            invoke_counts
        )
        for run_id in run_ids:
            attempt_count = _rows(
                runtime.store,
                "SELECT COUNT(*) FROM node_attempts "
                "WHERE run_id = ? AND node_id = ?",
                (run_id, ENTRY_NODE_ID),
            )
            assert attempt_count[0][0] == 1, attempt_count
            graph_count = _rows(
                runtime.store,
                "SELECT COUNT(*) FROM outbox_actions "
                "WHERE run_id = ? AND action_kind = 'graph_dispatch'",
                (run_id,),
            )
            assert graph_count[0][0] == 1, graph_count

        # ------------------------------------------------------------------
        # Assertion 3 — zero "database is locked" failures: neither in the
        # captured WARNING+ logs (incl. pump exception reports) nor in any
        # outbox problem payload.
        # ------------------------------------------------------------------
        locked = log_capture.locked_failures()
        assert locked == [], locked
        problems = _rows(
            runtime.store,
            "SELECT COALESCE(last_problem_json, '') FROM outbox_actions",
        )
        assert not any(
            "locked" in str(row[0]).lower() for row in problems
        ), problems

        # ------------------------------------------------------------------
        # Assertion 4 — real concurrency: the ten graph invokes overlapped.
        # Floor: peak >= 2. Proof: the deterministic all-ten handshake.
        # ------------------------------------------------------------------
        assert concurrency["max"] >= 2, concurrency
        assert all_ten_entered.is_set(), (
            "the ten-run in-flight handshake did not complete; "
            f"dispatch peak was only {concurrency}"
        )

        # ------------------------------------------------------------------
        # Assertion 5 — projection consistency: the store read side agrees
        # with the committed ledger state for every run.
        # ------------------------------------------------------------------
        for run_id in run_ids:
            run = runtime.store.get_run(run_id)
            assert run is not None
            command_row = _rows(
                runtime.store,
                "SELECT accepted_run_version, status FROM workflow_commands "
                "WHERE run_id = ?",
                (run_id,),
            )
            assert len(command_row) == 1, command_row
            accepted_version, command_status = command_row[0]
            assert command_status == "accepted", command_status
            # Command projection: accepted_run_version == run row version.
            assert run.run_version == accepted_version, (
                run_id,
                run.run_version,
                accepted_version,
            )
            # Event stream: contiguous per-run sequences, no gaps, no
            # duplicates, and the run row's last_event_sequence matches.
            event_seqs = [
                int(row[0])
                for row in _rows(
                    runtime.store,
                    "SELECT sequence FROM workflow_events "
                    "WHERE run_id = ? ORDER BY sequence",
                    (run_id,),
                )
            ]
            assert event_seqs == list(range(1, len(event_seqs) + 1)), (
                run_id,
                event_seqs,
            )
            assert run.last_event_sequence == event_seqs[-1], (run_id, event_seqs)
            # Attempt projection: the read-side latest_attempt equals the
            # committed attempt row.
            attempt = runtime.store.latest_attempt(run_id, ENTRY_NODE_ID)
            attempt_row = _rows(
                runtime.store,
                "SELECT node_run_id, attempt, status FROM node_attempts "
                "WHERE run_id = ?",
                (run_id,),
            )
            assert attempt is not None and len(attempt_row) == 1
            assert (attempt.node_run_id, attempt.attempt) == (
                attempt_row[0][0],
                attempt_row[0][1],
            ), (run_id, attempt, attempt_row)
    finally:
        root_logger.removeHandler(log_capture)
        pump.stop()
        runtime.close()


def test_ten_run_handshake_peaks_at_full_worker_width(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Same scene, sharper concurrency claim: the pump drives all TEN
    graph invokes in flight at once (workers=RUN_COUNT, one action per
    worker), proving the B3 fixed pool is genuinely width-10 for ten runs.
    """
    from core.research.workflow.challenge_cup_runtime import (
        GraphDispatchResult,
        build_pending_action,
    )
    from core.web.services.team_workflow.research_runtime import readiness_providers
    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        WORKFLOW_WORKERS_ENV,
        build_workflow_runtime,
    )

    monkeypatch.delenv(WORKFLOW_WORKERS_ENV, raising=False)
    monkeypatch.setattr(
        readiness_providers,
        "is_agent_resolvable",
        lambda agent_id: bool(agent_id),
    )

    pump = WorkflowOutboxPump(workers=RUN_COUNT, idle_poll_s=0.05)
    runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite3", wake_worker=pump.wake
    )

    lock = threading.Lock()
    in_flight = 0
    peak = 0
    barrier = threading.Barrier(RUN_COUNT)
    barrier_broken: list[str] = []

    def fake_snapshot(_run_id: str, _workflow_version_id: str = "") -> dict:
        return {"values": {}, "nextNodeIds": [], "checkpointId": ""}

    def fake_start(dispatch: Any) -> GraphDispatchResult:
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        try:
            try:
                # Strict rendezvous: all ten must be in flight together;
                # the barrier raises (BrokenBarrierError) if any invoke is
                # missing, which surfaces as a pump error + peak < 10.
                barrier.wait(timeout=15)
            except threading.BrokenBarrierError:
                barrier_broken.append(str(dispatch.run_id))
            time.sleep(0.03)
            state = {
                "run_id": dispatch.run_id,
                "active_node_id": dispatch.node_id,
                "active_attempt": dispatch.attempt,
                "node_attempts": {dispatch.node_id: dispatch.attempt},
                "input_snapshot_hash": dispatch.input_snapshot_hash,
                "binding_snapshot_id": dispatch.binding_snapshot_id,
                "budget_policy_hash": dispatch.budget_policy_hash,
            }
            return GraphDispatchResult(
                dispatch_kind="start",
                pending_action=build_pending_action(
                    state, dispatch.node_id
                ),
                next_node_ids=(dispatch.node_id,),
                checkpoint_id="ckpt-acceptance-width",
                state=state,
            )
        finally:
            with lock:
                in_flight -= 1

    monkeypatch.setattr(runtime.coordinator, "snapshot", fake_snapshot)
    monkeypatch.setattr(runtime.coordinator, "start_attempt", fake_start)
    monkeypatch.setattr(
        runtime.adapter_worker, "run_claim_one", lambda: False
    )

    run_ids = [f"run-width-{index:02d}" for index in range(RUN_COUNT)]
    for run_id in run_ids:
        _seed_run(runtime.store, run_id)
    try:
        for index, run_id in enumerate(run_ids):
            receipt = _submit_start_command(runtime, run_id, index)
            assert receipt.status == "accepted"

        pump.attach(runtime)

        def all_settled() -> bool:
            for run_id in run_ids:
                graph_rows = _rows(
                    runtime.store,
                    "SELECT status FROM outbox_actions "
                    "WHERE run_id = ? AND action_kind = 'graph_dispatch'",
                    (run_id,),
                )
                if {str(row[0]) for row in graph_rows} != {"succeeded"}:
                    return False
            return True

        assert _wait_until(all_settled, timeout=30), (
            "all ten runs' graph dispatches must settle"
        )
        assert not barrier_broken, barrier_broken
        assert peak == RUN_COUNT, peak
    finally:
        pump.stop()
        runtime.close()
