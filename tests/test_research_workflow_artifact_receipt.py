"""T5 RED: artifact receipt and handoff gating — unreadable or hash-mismatched
artifacts block the attempt and never produce an accepted handoff."""

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


def _action() -> PendingAction:
    return PendingAction(
        action_id="act-1",
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
                action_id="adapter-outbox-1",
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


def test_hash_mismatch_blocks_and_handoff_stays_pending(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        ports = FakeDomainPorts()
        ports.fail_artifact_hash = True
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports))
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda node: ("source_extraction",),
        )
        action = _action()
        _seed(harness, action)
        worker.run_once()
        attempt = harness.store.latest_attempt("run-test", "source_finding")
        assert attempt is not None and attempt.status == "blocked"
        assert "artifact_hash_mismatch" in (attempt.problem_json or "")
        # 没有 receipt、没有 handoff、没有 resume dispatch。
        receipts = harness.store.submit(
            lambda uow: uow.repository.list_receipts_for_node_run(action.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert receipts == []
        handoffs = harness.store.submit(
            lambda uow: uow.repository.get_handoff_by_from_node("run-test", action.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert handoffs is None
    finally:
        harness.close()


def test_unreadable_artifact_blocks_without_receipt(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        ports = FakeDomainPorts()
        ports.artifact_store.clear()

        class MissingStore(FakeDomainPorts):
            def read_back_artifact(self, canonical_ref: str):
                self.calls.append("read_back_artifact")
                return None

        ports = MissingStore()
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports))
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda node: ("source_extraction",),
        )
        action = _action()
        _seed(harness, action)
        worker.run_once()
        attempt = harness.store.latest_attempt("run-test", "source_finding")
        assert attempt is not None and attempt.status == "blocked"
        assert "artifact_unreadable" in (attempt.problem_json or "")
    finally:
        harness.close()


def test_verified_handoff_receipts_are_recorded(tmp_path: Path) -> None:
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
        action = _action()
        _seed(harness, action)
        worker.run_once()
        handoffs = harness.store.submit(
            lambda uow: uow.repository.get_handoff_by_from_node("run-test", action.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert handoffs is not None and handoffs[8] == "ready"
        receipt_ids = harness.store.submit(
            lambda uow: uow.repository.list_handoff_receipts(handoffs[0]),
            force_flush=True,
        ).result(timeout=10)
        assert len(receipt_ids) == 1
    finally:
        harness.close()
