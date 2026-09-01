"""Production outbox pump (B3): parallel claim-and-run dispatch pool.

Covers the Challenge Cup 10-concurrency pump contract:
- wake/idle drives workers to drain the outbox until idle (no lost wakeups);
- N workers consume multiple actions concurrently with each action executed
  exactly once (lease CAS sharding, no prefetch);
- worker count is configurable (default 10, ``VIBELUTION_WORKFLOW_WORKERS``);
- stop broadcasts and joins the pool with a bounded wait;
- two runs' graph actions advance concurrently without cross-run receipt
  leakage (receipt/attempt ownership stays per-run).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from core.web.services.team_workflow.research_runtime.outbox_pump import (
    WorkflowOutboxPump,
)

WORKFLOW_VERSION_ID = "challenge-cup-research-v2.1.0"


class _ClaimRuntime:
    """Thread-safe fake of ``WorkflowRuntime.claim_and_run_one``.

    Hands out one pending action per call (the same claim-as-you-run shape
    as the real runtime) and records who executed what.
    """

    def __init__(self, actions: list[str], *, exec_s: float = 0.0) -> None:
        self._pending = list(actions)
        self._lock = threading.Lock()
        self._exec_s = exec_s
        self.executions: dict[str, int] = {}
        self.executors: dict[str, str] = {}
        self.active = 0
        self.max_active = 0
        self.maintenance_calls = 0
        self.first_start = threading.Event()

    def claim_and_run_one(self) -> bool:
        with self._lock:
            if not self._pending:
                return False
            action = self._pending.pop(0)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        self.first_start.set()
        try:
            time.sleep(self._exec_s)
        finally:
            with self._lock:
                self.active -= 1
                self.executions[action] = self.executions.get(action, 0) + 1
                self.executors[action] = threading.current_thread().name
        return True

    def run_maintenance_once(self, limit: int = 4) -> int:
        with self._lock:
            self.maintenance_calls += 1
        return 0


def _wait_until(predicate, *, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_wake_drains_until_idle_and_runs_each_action_once() -> None:
    runtime = _ClaimRuntime(["a", "b"])
    pump = WorkflowOutboxPump(workers=2, idle_poll_s=0.05)
    pump.attach(runtime)
    try:
        assert _wait_until(lambda: runtime.executions == {"a": 1, "b": 1})
    finally:
        pump.stop()


def test_parallel_workers_consume_actions_exactly_once() -> None:
    actions = [f"action-{index}" for index in range(6)]
    runtime = _ClaimRuntime(actions, exec_s=0.05)
    pump = WorkflowOutboxPump(workers=3, idle_poll_s=0.05)
    pump.attach(runtime)
    try:
        # Six wake tokens (one per arrived action) fan the pool out; without
        # multi-worker wake support a single Event-based drain would run
        # them all on one thread.
        for _ in actions:
            pump.wake()
        assert _wait_until(lambda: len(runtime.executions) == len(actions))
        assert all(count == 1 for count in runtime.executions.values()), (
            runtime.executions
        )
        # Real overlap: more than one worker held an action at once.
        assert runtime.max_active >= 2, runtime.max_active
        assert len({*runtime.executors.values()}) >= 2
    finally:
        started = time.monotonic()
        pump.stop(timeout=10)
        assert time.monotonic() - started < 10


def test_worker_count_defaults_to_ten_and_env_overrides(
    monkeypatch: Any,
) -> None:
    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        DEFAULT_WORKFLOW_WORKERS,
        WORKFLOW_WORKERS_ENV,
        workflow_worker_count,
    )

    monkeypatch.delenv(WORKFLOW_WORKERS_ENV, raising=False)
    assert DEFAULT_WORKFLOW_WORKERS == 10
    assert workflow_worker_count() == 10

    monkeypatch.setenv(WORKFLOW_WORKERS_ENV, "3")
    assert workflow_worker_count() == 3

    monkeypatch.setenv(WORKFLOW_WORKERS_ENV, "not-a-number")
    assert workflow_worker_count() == 10

    monkeypatch.setenv(WORKFLOW_WORKERS_ENV, "0")
    assert workflow_worker_count() == 1

    monkeypatch.setenv(WORKFLOW_WORKERS_ENV, "-4")
    assert workflow_worker_count() == 1


def test_pump_spawns_configured_threads_and_stops_bounded() -> None:
    runtime = _ClaimRuntime([])
    pump = WorkflowOutboxPump(workers=3, idle_poll_s=0.05)
    pump.attach(runtime)
    pool_threads = list(pump.threads)
    try:
        assert pump.worker_count == 3
        # 3 dispatch workers + 1 serial maintenance thread.
        assert len(pool_threads) == 4
        assert all(thread.is_alive() for thread in pool_threads)
        assert _wait_until(lambda: runtime.maintenance_calls >= 1)
    finally:
        started = time.monotonic()
        pump.stop(timeout=10)
        elapsed = time.monotonic() - started
    assert elapsed < 10
    assert all(not thread.is_alive() for thread in pool_threads)
    pump.stop()  # idempotent
    assert pump.threads == ()


def test_stop_lets_workers_finish_current_action_then_exits() -> None:
    runtime = _ClaimRuntime(["a", "b", "c"], exec_s=0.2)
    pump = WorkflowOutboxPump(workers=2, idle_poll_s=0.05)
    pump.attach(runtime)
    pump.wake()
    assert runtime.first_start.wait(timeout=5)
    started = time.monotonic()
    pump.stop(timeout=10)
    elapsed = time.monotonic() - started
    assert elapsed < 10
    # No action was abandoned half-done: every started execution completed.
    assert all(count == 1 for count in runtime.executions.values())
    assert all(not thread.is_alive() for thread in pump.threads)


# ---------------------------------------------------------------------------
# Real-runtime receipt ownership: two runs' graph_dispatch actions are
# claimed concurrently by the pool; every commit is owner-CAS fenced, so
# receipts/attempts must land on their own run with exactly one executor.
# ---------------------------------------------------------------------------


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
        "researchObjectiveContract": {"question": "How to win?"},
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
                "snapshotId": f"snap:{run_id}:source_finding",
                "nodeId": "source_finding",
                "agentId": "agent-real-1",
                "roleKey": "source_finder",
            }
        ],
        "createdBy": "u-1",
        "createdAt": "2026-08-12T00:00:00Z",
        "snapshotHash": "c" * 64,
    }


def _seed_run(store: Any, run_id: str) -> None:
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
    return list(
        store.submit(
            lambda uow: uow.repository.execute(sql, params).fetchall(),
            force_flush=True,
        ).result(timeout=10)
    )


def test_parallel_graph_dispatch_keeps_receipt_ownership_per_run(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from core.research.workflow.challenge_cup_runtime import (
        GraphDispatchResult,
        build_pending_action,
    )
    from core.research.workflow.contracts import (
        ActorRef,
        CommandRequest,
        WorkflowCommandKind,
    )
    from core.web.services.team_workflow.research_runtime import readiness_providers
    from core.web.services.team_workflow.research_runtime.operator_authorization import (
        server_operator_scope,
    )
    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        build_workflow_runtime,
    )

    monkeypatch.setattr(
        readiness_providers, "is_agent_resolvable", lambda agent_id: bool(agent_id)
    )
    # Same wiring as start_production_workflow_runtime: every accepted
    # command's after-commit hook releases a wake token, so two commands
    # wake two workers before the pump even attaches.
    pump = WorkflowOutboxPump(workers=4, idle_poll_s=0.05)
    runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite3", wake_worker=pump.wake
    )
    concurrency = {"active": 0, "max": 0}
    concurrency_lock = threading.Lock()
    # Deterministic overlap: the FIRST invoke to enter fake_start blocks
    # until the second one enters (bounded), so a genuine two-worker
    # overlap is proven, not raced. The bounded timeout keeps the test
    # honest — if the pump serializes, the first invoke times out and the
    # max-concurrency assertion below still fails.
    release_invoke = threading.Event()

    def fake_snapshot(_run_id: str, _workflow_version_id: str = "") -> dict:
        return {"values": {}, "nextNodeIds": [], "checkpointId": ""}

    def fake_start(dispatch: Any) -> GraphDispatchResult:
        with concurrency_lock:
            concurrency["active"] += 1
            concurrency["max"] = max(
                concurrency["max"], concurrency["active"]
            )
            if concurrency["active"] >= 2:
                release_invoke.set()
        try:
            # Hold both in-flight invokes together until they overlap.
            release_invoke.wait(timeout=3)
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
                pending_action=build_pending_action(state, dispatch.node_id),
                next_node_ids=(dispatch.node_id,),
                checkpoint_id="ckpt-test",
                state=state,
            )
        finally:
            release_invoke.set()
            with concurrency_lock:
                concurrency["active"] -= 1

    monkeypatch.setattr(runtime.coordinator, "snapshot", fake_snapshot)
    monkeypatch.setattr(runtime.coordinator, "start_attempt", fake_start)
    # The graph commit creates one adapter_dispatch per run; the adapter
    # executor needs a real agent backend, so keep it idle — ownership of
    # the adapter rows is asserted below, not their execution.
    monkeypatch.setattr(runtime.adapter_worker, "run_claim_one", lambda: False)

    run_ids = ["run-parallel-a", "run-parallel-b"]
    for run_id in run_ids:
        _seed_run(runtime.store, run_id)

    try:
        for index, run_id in enumerate(run_ids):
            request = CommandRequest(
                command_id=f"cmd-{run_id}",
                run_id=run_id,
                team_id="research-team",
                command=WorkflowCommandKind.START_NODE,
                node_id="source_finding",
                expected_run_version=1,
                idempotency_key=f"ui:parallel-{index}",
                payload={},
                requested_by=ActorRef("user", "u-1"),
                requested_at_ms=1_750_000_000_000,
            )
            with server_operator_scope("u-1", roles=("operator",)):
                receipt = runtime.command_service.submit(request)
            assert receipt.status == "accepted"

        pump.attach(runtime)

        def both_runs_settled() -> bool:
            for run_id in run_ids:
                graph_rows = _rows(
                    runtime.store,
                    "SELECT status FROM outbox_actions "
                    "WHERE run_id = ? AND action_kind = 'graph_dispatch'",
                    (run_id,),
                )
                statuses = {str(row[0]) for row in graph_rows}
                if statuses != {"succeeded"}:
                    return False
                attempt = runtime.store.latest_attempt(run_id, "source_finding")
                if attempt is None or attempt.status == "starting":
                    return False
            return True

        assert _wait_until(both_runs_settled, timeout=10), (
            "both runs' graph dispatches must settle"
        )

        for run_id in run_ids:
            # Exactly one executor: exactly one attempt row per run, owned
            # by that run (no cross-run receipt leakage).
            attempt_rows = _rows(
                runtime.store,
                "SELECT run_id, node_id, node_run_id, status FROM node_attempts "
                "WHERE run_id = ?",
                (run_id,),
            )
            assert len(attempt_rows) == 1, attempt_rows
            row = attempt_rows[0]
            assert row[0] == run_id and row[1] == "source_finding"
            assert row[2] == f"nr-{run_id}-source_finding-a1"
            adapter_rows = _rows(
                runtime.store,
                "SELECT run_id, status FROM outbox_actions "
                "WHERE run_id = ? AND action_kind = 'adapter_dispatch'",
                (run_id,),
            )
            assert len(adapter_rows) == 1, adapter_rows
            assert adapter_rows[0][0] == run_id
        # Both graph invokes were in flight concurrently at some point.
        assert concurrency["max"] >= 2, concurrency
    finally:
        pump.stop()
        runtime.close()
