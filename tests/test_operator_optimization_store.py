import pytest

from core.web.services import team_service, team_workflow_orchestration_service as service
from core.web.services.team_workflow.operator_optimization.store import (
    CampaignConflict, create_campaign, read_campaign, update_campaign,
)
from tests._support.team_workflow.cases_experiment import _use_tmp_project_root


def test_campaign_creation_replay_scope_and_version(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="Operator team")["teamId"]
    project = service.get_active_research_project(team)["projectId"]
    payload = {"title": "Softmax pilot", "idempotencyKey": "create-1"}
    created = create_campaign(team, project, payload)
    assert create_campaign(team, project, payload) == created
    cid = created.optimizationCampaignId
    assert created.rounds == () and created.baselineRef is None
    with pytest.raises(CampaignConflict):
        create_campaign(team, project, {**payload, "title": "Changed"})
    updated = update_campaign(team, project, cid, expected_version=1, command_key="pause-1",
        command={"kind": "pause"}, transform=lambda c: c.model_copy(update={"status": "paused"}))
    assert updated.revision == 2
    assert update_campaign(team, project, cid, expected_version=1, command_key="pause-1",
        command={"kind": "pause"}, transform=lambda c: pytest.fail("duplicate transform")) == updated
    with pytest.raises(CampaignConflict):
        update_campaign(team, project, cid, expected_version=1, command_key="pause-2",
            command={"kind": "pause"}, transform=lambda c: c)
    other = service.create_research_project(team, {"name": "Other"})["project"]["projectId"]
    with pytest.raises(FileNotFoundError):
        read_campaign(team, other, cid)
    service.activate_research_project(team, other)
    assert read_campaign(team, project, cid).revision == 2


def test_initial_candidate_cannot_change_after_it_is_frozen(tmp_path, monkeypatch):
    from tests.test_operator_optimization_contract import candidate_ref
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="Frozen candidate")["teamId"]
    project = service.get_active_research_project(team)["projectId"]
    campaign = create_campaign(team, project, {"title": "Softmax", "idempotencyKey": "frozen"})
    ref = candidate_ref()
    update_campaign(team, project, campaign.optimizationCampaignId, expected_version=1,
        command_key="freeze", command={"action": "freeze"},
        transform=lambda c: c.model_copy(update={"baselineCandidateRef": ref}))
    with pytest.raises(CampaignConflict, match="baseline candidate is immutable"):
        update_campaign(team, project, campaign.optimizationCampaignId, expected_version=2,
            command_key="replace", command={"action": "replace"},
            transform=lambda c: c.model_copy(update={"baselineCandidateRef": ref.model_copy(update={"sha256": "f" * 64})}))
