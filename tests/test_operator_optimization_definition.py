from core.research.workflow.bindings import build_run_binding_snapshots
from core.research.workflow.models import AgentBindingLayers
from core.research.workflow.operator_optimization_definition import build_operator_definition


def test_optimization_definition_and_bindings_do_not_reuse_challenge_nodes():
    definition = build_operator_definition()
    ids = {n.nodeId for n in definition.nodes}
    assert "optimization_discussion" in ids
    assert "hypothesis_design" not in ids
    snapshots = build_run_binding_snapshots(
        run_id="opt-run-1", workflow_version_id="v1", definition=definition,
        layers=AgentBindingLayers(), captured_at="2026-09-05T00:00:00Z",
    )
    assert snapshots
    assert {s.workflowId for s in snapshots} == {"operator-optimization"}
    assert {s.nodeId for s in snapshots} <= ids
    plan_node = next(n for n in definition.nodes if n.nodeId == "optimization_plan")
    assert plan_node.producesArtifactKinds == ("optimization_plan",)


def test_baseline_definition_has_no_hypothesis_prerequisite():
    definition = build_operator_definition(baseline=True)
    assert [n.nodeId for n in definition.nodes] == ["operator_baseline"]
    assert not definition.edges


def test_operator_artifacts_keep_protocol_candidate_and_plan_kinds_distinct():
    from core.research.workflow.operator_optimization_definition import OPERATOR_ARTIFACT_KINDS

    assert "operator_measurement_protocol" in OPERATOR_ARTIFACT_KINDS
    assert "operator_candidate" in OPERATOR_ARTIFACT_KINDS
    assert "optimization_plan" in OPERATOR_ARTIFACT_KINDS
    assert "optimization_protocol" not in OPERATOR_ARTIFACT_KINDS


def test_baseline_input_has_no_catalog_and_pins_canonical_ledger(tmp_path, monkeypatch):
    import json
    from core.research.operator_optimization.contracts import CampaignBudget, OptimizationCampaign, OperatorObjective
    from core.web.services.team_workflow.operator_optimization.run_input import build_operator_run_input
    from core.web.services.team_workflow.research_runtime import run_creation
    from tests._support.workflow_ledger_helpers import open_ledger_store

    campaign = OptimizationCampaign(
        optimizationCampaignId="opt-" + "a" * 24, teamId="team-1", researchProjectId="project-1",
        title="Softmax", objective=OperatorObjective(), budget=CampaignBudget(), baselineSetupId="baseline-1",
        createdAt="2026-09-05T00:00:00Z", updatedAt="2026-09-05T00:00:00Z",
    )
    from core.research.operator_optimization.candidate import CudaCandidate, CudaCandidateRef, source_hash
    baseline_candidate = CudaCandidate(implementation="torch_softmax")
    data = build_operator_run_input(campaign, baseline_candidate_ref=CudaCandidateRef(
        artifactId="baseline-candidate", runId="run-1", sha256="a" * 64,
        candidate=baseline_candidate, sourceHash=source_hash(baseline_candidate),
    ))
    assert "catalogScope" not in data
    ledger = open_ledger_store(tmp_path / "ledger.sqlite")
    monkeypatch.setattr(run_creation, "get_write_store", lambda: ledger)
    monkeypatch.setattr(run_creation, "research_workflow_data_root", lambda: tmp_path)
    monkeypatch.setattr(run_creation, "effective_binding_layers", lambda team, layers: layers)
    try:
        result = run_creation.create_run("operator-optimization-baseline", run_input=data, idempotency_key="baseline-1")
        saved = ledger.get_run(result["runId"])
        assert saved.project_id == "project-1"
        assert saved.active_node_id == "operator_baseline"
        snapshot = json.loads(saved.input_snapshot_json)
        assert snapshot["catalogScope"] == {}
        assert snapshot["agentBindingSnapshot"] == []
        assert run_creation.create_run("operator-optimization-baseline", run_input=data, idempotency_key="baseline-1")["runId"] == result["runId"]
    finally:
        ledger.close()
