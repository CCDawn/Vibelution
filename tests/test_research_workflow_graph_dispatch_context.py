"""P1-1 RED: GraphDispatch payload carries every frozen field.

A start_node command must emit a graph_dispatch outbox whose payload has
nodeId, attempt, teamId, workflowVersionId, inputSnapshotHash,
bindingSnapshotId and budgetPolicyHash — the coordinator (challenge_cup_runtime)
needs them so a non-starting node never boots from source_finding and the
binding/budget freeze stays consistent. The factory is the only writer.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.research.workflow.contracts import WorkflowCommandKind
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


def _seed_run_with_snapshot(harness: CommandHarness) -> None:
    import json as _json

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
                "agentId": "agent-a",
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
        input_snapshot_json=_json.dumps(input_snapshot, ensure_ascii=False),
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


def test_start_node_dispatch_payload_carries_frozen_fields(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_run_with_snapshot(harness)
        harness.service.submit(harness.request())

        outbox = harness.store.list_pending_outbox("run-test")
        assert len(outbox) == 1
        assert outbox[0].action_kind == "graph_dispatch"
        payload = json.loads(outbox[0].payload_json)
        assert payload["commandId"] == outbox[0].command_id
        assert payload["runId"] == "run-test"
        assert payload["nodeRunId"] == "nr-run-test-source_finding-a1"
        assert payload["nodeId"] == "source_finding"
        assert payload["attempt"] == 1
        assert payload["teamId"] == "research-team"
        assert payload["workflowVersionId"] == "challenge-cup-research-v2.1.0"
        assert payload["inputSnapshotHash"] == "c" * 64
        assert payload["bindingSnapshotId"] == "snap:run-test:source_finding"
        assert payload["budgetPolicyHash"] == (
            "8b1cbcba0c1e4b6d2e10bcb0a87c0cac5d45b04f9bbbbf4a"
        ) or isinstance(payload["budgetPolicyHash"], str) and len(
            payload["budgetPolicyHash"]
        ) == 64

        attempt = harness.store.latest_attempt("run-test", "source_finding")
        assert attempt is not None
        assert attempt.binding_snapshot_id == "snap:run-test:source_finding"
    finally:
        harness.close()


def test_factory_builds_complete_payload_without_command_service(tmp_path: Path) -> None:
    from core.web.services.team_workflow.research_runtime.graph_dispatch_factory import (
        binding_snapshot_id_for_node,
        budget_policy_hash_from_input_snapshot,
        build_graph_dispatch_payload,
    )
    from tests._support.workflow_ledger_helpers import build_attempt_record

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_run_with_snapshot(harness)
        run = harness.store.get_run("run-test")
        assert run is not None
        attempt = build_attempt_record(
            node_run_id="nr-run-test-protocol_design-a1",
            run_id="run-test",
            node_id="protocol_design",
            attempt=1,
            status="starting",
            command_id="cmd-x",
        )
        payload = build_graph_dispatch_payload(
            run=run,
            attempt=attempt,
            command_id="cmd-x",
            dispatch_kind="start",
        )
        assert payload["nodeId"] == "protocol_design"
        assert payload["teamId"] == "research-team"
        assert payload["workflowVersionId"] == "challenge-cup-research-v2.1.0"
        assert payload["inputSnapshotHash"] == "c" * 64
        assert len(payload["budgetPolicyHash"]) == 64
        # 无该节点 binding 快照时不伪造 bindingSnapshotId。
        assert "bindingSnapshotId" not in payload

        payload_source = build_graph_dispatch_payload(
            run=run,
            attempt=build_attempt_record(
                node_run_id="nr-run-test-source_finding-a1",
                run_id="run-test",
                node_id="source_finding",
                attempt=1,
                status="starting",
                command_id="cmd-x",
            ),
            command_id="cmd-x",
            dispatch_kind="start",
        )
        assert payload_source["bindingSnapshotId"] == "snap:run-test:source_finding"

        input_snapshot = json.loads(run.input_snapshot_json)
        assert budget_policy_hash_from_input_snapshot(input_snapshot) == payload["budgetPolicyHash"]
        assert (
            binding_snapshot_id_for_node(input_snapshot, "source_finding")
            == "snap:run-test:source_finding"
        )
        assert binding_snapshot_id_for_node(input_snapshot, "unknown") is None
    finally:
        harness.close()


def test_legacy_input_snapshot_without_policy_yields_empty_hash(tmp_path: Path) -> None:
    from core.web.services.team_workflow.research_runtime.graph_dispatch_factory import (
        build_graph_dispatch_payload,
    )
    from tests._support.workflow_ledger_helpers import build_attempt_record

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        run = harness.store.get_run("run-test")
        assert run is not None
        attempt = build_attempt_record(
            node_run_id="nr-run-test-source_finding-a1",
            run_id="run-test",
            node_id="source_finding",
            attempt=1,
            status="starting",
            command_id="cmd-x",
        )
        payload = build_graph_dispatch_payload(
            run=run,
            attempt=attempt,
            command_id="cmd-x",
            dispatch_kind="start",
        )
        assert payload["teamId"] == "research-team"
        assert payload["inputSnapshotHash"] == "a" * 64
        # 无 budgetPolicy/agentBindingSnapshot 的旧 snapshot：空 hash + 无 binding。
        assert payload["budgetPolicyHash"] == ""
        assert "bindingSnapshotId" not in payload
    finally:
        harness.close()
