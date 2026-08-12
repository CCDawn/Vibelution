"""T5 RED: adapter read-back — inputs verified before any side effect;
mismatch blocks the attempt with zero budget/task side effects."""

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


def _make_action(*, action_id: str = "act-1", node_id: str = "source_finding") -> PendingAction:
    return PendingAction(
        action_id=action_id,
        run_id="run-test",
        node_run_id=f"nr-run-test-{node_id}-a1",
        node_id=node_id,
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="p-1",
    )


def _seed_adapter_dispatch(harness: CommandHarness, action: PendingAction) -> None:
    def mutate(uow):
        if uow.repository.get_command("cmd-driver") is None:
            from tests._support.workflow_ledger_helpers import build_command_record
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-driver", run_id="run-test", idempotency_key="cmd-driver"
                )
            )
        uow.repository.insert_outbox(
            _adapter_outbox(action)
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _adapter_outbox(action: PendingAction):
    from core.research.workflow.ledger import OutboxRecord

    from tests._support.workflow_ledger_helpers import FIXED_NOW_MS

    return OutboxRecord(
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


def test_input_readback_happens_before_any_side_effect(tmp_path: Path) -> None:
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
            successor_fn=lambda node: ("source_extraction",) if node == "source_finding" else (),
        )
        action = _make_action()
        _ensure_command(harness)
        harness.store.submit(
            lambda uow: uow.repository.insert_attempt(
                _attempt(action)
            ),
            force_flush=True,
        ).result(timeout=10)
        _seed_adapter_dispatch(harness, action)

        worker.run_once()
        assert ports.calls[0] == "read_back_input"
        assert ports.order("read_back_input", "reserve_budget", "create_agent_task", "execute_agent_turn")
        assert "read_back_artifact" in ports.calls
    finally:
        harness.close()


def test_input_readback_mismatch_blocks_without_budget(tmp_path: Path) -> None:
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
        action = _make_action()
        _ensure_command(harness)
        harness.store.submit(
            lambda uow: uow.repository.insert_attempt(_attempt(action)),
            force_flush=True,
        ).result(timeout=10)
        _seed_adapter_dispatch(harness, action)

        worker.run_once()
        # 零预算、零任务副作用。
        assert ports.reservations == []
        assert ports.tasks_by_action == {}
        assert "create_agent_task" not in ports.calls
        attempt = harness.store.latest_attempt("run-test", "source_finding")
        assert attempt is not None and attempt.status == "blocked"
        assert "input_readback_mismatch" in (attempt.problem_json or "")
    finally:
        harness.close()


def test_preflight_failure_blocks_without_side_effects(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        ports = FakeDomainPorts()
        ports.input_ok = {"act-preflight": False}
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports))
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda node: ("source_extraction",),
        )
        action = _make_action(action_id="act-preflight")
        _ensure_command(harness)
        harness.store.submit(
            lambda uow: uow.repository.insert_attempt(_attempt(action)),
            force_flush=True,
        ).result(timeout=10)
        _seed_adapter_dispatch(harness, action)
        worker.run_once()
        assert ports.reservations == []
        assert ports.tasks_by_action == {}
        attempt = harness.store.latest_attempt("run-test", "source_finding")
        assert attempt is not None and attempt.status == "blocked"
    finally:
        harness.close()


def _ensure_command(harness: CommandHarness) -> None:
    def mutate(uow):
        if uow.repository.get_command("cmd-driver") is None:
            from tests._support.workflow_ledger_helpers import build_command_record

            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-driver", run_id="run-test", idempotency_key="cmd-driver"
                )
            )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _attempt(action: PendingAction):
    from tests._support.workflow_ledger_helpers import FIXED_NOW_MS, build_attempt_record

    return build_attempt_record(
        node_run_id=action.node_run_id,
        run_id=action.run_id,
        node_id=action.node_id,
        attempt=action.attempt,
        status="dispatching",
        command_id="cmd-driver",
        started_at_ms=FIXED_NOW_MS,
    )
