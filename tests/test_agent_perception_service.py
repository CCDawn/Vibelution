from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from core.web.services.agent_perception import service
from core.web.services.agent_perception.policy import default_agent_perception_policy


def policy(*sources: str) -> dict:
    value = default_agent_perception_policy()
    value["enabled"] = True
    for source in sources:
        value["sources"][source]["mode"] = "auto"
        value["sources"][source]["triggers"]["task"] = True
    value["sources"]["team"]["teamIds"] = ["team-a"]
    value["sources"]["knowledge"]["scope"] = "all_authorized"
    return value


@pytest.fixture
def environment(monkeypatch):
    agent = {"agentId": "agent-a", "status": "active", "updatedAt": "revision-1", "configRevision": 1,
             "metadata": {"unrelated": {"keep": True}}}
    memory = {"enabled": True, "readKnowledgeBaseIds": []}
    tool_policy = {"allowedTools": ["github_project_library_search_tool"], "blockedTools": []}
    calls = []
    events = []

    class Directory:
        AgentNotFoundError = LookupError

        def get_agent(self, agent_id):
            return copy.deepcopy(agent) if agent_id == agent["agentId"] else None

        def update_agent_instance(self, agent_id, *, metadata, expected_updated_at, allow_agent_perception_policy=False):
            if expected_updated_at != agent["updatedAt"]:
                raise RuntimeError("revision conflict")
            agent["metadata"].update(copy.deepcopy(metadata))
            agent["updatedAt"] = "revision-2"

        def resolve_memory_policy_for_agent(self, agent_id):
            return memory

        def resolve_tool_policy_for_agent(self, agent_id):
            return tool_policy

        def list_current_episodic_events(self, agent_id, *, limit):
            return list(agent.get("testEpisodes") or [])[:limit]

    def base(owner_type, owner_id, raw_id, readable=True):
        return {"ownerType": owner_type, "ownerId": owner_id,
                "scopedKnowledgeBaseId": f"{owner_type}:{owner_id}:{raw_id}",
                "permissions": {"canRead": readable}}

    bases = [base("agent", "agent-a", "private"), base("team", "team-a", "one"),
             base("team", "team-b", "two"), base("team", "team-secret", "secret", False)]
    from core.web.services import team_knowledge_service, unified_knowledge_search_service
    from core.authorization import tool_authorization_service
    from core.web.services.agent_perception import access
    monkeypatch.setattr(service, "_directory", lambda: Directory())
    monkeypatch.setattr(service, "_consume_read_permit", lambda: None)
    monkeypatch.setattr(service, "_event", lambda code, agent_id, fields: events.append((code, fields)))
    monkeypatch.setattr(tool_authorization_service, "current_execution_authorization", lambda: SimpleNamespace(
        agent_id="agent-a", turn_id="turn-a", config_revision=1, config_hash="",
        executable_tools=("unified_memory_search_tool", "search_agent_private_memory_tool", "github_project_library_search_tool", "read_knowledge_item_tool"),
    ))
    monkeypatch.setattr(team_knowledge_service, "list_knowledge_overview", lambda **kwargs: {"knowledgeBases": bases})

    def search(**kwargs):
        calls.append(kwargs)
        return {"results": [{"resultId": kwargs["knowledge_base_id"], "title": "reference", "excerpt": "evidence" * 300,
                             "content": "SHOULD_NOT_LEAK" * 300, "metadata": {"raw": "SHOULD_NOT_LEAK"}}]}

    monkeypatch.setattr(unified_knowledge_search_service, "search_unified_memory", search)
    with access.perception_turn_scope("agent-a"):
        yield agent, memory, tool_policy, bases, calls, events


def test_missing_policy_keeps_legacy_unenforced_but_new_search_requires_setup(environment):
    state = service.get_perception_configuration("agent-a")
    assert state["configured"] is False
    assert all(row["enforced"] is False for row in state["sourceDecisions"])
    with pytest.raises(service.AgentPerceptionDenied, match="not been configured"):
        service.search_perception_sources("agent-a", query="workflow")


def test_available_scopes_only_expose_readable_shared_knowledge(environment):
    state = service.get_perception_configuration("agent-a")
    assert {row["id"] for row in state["availableScopes"]["teams"]} == {"team-a", "team-b"}
    assert {row["id"] for row in state["availableScopes"]["knowledgeBases"]} == {
        "team:team-a:one", "team:team-b:two",
    }


def test_save_uses_existing_agent_cas_preserves_unrelated_metadata_and_memory_policy(environment):
    agent, memory, _, _, _, _ = environment
    before = copy.deepcopy(memory)
    from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
    with server_operator_scope("test-operator", roles=("admin",)):
        result = service.save_perception_configuration("agent-a", policy("team"), expected_agent_updated_at="revision-1")
    assert result["configured"] is True
    assert result["agentUpdatedAt"] == "revision-2"
    assert agent["metadata"]["unrelated"] == {"keep": True}
    assert memory == before
    with server_operator_scope("test-operator", roles=("admin",)):
        with pytest.raises(RuntimeError, match="revision conflict"):
            service.save_perception_configuration("agent-a", policy("team"), expected_agent_updated_at="revision-1")


def test_explicit_total_close_blocks_new_reads_without_contacting_knowledge(environment):
    agent, _, _, _, calls, _ = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = default_agent_perception_policy()
    with pytest.raises(service.AgentPerceptionDenied):
        service.search_perception_sources("agent-a", query="workflow", requested_by_user=True)
    assert calls == []


def test_corrupt_saved_policy_fails_closed(environment):
    agent, *_ = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = None
    with pytest.raises(service.AgentPerceptionDenied, match="invalid"):
        service.get_perception_configuration("agent-a")


def test_team_scope_checks_selected_team_acl_and_explicit_base_before_read(environment):
    agent, _, _, _, calls, _ = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("team")
    result = service.search_perception_sources("agent-a", query="workflow", sources=["team"])
    assert [row["knowledge_base_id"] for row in calls] == ["team:team-a:one"]
    assert calls[0]["allowed_knowledge_base_ids"] == ["team:team-a:one"]
    assert calls[0]["include_user_content"] is False
    assert result["results"][0]["source"] == "team"
    assert "SHOULD_NOT_LEAK" not in str(result)


def test_all_authorized_respects_exclusions_and_does_not_bypass_personal_gate(environment):
    agent, _, _, _, calls, _ = environment
    value = policy("knowledge")
    value["sources"]["knowledge"]["excludedKnowledgeBaseIds"] = ["team:team-b:two"]
    agent["metadata"][service.POLICY_METADATA_KEY] = value
    service.search_perception_sources("agent-a", query="workflow", sources=["knowledge"])
    assert [row["knowledge_base_id"] for row in calls] == ["team:team-a:one"]


def test_memory_allow_list_is_intersected_even_when_acl_allows(environment):
    agent, memory, _, _, calls, _ = environment
    memory["readKnowledgeBaseIds"] = ["team:team-b:two"]
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("knowledge")
    service.search_perception_sources("agent-a", query="workflow", sources=["knowledge"])
    assert [row["knowledge_base_id"] for row in calls] == ["team:team-b:two"]


def test_overlapping_team_and_global_sources_read_each_base_once(environment):
    agent, _, _, _, calls, _ = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("team", "knowledge")
    service.search_perception_sources("agent-a", query="workflow", sources=["team", "knowledge"])
    assert len(calls) == 2
    assert len({row["knowledge_base_id"] for row in calls}) == 2


def test_acl_revoked_inside_search_callback_discards_inflight_excerpt(environment, monkeypatch):
    agent, _, _, bases, calls, _ = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("team")
    from core.web.services import unified_knowledge_search_service

    def search_then_revoke(**kwargs):
        calls.append(kwargs)
        result = {"results": [{"resultId": "in-flight", "title": "reference", "excerpt": "must be dropped"}]}
        next(row for row in bases if row["scopedKnowledgeBaseId"] == "team:team-a:one")["permissions"]["canRead"] = False
        return result

    monkeypatch.setattr(unified_knowledge_search_service, "search_unified_memory", search_then_revoke)
    result = service.search_perception_sources("agent-a", query="workflow", sources=["team"])

    assert len(calls) == 1
    assert result["readCount"] == 1
    assert result["results"] == []


def test_memory_policy_revoked_inside_episodic_callback_discards_personal_results(environment, monkeypatch):
    agent, memory, _, _, _, _ = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("personal")
    agent["testEpisodes"] = [
        {"episodeId": "episode-1", "kind": "preference", "text": "咖啡偏好：用户喜欢手冲咖啡。", "validUntil": ""},
    ]
    directory = service._directory()

    def events_then_disable(agent_id, *, limit):
        events = list(agent["testEpisodes"])[:limit]
        memory["enabled"] = False
        return events

    monkeypatch.setattr(directory, "list_current_episodic_events", events_then_disable)
    monkeypatch.setattr(service, "_directory", lambda: directory)
    from core.web.services.agent_perception import access

    with access.perception_turn_scope("agent-a", user_text="检索个人记忆", user_message_source="user"):
        result = service.search_perception_sources(
            "agent-a", query="咖啡偏好", sources=["personal"],
            invoked_tool="search_agent_private_memory_tool",
        )

    assert result["readCount"] == 1
    assert result["results"] == []


def test_knowledge_item_ticket_records_one_read_after_final_acl_check(environment, monkeypatch):
    agent, _, _, _, _, _ = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("team")
    activity = []
    monkeypatch.setattr(service, "_record_activity", lambda agent_id, **kwargs: activity.append((agent_id, kwargs)))
    ticket = service.begin_knowledge_item_read("agent-a", "team:team-a:one")

    assert ticket["knowledgeBaseId"] == "team:team-a:one"
    assert ticket["source"] == "team"
    assert service.finish_knowledge_item_read(ticket, result_count=1, result_chars=42) is True
    assert activity == [("agent-a", {
        "sources": ["team"], "read_count": 1, "result_count": 1,
        "session_id": "", "turn_id": "turn-a", "trigger": "task",
    })]


def test_knowledge_item_ticket_denies_acl_revoked_during_read(environment):
    agent, _, _, bases, _, _ = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("team")
    ticket = service.begin_knowledge_item_read("agent-a", "team:team-a:one")
    next(row for row in bases if row["scopedKnowledgeBaseId"] == "team:team-a:one")["permissions"]["canRead"] = False

    with pytest.raises(service.AgentPerceptionDenied, match="revoked"):
        service.finish_knowledge_item_read(ticket, result_count=1)


def test_knowledge_item_ticket_denies_memory_policy_revoked_during_read(environment):
    agent, memory, _, _, _, _ = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("personal")
    ticket = service.begin_knowledge_item_read("agent-a", "agent:agent-a:private")
    assert ticket["source"] == "personal"
    memory["enabled"] = False

    with pytest.raises(service.AgentPerceptionDenied, match="revoked"):
        service.finish_knowledge_item_read(ticket, result_count=1)


def test_task_search_uses_fixed_bounds_independent_of_background_policy(environment):
    agent, _, _, bases, calls, _ = environment
    value = policy("knowledge")
    value["background"]["maxCallsPerRun"] = 1
    value["background"]["maxResultChars"] = 1
    agent["metadata"][service.POLICY_METADATA_KEY] = value

    # A task search can fan out over multiple selected bases, but it has its
    # own fixed cap instead of inheriting an operator's background-run quota.
    bases.extend(
        {"ownerType": "team", "ownerId": f"team-extra-{index}",
         "scopedKnowledgeBaseId": f"team:team-extra-{index}:base-{index}",
         "permissions": {"canRead": True}}
        for index in range(10)
    )
    result = service.search_perception_sources("agent-a", query="workflow", sources=["knowledge"])

    assert len(calls) == result["readCount"] == 8
    assert all(call["max_context_chars"] == 1200 for call in calls)
    assert result["resultChars"] == sum(len(row["excerpt"]) for row in result["results"])
    assert 1 < result["resultChars"] <= 12_000


def test_manual_requires_trusted_explicit_user_request(environment):
    agent, _, _, _, calls, _ = environment
    value = policy("team")
    value["sources"]["team"]["mode"] = "manual"
    agent["metadata"][service.POLICY_METADATA_KEY] = value
    with pytest.raises(service.AgentPerceptionDenied):
        service.search_perception_sources("agent-a", query="workflow", sources=["team"], requested_by_user=True)
    from core.web.services.agent_perception import access
    with access.perception_turn_scope("agent-a", user_text="请搜索团队知识", user_message_source="user"):
        service.search_perception_sources("agent-a", query="workflow", sources=["team"], requested_by_user=False)
    assert len(calls) == 1


def test_personal_source_searches_bounded_current_episodic_memory(environment):
    agent, _, _, _, _, _ = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("personal")
    agent["testEpisodes"] = [
        {"episodeId": "episode-match", "kind": "preference", "occurredAt": "2026-10-03", "text": "咖啡偏好：用户喜欢手冲咖啡。", "validUntil": ""},
        {"episodeId": "episode-stale", "kind": "preference", "occurredAt": "2026-10-02", "text": "旧的咖啡偏好", "validUntil": "2026-10-04"},
        {"episodeId": "episode-other", "kind": "note", "occurredAt": "2026-10-01", "text": "周末骑行路线", "validUntil": ""},
    ]
    from core.web.services.agent_perception import access
    with access.perception_turn_scope("agent-a", user_text="检索个人记忆", user_message_source="user"):
        result = service.search_perception_sources(
            "agent-a", query="咖啡偏好", sources=["personal"],
            invoked_tool="search_agent_private_memory_tool",
        )
    episodes = [item for item in result["results"] if item.get("kind") == "episodic_memory"]
    assert [item["resultId"] for item in episodes] == ["episode-match"]
    assert episodes[0]["untrusted"] is True


def test_user_request_for_one_manual_source_does_not_authorize_another(environment):
    agent, _, _, _, calls, _ = environment
    value = policy("team", "knowledge")
    value["sources"]["team"]["mode"] = "manual"
    agent["metadata"][service.POLICY_METADATA_KEY] = value
    from core.web.services.agent_perception import access
    with access.perception_turn_scope("agent-a", user_text="请搜索知识库", user_message_source="user"):
        result = service.search_perception_sources(
            "agent-a", query="workflow", sources=["team", "knowledge"], requested_by_user=True,
        )
    assert [row["source"] for row in result["decisions"] if row["allowed"]] == ["knowledge"]
    assert calls and all(row["knowledge_base_id"].startswith("team:") for row in calls)
    assert all(row.get("source") == "knowledge" for row in result["results"])


def test_invoking_tool_cannot_read_a_different_source(environment):
    agent, *_ = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("projects")
    with pytest.raises(service.AgentPerceptionDenied, match="cannot read the requested"):
        service.search_perception_sources(
            "agent-a", query="governance", sources=["projects"],
            invoked_tool="unified_memory_search_tool",
        )


def test_project_source_also_respects_tool_policy(environment, monkeypatch):
    agent, _, tool_policy, _, _, _ = environment
    from core.web.services import github_project_library_service
    from core.authorization import tool_authorization_service
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("projects")
    reads = []
    monkeypatch.setattr(github_project_library_service, "search_github_project_cards", lambda **kwargs: reads.append(kwargs) or [])
    tool_policy["blockedTools"] = ["github_project_library_search_tool"]
    monkeypatch.setattr(tool_authorization_service, "current_execution_authorization", lambda: SimpleNamespace(
        agent_id="agent-a", turn_id="turn-a", config_revision=1, config_hash="",
        executable_tools=("unified_memory_search_tool",),
    ))
    with pytest.raises(service.AgentPerceptionDenied, match="did not authorize"):
        service.search_perception_sources("agent-a", query="governance", sources=["projects"],
                                          invoked_tool="github_project_library_search_tool")
    assert reads == []


def test_project_cards_use_real_nested_metadata_and_strip_paths(environment, monkeypatch):
    agent, *_ = environment
    from core.web.services import github_project_library_service
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("projects")
    card = {"resultId": "github-project:openai__codex:1", "title": "Codex", "metadata": {
        "fullName": "openai/codex", "description": "Agent execution governance", "headSha": "a" * 40,
        "license": "Apache-2.0", "absolutePath": "SHOULD_NOT_LEAK", "governanceReview": {
            "status": "review_required", "reason": "head_changed", "reuseBoundary": "Read-only reference; do not copy execution runtime",
            "evidenceRefs": [{"path": "codex-rs/core/src/exec_policy.rs", "line": 208, "kind": "source"}]}},
    }
    monkeypatch.setattr(github_project_library_service, "search_github_project_cards", lambda **kwargs: [card])
    result = service.search_perception_sources("agent-a", query="governance", sources=["projects"],
                                               invoked_tool="github_project_library_search_tool")
    item = result["results"][0]
    assert item["headSha"] == "a" * 40
    assert item["fullName"] == "openai/codex"
    assert item["excerpt"] == "Agent execution governance"
    assert item["evidenceRefs"][0]["line"] == "208"
    assert item["reviewStatus"] == "review_required" and item["reviewReason"] == "head_changed"
    assert item["license"] == "Apache-2.0"
    assert "SHOULD_NOT_LEAK" not in str(result)


def test_scope_change_between_reads_blocks_later_calls_and_discards_previous_results(environment, monkeypatch):
    agent, _, _, _, calls, _ = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("knowledge")
    from core.web.services import unified_knowledge_search_service

    def change_scope(**kwargs):
        calls.append(kwargs)
        agent["metadata"][service.POLICY_METADATA_KEY]["enabled"] = False
        return {"results": [{"excerpt": "already in flight"}]}

    monkeypatch.setattr(unified_knowledge_search_service, "search_unified_memory", change_scope)
    with pytest.raises(service.AgentPerceptionDenied, match="configuration changed"):
        service.search_perception_sources("agent-a", query="workflow", sources=["knowledge"])
    assert len(calls) == 1


def test_acl_change_between_reads_prevents_subsequent_private_read(environment, monkeypatch):
    agent, _, _, bases, calls, _ = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("knowledge")
    from core.web.services import unified_knowledge_search_service

    def revoke(**kwargs):
        calls.append(kwargs)
        bases[2]["permissions"]["canRead"] = False
        return {"results": [{"excerpt": "first permitted result"}]}

    monkeypatch.setattr(unified_knowledge_search_service, "search_unified_memory", revoke)
    service.search_perception_sources("agent-a", query="workflow", sources=["knowledge"])
    assert [row["knowledge_base_id"] for row in calls] == ["team:team-a:one"]


def test_raw_knowledge_name_does_not_expand_across_owners(environment):
    agent, _, _, _, calls, _ = environment
    value = policy("knowledge")
    value["sources"]["knowledge"].update(scope="selected", knowledgeBaseIds=["one"])
    agent["metadata"][service.POLICY_METADATA_KEY] = value
    with pytest.raises(service.AgentPerceptionDenied, match="invalid"):
        service.search_perception_sources("agent-a", query="workflow", sources=["knowledge"])
    assert calls == []


def test_raw_exclusion_cannot_silently_expand_all_authorized_scope(environment):
    agent, _, _, _, calls, _ = environment
    value = policy("knowledge")
    value["sources"]["knowledge"]["excludedKnowledgeBaseIds"] = ["one"]
    agent["metadata"][service.POLICY_METADATA_KEY] = value
    with pytest.raises(service.AgentPerceptionDenied, match="invalid"):
        service.search_perception_sources("agent-a", query="workflow", sources=["knowledge"])
    assert calls == []


def test_agent_can_narrow_all_authorized_to_one_base(environment):
    agent, _, _, _, calls, _ = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("knowledge")
    result = service.search_perception_sources(
        "agent-a", query="workflow", sources=["knowledge"],
        source_scopes={"knowledge": ["team:team-b:two"]},
    )
    assert [row["knowledge_base_id"] for row in calls] == ["team:team-b:two"]
    assert result["decisions"][0]["scope"]["ids"] == ["team:team-b:two"]


def test_agent_cannot_enlarge_selected_team_scope(environment):
    agent, _, _, _, calls, _ = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("team")
    with pytest.raises(service.AgentPerceptionDenied):
        service.search_perception_sources(
            "agent-a", query="workflow", sources=["team"], source_scopes={"team": ["team-b"]},
        )
    assert calls == []


def test_background_cannot_run_before_durable_budget_dispatcher_is_connected(environment):
    agent, _, _, _, calls, _ = environment
    value = policy("knowledge")
    value["background"].update(enabled=True, topics=["workflow"])
    value["sources"]["knowledge"]["triggers"]["background"] = True
    agent["metadata"][service.POLICY_METADATA_KEY] = value
    from core.web.services.agent_perception import access
    with access.perception_turn_scope("agent-a", trigger="background"):
        with pytest.raises(service.AgentPerceptionDenied, match="durable runtime permit"):
            service.search_perception_sources("agent-a", query="workflow", trigger="task")
    assert calls == []


def test_runtime_event_contains_hash_and_counts_not_query_or_source_body(environment):
    agent, _, _, _, _, events = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("team")
    service.search_perception_sources("agent-a", query="confidential task topic", sources=["team"])
    fields = events[-1][1]
    assert "queryHash" in fields and fields["queryLength"] == len("confidential task topic")
    assert "confidential" not in str(fields)
    assert "evidence" not in str(fields)


@pytest.mark.parametrize("kwargs", [{"sources": "team"}, {"sources": ["unknown"]}, {"sources": []},
                                    {"limit": True}, {"limit": 99}])
def test_invalid_search_arguments_do_not_read(environment, kwargs):
    agent, _, _, _, calls, _ = environment
    agent["metadata"][service.POLICY_METADATA_KEY] = policy("team")
    with pytest.raises(service.AgentPerceptionError):
        service.search_perception_sources("agent-a", query="workflow", **kwargs)
    assert calls == []


def test_saved_perception_policy_keeps_existing_static_context_and_tool_policy(tmp_path, monkeypatch):
    from core.orchestration import context_engine
    from core.web.services import agent_directory_service
    from tests.test_context_engine import _use_tmp_project_root
    from tests.test_context_prefix_freeze import _install_drifting_block_fakes

    _use_tmp_project_root(tmp_path, monkeypatch)
    _install_drifting_block_fakes(monkeypatch)
    monkeypatch.setattr(service, "_event", lambda *args, **kwargs: None)
    context_engine.reset_session_context_freeze_cache()
    try:
        agent = agent_directory_service.create_agent_instance(
            display_name="感知策略缓存测试", primary_mode="chat",
            llm_bindings={"dialogue": {"modelId": "model-primary"}},
        )
        before = context_engine.build_agent_context(agent["agentId"], session_id="perception-cache-test", run_id="one")
        from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
        with server_operator_scope("test-operator", roles=("admin",)):
            service.save_perception_configuration(agent["agentId"], policy("projects"), expected_agent_updated_at=agent["updatedAt"])
        after = context_engine.build_agent_context(agent["agentId"], session_id="perception-cache-test", run_id="two")
        fresh = context_engine.build_agent_context(agent["agentId"], session_id="perception-cache-new", run_id="one")
        assert before.static_context_block == after.static_context_block == fresh.static_context_block
        assert before.tool_policy == after.tool_policy == fresh.tool_policy
        assert "perceptionPolicy" not in after.static_context_block
    finally:
        context_engine.reset_session_context_freeze_cache()
