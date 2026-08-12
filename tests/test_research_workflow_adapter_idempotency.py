"""T5 RED: adapter idempotency + Agent anchor + budget ordering.

The stable actionId drives idempotent budget reservation and task creation;
a second execution after a crash reuses the same reservation and task and
never re-runs the agent turn twice. Agent attempts only enter running with
a complete anchor. Budget reservation happens strictly after readiness
read-back and strictly before task creation.
"""

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
)
from tests._support.adapter_fakes import FakeDomainPorts
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


def _action(action_id: str = "act-1") -> PendingAction:
    return PendingAction(
        action_id=action_id,
        run_id="run-test",
        node_run_id=f"nr-run-test-source_finding-a1",
        node_id="source_finding",
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="p-1",
    )


def _seed(harness: CommandHarness, action: PendingAction) -> None:
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
                node_id=action.node_id,
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


def _worker(
    harness: CommandHarness, ports: FakeDomainPorts, *, commit_hook=None, now_offset: int = 1000
) -> AdapterDispatchWorker:
    registry = ActionRegistry()
    registry.register(AgentActionAdapter(ports))
    return AdapterDispatchWorker(
        store=harness.store,
        registry=registry,
        ports=ports,
        successor_fn=lambda node: ("source_extraction",),
        commit_hook=commit_hook,
        now_provider=lambda: FIXED_NOW_MS + now_offset,
    )


def test_budget_reserved_before_task_creation(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        ports = FakeDomainPorts()
        worker = _worker(harness, ports)
        _seed(harness, _action())
        worker.run_once()
        assert ports.order("read_back_input", "reserve_budget", "create_agent_task")
        assert ports.reservations == ["act-1"]
    finally:
        harness.close()


def test_action_id_idempotent_rerun_reuses_reservation_and_task(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        ports = FakeDomainPorts()
        crashes = {"crashed": False}

        def crash_once():
            if not crashes["crashed"]:
                crashes["crashed"] = True
                raise RuntimeError("simulated crash before commit")

        worker = _worker(harness, ports, commit_hook=crash_once)
        _seed(harness, _action())
        worker.run_once()
        # 第一次提交前崩溃：无任何提交产物。
        assert harness.store.latest_event_sequence("run-test") == 1
        attempt = harness.store.latest_attempt("run-test", "source_finding")
        assert attempt is not None and attempt.status == "dispatching"
        assert len(ports.tasks_by_action) == 1
        assert ports.calls.count("execute_agent_turn") == 1

        # 重跑同一 outbox（lease 过期重领取）：domain 复用、agent turn 不重复。
        worker2 = _worker(harness, ports, now_offset=7000)
        worker2.run_once()
        assert len(ports.tasks_by_action) == 1
        assert ports.calls.count("execute_agent_turn") == 1
        attempt = harness.store.latest_attempt("run-test", "source_finding")
        assert attempt is not None and attempt.status == "succeeded"
    finally:
        harness.close()


def test_agent_anchor_complete_before_running(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        ports = FakeDomainPorts()
        worker = _worker(harness, ports)
        action = _action()
        _seed(harness, action)
        worker.run_once()
        attempt = harness.store.latest_attempt("run-test", "source_finding")
        assert attempt is not None and attempt.status == "succeeded"
        anchor = harness.store.submit(
            lambda uow: uow.repository.get_anchor_by_node_run(action.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert anchor is not None
        anchor_json = json.loads(anchor[13])
        assert anchor_json["sessionId"]
        assert anchor_json["taskId"]
        assert anchor_json["turnId"]
        assert anchor_json["sessionAttempt"] == 1
        # running 状态必须由完整 anchor 支撑（事件里记录了 anchor bound）。
        events = harness.store.list_events("run-test")
        assert any(event.event_type == "execution_anchor_bound" for event in events)
    finally:
        harness.close()


def test_verified_flow_writes_receipts_handoff_and_resume_dispatch(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        ports = FakeDomainPorts()
        worker = _worker(harness, ports)
        action = _action()
        _seed(harness, action)
        worker.run_once()
        receipts = harness.store.submit(
            lambda uow: uow.repository.list_receipts_for_node_run(action.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert len(receipts) == 1
        assert receipts[0][7] == "a" * 64  # sha256 已校验
        handoffs = harness.store.submit(
            lambda uow: uow.repository.get_handoff_by_from_node("run-test", action.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert handoffs is not None
        assert handoffs[8] == "ready"
        resume_rows = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT action_kind FROM outbox_actions WHERE action_kind = 'graph_dispatch'"
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert len(resume_rows) == 1
    finally:
        harness.close()
