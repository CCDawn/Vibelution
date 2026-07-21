"""Stage 4 secondary-god pure helper packs."""

from __future__ import annotations

from core.web.services import agent_directory_service, team_service
from core.web.services.agent_directory import profiles
from core.web.services.team import canvas_primitives


def test_agent_profiles_reexport_and_normalize() -> None:
    assert agent_directory_service.normalize_persona_profile is profiles.normalize_persona_profile
    assert agent_directory_service.normalize_task_profile is profiles.normalize_task_profile
    persona = profiles.normalize_persona_profile(
        {"personality": "  calm  ", "expertise": "a, b"}
    )
    assert persona["personality"] == "calm"
    assert persona["expertise"] == ["a", "b"]
    task = profiles.normalize_task_profile({"mission": " dig ", "taskTypes": ["x", "x", "y"]})
    assert task["mission"] == "dig"
    assert task["taskTypes"] == ["x", "y"]
    assert profiles.agent_persona_profile_has_content(persona)
    assert profiles.agent_task_profile_has_content(task)


def test_team_canvas_primitives_reexport_and_edge_normalize() -> None:
    assert team_service.NODE_TYPES is canvas_primitives.NODE_TYPES
    assert team_service.EDGE_TYPES is canvas_primitives.EDGE_TYPES
    edge = canvas_primitives.normalize_edge(
        {"source": "n1", "target": "n2", "type": "reports_to", "label": "  leads  "},
        0,
        {"n1", "n2"},
    )
    assert edge["type"] == "reports_to"
    assert edge["label"] == "leads"
    try:
        canvas_primitives.normalize_edge({"source": "n1", "target": "missing"}, 1, {"n1"})
        raised = False
    except canvas_primitives.TeamCanvasValidationError:
        raised = True
    assert raised
