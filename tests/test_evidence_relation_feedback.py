import json

import pytest

from core.web.services.team_workflow.research_runtime import artifact_readback_registry as registry
from core.web.services.team_workflow.source_collection import stage_writeback


@pytest.fixture
def graph(monkeypatch):
    value = {
        "nodes": [],
        "edges": [{"sourceCandidateId": "a", "targetCandidateId": "b", "evidenceRefs": ["claim-1"]}],
        "evidenceGaps": [{"description": "Independent replication missing"}],
        "counterEvidenceRefs": [{"evidenceRef": "claim-2", "claim": "Null result"}],
    }
    monkeypatch.setattr(registry, "_load_scoped_relation_graph", lambda **_: value)
    monkeypatch.setattr(registry, "load_allowed_evidence_refs", lambda **_: ["claim-1", "claim-2"])
    return value


@pytest.mark.parametrize("field", ["evidenceGaps", "counterEvidenceRefs"])
def test_relation_readback_reports_missing_fields_and_accepts_repair(graph, field):
    saved = graph.pop(field)
    assert registry.load_scoped_artifact_payload("evidence_relation_graph", team_id="team", authority_run_id="source") is None
    with pytest.raises(ValueError, match=field):
        registry.load_evidence_relation_graph_payload(team_id="team", authority_run_id="source", raise_on_invalid=True)
    graph[field] = saved
    assert registry.load_evidence_relation_graph_payload(team_id="team", authority_run_id="source", raise_on_invalid=True)


def test_relation_readback_rejects_unbound_theme_edge(graph):
    graph["edges"].append({"relation": "source_supports_theme", "evidenceRefs": []})
    with pytest.raises(ValueError, match="canonical claimEvidenceId"):
        registry.load_evidence_relation_graph_payload(team_id="team", authority_run_id="source", raise_on_invalid=True)


def test_relation_retry_updates_evidence_on_existing_edge():
    from core.web.services.team_workflow.source_collection.writeback_materialize import _merge_source_collection_stage_writeback_agent_graph

    edge = {"sourceCandidateId": "a", "targetCandidateId": "b", "relation": "supports", "evidenceRefs": []}
    graph = {"nodes": [{"candidateId": "a"}, {"candidateId": "b"}], "edges": [edge]}
    result = _merge_source_collection_stage_writeback_agent_graph(graph, {
        "edges": [{**edge, "evidenceRefs": ["claim-1"]}],
    })
    assert len(result["edges"]) == 1
    assert result["edges"][0]["evidenceRefs"] == ["claim-1"]
    assert graph["edges"][0]["evidenceRefs"] == []


@pytest.mark.parametrize("status", ["completed", "needs_review"])
def test_formal_relation_completion_feedback_precedes_task_acceptance(monkeypatch, graph, status):
    s = stage_writeback._service()
    task = {"taskId": "task", "stageId": "relations", "agentRole": "source_relation_mapper",
            "workflowRunId": "workflow", "status": "running"}
    graph["counterEvidenceRefs"] = []
    monkeypatch.setattr(s.team_service, "get_team", lambda *_: {})
    monkeypatch.setattr(s, "_find_source_collection_stage_session_task_by_id", lambda *_: (task, "source"))
    monkeypatch.setattr(s, "_merge_source_collection_stage_writeback_result_payload", lambda *_: {})
    monkeypatch.setattr(s, "_source_collection_stage_writeback_candidate_coverage", lambda *_: {})
    for name in ["sources", "content_extraction", "quality", "candidate_graph", "knowledge_ingestion"]:
        monkeypatch.setattr(s, "_materialize_source_collection_stage_writeback_" + name, lambda *_a, **_kw: {})
    monkeypatch.setattr(s, "_source_collection_stage_writeback_closure_summary", lambda *_a, **_kw: {
        "artifactComplete": True, "taskChecklistComplete": True,
    })
    monkeypatch.setattr(s, "_source_collection_stage_completion_gate", lambda **_: {"passed": True})
    with pytest.raises(s.TeamWorkflowOrchestrationError, match="evidence_relation_graph_invalid.*counterEvidenceRefs"):
        stage_writeback.writeback_source_collection_stage_session_task("team", "task", {"status": status})
    assert task["status"] == "running"


def test_relation_context_refreshes_validation_outside_cached_payload(monkeypatch, graph):
    from tools import source_collection_stage_tools as tools
    from core.web.services import team_workflow_orchestration_service as workflow

    monkeypatch.setattr(tools, "_resolve_source_collection_team_id", lambda **_: ("team", {}))
    monkeypatch.setattr(tools, "_record_stage_tool_event", lambda *_a, **_kw: None)
    monkeypatch.setattr(workflow, "get_source_collection_stage_task_context", lambda *_a, **_kw: {
        "stageId": "relations", "runId": "source", "taskId": "relation-feedback-test",
    })
    tools._invalidate_source_context_cache(team_id="team", task_id="relation-feedback-test")
    result = json.loads(tools.source_collection_context_tool(team_id="team", task_id="relation-feedback-test"))
    assert result["relationArtifactValidation"]["valid"] is True
    graph["evidenceGaps"] = []
    result = json.loads(tools.source_collection_context_tool(team_id="team", task_id="relation-feedback-test"))
    assert result["relationArtifactValidation"]["valid"] is False
    assert "evidenceGaps" in result["relationArtifactValidation"]["detail"]
    tools._invalidate_source_context_cache(team_id="team", task_id="relation-feedback-test")
