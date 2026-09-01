import json

import pytest

from core.orchestration import context_engine
from core.runtime_manager import work_run_store
from core.web.services import agent_directory_service, prompt_template_service, research_organization_service


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        agent_directory_service,
        "_configured_model_library_ids",
        lambda: {"model-primary", "model-research-broad"},
    )
    with context_engine._RESEARCH_ORG_CONTEXT_CACHE_LOCK:
        context_engine._RESEARCH_ORG_CONTEXT_CACHE.clear()
    with context_engine._PROJECT_AGENT_REGISTRY_CACHE_LOCK:
        context_engine._PROJECT_AGENT_REGISTRY_CACHE.clear()
    with context_engine._ACTIVE_AGENT_DIRECTORY_CACHE_LOCK:
        context_engine._ACTIVE_AGENT_DIRECTORY_CACHE.clear()
    context_engine.reset_session_context_freeze_cache()


class _FakeResearchWorkspace:
    def __init__(self, root):
        self.root = root / "workspace"

    def get_research_organization_path(self):
        return self.root / "research" / "organization_graph.json"

    def read_research_organization(self):
        path = self.get_research_organization_path()
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def write_research_organization(self, data):
        path = self.get_research_organization_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return True


def _use_tmp_research_org_workspace(tmp_path, monkeypatch):
    workspace = _FakeResearchWorkspace(tmp_path)
    monkeypatch.setattr(research_organization_service, "get_workspace", lambda: workspace)
    monkeypatch.setattr(research_organization_service, "record_research_scene_event", lambda *args, **kwargs: None)
    return workspace


def test_build_chat_agent_context_skips_research_org_context(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(
        context_engine,
        "_build_research_organization_context_block",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("chat agents should not build research org context")),
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="普通会话 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-chat",
    )
    agent_directory_service.write_group_context_event(
        agent["agentId"],
        {
            "sourceRoomId": "room-1",
            "sourceRoundId": "round-1",
            "topic": "统一配置",
            "summary": "模型与提示词分层",
            "ownMessage": "我负责广搜。",
            "peerHighlights": ["评审 Agent 发现兼容层风险"],
        },
    )
    agent_directory_service.write_agent_inbox_message(
        agent["agentId"],
        content="请检查 ModeBinding 是否还在读旧字段。",
        summary="检查 ModeBinding 旧字段",
        created_by="test",
    )

    packet = context_engine.build_agent_context(agent["agentId"], session_id="session-chat", run_id="turn-1")

    assert packet.agent_id == agent["agentId"]
    assert packet.agent_code == agent["agentCode"]
    assert packet.dialogue_model_id == "model-primary"
    assert packet.prompt_template_id == "prompt-chat-default"
    assert "## Conversation Agent Common Prompt" in packet.static_context_block
    assert "## Conversation Agent Role Prompt" in packet.static_context_block
    assert "assistant commentary -> tool call/result" in packet.static_context_block
    assert packet.role_key == ""
    assert packet.workspace_path == agent["workspacePath"]
    assert packet.memory_policy["privateMemoryRoot"].endswith("/memory")
    assert packet.tool_policy["policyId"]
    assert len(packet.group_context_events) == 1
    assert len(packet.inbox_messages) == 1
    assert "Agent Runtime Context" in packet.context_block
    assert "检查 ModeBinding 旧字段" in packet.context_block
    assert "Agent Runtime Context" in packet.static_context_block
    assert "检查 ModeBinding 旧字段" not in packet.static_context_block
    assert "检查 ModeBinding 旧字段" in packet.dynamic_context_block
    segments_by_key = {segment["key"]: segment for segment in packet.context_segments}
    assert segments_by_key["agent_runtime"]["placement"] == "cache_prefix"
    assert segments_by_key["agent_messages"]["placement"] == "volatile_turn"
    assert segments_by_key["agent_messages"]["chars"] > 0
    assert segments_by_key["agent_messages"]["hash"]
    assert "Research Organization Context" not in packet.context_block
    assert "Project Agent Territory Registry" not in packet.context_block
    assert "project_agent_registry" not in segments_by_key
    assert packet.timings["projectAgentRegistryContextSkipped"] is True
    assert packet.timings["totalDurationMs"] >= 0
    assert "runtimeContextBlockMs" in packet.timings
    assert "promptTemplateContextMs" in packet.timings
    assert packet.timings["researchOrgContextSkipped"] is True


def test_build_agent_context_stops_before_later_stages(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="可中断上下文 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-stop",
    )
    stages: list[str] = []
    original_episodic = agent_directory_service.list_current_episodic_events

    def episodic(*args, **kwargs):
        stages.append("episodic")
        return original_episodic(*args, **kwargs)

    monkeypatch.setattr(agent_directory_service, "list_current_episodic_events", episodic)

    def interrupt_checker():
        return "operator requested stop" if "episodic" in stages else ""

    with pytest.raises(context_engine.AgentContextInterrupted) as exc_info:
        context_engine.build_agent_context(
            agent["agentId"],
            session_id="session-stop",
            run_id="turn-1",
            agent_snapshot=agent,
            interrupt_checker=interrupt_checker,
        )

    assert stages == ["episodic"]
    assert exc_info.value.stage == "prepare_agent_context.group_context_events"
    assert exc_info.value.reason == "operator requested stop"


def test_build_agent_context_reuses_supplied_agent_snapshot(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="静态快照 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-snapshot",
    )
    original_get_agent = agent_directory_service.get_agent

    def reject_duplicate_agent_lookup(agent_id, *, include_archived=False):
        if agent_id == agent["agentId"] and not include_archived:
            raise AssertionError("supplied Agent snapshot should avoid duplicate get_agent")
        return original_get_agent(agent_id, include_archived=include_archived)

    monkeypatch.setattr(agent_directory_service, "get_agent", reject_duplicate_agent_lookup)

    packet = context_engine.build_agent_context(
        agent["agentId"],
        session_id="session-snapshot",
        run_id="turn-1",
        agent_snapshot=agent,
    )

    assert packet.agent_id == agent["agentId"]
    assert packet.display_name == agent["displayName"]
    assert packet.timings["agentLookupMs"] >= 0


def test_build_agent_context_skips_prompt_template_when_session_snapshot_owns_it(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="冻结提示词 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-snapshot",
    )

    monkeypatch.setattr(
        context_engine,
        "_build_prompt_template_context_block",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("validated session snapshot should own the prompt segment")
        ),
    )

    packet = context_engine.build_agent_context(
        agent["agentId"],
        session_id="session-snapshot",
        run_id="turn-1",
        agent_snapshot=agent,
        include_prompt_template_context=False,
    )

    assert packet.prompt_template_id == agent["promptTemplateId"]
    assert packet.timings["promptTemplateContextMs"] == 0
    assert packet.timings["promptTemplateContextSkipped"] is True
    assert all(segment["key"] != "prompt_template" for segment in packet.context_segments)


def test_default_chat_prompt_template_is_not_an_empty_fallback(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        context_engine,
        "_record_context_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)),
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="普通会话 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-chat",
    )

    packet = context_engine.build_agent_context(agent["agentId"], session_id="session-chat", run_id="turn-1")

    assert packet.prompt_template_id == "prompt-chat-default"
    assert "## Conversation Agent Common Prompt" in packet.static_context_block
    assert "## Conversation Agent Role Prompt" in packet.static_context_block
    assert not any(args[0] == "agent_runtime.prompt_template_empty_fallback" for args, kwargs in recorded_events)
    assert not any(
        args[0] == "agent_runtime.prompt_template_missing" and kwargs["level"] == "warning"
        for args, kwargs in recorded_events
    )


def test_build_research_agent_context_still_loads_research_org_context(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="研究组织 Agent",
        llm_bindings={"dialogue": {"modelId": "model-research-broad"}},
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
        direct_session_id="session-research",
    )
    calls: list[str] = []
    monkeypatch.setattr(
        context_engine,
        "_build_research_organization_context_block",
        lambda agent_id, **kwargs: calls.append(agent_id)
        or {
            "contextBlock": "## Research Organization Context\nMembers: none",
            "cacheHit": False,
            "cacheAgeMs": 0,
        },
    )

    packet = context_engine.build_agent_context(agent["agentId"], session_id="session-research", run_id="turn-1")

    assert calls == [agent["agentId"]]
    assert "Research Organization Context" in packet.context_block
    assert "## Conversation Agent Common Prompt" not in packet.context_block
    assert packet.timings["researchOrgContextMs"] >= 0
    assert "researchOrgContextSkipped" not in packet.timings


def test_build_research_agent_context_reuses_short_lived_research_org_snapshot(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    workspace = _use_tmp_research_org_workspace(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="研究缓存 Agent",
        llm_bindings={"dialogue": {"modelId": "model-research-broad"}},
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
        direct_session_id="session-research-cache",
    )
    organization = research_organization_service.get_research_organization()
    organization["agents"].append(
        {
            "nodeId": agent["agentId"],
            "agentId": agent["agentId"],
            "role": "research_specialist",
            "employeeRank": "member",
            "status": "active",
        }
    )
    workspace.write_research_organization(organization)
    calls: list[str] = []
    original_builder = research_organization_service.build_research_organization_context_block

    def counting_builder(agent_id, **kwargs):
        calls.append(agent_id)
        return original_builder(agent_id, **kwargs)

    monkeypatch.setattr(research_organization_service, "build_research_organization_context_block", counting_builder)

    first = context_engine.build_agent_context(agent["agentId"], session_id="session-research-cache", run_id="turn-1")
    second = context_engine.build_agent_context(agent["agentId"], session_id="session-research-cache", run_id="turn-2")

    assert calls == [agent["agentId"]]
    assert "Research Organization Context" in first.context_block
    assert "Research Organization Context" in second.context_block
    assert first.timings["researchOrgContextCacheHit"] is False
    assert second.timings["researchOrgContextCacheHit"] is True
    assert second.timings["researchOrgContextCacheAgeMs"] >= 0


def test_build_research_agent_context_cache_invalidates_when_research_org_changes(tmp_path, monkeypatch):
    """会话内冻结花名册字节（缓存前缀稳定），新 session 才重建出新快照。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    workspace = _use_tmp_research_org_workspace(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="研究缓存失效 Agent",
        llm_bindings={"dialogue": {"modelId": "model-research-broad"}},
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
        direct_session_id="session-research-cache-invalidate",
    )
    organization = research_organization_service.get_research_organization()
    organization["agents"].append(
        {
            "nodeId": agent["agentId"],
            "agentId": agent["agentId"],
            "role": "research_specialist",
            "employeeRank": "member",
            "status": "active",
        }
    )
    workspace.write_research_organization(organization)
    calls: list[str] = []
    original_builder = research_organization_service.build_research_organization_context_block

    def counting_builder(agent_id, **kwargs):
        calls.append(agent_id)
        return original_builder(agent_id, **kwargs)

    monkeypatch.setattr(research_organization_service, "build_research_organization_context_block", counting_builder)

    first = context_engine.build_agent_context(
        agent["agentId"],
        session_id="session-research-cache-invalidate",
        run_id="turn-1",
    )
    organization["updatedAt"] = "2030-01-01T00:00:00Z"
    organization["auditEvents"] = [
        *(organization.get("auditEvents") or []),
        {"eventType": "test_cache_invalidation", "allowed": True},
    ]
    organization["agents"].append(
        {
            "nodeId": "agent-newcomer-invalidate",
            "agentId": "agent-newcomer-invalidate",
            "role": "research_specialist",
            "employeeRank": "member",
            "status": "active",
        }
    )
    workspace.write_research_organization(organization)
    second = context_engine.build_agent_context(
        agent["agentId"],
        session_id="session-research-cache-invalidate",
        run_id="turn-2",
    )
    refreshed = context_engine.build_agent_context(
        agent["agentId"],
        session_id="session-research-cache-invalidate-next",
        run_id="turn-1",
    )

    # 同一 session：花名册字节被会话级冻结，底层不重算。
    assert calls == [agent["agentId"], agent["agentId"]]
    assert first.timings["researchOrgContextCacheHit"] is False
    assert second.timings["researchOrgContextCacheHit"] is True
    assert second.timings["researchOrgContextFrozen"] is True
    assert first.static_context_block == second.static_context_block
    # 新 session：拿到的才是组织变更后的新快照。
    assert refreshed.static_context_block != first.static_context_block
    assert refreshed.timings["researchOrgContextFrozen"] is not True


def test_build_agent_context_leaves_agents_md_to_prompt_manager_or_session_snapshot(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    (tmp_path / "AGENTS.md").write_text(
        "\n".join(
            [
                "# Test Rules",
                "",
                "## Session-Level Agent Memory Coordination",
                "",
                "- Session-level Agents may process project work in parallel.",
                "- Project memory is a single-writer shared record.",
                "- AGENTS.md is the default contract for this behavior.",
                "",
                "## Session Agent Territory And Handoff",
                "",
                "- Every session-level Agent must treat its agentId and sessionId as its runtime identity.",
                "- If the user asks outside scope, recommend a matching handoff target.",
                "",
                "## Unrelated Section",
                "",
                "- This line must not enter the runtime context.",
            ]
        ),
        encoding="utf-8",
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="并行处理 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-parallel-memory",
    )
    events = []
    monkeypatch.setattr(
        context_engine,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    packet = context_engine.build_agent_context(agent["agentId"], session_id="session-parallel-memory", run_id="turn-1")

    assert "Project Operating Rules" not in packet.context_block
    assert "AGENTS.md is the default contract for this behavior." not in packet.context_block
    segments_by_key = {segment["key"]: segment for segment in packet.context_segments}
    assert "project_rules" not in segments_by_key
    assert packet.timings["projectRulesContextMs"] == 0
    assert packet.timings["projectRulesContextSkipped"] is True
    resolved = next(
        item for item in events
        if item[0][:3] == ("agent_context", "context_engine", "agent_runtime.resolved")
    )
    assert resolved[1]["fields"]["projectRulesContextIncluded"] is False
    assert resolved[1]["fields"]["projectRulesContextOwner"] == "prompt_manager_or_session_snapshot"


def test_build_agent_context_reuses_registry_file_cache_without_project_rules_copy(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    (tmp_path / "AGENTS.md").write_text(
        "\n".join(
            [
                "## Session-Level Agent Memory Coordination",
                "",
                "- Project memory writes are serialized.",
                "",
                "## Session Agent Territory And Handoff",
                "",
                "- Recommend handoff for out-of-scope work.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    registry_path = tmp_path / ".docs" / "project-memory" / "agent-registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    agent = agent_directory_service.create_agent_instance(
        display_name="缓存 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-cache",
        metadata={"includeProjectAgentRegistryContext": True},
    )
    registry_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "laneTerritories": {},
                "agents": [
                    {
                        "agentId": agent["agentId"],
                        "sessionId": "session-cache",
                        "displayName": "缓存 Agent",
                        "managementScope": {"summary": "负责缓存验证"},
                        "status": "active",
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    events = []
    monkeypatch.setattr(
        context_engine,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    context_engine.build_agent_context(agent["agentId"], session_id="session-cache", run_id="turn-1")
    context_engine.build_agent_context(agent["agentId"], session_id="session-cache", run_id="turn-2")

    registry_events = [item for item in events if item[0][2] == "agent_runtime.project_agent_registry_context_loaded"]
    assert not any(item[0][2] == "agent_runtime.project_rules_context_loaded" for item in events)
    assert [item[1]["fields"]["cacheHit"] for item in registry_events[-2:]] == [False, True]
    assert [item[1]["fields"]["activeAgentDirectoryCacheHit"] for item in registry_events[-2:]] == [False, True]


def test_build_agent_context_records_static_and_dynamic_segment_hashes(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    (tmp_path / "AGENTS.md").write_text(
        "\n".join(
            [
                "## Session-Level Agent Memory Coordination",
                "",
                "- Project memory writes are serialized.",
                "",
                "## Session Agent Territory And Handoff",
                "",
                "- Recommend handoff for out-of-scope work.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    events = []
    monkeypatch.setattr(
        context_engine,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="分段 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-segments",
    )
    agent_directory_service.write_agent_inbox_message(
        agent["agentId"],
        content="动态 inbox 消息",
        summary="动态 inbox",
        created_by="test",
    )

    packet = context_engine.build_agent_context(agent["agentId"], session_id="session-segments", run_id="turn-1")

    assert packet.static_context_block
    assert packet.dynamic_context_block
    assert packet.context_block == "\n\n".join([packet.static_context_block, packet.dynamic_context_block])
    assert packet.timings["staticContextChars"] == len(packet.static_context_block)
    assert packet.timings["dynamicContextChars"] == len(packet.dynamic_context_block)
    assert packet.timings["staticContextHash"]
    assert packet.timings["dynamicContextHash"]
    resolved_events = [item for item in events if item[0][2] == "agent_runtime.resolved"]
    assert resolved_events
    fields = resolved_events[-1][1]["fields"]
    assert fields["staticContextChars"] == len(packet.static_context_block)
    assert fields["dynamicContextChars"] == len(packet.dynamic_context_block)
    assert fields["staticContextHash"] == packet.timings["staticContextHash"]
    assert fields["dynamicContextHash"] == packet.timings["dynamicContextHash"]
    assert fields["contextSegmentCount"] == len(packet.context_segments)


def test_build_agent_context_includes_project_agent_territory_registry(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    registry_path = tmp_path / ".docs" / "project-memory" / "agent-registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_agent = agent_directory_service.create_agent_instance(
        display_name="运行主干 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-runtime",
        metadata={"includeProjectAgentRegistryContext": True},
    )
    qa_agent = agent_directory_service.create_agent_instance(
        display_name="质量运维 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-quality",
    )
    archived_agent = agent_directory_service.create_agent_instance(
        display_name="旧前端 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-archived-territory",
    )
    agent_directory_service.archive_agent_instance(archived_agent["agentId"])
    registry_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "laneTerritories": {
                    "agent-runtime-core": {
                        "managementScope": {
                            "summary": "默认负责 Agent 运行主干",
                            "taskTypes": ["runtime"],
                        },
                        "handoffTargets": ["quality-and-operations"],
                    }
                },
                "agents": [
                    {
                        "agentId": runtime_agent["agentId"],
                        "sessionId": "session-runtime",
                        "displayName": "运行主干 Agent",
                        "responsibilityLane": "agent-runtime-core",
                        "managementScope": {
                            "summary": "负责 ContextEngine、AgentDirectory 与运行上下文",
                            "files": ["core/orchestration/**", "core/web/services/agent_directory_service.py"],
                            "taskTypes": ["runtime-context", "agent-directory"],
                        },
                        "handoffTargets": ["quality-and-operations"],
                        "outOfScopePolicy": "recommend_handoff",
                        "status": "active",
                    },
                    {
                        "agentId": qa_agent["agentId"],
                        "sessionId": "session-quality",
                        "displayName": "质量运维 Agent",
                        "responsibilityLane": "quality-and-operations",
                        "managementScope": {
                            "summary": "负责测试、日志与发布收口",
                            "files": ["tests/**", "logs/runtime_scenes/**"],
                            "taskTypes": ["qa", "logging"],
                        },
                        "status": "active",
                    },
                    {
                        "agentId": archived_agent["agentId"],
                        "sessionId": "session-archived-territory",
                        "displayName": "旧前端 Agent",
                        "responsibilityLane": "web-workbench-surface",
                        "status": "archived",
                    },
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    events = []
    monkeypatch.setattr(
        context_engine,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    packet = context_engine.build_agent_context(runtime_agent["agentId"], session_id="session-runtime", run_id="turn-1")

    assert "Project Agent Territory Registry" in packet.context_block
    assert "sessionId=session-runtime" in packet.context_block
    assert "lane=agent-runtime-core" in packet.context_block
    assert "负责 ContextEngine、AgentDirectory 与运行上下文" in packet.context_block
    assert "If a user request is outside your management scope" in packet.context_block
    assert "sessionId=session-quality" in packet.context_block
    assert "lane=quality-and-operations" in packet.context_block
    assert "session-archived-territory" not in packet.context_block
    assert "projectAgentRegistryContextMs" in packet.timings
    assert any(
        item[0][:3] == ("agent_context", "context_engine", "agent_runtime.project_agent_registry_context_loaded")
        and item[1]["fields"]["sourceExists"] is True
        and item[1]["fields"]["handoffTargetCount"] == 1
        for item in events
    )


def test_build_agent_context_auto_initializes_project_agent_registry_when_missing(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    lane_dir = tmp_path / ".docs" / "project-memory" / "lanes"
    lane_dir.mkdir(parents=True, exist_ok=True)
    (lane_dir / "chat-coding-surface.json").write_text(
        json.dumps(
            {
                "id": "chat-coding-surface",
                "title": "Chat Coding Surface",
                "focus": "真实群聊体验",
                "modules": [
                    {
                        "title": "Chat UI",
                        "relatedFiles": [
                            "web/src/routes/ChatCodingRoute.tsx",
                            "core/web/services/session_service.py",
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (lane_dir / "agent-runtime-core.json").write_text(
        json.dumps(
            {
                "id": "agent-runtime-core",
                "title": "Agent Runtime Core",
                "focus": "上下文装配",
                "modules": [
                    {
                        "title": "ContextEngine",
                        "relatedFiles": ["core/orchestration/context_engine.py"],
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="孤立会话 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-lonely",
        metadata={"includeProjectAgentRegistryContext": True},
    )
    peer = agent_directory_service.create_agent_instance(
        display_name="同项目可推荐 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="research",
        direct_session_id="session-peer",
    )
    events = []
    monkeypatch.setattr(
        context_engine,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )
    registry_path = tmp_path / ".docs" / "project-memory" / "agent-registry.json"
    assert not registry_path.exists()

    packet = context_engine.build_agent_context(agent["agentId"], session_id="session-lonely", run_id="turn-1")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    assert registry_path.exists()
    assert registry["schemaVersion"] == 1
    assert registry["policy"]["autoInitialized"] is True
    assert "agent-runtime-core" in registry["laneTerritories"]
    assert "chat-coding-surface" in registry["laneTerritories"]
    assert len(registry["laneTerritories"]) == 2
    assert registry["laneTerritories"]["chat-coding-surface"]["managementScope"]["summary"] == (
        "负责 Chat Coding Surface；当前焦点：真实群聊体验"
    )
    assert (
        "web/src/routes/ChatCodingRoute.tsx"
        in registry["laneTerritories"]["chat-coding-surface"]["managementScope"]["files"]
    )
    assert "Project Agent Territory Registry" in packet.context_block
    assert "sessionId=session-lonely" in packet.context_block
    assert "真实群聊体验" in packet.context_block
    assert f"agentId={agent['agentId']}" in packet.context_block
    assert "HandoffTargets:" in packet.context_block
    assert f"agentId={peer['agentId']}" in packet.context_block
    assert "sessionId=session-peer" in packet.context_block
    assert any(
        item[0][:3] == ("agent_context", "context_engine", "agent_runtime.project_agent_registry_auto_initialized")
        and item[1]["fields"]["laneTerritoryCount"] == 2
        for item in events
    )
    assert any(
        item[0][:3] == ("agent_context", "context_engine", "agent_runtime.project_agent_registry_context_loaded")
        and item[1]["fields"]["sourceExists"] is True
        and item[1]["fields"]["autoInitialized"] is True
        for item in events
    )


def test_build_agent_context_auto_initializes_project_agent_registry_without_memory_lanes(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="无记忆泳道 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-no-lanes",
        metadata={"includeProjectAgentRegistryContext": True},
    )

    packet = context_engine.build_agent_context(agent["agentId"], session_id="session-no-lanes", run_id="turn-1")
    registry = json.loads((tmp_path / ".docs" / "project-memory" / "agent-registry.json").read_text(encoding="utf-8"))

    assert set(registry["laneTerritories"]) == {
        "agent-runtime-core",
        "chat-coding-surface",
        "quality-and-operations",
    }
    assert "Project Agent Territory Registry" in packet.context_block
    assert "conversation-ui" in packet.context_block


def test_build_agent_context_initializes_registry_outside_identified_checkout(tmp_path, monkeypatch):
    identity_path = tmp_path / ".vibelution" / "project.json"
    identity_path.parent.mkdir(parents=True)
    identity_path.write_text(
        json.dumps({"schemaVersion": 1, "projectId": "test-vibelution"}) + "\n",
        encoding="utf-8",
    )
    projects_home = tmp_path / "external" / "projects"
    monkeypatch.setenv("VIBELUTION_PROJECTS_HOME", str(projects_home))
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="外部记忆 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-external-memory",
        metadata={"includeProjectAgentRegistryContext": True},
    )

    packet = context_engine.build_agent_context(
        agent["agentId"],
        session_id="session-external-memory",
        run_id="turn-1",
    )

    registry_path = projects_home / "test-vibelution" / "memory" / "agent-registry.json"
    assert registry_path.exists()
    assert not (tmp_path / ".docs" / "project-memory" / "agent-registry.json").exists()
    assert "active external project memory/agent-registry.json" in packet.context_block


def test_build_agent_context_keeps_invalid_project_agent_registry_file(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    registry_path = tmp_path / ".docs" / "project-memory" / "agent-registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text("{invalid", encoding="utf-8")
    agent = agent_directory_service.create_agent_instance(
        display_name="坏配置兜底 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-invalid-registry",
        metadata={"includeProjectAgentRegistryContext": True},
    )
    events = []
    monkeypatch.setattr(
        context_engine,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    packet = context_engine.build_agent_context(agent["agentId"], session_id="session-invalid-registry", run_id="turn-1")

    assert registry_path.read_text(encoding="utf-8") == "{invalid"
    assert "Project Agent Territory Registry" in packet.context_block
    assert "sessionId=session-invalid-registry" in packet.context_block
    assert "conversation-ui" in packet.context_block
    assert any(
        item[0][:3] == ("agent_context", "context_engine", "agent_runtime.project_agent_registry_context_failed")
        and item[1]["fields"]["reason"] == "JSONDecodeError"
        for item in events
    )
    assert not any(
        item[0][:3] == ("agent_context", "context_engine", "agent_runtime.project_agent_registry_auto_initialized")
        for item in events
    )


def test_build_agent_context_includes_research_org_member_and_edge_context(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_tmp_research_org_workspace(tmp_path, monkeypatch)

    organization = research_organization_service.get_research_organization()
    ceo = next(node for node in organization["agents"] if node["role"] == "ceo")
    advisor = next(node for node in organization["agents"] if node["role"] == "organization_advisor")
    steward = next(node for node in organization["agents"] if node["role"] == "capability_steward")

    packet = context_engine.build_agent_context(
        ceo["agentId"],
        session_id=ceo["agent"]["directSessionId"],
        run_id="turn-research-ceo",
    )

    assert "Research Organization Context" in packet.context_block
    assert ceo["agentCode"] in packet.context_block
    assert advisor["agentCode"] in packet.context_block
    assert steward["agentCode"] in packet.context_block
    assert ceo["agentId"] in packet.context_block
    assert advisor["agentId"] in packet.context_block
    assert steward["agentId"] in packet.context_block
    assert "Directly reachable from you:" in packet.context_block
    assert f"edge-{ceo['agentId']}-{advisor['agentId']}" in packet.context_block
    assert f"edge-{ceo['agentId']}-{steward['agentId']}" in packet.context_block
    assert "allowedTypes=" in packet.context_block
    assert "Use AgentId or AgentCode with agent_message_tool" in packet.context_block
    assert "Organization Governance Protocol:" in packet.context_block
    assert "Research Communication Protocol:" in packet.context_block
    assert "Every research_org message from an Agent must include metadata_json.researchOrgIntent" in packet.context_block
    assert "Reply format: Conclusion; Evidence; Risk; Decision needed; Next step." in packet.context_block
    assert "research_agent_creation_proposal_tool" in packet.context_block
    assert "only after that proposal is applied should you configure its tool permissions or communication edges" in packet.context_block
    assert "Organization Advisor can propose new Agents" in packet.context_block
    assert "Capability Steward can propose missing capability Agents" in packet.context_block
    assert "prompt/tool/memory policy recommendations" in packet.context_block
    assert "Organization Capability Roster:" in packet.context_block
    assert "proposalActions=propose_create_agent" in packet.context_block
    assert "Team Onboarding Context:" in packet.context_block
    assert "You may treat other members' roster entries as their responsibilities, not as tools you can call." in packet.context_block


def test_research_specialist_context_does_not_name_hidden_creation_tool(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_tmp_research_org_workspace(tmp_path, monkeypatch)

    proposal = research_organization_service.create_research_org_proposal(
        {
            "riskLevel": "medium",
            "actions": [
                {
                    "actionType": "create_agent",
                    "displayName": "普通研究员",
                    "role": "research_specialist",
                    "roleKey": "research_specialist",
                    "allowedTools": ["agent_message_tool"],
                }
            ],
        }
    )
    applied = research_organization_service.apply_research_org_proposal(proposal["proposal"]["proposalId"])
    specialist_id = applied["results"][0]["agentId"]

    packet = context_engine.build_agent_context(
        specialist_id,
        session_id=agent_directory_service.get_agent(specialist_id)["directSessionId"],
        run_id="turn-specialist",
    )

    assert "research_agent_creation_proposal_tool" not in packet.context_block
    assert "report the gap to CEO, Organization Advisor, or Capability Steward" in packet.context_block
    assert "peer-only tools hidden by your ToolPolicy" in packet.context_block


def test_build_agent_context_filters_research_org_context_to_connected_subgraph(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_tmp_research_org_workspace(tmp_path, monkeypatch)
    disconnected = agent_directory_service.create_agent_instance(
        display_name="旧研究员",
        primary_mode="research",
        role_key="research_specialist",
        prompt_template_id="prompt-research-broad",
        direct_session_id="session-old-specialist",
        metadata={"researchOrgRole": "research_specialist", "systemRole": "research_specialist"},
    )
    organization = research_organization_service.get_research_organization()
    ceo = next(node for node in organization["agents"] if node["role"] == "ceo")
    advisor = next(node for node in organization["agents"] if node["role"] == "organization_advisor")
    organization["agents"].append(
        {
            "nodeId": disconnected["agentId"],
            "agentId": disconnected["agentId"],
            "role": "research_specialist",
            "employeeRank": "member",
            "status": "active",
        }
    )
    research_organization_service.save_research_organization(organization)

    packet = context_engine.build_agent_context(
        ceo["agentId"],
        session_id=ceo["agent"]["directSessionId"],
        run_id="turn-research-ceo",
    )

    assert ceo["agentId"] in packet.context_block
    assert advisor["agentId"] in packet.context_block
    assert f"agentId={disconnected['agentId']} " not in packet.context_block


def test_created_research_agent_context_includes_role_contract_and_escalation(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_tmp_research_org_workspace(tmp_path, monkeypatch)

    proposal = research_organization_service.create_research_org_proposal(
        {
            "riskLevel": "medium",
            "actions": [
                {
                    "actionType": "create_agent",
                    "displayName": "知识库管理员",
                    "role": "research_knowledge_steward",
                    "roleKey": "research_knowledge_steward",
                    "promptTemplateId": "prompt-research-broad",
                    "responsibilities": [
                        "Maintains research database schemas and memory cleanup queues.",
                        "Reports storage risks before changing shared knowledge.",
                    ],
                    "allowedTools": ["agent_message_tool", "research_knowledge_query_tool"],
                    "readSharedGroups": ["project", "research", "agent_config"],
                    "writeSharedGroups": ["research"],
                    "communicationTargets": ["CEO", "Capability Steward"],
                }
            ],
        }
    )
    applied = research_organization_service.apply_research_org_proposal(proposal["proposal"]["proposalId"])
    created_agent_id = applied["results"][0]["agentId"]

    packet = context_engine.build_agent_context(
        created_agent_id,
        session_id=agent_directory_service.get_agent(created_agent_id)["directSessionId"],
        run_id="turn-created-agent",
    )

    created_agent = agent_directory_service.get_agent(created_agent_id)
    role_contract = created_agent["metadata"]["roleContract"]
    assert role_contract["teamId"] == "research-team"
    assert role_contract["role"] == "research_knowledge_steward"
    assert role_contract["onboardingRequired"] is True
    assert role_contract["allowedTools"] == ["agent_message_tool", "research_knowledge_query_tool"]
    assert "Team Onboarding Context:" in packet.context_block
    assert "Your role: research_knowledge_steward" in packet.context_block
    assert "Maintains research database schemas and memory cleanup queues." in packet.context_block
    assert "Escalation path: CEO -> Organization Advisor -> Capability Steward -> User gate" in packet.context_block
    assert "Do not expand your own tools" in packet.context_block
    assert "Organization Capability Roster:" in packet.context_block


def test_build_agent_context_returns_empty_packet_for_missing_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    packet = context_engine.build_agent_context("missing-agent", session_id="session-missing")

    assert packet.agent_id == "missing-agent"
    assert packet.session_id == "session-missing"
    assert packet.context_block == ""
    assert packet.memory_policy == {}
    assert packet.tool_policy == {}


def test_build_agent_context_returns_empty_packet_for_archived_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="已归档上下文 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-archived",
    )
    events = []
    monkeypatch.setattr(
        context_engine,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    agent_directory_service.archive_agent_instance(agent["agentId"])
    packet = context_engine.build_agent_context(agent["agentId"], session_id="session-archived")

    assert packet.agent_id == agent["agentId"]
    assert packet.session_id == "session-archived"
    assert packet.context_block == ""
    assert packet.memory_policy == {}
    assert packet.tool_policy == {}
    assert packet.timings["reason"] == "archived_agent"
    assert packet.timings["agentStatus"] == "archived"
    assert any(
        item[0][:3] == ("agent_context", "context_engine", "agent_runtime.resolve_failed")
        and item[1]["fields"]["reason"] == "archived_agent"
        and item[1]["fields"]["agentStatus"] == "archived"
        for item in events
    )


def test_prepare_subagent_spawn_isolated_by_default_and_fork_is_explicit(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    parent = agent_directory_service.create_agent_instance(
        display_name="父 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-parent",
        metadata={
            "delegationPolicy": {
                "allowSubagents": True,
                "maxDepth": 2,
                "maxConcurrent": 1,
                "allowWakeMessages": True,
                "allowedContextModes": ["isolated", "fork"],
            }
        },
    )

    isolated = context_engine.prepare_subagent_spawn(
        parent["agentId"],
        "session-parent",
        context_mode="isolated",
    )
    forked = context_engine.prepare_subagent_spawn(
        parent["agentId"],
        "session-parent",
        context_mode="fork",
    )

    assert isolated.parent_context is None
    assert forked.parent_context is not None
    assert forked.parent_context.agent_id == parent["agentId"]


def test_prepare_subagent_spawn_respects_delegation_policy(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    parent = agent_directory_service.create_agent_instance(
        display_name="受控父 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-parent",
        metadata={
            "delegationPolicy": {
                "allowSubagents": True,
                "maxDepth": 1,
                "maxConcurrent": 1,
                "allowWakeMessages": True,
                "allowedContextModes": ["isolated"],
            }
        },
    )

    allowed = context_engine.prepare_subagent_spawn(
        parent["agentId"],
        "session-parent",
        context_mode="isolated",
        requested_depth=1,
    )

    assert allowed.context_mode == "isolated"
    try:
        context_engine.prepare_subagent_spawn(
            parent["agentId"],
            "session-parent",
            context_mode="fork",
            requested_depth=1,
        )
    except ValueError as exc:
        assert "fork" in str(exc)
    else:
        raise AssertionError("Expected disallowed context mode to be blocked")
    try:
        context_engine.prepare_subagent_spawn(
            parent["agentId"],
            "session-parent",
            context_mode="isolated",
            requested_depth=2,
        )
    except ValueError as exc:
        assert "深度" in str(exc) or "depth" in str(exc).lower()
    else:
        raise AssertionError("Expected max depth to be blocked")


def test_record_agent_turn_result_writes_bounded_agent_event(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="会话 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-live",
    )

    context_engine.record_agent_turn_result(
        agent["agentId"],
        "session-live",
        {
            "status": "completed",
            "summary": "line1\nline2\nline3\nline4\nline5",
            "tool_call_count": 2,
        },
        run_id="session-live-turn-1",
    )

    event_path = tmp_path / agent["workspacePath"] / "events" / "agent_turn_results.jsonl"
    records = [
        json.loads(line)
        for line in event_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["agentId"] == agent["agentId"]
    assert records[0]["sessionId"] == "session-live"
    assert records[0]["status"] == "completed"
    assert records[0]["toolCallCount"] == 2
    assert records[0]["summary"] == "line1\nline2\nline3\nline4"

    run_path = (
        work_run_store.WORK_RUNS_DIR
        / context_engine.AGENT_RUN_KIND
        / "runs"
        / f"agentrun-{agent['agentId']}-session-live-turn-1.json"
    )
    snapshot = json.loads(run_path.read_text(encoding="utf-8"))
    assert snapshot["runKind"] == "agent_run"
    assert snapshot["sourceRunId"] == "session-live-turn-1"
    assert snapshot["agentId"] == agent["agentId"]
    assert snapshot["agentCode"] == agent["agentCode"]
    assert snapshot["primaryMode"] == "chat"
    assert snapshot["dialogueModelId"] == "model-primary"
    assert snapshot["promptTemplateId"] == "prompt-chat-default"
    assert snapshot["workspacePath"] == agent["workspacePath"]
    assert snapshot["sessionId"] == "session-live"
    assert snapshot["status"] == "completed"
    assert snapshot["toolCallCount"] == 2
    assert snapshot["summary"] == "line1\nline2\nline3\nline4"
    assert "raw_output" not in snapshot
    assert "apiKey" not in json.dumps(snapshot)


def test_list_agent_runs_returns_bounded_safe_snapshots(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="运行历史 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-runs",
    )

    context_engine.record_agent_turn_result(
        agent["agentId"],
        "session-runs",
        {
            "status": "completed",
            "summary": "Authorization: Bearer sk-sensitive-token\nok",
            "raw_output": "full raw output should not be preferred",
            "tool_call_count": 1,
        },
        run_id="session-runs-turn-1",
    )
    context_engine.record_subagent_result(
        "session-runs-turn-1",
        "sub-1",
        {
            "status": "completed",
            "summary": "sub result",
            "parentAgentId": agent["agentId"],
            "parentSessionId": "session-runs",
            "contextMode": "isolated",
            "toolCallCount": 0,
        },
    )

    payload = context_engine.list_agent_runs_for_agent(agent["agentId"], limit=5)

    assert payload["agentId"] == agent["agentId"]
    assert payload["limit"] == 5
    assert len(payload["runs"]) == 1
    assert payload["runs"][0]["runKind"] == "agent_run"
    assert payload["runs"][0]["sourceRunId"] == "session-runs-turn-1"
    assert payload["runs"][0]["summary"] == "Authorization: Bearer ***\nok"
    assert "raw_output" not in payload["runs"][0]
    assert "metadata" not in payload["runs"][0]
    assert len(payload["subAgentRuns"]) == 1
    assert payload["subAgentRuns"][0]["runKind"] == "sub_agent_run"
    assert payload["subAgentRuns"][0]["parentRunId"] == "session-runs-turn-1"
    assert payload["subAgentRuns"][0]["parentAgentId"] == agent["agentId"]


def test_string_registry_names_are_kept_as_one_item():
    entry = context_engine._project_agent_registry_entry_from_sources(
        {},
        {
            "agentId": "agent-1",
            "handoffTargets": "quality-and-operations",
            "managementScope": {
                "summary": "runtime",
                "files": "core/orchestration/**",
                "taskTypes": "runtime-context",
            },
        },
        lane_defaults={},
    )
    assert entry["handoffTargets"] == ["quality-and-operations"]
    assert entry["managementScope"]["files"] == ["core/orchestration/**"]
    assert entry["managementScope"]["taskTypes"] == ["runtime-context"]
    assert context_engine._join_context_segments("not-a-segment-list", "cache_prefix") == ""
    assert context_engine._bounded_limit("bad", default=6) == 6
    assert context_engine._safe_int(0) == 0
    assert context_engine._safe_int("bad") == 0
    assert context_engine._safe_int(True) == 0
    assert context_engine._safe_int(b"6") == 6
    assert context_engine._coerce_bool("false", default=True) is False
    assert context_engine._context_hash(b"static-block") == context_engine._context_hash("static-block")
    assert context_engine._agent_allows_project_agent_registry_context(
        {"metadata": '{"includeProjectAgentRegistryContext":"false"}'}
    ) is False
    assert context_engine._agent_allows_project_agent_registry_context(
        {"metadata": '{"includeProjectAgentRegistryContext":"true"}'}
    ) is True


def test_context_engine_parses_json_name_lists_and_segment_envelopes():
    assert context_engine._coerce_str_list('["alpha", "beta"]') == ["alpha", "beta"]
    assert context_engine._coerce_str_list(bytearray(b"ops-lane")) == ["ops-lane"]
    assert context_engine._coerce_str_list(
        {"ops": {"enabled": False}, "quality": {"enabled": True}}
    ) == ["quality"]
    assert context_engine._join_context_segments(
        b'{"items": [{"placement": "cache_prefix", "block": "hello"}]}',
        b"cache_prefix",
    ) == "hello"
    assert context_engine._join_context_segments(
        [{"placement": b"cache_prefix", "block": b"hello"}],
        "cache_prefix",
    ) == "hello"
    assert context_engine._bounded_limit(True, default=6) == 6


def test_list_agent_runs_for_agents_treats_string_id_as_one_agent(monkeypatch):
    seen: dict[str, object] = {}

    def fake_list(agent_ids, *, limit=20):
        seen["ids"] = list(agent_ids)
        seen["limit"] = limit
        return {"agentIds": list(agent_ids), "limit": limit, "agents": {}}

    monkeypatch.setattr(context_engine.agent_run_store, "list_agent_runs_for_agents", fake_list)
    payload = context_engine.list_agent_runs_for_agents("agent-xyz", limit="5")
    assert seen["ids"] == ["agent-xyz"]
    assert seen["limit"] == 5
    assert payload["agentIds"] == ["agent-xyz"]

    json_payload = context_engine.list_agent_runs_for_agents(
        '["agent-a", "agent-b"]',
        limit=True,
    )
    assert seen["ids"] == ["agent-a", "agent-b"]
    assert seen["limit"] == 20
    assert json_payload["agentIds"] == ["agent-a", "agent-b"]


def test_record_agent_turn_result_keeps_explicit_zero_tool_calls(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="零工具调用 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-zero-tools",
    )

    context_engine.record_agent_turn_result(
        agent["agentId"],
        "session-zero-tools",
        {
            "status": "completed",
            "summary": "no tools",
            "tool_call_count": 0,
            "toolCallCount": 9,
        },
        run_id="session-zero-tools-turn-1",
    )

    event_path = tmp_path / agent["workspacePath"] / "events" / "agent_turn_results.jsonl"
    records = [
        json.loads(line)
        for line in event_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records[0]["toolCallCount"] == 0


def test_prepare_subagent_spawn_accepts_bytes_context_mode(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    parent = agent_directory_service.create_agent_instance(
        display_name="字节模式父 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-bytes-parent",
        metadata={
            "delegationPolicy": {
                "allowSubagents": True,
                "maxDepth": 1,
                "maxConcurrent": 1,
                "allowWakeMessages": True,
                "allowedContextModes": ["isolated", "fork"],
            }
        },
    )

    isolated = context_engine.prepare_subagent_spawn(
        parent["agentId"],
        "session-bytes-parent",
        context_mode=b"isolated",
    )
    assert isolated.context_mode == "isolated"
    assert isolated.parent_context is None


def test_build_agent_context_coerces_json_snapshot_and_false_prompt_flag(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="JSON 快照 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-json-snapshot",
    )
    original_get_agent = agent_directory_service.get_agent

    def reject_duplicate_agent_lookup(agent_id, *, include_archived=False):
        if agent_id == agent["agentId"] and not include_archived:
            raise AssertionError("JSON Agent snapshot should avoid duplicate get_agent")
        return original_get_agent(agent_id, include_archived=include_archived)

    monkeypatch.setattr(agent_directory_service, "get_agent", reject_duplicate_agent_lookup)
    monkeypatch.setattr(
        context_engine,
        "_build_prompt_template_context_block",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("string false should skip prompt template context")
        ),
    )

    snapshot = dict(agent)
    snapshot["agent_id"] = snapshot.pop("agentId")
    packet = context_engine.build_agent_context(
        agent["agentId"].encode("utf-8"),
        session_id=b"session-json-snapshot",
        run_id=b"turn-1",
        agent_snapshot=json.dumps(snapshot),
        include_prompt_template_context="false",
    )

    assert packet.agent_id == agent["agentId"]
    assert packet.display_name == agent["displayName"]
    assert packet.session_id == "session-json-snapshot"
    assert packet.timings["promptTemplateContextSkipped"] is True
    assert all(segment["key"] != "prompt_template" for segment in packet.context_segments)


def test_record_agent_turn_result_parses_json_payload(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="JSON 结果 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-json-result",
    )

    context_engine.record_agent_turn_result(
        agent["agentId"],
        b"session-json-result",
        '{"status":"completed","summary":"ok","toolCallCount":"3","runId":"session-json-result-turn-1"}',
    )

    event_path = tmp_path / agent["workspacePath"] / "events" / "agent_turn_results.jsonl"
    records = [
        json.loads(line)
        for line in event_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records[0]["sessionId"] == "session-json-result"
    assert records[0]["toolCallCount"] == 3
    assert records[0]["runId"] == "session-json-result-turn-1"
    assert records[0]["status"] == "completed"
