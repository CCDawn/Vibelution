"""T5 RED: budget ordering — readiness read-back before reservation, budget
before task creation, one terminal state per reservation, human nodes never
reserve."""

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


def _action(*, action_id: str, node_id: str, actor: ActorKind, action_kind: str) -> PendingAction:
    return PendingAction(
        action_id=action_id,
        run_id="run-test",
        node_run_id=f"nr-run-test-{node_id}-a1",
        node_id=node_id,
        attempt=1,
        actor_kind=actor,
        action_kind=action_kind,
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="p-1",
    )


def _seed(harness: CommandHarness, action: PendingAction, node_id: str) -> None:
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
                node_id=node_id,
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


def test_budget_never_reserved_when_readiness_readback_fails(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        ports = FakeDomainPorts()
        ports.fail_input_readback = True
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports))
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda node: ("source_extraction",),
        )
        action = _action(
            action_id="act-1", node_id="source_finding", actor=ActorKind.AGENT, action_kind="start_agent_task"
        )
        _seed(harness, action, "source_finding")
        worker.run_once()
        assert ports.reservations == []
        assert "reserve_budget" not in ports.calls
        assert ports.order("read_back_input")
    finally:
        harness.close()


def test_human_adapter_never_reserves_budget(tmp_path: Path) -> None:
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
        action = _action(
            action_id="act-human",
            node_id="knowledge_handoff",
            actor=ActorKind.HUMAN,
            action_kind="human_task",
        )
        _seed(harness, action, "knowledge_handoff")
        worker.run_once()
        assert ports.reservations == []
        assert "reserve_budget" not in ports.calls
        # 但 human task 已创建（无 token 消耗）。
        assert len(ports.human_tasks_by_action) == 1
    finally:
        harness.close()


def test_reservation_has_single_terminal_settlement(tmp_path: Path) -> None:
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
        action = _action(
            action_id="act-1", node_id="source_finding", actor=ActorKind.AGENT, action_kind="start_agent_task"
        )
        _seed(harness, action, "source_finding")
        worker.run_once()
        budget_receipt = harness.store.submit(
            lambda uow: uow.repository.get_budget_receipt("br-placeholder"),
            force_flush=True,
        ).result(timeout=10)
        # receipt id 是随机生成的；通过 reservation 查 budget_receipts。
        rows = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status FROM budget_receipts WHERE reservation_id = 'res-act-1'"
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert len(rows) == 1
        assert rows[0][0] == "settled"
    finally:
        harness.close()
