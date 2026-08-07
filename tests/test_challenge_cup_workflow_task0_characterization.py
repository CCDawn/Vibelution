"""Task 0 characterization: lock split SSOT before Challenge Cup workflow rewrite.

Proves current production behavior only. Does not implement the new LangGraph domain.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.web.services import (
    agent_directory_service,
    agent_mode_binding_service,
    prompt_template_service,
    research_organization_service,
    research_service,
    session_service,
    team_service,
)


class _FakeWorkspace:
    def __init__(self, root: Path):
        self.root = root / "workspace"

    def get_research_flow_canvas_path(self) -> Path:
        return self.root / "prompts" / "research" / "flow_canvas.json"

    def get_research_organization_path(self) -> Path:
        return self.root / "research" / "organization_graph.json"

    def read_research_flow_canvas(self) -> dict:
        path = self.get_research_flow_canvas_path()
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def write_research_flow_canvas(self, data) -> bool:
        path = self.get_research_flow_canvas_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return True

    def read_research_organization(self) -> dict:
        path = self.get_research_organization_path()
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def write_research_organization(self, data) -> bool:
        path = self.get_research_organization_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return True


def _worker_flow_canvas() -> dict:
    """Saved execution graph with pipeline node ids (not organization agents)."""
    return {
        "schemaVersion": 1,
        "canvasKind": "research_flow_canvas",
        "updatedAt": "2026-08-07T00:00:00Z",
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "nodes": [
            {
                "id": "broad_search",
                "label": "广撒网",
                "type": "agent",
                "status": "ready",
                "x": 80,
                "y": 160,
                "agentKey": "broad",
                "promptKey": "broad",
                "llmConfigId": "",
                "description": "worker node",
                "routeCondition": "start",
            },
            {
                "id": "deep_search",
                "label": "深搜",
                "type": "agent",
                "status": "idle",
                "x": 400,
                "y": 160,
                "agentKey": "deep",
                "promptKey": "deep",
                "llmConfigId": "",
                "description": "worker node",
                "routeCondition": "after broad",
            },
        ],
        "edges": [
            {
                "id": "edge_broad_deep",
                "source": "broad_search",
                "target": "deep_search",
                "label": "线索",
                "condition": "completed",
                "type": "success",
            }
        ],
    }


def _wire_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _FakeWorkspace:
    workspace = _FakeWorkspace(tmp_path)
    monkeypatch.setattr(research_service, "get_workspace", lambda: workspace)
    monkeypatch.setattr(research_organization_service, "get_workspace", lambda: workspace)
    monkeypatch.setattr(research_organization_service, "record_research_scene_event", lambda *a, **k: None)
    monkeypatch.setattr(research_service, "_record_research_config_event", lambda *a, **k: None)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)
    return workspace


def test_task0_get_flow_canvas_reads_organization_graph_not_saved_worker_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /research/flow-canvas SSOT is organization-derived locked graph."""
    workspace = _wire_workspace(tmp_path, monkeypatch)
    workspace.write_research_flow_canvas(_worker_flow_canvas())

    displayed = research_service.get_research_flow_canvas()
    saved = research_service._get_saved_research_flow_canvas(sync_agent_instances=False)

    displayed_ids = {node["id"] for node in displayed["nodes"]}
    saved_ids = {node["id"] for node in saved["nodes"]}

    assert "broad_search" not in displayed_ids
    assert "deep_search" not in displayed_ids
    assert displayed.get("projectBinding", {}).get("locked") is True
    assert displayed.get("organizationPath")
    assert {node.get("type") for node in displayed["nodes"]} == {"agent"}

    # Saved disk graph still holds worker pipeline ids used by execute path.
    assert "broad_search" in saved_ids
    assert "deep_search" in saved_ids
    assert displayed_ids != saved_ids


def test_task0_execute_uses_saved_canvas_node_ids_not_get_display_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /research/flow-canvas/execute SSOT is saved flow_canvas.json."""
    workspace = _wire_workspace(tmp_path, monkeypatch)
    workspace.write_research_flow_canvas(_worker_flow_canvas())

    displayed = research_service.get_research_flow_canvas()
    assert "broad_search" not in {n["id"] for n in displayed["nodes"]}

    executed: list[tuple[str, str]] = []

    def _fake_execute(action_key: str, session_id: str):
        executed.append((action_key, session_id))
        return {"sourceCount": 0}, "completed"

    monkeypatch.setattr(research_service, "_execute_research_flow_action", _fake_execute)

    result = research_service.execute_research_flow_canvas_node("session-task0", node_id="broad_search")
    assert result["execution"]["nodeId"] == "broad_search"
    assert executed and executed[0][0]
    # Execute path must not require organization node ids from GET.
    org_ids = {n["id"] for n in displayed["nodes"]}
    assert result["execution"]["nodeId"] not in org_ids


def test_task0_saved_and_display_are_two_writers_risk_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Document dual writer surface: save persists worker layout; GET re-syncs org."""
    workspace = _wire_workspace(tmp_path, monkeypatch)
    # Seed org by calling get (creates org + team if missing via ensure path).
    first = research_service.get_research_flow_canvas()
    assert first["validation"]["valid"] is True

    workspace.write_research_flow_canvas(_worker_flow_canvas())
    after_write_get = research_service.get_research_flow_canvas()
    after_write_saved = research_service._get_saved_research_flow_canvas(sync_agent_instances=False)

    assert "broad_search" in {n["id"] for n in after_write_saved["nodes"]}
    assert "broad_search" not in {n["id"] for n in after_write_get["nodes"]}

    # Production writers that must be retired after LangGraph cutover.
    assert hasattr(research_service, "execute_research_flow_canvas_node")
    assert hasattr(research_service, "save_research_flow_canvas")
    assert hasattr(research_service, "get_research_flow_canvas")


def test_task0_legacy_flow_canvas_default_is_organization_agents_not_stage_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire_workspace(tmp_path, monkeypatch)
    canvas = research_service.get_research_flow_canvas()
    labels_or_keys = {
        str(node.get("agentKey") or node.get("id") or "")
        for node in canvas["nodes"]
    }
    # Challenge-cup stage pipeline ids must not appear as GET display nodes today.
    for banned in (
        "source_finding",
        "hypothesis_design",
        "controlled_run",
        "knowledge_collection",
        "experiment",
        "iteration",
    ):
        assert banned not in labels_or_keys
    # Organization team binding is present.
    assert canvas["projectBinding"]["teamId"] == "research-team"
    assert canvas["projectBinding"]["source"] == "team"


def test_task0_no_third_flow_execute_writer_in_research_routes() -> None:
    """Router surface: only research.py exposes flow-canvas execute endpoint."""
    route_path = Path(__file__).resolve().parents[1] / "core" / "web" / "routes" / "research.py"
    text = route_path.read_text(encoding="utf-8")
    assert '@router.post("/research/flow-canvas/execute")' in text
    assert "execute_research_flow_canvas_node" in text
    # No LangGraph runtime route yet (Task 2/3 introduce it).
    runtime_route = (
        Path(__file__).resolve().parents[1]
        / "core"
        / "web"
        / "routes"
        / "team_workflows"
        / "research_runtime.py"
    )
    assert not runtime_route.exists()
