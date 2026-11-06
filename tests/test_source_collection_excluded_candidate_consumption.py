"""Explicit source exclusions apply to consumption while preserving history."""

from core.web.services import data_processing_service, team_service
from core.web.services import team_workflow_orchestration_service as service
from core.web.services.team_workflow.research_runtime.artifact_readback_registry import load_scoped_artifact_payload
from core.web.services.team_workflow.source_collection.candidates import (
    filter_active_source_candidates,
    list_candidate_store_authority_records,
)
from tests._support.team_workflow.helpers import _capture_workflow_events, _use_tmp_project_root
from tests._support.team_workflow.cases_source_collection import _create_owned_source_collection_processing_run


def test_wrong_doi_exclusion_keeps_corrected_source_and_auditable_history(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _capture_workflow_events(monkeypatch)
    team = team_service.create_team(name="Source correction")
    team_id = team["teamId"]
    run = _create_owned_source_collection_processing_run(team, title="Living materials")
    run_id = run["runId"]
    records = [data_processing_service.add_record(run_id, {
        "sourceType": "paper", "sourceRef": f"https://doi.org/{doi}",
        "title": "Living material study", "summary": "Source metadata requires verification.",
        "metadata": {"doi": doi},
    }) for doi in ["10.1016/j.matt.2024.10.018", "10.1016/j.matt.2024.10.008"]]
    candidates = [service.import_data_record_as_source_candidate(team_id, run_id, record["recordId"])["candidate"] for record in records]
    old_id, corrected_id = [item["candidateId"] for item in candidates]
    assert {item["candidateId"] for item in service._source_collection_candidates_for_run(team_id, run_id)} == {old_id, corrected_id}
    evidence = [f"replaced candidate:{old_id} with candidate:{corrected_id}", "https://doi.org/10.1016/j.matt.2024.10.008"]
    exclusion = service._record_source_collection_exclusion(
        team_id, run, records[0], reason="duplicate_invalid", evidence=evidence,
        task_id="task-source-correction", stage_id="finding",
    )
    active = service._source_collection_candidates_for_run(team_id, run_id)
    assert [item["candidateId"] for item in active] == [corrected_id]
    canonical = load_scoped_artifact_payload("source_candidate_batch", team_id=team_id, authority_run_id=run_id)
    assert canonical is not None
    assert [item["candidateId"] for item in canonical["candidates"]] == [corrected_id]
    history = list_candidate_store_authority_records(team_id, run_id=run_id)
    assert {item["candidateId"] for item in history} == {old_id, corrected_id}
    assert exclusion["recordIds"] == [records[0]["recordId"]]
    assert exclusion["evidence"] == evidence
    assert exclusion["reason"] == "duplicate_invalid"
    assert records[0]["sourceRef"].endswith(".018")
    other_run = data_processing_service.create_processing_run(title="Another research question")
    assert filter_active_source_candidates(team_id, other_run["runId"], candidates) == candidates


def test_missing_receipt_alone_does_not_exclude_candidate(monkeypatch):
    monkeypatch.setattr(service, "_load_source_collection_exclusion_store", lambda _: {"entries": []})
    candidates = [{"candidateType": "source_manifest", "candidateId": "real-unbound-source", "qualityStatus": "pending_screening"}]
    assert filter_active_source_candidates("team", "run", candidates) == candidates


def _excluded_rerun_run(team_name, tmp_path, monkeypatch):
    """Run where every record was excluded through the real ledger."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    _capture_workflow_events(monkeypatch)
    team = team_service.create_team(name=team_name)
    run = _create_owned_source_collection_processing_run(team, title="Rerun exclusion ledger")
    records = [
        data_processing_service.add_record(run["runId"], {
            "sourceType": "url",
            "sourceRef": f"https://example.test/rerun-{index}",
            "title": f"Rerun source {index}",
            "summary": "Excluded through the real ledger in earlier rounds.",
        })
        for index in range(2)
    ]
    for record in records:
        service._record_source_collection_exclusion(
            team["teamId"], run, record, reason="no_effective_content",
            task_id="task-first-round", stage_id="extraction",
        )
    return team["teamId"], run["runId"], records


def test_rerun_coverage_classifies_ledger_excluded_records_as_excluded_not_invalid(tmp_path, monkeypatch):
    """ISS-038 回归：重跑摘要不得把命中排除账本的 recordId 计成 invalid/failed。"""
    team_id, run_id, records = _excluded_rerun_run("Source correction", tmp_path, monkeypatch)
    writeback = {"status": "completed", "result": {"recordExtractions": [
        {"recordId": record["recordId"], "decision": "extracted"} for record in records
    ] + [{"recordId": "ghost-record", "decision": "extracted"}]}}
    task = {
        "taskId": "task-rerun",
        "stageId": "extraction",
        "agentRole": "source_extractor",
        "retrySourceTaskId": "task-first-round",
        "writeback": writeback,
    }

    coverage = service._source_collection_stage_writeback_candidate_coverage(team_id, run_id, task, writeback)

    assert coverage["applicable"] is True
    assert coverage["total"] == 0
    assert coverage["processed"] == 0
    assert coverage["invalid"] == 1
    assert coverage["invalidRecordIds"] == ["ghost-record"]
    assert coverage["excluded"] == 2
    assert coverage["excludedRecordIds"] == [record["recordId"] for record in records]
    assert coverage["complete"] is True


def test_retry_reconcile_summary_keeps_excluded_records_out_of_invalid(tmp_path, monkeypatch):
    """ISS-038 回归：写回响应与重跑摘要读取共用同一排除口径。"""
    team_id, run_id, records = _excluded_rerun_run("Source correction", tmp_path, monkeypatch)
    result = {"recordExtractions": [
        {"recordId": record["recordId"], "decision": "extracted"} for record in records
    ]}
    task = {
        "taskId": "task-rerun",
        "stageId": "extraction",
        "agentRole": "source_extractor",
        "status": "completed",
        "retrySourceTaskId": "task-first-round",
        "writeback": {"status": "completed", "result": dict(result)},
        "result": dict(result),
    }

    reconciled = service._reconcile_source_collection_stage_session_task_retry_coverage(team_id, run_id, task)

    coverage = reconciled["writeback"]["coverageSummary"]
    assert coverage["invalid"] == 0
    assert coverage["invalidRecordIds"] == []
    assert coverage["excluded"] == 2
    assert coverage["excludedRecordIds"] == [record["recordId"] for record in records]
    assert coverage["complete"] is True
    assert reconciled["writeback"]["invalidRecordIds"] == []
    assert reconciled["result"]["coverageSummary"]["complete"] is True
