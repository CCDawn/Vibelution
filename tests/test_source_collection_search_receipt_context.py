"""Structured search-receipt projection for finding task context."""

from __future__ import annotations

import json
from collections import OrderedDict

from core.web.services.team_workflow.source_collection_context import (
    compact_source_collection_search_receipts,
    compact_source_collection_stage_task_context,
    summarize_source_collection_search_receipts,
    summarize_source_collection_writeback_batches,
)


def _receipt(index: int, *, assignment_id: str = "assignment-current") -> dict[str, object]:
    status = ("found", "failed", "returned")[index % 3]
    return {
        "sourceCollectionRunId": "source-1",
        "assignmentId": assignment_id,
        "queryId": f"query-{index}",
        "provider": "provider-a",
        "perspective": "mechanism",
        "status": status,
        "query": "long frozen query " * 120,
        "resultRefs": [f"https://example.org/result-{index}-{ref}" for ref in range(20)],
        "eventIds": [f"event-{index}-{event}" for event in range(30)],
        "failureReason": "provider unavailable" if status == "failed" else "",
        "startedAt": "2026-09-08T00:00:00Z",
        "terminalAt": "2026-09-08T00:01:00Z",
    }


def test_single_oversized_receipt_is_also_compacted() -> None:
    receipt = {**_receipt(0), "query": "oversized query " * 10000}
    compact = compact_source_collection_search_receipts([receipt])
    assert compact[0]["queryId"] == receipt["queryId"]
    assert compact[0]["resultRefs"] == receipt["resultRefs"][:16]
    assert compact[0]["eventIds"] == receipt["eventIds"][:24]
    assert "query" not in compact[0]
    assert len(json.dumps(compact)) < 2500
    assert json.loads(json.dumps(compact)) == compact


def test_large_search_receipt_trace_is_projected_with_complete_summary() -> None:
    receipts = [_receipt(index) for index in range(20)]

    compact = compact_source_collection_search_receipts(receipts)
    summary = summarize_source_collection_search_receipts(
        receipts,
        next_action="Repair failed receipts with scoped searches.",
    )

    assert len(compact) == 12
    assert set(compact[0]) == {
        "sourceCollectionRunId",
        "assignmentId",
        "queryId",
        "provider",
        "perspective",
        "status",
        "resultRefs",
        "eventIds",
        "failureReason",
        "resultRefCount",
        "eventIdCount",
        "truncated",
    }
    assert compact[0]["assignmentId"] == "assignment-current"
    assert compact[0]["queryId"] == "query-8"
    assert compact[-1]["queryId"] == "query-19"
    assert compact[0]["resultRefs"] == [
        f"https://example.org/result-8-{ref}" for ref in range(16)
    ]
    assert compact[0]["eventIds"] == [f"event-8-{event}" for event in range(24)]
    assert compact[0]["resultRefCount"] == 20
    assert compact[0]["eventIdCount"] == 30
    assert compact[0]["truncated"] is True
    assert "query" not in compact[0]

    assert summary == {
        "receiptCount": 20,
        "visibleReceiptCount": 12,
        "omittedReceiptCount": 8,
        "foundCount": 7,
        "failedCount": 7,
        "returnedCount": 6,
        "resultRefCount": 400,
        "eventIdCount": 600,
        "statusCounts": {"found": 7, "failed": 7, "returned": 6},
        "truncated": True,
        "nextAction": "Repair failed receipts with scoped searches.",
    }
    assert len(json.dumps(compact, ensure_ascii=False)) < len(json.dumps(receipts, ensure_ascii=False))


def test_finding_context_tool_scopes_and_compacts_trace(monkeypatch) -> None:
    from core.web.services import team_workflow_orchestration_service as service
    from core.web.services.team_workflow.research_runtime import artifact_readback_registry
    from core.web.services.team_workflow.source_collection import search_execution
    from tools import source_collection_stage_tools as stage_tools

    monkeypatch.setattr(stage_tools, "_SOURCE_CONTEXT_CACHE", OrderedDict())
    monkeypatch.setattr(stage_tools, "_resolve_source_collection_team_id", lambda **_: ("team-1", {}))
    monkeypatch.setattr(stage_tools, "_record_stage_tool_event", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        service,
        "get_source_collection_stage_task_context",
        lambda *_a, **_kw: {
            "stageId": "finding",
            "runId": "source-1",
            "assignments": [{"assignmentId": "assignment-current"}],
        },
    )
    monkeypatch.setattr(
        search_execution,
        "project_source_collection_search_trace",
        lambda *_a, **_kw: [
            _receipt(index) for index in range(20)
        ] + [_receipt(99, assignment_id="assignment-foreign")],
    )

    def invalid_receipt(**_kwargs):
        raise ValueError("missing terminal receipt")

    monkeypatch.setattr(artifact_readback_registry, "load_source_finding_receipt_payload", invalid_receipt)

    result = json.loads(
        stage_tools.source_collection_context_tool(
            team_id="team-1",
            run_id="source-1",
            stage_id="finding",
        )
    )

    assert len(result["searchReceipts"]) == 12
    assert {item["assignmentId"] for item in result["searchReceipts"]} == {"assignment-current"}
    assert result["searchReceiptSummary"]["receiptCount"] == 20
    assert result["searchReceiptSummary"]["omittedReceiptCount"] == 8
    assert result["searchReceiptSummary"]["truncated"] is True
    assert result["searchReceiptSummary"]["nextAction"].startswith("Repair the missing receipts")
    assert result["searchReceiptValidation"]["valid"] is False
    json.loads(json.dumps(result, ensure_ascii=False))


def test_compact_context_preserves_writeback_batch_budget_without_fingerprints() -> None:
    batches = [
        {
            "batchFingerprint": "batch-1",
            "leadCount": 4,
            "leadFingerprints": ["large-fingerprint"] * 80,
            "newAcceptedLeadCount": 4,
            "recordedAt": "2026-09-08T00:00:00Z",
        },
        {
            "batchFingerprint": "batch-2",
            "leadCount": 4,
            "leadFingerprints": ["another-large-fingerprint"] * 80,
            "newAcceptedLeadCount": 3,
            "recordedAt": "2026-09-08T00:02:00Z",
        },
    ]
    envelope = {
        "totalAcceptedLeadBudget": 8,
        "maxLeadsPerWriteback": 4,
        "maxWritebackBatches": 2,
        "effectiveAcceptedLeadLimit": 8,
    }
    budget = summarize_source_collection_writeback_batches(batches, search_envelope=envelope)
    context = compact_source_collection_stage_task_context({
        "contextMode": "compact", "stageId": "finding",
        "task": {"status": "running", "sourceCollectionWritebackBatchSummary": budget},
        "writebackContract": {"searchEnvelope": envelope},
    })
    assert context["writebackBudget"]["newAcceptedLeadCount"] == 7
    assert context["writebackBudget"]["remainingAcceptedLeadCount"] == 1
    assert context["writebackBudget"]["remainingBatchCount"] == 0
    assert context["writebackContract"]["searchEnvelope"]["effectiveAcceptedLeadLimit"] == 8
    assert "leadFingerprints" not in json.dumps(context, ensure_ascii=False)
