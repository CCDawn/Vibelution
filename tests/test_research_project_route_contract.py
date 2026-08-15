"""Research-project list JSON response contract regressions."""

from __future__ import annotations

from core.web.routes.team_workflows._models import ResearchProjectListResponse


def test_research_project_list_publishes_known_schema_fields() -> None:
    properties = set(ResearchProjectListResponse.model_json_schema().get("properties") or {})
    expected = {
        "schemaVersion",
        "teamId",
        "activeProjectId",
        "projects",
        "updatedAt",
        "project",
    }
    assert expected <= properties, (
        f"ResearchProjectListResponse is missing fields: {sorted(expected - properties)}"
    )


def test_research_project_list_keeps_unknown_fields() -> None:
    payload = ResearchProjectListResponse.model_validate(
        {
            "teamId": "team-1",
            "projects": [{"projectId": "research-1", "name": "Loop"}],
            "project": {"projectId": "research-1"},
        }
    ).model_dump()

    assert payload["projects"] == [{"projectId": "research-1", "name": "Loop"}]
    assert payload["project"] == {"projectId": "research-1"}


def test_research_project_list_keeps_unknown_fields_without_injecting_defaults() -> None:
    payload = ResearchProjectListResponse.model_validate(
        {
            "teamId": "team-1",
            "activeProjectId": "legacy-default",
            "futureHint": {"owner": "research_projects"},
        }
    ).model_dump(exclude_unset=True)

    assert payload == {
        "teamId": "team-1",
        "activeProjectId": "legacy-default",
        "futureHint": {"owner": "research_projects"},
    }
