from types import SimpleNamespace

from core.research.workflow.operator_optimization_definition import build_operator_definition
from core.web.services.team_workflow.research_runtime.readiness.operator_optimization import evaluate_operator_node
from core.web.services.team_workflow.research_runtime.readiness import NodeReadinessService


def test_operator_definitions_have_readiness_evaluators():
    for baseline in (False, True):
        service = NodeReadinessService(run_source=lambda _: None, definition=build_operator_definition(baseline=baseline))
        service.assert_registry_complete()


def test_baseline_requires_authorized_budget_and_frozen_setup_without_hypothesis_gate():
    run = SimpleNamespace(team_id="team", project_id="project", run_id="run")
    node = build_operator_definition(baseline=True).nodes[0]
    state = {"campaign": {"teamId": "team", "researchProjectId": "project", "status": "running",
        "activeRunId": "run", "revision": 1, "baselineRef": None,
        "budget": {"authorized": False, "gpuSecondsLimit": 60, "modelCostLimit": 0}},
        "environmentVerified": False, "protocolFrozen": False,
        "budgetSummary": {"gpuTuningAvailableSeconds": 48}}
    context = SimpleNamespace(operator_campaign_state=lambda *_: state)
    result = evaluate_operator_node(run, node, None, context)
    assert {item.code for item in result.blockers} == {
        "operator_budget_unauthorized", "operator_environment_unverified", "operator_protocol_missing"}
    state["campaign"]["budget"]["authorized"] = True
    state.update(environmentVerified=True, protocolFrozen=True)
    assert evaluate_operator_node(run, node, None, context).ready
    state["budgetSummary"]["gpuTuningAvailableSeconds"] = 0
    assert {b.code for b in evaluate_operator_node(run, node, None, context).blockers} == {"operator_gpu_budget_empty"}
    state["budgetSummary"]["gpuTuningAvailableSeconds"] = 48
    state["campaign"]["status"] = "paused"
    assert not evaluate_operator_node(run, node, None, context).ready
