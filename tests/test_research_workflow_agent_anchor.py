"""T5 RED: Agent anchors — complete anchor required for running; human gate
anchors bind humanTaskId; incomplete anchors never fake running."""

from __future__ import annotations

import json
from pathlib import Path

from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.action_registry import ActionRegistry
from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
    AdapterDispatchWorker,
)
from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
    AgentActionAdapter,
    HumanActionAdapter,
)
from tests._support.adapter_fakes import FakeDomainPorts
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


def _agent_action() -> PendingAction:
    return PendingAction(
        action_id="act-agent",
        run_id="run-test",
        node_run_id="nr-run-test-source_finding-a1",
        node_id="source_finding",
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="p-1",
    )


def _project_agent_action() -> PendingAction:
    return PendingAction(
        action_id="act-project-agent",
        run_id="run-test",
        node_run_id="nr-run-test-problem_understanding-a1",
        node_id="problem_understanding",
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="p-1",
    )


def _human_action() -> PendingAction:
    return PendingAction(
        action_id="act-human",
        run_id="run-test",
        node_run_id="nr-run-test-knowledge_handoff-a1",
        node_id="knowledge_handoff",
        attempt=1,
        actor_kind=ActorKind.HUMAN,
        action_kind="human_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="p-1",
    )


def _seed(harness: CommandHarness, action: PendingAction, attempt_node_id: str) -> None:
    from core.research.workflow.ledger import OutboxRecord

    def mutate(uow):
        if uow.repository.get_command("cmd-driver") is None:
            from tests._support.workflow_ledger_helpers import build_command_record
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-driver", run_id="run-test", idempotency_key="cmd-driver"
                )
            )
        from tests._support.workflow_ledger_helpers import build_attempt_record

        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=action.node_run_id,
                run_id=action.run_id,
                node_id=attempt_node_id,
                attempt=1,
                status="dispatching",
                command_id="cmd-driver",
                started_at_ms=FIXED_NOW_MS,
            )
        )
        uow.repository.insert_outbox(
            OutboxRecord(
                action_id=f"adapter-outbox-{action.action_id}",
                run_id=action.run_id,
                command_id="cmd-driver",
                node_run_id=action.node_run_id,
                action_kind="adapter_dispatch",
                idempotency_key=f"adapter:{action.action_id}",
                payload_json=json.dumps(action.to_dict()),
                status="pending",
                attempt_count=0,
                available_at_ms=FIXED_NOW_MS,
                lease_owner=None,
                lease_expires_at_ms=None,
                last_problem_json=None,
                created_at_ms=FIXED_NOW_MS,
                updated_at_ms=FIXED_NOW_MS,
            )
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def test_dispatch_publishes_provisional_anchor_and_moves_attempt_to_running(tmp_path: Path) -> None:
    """Turn accepted = real execution signal: anchor visible before the long turn."""

    from core.web.services.team_workflow.research_runtime.domain_ports import (
        AgentTaskHandle,
        BindingResolution,
    )
    from core.web.services.team_workflow.research_runtime.real_domain_ports import (
        publish_agent_task_started_anchor,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _agent_action()
        _seed(harness, action, "source_finding")
        binding = BindingResolution(agent_id="agent-finder", role_key="source_finder")
        handle = AgentTaskHandle(
            session_id="session-finding",
            session_attempt=1,
            task_id="stagetask-finding",
            turn_id="turn-finding",
        )

        def attempt_row():
            return harness.store.submit(
                lambda uow: uow.repository.get_attempt(action.node_run_id),
                force_flush=True,
            ).result(timeout=10)

        assert str(attempt_row().status) == "dispatching"
        assert str(attempt_row().execution_anchor_id or "") == ""

        publish_agent_task_started_anchor(
            harness.store, action=action, binding=binding, handle=handle
        )

        row = attempt_row()
        assert str(row.status) == "running"
        assert str(row.execution_anchor_id or "") != ""
        anchor = harness.store.submit(
            lambda uow: uow.repository.get_anchor_by_node_run(action.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert anchor is not None
        assert str(anchor[5] or "") == "session-finding"
        assert str(anchor[7] or "") == "stagetask-finding"
        assert str(anchor[8] or "") == "turn-finding"
        assert str(anchor[12] or "") == "running"
        anchor_json = json.loads(anchor[13])
        assert anchor_json.get("provisional") is True
        assert anchor_json.get("taskId") == "stagetask-finding"

        # The authoritative commit still lands on top of the provisional
        # anchor: the adapter worker finishes and the attempt reaches
        # succeeded with the anchor finalized.
        ports = FakeDomainPorts()
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports))
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda node: ("source_extraction",),
            now_provider=lambda: FIXED_NOW_MS + 1_000,
        )
        worker.run_once()
        row = attempt_row()
        assert str(row.status) == "succeeded"
        anchor = harness.store.submit(
            lambda uow: uow.repository.get_anchor_by_node_run(action.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert str(anchor[12] or "") == "bound"
        # The commit's own handle is authoritative and replaced the
        # provisional task identity.
        assert str(anchor[7] or "") == "task-act-agen"
    finally:
        harness.close()


def test_provisional_anchor_never_resurrects_terminal_attempt(tmp_path: Path) -> None:
    from core.web.services.team_workflow.research_runtime.domain_ports import (
        AgentTaskHandle,
        BindingResolution,
    )
    from core.web.services.team_workflow.research_runtime.real_domain_ports import (
        publish_agent_task_started_anchor,
    )
    from tests._support.workflow_ledger_helpers import (
        build_attempt_record,
        build_command_record,
        build_run_record,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:

        def mutate(uow):
            if uow.repository.get_run("run-test") is None:
                uow.repository.insert_run(build_run_record(run_id="run-test", last_event_sequence=1))
            if uow.repository.get_command("cmd-driver") is None:
                uow.repository.insert_command(
                    build_command_record(
                        command_id="cmd-driver", run_id="run-test", idempotency_key="cmd-driver"
                    )
                )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id="nr-run-test-source_finding-a1",
                    run_id="run-test",
                    node_id="source_finding",
                    attempt=1,
                    status="failed",
                    command_id="cmd-driver",
                    started_at_ms=FIXED_NOW_MS,
                )
            )

        harness.store.submit(mutate, force_flush=True).result(timeout=10)
        action = _agent_action()
        publish_agent_task_started_anchor(
            harness.store,
            action=action,
            binding=BindingResolution(agent_id="agent-finder", role_key="source_finder"),
            handle=AgentTaskHandle(
                session_id="session-finding",
                session_attempt=1,
                task_id="stagetask-finding",
                turn_id="turn-finding",
            ),
        )
        row = harness.store.submit(
            lambda uow: uow.repository.get_attempt(action.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert str(row.status) == "failed"
        assert harness.store.submit(
            lambda uow: uow.repository.get_anchor_by_node_run(action.node_run_id),
            force_flush=True,
        ).result(timeout=10) is None
    finally:
        harness.close()


def test_agent_anchor_must_be_complete_for_running(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        ports = FakeDomainPorts()
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports))
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda node: ("source_extraction",),
            now_provider=lambda: FIXED_NOW_MS + 1_000,
        )
        action = _agent_action()
        _seed(harness, action, "source_finding")
        worker.run_once()
        # 完整 anchor（session/task/turn）后 attempt 才能 succeeded。
        anchor = harness.store.submit(
            lambda uow: uow.repository.get_anchor_by_node_run(action.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert anchor is not None
        anchor_json = json.loads(anchor[13])
        assert all(
            anchor_json.get(key)
            for key in ("sessionId", "sessionAttempt", "taskId", "turnId")
        )
        # 事件记录 anchor bound。
        events = harness.store.list_events("run-test")
        assert any(e.event_type == "execution_anchor_bound" for e in events)
    finally:
        harness.close()


def test_incomplete_agent_anchor_never_marks_running(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        ports = FakeDomainPorts()

        class IncompletePorts(FakeDomainPorts):
            def create_agent_task(self, *, action):
                self.calls.append("create_agent_task")
                from core.web.services.team_workflow.research_runtime.domain_ports import (
                    AgentTaskHandle,
                )

                return AgentTaskHandle(session_id="", session_attempt=0, task_id="", turn_id="")

        ports = IncompletePorts()
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports))
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda node: ("source_extraction",),
            now_provider=lambda: FIXED_NOW_MS + 1_000,
        )
        action = _agent_action()
        _seed(harness, action, "source_finding")
        worker.run_once()
        attempt = harness.store.latest_attempt("run-test", "source_finding")
        # anchor 不完整：不允许 running——adapter 以不完整 anchor 完成时
        # attempt 直接 blocked（防止假 running）。
        assert attempt is not None
        assert attempt.status in ("blocked", "succeeded")
        if attempt.status == "succeeded":
            anchor = harness.store.submit(
                lambda uow: uow.repository.get_anchor_by_node_run(action.node_run_id),
                force_flush=True,
            ).result(timeout=10)
            assert anchor is not None
            anchor_json = json.loads(anchor[13])
            assert not all(
                anchor_json.get(key)
                for key in ("sessionId", "taskId", "turnId")
            )
    finally:
        harness.close()


def test_human_gate_anchor_binds_human_task(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        ports = FakeDomainPorts()
        registry = ActionRegistry()
        registry.register(HumanActionAdapter(ports))
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda node: ("hypothesis_design",),
            now_provider=lambda: FIXED_NOW_MS + 1_000,
        )
        action = _human_action()
        _seed(harness, action, "knowledge_handoff")
        worker.run_once()
        attempt = harness.store.latest_attempt("run-test", "knowledge_handoff")
        assert attempt is not None and attempt.status == "waiting_human"
        anchor = harness.store.submit(
            lambda uow: uow.repository.get_anchor_by_node_run(action.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert anchor is not None
        anchor_json = json.loads(anchor[13])
        assert anchor_json["humanTaskId"]
        # 人工门 handoff 等待人工。
        handoffs = harness.store.submit(
            lambda uow: uow.repository.get_handoff_by_from_node("run-test", action.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert handoffs is not None and handoffs[8] == "waiting_human"
        # human 不预留模型 token。
        assert ports.reservations == []
        assert "reserve_budget" not in ports.calls
    finally:
        harness.close()


def _worker(harness) -> AdapterDispatchWorker:
    ports = FakeDomainPorts()
    registry = ActionRegistry()
    registry.register(AgentActionAdapter(ports))
    return AdapterDispatchWorker(
        store=harness.store,
        registry=registry,
        ports=ports,
        successor_fn=lambda node: ("source_extraction",),
        now_provider=lambda: FIXED_NOW_MS + 1_000,
    )


def _leased_outbox(harness, action: PendingAction, *, attempt_count: int):
    """Lease the seeded outbox row and return the live record the worker sees."""
    from core.research.workflow.ledger.outbox import lease_ready_actions

    leased = lease_ready_actions(
        harness.store, owner="adapter-worker", now_ms=FIXED_NOW_MS, limit=1
    )
    assert leased and leased[0].action_id == f"adapter-outbox-{action.action_id}"
    record = leased[0]
    if attempt_count:
        from dataclasses import replace as _replace

        record = _replace(record, attempt_count=attempt_count)
    return record


def _outbox_row(harness, action_id: str):
    return harness.store.submit(
        lambda uow: uow.repository.get_outbox(action_id),
        force_flush=True,
    ).result(timeout=10)


def test_live_turn_wait_heartbeat_does_not_consume_transient_budget(
    tmp_path: Path,
) -> None:
    """A wait timeout on a still-running turn must requeue without failing,
    even past the transient attempt cap; attempts reset so the lease cap
    cannot starve a healthy long turn."""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _agent_action()
        _seed(harness, action, "source_finding")
        worker = _worker(harness)
        outbox = _leased_outbox(harness, action, attempt_count=99)

        worker._requeue_live_turn_wait(
            outbox,
            action,
            "turn_not_ready:running",
            snapshot={
                "terminal": False,
                "completionSource": "running",
                "challengeTaskStartedAtMs": FIXED_NOW_MS,
                "continuationRootTurnId": "turn-main",
                "continuationTurnId": "turn-cont-1",
                "continuationTurnChain": ["turn-main", "turn-cont-1"],
                "continuationsUsed": 1,
                "continuationNoProgressCount": 2,
            },
        )

        row = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert row is not None
        assert row.status == "pending"
        assert row.attempt_count == 0
        problem = json.loads(row.last_problem_json or "{}")
        assert problem["continuationRootTurnId"] == "turn-main"
        assert problem["continuationTurnId"] == "turn-cont-1"
        assert problem["continuationTurnChain"] == ["turn-main", "turn-cont-1"]
        assert problem["continuationsUsed"] == 1
        assert problem["continuationNoProgressCount"] == 2
        assert problem.get("code") == "live_turn_wait"
    finally:
        harness.close()


def test_live_turn_wait_wall_clock_cap_fails(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _agent_action()
        _seed(harness, action, "source_finding")
        worker = _worker(harness)
        outbox = _leased_outbox(harness, action, attempt_count=1)
        from dataclasses import replace as _replace

        stale = _replace(
            outbox,
            created_at_ms=FIXED_NOW_MS - worker._MAX_LIVE_TURN_WAIT_MS - 1_000,
        )
        worker._requeue_live_turn_wait(
            stale,
            action,
            "turn_not_ready:running",
            snapshot={
                "terminal": False,
                "completionSource": "running",
                "challengeTaskStartedAtMs": (
                    FIXED_NOW_MS - worker._MAX_LIVE_TURN_WAIT_MS - 1_000
                ),
            },
        )

        row = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert row is not None
        assert row.status == "failed"
        problem = json.loads(row.last_problem_json or "{}")
        assert problem.get("code") == "live_turn_wait_timeout"
    finally:
        harness.close()


def test_live_turn_wait_same_state_hits_no_progress_cap(tmp_path: Path) -> None:
    from dataclasses import replace as _replace

    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        live_turn_progress_fingerprint,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _agent_action()
        _seed(harness, action, "source_finding")
        worker = _worker(harness)
        outbox = _leased_outbox(harness, action, attempt_count=1)
        created_at_ms = FIXED_NOW_MS - worker._MAX_LIVE_TURN_NO_PROGRESS_MS
        snapshot = {
            "terminal": False,
            "completionSource": "running",
            "messageCount": 1,
            "activeTurnId": "turn-finding",
            # A truly silent turn: no in-flight signal.  A turnCurrent=True
            # snapshot is an actively executing model call and is never
            # no-progress (see test_challenge_logical_deadline_scale).
            "turnCurrent": False,
            "challengeTaskStartedAtMs": created_at_ms,
        }
        stalled = _replace(
            outbox,
            created_at_ms=created_at_ms,
            last_problem_json=json.dumps(
                {
                    "code": "live_turn_wait",
                    "lastProgressAtMs": created_at_ms,
                    "progressFingerprint": live_turn_progress_fingerprint(snapshot),
                }
            ),
        )

        worker._requeue_live_turn_wait(
            stalled,
            action,
            "turn_not_ready:running",
            snapshot=snapshot,
        )

        row = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert row is not None
        assert row.status == "failed"
        problem = json.loads(row.last_problem_json or "{}")
        assert problem["code"] == "live_turn_no_progress_timeout"
        assert problem["noProgressMs"] >= worker._MAX_LIVE_TURN_NO_PROGRESS_MS
        assert problem["waitedMs"] < worker._MAX_LIVE_TURN_WAIT_MS
    finally:
        harness.close()


def test_live_turn_wait_real_progress_resets_only_no_progress_clock() -> None:
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        decide_live_turn_wait,
        live_turn_progress_fingerprint,
    )

    created_at_ms = 1_000_000
    previous_snapshot = {
        "terminal": False,
        "completionSource": "running",
        "messageCount": 1,
        "activeTurnId": "turn-1",
    }
    current_snapshot = {**previous_snapshot, "messageCount": 2}
    decision = decide_live_turn_wait(
        now_ms=created_at_ms + 250_000,
        created_at_ms=created_at_ms,
        previous_problem={
            "code": "live_turn_wait",
            "lastProgressAtMs": created_at_ms,
            "progressFingerprint": live_turn_progress_fingerprint(previous_snapshot),
        },
        snapshot=current_snapshot,
    )

    assert decision.progress_advanced is True
    assert decision.no_progress_ms == 0
    assert decision.stop_code == ""

    # The absolute wait stop derives from the deadline contract (explicit
    # contract here; the bounded default applies when the dispatcher has no
    # contract -- see test_challenge_logical_deadline_scale).
    logical_timeout = decide_live_turn_wait(
        now_ms=created_at_ms + 300_000,
        created_at_ms=created_at_ms,
        previous_problem={
            "code": "live_turn_wait",
            "lastProgressAtMs": created_at_ms + 299_000,
            "progressFingerprint": live_turn_progress_fingerprint(previous_snapshot),
        },
        snapshot=current_snapshot,
        deadline_at_ms=created_at_ms + 300_000,
    )
    assert logical_timeout.stop_code == "live_turn_wait_timeout"
    assert logical_timeout.deadline_source == "task_bundle_contract"

    # Without a contract the same state stays inside the bounded default.
    within_default = decide_live_turn_wait(
        now_ms=created_at_ms + 300_000,
        created_at_ms=created_at_ms,
        previous_problem={
            "code": "live_turn_wait",
            "lastProgressAtMs": created_at_ms + 299_000,
            "progressFingerprint": live_turn_progress_fingerprint(previous_snapshot),
        },
        snapshot=current_snapshot,
    )
    assert within_default.stop_code == ""
    assert within_default.deadline_source == "bounded_default"


def test_live_turn_wait_cannot_reset_missing_task_clock_on_requeue(
    tmp_path: Path,
) -> None:
    from dataclasses import replace as _replace

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _agent_action()
        _seed(harness, action, "source_finding")
        worker = _worker(harness)
        outbox = _leased_outbox(harness, action, attempt_count=1)
        original_started_at_ms = FIXED_NOW_MS - 250_000
        persisted = _replace(
            outbox,
            created_at_ms=FIXED_NOW_MS - 200_000,
            last_problem_json=json.dumps(
                {
                    "code": "live_turn_wait",
                    "logicalTaskStartedAtMs": original_started_at_ms,
                    "lastProgressAtMs": original_started_at_ms,
                }
            ),
        )

        worker._requeue_live_turn_wait(
            persisted,
            action,
            "turn_not_ready:running",
            snapshot={
                "terminal": False,
                "completionSource": "running",
                # A missing canonical timestamp used to regenerate this
                # fallback on every dispatch and reset the deadline.
                "challengeTaskStartedAtMs": FIXED_NOW_MS,
            },
        )

        row = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert row is not None
        problem = json.loads(row.last_problem_json or "{}")
        assert problem["logicalTaskStartedAtMs"] == original_started_at_ms
        assert problem["waitedMs"] == 251_000
    finally:
        harness.close()


def _stale_outbox(harness, action: PendingAction, worker: AdapterDispatchWorker, *, attempt_count: int):
    from dataclasses import replace as _replace

    outbox = _leased_outbox(harness, action, attempt_count=attempt_count)
    return _replace(
        outbox,
        created_at_ms=FIXED_NOW_MS - worker._MAX_LIVE_TURN_WAIT_MS - 1_000,
        last_problem_json=json.dumps(
            {
                "code": "live_turn_wait",
                "logicalTaskStartedAtMs": (
                    FIXED_NOW_MS - worker._MAX_LIVE_TURN_WAIT_MS - 1_000
                ),
                "lastProgressAtMs": (
                    FIXED_NOW_MS - worker._MAX_LIVE_TURN_WAIT_MS - 1_000
                ),
            }
        ),
    )


def _publish_provisional_anchor(
    harness,
    action: PendingAction,
    *,
    task_id: str = "stagetask-finding",
    session_id: str = "session-finding",
    turn_id: str = "turn-finding",
) -> None:
    from core.web.services.team_workflow.research_runtime.domain_ports import (
        AgentTaskHandle,
        BindingResolution,
    )
    from core.web.services.team_workflow.research_runtime.real_domain_ports import (
        publish_agent_task_started_anchor,
    )

    publish_agent_task_started_anchor(
        harness.store,
        action=action,
        binding=BindingResolution(agent_id="agent-finder", role_key="source_finder"),
        handle=AgentTaskHandle(
            session_id=session_id,
            session_attempt=1,
            task_id=task_id,
            turn_id=turn_id,
        ),
    )


def test_live_turn_wait_timeout_reconciles_stage_task(monkeypatch, tmp_path: Path) -> None:
    """After the logical wall-clock cap fails the attempt, the abandoned wait must
    still run the pushed-writeback leg: the stage task store is reconciled from
    the anchor identity with interrupted semantics for a non-terminal turn."""
    import core.web.services.session.turn_diagnostics as turn_diagnostics
    import core.web.services.team_workflow.source_collection.stage_writeback as stage_writeback

    calls: list[dict] = []
    monkeypatch.setattr(
        stage_writeback,
        "reconcile_source_collection_stage_session_task_after_turn",
        lambda team_id, task_id, **kwargs: calls.append(
            {"teamId": team_id, "taskId": task_id, **kwargs}
        )
        or {"status": "reconciled", "taskStatus": "needs_review"},
    )
    monkeypatch.setattr(
        turn_diagnostics,
        "get_session_turn_completion_snapshot",
        lambda session_id, turn_id="": {
            "sessionId": session_id,
            "turnId": turn_id,
            "terminal": False,
            "terminalStatus": "",
            "completionSource": "running",
        },
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _agent_action()
        _seed(harness, action, "source_finding")
        _publish_provisional_anchor(harness, action)
        worker = _worker(harness)
        stale = _stale_outbox(harness, action, worker, attempt_count=1)

        worker._requeue_live_turn_wait(stale, action, "turn_not_ready:running")

        row = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert row is not None
        assert row.status == "failed"
        # The reconcile ran once with the dispatch anchor identity.
        assert len(calls) == 1
        call = calls[0]
        assert call["teamId"] == "research-team"
        assert call["taskId"] == "stagetask-finding"
        assert call["session_id"] == "session-finding"
        assert call["turn_id"] == "turn-finding"
        assert call["run_id"] == "run-test"
        assert call["final_status"] == "interrupted"
        assert call["reason"] == "live_turn_wait_timeout"
    finally:
        harness.close()


def test_live_turn_wait_timeout_stale_owner_does_not_reconcile_stage_task(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A worker that lost its outbox lease must not mutate the new owner's task."""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _agent_action()
        _seed(harness, action, "source_finding")
        worker = _worker(harness)
        stale = _stale_outbox(harness, action, worker, attempt_count=1)
        worker._owner = "stale-adapter-worker"
        reconciled: list[str] = []
        monkeypatch.setattr(
            worker,
            "_reconcile_stage_task_after_wait_timeout",
            lambda *_args, **_kwargs: reconciled.append("called"),
        )

        worker._requeue_live_turn_wait(stale, action, "turn_not_ready:running")

        assert reconciled == []
        row = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert row is not None
        assert row.status == "leased"
        assert row.lease_owner == "adapter-worker"
    finally:
        harness.close()


def test_logical_task_deadline_stale_owner_does_not_reconcile_stage_task(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """The direct deadline exception path obeys the same outbox ownership fence."""
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        ChallengeTaskDeadlineExceeded,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _agent_action()
        _seed(harness, action, "source_finding")
        worker = _worker(harness)
        outbox = _leased_outbox(harness, action, attempt_count=1)
        worker._owner = "stale-adapter-worker"
        reconciled: list[str] = []

        def raise_deadline(*_args, **_kwargs):
            raise ChallengeTaskDeadlineExceeded(
                {"code": "challenge_logical_task_deadline_exhausted"}
            )

        monkeypatch.setattr(worker, "_execute_with_lease_heartbeat", raise_deadline)
        monkeypatch.setattr(
            worker,
            "_reconcile_stage_task_after_wait_timeout",
            lambda *_args, **_kwargs: reconciled.append("called"),
        )

        worker._handle(outbox)

        assert reconciled == []
        row = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert row is not None
        assert row.status == "leased"
        assert row.lease_owner == "adapter-worker"
    finally:
        harness.close()


def test_live_turn_wait_timeout_closes_running_project_task(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import core.web.services.team_workflow.research_project_agent_tasks as project_tasks

    calls: list[dict] = []
    monkeypatch.setattr(
        project_tasks,
        "reconcile_research_project_agent_task_statuses",
        lambda team_id, project_id: calls.append(
            {"kind": "reconcile", "teamId": team_id, "projectId": project_id}
        )
        or {"checked": 1, "reconciled": 0},
    )
    monkeypatch.setattr(
        project_tasks,
        "_read_research_project_agent_task_record",
        lambda team_id, project_id, task_id: {
            "taskId": task_id,
            "status": "running",
            "resultRefs": [],
        },
    )

    def update_status(team_id, project_id, task_id, **kwargs):
        calls.append(
            {
                "kind": "update",
                "teamId": team_id,
                "projectId": project_id,
                "taskId": task_id,
                **kwargs,
            }
        )
        return {"taskId": task_id, "status": kwargs["status"]}

    monkeypatch.setattr(
        project_tasks,
        "update_research_project_agent_task_status",
        update_status,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _project_agent_action()
        _seed(harness, action, "problem_understanding")
        _publish_provisional_anchor(
            harness,
            action,
            task_id="project-task-1",
            session_id="session-project",
            turn_id="turn-project",
        )
        worker = _worker(harness)
        stale = _stale_outbox(harness, action, worker, attempt_count=1)

        worker._requeue_live_turn_wait(stale, action, "turn_not_ready:running")

        row = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert row is not None and row.status == "failed"
        update = next(item for item in calls if item["kind"] == "update")
        assert update == {
            "kind": "update",
            "teamId": "research-team",
            "projectId": "challenge-sci-096",
            "taskId": "project-task-1",
            "status": "timed_out",
            "result_refs": [],
            "failure_code": "live_turn_wait_timeout",
        }
    finally:
        harness.close()


def test_live_turn_wait_timeout_reconcile_error_is_swallowed(
    monkeypatch, tmp_path: Path
) -> None:
    """A failing stage-task reconcile must never break the failure path: the
    outbox attempt stays failed and the exception does not propagate."""
    import core.web.services.session.turn_diagnostics as turn_diagnostics
    import core.web.services.team_workflow.source_collection.stage_writeback as stage_writeback

    monkeypatch.setattr(
        stage_writeback,
        "reconcile_source_collection_stage_session_task_after_turn",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        turn_diagnostics,
        "get_session_turn_completion_snapshot",
        lambda session_id, turn_id="": {
            "sessionId": session_id,
            "turnId": turn_id,
            "terminal": True,
            "terminalStatus": "completed",
        },
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _agent_action()
        _seed(harness, action, "source_finding")
        _publish_provisional_anchor(harness, action)
        worker = _worker(harness)
        stale = _stale_outbox(harness, action, worker, attempt_count=1)

        worker._requeue_live_turn_wait(stale, action, "turn_not_ready:running")

        row = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert row is not None
        assert row.status == "failed"
        problem = json.loads(row.last_problem_json or "{}")
        assert problem.get("code") == "live_turn_wait_timeout"
    finally:
        harness.close()


def test_live_turn_wait_requeue_records_workflow_heartbeat(tmp_path: Path) -> None:
    """Each live-turn wait requeue appends one structured workflow event so a
    bounded long wait is visible in workflow_events (it used to be silent)."""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _agent_action()
        _seed(harness, action, "source_finding")
        worker = _worker(harness)
        outbox = _leased_outbox(harness, action, attempt_count=99)

        worker._requeue_live_turn_wait(
            outbox,
            action,
            "turn_not_ready:running",
            snapshot={
                "terminal": False,
                "completionSource": "running",
                "challengeTaskStartedAtMs": FIXED_NOW_MS,
            },
        )

        events = [
            event
            for event in harness.store.list_events("run-test")
            if event.event_type == "adapter_dispatch_live_turn_wait_heartbeat"
        ]
        assert len(events) == 1
        payload = json.loads(events[0].payload_json)
        assert payload["runId"] == "run-test"
        assert payload["actionId"] == "act-agent"
        assert payload["nodeId"] == "source_finding"
        assert payload["attemptCount"] == 99
        assert payload["waitedMs"] == 1_000
        assert payload["maxWaitMs"] == worker._MAX_LIVE_TURN_WAIT_MS
        assert payload["noProgressMs"] == 1_000
        assert payload["maxNoProgressMs"] == worker._MAX_LIVE_TURN_NO_PROGRESS_MS
        assert payload["progressAdvanced"] is False
        # The requeue itself is unchanged: pending with attempts reset.
        row = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert row is not None
        assert row.status == "pending"
        assert row.attempt_count == 0
    finally:
        harness.close()


def test_turn_alive_progressing_requires_running_source() -> None:
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
        _turn_alive_progressing,
    )
    from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
        TurnNotReadyError,
    )

    live = TurnNotReadyError(
        "wait",
        snapshot={"terminal": False, "completionSource": "running"},
    )
    receipt_pending = TurnNotReadyError(
        "wait",
        snapshot={
            "terminal": False,
            "completionSource": "receipt_registry_pending",
        },
    )
    terminal = TurnNotReadyError(
        "wait", snapshot={"terminal": True, "completionSource": "last_turn_status"}
    )
    ambiguous = TurnNotReadyError("wait", snapshot={"terminal": False})
    empty = TurnNotReadyError("wait")

    assert _turn_alive_progressing(live) is True
    assert _turn_alive_progressing(receipt_pending) is True
    assert _turn_alive_progressing(terminal) is False
    assert _turn_alive_progressing(ambiguous) is False
    assert _turn_alive_progressing(empty) is False


def test_turn_alive_progressing_rejects_terminal_receipt_pending() -> None:
    """Turn 已终态但 receipt registry 仍 pending 时不得继续空等：
    _turn_alive_progressing 必须放行到快速失败路径，turn 未终态时仍续等。"""
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
        _receipt_persistence_pending_terminal,
        _turn_alive_progressing,
    )
    from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
        TurnNotReadyError,
    )

    terminal_receipt_pending = TurnNotReadyError(
        "model invocation receipt persistence is pending",
        snapshot={
            "terminal": False,
            "terminalStatus": "",
            "completionSource": "receipt_registry_pending",
            "turnTerminal": True,
            "turnTerminalStatus": "completed",
            "receiptPersistencePending": True,
        },
    )
    running_receipt_pending = TurnNotReadyError(
        "wait",
        snapshot={
            "terminal": False,
            "completionSource": "receipt_registry_pending",
            "turnTerminal": False,
            "receiptPersistencePending": True,
        },
    )

    assert _receipt_persistence_pending_terminal(terminal_receipt_pending) is True
    assert _receipt_persistence_pending_terminal(running_receipt_pending) is False
    assert _turn_alive_progressing(terminal_receipt_pending) is False
    assert _turn_alive_progressing(running_receipt_pending) is True


def test_receipt_persistence_pending_terminal_fails_fast_with_dedicated_code(
    tmp_path: Path,
) -> None:
    """终态 turn 的 receipt 永不落库时必须快速失败（专用 code），不再走
    10 分钟 live-wait 空等。"""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _agent_action()
        _seed(harness, action, "source_finding")
        worker = _worker(harness)
        outbox = _leased_outbox(harness, action, attempt_count=99)

        worker._requeue_receipt_persistence_pending(
            outbox,
            action,
            "model invocation receipt persistence is pending",
            snapshot={"turnTerminalStatus": "completed"},
        )

        row = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert row is not None
        assert row.status == "failed"
        problem = json.loads(row.last_problem_json or "{}")
        assert problem.get("code") == "receipt_persistence_pending_terminal"
        assert problem.get("turnTerminalStatus") == "completed"
    finally:
        harness.close()


def test_receipt_persistence_pending_within_budget_requeues_with_dedicated_problem(
    tmp_path: Path,
) -> None:
    """transient 预算内仍先重排（慢 receipt worker 有界重试），problem 带专用 code。"""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _agent_action()
        _seed(harness, action, "source_finding")
        worker = _worker(harness)
        outbox = _leased_outbox(harness, action, attempt_count=1)

        worker._requeue_receipt_persistence_pending(
            outbox,
            action,
            "model invocation receipt persistence is pending",
        )

        row = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert row is not None
        assert row.status == "pending"
        problem = json.loads(row.last_problem_json or "{}")
        assert problem.get("code") == "receipt_persistence_pending"
    finally:
        harness.close()


def test_project_task_reconcile_lag_is_live_progressing(monkeypatch) -> None:
    """turn 完成但 project task 记录仍在 running：等待必须走 live-wait，
    不得消耗 transient 预算（慢模型下 5 次重排就误判 transient_exhausted）。"""
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
        _turn_alive_progressing,
    )
    from core.web.services.team_workflow.research_runtime import (
        agent_turn_completion,
    )
    from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
        TurnNotReadyError,
    )

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_agent_tasks.reconcile_research_project_agent_task_statuses",
        lambda _team_id, _project_id: None,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_project_agent_tasks._read_research_project_agent_task_record",
        lambda _team_id, _project_id, _task_id: {
            "taskId": "research-agent-task-lag",
            "status": "running",
        },
    )

    try:
        agent_turn_completion._require_project_task_terminal(
            team_id="research-team",
            project_id="project-1",
            task_id="research-agent-task-lag",
        )
    except TurnNotReadyError as exc:
        snapshot = dict(getattr(exc, "snapshot", None) or {})
        assert snapshot.get("terminal") is False
        assert snapshot.get("completionSource") == "running"
        assert _turn_alive_progressing(exc) is True
    else:
        raise AssertionError("expected TurnNotReadyError for a lagging task record")
