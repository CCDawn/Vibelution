from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service
from core.web.services import tool_registry_service as registry
from core.web.services import tool_catalog


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
    cli_agent = next(item for item in payload["tools"] if item["name"] == "cli_agent_run_tool")
    assert cli_agent["category"] == "agent_collaboration"
    assert cli_agent["permissionTier"] == "high"
    assert cli_agent["permissionPolicy"]["requiresExplicitAllow"] is (
        str(cli_agent["name"]).strip() in tool_catalog.explicit_allow_tool_names()
    )
    assert "operations" in cli_agent["bundleIds"]
    assert cli_agent["testPolicy"]["callable"] is False


def test_tools_api_exposes_image2_model_selector(monkeypatch):
    public_config = {
        "llm": {
            "model_library": {
                "image_model": {
                    "provider": {
                        "kind": "openai",
                        "api_key_env": "OPENAI_API_KEY",
                        "base_url": "https://api.openai.com/v1",
                        "compat_mode": "openai",
                        "requires_api_key": True,
                        "context_window": 128000,
                    },
                    "model": "gpt-image-1.5",
                    "label": "Image Model",
                    "api_key_env": "IMAGE_TOOL_KEY",
                    "transport": "chat_completions",
                    "contract": "tool_chat",
                    "tool_calling_mode": "disabled",
                    "streaming": False,
                    "strict_compatibility": False,
                }
            }
        },
        "tools": {"image2": {"default_model_ref": "image_model"}},
    }
    monkeypatch.setattr(registry, "load_public_config", lambda: public_config)

    response = _client().get("/api/tools/image2/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["toolId"] == "image2_generate_tool"
    assert payload["defaultModelRef"] == "image_model"
    assert payload["selectedModel"]["modelRef"] == "image_model"
    assert payload["selectedModel"]["model"] == "gpt-image-1.5"
    assert payload["selectedModel"]["resolvedModel"] == "gpt-image-1.5"
    assert payload["selectedModel"]["modelDiscoveryStatus"] == "skipped"
    assert "apiKey" not in payload["selectedModel"]


def test_tools_api_discovers_relay_image2_request_model(monkeypatch):
    captured = {}
    public_config = {
        "llm": {
            "model_library": {
                "relay_image2": {
                    "provider": {
                        "kind": "relay",
                        "api_key_env": "OPENAI_API_KEY",
                        "base_url": "https://ai-pixel.online",
                        "compat_mode": "openai",
                        "requires_api_key": True,
                        "context_window": 128000,
                    },
                    "model": "image2",
                    "label": "Image2 via relay",
                    "api_key_env": "VIBELUTION_LLM_RELAY_IMAGE2_API_KEY",
                    "transport": "responses",
                    "contract": "tool_chat",
                    "tool_calling_mode": "disabled",
                    "streaming": False,
                    "strict_compatibility": False,
                }
            }
        },
        "tools": {"image2": {"default_model_ref": "relay_image2"}},
    }

    def fake_get(url, headers, timeout):
        captured.update({"url": url, "headers": headers, "timeout": timeout})

        class Response:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {"data": [{"id": "chat-model"}, {"id": "gpt-image-1.5"}, {"id": "gpt-image-2"}]}

        return Response()

    monkeypatch.setattr(registry, "load_public_config", lambda: public_config)
    monkeypatch.setattr(registry, "_read_registry_env_var", lambda name: "image-secret")
    monkeypatch.setitem(__import__("sys").modules, "requests", type("Requests", (), {"get": staticmethod(fake_get)}))

    response = _client().get("/api/tools/image2/models")

    assert response.status_code == 200, response.text
    payload = response.json()
    selected = payload["selectedModel"]
    assert selected["modelRef"] == "relay_image2"
    assert selected["configuredModel"] == "image2"
    assert selected["resolvedModel"] == "gpt-image-1.5"
    assert selected["model"] == "gpt-image-1.5"
    assert selected["discoveredModels"] == ["gpt-image-1.5", "gpt-image-2"]
    assert selected["modelDiscoveryStatus"] == "succeeded"
    assert captured["url"] == "https://ai-pixel.online/v1/models"
    assert captured["headers"]["Authorization"] == "Bearer image-secret"
    assert "apiKey" not in selected


def test_tools_api_updates_image2_default_model(monkeypatch):
    saved = {}
    reloaded = {}
    public_config = {
        "llm": {
            "model_library": {
                "image_model": {
                    "provider": {
                        "kind": "openai",
                        "api_key_env": "OPENAI_API_KEY",
                        "base_url": "https://api.openai.com/v1",
                        "compat_mode": "openai",
                        "requires_api_key": True,
                        "context_window": 128000,
                    },
                    "model": "gpt-image-1.5",
                    "label": "Image Model",
                    "transport": "chat_completions",
                    "contract": "tool_chat",
                    "tool_calling_mode": "disabled",
                    "streaming": False,
                    "strict_compatibility": False,
                }
            },
            "profiles": {
                "primary": {
                    "provider": {
                        "kind": "openai",
                        "api_key_env": "OPENAI_API_KEY",
                        "base_url": "https://api.openai.com/v1",
                        "compat_mode": "openai",
                        "requires_api_key": True,
                        "context_window": 128000,
                    },
                    "model": "gpt-5.5",
                    "transport": "chat_completions",
                    "contract": "tool_chat",
                    "tool_calling_mode": "auto",
                    "strict_compatibility": False,
                }
            },
        },
        "tools": {"image2": {"default_model_ref": ""}},
    }

    def fake_load_public_config():
        return saved.get("config", public_config)

    def fake_save_public_config(updated):
        saved["config"] = updated

    monkeypatch.setattr(registry, "load_public_config", fake_load_public_config)
    monkeypatch.setattr(registry, "save_public_config", fake_save_public_config)
    monkeypatch.setattr(registry, "reload_config", lambda path: reloaded.setdefault("path", path))
    monkeypatch.setattr(registry, "_record_registry_event", lambda *args, **kwargs: None)

    response = _client().put("/api/tools/image2/default-model", json={"modelRef": "image_model"})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["defaultModelRef"] == "image_model"
    assert saved["config"]["tools"]["image2"]["default_model_ref"] == "image_model"
    assert reloaded["path"]


def test_tools_api_rejects_unknown_image2_model(monkeypatch):
    public_config = {"llm": {"model_library": {}}, "tools": {"image2": {"default_model_ref": ""}}}
    monkeypatch.setattr(registry, "load_public_config", lambda: public_config)

    response = _client().put("/api/tools/image2/default-model", json={"modelRef": "missing_model"})

    assert response.status_code == 422
    assert "Unknown image2 model reference" in response.json()["detail"]


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
    cli_agent = next(item for item in payload["tools"] if item["name"] == "cli_agent_run_tool")
    assert cli_agent["agentScopes"]["subagent_explorer"]["visible"] is True
    assert cli_agent["agentScopes"]["subagent_explorer"]["callable"] is False
    assert "只读模式" in cli_agent["agentScopes"]["subagent_explorer"]["blockReason"]


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


def test_tools_api_runs_safe_builtin_test_with_binary_failure_output(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    def fake_execute(self, tool_name, tool_args):
        return ("[错误] test binary payload".encode("utf-8"), None)

    monkeypatch.setattr("core.infrastructure.tool_executor.ToolExecutor.execute", fake_execute)

    response = _client().post("/api/tools/get_git_status_summary_tool/test", json={"args": {}})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["called"] is True
    assert payload["resultPreview"] == "[错误] test binary payload"
    assert payload["agentCompatibility"]["status"] == "failed"


def test_tools_api_tests_safe_builtin_ignores_selected_agent_tool_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "record_runtime_scene_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(registry, "_record_registry_event", lambda *args, **kwargs: None)
    agent = agent_directory_service.create_agent_instance(
        display_name="Route Policy Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
    )
    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={"blockedTools": ["get_current_goal_tool"]},
    )

    def fake_execute(self, tool_name, tool_args):
        return ("ran despite blocked policy", None)

    monkeypatch.setattr("core.infrastructure.tool_executor.ToolExecutor.execute", fake_execute)

    response = _client().post(
        "/api/tools/get_current_goal_tool/test",
        json={"args": {}, "agentId": agent["agentId"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert payload["called"] is True
    assert payload["agent"]["agentId"] == agent["agentId"]
    assert payload["agentCompatibility"]["status"] == "succeeded"
    assert payload["resultPreview"] == "ran despite blocked policy"


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


def test_tools_api_generated_tool_test_flags_failure_template(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")
    client = _client()
    client.post(
        "/api/tools/generated",
        json={
            "name": "route_manifest_fail_tool",
            "description": "Route generated manifest failure probe.",
            "argsSchema": {"type": "object", "properties": {}},
            "responseTemplate": "{\"status\": \"failed\"}",
        },
    )

    response = client.post("/api/tools/route_manifest_fail_tool/test", json={"args": {}})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["callable"] is False
    assert payload["agentCompatibility"]["status"] == "failed"
    assert payload["agentCompatibility"]["callable"] is False
    assert payload["resultPreview"] == '{"status": "failed"}'


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
