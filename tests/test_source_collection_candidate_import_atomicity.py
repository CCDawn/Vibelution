"""Candidate import check+register critical-section tests (concurrency plan C5).

Guarantees under test:
- Concurrent imports of the same source identity must yield exactly one
  source_manifest candidate; losers reuse the winner's candidateId.
- Concurrent imports of distinct sources must not interfere with each other.
- ``register_candidate_source`` is identity-idempotent at the storage layer:
  a second registration with the same ``metadata.sourceIdentityKey`` reuses
  the existing record instead of appending a duplicate.
- Registrations without a source identity key (manual/plain callers) and
  non-source_manifest candidate types keep the historical append behavior.
"""

from __future__ import annotations

import threading

from tests._support.team_workflow.helpers import *  # noqa: F403


def _run_import_workers(team_id: str, run_id: str, records: list[dict]) -> list[dict]:
    barrier = threading.Barrier(len(records))
    errors: list[Exception] = []
    responses: list[dict] = []

    def _worker(record: dict) -> None:
        try:
            barrier.wait(timeout=10)
            responses.append(
                team_workflow_orchestration_service.import_data_record_as_source_candidate(
                    team_id,
                    run_id,
                    record["recordId"],
                    {"createdByAgent": "data_intake_coordinator"},
                )
            )
        except Exception as error:  # pragma: no cover - surfaced via assertion
            errors.append(error)

    threads = [threading.Thread(target=_worker, args=(record,)) for record in records]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    for thread in threads:
        assert not thread.is_alive(), "import worker thread timed out"
    assert not errors, f"import worker threads raised: {errors!r}"
    assert len(responses) == len(records)
    return responses


def test_concurrent_import_same_source_creates_single_candidate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _capture_workflow_events(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run = data_processing_service.create_processing_run(title="Source collection")
    same_ref = "https://example.test/duplicated-neuro-paper"
    records = [
        data_processing_service.add_record(
            run["runId"],
            {
                "sourceType": "url",
                "sourceRef": same_ref,
                "title": "Neurology source",
                "summary": "A useful candidate source.",
            },
        )
        for _ in range(3)
    ]
    assert len({record["recordId"] for record in records}) == 3

    responses = _run_import_workers(team["teamId"], run["runId"], records)

    created = [item for item in responses if item.get("created")]
    reused = [item for item in responses if not item.get("created")]
    assert len(created) == 1
    assert len(reused) == 2
    winner_id = created[0]["candidate"]["candidateId"]
    assert all(item["candidate"]["candidateId"] == winner_id for item in reused)
    assert all(item.get("duplicateOfCandidateId") == winner_id for item in reused)
    assert all(item.get("duplicateReason") == "source_identity_key" for item in reused)

    source_list = team_workflow_orchestration_service.list_candidate_store(
        team["teamId"], candidate_type="source_manifest"
    )
    assert source_list["candidateCount"] == 1
    assert source_list["candidates"][0]["candidateId"] == winner_id


def test_concurrent_import_distinct_sources_all_persist(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _capture_workflow_events(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    run = data_processing_service.create_processing_run(title="Source collection")
    records = [
        data_processing_service.add_record(
            run["runId"],
            {
                "sourceType": "url",
                "sourceRef": f"https://example.test/distinct-source-{index}",
                "title": f"Distinct source {index}",
                "summary": "An independent candidate source.",
            },
        )
        for index in range(4)
    ]

    responses = _run_import_workers(team["teamId"], run["runId"], records)

    assert all(item.get("created") for item in responses)
    candidate_ids = {item["candidate"]["candidateId"] for item in responses}
    assert len(candidate_ids) == len(records)
    source_list = team_workflow_orchestration_service.list_candidate_store(
        team["teamId"], candidate_type="source_manifest"
    )
    assert source_list["candidateCount"] == len(records)
    assert {item["candidateId"] for item in source_list["candidates"]} == candidate_ids


def test_register_candidate_source_reuses_existing_identity(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    scene_events = _capture_workflow_events(monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    payload = {
        "candidateType": "source_manifest",
        "title": "Identity guarded source",
        "sourceUrl": "https://example.test/identity-guarded",
        "metadata": {"sourceIdentityKey": "url:example.test/identity-guarded"},
    }

    first = team_workflow_orchestration_service.register_candidate_source(team["teamId"], payload)
    second = team_workflow_orchestration_service.register_candidate_source(team["teamId"], payload)

    assert first.get("duplicate") is None
    assert second.get("duplicate") is True
    assert second.get("duplicateReason") == "source_identity_key"
    assert second["candidate"]["candidateId"] == first["candidate"]["candidateId"]
    assert second.get("duplicateOfCandidateId") == first["candidate"]["candidateId"]

    source_list = team_workflow_orchestration_service.list_candidate_store(
        team["teamId"], candidate_type="source_manifest"
    )
    assert source_list["candidateCount"] == 1

    reused_events = _workflow_scene_events_by_code(scene_events, "candidate.register_duplicate_reused")
    assert reused_events
    assert reused_events[-1]["fields"]["candidateId"] == first["candidate"]["candidateId"]
    assert reused_events[-1]["fields"]["sourceIdentityKey"] == "url:example.test/identity-guarded"


def test_register_candidate_source_without_identity_key_keeps_append_behavior(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    payload = {
        "candidateType": "source_manifest",
        "title": "Manual registration without identity key",
        "sourceUrl": "https://example.test/manual-no-identity",
    }

    first = team_workflow_orchestration_service.register_candidate_source(team["teamId"], payload)
    second = team_workflow_orchestration_service.register_candidate_source(team["teamId"], payload)

    assert first.get("duplicate") is None
    assert second.get("duplicate") is None
    assert second["candidate"]["candidateId"] != first["candidate"]["candidateId"]
    source_list = team_workflow_orchestration_service.list_candidate_store(
        team["teamId"], candidate_type="source_manifest"
    )
    assert source_list["candidateCount"] == 2


def test_register_candidate_source_non_manifest_type_is_not_identity_deduped(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    payload = {
        "candidateType": "paper_note",
        "title": "Paper note with borrowed identity",
        "metadata": {"sourceIdentityKey": "url:example.test/identity-guarded"},
    }

    first = team_workflow_orchestration_service.register_candidate_source(team["teamId"], payload)
    second = team_workflow_orchestration_service.register_candidate_source(team["teamId"], payload)

    assert first.get("duplicate") is None
    assert second.get("duplicate") is None
    assert second["candidate"]["candidateId"] != first["candidate"]["candidateId"]
