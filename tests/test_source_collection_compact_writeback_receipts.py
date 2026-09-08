"""Finding Agents receive persisted IDs and remaining budget without rereading sources."""

import json

import pytest

from core.web.services.team_workflow.source_collection.stage_reconcile import _source_collection_context_task_summary
from core.web.services.team_workflow.source_collection.writeback_materialize import _source_collection_stage_writeback_lead_fingerprint
from core.web.services.team_workflow.source_collection_context import compact_source_collection_stage_task_context
from tools import source_collection_stage_tools as stage_tools


def _task(accepted=4):
    return {
        "taskId": "task-1", "stageId": "finding", "status": "running",
        "sourceCollectionWritebackBatches": [{"batchFingerprint": "batch-1", "leadCount": accepted, "newAcceptedLeadCount": accepted}],
        "writebackContract": {"searchEnvelope": {
            "totalAcceptedLeadBudget": 8, "effectiveAcceptedLeadLimit": 8,
            "maxLeadsPerWriteback": 4, "maxWritebackBatches": 4,
        }},
    }


@pytest.mark.parametrize("accepted", [0, 4, 8])
@pytest.mark.parametrize("context_mode", ["compact", "minimal", "retry_missing"])
def test_task_budget_survives_actual_service_summary_and_compaction(accepted, context_mode):
    task = _task(accepted)
    if not accepted:
        task["sourceCollectionWritebackBatches"] = []
    summary = _source_collection_context_task_summary(task)
    context = compact_source_collection_stage_task_context({
        "stageId": "finding", "task": summary, "contextMode": context_mode, "writebackContract": task["writebackContract"],
    })
    budget = context["writebackBudget"]
    assert budget["remainingAcceptedLeadCount"] == 8 - accepted
    assert budget["remainingBatchCount"] == (4 if not accepted else 3)
    assert "sourceCollectionWritebackBatches" not in json.dumps(context)


def test_writeback_tool_returns_only_current_batch_ids_and_real_gate(monkeypatch):
    from core.web.services import team_workflow_orchestration_service as service

    leads = [{"title": f"Source {index}", "url": f"https://example.org/{index}"} for index in range(4)]
    lineage = [{
        "fingerprint": _source_collection_stage_writeback_lead_fingerprint(lead),
        "leadId": f"lead-{index}",
        "record": {"recordId": f"record-{index}", "status": "created", "content": "large source " * 10000},
        "candidate": {"candidateId": f"candidate-{index}", "status": "imported"},
    } for index, lead in enumerate(leads)]
    lineage.insert(0, {"fingerprint": "old-batch", "leadId": "old-lead", "record": {"recordId": "old-record"}})
    task = _task()
    response = {"teamId": "team-1", "taskId": "task-1", "stageId": "finding", "task": task, "writeback": {
        "status": "needs_review", "agentRequestedStatus": "completed",
        "receiptGate": {"passed": False, "error": "candidate-old needs a real receipt"},
        "closureSummary": {"completionGate": {"passed": False}, "retryInstruction": "Repair only candidate-old receipt."},
        "materializedSources": {"createdRecordCount": 4, "importedCandidateCount": 4, "lineage": lineage},
    }}
    monkeypatch.setattr(service, "writeback_source_collection_stage_session_task", lambda *_: response)
    monkeypatch.setattr(stage_tools, "_resolve_source_collection_team_id", lambda **_: ("team-1", {}))
    monkeypatch.setattr(stage_tools, "_record_stage_tool_event", lambda *_, **__: None)
    raw = stage_tools.source_collection_stage_writeback_tool(
        team_id="team-1", task_id="task-1", result_json=json.dumps({"candidateLeads": leads}),
    )
    compact = json.loads(raw)
    assert compact["status"] == "needs_review"
    assert compact["requestedStatus"] == "completed"
    assert compact["receiptGate"]["passed"] is False
    assert [item["recordId"] for item in compact["sourceReceipts"]] == [f"record-{index}" for index in range(4)]
    assert [item["candidateId"] for item in compact["sourceReceipts"]] == [f"candidate-{index}" for index in range(4)]
    assert compact["writebackBudget"]["remainingAcceptedLeadCount"] == 4
    assert compact["writebackBudget"]["remainingBatchCount"] == 3
    assert compact["nextStep"] == "Repair only candidate-old receipt."
    assert len(raw) < 8000
    assert "large source" not in raw and "old-record" not in raw


def test_completed_writeback_does_not_invite_another_search():
    response = {"stageId": "finding", "task": _task(8), "writeback": {
        "status": "completed", "closureSummary": {"completionGate": {"passed": True}},
    }}
    compact = stage_tools._compact_source_collection_stage_writeback_response(response, {})
    assert compact["writebackBudget"]["remainingAcceptedLeadCount"] == 0
    assert "no further search" in compact["nextStep"]
