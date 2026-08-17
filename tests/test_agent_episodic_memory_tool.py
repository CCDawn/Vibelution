import json

from core.web.services import agent_directory_service
from core.orchestration import context_engine
from tools import episodic_memory_tools
from tools.episodic_memory_tools import (
    append_personal_memory_tool,
    supersede_personal_memory_tool,
)


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
        append_personal_memory_tool(
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
    result = json.loads(append_personal_memory_tool(text="nope"))
    assert result["ok"] is False
    assert result["error"] == "agent_runtime_missing"


def test_append_tool_has_no_target_agent_parameter():
    import inspect

    signature = inspect.signature(append_personal_memory_tool)
    assert "agent_id" not in signature.parameters
    assert "target_agent" not in signature.parameters


def test_default_session_policy_includes_personal_memory_tools():
    assert agent_directory_service.PERSONAL_MEMORY_APPEND_TOOL_NAME == "append_personal_memory_tool"
    assert agent_directory_service.PERSONAL_MEMORY_SUPERSEDE_TOOL_NAME == "supersede_personal_memory_tool"
    for name in (
        agent_directory_service.PERSONAL_MEMORY_APPEND_TOOL_NAME,
        agent_directory_service.PERSONAL_MEMORY_SUPERSEDE_TOOL_NAME,
    ):
        assert name in agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS
        assert name not in agent_directory_service.DEFAULT_SESSION_AGENT_PREFERRED_TOOLS
        assert name not in agent_directory_service.SESSION_PROTOCOL_ALLOWED_TOOLS
    assert "append_episodic_memory_tool" not in agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS
    assert "supersede_episodic_memory_tool" not in agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS


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
    assert agent_directory_service.PERSONAL_MEMORY_APPEND_TOOL_NAME in projected["allowedTools"]
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
    assert agent_directory_service.PERSONAL_MEMORY_APPEND_TOOL_NAME not in projected["allowedTools"]


def test_key_tools_catalog_includes_personal_memory_tools():
    from core.web.services import tool_catalog
    from tools.Key_Tools import create_key_tools

    names = {getattr(item, "name", "") for item in create_key_tools()}
    for name in ("append_personal_memory_tool", "supersede_personal_memory_tool"):
        assert name in names
        assert name in tool_catalog.TOOL_CATALOG
        metadata = tool_catalog.metadata_for_tool(name)
        assert metadata["category"] == "memory_context"
        assert metadata["permissionTier"] == "medium"
        assert "memory_write" in metadata["riskTags"]
    assert "append_episodic_memory_tool" not in names
    assert "supersede_episodic_memory_tool" not in names
    assert "append_episodic_memory_tool" in tool_catalog.TOOL_CATALOG
    assert "supersede_episodic_memory_tool" in tool_catalog.TOOL_CATALOG
    assert episodic_memory_tools.APPEND_PERSONAL_MEMORY_TOOL_NAME == "append_personal_memory_tool"
    assert episodic_memory_tools.SUPERSEDE_PERSONAL_MEMORY_TOOL_NAME == "supersede_personal_memory_tool"


def test_personal_memory_tool_descriptions_prefer_dumped_context():
    from core.web.services.tool_registry_service import MAX_DESCRIPTION_CHARS
    from tools.Key_Tools import create_key_tools

    tools = {getattr(item, "name", ""): item for item in create_key_tools()}
    append_doc = str(tools["append_personal_memory_tool"].description or "")
    supersede_doc = str(tools["supersede_personal_memory_tool"].description or "")

    assert "个人记忆" in append_doc
    assert "个人记忆" in supersede_doc
    assert "世代交接" in append_doc
    assert "只写自己的 episodic_events.jsonl" not in append_doc
    assert "glob" in append_doc
    assert "文件搜索" in supersede_doc
    assert len(append_doc) <= MAX_DESCRIPTION_CHARS
    assert len(supersede_doc) <= MAX_DESCRIPTION_CHARS
    assert "个人记忆" in (append_personal_memory_tool.__doc__ or "")
    assert "个人记忆" in (supersede_personal_memory_tool.__doc__ or "")


def test_supersede_tool_replaces_current_episode(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Episode Editor")
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": agent["agentId"], "sessionId": "session-edit"},
    )
    first = json.loads(append_personal_memory_tool(text="Prefer quiet mornings.", kind="preference"))
    result = json.loads(
        supersede_personal_memory_tool(
            episode_id=first["episodeId"],
            successor_text="Prefer focused afternoons.",
            kind="preference",
        )
    )
    assert result["ok"] is True
    assert result["status"] == "superseded"
    current = agent_directory_service.list_current_episodic_events(agent["agentId"])
    assert [item["episodeId"] for item in current] == [result["successorEpisodeId"]]
    assert current[0]["text"] == "Prefer focused afternoons."


def test_new_session_context_includes_current_personal_episodes(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Episode Recall")
    token = "ACCEPT-RECALL-keep-across-sessions"
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": agent["agentId"], "sessionId": "session-write"},
    )
    written = json.loads(append_personal_memory_tool(text=f"User prefers {token}", kind="preference"))
    packet = context_engine.build_agent_context(
        agent["agentId"],
        session_id="session-read",
        run_id="turn-read",
    )
    assert written["episodeId"] in packet.dynamic_context_block
    assert token in packet.dynamic_context_block
    assert token not in packet.static_context_block
    assert packet.episodic_events[0]["episodeId"] == written["episodeId"]


def test_superseded_episode_is_not_dumped_into_new_session_context(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Episode Drop")
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": agent["agentId"], "sessionId": "session-drop"},
    )
    first = json.loads(append_personal_memory_tool(text="Old stale preference.", kind="preference"))
    json.loads(supersede_personal_memory_tool(episode_id=first["episodeId"]))
    packet = context_engine.build_agent_context(
        agent["agentId"],
        session_id="session-after-drop",
        run_id="turn-after-drop",
    )
    assert first["episodeId"] not in packet.dynamic_context_block
    assert "Old stale preference." not in packet.context_block
    assert "## 个人记忆" in packet.dynamic_context_block
    assert packet.dynamic_context_block.splitlines()[1].strip() == "无"


def test_narrow_handoff_snapshot_projects_supersede_tool():
    agent = {
        "agentId": "agent-narrow",
        "toolPolicyId": "tool-agent-narrow",
        "primaryMode": "chat",
    }
    policy = {
        "policyId": "tool-agent-narrow",
        "allowedTools": list(agent_directory_service._NARROW_HANDOFF_SESSION_AGENT_ALLOWED_TOOLS),
        "preferredTools": list(agent_directory_service.DEFAULT_SESSION_AGENT_PREFERRED_TOOLS),
    }
    projected = agent_directory_service._with_session_terminal_protocol_defaults(agent, policy)
    assert agent_directory_service.PERSONAL_MEMORY_SUPERSEDE_TOOL_NAME in projected["allowedTools"]
    assert projected["allowedTools"] == list(agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS)


def test_episodic_named_snapshot_projects_renamed_personal_memory_tools():
    agent = {
        "agentId": "agent-episodic-named",
        "toolPolicyId": "tool-agent-episodic-named",
        "primaryMode": "chat",
    }
    policy = {
        "policyId": "tool-agent-episodic-named",
        "allowedTools": list(agent_directory_service._EPISODIC_NAMED_SESSION_AGENT_ALLOWED_TOOLS),
        "preferredTools": list(agent_directory_service.DEFAULT_SESSION_AGENT_PREFERRED_TOOLS),
    }
    projected = agent_directory_service._with_session_terminal_protocol_defaults(agent, policy)
    assert projected["allowedTools"] == list(agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS)
    assert "append_episodic_memory_tool" not in projected["allowedTools"]
    assert "append_personal_memory_tool" in projected["allowedTools"]


def test_custom_policy_rewrites_legacy_personal_memory_tool_names():
    agent = {
        "agentId": "agent-custom-legacy-memory",
        "toolPolicyId": "tool-agent-custom-legacy-memory",
        "primaryMode": "chat",
    }
    policy = {
        "policyId": "tool-agent-custom-legacy-memory",
        "allowedTools": ["grep_search_tool", "append_episodic_memory_tool"],
        "preferredTools": ["append_episodic_memory_tool"],
    }
    projected = agent_directory_service._with_session_terminal_protocol_defaults(agent, policy)
    assert projected["allowedTools"] == ["grep_search_tool", "append_personal_memory_tool"]
    assert projected["preferredTools"] == ["append_personal_memory_tool"]
