from core.infrastructure.agent_session import reset_session_state
from core.prompt_manager import PromptManager, split_sys_prompt_prefix
from core.web.services.session_service import (
    SESSION_PROMPT_CACHE_SCOPE_AGENT_STATIC,
    SESSION_PROMPT_CACHE_SCOPE_SESSION_FALLBACK,
    _SESSION_LIST_CACHE_TTL_SECONDS,
    _begin_session_list_cache_build,
    _finish_session_list_cache_build,
    _invalidate_session_list_cache,
    _session_prompt_cache_partition,
    _session_prompt_cache_scope,
)


def test_delegation_state_stays_outside_cacheable_prompt_prefix():
    session = reset_session_state()
    session.record_delegation_start("diagnose", "分析缓存命中", {"file": "logs/demo.jsonl"})

    pm = PromptManager()
    sp = pm.build(include=["DELEGATION_RULES", "DELEGATION_STATE"])
    static_parts, dynamic_parts = split_sys_prompt_prefix(sp)

    assert any("## 委派规则" in part for part in static_parts)
    assert not any("当前委派中" in part for part in static_parts)
    assert any("## 委派状态" in part for part in dynamic_parts)
    assert any("当前委派中" in part for part in dynamic_parts)


def test_chat_prompt_cache_partition_reuses_agent_static_scope_across_sessions():
    first = _session_prompt_cache_partition(
        session_id="session-a",
        agent_id="agent-alpha",
        llm_slot="dialogue",
        model_id="model-a",
        prompt_template_id="template-a",
    )
    second = _session_prompt_cache_partition(
        session_id="session-b",
        agent_id="agent-alpha",
        llm_slot="dialogue",
        model_id="model-a",
        prompt_template_id="template-a",
    )
    other_agent = _session_prompt_cache_partition(
        session_id="session-b",
        agent_id="agent-beta",
        llm_slot="dialogue",
        model_id="model-a",
        prompt_template_id="template-a",
    )

    assert first == second
    assert first != other_agent
    assert first.startswith("chat-agent-static-")
    assert len(first) <= 40
    assert _session_prompt_cache_scope(agent_id="agent-alpha") == SESSION_PROMPT_CACHE_SCOPE_AGENT_STATIC


def test_chat_prompt_cache_partition_falls_back_to_session_scope_without_agent():
    first = _session_prompt_cache_partition(
        session_id="session-a",
        llm_slot="dialogue",
        model_id="model-a",
    )
    second = _session_prompt_cache_partition(
        session_id="session-b",
        llm_slot="dialogue",
        model_id="model-a",
    )

    assert first != second
    assert first.startswith("chat-session-")
    assert len(first) <= 32
    assert _session_prompt_cache_scope(agent_id="") == SESSION_PROMPT_CACHE_SCOPE_SESSION_FALLBACK


def test_session_list_cache_ttl_covers_chat_index_poll_interval():
    _invalidate_session_list_cache()
    signature = (("chat-state.json", 1, 10), ("agent-registry.json", 1, 10))

    cached, should_build, waited = _begin_session_list_cache_build(now=100.0, signature=signature)
    assert cached is None
    assert should_build is True
    assert waited is False

    _finish_session_list_cache_build(
        signature=signature,
        sessions=[{"id": "session-a"}],
        started_at=100.0,
        conversation_count=1,
        agent_count=1,
    )

    cached, should_build, waited = _begin_session_list_cache_build(now=103.0, signature=signature)
    assert should_build is False
    assert waited is False
    assert cached is not None
    assert cached[0] == [{"id": "session-a"}]
    assert cached[1] == 3000
    assert _SESSION_LIST_CACHE_TTL_SECONDS >= 3.0

    cached, should_build, waited = _begin_session_list_cache_build(
        now=100.0 + _SESSION_LIST_CACHE_TTL_SECONDS + 0.01,
        signature=signature,
    )
    assert cached is None
    assert should_build is True
    assert waited is False
    _finish_session_list_cache_build(signature=signature)
