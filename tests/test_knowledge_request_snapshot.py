"""The child must receive the request it is being asked to investigate."""
import json
from pathlib import Path

import pytest

from tests.test_knowledge_sideflow_run import _invoke, _seed_parent
from tests._support.graph_helpers import GraphHarness


def test_child_freezes_full_request_and_replays_without_replacing_it(tmp_path: Path):
    harness = GraphHarness(tmp_path)
    try:
        _seed_parent(harness)
        context = {"roundId": "round-1", "evidenceGaps": ["Does vectorization help?"]}
        result = _invoke(harness, consumer_context=context)
        child = harness.commands.store.get_run(result["childRunId"])
        frozen = json.loads(child.input_snapshot_json)
        request = frozen["knowledgeRequest"]
        assert request["consumerContext"] == context
        assert request["searchEnvelope"]["keywords"] == ["evaporation", "cooling"]
        assert request["requirements"] == {"minSources": 3}
        context["evidenceGaps"].append("mutated after dispatch")
        replay = _invoke(harness, consumer_context=request["consumerContext"])
        assert replay["childRunId"] == child.run_id
        assert harness.commands.store.get_run(child.run_id).input_snapshot_json == child.input_snapshot_json
    finally:
        harness.close()


def test_collection_payload_uses_gaps_and_retains_full_request():
    from core.web.services.team_workflow.research_runtime.knowledge_request_snapshot import collection_request_scope

    snapshot = {"knowledgeRequest": {
        "scope": {"teamId": "team-a"},
        "searchEnvelope": {"claimsToInvestigate": ["vectorized loads", "tail correctness"]},
        "requirements": {"operatorClaims": {"counterevidence": "tails regress"}},
        "consumerContext": {"roundId": "round-a"},
    }}
    result = collection_request_scope(snapshot)
    assert result["searchEnvelope"]["claimsToInvestigate"] == ["vectorized loads", "tail correctness"]
    assert result["knowledgeRequest"] == snapshot["knowledgeRequest"]
    assert result["requirements"]["operatorClaims"]["counterevidence"] == "tails regress"
    assert result["seedQueries"] == ["vectorized loads", "tail correctness"]
    assert collection_request_scope({}) == {}


def test_changed_request_is_rejected_before_child_creation(tmp_path: Path):
    from dataclasses import replace
    from core.web.services.team_workflow.research_runtime.knowledge_sideflow_service import (
        KnowledgeSideflowError, ensure_knowledge_child_run,
    )

    harness = GraphHarness(tmp_path)
    try:
        _seed_parent(harness)
        result = _invoke(harness)
        invocation = replace(result["invocation"], invocation_id="kinv-altered", knowledge_child_run_id=None)
        request = json.loads(harness.commands.store.get_run(result["childRunId"]).input_snapshot_json)["knowledgeRequest"]
        request["requirements"]["minSources"] = 99
        with pytest.raises(KnowledgeSideflowError) as error:
            ensure_knowledge_child_run(harness.commands.store, invocation, request=request)
        assert error.value.code == "knowledge_request_mismatch"
        with pytest.raises(KnowledgeSideflowError) as error:
            ensure_knowledge_child_run(harness.commands.store, invocation)
        assert error.value.code == "knowledge_request_missing"
    finally:
        harness.close()


def test_native_source_adapter_passes_request_to_collection_and_query_planner(monkeypatch):
    from types import SimpleNamespace
    from core.web.services.team_workflow.research_runtime.real_domain_ports import _start_source_collection_agent_task
    from core.web.services.team_workflow.source_collection import residual

    captured = {}
    request = {"scope": {}, "searchEnvelope": {"claimsToInvestigate": ["softmax vector loads"]},
               "requirements": {"operatorClaims": {"counterevidence": "tail slowdown"}},
               "consumerContext": {"roundId": "round-a"}}
    def start_run(team_id, payload):
        captured.update(payload)
        return {"run": {"runId": "collection-a"}}
    monkeypatch.setattr("core.web.services.team_workflow.source_collection.runs.start_source_collection_run", start_run)
    monkeypatch.setattr("core.web.services.team_workflow.research_runtime.source_stage_task_replay.find_reusable_source_stage_task", lambda **kw: None)
    monkeypatch.setattr("core.web.services.team_workflow.source_collection.stage_session.start_source_collection_stage_session_task", lambda *args: {"taskId": "task-a"})
    _start_source_collection_agent_task(team_id="team-a", project_id="project-a",
        input_snapshot={"knowledgeRequest": request},
        action=SimpleNamespace(run_id="child-a", node_id="source_finding", attempt=1),
        binding=SimpleNamespace(agent_id="finder-a"), stage_id="finding", role_key="source_finder", idempotency_key="start-a")
    assert captured["scope"]["knowledgeRequest"] == request
    assert captured["scope"]["workflowRunId"] == "child-a"
    seeds = residual._source_collection_query_seeds(captured, captured["scope"], [], topic="", goal="")
    assert "softmax vector loads" in seeds
