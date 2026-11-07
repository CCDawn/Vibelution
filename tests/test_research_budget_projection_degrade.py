"""ISS-066: corrupt budget usage records keep fail-soft zero totals, but the
drop must be observable through the existing runtime-scene event channel
instead of silently reporting zero usage."""

from __future__ import annotations

import pytest

from core.research.workflow.contracts.workflow_snapshot import (
    AgentBindingSummary,
    BudgetReceiptRef,
    BudgetSummary,
    HandoffSummary,
    ResearchWorkflowSnapshot,
    WorkflowRunSummary,
)
from core.web.services import runtime_scene_service
from core.web.services.team_workflow.research_runtime import (
    ledger_domain_projections,
    query_service,
)


@pytest.fixture
def scene_events(monkeypatch) -> list[dict]:
    events: list[dict] = []

    def _capture(component, phase, event_code, **kwargs):
        events.append({"eventCode": event_code, "component": component, **kwargs})
        return {}

    monkeypatch.setattr(
        runtime_scene_service, "record_runtime_scene_event_quietly", _capture
    )
    return events


def test_budget_receipt_summary_reports_corrupt_payload(scene_events) -> None:
    row = (
        "receipt-1",
        "run-1",
        "nr-1",
        "res-1",
        "stage-1",
        "policy-hash",
        "{reserved payload not json",
        '{"usage": {"tokens": 5}}',
        "settled",
        1,
        2,
    )

    summary = query_service._budget_receipt_summary(row)

    # Fail-soft preserved: corrupt payload degrades to empty, good payload reads.
    assert summary["reservedPayload"] == {}
    assert summary["settledPayload"] == {"usage": {"tokens": 5}}
    degraded = [
        event
        for event in scene_events
        if event["eventCode"] == "budget_receipt_payload_unreadable"
    ]
    assert len(degraded) == 1
    assert degraded[0]["fields"]["receiptId"] == "receipt-1"
    assert degraded[0]["fields"]["payloadKind"] == "reserved"
    assert degraded[0]["outcome"] == "degraded"


def test_budget_records_report_invalid_usage_counters(scene_events) -> None:
    ref = BudgetReceiptRef(
        receipt_id="receipt-9",
        node_run_id="nr-9",
        reservation_id="res-9",
        stage_id="collection",
        status="settled",
        policy_hash="policy",
        reserved_payload={"reserved": {"tokens": 10}, "limits": {"tokens": 100}},
        settled_payload={"usage": {"tokens": "corrupt", "toolCalls": 2}},
        created_at_ms=1,
        updated_at_ms=2,
    )
    snapshot = ResearchWorkflowSnapshot(
        run=WorkflowRunSummary(
            run_id="run-9",
            team_id="team-1",
            workflow_id="challenge-cup-research",
            workflow_version_id="3.0.0",
            thread_id="thread-9",
            project_id="project-9",
            question_id="SCI-001",
            status="running",
            run_version=1,
            input_snapshot_hash="hash",
            binding_snapshot_set_id="set-9",
            active_node_id="controlled_run",
            parent_run_id=None,
            forked_from_checkpoint_id=None,
            completion_kind="",
            terminal_reason="",
            created_at_ms=1,
            updated_at_ms=2,
            completed_at_ms=None,
        ),
        definition={},
        node_attempts={},
        active_node_ids=(),
        pending_human_tasks=(),
        command_offers=(),
        handoff_summary=HandoffSummary(counts_by_status={}, refs=(), count=0),
        agent_binding_summary=AgentBindingSummary(
            binding_snapshot_set_id="set-9", binding_snapshot_ids=(), count=0
        ),
        budget_summary=BudgetSummary(
            safety_limits=None, receipt_refs=(ref,), receipt_count=1
        ),
        latest_event_sequence=0,
        generated_at="2026-01-01T00:00:00Z",
    )

    ledgers, reservations = ledger_domain_projections._budget_records(snapshot)

    stage = ledgers[0]
    # Fail-soft preserved: invalid counter zeroes out of the consumed total,
    # valid counter counts; the reservation row keeps the raw stored usage.
    assert stage["consumed"]["tokens"] == 0
    assert stage["consumed"]["toolCalls"] == 2
    assert reservations[0]["actual"]["tokens"] == "corrupt"
    degraded = [
        event
        for event in scene_events
        if event["eventCode"] == "budget_usage_counters_invalid"
    ]
    assert len(degraded) == 1
    assert degraded[0]["fields"]["receiptId"] == "res-9"
    assert degraded[0]["fields"]["droppedKeys"] == ["tokens"]
