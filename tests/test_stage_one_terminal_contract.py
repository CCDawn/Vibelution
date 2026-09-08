"""Stage-one frozen graph, canonical package inputs and Ledger closeout."""

import json

import pytest

from core.research.workflow.challenge_cup_runtime import successor_map
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import (
    definition_identity, reset_registry_for_tests, resolve_definition_by_version_id,
)
from core.research.workflow.stage_one_definition import stage_one_creation_definition
from core.web.services.team_workflow.research_runtime import (
    question_launch, real_domain_ports, run_creation, workflow_artifact_store,
)
from core.web.services.team_workflow.research_runtime.readiness import NodeReadinessService
from core.web.services.team_workflow.research_runtime.real_readiness_context import RealDomainReadinessContext
from core.web.services.team_workflow.research_runtime.service import _definition_meta_from
from tests._support.graph_helpers import GraphHarness
from tests._support.readiness_fakes import FakeDomainContext, make_run
from tests.test_research_workflow_result_package_terminal import _seed_succeeded_package


def test_new_definition_survives_registry_restart_and_preserves_full_graph(tmp_path):
    definition, identity = stage_one_creation_definition()
    assert [node.nodeId for node in definition.nodes] == [
        "problem_understanding", "hypothesis_design", "result_package",
    ]
    reset_registry_for_tests()
    assert resolve_definition_by_version_id(identity.workflowVersionId) == definition
    assert successor_map(identity.workflowVersionId)["hypothesis_design"] == ("result_package",)
    old = definition_identity(build_challenge_cup_workflow_definition())
    assert successor_map(old.workflowVersionId)["hypothesis_design"] == ("protocol_design",)
    assert _definition_meta_from(definition.workflowId, definition=definition)[1] == identity
    assert run_creation._question_run_creation_definition() == definition
    from core.web.services.team_workflow.research_runtime.checkpoint_lifecycle import (
        prepare_initial_checkpoint, latest_checkpoint_id,
    )
    path = str(tmp_path / "stage-one.sqlite")
    checkpoint = prepare_initial_checkpoint(path, "run-stage-one", definition=definition)
    assert latest_checkpoint_id(path, "run-stage-one", definition=definition) == checkpoint


def test_question_progress_uses_each_frozen_graph_without_cross_version_success():
    definition, identity = stage_one_creation_definition()
    old = definition_identity(build_challenge_cup_workflow_definition())
    rows = [
        {**old.to_dict(), "runId": "old", "questionId": "SCI-011", "status": "succeeded", "updatedAtMs": 1},
        {**identity.to_dict(), "runId": "new", "questionId": "SCI-011", "status": "blocked",
         "runtimeCurrentNodeIds": ["result_package"], "updatedAtMs": 2},
        {**old.to_dict(), "runId": "other", "questionId": "SCI-012", "status": "running",
         "runtimeCurrentNodeIds": ["protocol_design"], "updatedAtMs": 2},
    ]
    result = question_launch.attach_question_run_checkpoints(
        [{"questionId": "SCI-011"}, {"questionId": "SCI-012"}], rows
    )
    assert result[0]["checkpoint"]["totalSteps"] == len(definition.nodes)
    assert result[0]["checkpoint"]["completedCount"] == 2
    assert result[0]["checkpoint"]["status"] == "blocked"
    assert result[1]["checkpoint"]["totalSteps"] == 12


@pytest.fixture
def stage_one_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow_artifact_store, "_root", lambda: tmp_path)
    monkeypatch.setattr(workflow_artifact_store, "resolve_project_workspace_home", lambda _: tmp_path)
    harness = GraphHarness(tmp_path)
    definition, identity = stage_one_creation_definition()
    harness.seed(workflow_definition=definition, status="running")
    snapshot = {
        "snapshotHash": "a" * 64, "teamId": "research-team", "questionId": "SCI-096",
        "constraintSnapshot": {"formalWrites": False},
    }
    harness.commands.store.submit(lambda uow: uow.repository.execute(
        "UPDATE workflow_runs SET input_snapshot_json = ? WHERE run_id = ?",
        (json.dumps(snapshot), "run-test"),
    ), force_flush=True).result(timeout=10)
    try:
        yield harness, identity
    finally:
        harness.close()


def _put(kind, payload, *, run_id="run-test"):
    return workflow_artifact_store.put_workflow_artifact(
        "research-team", kind=kind, workflow_run_id=run_id,
        source_collection_run_id=run_id, payload=payload, artifact_identity=f"test:{kind}",
    )


@pytest.mark.parametrize("missing", [None, "stage1_research_plan", "dimension_reviews", "hypothesis_set"])
def test_packaging_gate_reads_current_inputs_without_experiment_governance(stage_one_runtime, missing):
    harness, identity = stage_one_runtime
    for kind in ("problem_understanding", "hypothesis_set", "dimension_reviews", "stage1_research_plan", "competition_alignment"):
        payload = {"human_gate": {"decision": "approved"}}
        _put(kind, payload, run_id="run-other" if kind == missing else "run-test")
    actual = RealDomainReadinessContext(harness.commands.store).result_package("research-team", "run-test")
    context = FakeDomainContext()
    context._result_package = actual
    context._version_governance = None
    run = make_run(workflow_version_id=identity.workflowVersionId)
    result = NodeReadinessService(run_source=lambda _: run).evaluate(
        team_id="research-team", run_id="run-test", node_id="result_package", context=context, use_cache=False,
    )
    assert result.ready is (missing is None)
    if missing:
        assert any(item.code == "result_package_incomplete" for item in result.blockers)


def test_system_port_supplies_ledger_projection_and_terminal_closes_once(stage_one_runtime, monkeypatch):
    from core.research.workflow.contracts import PendingAction
    from core.research.workflow.models import ActorKind

    harness, identity = stage_one_runtime
    captured = {}

    def execute(action, **kwargs):
        captured.update(kwargs["input_snapshot"])
        return [], {"runnerId": "test"}

    monkeypatch.setattr(real_domain_ports, "_execute_real_system_action", execute)
    action = PendingAction("action", "run-test", "nr-package", "result_package", 1,
                           ActorKind.SYSTEM, "build_package", "a" * 64, (), None, "budget")
    real_domain_ports.RealDomainPorts(harness.commands.store).execute_system_action(action=action)
    record = captured["workflowRunProjection"]
    assert record["workflowVersionId"] == identity.workflowVersionId
    assert record["terminalReason"] == "stage_one_proposal_completed"
    assert record["inputSnapshot"]["constraintSnapshot"]["formalWrites"] is False
    _put("research_result_package", {"package": {
        "terminalReason": record["terminalReason"], "traceability": {"artifactRefs": ["hypothesis"]},
    }})
    _seed_succeeded_package(harness, "run-test")
    assert harness.worker.run_once() >= 1
    completed = harness.commands.store.get_run("run-test")
    assert completed.status == "succeeded"
    assert completed.completion_kind == "proposal_completed"
    assert completed.terminal_reason == "stage_one_proposal_completed"
    harness.worker.run_once()
    assert harness.commands.store.get_run("run-test").completed_at_ms == completed.completed_at_ms
