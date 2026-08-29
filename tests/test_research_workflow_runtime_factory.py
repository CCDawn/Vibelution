"""P1-3 RED: production composition root + real DomainReadinessContext.

build_workflow_runtime wires Ledger + coordinator + readiness + real ports +
real context into a single runtime; RealDomainReadinessContext reads frozen
input snapshot (budget limits, binding, adapter registry, question) instead of
returning fakes.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.web.services.team_workflow.research_runtime.real_readiness_context import (
    RealDomainReadinessContext,
)
from core.web.services.team_workflow.research_runtime.runtime_factory import (
    build_workflow_runtime,
)
from tests._support.workflow_ledger_helpers import build_run_record


def _seed_with_snapshot(store, *, run_id: str = "run-test") -> None:
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
        "researchObjectiveContract": {"question": "How to win?"},
        "sourcePolicy": {},
        "budgetPolicy": {
            "stageBudgets": {
                "knowledge_collection": {"tokens": 1000, "toolCalls": 5}
            }
        },
        "stopPolicy": {},
        "environmentSnapshotRef": "env-1",
        "modelRoutingPolicy": {},
        "evaluationContract": {},
        "agentBindingSnapshot": [
            {
                "snapshotId": f"snap:{run_id}:source_finding",
                "nodeId": "source_finding",
                "agentId": "agent-real-1",
                "roleKey": "source_finder",
            }
        ],
        "createdBy": "u-1",
        "createdAt": "2026-08-12T00:00:00Z",
        "snapshotHash": "c" * 64,
    }
    # The run is intentionally fresh for production-worker coverage.  The P0
    # reconciliation must still reap genuinely stale ``created`` runs, so do
    # not seed this fixture with the historical fixed timestamp.
    record = build_run_record(
        run_id=run_id,
        last_event_sequence=1,
        created_at_ms=int(time.time() * 1000),
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
            __import__("tests._support.workflow_ledger_helpers", fromlist=["build_event_record"]).build_event_record(
                sequence=1,
                run_id=run_id,
                event_type="run_created",
                event_id=f"evt-created-{run_id}",
            )
        )

    store.submit(mutate, force_flush=True).result(timeout=10)


def test_composition_root_wires_full_runtime(tmp_path: Path) -> None:
    runtime = build_workflow_runtime(tmp_path / "ledger.sqlite3")
    try:
        assert runtime.store is not None
        assert runtime.coordinator is not None
        assert runtime.readiness is not None
        assert runtime.ports is not None
        assert runtime.registry is not None
        assert runtime.command_service is not None
        assert runtime.graph_worker is not None
        assert runtime.adapter_worker is not None
        assert runtime.receipt_persistence_worker is not None
        # registry 覆盖全部 16 节点 adapter kind。
        from core.research.workflow.definition import (
            build_challenge_cup_workflow_definition,
        )
        from core.research.workflow.models import ActorKind

        definition = build_challenge_cup_workflow_definition()
        for node in definition.nodes:
            if node.actorKind == ActorKind.AGENT:
                kind = "start_agent_task"
            elif node.actorKind == ActorKind.SYSTEM:
                kind = f"system_action:{node.nodeId}"
            else:
                kind = f"human_task:{node.nodeId}"
            assert runtime.registry.get(kind) is not None, f"missing {kind}"
    finally:
        runtime.close()


def test_real_context_reads_frozen_snapshot_data(tmp_path: Path) -> None:
    runtime = build_workflow_runtime(tmp_path / "ledger.sqlite3")
    try:
        _seed_with_snapshot(runtime.store)
        context = runtime.readiness_context

        question = context.question_snapshot("research-team", "SCI-096")
        assert question is not None
        assert question["question"] == "How to win?"

        budget = context.budget_limits("research-team", "run-test")
        assert budget.stage_tokens_limit == 1000
        assert budget.max_tool_calls == 5

        binding = context.binding_snapshot("run-test", "source_finding")
        assert binding is not None
        assert binding["agentId"] == "agent-real-1"
        assert binding["roleKey"] == "source_finder"

        # Agent Directory is authoritative: unknown ids are not resolvable.
        assert context.agent_resolvable("agent-real-1") is False
        assert context.adapter_registered("source_finding") is True
        assert context.adapter_registered("controlled_run") is True
        assert context.adapter_registered("knowledge_handoff") is True
    finally:
        runtime.close()


def test_real_context_returns_conservative_missing(tmp_path: Path) -> None:
    runtime = build_workflow_runtime(tmp_path / "ledger.sqlite3")
    try:
        _seed_with_snapshot(runtime.store)
        context = runtime.readiness_context
        # 未接线领域：保守返回 None（节点不会误判 ready）。
        assert context.candidate_stats("research-team", "run-test") is None
        assert context.evidence_cards_stats("research-team", "run-test") is None
        assert context.knowledge_package("research-team", "run-test") is None
    finally:
        runtime.close()


def test_composition_root_command_flow_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime import readiness_providers

    monkeypatch.setattr(
        readiness_providers, "is_agent_resolvable", lambda agent_id: bool(agent_id)
    )
    runtime = build_workflow_runtime(tmp_path / "ledger.sqlite3")
    try:
        _seed_with_snapshot(runtime.store)
        from core.research.workflow.contracts import ActorRef, CommandRequest
        from core.web.services.team_workflow.research_runtime.operator_authorization import (
            server_operator_scope,
        )

        request = CommandRequest(
            command_id="cmd-client",
            run_id="run-test",
            team_id="research-team",
            command=WorkflowCommandKind.START_NODE,
            node_id="source_finding",
            expected_run_version=1,
            idempotency_key="ui:compose-1",
            payload={},
            requested_by=ActorRef("user", "u-1"),
            requested_at_ms=1_750_000_000_000,
        )
        with server_operator_scope("u-1", roles=("operator",)):
            receipt = runtime.command_service.submit(request)
        assert receipt.status == "accepted"
        run = runtime.store.get_run("run-test")
        assert run is not None and run.run_version == 2
    finally:
        runtime.close()


def _pending_graph_dispatch(store, run_id: str):
    return store.submit(
        lambda uow: [
            item
            for item in uow.repository.list_pending_outbox(run_id)
            if item.action_kind == "graph_dispatch"
        ],
        force_flush=True,
    ).result(timeout=10)


def test_production_runtime_drains_graph_dispatch_without_manual_run_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from core.research.workflow.challenge_cup_runtime import (
        GraphDispatchResult,
        build_pending_action,
    )
    from core.research.workflow.contracts import ActorRef, CommandRequest
    from core.web.services.team_workflow.research_runtime import readiness_providers
    from core.web.services.team_workflow.research_runtime.operator_authorization import (
        server_operator_scope,
    )
    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        production_workflow_runtime,
        start_production_workflow_runtime,
        stop_production_workflow_runtime,
    )

    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(
        readiness_providers, "is_agent_resolvable", lambda agent_id: bool(agent_id)
    )
    stop_production_workflow_runtime()
    try:
        assert start_production_workflow_runtime() == "ready"
        runtime = production_workflow_runtime()
        assert runtime is not None

        def fake_snapshot(_run_id: str, _workflow_version_id: str = "") -> dict:
            return {"values": {}, "nextNodeIds": [], "checkpointId": ""}

        def fake_start(dispatch):
            state = {
                "run_id": dispatch.run_id,
                "active_node_id": dispatch.node_id,
                "active_attempt": dispatch.attempt,
                "node_attempts": {dispatch.node_id: dispatch.attempt},
                "input_snapshot_hash": dispatch.input_snapshot_hash,
                "binding_snapshot_id": dispatch.binding_snapshot_id,
                "budget_policy_hash": dispatch.budget_policy_hash,
            }
            return GraphDispatchResult(
                dispatch_kind="start",
                pending_action=build_pending_action(state, dispatch.node_id),
                next_node_ids=(dispatch.node_id,),
                checkpoint_id="ckpt-test",
                state=state,
            )

        monkeypatch.setattr(runtime.coordinator, "snapshot", fake_snapshot)
        monkeypatch.setattr(runtime.coordinator, "start_attempt", fake_start)
        monkeypatch.setattr(runtime.adapter_worker, "run_once", lambda limit=8: 0)
        monkeypatch.setattr(runtime.fork_worker, "run_once", lambda limit=8: 0)

        _seed_with_snapshot(runtime.store)
        request = CommandRequest(
            command_id="cmd-prod-pump",
            run_id="run-test",
            team_id="research-team",
            command=WorkflowCommandKind.START_NODE,
            node_id="source_finding",
            expected_run_version=1,
            idempotency_key="ui:prod-pump-1",
            payload={},
            requested_by=ActorRef("user", "u-1"),
            requested_at_ms=1_750_000_000_000,
        )
        with server_operator_scope("u-1", roles=("operator",)):
            receipt = runtime.command_service.submit(request)
        assert receipt.status == "accepted"

        deadline = time.time() + 5
        pending = _pending_graph_dispatch(runtime.store, "run-test")
        attempt = runtime.store.latest_attempt("run-test", "source_finding")
        while time.time() < deadline and (
            pending
            or attempt is None
            or attempt.status == "starting"
        ):
            time.sleep(0.05)
            pending = _pending_graph_dispatch(runtime.store, "run-test")
            attempt = runtime.store.latest_attempt("run-test", "source_finding")
        assert pending == []
        assert attempt is not None
        assert attempt.status != "starting"
    finally:
        stop_production_workflow_runtime()
