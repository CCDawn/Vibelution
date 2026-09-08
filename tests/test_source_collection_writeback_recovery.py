"""Exercise actual stores across interrupted finding writes and same-batch replay."""

import pytest

from core.web.services import data_processing_service
from core.web.services import team_workflow_orchestration_service as service
from core.web.services.team_workflow.source_collection import search_execution
from core.web.services.team_workflow.source_collection import stage_writeback
from core.web.services.team_workflow.source_collection.candidates import list_candidate_store_authority_records
from tests._support.team_workflow.cases_source_collection import _finding_close_first_step_task


@pytest.mark.parametrize("failure_point", ["record", "record_committed", "candidate", "candidate_committed", "task"])
def test_finding_replays_interrupted_batch_without_duplicate_sources_or_budget(
    tmp_path, monkeypatch, failure_point,
):
    env = _finding_close_first_step_task(tmp_path, monkeypatch)
    team_id, run_id, task_id = env["team"]["teamId"], env["runId"], env["task"]["taskId"]
    locator = "https://doi.org/10.1038/4580"
    # Storage failures are this test's boundary. Search projection is fixed;
    # receipt authenticity and provider-result grouping have separate tests.
    monkeypatch.setattr(search_execution, "project_source_collection_search_trace", lambda *_a, **_kw: [{
        "query": "predictive coding mechanism", "queryId": "query-storage-replay",
        "perspective": "mechanism", "status": "found", "provider": "fixture",
        "resultRefs": [locator], "receiptRefSets": [[locator]], "eventIds": ["event-storage-replay"],
    }])
    payload = {"status": "needs_review", "summary": "Persist a bounded source batch", "result": {
        "candidateLeads": [{"title": "Predictive coding in the visual cortex", "locator": locator,
                            "sourceType": "paper", "perspective": "mechanism"}],
    }}
    boundary = failure_point.removesuffix("_committed")
    target, name, error = {
        "record": (data_processing_service, "add_record", data_processing_service.DataProcessingError),
        "candidate": (service, "import_data_record_as_source_candidate", service.TeamWorkflowOrchestrationError),
        "task": (service, "_upsert_source_collection_stage_session_task", OSError),
    }[boundary]
    original = getattr(target, name)
    calls = []

    def fail_once(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            if failure_point.endswith("_committed"):
                original(*args, **kwargs)
            raise error(f"injected {failure_point} persistence interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(target, name, fail_once)
    if failure_point == "task":
        with pytest.raises(OSError, match="injected task"):
            service.writeback_source_collection_stage_session_task(team_id, task_id, payload)
    else:
        first = service.writeback_source_collection_stage_session_task(team_id, task_id, payload)
        materialized = first["writeback"]["materializedSources"]
        assert materialized["failedCount"] == 1
        assert materialized["lineage"][0]["reason"] == {
            "record": "data_record_create_failed", "candidate": "candidate_import_failed",
        }[boundary]
        assert not first["task"]["completionGate"]["passed"]
    before = data_processing_service.list_records(run_id)["summary"]["recordCount"]
    assert before == (0 if failure_point == "record" else 1)

    recovered = service.writeback_source_collection_stage_session_task(team_id, task_id, payload)
    assert recovered["writeback"]["materializedSources"]["failedCount"] == 0
    replay = service.writeback_source_collection_stage_session_task(team_id, task_id, payload)
    assert replay["writeback"]["materializedSources"]["createdRecordCount"] == 0
    assert replay["writeback"]["materializedSources"]["skippedDuplicateCount"] == 1
    assert data_processing_service.list_records(run_id)["summary"]["recordCount"] == 1
    candidates = list_candidate_store_authority_records(team_id, run_id=run_id)
    assert len(candidates) == 1
    store = service._load_source_collection_stage_session_task_store(team_id, run_id)
    stored = next(task for task in store["tasks"] if task["taskId"] == task_id)
    batches = stored["sourceCollectionWritebackBatches"]
    assert len(batches) == 1
    assert sum(batch["newAcceptedLeadCount"] for batch in batches) == 1
    assert stored["writeback"]["materializedSources"]["lineage"][0]["candidate"]["candidateId"] == candidates[0]["candidateId"]


def test_finding_preflight_preserves_incoming_url_identity_before_record_projection(monkeypatch):
    doi = "10.1038/paper-b"
    url = "https://publisher.test/paper-a"
    monkeypatch.setattr(search_execution, "project_source_collection_search_trace", lambda *_a, **_kw: [{
        "status": "found", "eventIds": ["event"], "resultRefs": [url, doi],
        "receiptRefSets": [[url], [doi]],
    }])
    with pytest.raises(service.TeamWorkflowOrchestrationError, match="source_search_receipt_missing"):
        stage_writeback._source_collection_stage_finding_receipt_preflight(
            "team", "source", {"taskId": "task", "stageId": "finding", "workflowRunId": "workflow"},
            {"candidateLeads": [{"title": "Mismatched source", "doi": doi, "url": url}]},
        )


def test_search_projection_keeps_single_locator_receipts_alongside_grouped_results(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"
    old_doi, new_doi = "10.1038/old-paper", "10.1038/new-paper"
    common = {"assignmentId": "assignment", "queryId": "query", "provider": "provider",
              "eventType": "search.tool_result_returned", "query": "papers", "perspective": "mechanism"}
    service._append_jsonl(events_path, [
        {**common, "eventId": "old-event", "refs": [old_doi]},
        {**common, "eventId": "new-event", "refs": [new_doi], "receiptRefSets": [[new_doi]]},
    ])
    monkeypatch.setattr(service, "_source_collection_storage_artifact_paths", lambda *_: {"searchEventsPath": events_path})
    trace = search_execution.project_source_collection_search_trace("team", "source")
    groups = search_execution._source_finding_trace_receipt_ref_sets(trace)
    assert search_execution._source_finding_candidate_receipt_is_bound({"sourceUrl": f"https://doi.org/{old_doi}"}, groups)
    assert search_execution._source_finding_candidate_receipt_is_bound({"sourceUrl": f"https://doi.org/{new_doi}"}, groups)
