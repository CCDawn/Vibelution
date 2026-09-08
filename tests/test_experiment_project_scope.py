"""Formal plan operations retain the owner even when the project switcher changes."""
from __future__ import annotations

import pytest

from core.web.services import team_service
from core.web.services import team_workflow_orchestration_service as service
from tests._support.team_workflow.cases_experiment import (
    _seed_formal_full_run_plan,
    _use_tmp_project_root,
)


@pytest.mark.parametrize("explicit_project", [True, False])
def test_full_run_preparation_resolves_original_plan_after_switch(
    tmp_path, monkeypatch, explicit_project,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team_id = team_service.create_team(name="Scoped experiments")["teamId"]
    service.ensure_team_workflow_orchestration(team_id)
    project = service.get_active_research_project(team_id)
    plan_id = _seed_formal_full_run_plan(team_id)
    original_path = service._experiment_plan_store_path(team_id, project["projectId"])
    other = service.create_research_project(team_id, {"name": "Other project"})
    other_id = other["project"]["projectId"]
    service.activate_research_project(team_id, other_id)
    monkeypatch.setattr(service.formal_runner, "prepare_full_run", lambda *a, **k: {
        "adapterId": a[0], "status": "prepared", "seedCount": 3,
    })
    payload = {"executionConfig": {"outputRoot": str(tmp_path / "experiments" / "scoped")}}
    if explicit_project:
        payload["researchProjectId"] = project["projectId"]
    result = service.prepare_experiment_full_run(team_id, plan_id, payload)
    assert result["preparation"]["researchProjectId"] == project["projectId"]
    assert service._read_json(original_path)["plans"][0]["activeFullRunPreparationId"]
    assert service.get_active_research_project(team_id)["projectId"] == other_id
    with pytest.raises(service.TeamWorkflowOrchestrationError, match="not found|belong"):
        service.prepare_experiment_full_run(team_id, plan_id, {
            **payload, "researchProjectId": other_id,
        })


@pytest.mark.parametrize("fails", [False, True])
def test_full_run_terminal_writeback_survives_project_switch_in_runner(tmp_path, monkeypatch, fails):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team_id = team_service.create_team(name="Scoped writeback")["teamId"]
    service.ensure_team_workflow_orchestration(team_id)
    owner = service.get_active_research_project(team_id)["projectId"]
    plan_id = _seed_formal_full_run_plan(team_id)
    other = service.create_research_project(team_id, {"name": "Other"})["project"]["projectId"]
    service.activate_research_project(team_id, owner)

    def run(*args, **kwargs):
        service.activate_research_project(team_id, other)
        if fails:
            raise service.formal_runner.FormalRunnerError("controlled failure")
        return {"status": "completed", "adapterId": args[0], "seedCount": 3}

    monkeypatch.setattr(service.formal_runner, "run_full_run", run)
    payload = {"researchProjectId": owner, "executionConfig": {
        "outputRoot": str(tmp_path / "experiments" / "writeback"),
    }}
    if fails:
        with pytest.raises(service.TeamWorkflowOrchestrationError, match="controlled failure"):
            service.execute_experiment_full_run(team_id, plan_id, payload)
    else:
        service.execute_experiment_full_run(team_id, plan_id, payload)
    plan = service._load_experiment_plan_store(team_id, owner)["plans"][0]
    assert plan["activeFullRunExecution"]["researchProjectId"] == owner
    assert plan["activeFullRunExecution"]["status"] == ("failed" if fails else "completed")
    assert service.get_active_research_project(team_id)["projectId"] == other
