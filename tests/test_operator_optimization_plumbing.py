import pytest

from core.research.workflow.models import AgentBindingLayers
from core.research.workflow.operator_optimization_definition import OPERATOR_ARTIFACT_KINDS
from core.web.services.team_workflow.research_runtime.binding_config import (
    BindingConfigValidationError, WorkflowBindingConfigStore,
)
from core.web.services.team_workflow.research_runtime import workflow_artifact_store as artifacts
from core.web.services.team_workflow.research_runtime.artifact_readback_registry import load_scoped_artifact_payload
from core.web.services.team_workflow.research_runtime.human_gate_artifacts import canonical_sha256


def test_runtime_binding_view_uses_operator_graph(tmp_path, monkeypatch):
    from core.web.services.team_workflow.research_runtime import service
    runtime = service.ResearchWorkflowRuntimeService.__new__(service.ResearchWorkflowRuntimeService)
    monkeypatch.setattr(runtime, "_effective_binding_layers", lambda *args: AgentBindingLayers(
        nodeOverrides={"optimization_discussion": "planner"},
    ))
    monkeypatch.setattr(service, "_agent_display_name_map", lambda: {})
    result = runtime.get_effective_agent_bindings("operator-optimization")
    assert {row["nodeId"] for row in result["bindings"]} == {
        "optimization_discussion", "optimization_plan",
    }
    assert runtime.get_effective_agent_bindings("operator-optimization-baseline")["bindings"] == []


def test_binding_overrides_are_validated_against_selected_graph(tmp_path):
    store = WorkflowBindingConfigStore(tmp_path)
    layers = AgentBindingLayers(nodeOverrides={"optimization_discussion": "planner"})
    store.save("operator-optimization", "team", layers)
    assert store.load("operator-optimization", "team").nodeOverrides == layers.nodeOverrides
    with pytest.raises(BindingConfigValidationError):
        store.save("challenge-cup-research", "team", layers)
    with pytest.raises(BindingConfigValidationError):
        store.save("operator-optimization-baseline", "team", layers)
    with pytest.raises(BindingConfigValidationError):
        store.save("operator-optimization", "team", AgentBindingLayers(nodeOverrides={"hypothesis_design": "planner"}))


@pytest.mark.parametrize("kind", sorted(OPERATOR_ARTIFACT_KINDS))
def test_operator_artifacts_use_canonical_scoped_hash_readback(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(artifacts, "_path", lambda team, kind: tmp_path / team / f"{kind}.jsonl")
    payload = {"researchProjectId": "project", "optimizationCampaignId": "campaign", "value": 1}
    artifacts.put_workflow_artifact("team", kind=kind, workflow_run_id="run", payload=payload)
    args = dict(team_id="team", workflow_run_id="run", authority_run_id="run")
    envelope = load_scoped_artifact_payload(kind, **args)
    assert envelope["payload"] == payload
    args["content_hash"] = canonical_sha256(envelope)
    assert load_scoped_artifact_payload(kind, **args) == envelope
    assert load_scoped_artifact_payload(kind, **{**args, "workflow_run_id": "other"}) is None
    assert load_scoped_artifact_payload(kind, **{**args, "content_hash": "0" * 64}) is None
