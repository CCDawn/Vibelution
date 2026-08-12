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
