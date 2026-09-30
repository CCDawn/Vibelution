"""P2-e graph dispatch governance: PAUSED status, consecutive-error pause,
deadlock pause and the per-node-type WIP cap.

Behavior contract under test:
- PAUSED is a recoverable hold (transitions), never reachable from BLOCKED.
- Threshold-consecutive failed attempts park the run in the same transaction
  that landed the last failure; in-flight work settles; new ``start``
  dispatches are deferred until resume.
- The deadlock sweep parks live runs with an empty ready set and a non-empty
  blocked inventory; designed holds (blocked status, waiting_human, queued
  work, repairable accepted handoffs) are never hijacked.
- The WIP cap requeues over-cap ``start`` dispatches without blocking or
  staling any node; default (no limits) keeps scheduling byte-equal.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.research.workflow.contracts import ExecutionReceipt
from core.research.workflow.models import WorkflowRunStatus
from core.research.workflow.transitions import (
    RunStatus,
    can_pause_run,
    can_transition_run,
)
from core.web.services.team_workflow.research_runtime.dispatch_governance import (
    GovernancePolicy,
    classify_deadlock,
    consecutive_error_count,
    resume_from_pause,
    run_deadlock_sweep,
)
from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
    GraphDispatchWorker,
)
from tests._support.graph_helpers import FIXED_NOW_MS, GraphHarness
from tests._support.workflow_ledger_helpers import (
    build_attempt_record,
    build_command_record,
    build_outbox_record,
)


def _seed_command(harness: GraphHarness, command_id: str = "cmd-governance-1") -> None:
    store = harness.commands.store

    def mutate(uow):
        if uow.repository.get_command(command_id) is None:
            uow.repository.insert_command(
                build_command_record(
                    command_id=command_id,
                    run_id="run-test",
                    node_id="source_finding",
                    idempotency_key=f"key:{command_id}",
                )
            )

    store.submit(mutate, force_flush=True).result(timeout=10)


def _build_worker(
    harness: GraphHarness,
    *,
    governance: GovernancePolicy | None,
    now_ms: int = FIXED_NOW_MS + 1000,
) -> GraphDispatchWorker:
    return GraphDispatchWorker(
        store=harness.commands.store,
        coordinator=harness.coordinator,
        owner_id="graph-worker-governance-test",
        now_provider=lambda: now_ms,
        governance=governance,
    )


def _fail_attempt(
    harness: GraphHarness,
    *,
    node_id: str,
    attempt: int,
    seq: int,
    worker: GraphDispatchWorker | None = None,
) -> None:
    """Land one failed receipt on ``node_id`` attempt ``attempt``."""
    harness.enqueue_graph_dispatch(
        "run-test",
        node_id,
        attempt,
        dispatch_kind="resume_action",
        receipt=ExecutionReceipt(
            action_id=f"act-fail-{node_id}-{attempt}-{seq}",
            node_run_id=f"nr-run-test-{node_id}-a{attempt}",
            outcome="failed",
            artifact_receipt_ids=(),
            execution_anchor_id=None,
            budget_receipt_id=None,
            problem=None,
            completed_at_ms=FIXED_NOW_MS,
        ),
        idempotency_key=f"governance-fail:{node_id}:{attempt}:{seq}",
    )
    (worker or harness.worker).run_once()


def _run_record(harness: GraphHarness):
    return harness.commands.store.get_run("run-test")


# --------------------------------------------------------------------- status


def test_paused_is_a_recoverable_hold_never_reached_from_blocked() -> None:
    assert WorkflowRunStatus.PAUSED.value == "paused"
    assert RunStatus.PAUSED.value == "paused"
    # Live statuses may park.
    assert can_pause_run(RunStatus.RUNNING)
    assert can_pause_run(RunStatus.CREATED)
    assert can_pause_run(RunStatus.WAITING_HUMAN)
    # A designed BLOCKED hold keeps its own recovery semantics — the
    # governance never hijacks it.
    assert not can_pause_run(RunStatus.BLOCKED)
    assert not can_transition_run(RunStatus.BLOCKED, RunStatus.PAUSED)
    # Recovery: the ordinary start/retry path writes RUNNING from PAUSED.
    assert can_transition_run(RunStatus.PAUSED, RunStatus.RUNNING)
    assert can_transition_run(RunStatus.PAUSED, RunStatus.WAITING_HUMAN)
    assert can_transition_run(RunStatus.PAUSED, RunStatus.BLOCKED)
    assert can_transition_run(RunStatus.PAUSED, RunStatus.RECONCILIATION_REQUIRED)
    # Operator overrides stay possible, but a paused run can never be
    # silently closed as a success.
    assert can_transition_run(RunStatus.PAUSED, RunStatus.FAILED)
    assert can_transition_run(RunStatus.PAUSED, RunStatus.CANCELLED)
    assert not can_transition_run(RunStatus.PAUSED, RunStatus.SUCCEEDED)
    # PAUSED is not a terminal status.
    from core.research.workflow.transitions import is_terminal_run

    assert not is_terminal_run(RunStatus.PAUSED)


def test_consecutive_error_count_is_a_trailing_streak() -> None:
    class _Row:
        def __init__(self, node_id: str, attempt: int, status: str) -> None:
            self.node_id = node_id
            self.attempt = attempt
            self.status = status

    assert consecutive_error_count([]) == 0
    assert (
        consecutive_error_count(
            [
                _Row("problem_understanding", 1, "succeeded"),
                _Row("hypothesis_design", 1, "failed"),
                _Row("hypothesis_design", 2, "failed"),
            ]
        )
        == 2
    )
    # Any non-failed terminal outcome resets the streak.
    assert (
        consecutive_error_count(
            [
                _Row("hypothesis_design", 1, "failed"),
                _Row("hypothesis_design", 2, "failed"),
                _Row("hypothesis_design", 3, "blocked"),
                _Row("hypothesis_design", 4, "failed"),
            ]
        )
        == 1
    )
    # STALE rows are superseded history and never break or count.
    assert (
        consecutive_error_count(
            [
                _Row("hypothesis_design", 1, "succeeded"),
                _Row("hypothesis_design", 1, "stale"),
                _Row("hypothesis_design", 2, "failed"),
            ]
        )
        == 1
    )


# ------------------------------------------------- consecutive-error pause


def test_consecutive_errors_pause_at_threshold_and_defer_new_starts(
    tmp_path: Path,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("hypothesis_design")
        for attempt in range(1, 5):
            _fail_attempt(harness, node_id="hypothesis_design", attempt=attempt, seq=attempt)
        run = _run_record(harness)
        assert run.status == "created"  # below threshold: unchanged

        # 5th consecutive failure parks the run in the same transaction.
        _fail_attempt(harness, node_id="hypothesis_design", attempt=5, seq=5)
        run = _run_record(harness)
        assert run.status == "paused"
        problem = json.loads(run.blocked_problem_json or "{}")
        assert problem["code"] == "consecutive_errors_paused"
        assert problem["pauseKind"] == "consecutive_errors"
        assert problem["consecutiveErrors"] == 5
        assert problem["threshold"] == 5
        assert problem["lastNodeId"] == "hypothesis_design"
        events = harness.commands.store.list_events("run-test")
        paused_events = [e for e in events if e.event_type == "run_paused"]
        assert len(paused_events) == 1

        # In-flight settlement receipts keep landing after the pause; only
        # NEW start dispatches are deferred.
        _fail_attempt(harness, node_id="hypothesis_design", attempt=5, seq=100)
        latest = harness.commands.store.latest_attempt(
            "run-test", "hypothesis_design"
        )
        assert latest is not None and latest.attempt == 5

        harness.enqueue_graph_dispatch("run-test", "hypothesis_design", 6)
        assert harness.worker.run_once() == 1
        pending = [
            row
            for row in harness.commands.store.list_pending_outbox("run-test")
            if row.action_kind == "graph_dispatch"
        ]
        assert len(pending) == 1
        assert json.loads(pending[0].last_problem_json or "{}")["code"] == "run_paused"
        attempts = harness.commands.store.list_attempts("run-test")
        attempt6 = next(a for a in attempts if a.attempt == 6)
        assert attempt6.status == "starting"  # never advanced, never blocked
        assert _run_record(harness).status == "paused"
    finally:
        harness.close()


def test_success_resets_the_consecutive_error_streak(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        # Ledger history: a failure streak that was interrupted by a success.
        # Directly seeded in commit order (the pause trigger reads the same
        # ledger truth), then real worker-driven failures continue the story.
        _seed_command(harness)
        store = harness.commands.store

        def seed_history() -> None:
            def mutate(uow):
                uow.repository.insert_attempt(
                    build_attempt_record(
                        node_run_id="nr-run-test-problem_understanding-a1",
                        run_id="run-test",
                        node_id="problem_understanding",
                        attempt=1,
                        status="succeeded",
                        command_id="cmd-governance-1",
                        started_at_ms=FIXED_NOW_MS - 10_000,
                    )
                )
                for offset, status in enumerate(
                    ("failed", "failed", "failed", "succeeded"), start=1
                ):
                    uow.repository.insert_attempt(
                        build_attempt_record(
                            node_run_id=f"nr-run-test-hypothesis_design-a{offset}",
                            run_id="run-test",
                            node_id="hypothesis_design",
                            attempt=offset,
                            status=status,
                            command_id="cmd-governance-1",
                            started_at_ms=FIXED_NOW_MS - 10_000 + offset,
                        )
                    )

            store.submit(mutate, force_flush=True).result(timeout=10)

        seed_history()
        # Real failure on top of the successful attempt: streak resets to 1.
        _fail_attempt(harness, node_id="hypothesis_design", attempt=5, seq=1)
        assert _run_record(harness).status == "created"

        # Four further real failures reach the threshold of five.
        for seq, attempt in enumerate(range(6, 10), start=2):
            _fail_attempt(harness, node_id="hypothesis_design", attempt=attempt, seq=seq)
        run = _run_record(harness)
        assert run.status == "paused"
        problem = json.loads(run.blocked_problem_json or "{}")
        assert problem["consecutiveErrors"] == 5
    finally:
        harness.close()


def test_consecutive_error_pause_disabled_by_policy(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("hypothesis_design")
        worker = _build_worker(
            harness,
            governance=GovernancePolicy(
                max_consecutive_errors=None,
                deadlock_detection_enabled=False,
            ),
        )
        for attempt in range(1, 9):
            _fail_attempt(
                harness,
                node_id="hypothesis_design",
                attempt=attempt,
                seq=attempt,
                worker=worker,
            )
        assert _run_record(harness).status == "created"
    finally:
        harness.close()


# --------------------------------------------------------- deadlock pause


def _seed_stuck_run(harness: GraphHarness, *, status: str = "running") -> None:
    harness.seed(status=status)
    _seed_command(harness)
    store = harness.commands.store

    def mutate(uow):
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id="nr-run-test-source_finding-a1",
                run_id="run-test",
                node_id="source_finding",
                attempt=1,
                status="blocked",
                command_id="cmd-governance-1",
                problem_json=json.dumps(
                    {"code": "graph_dispatch_invalid", "detail": "boom"}
                ),
            )
        )

    store.submit(mutate, force_flush=True).result(timeout=10)


def test_deadlock_sweep_parks_stranded_run_with_blocked_inventory(
    tmp_path: Path,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        _seed_stuck_run(harness)
        store = harness.commands.store
        paused = run_deadlock_sweep(
            store,
            policy=GovernancePolicy(),
            now_ms=FIXED_NOW_MS + 2000,
            actor_id="governance-test",
        )
        assert paused == 1
        run = store.get_run("run-test")
        assert run.status == "paused"
        problem = json.loads(run.blocked_problem_json or "{}")
        assert problem["code"] == "deadlock_paused"
        assert problem["pauseKind"] == "deadlock"
        assert problem["blockedNodes"] == [
            {
                "nodeId": "source_finding",
                "nodeRunId": "nr-run-test-source_finding-a1",
                "code": "graph_dispatch_invalid",
                "detail": "boom",
            }
        ]
        events = store.list_events("run-test")
        assert [e.event_type for e in events].count("run_paused") == 1

        # Idempotent: an already-paused run is never re-judged.
        assert (
            run_deadlock_sweep(
                store,
                policy=GovernancePolicy(),
                now_ms=FIXED_NOW_MS + 3000,
            )
            == 0
        )
        assert [e.event_type for e in store.list_events("run-test")].count(
            "run_paused"
        ) == 1
    finally:
        harness.close()


def test_deadlock_sweep_skips_designed_holds_and_recoverable_states(
    tmp_path: Path,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        store = harness.commands.store

        # A designed BLOCKED hold keeps its status and offers.
        _seed_stuck_run(harness, status="blocked")

        def set_status(status: str, seq: int) -> None:
            def mutate(uow):
                run = uow.repository.get_run("run-test")
                uow.repository.update_run_status(
                    "run-test", run.team_id, status, FIXED_NOW_MS + seq
                )

            store.submit(mutate, force_flush=True).result(timeout=10)

        policy = GovernancePolicy()
        assert run_deadlock_sweep(store, policy=policy, now_ms=FIXED_NOW_MS) == 0
        assert store.get_run("run-test").status == "blocked"

        # Queued outbox work means the run is not deadlocked.
        set_status("running", 1)

        def enqueue_outbox() -> None:
            def mutate(uow):
                uow.repository.insert_outbox(
                    build_outbox_record(
                        "act-stuck-1",
                        run_id="run-test",
                        command_id="cmd-governance-1",
                        status="pending",
                    )
                )

            store.submit(mutate, force_flush=True).result(timeout=10)

        enqueue_outbox()
        assert run_deadlock_sweep(store, policy=policy, now_ms=FIXED_NOW_MS) == 0
        assert store.get_run("run-test").status == "running"

        def clear_outbox() -> None:
            def mutate(uow):
                uow.repository.execute(
                    "DELETE FROM outbox_actions WHERE action_id = 'act-stuck-1'"
                )

            store.submit(mutate, force_flush=True).result(timeout=10)

        clear_outbox()

        # A waiting_human attempt is active work, not deadlock.
        def add_active_attempt() -> None:
            def mutate(uow):
                uow.repository.insert_attempt(
                    build_attempt_record(
                        node_run_id="nr-run-test-source_extraction-a1",
                        run_id="run-test",
                        node_id="source_extraction",
                        attempt=1,
                        status="waiting_human",
                        command_id="cmd-governance-1",
                    )
                )

            store.submit(mutate, force_flush=True).result(timeout=10)

        add_active_attempt()
        assert run_deadlock_sweep(store, policy=policy, now_ms=FIXED_NOW_MS) == 0

        def remove_active_attempt() -> None:
            def mutate(uow):
                uow.repository.execute(
                    "DELETE FROM node_attempts WHERE node_run_id = "
                    "'nr-run-test-source_extraction-a1'"
                )

            store.submit(mutate, force_flush=True).result(timeout=10)

        remove_active_attempt()

        # An accepted handoff without a successor attempt is repairable ready
        # work — the existing sweeps own it, not the deadlock pause.
        def add_orphan_handoff() -> None:
            def mutate(uow):
                uow.repository.execute(
                    """
                    INSERT INTO handoffs (
                      handoff_id, run_id, edge_id, from_node_run_id, to_node_id,
                      gate_kind, input_snapshot_hash, status, offered_at_ms
                    ) VALUES ('ho-1', 'run-test', 'e-1',
                              'nr-run-test-source_finding-a1', 'source_extraction',
                              'auto', 'h', 'accepted', ?)
                    """,
                    (FIXED_NOW_MS,),
                )

            store.submit(mutate, force_flush=True).result(timeout=10)

        add_orphan_handoff()
        assert run_deadlock_sweep(store, policy=policy, now_ms=FIXED_NOW_MS) == 0
        assert store.get_run("run-test").status == "running"

        # Policy off: nothing ever parks.
        assert (
            run_deadlock_sweep(
                store,
                policy=GovernancePolicy(
                    max_consecutive_errors=None,
                    deadlock_detection_enabled=False,
                ),
                now_ms=FIXED_NOW_MS,
            )
            == 0
        )
    finally:
        harness.close()


def test_classify_deadlock_requires_blocked_inventory() -> None:
    class _Row:
        def __init__(self, node_id: str, attempt: int, status: str) -> None:
            self.node_id = node_id
            self.node_run_id = f"nr-{node_id}-a{attempt}"
            self.attempt = attempt
            self.status = status
            self.problem_json = None

    # All-succeeded history with nothing active is completion drift, not a
    # blocked deadlock — no blocked inventory, no pause.
    assert (
        classify_deadlock([_Row("result_package", 1, "succeeded")], 0, set()) is None
    )
    verdict = classify_deadlock(
        [_Row("source_finding", 1, "blocked")], 0, set()
    )
    assert verdict is not None
    assert verdict.blocked_nodes[0]["nodeId"] == "source_finding"


# ------------------------------------------------------- node-type WIP cap


def test_node_type_wip_cap_requeues_without_block_or_stale(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("hypothesis_design")
        worker = _build_worker(
            harness,
            governance=GovernancePolicy(
                max_consecutive_errors=None,
                deadlock_detection_enabled=False,
                node_type_wip_limits={"hypothesis_design": 1},
            ),
        )
        # attempt 1 is in flight (dispatching); a second start dispatch of the
        # same node type stays queued for the next round.
        adapter_before = len(
            [
                row
                for row in harness.commands.store.list_pending_outbox("run-test")
                if row.action_kind == "adapter_dispatch"
            ]
        )
        harness.enqueue_graph_dispatch("run-test", "hypothesis_design", 2)
        assert worker.run_once() == 1
        pending = [
            row
            for row in harness.commands.store.list_pending_outbox("run-test")
            if row.action_kind == "graph_dispatch"
        ]
        assert len(pending) == 1
        assert json.loads(pending[0].last_problem_json or "{}")["code"] == (
            "node_type_wip_limit"
        )
        statuses = {
            (a.node_id, a.attempt): a.status
            for a in harness.commands.store.list_attempts("run-test")
        }
        assert statuses[("hypothesis_design", 1)] == "dispatching"  # untouched
        assert statuses[("hypothesis_design", 2)] == "starting"  # never ran
        adapter_after = len(
            [
                row
                for row in harness.commands.store.list_pending_outbox("run-test")
                if row.action_kind == "adapter_dispatch"
            ]
        )
        assert adapter_after == adapter_before  # no adapter work created
        assert _run_record(harness).status == "created"  # not blocked
        assert all(
            a.status != "stale"
            for a in harness.commands.store.list_attempts("run-test")
        )

        # Below the cap (own attempt excluded), the dispatch proceeds once
        # the gated requeue becomes available again.
        worker2 = _build_worker(harness, governance=None, now_ms=FIXED_NOW_MS + 60_000)
        assert worker2.run_once() == 1
        pending_after = [
            row
            for row in harness.commands.store.list_pending_outbox("run-test")
            if row.action_kind == "graph_dispatch"
        ]
        assert pending_after == []
        assert harness.latest_adapter_pending() is not None
        statuses_after = {
            (a.node_id, a.attempt): a.status
            for a in harness.commands.store.list_attempts("run-test")
        }
        assert statuses_after[("hypothesis_design", 2)] == "dispatching"
    finally:
        harness.close()


# --------------------------------------------------- default equivalence


def test_default_policy_keeps_scheduling_equivalent(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("hypothesis_design")
        # Default env (nothing set): one failure neither pauses nor defers.
        _fail_attempt(harness, node_id="hypothesis_design", attempt=1, seq=1)
        run = _run_record(harness)
        assert run.status == "created"
        # The retry start dispatch is NOT gated (WIP cap off by default).
        harness.enqueue_graph_dispatch("run-test", "hypothesis_design", 2)
        assert harness.worker.run_once() == 1
        assert harness.latest_adapter_pending() is not None
        # Deadlock sweep on a run with queued work never parks it.
        assert (
            run_deadlock_sweep(
                harness.commands.store,
                policy=GovernancePolicy.from_env(),
                now_ms=FIXED_NOW_MS + 5000,
            )
            == 0
        )
        assert _run_record(harness).status == "created"
    finally:
        harness.close()


def test_disabled_policy_is_fully_inert() -> None:
    policy = GovernancePolicy.disabled()
    assert policy.pause_gates_enabled is False
    assert policy.wip_enabled is False
    assert policy.max_consecutive_errors is None
    assert policy.deadlock_detection_enabled is False
    assert policy.wip_limit_for("hypothesis_design") is None


# -------------------------------------------------------------- resume


def test_resume_from_pause_clears_the_hold(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        _seed_stuck_run(harness)
        store = harness.commands.store
        assert (
            run_deadlock_sweep(store, policy=GovernancePolicy(), now_ms=FIXED_NOW_MS)
            == 1
        )
        run = store.get_run("run-test")
        assert run.status == "paused"
        assert resume_from_pause(
            store,
            run_id="run-test",
            team_id=run.team_id,
            now_ms=FIXED_NOW_MS + 1000,
            actor_id="operator-test",
        )
        resumed = store.get_run("run-test")
        assert resumed.status == "running"
        assert resumed.blocked_problem_json is None
        events = [e.event_type for e in store.list_events("run-test")]
        assert "run_resumed" in events
        # Idempotent: an already-resumed run is a no-op.
        assert not resume_from_pause(
            store,
            run_id="run-test",
            team_id=run.team_id,
            now_ms=FIXED_NOW_MS + 2000,
        )
    finally:
        harness.close()


def test_governance_sweep_method_parks_stranded_run(tmp_path: Path) -> None:
    # The worker method delegates to the sweep and stays fail-open.
    harness = GraphHarness(tmp_path / "sweep-worker")
    try:
        _seed_stuck_run(harness)
        worker = _build_worker(harness, governance=None)
        assert worker.run_governance_sweep() == 1
        assert harness.commands.store.get_run("run-test").status == "paused"
    finally:
        harness.close()
