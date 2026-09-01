# -*- coding: utf-8 -*-
"""System prompt 缓存前缀稳定化护栏。

核心契约：同一 (agent, session) 跨轮重建上下文时，merge 进第一条 system
消息的 cache_prefix 静态块字节必须恒定（即使底层 catalog / 花名册 /
prompt template 在会话中途发生变化）；不同 session 允许拿到新字节。
动态运行时上下文不受冻结影响，保持逐轮新鲜。
"""

import hashlib
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from agent import TurnStopRequested
from core.orchestration import context_engine, turn_llm_adapter
from core.orchestration.turn_llm_adapter import (
    AgentLlmTurnHooks,
    _message_digest_entries,
    invoke_agent_llm_turn,
)
from core.orchestration.turn_outcome import TurnOutcomeController
from core.web.services import (
    agent_directory_service,
    prompt_template_service,
    research_organization_service,
    team_knowledge_service,
)
from tests.test_context_engine import (
    _use_tmp_project_root,
    _use_tmp_research_org_workspace,
)


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


class _DummyContext:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _DummyUI:
    def thinking(self, _label):
        return _DummyContext()


@pytest.fixture(autouse=True)
def _clean_session_freeze_cache():
    context_engine.reset_session_context_freeze_cache()
    yield
    context_engine.reset_session_context_freeze_cache()


def _create_research_agent(tmp_root, monkeypatch):
    """Create a research-mode agent that consumes all three drifting blocks."""
    agent = agent_directory_service.create_agent_instance(
        display_name="前缀冻结 Agent",
        llm_bindings={"dialogue": {"modelId": "model-research-broad"}},
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
        direct_session_id="session-freeze",
        metadata={"includePublicStructureContext": True},
    )
    workspace = _use_tmp_research_org_workspace(tmp_root, monkeypatch)
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
    return agent


def _install_drifting_block_fakes(monkeypatch):
    """Fake the three drifting producers with externally mutable content."""
    catalog_state = {"block": "## Public Structure Catalog\nincluded=3 omitted=1 excludedStartup=0 budgetChars=4000"}

    def fake_startup_block(*, agent_id=""):
        return {"block": catalog_state["block"], "budget": {"included": 3}}

    monkeypatch.setattr(team_knowledge_service, "build_startup_structure_block", fake_startup_block)

    template_state = {"block": "## Prompt Template v1\n- stable body"}

    def fake_template_context(template_id, **_kwargs):
        return {"reason": "", "contextBlock": template_state["block"]}

    monkeypatch.setattr(prompt_template_service, "build_agent_prompt_template_context", fake_template_context)
    return catalog_state, template_state


def test_same_session_freezes_static_prefix_bytes_across_drifting_sources(tmp_path, monkeypatch):
    """sha 护栏：同 session 跨轮，即使三个漂移源全部变化，静态块字节恒定。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    workspace = _use_tmp_research_org_workspace(tmp_path, monkeypatch)
    catalog_state, template_state = _install_drifting_block_fakes(monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="前缀冻结 Agent",
        llm_bindings={"dialogue": {"modelId": "model-research-broad"}},
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
        direct_session_id="session-freeze-guard",
        metadata={"includePublicStructureContext": True},
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

    turn_one = context_engine.build_agent_context(agent["agentId"], session_id="sess-A", run_id="turn-1")
    assert "included=3" in turn_one.static_context_block
    assert "Prompt Template v1" in turn_one.static_context_block

    # 会话中途所有漂移源发生变化：目录计数/冲突、模板编辑、花名册新增成员。
    catalog_state["block"] = "## Public Structure Catalog\nincluded=7 omitted=9 excludedStartup=2 conflict=3 budgetChars=4000"
    template_state["block"] = "## Prompt Template v2\n- edited body"
    organization["agents"].append(
        {
            "nodeId": "agent-newcomer",
            "agentId": "agent-newcomer",
            "role": "research_specialist",
            "employeeRank": "member",
            "status": "active",
        }
    )
    workspace.write_research_organization(organization)
    with context_engine._RESEARCH_ORG_CONTEXT_CACHE_LOCK:
        context_engine._RESEARCH_ORG_CONTEXT_CACHE.clear()

    turn_two = context_engine.build_agent_context(agent["agentId"], session_id="sess-A", run_id="turn-2")

    # 防回归核心断言：第一条 system 消息的静态前缀字节恒定。
    assert _sha(turn_two.static_context_block) == _sha(turn_one.static_context_block)
    assert "included=3" in turn_two.static_context_block
    assert "included=7" not in turn_two.static_context_block
    assert "Prompt Template v1" in turn_two.static_context_block
    assert "Prompt Template v2" not in turn_two.static_context_block
    assert "agent-newcomer" not in turn_two.static_context_block
    assert turn_two.timings["staticContextFrozenSegments"] == [
        "agent_runtime",
        "research_organization",
        "prompt_template",
        "public_structure",
    ]

    # 不同 session 允许（并且应该）拿到会话开始时的新快照。
    turn_new_session = context_engine.build_agent_context(agent["agentId"], session_id="sess-B", run_id="turn-1")
    assert _sha(turn_new_session.static_context_block) != _sha(turn_one.static_context_block)
    assert "included=7" in turn_new_session.static_context_block
    assert "Prompt Template v2" in turn_new_session.static_context_block
    assert "agent-newcomer" in turn_new_session.static_context_block


def test_dynamic_context_stays_live_while_static_prefix_frozen(tmp_path, monkeypatch):
    """冻结只作用于 cache_prefix 静态块；dynamic 块保持逐轮新鲜。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    _install_drifting_block_fakes(monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="动静分离 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-dynamic-live",
    )

    turn_one = context_engine.build_agent_context(agent["agentId"], session_id="sess-dyn", run_id="turn-1")
    agent_directory_service.write_agent_inbox_message(
        agent["agentId"],
        content="第二轮新到的 inbox 消息",
        summary="新 inbox 消息",
        created_by="test",
    )
    turn_two = context_engine.build_agent_context(agent["agentId"], session_id="sess-dyn", run_id="turn-2")

    assert _sha(turn_two.static_context_block) == _sha(turn_one.static_context_block)
    assert "第二轮新到的 inbox 消息" not in turn_two.static_context_block
    assert "第二轮新到的 inbox 消息" in turn_two.dynamic_context_block
    assert "第二轮新到的 inbox 消息" in turn_two.context_block


def test_frozen_output_matches_fresh_output_when_inputs_stable(tmp_path, monkeypatch):
    """零差异：无漂移输入时，冻结复用与重新计算产出完全一致。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    _install_drifting_block_fakes(monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="零差异 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-zero-diff",
    )

    frozen = context_engine.build_agent_context(agent["agentId"], session_id="sess-z", run_id="turn-1")
    frozen_again = context_engine.build_agent_context(agent["agentId"], session_id="sess-z", run_id="turn-2")
    fresh_other_session = context_engine.build_agent_context(agent["agentId"], session_id="sess-z2", run_id="turn-1")

    assert _sha(frozen_again.static_context_block) == _sha(frozen.static_context_block)
    assert _sha(fresh_other_session.static_context_block) == _sha(frozen.static_context_block)


def test_session_freeze_ttl_refresh_recomputes_after_expiry(monkeypatch):
    context_engine.reset_session_context_freeze_cache()
    calls = []
    counter = {"n": 0}

    def produce():
        counter["n"] += 1
        return f"block-{counter['n']}"

    first, first_frozen = context_engine._session_frozen_context_block(
        "public_structure",
        agent_id="agent-ttl",
        session_id="sess-ttl",
        produce=produce,
        ttl_seconds=0.05,
    )
    second, second_frozen = context_engine._session_frozen_context_block(
        "public_structure",
        agent_id="agent-ttl",
        session_id="sess-ttl",
        produce=produce,
        ttl_seconds=0.05,
    )
    assert first == "block-1" and first_frozen is False
    assert second == "block-1" and second_frozen is True
    assert counter["n"] == 1
    calls.append(counter["n"])

    import time as _time

    _time.sleep(0.08)
    third, third_frozen = context_engine._session_frozen_context_block(
        "public_structure",
        agent_id="agent-ttl",
        session_id="sess-ttl",
        produce=produce,
        ttl_seconds=0.05,
    )
    assert third == "block-2" and third_frozen is False
    assert counter["n"] == 2


def test_session_freeze_requires_session_identity(monkeypatch):
    context_engine.reset_session_context_freeze_cache()
    counter = {"n": 0}

    def produce():
        counter["n"] += 1
        return f"block-{counter['n']}"

    first, first_frozen = context_engine._session_frozen_context_block(
        "public_structure", agent_id="agent-a", session_id="", produce=produce
    )
    second, second_frozen = context_engine._session_frozen_context_block(
        "public_structure", agent_id="agent-a", session_id="", produce=produce
    )
    assert first == "block-1" and second == "block-2"
    assert first_frozen is False and second_frozen is False


def test_session_freeze_cache_is_bounded(monkeypatch):
    context_engine.reset_session_context_freeze_cache()
    monkeypatch.setattr(context_engine, "_STATIC_CONTEXT_FREEZE_MAX_ENTRIES", 2)
    for index in range(4):
        context_engine._session_frozen_context_block(
            "public_structure",
            agent_id=f"agent-{index}",
            session_id="sess-bounded",
            produce=lambda suffix=index: f"block-{suffix}",
        )
    with context_engine._STATIC_CONTEXT_FREEZE_LOCK:
        cached_keys = list(context_engine._STATIC_CONTEXT_FREEZE_CACHE.keys())
    assert len(cached_keys) == 2
    assert cached_keys[-1] == ("sess-bounded", "agent-3", "public_structure")


# ---------------------------------------------------------------------------
# resume fallback 防御：找不到 user 消息时 volatile 上下文追加尾部，
# 不再 insert_at=1（否则会把 history 推到 provider cache 前缀之外）。
# ---------------------------------------------------------------------------


def test_insert_volatile_context_without_user_message_appends_at_tail():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "历史回复一"},
        {"role": "assistant", "content": "历史回复二"},
    ]
    inserted = TurnOutcomeController.insert_volatile_context_before_current_user(
        messages=messages,
        context_messages=[{"role": "system", "content": "volatile"}],
    )
    assert inserted[0] == messages[0]
    assert inserted[1:-1] == messages[1:]
    assert inserted[-1] == {"role": "system", "content": "volatile"}


def test_insert_volatile_context_fallback_keeps_history_prefix_bytes():
    """history 部分的字节序列必须与插入前完全一致（前缀稳定性证据）。"""
    history = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]
    inserted = TurnOutcomeController.insert_volatile_context_before_current_user(
        messages=[dict(item) for item in history],
        context_messages=[{"role": "system", "content": "ctx"}],
    )
    assert [dict(item) for item in inserted[: len(history)]] == history


def test_insert_volatile_context_with_user_message_unchanged():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hi"},
    ]
    inserted = TurnOutcomeController.insert_volatile_context_before_current_user(
        messages=messages,
        context_messages=[{"role": "system", "content": "ctx"}],
    )
    assert inserted == [
        {"role": "system", "content": "system"},
        {"role": "system", "content": "ctx"},
        {"role": "user", "content": "hi"},
    ]


def test_insert_volatile_context_empty_messages_starts_payload():
    inserted = TurnOutcomeController.insert_volatile_context_before_current_user(
        messages=[],
        context_messages=[{"role": "system", "content": "ctx"}],
    )
    assert inserted == [{"role": "system", "content": "ctx"}]


# ---------------------------------------------------------------------------
# USER_PROFILE / DELEGATION_RULES 静态化
# ---------------------------------------------------------------------------


def test_user_profile_and_delegation_rules_are_static_prefix_sections():
    from core.prompt_manager.sections import make_delegation_rules_section, make_user_profile_section

    profile = make_user_profile_section()
    delegation = make_delegation_rules_section()
    assert profile.cache_break is False
    assert profile.cache_prefix is True
    assert delegation.cache_break is False
    assert delegation.cache_prefix is True


def test_static_sections_compute_once_and_stay_in_system_prefix():
    from core.prompt_manager.builder import get_system_prompt
    from core.prompt_manager.section_cache import SystemPromptCache
    from core.prompt_manager.sections import make_delegation_rules_section

    cache = SystemPromptCache()
    first = get_system_prompt([make_delegation_rules_section()], cache)
    second = get_system_prompt([make_delegation_rules_section()], cache)
    assert first.section_results[0].source == "computed"
    assert second.section_results[0].source == "cache"
    assert second.section_results[0].content == first.section_results[0].content
    assert second.section_results[0].cache_prefix is True
    manifest = second.assembly_manifest.to_public_dict()
    prefix_segments = [
        segment
        for segment in manifest.get("segments") or []
        if segment.get("key") == "DELEGATION_RULES"
    ]
    assert prefix_segments and prefix_segments[0].get("placement") == "system_prefix"


# ---------------------------------------------------------------------------
# 会议轮/普通轮统一的逐消息 sha 日志
# ---------------------------------------------------------------------------


def test_message_digest_entries_summarize_without_content_leakage():
    messages = [
        {"role": "system", "content": "stable prefix"},
        AIMessage(content="assistant reply"),
        {"role": "user", "content": [{"type": "text", "text": "blocked content"}]},
    ]
    entries = _message_digest_entries(messages)
    assert [entry["role"] for entry in entries] == ["system", "ai", "user"]
    assert all(set(entry) == {"index", "role", "sha256", "chars"} for entry in entries)
    assert entries[0]["sha256"] == hashlib.sha256(b"stable prefix").hexdigest()[:16]
    assert entries[2]["chars"] > 0
    serialized = json.dumps(entries, ensure_ascii=False)
    assert "blocked content" not in serialized


def test_message_digest_entries_are_stable_for_equal_bytes():
    entries_a = _message_digest_entries([{"role": "system", "content": "same"}])
    entries_b = _message_digest_entries([{"role": "system", "content": "same"}])
    assert entries_a == entries_b
    entries_c = _message_digest_entries([{"role": "system", "content": "changed"}])
    assert entries_a[0]["sha256"] != entries_c[0]["sha256"]


def test_invoke_agent_llm_turn_records_message_digest_event():
    scene_events = []

    class DummyLLM:
        profile_id = "primary"

        def effective_route_identity(self):
            return ("primary",)

        def effective_route_id(self):
            return "primary-route"

        def project_outcome_message(self, outcome):
            return AIMessage(content=outcome.final_text)

    from core.llm.types import CanonicalItemIdentity, TurnOutcome

    identity = CanonicalItemIdentity(
        session_id="session-digest",
        turn_id="turn-digest",
        invocation_id="invocation-digest",
        iteration=0,
        item_id="answer-digest",
    )

    def fake_invoke(_client, messages, **_kwargs):
        return TurnOutcome.final_answer(identity=identity, text="ok")

    hooks = AgentLlmTurnHooks(
        get_ui=lambda: _DummyUI(),
        llm_cancel_context=lambda _checker: _DummyContext(),
        raise_if_stop=lambda: None,
        current_stop_reason=lambda: "",
        get_llm_for_mode=lambda **_kwargs: DummyLLM(),
        should_stream=lambda *_args, **_kwargs: False,
        build_invocation_context=lambda **_kwargs: SimpleNamespace(
            to_metadata=lambda client=None: {"invocationId": "inv-1"}
        ),
        invoke_outcome=fake_invoke,
        run_streaming_outcome=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("non-stream path must not stream")
        ),
        canonicalize=lambda outcome: outcome,
        plan_recovery=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("success path must not recover")
        ),
        record_scene_event=lambda phase, event, **kwargs: scene_events.append((phase, event, kwargs)),
        record_route_success=lambda **_kwargs: None,
        request_compression=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("success path must not compress")
        ),
        debug_logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
        error_logger=SimpleNamespace(log_error=lambda *_args, **_kwargs: None),
        config=None,
        force_disable_tools=False,
        stop_error_cls=TurnStopRequested,
    )
    result = invoke_agent_llm_turn(
        messages=[{"role": "system", "content": "prefix"}, {"role": "user", "content": "hi"}],
        hooks=hooks,
    )
    assert result.payload[1].content == "ok"
    digest_events = [item for item in scene_events if item[1] == "llm_request_messages_digest"]
    assert len(digest_events) == 1
    phase, _event, kwargs = digest_events[0]
    assert phase == "llm_route"
    assert kwargs.get("level") == "debug"
    digests = kwargs["fields"]["messageDigests"]
    assert [entry["role"] for entry in digests] == ["system", "user"]
