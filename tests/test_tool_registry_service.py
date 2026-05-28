import pytest
import time

from core.web.services import agent_directory_service
from core.web.services import tool_registry_service as registry


def test_tool_registry_lists_builtins_as_protected(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    payload = registry.get_tool_registry()

    builtin = next(item for item in payload["tools"] if item["name"] == "grep_search_tool")
    safe_builtin = next(item for item in payload["tools"] if item["name"] == "get_git_status_summary_tool")
    assert builtin["source"] == "built_in"
    assert builtin["deleteAllowed"] is False
    assert builtin["llmVisible"] is True
    assert builtin["testPolicy"]["mode"] == "blocked"
    assert safe_builtin["testPolicy"]["mode"] == "safe_builtin_fixture"
    assert safe_builtin["testPolicy"]["argsPreview"] == {"limit": 3}


def test_tool_registry_exposes_agent_scoped_tool_views(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    payload = registry.get_tool_registry()

    scopes = {scope["id"]: scope for scope in payload["agentScopes"]}
    assert {"main_agent", "subagent_default", "subagent_explorer", "subagent_worker"}.issubset(scopes)
    assert scopes["subagent_explorer"]["isSubagent"] is True
    assert scopes["subagent_explorer"]["mode"] == "readonly"

    grep_tool = next(item for item in payload["tools"] if item["name"] == "grep_search_tool")
    apply_tool = next(item for item in payload["tools"] if item["name"] == "apply_diff_edit_tool")
    spawn_tool_names = {item["name"] for item in payload["tools"]}

    assert "spawn_agent_tool" not in spawn_tool_names
    assert grep_tool["agentScopes"]["subagent_explorer"]["visible"] is True
    assert grep_tool["agentScopes"]["subagent_explorer"]["callable"] is True
    assert apply_tool["agentScopes"]["subagent_explorer"]["visible"] is True
    assert apply_tool["agentScopes"]["subagent_explorer"]["callable"] is False
    assert "只读" in apply_tool["agentScopes"]["subagent_explorer"]["blockReason"] or "read-only" in apply_tool["agentScopes"]["subagent_explorer"]["blockReason"]
    assert scopes["subagent_explorer"]["counts"]["visible"] > 0
    assert scopes["subagent_explorer"]["counts"]["blocked"] > 0


def test_generated_tool_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    created = registry.create_generated_tool(
        {
            "name": "summarize_notes_tool",
            "description": "Summarize a short note payload for later controlled runtime integration.",
            "argsSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                },
                "required": ["text"],
            },
        }
    )
    enabled = registry.set_generated_tool_enabled("summarize_notes_tool", True)
    deleted = registry.delete_generated_tool("summarize_notes_tool")

    assert created["source"] == "generated"
    assert created["validated"] is True
    assert created["enabled"] is False
    assert created["llmVisible"] is False
    assert enabled["enabled"] is True
    assert enabled["runtimeActive"] is False
    assert deleted["deleted"] is True
    assert registry.get_tool_registry()["counts"]["generated"] == 0


def test_generated_tool_cannot_override_builtin(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    with pytest.raises(registry.ToolRegistryConflictError):
        registry.create_generated_tool(
            {
                "name": "grep_search_tool",
                "description": "Attempt to replace the built-in search tool.",
                "argsSchema": {"type": "object", "properties": {}},
            }
        )


def test_delete_tool_blocks_builtin(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    with pytest.raises(registry.ToolRegistryPermissionError):
        registry.delete_tool("grep_search_tool")


def test_generated_tool_rejects_unsafe_schema_keyword(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    with pytest.raises(registry.ToolRegistryError):
        registry.create_generated_tool(
            {
                "name": "unsafe_schema_tool",
                "description": "Contains a schema keyword that is intentionally unsupported.",
                "argsSchema": {
                    "type": "object",
                    "properties": {},
                    "$ref": "#/definitions/hidden",
                },
            }
        )


def test_generated_tool_manifest_test_does_not_execute_code(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")
    registry.create_generated_tool(
        {
            "name": "manifest_probe_tool",
            "description": "Probe the generated tool manifest test path.",
            "argsSchema": {"type": "object", "properties": {}},
            "responseTemplate": "manifest probe response",
        }
    )

    result = registry.test_tool("manifest_probe_tool", args={"value": "x"})

    assert result["status"] == "succeeded"
    assert result["called"] is True
    assert result["source"] == "generated"
    assert result["resultPreview"] == "manifest probe response"
    assert result["argsUsed"] == {"value": "x"}
    assert result["testPolicy"]["mode"] == "generated_manifest_simulation"
    assert result["testPolicy"]["runtimeCall"] is False
    assert result["agentCompatibility"]["status"] == "succeeded"
    assert result["agentCompatibility"]["toolCall"]["name"] == "manifest_probe_tool"
    assert result["agentCompatibility"]["argsParsed"] == {"value": "x"}
    assert result["agentCompatibility"]["messageType"] == "tool"


def test_generated_tool_agent_compatibility_rejects_missing_required_arg(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")
    registry.create_generated_tool(
        {
            "name": "requires_text_tool",
            "description": "Requires text so agent-call compatibility can catch invalid args.",
            "argsSchema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            "responseTemplate": "ok",
        }
    )

    result = registry.test_tool("requires_text_tool", args={})

    assert result["status"] == "failed"
    assert result["called"] is False
    assert result["agentCompatibility"]["status"] == "failed"
    assert result["agentCompatibility"]["callable"] is False
    assert "text" in result["agentCompatibility"]["message"]


def test_builtin_tool_test_blocks_non_allowlisted_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    result = registry.test_tool("grep_search_tool")

    assert result["status"] == "blocked"
    assert result["called"] is False
    assert result["callable"] is False
    assert result["testPolicy"]["mode"] == "blocked"
    assert result["agentCompatibility"]["status"] == "blocked"
    assert result["agentCompatibility"]["callable"] is False


def test_subagent_scope_test_blocks_readonly_mutating_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    result = registry.test_tool("apply_diff_edit_tool", agent_scope="subagent_explorer")

    assert result["status"] == "blocked"
    assert result["called"] is False
    assert result["agentScope"]["id"] == "subagent_explorer"
    assert result["agentCompatibility"]["status"] == "blocked"
    assert result["agentCompatibility"]["callable"] is False
    assert "只读" in result["message"] or "read-only" in result["message"]


def test_builtin_tool_test_runs_allowlisted_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    result = registry.test_tool("get_current_goal_tool")

    assert result["status"] in {"succeeded", "failed"}
    assert result["called"] is True
    assert result["callable"] is True
    assert result["source"] == "built_in"
    assert result["testPolicy"]["mode"] == "safe_builtin_fixture"
    assert result["testPolicy"]["runtimeCall"] is True
    assert result["agentCompatibility"]["status"] in {"succeeded", "failed"}
    assert result["agentCompatibility"]["toolCall"]["name"] == "get_current_goal_tool"


def test_builtin_tool_test_uses_fixed_args_for_allowlisted_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")
    captured = {}

    def fake_execute(self, tool_name, tool_args):
        captured["tool_name"] = tool_name
        captured["tool_args"] = dict(tool_args)
        return ("ok", None)

    monkeypatch.setattr("core.infrastructure.tool_executor.ToolExecutor.execute", fake_execute)

    result = registry.test_tool("get_git_status_summary_tool", args={"limit": 999})

    assert result["status"] == "succeeded"
    assert result["called"] is True
    assert result["argsUsed"] == {"limit": 3}
    assert captured == {
        "tool_name": "get_git_status_summary_tool",
        "tool_args": {"limit": 3},
    }


def test_tool_test_honors_selected_agent_blocked_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "record_runtime_scene_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(registry, "_record_registry_event", lambda *args, **kwargs: None)
    agent = agent_directory_service.create_agent_instance(display_name="Blocked Tool Agent", profile_id="primary")
    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={"blockedTools": ["get_current_goal_tool"]},
    )

    def fail_execute(self, tool_name, tool_args):
        raise AssertionError("blocked Agent ToolPolicy should stop before runtime execution")

    monkeypatch.setattr("core.infrastructure.tool_executor.ToolExecutor.execute", fail_execute)

    result = registry.test_tool("get_current_goal_tool", agent_id=agent["agentId"])

    assert result["status"] == "blocked"
    assert result["called"] is False
    assert result["callable"] is False
    assert result["agent"]["agentId"] == agent["agentId"]
    assert result["agentCompatibility"]["status"] == "blocked"
    assert "ToolPolicy" in result["message"] or "工具策略" in result["message"]


def test_tool_test_runs_safe_builtin_inside_selected_agent_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "record_runtime_scene_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(registry, "_record_registry_event", lambda *args, **kwargs: None)
    agent = agent_directory_service.create_agent_instance(display_name="Allowed Tool Agent", profile_id="primary")
    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={"allowedTools": ["get_current_goal_tool"]},
    )
    captured = {}

    def fake_execute(self, tool_name, tool_args):
        captured["tool_name"] = tool_name
        captured["tool_args"] = dict(tool_args)
        captured["agent_id"] = agent_directory_service.current_agent_runtime().get("agentId")
        return ("ok", None)

    monkeypatch.setattr("core.infrastructure.tool_executor.ToolExecutor.execute", fake_execute)

    result = registry.test_tool("get_current_goal_tool", agent_id=agent["agentId"])

    assert result["status"] == "succeeded"
    assert result["called"] is True
    assert result["agent"]["agentId"] == agent["agentId"]
    assert result["agentCompatibility"]["status"] == "succeeded"
    assert captured == {
        "tool_name": "get_current_goal_tool",
        "tool_args": {},
        "agent_id": agent["agentId"],
    }


def test_builtin_tool_test_times_out_without_waiting_for_slow_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")
    monkeypatch.setattr(registry, "TOOL_TEST_TIMEOUT_SECONDS", 0.05)

    def slow_execute(self, tool_name, tool_args):
        time.sleep(0.25)
        return ("late", None)

    monkeypatch.setattr("core.infrastructure.tool_executor.ToolExecutor.execute", slow_execute)

    result = registry.test_tool("get_current_goal_tool")

    assert result["status"] == "timeout"
    assert result["called"] is False
    assert result["callable"] is False
    assert result["timeout"]["timedOut"] is True
    assert result["timeout"]["durationMs"] < 250
    assert result["agentCompatibility"]["status"] == "timeout"
