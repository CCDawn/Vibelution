"""T5.1-1 RED: default Agent task adapters + adapter-worker exception containment.

Production RealDomainPorts must map every Agent node (including source_*) onto a
canonical task adapter. AdapterDispatchWorker must never leave Attempt in
dispatching / Outbox in leased when execute/preflight/read-back/verify raises.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.research.workflow.contracts import PendingAction
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.action_registry import ActionRegistry
from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
    AdapterDispatchWorker,
)
from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
    AgentActionAdapter,
)
from core.web.services.team_workflow.research_runtime.real_domain_ports import (
    RealDomainPorts,
    _task_kind_for,
)
from tests._support.adapter_fakes import FakeDomainPorts
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


AGENT_NODE_IDS = tuple(
    node.nodeId
    for node in build_challenge_cup_workflow_definition().nodes
    if node.actorKind == ActorKind.AGENT
)


def test_task_adapter_registry_covers_every_agent_node() -> None:
    from core.web.services.team_workflow.research_runtime.task_adapter_registry import (
        resolve_agent_task_adapter,
    )

    missing = [node_id for node_id in AGENT_NODE_IDS if resolve_agent_task_adapter(node_id) is None]
    assert missing == [], f"Agent nodes missing task adapters: {missing}"


def test_real_domain_ports_task_kind_covers_source_finding() -> None:
    # Legacy helper must not reject the production first node.
    assert _task_kind_for("source_finding") is not None
    assert _task_kind_for("source_extraction") is not None
    assert _task_kind_for("evidence_relations") is not None
    assert _task_kind_for("knowledge_ingestion") is not None


def test_real_ports_create_agent_task_rejects_unknown_with_stable_code(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        ports = RealDomainPorts(harness.store)
        action = PendingAction(
            action_id="act-unknown",
            run_id="run-test",
            node_run_id="nr-run-test-unknown-a1",
            node_id="not_a_real_node",
            attempt=1,
            actor_kind=ActorKind.AGENT,
            action_kind="start_agent_task",
            input_snapshot_hash="a" * 64,
            input_artifact_refs=(),
            binding_snapshot_id=None,
            budget_policy_hash="p-1",
        )
        with pytest.raises(RuntimeError, match="has no task adapter"):
            ports.create_agent_task(action=action)
    finally:
        harness.close()


def _seed_dispatching(harness: CommandHarness, action: PendingAction) -> None:
    from core.research.workflow.ledger import OutboxRecord
    from tests._support.workflow_ledger_helpers import (
        build_attempt_record,
        build_command_record,
        build_event_record,
        build_run_record,
    )

    def mutate(uow):
        if uow.repository.get_run(action.run_id) is None:
            uow.repository.insert_run(build_run_record(run_id=action.run_id, last_event_sequence=1))
            uow.repository.insert_event(
                build_event_record(
                    sequence=1,
                    run_id=action.run_id,
                    event_type="run_created",
                    event_id=f"evt-created-{action.run_id}",
                )
            )
        if uow.repository.get_command("cmd-driver") is None:
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-driver",
                    run_id=action.run_id,
                    idempotency_key="cmd-driver",
                )
            )
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


@pytest.mark.parametrize(
    "boom_phase",
    ("read_back_input", "preflight", "execute", "verify"),
)
def test_adapter_worker_contains_phase_exceptions(tmp_path: Path, boom_phase: str) -> None:
    harness = CommandHarness(tmp_path / f"ledger-{boom_phase}.sqlite3")
    try:
        action = PendingAction(
            action_id="act-boom",
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
        _seed_dispatching(harness, action)

        class BoomPorts(FakeDomainPorts):
            def read_back_input(self, action):  # type: ignore[override]
                if boom_phase == "read_back_input":
                    raise RuntimeError("boom-readback")
                return super().read_back_input(action)

            def create_agent_task(self, *, action):  # type: ignore[override]
                if boom_phase == "execute":
                    raise RuntimeError("boom-execute")
                return super().create_agent_task(action=action)

            def read_back_artifact(self, canonical_ref: str):  # type: ignore[override]
                if boom_phase == "verify":
                    raise RuntimeError("boom-verify")
                return super().read_back_artifact(canonical_ref)

        ports = BoomPorts()
        registry = ActionRegistry()
        adapter = AgentActionAdapter(ports)

        if boom_phase == "preflight":
            original_preflight = adapter.preflight

            def exploding_preflight(action):
                raise RuntimeError("boom-preflight")

            adapter.preflight = exploding_preflight  # type: ignore[method-assign]
            _ = original_preflight

        registry.register(adapter)
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda _node: (),
        )
        # Must not raise out of the worker.
        worker.run_once()

        attempt = harness.store.latest_attempt(action.run_id, action.node_id)
        assert attempt is not None
        assert attempt.status in {"failed", "blocked", "reconciliation_required"}
        assert attempt.status != "dispatching"

        outbox_rows = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status FROM outbox_actions WHERE action_id = ?",
                (f"adapter-outbox-{action.action_id}",),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert outbox_rows is not None
        assert outbox_rows[0] != "leased"
    finally:
        harness.close()
