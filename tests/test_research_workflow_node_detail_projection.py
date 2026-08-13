"""T6.6G: formal NodeDetail projection from Snapshot + WorkflowDefinition."""

from __future__ import annotations

from pathlib import Path

from core.web.services.team_workflow.research_runtime.query_service import (
    NodeNotFoundError,
    WorkflowQueryService,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


FIXED_GENERATED_AT = "2026-08-12T14:00:00.000Z"


def test_node_detail_includes_definition_and_attempt_fields(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-node")
        harness.service.submit(
            harness.request(run_id="run-node", idempotency_key="seed-start")
        )
        query = WorkflowQueryService(
            store=harness.store,
            readiness_service=harness.readiness,
            readiness_context=lambda: harness.context,
            clock_iso=lambda: FIXED_GENERATED_AT,
            evaluated_at_ms=lambda: FIXED_NOW_MS,
        )
        detail = query.get_node_detail(
            team_id="research-team",
            run_id="run-node",
            node_id="source_finding",
        )
        payload = detail.to_dict()
        assert payload["nodeId"] == "source_finding"
        assert payload["actorKind"] == "agent"
        assert payload["label"]
        assert payload["primaryRoleKey"]
        assert payload["runtimeCurrent"] is True
        assert payload["attempts"]
        assert payload["latestAttempt"]["nodeId"] == "source_finding"
        assert payload["latestEventSequence"] >= 1
        assert "commandOffers" in payload
        assert payload["sessionAnchorDegraded"] is True
        assert payload["chatDeepLink"] is None
    finally:
        harness.close()


def _insert_anchor(
    harness: CommandHarness,
    *,
    node_run_id: str,
    agent_id: str,
    session_id: str | None,
    task_id: str | None,
    turn_id: str | None,
) -> None:
    def mutate(uow) -> None:
        uow.repository.insert_anchor(
            anchor_id=f"anchor-{node_run_id}",
            node_run_id=node_run_id,
            actor_kind="agent",
            agent_id=agent_id,
            role_key="source_finder",
            session_id=session_id,
            session_attempt=1,
            task_id=task_id,
            turn_id=turn_id,
            anchor_json="{}",
            created_at_ms=FIXED_NOW_MS,
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _query(harness: CommandHarness) -> WorkflowQueryService:
    return WorkflowQueryService(
        store=harness.store,
        readiness_service=harness.readiness,
        readiness_context=lambda: harness.context,
        clock_iso=lambda: FIXED_GENERATED_AT,
        evaluated_at_ms=lambda: FIXED_NOW_MS,
    )


def test_node_detail_projects_complete_session_anchor(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-anchor")
        harness.service.submit(
            harness.request(run_id="run-anchor", idempotency_key="seed-start")
        )
        query = _query(harness)
        seeded = query.get_node_detail(
            team_id="research-team",
            run_id="run-anchor",
            node_id="source_finding",
        )
        assert seeded.latest_attempt is not None
        _insert_anchor(
            harness,
            node_run_id=seeded.latest_attempt.node_run_id,
            agent_id="agent-finder",
            session_id="session-1",
            task_id="task-1",
            turn_id="turn-1",
        )
        payload = query.get_node_detail(
            team_id="research-team",
            run_id="run-anchor",
            node_id="source_finding",
        ).to_dict()
        assert payload["agentId"] == "agent-finder"
        assert payload["sessionId"] == "session-1"
        assert payload["taskId"] == "task-1"
        assert payload["turnId"] == "turn-1"
        assert payload["sessionAnchorDegraded"] is False
        link = str(payload["chatDeepLink"] or "")
        assert "session=session-1" in link
        assert "focusTask=task-1" in link
        assert "focusTurn=turn-1" in link
        assert "returnTo=" in link
    finally:
        harness.close()


def test_node_detail_degrades_incomplete_agent_anchor(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-degraded")
        harness.service.submit(
            harness.request(run_id="run-degraded", idempotency_key="seed-start")
        )
        query = _query(harness)
        seeded = query.get_node_detail(
            team_id="research-team",
            run_id="run-degraded",
            node_id="source_finding",
        )
        assert seeded.latest_attempt is not None
        _insert_anchor(
            harness,
            node_run_id=seeded.latest_attempt.node_run_id,
            agent_id="agent-finder",
            session_id="session-only",
            task_id=None,
            turn_id=None,
        )
        payload = query.get_node_detail(
            team_id="research-team",
            run_id="run-degraded",
            node_id="source_finding",
        ).to_dict()
        assert payload["sessionId"] == "session-only"
        assert payload["sessionAnchorDegraded"] is True
        assert payload["chatDeepLink"] is None
    finally:
        harness.close()


def test_node_detail_rejects_unknown_node(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-node")
        query = WorkflowQueryService(
            store=harness.store,
            readiness_service=harness.readiness,
            readiness_context=lambda: harness.context,
            clock_iso=lambda: FIXED_GENERATED_AT,
            evaluated_at_ms=lambda: FIXED_NOW_MS,
        )
        try:
            query.get_node_detail(
                team_id="research-team",
                run_id="run-node",
                node_id="missing-node",
            )
            raise AssertionError("expected NodeNotFoundError")
        except NodeNotFoundError:
            pass
    finally:
        harness.close()


def test_node_detail_uses_frozen_binding_when_anchor_missing(tmp_path: Path) -> None:
    import json as _json

    from tests._support.workflow_ledger_helpers import (
        build_event_record,
        build_run_record,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
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
            "budgetPolicy": {},
            "stopPolicy": {},
            "environmentSnapshotRef": "env-1",
            "modelRoutingPolicy": {},
            "evaluationContract": {},
            "agentBindingSnapshot": [
                {
                    "snapshotId": "snap:run-bound:source_finding",
                    "nodeId": "source_finding",
                    "agentId": "agent-finder",
                    "roleKey": "source_finder",
                    "resolvedFrom": "workflow_default",
                }
            ],
            "createdBy": "u-1",
            "createdAt": "2026-08-12T00:00:00Z",
            "snapshotHash": "c" * 64,
        }
        record = build_run_record(run_id="run-bound", last_event_sequence=1)
        record = record.__class__(
            **{
                **record.__dict__,
                "input_snapshot_json": _json.dumps(input_snapshot, ensure_ascii=False),
            }
        )

        def mutate(uow):
            uow.repository.insert_run(record)
            uow.repository.insert_event(
                build_event_record(
                    sequence=1,
                    run_id="run-bound",
                    event_type="run_created",
                    event_id="evt-created-run-bound",
                )
            )

        harness.store.submit(mutate, force_flush=True).result(timeout=10)
        harness.service.submit(
            harness.request(run_id="run-bound", idempotency_key="seed-bound")
        )
        payload = _query(harness).get_node_detail(
            team_id="research-team",
            run_id="run-bound",
            node_id="source_finding",
        ).to_dict()
        assert payload["agentId"] == "agent-finder"
        assert payload["resolvedFrom"] == "workflow_default"
        assert payload["sessionAnchorDegraded"] is True
        assert payload["sessionId"] is None
        assert payload["chatDeepLink"] is None
    finally:
        harness.close()
