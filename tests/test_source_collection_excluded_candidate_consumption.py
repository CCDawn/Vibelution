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
