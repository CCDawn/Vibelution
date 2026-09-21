"""A recovery replaces an execution, never the experiment or its liabilities."""
import json

import pytest

from core.research.workflow.models import AgentBindingLayers
from core.web.services.team_workflow.operator_optimization import rounds
from core.web.services.team_workflow.operator_optimization.store import CampaignConflict, read_campaign
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests._support.workflow_ledger_helpers import open_ledger_store
from tests.test_operator_optimization_budget import activity
from tests.test_operator_optimization_rounds import ready, actual_create_run


@pytest.fixture
def cancelled(activity, ready, tmp_path, monkeypatch):
    campaign, baseline, _ = ready
    ledger = open_ledger_store(tmp_path / "recovery.sqlite")

    class Store:
        def get_run(self, run_id):
            return baseline if run_id == "run1" else ledger.get_run(run_id)

        def __getattr__(self, name):
            return getattr(ledger, name)

    monkeypatch.setattr(rounds.run_creation, "get_write_store", lambda: Store())
    monkeypatch.setattr(rounds.run_creation, "create_run", actual_create_run)
    monkeypatch.setattr(rounds.run_creation, "research_workflow_data_root", lambda: tmp_path)
    monkeypatch.setattr(rounds.run_creation, "effective_binding_layers", lambda team, layers, **kwargs:
        layers if layers.nodeOverrides else AgentBindingLayers(
            workflowDefaults={"experiment_planner": "original-planner"}))
    campaign = rounds.prepare_round(*activity, expected_version=campaign.revision, command_key="first")
    # update_run_status is a full-replacement settlement: the cancel keeps
    # the node the run was cancelled at, exactly like the production
    # cancel_run command does (recover_round re-checks that pointer).
    cancelled_at_node = ledger.get_run(campaign.activeRunId).active_node_id
    ledger.submit(lambda uow: uow.repository.update_run_status(
        campaign.activeRunId, activity[0], "cancelled", 100,
        active_node_id=cancelled_at_node), force_flush=True).result()
    try:
        yield campaign, ledger
    finally:
        ledger.close()


def recover(activity, campaign, key="recover"):
    from core.web.services.team_workflow.operator_optimization.recovery import recover_round

    with server_operator_scope("operator", roles=("operator",)):
        return recover_round(*activity, campaign.rounds[-1].roundId,
            expected_version=campaign.revision, command_key=key)


def test_recovery_preserves_round_budget_and_frozen_sources(activity, cancelled, monkeypatch):
    from core.web.services.team_workflow.research_runtime.team_role_source import effective_binding_layers

    monkeypatch.setattr(rounds.run_creation, "effective_binding_layers", effective_binding_layers)
    campaign, ledger = cancelled
    old = ledger.get_run(campaign.activeRunId)
    recovered = recover(activity, campaign)
    assert recovered.activeRunId != old.run_id
    assert recovered.budget == campaign.budget
    assert recovered.gpuReservations == campaign.gpuReservations
    assert recovered.baselineRef == campaign.baselineRef
    assert len(recovered.rounds) == len(campaign.rounds) == 1
    record = recovered.rounds[0]
    assert record.roundId == campaign.rounds[0].roundId
    assert record.ordinal == 1
    assert record.previousRunIds == (old.run_id,)
    assert ledger.get_run(old.run_id) == old
    new = ledger.get_run(recovered.activeRunId)
    assert new.status == "created" and new.active_node_id == "optimization_discussion"
    assert new.workflow_version_id == old.workflow_version_id
    before, after = map(json.loads, (old.input_snapshot_json, new.input_snapshot_json))
    for key in ("researchObjectiveContract", "budgetPolicy", "stopPolicy", "modelRoutingPolicy", "datasetRefs"):
        assert after[key] == before[key]
    assert [(b["nodeId"], b["agentId"]) for b in after["agentBindingSnapshot"]] == [
        (b["nodeId"], b["agentId"]) for b in before["agentBindingSnapshot"]]
    assert record.protocolRef.runId == new.run_id
    for kind, digest in (("operator_environment", after["environmentSnapshotRef"]),
                         ("operator_measurement_protocol", record.protocolRef.sha256)):
        assert rounds.load_scoped_artifact_payload(kind, team_id=activity[0],
            workflow_run_id=new.run_id, authority_run_id=new.run_id, content_hash=digest)
    assert recover(activity, campaign) == recovered
    with pytest.raises(CampaignConflict):
        recover(activity, recovered, "another-key")


def test_recovery_new_run_can_read_discussion_evidence(activity, cancelled, monkeypatch):
    from core.web.services.team_workflow.operator_optimization import discussion

    campaign, _ = cancelled
    recovered = recover(activity, campaign)
    monkeypatch.setattr(discussion, "get_write_store", rounds.run_creation.get_write_store)
    inputs = discussion.discussion_input(activity[0], recovered.activeRunId)
    assert inputs["context"]["roundId"] == campaign.rounds[0].roundId
    assert inputs["evidence"][0]["sourceRunId"] == campaign.baselineRunId


def test_recovery_replays_orphan_successor_after_campaign_write_failure(activity, cancelled, monkeypatch):
    from core.web.services.team_workflow.operator_optimization import store

    campaign, ledger = cancelled
    service = store._service()
    original = service._write_json

    def fail_campaign(path, payload):
        if "campaign" in payload:
            raise OSError("simulated campaign persistence failure")
        return original(path, payload)

    monkeypatch.setattr(service, "_write_json", fail_campaign)
    with pytest.raises(OSError, match="simulated"):
        recover(activity, campaign)
    runs = ledger.read(lambda repo: repo.list_runs_for_team(activity[0], "operator-optimization"))
    assert len(runs) == 2
    monkeypatch.setattr(service, "_write_json", original)
    recovered = recover(activity, campaign, "replacement-key")
    assert recovered.activeRunId in {run.run_id for run in runs}
    assert len(ledger.read(lambda repo: repo.list_runs_for_team(activity[0], "operator-optimization"))) == 2


def test_repeated_recovery_accumulates_history(activity, cancelled):
    campaign, ledger = cancelled
    first = recover(activity, campaign)
    # Full-replacement cancel: keep the cancelled-at node like production.
    first_cancelled_at_node = ledger.get_run(first.activeRunId).active_node_id
    ledger.submit(lambda uow: uow.repository.update_run_status(
        first.activeRunId, activity[0], "cancelled", 200,
        active_node_id=first_cancelled_at_node), force_flush=True).result()
    second = recover(activity, first, "recover-again")
    assert second.rounds[0].previousRunIds == (campaign.activeRunId, first.activeRunId)
    assert second.rounds[0].ordinal == 1


def test_recovery_requires_operator_even_for_replay(activity, cancelled):
    from core.web.services.team_workflow.operator_optimization.recovery import recover_round

    campaign, _ = cancelled
    recover(activity, campaign)
    with pytest.raises(PermissionError):
        recover_round(*activity, campaign.rounds[0].roundId,
            expected_version=campaign.revision, command_key="recover")


def test_recovery_rejects_later_stage(activity, cancelled):
    campaign, ledger = cancelled
    ledger.submit(lambda uow: uow.repository.execute(
        "UPDATE workflow_runs SET active_node_id='experiment_planning' WHERE run_id=?",
        (campaign.activeRunId,)), force_flush=True).result()
    with pytest.raises(CampaignConflict, match="discussion"):
        recover(activity, campaign)
    assert read_campaign(*activity) == campaign


@pytest.mark.parametrize("field,value", [("team_id", "other-team"), ("project_id", "other-project")])
def test_recovery_rejects_wrong_ledger_owner(activity, cancelled, field, value):
    campaign, ledger = cancelled
    ledger.submit(lambda uow: uow.repository.execute(
        f"UPDATE workflow_runs SET {field}=? WHERE run_id=?", (value, campaign.activeRunId)),
        force_flush=True).result()
    with pytest.raises(CampaignConflict, match="scope"):
        recover(activity, campaign)


def test_recovery_keeps_old_model_liability_in_new_run_admission(activity, cancelled):
    from core.research.operator_optimization.model_budget_contracts import OperatorDiscussionBudget
    from core.web.services.team_workflow.operator_optimization.model_budget import reserve_model_budget, ModelBudgetError
    from tests.test_operator_optimization_model_budget import _seed_parent

    campaign, ledger = cancelled
    budget = OperatorDiscussionBudget.model_validate({"tokenLimit": 1000,
        "maxOutputTokensPerCall": 100, "maxCalls": 3,
        "prices": [{"modelRef": "qwen/test", "priceVersion": "test", "currency": "CNY",
            "inputPerMillion": 6000, "outputPerMillion": 6000}]})
    kwargs = {"optimization_campaign_id": activity[2], "round_id": campaign.rounds[0].roundId,
        "discussion_budget": budget, "model_cost_limit": campaign.budget.modelCostLimit,
        "campaign_currency": "CNY", "model_ref": "qwen/test", "policy_hash": "test"}
    _seed_parent(ledger, run_id=campaign.activeRunId, node_run_id="old-discussion")
    receipt = reserve_model_budget(ledger, run_id=campaign.activeRunId,
        node_run_id="old-discussion", **kwargs)
    recovered = recover(activity, campaign)
    _seed_parent(ledger, run_id=recovered.activeRunId, node_run_id="new-discussion")
    with pytest.raises(ModelBudgetError, match="limit"):
        reserve_model_budget(ledger, run_id=recovered.activeRunId, node_run_id="new-discussion", **kwargs)
    assert reserve_model_budget(ledger, run_id=campaign.activeRunId,
        node_run_id="old-discussion", **kwargs)["reservationId"] == receipt["reservationId"]
