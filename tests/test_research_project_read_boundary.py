"""Project identity reads must not hydrate or repair the team's UI graph."""
import pytest

from core.web.services import team_service
from core.web.services.team_workflow import research_projects
from core.web.services.team_workflow.operator_optimization.store import read_campaign
from tests.test_operator_optimization_budget import activity


def test_operator_campaign_read_does_not_repair_team_or_load_chat_rooms(activity, monkeypatch):
    team, project, _ = activity
    expected = research_projects.get_research_project(team, project)

    def unexpected_team_repair(*args, **kwargs):
        raise AssertionError("project identity read entered team UI repair")

    monkeypatch.setattr(team_service, "_repair_team", unexpected_team_repair)
    assert research_projects.get_research_project(team, project) == expected
    assert read_campaign(*activity).researchProjectId == project


def test_project_identity_read_still_requires_existing_team_and_project(activity):
    team, project, _ = activity
    with pytest.raises(team_service.TeamNotFoundError):
        research_projects.get_research_project("missing-team", project)
    with pytest.raises(research_projects.ResearchProjectNotFoundError):
        research_projects.get_research_project(team, "missing-project")
