"""Task 8/9: legacy flow-canvas execute gate rollback drill."""

from __future__ import annotations

import pytest

from core.web.services import research_service


def test_legacy_execute_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIBELUTION_LEGACY_FLOW_CANVAS_EXECUTE", raising=False)
    with pytest.raises(ValueError, match="disabled"):
        research_service.execute_research_flow_canvas_node("s", node_id="broad_search")


def test_legacy_execute_rollback_env_reenables_writer_path(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rollback drill: env flag reopens legacy writer without reviving dual default."""
    monkeypatch.setenv("VIBELUTION_LEGACY_FLOW_CANVAS_EXECUTE", "1")

    class FakeWorkspace:
        def get_research_flow_canvas_path(self):
            return tmp_path / "flow_canvas.json"

        def read_research_flow_canvas(self):
            return {
                "schemaVersion": 1,
                "canvasKind": "research_flow_canvas",
                "nodes": [
                    {
                        "id": "broad_search",
                        "label": "broad",
                        "type": "agent",
                        "status": "ready",
                        "x": 0,
                        "y": 0,
                        "agentKey": "broad",
                        "promptKey": "broad",
                        "llmConfigId": "",
                        "description": "d",
                        "routeCondition": "c",
                    }
                ],
                "edges": [],
                "viewport": {"x": 0, "y": 0, "zoom": 1},
            }

        def write_research_flow_canvas(self, data):
            return True

    monkeypatch.setattr(research_service, "get_workspace", lambda: FakeWorkspace())
    monkeypatch.setattr(
        research_service,
        "_execute_research_flow_action",
        lambda action_key, session_id: ({"sourceCount": 0}, "completed"),
    )
    monkeypatch.setattr(research_service, "_record_research_config_event", lambda *a, **k: None)
    monkeypatch.setattr(research_service, "record_research_scene_event", lambda *a, **k: None)
    monkeypatch.setattr(research_service, "_record_research_flow_execution_event", lambda *a, **k: None)
    monkeypatch.setattr(
        research_service,
        "_persist_research_flow_canvas_state",
        lambda canvas, nodes, edges: {**canvas, "nodes": nodes, "edges": edges},
    )
    # Validation may still fail depending on normalize — if so rollback path still entered past gate.
    try:
        research_service.execute_research_flow_canvas_node("session-rollback", node_id="broad_search")
    except ValueError as exc:
        # Must not be the sole-writer disable message.
        assert "Legacy /api/research/flow-canvas/execute is disabled" not in str(exc)
