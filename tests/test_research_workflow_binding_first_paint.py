"""First-paint bindings must not hydrate full Team canvas or Agent APIs."""

from __future__ import annotations

from pathlib import Path

from core.web.services.team_workflow.research_runtime.team_role_source import (
    resolve_team_role_bindings,
)

ROLE_SOURCE = Path("core/web/services/team_workflow/research_runtime/team_role_source.py")
RUNTIME_SERVICE = Path("core/web/services/team_workflow/research_runtime/service.py")
QUERY_SERVICE = Path("core/web/services/team_workflow/research_runtime/query_service.py")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_role_source_uses_light_binding_records() -> None:
    source = _read(ROLE_SOURCE)
    assert "list_team_role_binding_sources" in source
    assert "get_team_canvas" not in source
    assert "from core.web.services.team_service import get_team, get_team_canvas" not in source


def test_display_name_lookup_skips_full_agent_api() -> None:
    runtime = _read(RUNTIME_SERVICE)
    query = _read(QUERY_SERVICE)
    assert "lookup_agent_display_name_map" in runtime
    assert "def _agent_display_name(" in runtime
    assert "from core.web.services.agent_directory_service import get_agent" not in runtime
    assert "lookup_agent_display_name_map" in query
    assert "from core.web.services.agent_directory_service import get_agent" not in query


def test_resolve_team_role_bindings_ignores_canvas_without_full_hydration(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("full team/canvas hydration must not run")

    monkeypatch.setattr("core.web.services.team_service.get_team", boom)
    monkeypatch.setattr("core.web.services.team_service.get_team_canvas", boom)
    monkeypatch.setattr(
        "core.web.services.team_service.list_team_role_binding_sources",
        lambda _team_id: {
            "canvas_nodes": [{"role": "source_finder", "agentId": "agent-canvas"}],
            "members": [
                {"role": "source_finder", "agentId": "agent-member"},
                {"role": "source_extractor", "agentId": "agent-extract"},
            ],
        },
    )

    assert resolve_team_role_bindings("research-team") == {
        "source_finder": "agent-member",
        "source_extractor": "agent-extract",
    }


def test_resolve_team_role_bindings_empty_on_lookup_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.web.services.team_service.list_team_role_binding_sources",
        lambda _team_id: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )
    assert resolve_team_role_bindings("research-team") == {}
    assert resolve_team_role_bindings("") == {}
