from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from tests.test_source_collection_ingestion_actor_authority import _prepare_ingestion_writeback_case
from core.web.services import team_workflow_orchestration_service as s


def test_stale_ingestion_task_reuses_applied_receipt(tmp_path, monkeypatch):
    team, source, task, payload = _prepare_ingestion_writeback_case(
        tmp_path, monkeypatch, include_ingestor_in_team=True, recorded_by_agent="ingestor")
    stale_task = deepcopy(task["task"])
    first = s._materialize_source_collection_stage_writeback_knowledge_ingestion(
        team["teamId"], stale_task["runId"], deepcopy(stale_task), deepcopy(payload))
    assert first["status"] == "completed"
    assert first["formalKnowledgeItemCount"] == 1

    def forbid(*args, **kwargs):
        raise AssertionError("Replay must reuse the applied source/proposal/item receipt")

    monkeypatch.setattr(s, "record_local_research_model_output", forbid)
    monkeypatch.setattr(s, "submit_steward_pack_to_knowledge_ingestion", forbid)
    monkeypatch.setattr(s, "review_steward_pack_knowledge_ingestion", forbid)
    second = s._materialize_source_collection_stage_writeback_knowledge_ingestion(
        team["teamId"], stale_task["runId"], deepcopy(stale_task), deepcopy(payload))
    assert second["status"] == "completed"
    assert second["formalKnowledgeItemIds"] == first["formalKnowledgeItemIds"]
    assert second["stewardPackCandidateId"] == first["stewardPackCandidateId"]


def test_ingestion_resumes_after_source_review_without_reaccepting_source(tmp_path, monkeypatch):
    team, source, task, payload = _prepare_ingestion_writeback_case(
        tmp_path, monkeypatch, include_ingestor_in_team=True, recorded_by_agent="ingestor")
    real_submit = s.submit_steward_pack_to_knowledge_ingestion

    def interrupted(team_id, candidate_id, contract, **kwargs):
        if contract.get("centralSourceId"):
            raise s.TeamWorkflowOrchestrationError("simulated interruption after source acceptance")
        return real_submit(team_id, candidate_id, contract, **kwargs)

    monkeypatch.setattr(s, "submit_steward_pack_to_knowledge_ingestion", interrupted)
    first = s._materialize_source_collection_stage_writeback_knowledge_ingestion(
        team["teamId"], task["task"]["runId"], deepcopy(task["task"]), deepcopy(payload))
    assert first["status"] == "failed"
    monkeypatch.setattr(s, "submit_steward_pack_to_knowledge_ingestion", real_submit)

    def forbid(*args, **kwargs):
        raise AssertionError("Accepted inbox source must not be reviewed a second time")

    monkeypatch.setattr(s.team_knowledge_service, "review_owner_inbox_source", forbid)
    second = s._materialize_source_collection_stage_writeback_knowledge_ingestion(
        team["teamId"], task["task"]["runId"], deepcopy(task["task"]), deepcopy(payload))
    assert second["status"] == "completed"
    assert second["formalKnowledgeItemCount"] == 1


def test_overlapping_ingestion_does_not_enter_side_effects_twice(tmp_path, monkeypatch):
    from core.web.services.team_workflow import storage_durability
    from core.web.services.team_workflow.source_collection import writeback_materialize as materializer

    team, source, task, payload = _prepare_ingestion_writeback_case(
        tmp_path, monkeypatch, include_ingestor_in_team=True, recorded_by_agent="ingestor")
    real_lock = storage_durability.inter_process_lock
    monkeypatch.setattr(storage_durability, "inter_process_lock", lambda path: real_lock(path, timeout_s=0))
    entered, release = Event(), Event()
    calls = []

    def slow_write(*args):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return {"status": "completed"}

    monkeypatch.setattr(materializer, "_materialize_source_collection_stage_writeback_knowledge_ingestion_locked", slow_write)
    args = (team["teamId"], task["task"]["runId"], task["task"], payload)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(materializer._materialize_source_collection_stage_writeback_knowledge_ingestion, *args)
        try:
            assert entered.wait(5)
            with pytest.raises(OSError):
                materializer._materialize_source_collection_stage_writeback_knowledge_ingestion(*args)
        finally:
            release.set()
        assert future.result()["status"] == "completed"
    assert len(calls) == 1
