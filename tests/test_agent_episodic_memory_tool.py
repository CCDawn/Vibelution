import json

from core.web.services import agent_directory_service
from tools import episodic_memory_tools
from tools.episodic_memory_tools import append_episodic_memory_tool


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)


def test_append_tool_writes_current_agent_episode(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Episode Writer")
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": agent["agentId"], "sessionId": "session-live"},
    )

    result = json.loads(
        append_episodic_memory_tool(
            text="Prefer focused pytest.",
            kind="preference",
            refs_json='[{"type":"path","id":"tests/test_agent_episodic_memory_tool.py"}]',
        )
    )

    assert result["ok"] is True
    assert result["status"] == "appended"
    assert result["agentId"] == agent["agentId"]
    current = agent_directory_service.list_current_episodic_events(agent["agentId"])
    assert current[0]["episodeId"] == result["episodeId"]
    assert {"type": "session", "id": "session-live"} in current[0]["refs"]
    assert {"type": "path", "id": "tests/test_agent_episodic_memory_tool.py"} in current[0]["refs"]
    policy = agent_directory_service.resolve_memory_policy_for_agent(agent["agentId"])
    summaries = agent_directory_service._resolve_project_path(str(policy.get("summariesPath") or ""))
    assert not summaries.exists()


def test_append_tool_requires_bound_runtime(monkeypatch):
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {})
    result = json.loads(append_episodic_memory_tool(text="nope"))
    assert result["ok"] is False
    assert result["error"] == "agent_runtime_missing"


def test_append_tool_has_no_target_agent_parameter():
    import inspect

    signature = inspect.signature(append_episodic_memory_tool)
    assert "agent_id" not in signature.parameters
    assert "target_agent" not in signature.parameters


def test_default_session_policy_includes_personal_episode_tool():
    assert agent_directory_service.PERSONAL_EPISODE_TOOL_NAME == "append_episodic_memory_tool"
    assert agent_directory_service.PERSONAL_EPISODE_TOOL_NAME in agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS
    assert agent_directory_service.PERSONAL_EPISODE_TOOL_NAME not in agent_directory_service.DEFAULT_SESSION_AGENT_PREFERRED_TOOLS
    assert agent_directory_service.PERSONAL_EPISODE_TOOL_NAME not in agent_directory_service.SESSION_PROTOCOL_ALLOWED_TOOLS


def test_generation_handoff_tools_stay_off_default_session_policy():
    for name in agent_directory_service.GENERATION_HANDOFF_MEMORY_TOOLS:
        assert name not in agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS
        assert name not in agent_directory_service.DEFAULT_SESSION_AGENT_PREFERRED_TOOLS
        assert name in agent_directory_service.SELF_EVOLUTION_EXECUTABLE_AGENT_ALLOWED_TOOLS
    assert "get_core_context_tool" in agent_directory_service.SELF_EVOLUTION_EXECUTABLE_AGENT_PREFERRED_TOOLS
    assert "commit_compressed_memory_tool" not in agent_directory_service.SELF_EVOLUTION_EXECUTABLE_AGENT_PREFERRED_TOOLS


def test_untouched_protocol_snapshot_projects_episode_tool():
    agent = {
        "agentId": "agent-session",
        "toolPolicyId": "tool-agent-session",
        "primaryMode": "chat",
    }
    policy = {
        "policyId": "tool-agent-session",
        "allowedTools": list(agent_directory_service.SESSION_PROTOCOL_ALLOWED_TOOLS),
        "preferredTools": list(agent_directory_service.SESSION_PROTOCOL_PREFERRED_TOOLS),
    }
    projected = agent_directory_service._with_session_terminal_protocol_defaults(agent, policy)
    assert agent_directory_service.PERSONAL_EPISODE_TOOL_NAME in projected["allowedTools"]
    assert projected["allowedTools"] == list(agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS)
    assert projected["preferredTools"] == list(agent_directory_service.DEFAULT_SESSION_AGENT_PREFERRED_TOOLS)
    for name in agent_directory_service.GENERATION_HANDOFF_MEMORY_TOOLS:
        assert name not in projected["allowedTools"]
        assert name not in projected["preferredTools"]


def test_episode_era_snapshot_drops_generation_handoff_tools():
    agent = {
        "agentId": "agent-episode-era",
        "toolPolicyId": "tool-agent-episode-era",
        "primaryMode": "chat",
    }
    policy = {
        "policyId": "tool-agent-episode-era",
        "allowedTools": list(agent_directory_service._EPISODE_ERA_SESSION_AGENT_ALLOWED_TOOLS),
        "preferredTools": list(agent_directory_service.SESSION_PROTOCOL_PREFERRED_TOOLS),
    }
    projected = agent_directory_service._with_session_terminal_protocol_defaults(agent, policy)
    assert projected["allowedTools"] == list(agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS)
    assert "get_core_context_tool" not in projected["allowedTools"]
    assert "get_current_goal_tool" not in projected["allowedTools"]


def test_custom_session_policy_keeps_explicit_generation_handoff_grant():
    agent = {
        "agentId": "agent-custom-handoff",
        "toolPolicyId": "tool-agent-custom-handoff",
        "primaryMode": "chat",
    }
    policy = {
        "policyId": "tool-agent-custom-handoff",
        "allowedTools": ["grep_search_tool", "get_core_context_tool"],
        "preferredTools": ["get_core_context_tool"],
    }
    projected = agent_directory_service._with_session_terminal_protocol_defaults(agent, policy)
    assert projected["allowedTools"] == ["grep_search_tool", "get_core_context_tool"]
    assert projected["preferredTools"] == ["get_core_context_tool"]


def test_custom_session_policy_is_not_widened():
    agent = {
        "agentId": "agent-custom",
        "toolPolicyId": "tool-agent-custom",
        "primaryMode": "chat",
    }
    policy = {
        "policyId": "tool-agent-custom",
        "allowedTools": ["grep_search_tool", "cli_tool"],
        "preferredTools": ["cli_tool"],
    }
    projected = agent_directory_service._with_session_terminal_protocol_defaults(agent, policy)
    assert projected["allowedTools"] == ["grep_search_tool", "cli_tool"]
    assert agent_directory_service.PERSONAL_EPISODE_TOOL_NAME not in projected["allowedTools"]


def test_key_tools_catalog_includes_append_episodic_memory_tool():
    from core.web.services import tool_catalog
    from tools.Key_Tools import create_key_tools

    names = {getattr(item, "name", "") for item in create_key_tools()}
    assert "append_episodic_memory_tool" in names
    assert episodic_memory_tools.APPEND_EPISODIC_MEMORY_TOOL_NAME == "append_episodic_memory_tool"
    assert "append_episodic_memory_tool" in tool_catalog.TOOL_CATALOG
    metadata = tool_catalog.metadata_for_tool("append_episodic_memory_tool")
    assert metadata["category"] == "memory_context"
    assert metadata["permissionTier"] == "medium"
    assert "memory_write" in metadata["riskTags"]
