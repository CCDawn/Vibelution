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

        worker._requeue_live_turn_wait(outbox, action, "turn_not_ready:running")

        row = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert row is not None
        assert row.status == "pending"
        assert row.attempt_count == 0
        problem = json.loads(row.last_problem_json or "{}")
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
        worker._requeue_live_turn_wait(stale, action, "turn_not_ready:running")

        row = _outbox_row(harness, f"adapter-outbox-{action.action_id}")
        assert row is not None
        assert row.status == "failed"
        problem = json.loads(row.last_problem_json or "{}")
        assert problem.get("code") == "live_turn_wait_timeout"
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
    terminal = TurnNotReadyError(
        "wait", snapshot={"terminal": True, "completionSource": "last_turn_status"}
    )
    ambiguous = TurnNotReadyError("wait", snapshot={"terminal": False})
    empty = TurnNotReadyError("wait")

    assert _turn_alive_progressing(live) is True
    assert _turn_alive_progressing(terminal) is False
    assert _turn_alive_progressing(ambiguous) is False
    assert _turn_alive_progressing(empty) is False


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
        "core.web.services.team_workflow.research_project_agent_tasks.get_research_project_agent_task_status",
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
