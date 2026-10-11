from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from tests._support.team_workflow.helpers import (
    _use_tmp_project_root,
    agent_directory_service,
)
from tests.test_source_collection_ingestion_actor_authority import _prepare_ingestion_writeback_case
from core.web.services import team_workflow_orchestration_service as s
from core.web.services.team_workflow.source_collection.writeback_materialize import (
    _reusable_source_ingestion_pack,
)

# 超过 metadata 落盘归一化的 1000 字符上限：现场重建的 pack output 保留全长，
# 存量 pack 的 metadata.output 被截断，两者字节不同、语义相同。
_LONG_SUMMARY = "Neural predictive coding evidence for a governed knowledge item. " * 30


def _reviewer_member():
    reviewer = agent_directory_service.create_agent_instance(display_name="独立入库审核")
    return reviewer, {"agentId": reviewer["agentId"], "role": "coordinator", "agentName": "独立入库审核"}


def _steward_pack_records(team_id, run_id):
    store = s._load_candidate_store(team_id, run_id=run_id)
    return [
        item
        for item in store.get("candidates") or []
        if isinstance(item, dict) and (item.get("metadata") or {}).get("taskType") == "steward_pack_draft"
    ]


def _stored_pack(team_id, run_id, candidate_id):
    store = s._load_candidate_store(team_id, run_id=run_id)
    return s._find_candidate(store, candidate_id) or {}


def _complete_ingestion_review_chain(team_id, run_id, pack_candidate_id, reviewer_agent_id, steward_agent_id):
    """Independent reviewer accepts the source, then approves the knowledge proposal."""
    pack = _stored_pack(team_id, run_id, pack_candidate_id)
    ingestion = (pack.get("metadata") or {}).get("knowledgeIngestion") or {}
    knowledge_base_id = str(ingestion.get("knowledgeBaseId") or "")
    reviewed_source = s.team_knowledge_service.review_owner_inbox_source(
        "team",
        team_id,
        str(ingestion.get("inboxSourceId")),
        decision="accepted",
        reviewed_by_agent_id=reviewer_agent_id,
    )
    central_source_id = str((reviewed_source.get("centralSource") or {}).get("centralSourceId") or "")
    s.submit_steward_pack_to_knowledge_ingestion(
        team_id,
        pack_candidate_id,
        {
            "knowledgeBaseId": knowledge_base_id,
            "proposedByAgentId": steward_agent_id,
            "centralSourceId": central_source_id,
        },
        run_id=run_id,
    )
    return s.review_steward_pack_knowledge_ingestion(
        team_id,
        pack_candidate_id,
        {
            "knowledgeBaseId": knowledge_base_id,
            "reviewedByAgentId": reviewer_agent_id,
            "decision": "approved",
            "resolutionNote": "Independent review accepted the evidence.",
        },
        run_id=run_id,
    )


def test_stale_ingestion_task_reuses_applied_receipt(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    reviewer, reviewer_member = _reviewer_member()
    team, source, task, payload = _prepare_ingestion_writeback_case(
        tmp_path, monkeypatch, include_ingestor_in_team=True, recorded_by_agent="ingestor",
        extra_members=[reviewer_member])
    stale_task = deepcopy(task["task"])
    first = s._materialize_source_collection_stage_writeback_knowledge_ingestion(
        team["teamId"], stale_task["runId"], deepcopy(stale_task), deepcopy(payload))
    # Independent-review gate: round 1 submits the pack and stays pending until
    # a reviewer applies the receipts through the explicit review APIs.
    assert first["status"] == "pending_review"
    pack_candidate_id = first["stewardPackCandidateId"]
    applied = _complete_ingestion_review_chain(
        team["teamId"], stale_task["runId"], pack_candidate_id, reviewer["agentId"], stale_task["agentId"])
    knowledge_item_ids = applied["knowledgeIngestion"]["officialSyncRecord"]["knowledgeItemIds"]

    def forbid(*args, **kwargs):
        raise AssertionError("Replay must reuse the applied source/proposal/item receipt")

    monkeypatch.setattr(s, "record_local_research_model_output", forbid)
    monkeypatch.setattr(s, "submit_steward_pack_to_knowledge_ingestion", forbid)
    monkeypatch.setattr(s, "review_steward_pack_knowledge_ingestion", forbid)
    packs_before = _steward_pack_records(team["teamId"], stale_task["runId"])
    second = s._materialize_source_collection_stage_writeback_knowledge_ingestion(
        team["teamId"], stale_task["runId"], deepcopy(stale_task), deepcopy(payload))
    assert second["status"] == "completed"
    assert second["formalKnowledgeItemIds"] == knowledge_item_ids
    assert second["stewardPackCandidateId"] == pack_candidate_id
    assert _steward_pack_records(team["teamId"], stale_task["runId"]) == packs_before


def test_replay_reuses_synced_pack_with_storage_normalized_output(tmp_path, monkeypatch):
    """Replays converge on the stored (normalized) pack instead of re-pending."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    reviewer, reviewer_member = _reviewer_member()
    team, source, task, payload = _prepare_ingestion_writeback_case(
        tmp_path, monkeypatch, include_ingestor_in_team=True, recorded_by_agent="ingestor",
        extra_members=[reviewer_member], source_summary=_LONG_SUMMARY)
    stage_task = deepcopy(task["task"])
    real_record = s.record_local_research_model_output
    captured_outputs: list[dict] = []

    def capture_record(team_id, record_payload, **kwargs):
        captured_outputs.append(deepcopy(record_payload.get("output")))
        return real_record(team_id, record_payload, **kwargs)

    monkeypatch.setattr(s, "record_local_research_model_output", capture_record)
    first = s._materialize_source_collection_stage_writeback_knowledge_ingestion(
        team["teamId"], stage_task["runId"], deepcopy(stage_task), deepcopy(payload))
    monkeypatch.setattr(s, "record_local_research_model_output", real_record)
    assert first["status"] == "pending_review"
    pack_candidate_id = first["stewardPackCandidateId"]
    stored_output = (_stored_pack(team["teamId"], stage_task["runId"], pack_candidate_id)
                     .get("metadata") or {}).get("output") or {}
    # 缺陷前提：现场重建形态（capture）与落盘归一化形态字节不同、语义相同。
    assert captured_outputs and captured_outputs[0] != stored_output
    assert s._normalize_metadata(captured_outputs[0]) == stored_output
    _complete_ingestion_review_chain(
        team["teamId"], stage_task["runId"], pack_candidate_id, reviewer["agentId"], stage_task["agentId"])

    def forbid(*args, **kwargs):
        raise AssertionError("Replay must reuse the synced pack without new side effects")

    monkeypatch.setattr(s, "record_local_research_model_output", forbid)
    monkeypatch.setattr(s, "submit_steward_pack_to_knowledge_ingestion", forbid)
    monkeypatch.setattr(s, "review_steward_pack_knowledge_ingestion", forbid)
    packs_before = _steward_pack_records(team["teamId"], stage_task["runId"])
    second = s._materialize_source_collection_stage_writeback_knowledge_ingestion(
        team["teamId"], stage_task["runId"], deepcopy(stage_task), deepcopy(payload))
    assert second["status"] == "completed"
    assert second["stewardPackCandidateId"] == pack_candidate_id
    assert second["formalKnowledgeItemCount"] == 1
    assert _steward_pack_records(team["teamId"], stage_task["runId"]) == packs_before

    # 收敛捷径：上一轮 completed 回放结果存在时，重放直接复用该回执。
    replay_task = deepcopy(stage_task)
    replay_task["writeback"] = {"materializedKnowledgeIngestion": second}
    third = s._materialize_source_collection_stage_writeback_knowledge_ingestion(
        team["teamId"], stage_task["runId"], replay_task, deepcopy(payload))
    assert third["status"] == "completed"
    assert third["stewardPackCandidateId"] == pack_candidate_id
    assert third["formalKnowledgeItemIds"] == second["formalKnowledgeItemIds"]
    assert third["reusedOfficialSync"] is True


def test_replay_prefers_synced_original_over_newer_pending_duplicate(tmp_path, monkeypatch):
    """Defect rounds leave pending duplicates; reuse must pick the synced original."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    reviewer, reviewer_member = _reviewer_member()
    team, source, task, payload = _prepare_ingestion_writeback_case(
        tmp_path, monkeypatch, include_ingestor_in_team=True, recorded_by_agent="ingestor",
        extra_members=[reviewer_member], source_summary=_LONG_SUMMARY)
    stage_task = deepcopy(task["task"])
    first = s._materialize_source_collection_stage_writeback_knowledge_ingestion(
        team["teamId"], stage_task["runId"], deepcopy(stage_task), deepcopy(payload))
    pack_candidate_id = first["stewardPackCandidateId"]
    stored_pack = _stored_pack(team["teamId"], stage_task["runId"], pack_candidate_id)
    stored_output = deepcopy((stored_pack.get("metadata") or {}).get("output") or {})
    scoped_knowledge_base_id = str(
        ((stored_pack.get("metadata") or {}).get("knowledgeIngestion") or {}).get("knowledgeBaseId") or "")
    _complete_ingestion_review_chain(
        team["teamId"], stage_task["runId"], pack_candidate_id, reviewer["agentId"], stage_task["agentId"])

    # 模拟缺陷轮次的重复 pending 副本：语义相同、创建时间更新。
    fresh_output = deepcopy(stored_output)
    duplicate = s.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "steward_pack_draft",
            "title": "defect-round duplicate",
            "createdByAgent": stage_task["agentId"],
            "output": deepcopy(stored_output),
        },
        run_id=stage_task["runId"],
    )["candidate"]
    reused = _reusable_source_ingestion_pack(
        team["teamId"], stage_task["runId"], fresh_output, scoped_knowledge_base_id)
    assert reused is not None
    assert reused["candidateId"] == pack_candidate_id
    assert reused["candidateId"] != duplicate["candidateId"]

    second = s._materialize_source_collection_stage_writeback_knowledge_ingestion(
        team["teamId"], stage_task["runId"], deepcopy(stage_task), deepcopy(payload))
    assert second["status"] == "completed"
    assert second["stewardPackCandidateId"] == pack_candidate_id
    pack_ids = [item["candidateId"] for item in _steward_pack_records(team["teamId"], stage_task["runId"])]
    assert sorted(pack_ids) == sorted([pack_candidate_id, duplicate["candidateId"]])


def test_changed_pack_content_is_not_reused(tmp_path, monkeypatch):
    """Real content changes (claims/target domain) must create a fresh pack."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    reviewer, reviewer_member = _reviewer_member()
    team, source, task, payload = _prepare_ingestion_writeback_case(
        tmp_path, monkeypatch, include_ingestor_in_team=True, recorded_by_agent="ingestor",
        extra_members=[reviewer_member], source_summary=_LONG_SUMMARY)
    stage_task = deepcopy(task["task"])
    first = s._materialize_source_collection_stage_writeback_knowledge_ingestion(
        team["teamId"], stage_task["runId"], deepcopy(stage_task), deepcopy(payload))
    pack_candidate_id = first["stewardPackCandidateId"]
    stored_pack = _stored_pack(team["teamId"], stage_task["runId"], pack_candidate_id)
    stored_output = deepcopy((stored_pack.get("metadata") or {}).get("output") or {})
    scoped_knowledge_base_id = str(
        ((stored_pack.get("metadata") or {}).get("knowledgeIngestion") or {}).get("knowledgeBaseId") or "")
    assert _reusable_source_ingestion_pack(
        team["teamId"], stage_task["runId"], deepcopy(stored_output), scoped_knowledge_base_id) is not None

    changed = deepcopy(stored_output)
    claims = [claim for claim in list(changed.get("claims") or []) if isinstance(claim, dict)]
    assert claims
    claims[0]["claim"] = str(claims[0].get("claim") or "") + " Revised after new evidence."
    assert _reusable_source_ingestion_pack(
        team["teamId"], stage_task["runId"], changed, scoped_knowledge_base_id) is None

    changed_payload = deepcopy(payload)
    changed_payload["result"]["steward_assessment"]["targetDomain"] = "修订后的神经算法目标域"
    second = s._materialize_source_collection_stage_writeback_knowledge_ingestion(
        team["teamId"], stage_task["runId"], deepcopy(stage_task), deepcopy(changed_payload))
    assert second["stewardPackCandidateId"] != pack_candidate_id
    assert second["status"] == "pending_review"
    pack_ids = [item["candidateId"] for item in _steward_pack_records(team["teamId"], stage_task["runId"])]
    assert pack_candidate_id in pack_ids
    assert second["stewardPackCandidateId"] in pack_ids
    assert len(pack_ids) == 2


def test_ingestion_resumes_after_source_review_without_reaccepting_source(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    reviewer, reviewer_member = _reviewer_member()
    team, source, task, payload = _prepare_ingestion_writeback_case(
        tmp_path, monkeypatch, include_ingestor_in_team=True, recorded_by_agent="ingestor",
        extra_members=[reviewer_member])
    real_submit = s.submit_steward_pack_to_knowledge_ingestion

    def interrupted(team_id, candidate_id, contract, **kwargs):
        response = real_submit(team_id, candidate_id, contract, **kwargs)
        raise s.TeamWorkflowOrchestrationError("simulated interruption after source acceptance")

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
    assert second["status"] == "pending_review"
    assert second["sourceReviewStatus"] == "pending_source_review"
    assert len(_steward_pack_records(team["teamId"], task["task"]["runId"])) == 1


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
