from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import tool_registry_service as registry


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def test_tools_api_lists_builtin_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    response = _client().get("/api/tools")

    assert response.status_code == 200
    payload = response.json()
    assert payload["counts"]["builtIn"] > 0
    builtin = next(item for item in payload["tools"] if item["name"] == "grep_search_tool")
    assert builtin["deleteAllowed"] is False


def test_tools_api_lists_agent_scopes(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    response = _client().get("/api/tools")

    assert response.status_code == 200
    payload = response.json()
    scopes = {scope["id"]: scope for scope in payload["agentScopes"]}
    assert "main_agent" in scopes
    assert "subagent_explorer" in scopes
    assert scopes["subagent_explorer"]["isSubagent"] is True
    apply_tool = next(item for item in payload["tools"] if item["name"] == "apply_diff_edit_tool")
    assert apply_tool["agentScopes"]["subagent_explorer"]["visible"] is True
    assert apply_tool["agentScopes"]["subagent_explorer"]["callable"] is False


def test_tools_api_blocks_builtin_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    response = _client().delete("/api/tools/grep_search_tool")

    assert response.status_code == 409
    assert "Built-in" in response.json()["detail"]


def test_tools_api_generated_tool_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")
    client = _client()

    create_response = client.post(
        "/api/tools/generated",
        json={
            "name": "brief_digest_tool",
            "description": "Create a controlled digest from a short text payload.",
            "argsSchema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    )
    enable_response = client.put("/api/tools/generated/brief_digest_tool/enabled", json={"enabled": True})
    delete_response = client.delete("/api/tools/brief_digest_tool")

    assert create_response.status_code == 200, create_response.text
    assert create_response.json()["validated"] is True
    assert enable_response.status_code == 200, enable_response.text
    assert enable_response.json()["enabled"] is True
    assert delete_response.status_code == 200, delete_response.text
    assert delete_response.json()["deleted"] is True


def test_tools_api_blocks_unsafe_builtin_test(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    response = _client().post("/api/tools/grep_search_tool/test", json={"args": {}})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["called"] is False
    assert payload["testPolicy"]["mode"] == "blocked"


def test_tools_api_blocks_readonly_subagent_mutating_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    response = _client().post("/api/tools/apply_diff_edit_tool/test", json={"args": {}, "agentScope": "subagent_worker"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["called"] is False
    assert payload["agentScope"]["id"] == "subagent_worker"
    assert payload["agentCompatibility"]["callable"] is False


def test_tools_api_runs_safe_builtin_test_with_fixed_args(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")
    captured = {}

    def fake_execute(self, tool_name, tool_args):
        captured["tool_name"] = tool_name
        captured["tool_args"] = dict(tool_args)
        return ("ok", None)

    monkeypatch.setattr("core.infrastructure.tool_executor.ToolExecutor.execute", fake_execute)

    response = _client().post("/api/tools/get_recent_changes_tool/test", json={"args": {"limit": 999}})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert payload["called"] is True
    assert payload["testPolicy"]["mode"] == "safe_builtin_fixture"
    assert payload["argsUsed"] == {"limit": 3}
    assert captured == {
        "tool_name": "get_recent_changes_tool",
        "tool_args": {"limit": 3},
    }


def test_tools_api_generated_tool_test(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")
    client = _client()
    client.post(
        "/api/tools/generated",
        json={
            "name": "route_probe_tool",
            "description": "Probe generated tool testing through the API.",
            "argsSchema": {"type": "object", "properties": {}},
            "responseTemplate": "route probe response",
        },
    )

    response = client.post("/api/tools/route_probe_tool/test", json={"args": {"sample": True}})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert payload["called"] is True
    assert payload["resultPreview"] == "route probe response"
    assert payload["testPolicy"]["mode"] == "generated_manifest_simulation"
    assert payload["agentCompatibility"]["status"] == "succeeded"
    assert payload["agentCompatibility"]["toolCall"]["name"] == "route_probe_tool"
    assert payload["timeout"]["timedOut"] is False


def test_tools_api_generated_tool_test_reports_agent_arg_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")
    client = _client()
    client.post(
        "/api/tools/generated",
        json={
            "name": "route_requires_text_tool",
            "description": "Require text so the route surfaces agent compatibility failures.",
            "argsSchema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            "responseTemplate": "ok",
        },
    )

    response = client.post("/api/tools/route_requires_text_tool/test", json={"args": {}})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["agentCompatibility"]["status"] == "failed"
    assert payload["agentCompatibility"]["callable"] is False
    assert "text" in payload["agentCompatibility"]["message"]
