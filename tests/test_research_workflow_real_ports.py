"""P1-4 RED: real Agent binding resolution + authoritative budget lifecycle.

The adapter must resolve agentId/roleKey from the frozen RunAgentBindingSnapshot
(never `agent-{node_id}` fakes), propagate the authoritative reservation from
reserve_budget into the ledger budget_receipt, and call settle_budget after the
receipt commit so ledger "settled" reflects the domain budget authority.
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
from core.web.services.team_workflow.research_runtime.domain_ports import AgentTaskHandle
from core.web.services.team_workflow.research_runtime.real_domain_ports import (
    RealDomainPorts,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


def _seed_run_with_binding(harness: CommandHarness) -> None:
    from tests._support.workflow_ledger_helpers import (
        build_event_record,
        build_run_record,
    )

    input_snapshot = {
        "teamId": "research-team",
        "projectId": "challenge-sci-096",
        "questionId": "SCI-096",
        "workflowVersionId": "challenge-cup-research-v2.1.0",
        "researchBriefHash": "b" * 64,
        "datasetRefs": [],
        "metricContract": {},
        "constraintSnapshot": {},
        "competitionRuleRef": "rule",
        "competitionRuleVersion": "1",
        "trackAndRubricSnapshot": {},
        "researchObjectiveContract": {},
        "sourcePolicy": {},
        "budgetPolicy": {"stageBudgets": {"knowledge_collection": {"tokens": 250000}}},
        "stopPolicy": {},
        "environmentSnapshotRef": "env-1",
        "modelRoutingPolicy": {},
        "evaluationContract": {},
        "agentBindingSnapshot": [
            {
                "snapshotId": "snap:run-test:source_finding",
                "nodeId": "source_finding",
                "agentId": "agent-real-1",
                "roleKey": "source_finder",
            }
        ],
        "createdBy": "u-1",
        "createdAt": "2026-08-12T00:00:00Z",
        "snapshotHash": "c" * 64,
    }
    record = build_run_record(
        run_id="run-test",
        last_event_sequence=1,
        input_snapshot_hash="c" * 64,
    )
    record = record.__class__(
        run_id=record.run_id,
        team_id=record.team_id,
        workflow_id=record.workflow_id,
        workflow_version_id=record.workflow_version_id,
        thread_id=record.thread_id,
        project_id=record.project_id,
        question_id=record.question_id,
        status=record.status,
        run_version=record.run_version,
        last_event_sequence=record.last_event_sequence,
        input_snapshot_json=json.dumps(input_snapshot, ensure_ascii=False),
        input_snapshot_hash=record.input_snapshot_hash,
        safety_limits_json=record.safety_limits_json,
        binding_snapshot_set_id=record.binding_snapshot_set_id,
        active_node_id=record.active_node_id,
        parent_run_id=record.parent_run_id,
        forked_from_checkpoint_id=record.forked_from_checkpoint_id,
        completion_kind=record.completion_kind,
        terminal_reason=record.terminal_reason,
        blocked_problem_json=record.blocked_problem_json,
        created_at_ms=record.created_at_ms,
        updated_at_ms=record.updated_at_ms,
        completed_at_ms=record.completed_at_ms,
    )

    def mutate(uow):
        uow.repository.insert_run(record)
        uow.repository.insert_event(
            build_event_record(
                sequence=1,
                run_id="run-test",
                event_type="run_created",
                event_id="evt-created-run-test",
            )
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _action(node_id: str = "source_finding") -> PendingAction:
    return PendingAction(
        action_id="act-1",
        run_id="run-test",
        node_run_id=f"nr-run-test-{node_id}-a1",
        node_id=node_id,
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="c" * 64,
        input_artifact_refs=(),
        binding_snapshot_id="snap:run-test:source_finding",
        budget_policy_hash="p-1",
    )


def _seed_adapter(harness: CommandHarness, action: PendingAction) -> None:
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


def test_real_ports_resolve_binding_from_frozen_snapshot(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_run_with_binding(harness)
        ports = RealDomainPorts(harness.store)
        action = _action()
        binding = ports.resolve_binding(action)
        assert binding.agent_id == "agent-real-1"
        assert binding.role_key == "source_finder"
        assert binding.binding_snapshot_id == "snap:run-test:source_finding"
        verdict = ports.read_back_input(action)
        assert verdict.ok
    finally:
        harness.close()


def test_real_ports_resolve_binding_missing_node_yields_empty(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_run_with_binding(harness)
        ports = RealDomainPorts(harness.store)
        binding = ports.resolve_binding(_action(node_id="protocol_design"))
        assert binding.agent_id == ""
        assert binding.role_key == ""
    finally:
        harness.close()


def test_adapter_uses_real_binding_and_settles_budget(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_run_with_binding(harness)

        settled: list[dict] = []

        def task_factory(*, action, binding):
            return AgentTaskHandle(
                session_id=f"session-{action.node_id}",
                session_attempt=1,
                task_id=f"task-{action.node_id}",
                turn_id=f"turn-{action.node_id}",
            )

        class SettleRecordingPorts(RealDomainPorts):
            def settle_budget(self, *, reservation, usage):
                settled.append({"reservation": reservation, "usage": usage})
                super().settle_budget(reservation=reservation, usage=usage)

        ports = SettleRecordingPorts(harness.store, agent_task_factory=task_factory)
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports, estimate_tokens=100))
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda node: ("source_extraction",),
        )
        action = _action()
        _seed_adapter(harness, action)
        worker.run_once()

        anchor = harness.store.submit(
            lambda uow: uow.repository.get_anchor_by_node_run(action.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert anchor is not None
        anchor_json = json.loads(anchor[13])
        assert anchor_json["agentId"] == "agent-real-1"
        assert anchor_json["roleKey"] == "source_finder"
        assert anchor_json["reservationId"] == "reservation-nr-run-test-source_finding-a1"
        assert anchor_json["sessionId"] == "session-source_finding"

        receipts = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT reservation_id, status FROM budget_receipts WHERE node_run_id = ?",
                (action.node_run_id,),
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert len(receipts) == 1
        assert receipts[0][0] == "reservation-nr-run-test-source_finding-a1"
        assert receipts[0][1] == "settled"

        # settle_budget 被调用，且 usage 被传递。
        assert len(settled) == 1
        assert settled[0]["reservation"]["reservationId"] == receipts[0][0]
        assert settled[0]["usage"]["estimate_tokens"] == 100
    finally:
        harness.close()


def test_reserve_idempotent_same_action_reuses_reservation(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_run_with_binding(harness)
        ports = RealDomainPorts(harness.store)
        action = _action()
        first = ports.reserve_budget(action=action, estimate_tokens=100)
        second = ports.reserve_budget(action=action, estimate_tokens=100)
        assert first["reservationId"] == second["reservationId"]
        assert first["reservationId"] == "reservation-nr-run-test-source_finding-a1"
        assert "nodeRunId" in first
        assert first["status"] == "reserved"
    finally:
        harness.close()
