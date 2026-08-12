"""P1-2 RED: Graph->Adapter action kind contract on every node.

The graph derives `human_task:{node}` and `system_action:{node}` kinds; the
registry must register every node's exact kind so the adapter worker never
fails with adapter_not_registered on a real run. The definition node set and
the registry key set must match one-to-one for adapter kinds.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.research.workflow.contracts import PendingAction
from core.research.workflow.definition import (
    build_challenge_cup_workflow_definition,
)
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.action_registry import ActionRegistry
from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
    AdapterDispatchWorker,
)
from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
    register_default_adapters,
)
from tests._support.adapter_fakes import FakeDomainPorts
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


def _action_for(node_id: str, actor_kind: ActorKind, attempt: int = 1) -> PendingAction:
    if actor_kind == ActorKind.AGENT:
        action_kind = "start_agent_task"
    elif actor_kind == ActorKind.SYSTEM:
        action_kind = f"system_action:{node_id}"
    else:
        action_kind = f"human_task:{node_id}"
    return PendingAction(
        action_id=f"act-{node_id}-{attempt}",
        run_id="run-test",
        node_run_id=f"nr-run-test-{node_id}-a{attempt}",
        node_id=node_id,
        attempt=attempt,
        actor_kind=actor_kind,
        action_kind=action_kind,
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
                    command_id="cmd-driver",
                    run_id="run-test",
                    idempotency_key="cmd-driver",
                )
            )
        from tests._support.workflow_ledger_helpers import build_attempt_record

        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=action.node_run_id,
                run_id=action.run_id,
                node_id=action.node_id,
                attempt=action.attempt,
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


def test_registry_registers_every_node_exact_action_kind() -> None:
    ports = FakeDomainPorts()
    registry = register_default_adapters(ActionRegistry(), ports)

    definition = build_challenge_cup_workflow_definition()
    expected: set[str] = set()
    for node in definition.nodes:
        if node.actorKind == ActorKind.AGENT:
            expected.add("start_agent_task")
        elif node.actorKind == ActorKind.SYSTEM:
            expected.add(f"system_action:{node.nodeId}")
        else:
            expected.add(f"human_task:{node.nodeId}")

    assert registry.kinds() == expected
    # 每个节点 kind 都能解析到 adapter。
    for node in definition.nodes:
        kind = "start_agent_task" if node.actorKind == ActorKind.AGENT else (
            f"system_action:{node.nodeId}"
            if node.actorKind == ActorKind.SYSTEM
            else f"human_task:{node.nodeId}"
        )
        assert registry.get(kind) is not None, f"missing adapter for {kind}"


def _run_adapter_for_node(
    harness: CommandHarness, ports: FakeDomainPorts, node_id: str, actor_kind: ActorKind
) -> None:
    registry = register_default_adapters(ActionRegistry(), ports)
    worker = AdapterDispatchWorker(
        store=harness.store,
        registry=registry,
        ports=ports,
        successor_fn=lambda node: (),
    )
    action = _action_for(node_id, actor_kind)
    _seed(harness, action)
    worker.run_once()
    outbox = harness.store.submit(
        lambda uow: uow.repository.get_outbox(f"adapter-outbox-{action.action_id}"),
        force_flush=True,
    ).result(timeout=10)
    assert outbox is not None
    if outbox.status == "failed":
        problem = json.loads(outbox.last_problem_json or "{}")
        assert problem.get("code") != "adapter_not_registered", (
            f"{node_id} adapter_not_registered: {problem}"
        )


def test_every_human_and_system_node_resolves_adapter(tmp_path: Path) -> None:
    definition = build_challenge_cup_workflow_definition()
    for node in definition.nodes:
        if node.actorKind == ActorKind.HUMAN or node.actorKind == ActorKind.SYSTEM:
            harness = CommandHarness(tmp_path / f"ledger-{node.nodeId}.sqlite3")
            try:
                harness.seed_run()
                _run_adapter_for_node(harness, FakeDomainPorts(), node.nodeId, node.actorKind)
            finally:
                harness.close()


def test_every_agent_node_resolves_adapter(tmp_path: Path) -> None:
    definition = build_challenge_cup_workflow_definition()
    for node in definition.nodes:
        if node.actorKind == ActorKind.AGENT:
            harness = CommandHarness(tmp_path / f"ledger-{node.nodeId}.sqlite3")
            try:
                harness.seed_run()
                _run_adapter_for_node(harness, FakeDomainPorts(), node.nodeId, node.actorKind)
            finally:
                harness.close()
