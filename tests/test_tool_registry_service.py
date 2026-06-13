import pytest
import json
import time

from core.web.services import agent_directory_service
from core.web.services import tool_registry_service as registry


def test_tool_registry_lists_builtins_as_protected(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    payload = registry.get_tool_registry()

    builtin = next(item for item in payload["tools"] if item["name"] == "grep_search_tool")
    safe_builtin = next(item for item in payload["tools"] if item["name"] == "get_git_status_summary_tool")
    image_tool = next(item for item in payload["tools"] if item["name"] == "image2_generate_tool")
    assert builtin["source"] == "built_in"
    assert builtin["deleteAllowed"] is False
    assert builtin["llmVisible"] is True
    assert builtin["category"] == "workspace_read"
    assert builtin["categoryLabel"] == "Workspace read"
    assert "core" in builtin["bundleIds"]
    assert "research" in builtin["bundleIds"]
    assert "coding" in builtin["bundleIds"]
    assert builtin["capabilityTags"] == ["search", "codebase", "read_only"]
    assert builtin["permissionTier"] == "low"
    assert builtin["testPolicy"]["mode"] == "blocked"
    assert safe_builtin["testPolicy"]["mode"] == "safe_builtin_fixture"
    assert safe_builtin["testPolicy"]["argsPreview"] == {"limit": 3}
    assert safe_builtin["permissionPolicy"]["requiresExplicitAllow"] is False
    assert image_tool["category"] == "media_research"
    assert image_tool["permissionTier"] == "high"
    assert "model_cost" in image_tool["riskTags"]
    edge_tool = next(item for item in payload["tools"] if item["name"] == "research_communication_edge_proposal_tool")
    assert edge_tool["category"] == "agent_collaboration"
    assert edge_tool["permissionTier"] == "high"
    assert edge_tool["permissionPolicy"]["requiresExplicitAllow"] is True
    creation_tool = next(item for item in payload["tools"] if item["name"] == "research_agent_creation_proposal_tool")
    assert creation_tool["category"] == "agent_collaboration"
    assert creation_tool["permissionTier"] == "high"
    assert creation_tool["permissionPolicy"]["requiresExplicitAllow"] is True
    apply_tool = next(item for item in payload["tools"] if item["name"] == "research_proposal_apply_tool")
    assert apply_tool["category"] == "agent_collaboration"
    assert apply_tool["permissionTier"] == "high"
    assert apply_tool["permissionPolicy"]["requiresExplicitAllow"] is True
    child_tool = next(item for item in payload["tools"] if item["name"] == "create_child_session_tool")
    assert child_tool["category"] == "agent_collaboration"
    assert child_tool["permissionTier"] == "high"
    assert "session_state_write" in child_tool["riskTags"]
    list_child_tool = next(item for item in payload["tools"] if item["name"] == "list_child_sessions_tool")
    assert list_child_tool["category"] == "agent_collaboration"
    assert list_child_tool["permissionTier"] == "medium"
    bundles = {item["bundleId"]: item for item in payload["toolBundles"]}
    assert {"core", "research", "coding", "collaboration"}.issubset(bundles)
    assert "grep_search_tool" in bundles["core"]["toolNames"]
    assert "research_knowledge_query_tool" in bundles["research"]["toolNames"]
    assert "unified_knowledge_search_tool" in bundles["research"]["toolNames"]
    assert "research_agent_creation_proposal_tool" in bundles["collaboration"]["toolNames"]
    assert "research_communication_edge_proposal_tool" in bundles["collaboration"]["toolNames"]
    assert "research_proposal_apply_tool" in bundles["collaboration"]["toolNames"]
    assert "create_child_session_tool" in bundles["collaboration"]["toolNames"]
    assert "list_child_sessions_tool" in bundles["collaboration"]["toolNames"]
    assert bundles["research"]["explicitAllowToolCount"] >= 1
    assert bundles["collaboration"]["explicitAllowToolCount"] >= 1
    assert bundles["coding"]["highRiskToolCount"] >= 1
    assert bundles["core"]["label"] == "会话 Agent 基础包"
    assert "conversation_log_inspect_tool" in bundles["core"]["toolNames"]
    log_tool = next(item for item in payload["tools"] if item["name"] == "conversation_log_inspect_tool")
    assert log_tool["category"] == "workspace_read"
    assert log_tool["permissionTier"] == "low"
    assert log_tool["permissionPolicy"]["requiresExplicitAllow"] is False
    assert bundles["research"]["label"] == "科研工具包"


def test_tool_registry_exposes_tool_bundle_membership_without_duplicating_generated_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    created = registry.create_generated_tool(
        {
            "name": "custom_probe_tool",
            "description": "Custom probe tool that is not assigned to a built-in package.",
            "argsSchema": {"type": "object", "properties": {}},
        }
    )
    payload = registry.get_tool_registry()

    read_file = next(item for item in payload["tools"] if item["name"] == "read_file_tool")
    generated = next(item for item in payload["tools"] if item["name"] == created["name"])

    assert set(read_file["bundleIds"]).issuperset({"core", "research", "coding"})
    assert generated["bundleIds"] == []


def test_tool_registry_marks_research_knowledge_tool_as_explicit_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    payload = registry.get_tool_registry()

    tool = next(item for item in payload["tools"] if item["name"] == "research_knowledge_query_tool")
    assert tool["source"] == "built_in"
    assert tool["llmVisible"] is True
    assert tool["permissionPolicy"]["requiresExplicitAllow"] is True
    assert "ToolPolicy.allowedTools" in tool["permissionPolicy"]["reason"]

    rag_tool = next(item for item in payload["tools"] if item["name"] == "knowledge_rag_retrieve_tool")
    assert rag_tool["source"] == "built_in"
    assert rag_tool["llmVisible"] is True
    assert rag_tool["category"] == "memory_context"
    assert rag_tool["permissionPolicy"]["requiresExplicitAllow"] is True
    assert "ToolPolicy.allowedTools" in rag_tool["permissionPolicy"]["reason"]
    unified_tool = next(item for item in payload["tools"] if item["name"] == "unified_knowledge_search_tool")
    assert unified_tool["source"] == "built_in"
    assert unified_tool["llmVisible"] is True
    assert unified_tool["category"] == "memory_context"
    assert "unified_search" in unified_tool["capabilityTags"]
    assert unified_tool["permissionPolicy"]["requiresExplicitAllow"] is True
    assert "ToolPolicy.allowedTools" in unified_tool["permissionPolicy"]["reason"]


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
    assert created["category"] == "custom_generated"
    assert created["permissionTier"] == "generated"
    assert created["riskTags"] == ["custom_tool"]
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


@pytest.mark.parametrize("status", ["failed", "cancelled", "no_result", "submitted", "in_progress", "timed_out"])
def test_builtin_tool_test_marks_structured_failure_status_as_failed(tmp_path, monkeypatch, status):
    monkeypatch.setattr(registry, "GENERATED_TOOLS_PATH", tmp_path / "generated_tools.json")

    monkeypatch.setattr(
        "core.infrastructure.tool_executor.ToolExecutor.execute",
        lambda self, tool_name, tool_args: (json.dumps({"status": status}), None),
    )

    result = registry.test_tool("get_current_goal_tool")

    assert result["status"] == "failed"
    assert json.loads(result["resultPreview"])["status"] == status
    assert result["called"] is True
    assert result["agentCompatibility"]["status"] in {"succeeded", "failed"}


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
    agent = agent_directory_service.create_agent_instance(
        display_name="Blocked Tool Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
    )
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
    agent = agent_directory_service.create_agent_instance(
        display_name="Allowed Tool Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
    )
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


@pytest.mark.slow
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
