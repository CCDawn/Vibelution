"""群聊 speaker 核心快照 seed 与装配预算闸行为。

直聊 session worker 把 COMMON/SOUL/AGENTS 冻结进核心快照并以 host-seed 标记
移出 PromptManager 装配预算；群聊 speaker 长期缺这一步，32k 窗口下 STABLE_CORE
预算装不下核心三文件，protected_tier_over_budget 硬闸让全员发言失败。这里钉住
room 路径的 seed 契约与 fail-closed 回退（无模板/缺模板不绕闸）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.prompt_manager.assembly_contract import (
    PromptCachePolicy,
    PromptDecision,
    PromptPlacement,
    PromptSegment,
    PromptStability,
    PromptTier,
    PromptTrust,
)
from core.prompt_manager.assembly_resolver import (
    PromptAssemblyBudgetError,
    PromptSectionResolver,
)
from core.web.services import agent_directory_service, chat_room_service, session_service
from core.web.services import prompt_template_service

from tests.test_chat_room_service import (
    _install_chat_room_test_llm_config,
    _isolate_chat_room_kernel,
)


_WINDOW_32K = 32_768


def _participant_for(room: dict, agent_id: str) -> dict:
    return next(
        p
        for p in room["participants"]
        if str(p.get("agentId") or "") == agent_id
    )


def _seed_template_and_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, title: str) -> dict:
    """一个绑定自定义模板的群聊成员（persistent Agent + 直属会话）。"""

    prompt_template_service.update_prompt_template(
        "prompt-chat-room-custom",
        name="群聊快照测试模板",
        category="chat",
        source_path="workspace/prompts/chat/room_custom.md",
        content="你是群聊快照测试的角色提示词。",
    )
    detail = session_service.create_chat_session(title=title)
    agent_id = str(detail["agentId"] or "").strip()
    agent_directory_service.update_agent_instance(
        agent_id,
        prompt_template_id="prompt-chat-room-custom",
    )
    return detail


def _capture_prepare_and_run(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[dict], list[object]]:
    """捕获 prepare_agent_turn 的 static_runtime_context 与 run 拿到的 agent。"""

    real_prepare = chat_room_service.prepare_agent_turn
    prepared: list[dict] = []

    def capturing_prepare(agent, **kwargs):
        prepared.append(dict(kwargs))
        return real_prepare(agent, **kwargs)

    monkeypatch.setattr(chat_room_service, "prepare_agent_turn", capturing_prepare)

    captured_agents: list[object] = []

    def fake_runner(agent, **_kwargs):
        captured_agents.append(agent)
        return {"status": "completed", "raw_output": "ok", "summary": "ok"}

    monkeypatch.setattr(chat_room_service, "run_existing_agent_single_turn", fake_runner)
    return prepared, captured_agents


def _core_segment(name: str, content: str) -> PromptSegment:
    return PromptSegment.from_content(
        key=name,
        content=content,
        tier=PromptTier.STABLE_CORE,
        placement=PromptPlacement.SYSTEM_PREFIX,
        stability=PromptStability.PROJECT_STATIC,
        trust=PromptTrust.PROTECTED_CORE,
        source=f"test.core.{name.lower()}",
        required=True,
        cache_policy=PromptCachePolicy.NEVER_CACHE,
    )


def test_chat_room_speaker_seeds_core_prompt_snapshot(tmp_path, monkeypatch):
    """有模板的 speaker：快照块进 static context、host-seed 标记为 True，
    装配侧排除三核心段且 enforce_core_floor=False，预算闸不再看到 STABLE_CORE。"""

    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)
    _install_chat_room_test_llm_config(monkeypatch)
    detail = _seed_template_and_member(tmp_path, monkeypatch, "快照发言者甲")
    peer = session_service.create_chat_session(title="快照旁听者")
    room = chat_room_service.create_chat_room(
        title="快照群聊",
        participant_agent_ids=[detail["agentId"], peer["agentId"]],
    )
    participant = _participant_for(room, detail["agentId"])
    prepared, captured_agents = _capture_prepare_and_run(monkeypatch)

    result = chat_room_service._run_participant_agent(
        participant,
        "请发言",
        {
            "roomId": room["roomId"],
            "roundId": "round-snapshot-seed",
            "topic": "快照 seed",
            "purpose": "discussion",
        },
    )
    assert result["status"] == "completed"
    assert prepared and captured_agents

    agent = captured_agents[0]
    static_context = str(prepared[0].get("static_runtime_context") or "")
    # 快照块随 static runtime context 注入且承载三核心全文。
    assert "## Agent System Prompt Snapshot" in static_context
    assert "PromptTemplateId: prompt-chat-room-custom" in static_context
    assert "## Core Prompt: COMMON" in static_context
    assert "## Core Prompt: SOUL" in static_context
    assert "## Core Prompt: AGENTS" in static_context
    # 快照已含角色模板内容，ContextEngine 的模板块不再重复注入。
    assert "## Agent Prompt Template" not in static_context
    # host-seed 标记与直聊 worker 同源。
    assert agent._core_prompt_snapshot_seeded_by_host is True

    # 装配契约：排除三核心段 + enforce_core_floor=False。
    excluded = agent._excluded_system_prompt_sections_for_turn(
        stable_session_prompt=False
    )
    assert {"COMMON", "SOUL", "AGENTS"} <= set(excluded)
    context = agent._prompt_assembly_context_for_turn()
    assert context is not None
    assert context.enforce_core_floor is False

    # 同一装配上下文下，不含 STABLE_CORE 段的 manifest 可解析，段清单无 stable_core。
    session_segment = PromptSegment.from_content(
        key="SESSION_NOTE",
        content="会话静态备注。",
        tier=PromptTier.SESSION_SNAPSHOT,
        placement=PromptPlacement.SYSTEM_PREFIX,
        stability=PromptStability.SESSION_STATIC,
        trust=PromptTrust.DERIVED_RUNTIME,
        source="test.session_note",
        cache_policy=PromptCachePolicy.NEVER_CACHE,
    )
    resolution = PromptSectionResolver().resolve([session_segment], context)
    assert all(segment.tier != PromptTier.STABLE_CORE for segment in resolution.segments)


def test_chat_room_speaker_without_seedable_snapshot_fails_closed(tmp_path, monkeypatch):
    """快照不可 seed（无 promptTemplateId 分支返回空 dict）时不得绕闸：
    三核心段留在装配清单里，32k 窗口下 protected_tier_over_budget 硬闸 raise。"""

    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)
    _install_chat_room_test_llm_config(monkeypatch)
    # 把测试模型的声明窗口钉到 32k：STABLE_CORE 预算 3000，装不下核心三文件。
    base_config = session_service.get_config()
    model_entry = base_config.llm.model_library.get("chat-room-test-model")
    assert isinstance(model_entry, dict)
    model_entry["context_window"] = _WINDOW_32K
    llm_bindings = {"dialogue": {"modelId": "chat-room-test-model"}}

    detail = session_service.create_chat_session(
        title="无模板发言者乙", llm_bindings=llm_bindings
    )
    peer = session_service.create_chat_session(
        title="无模板旁听者", llm_bindings=llm_bindings
    )
    room = chat_room_service.create_chat_room(
        title="无快照群聊",
        participant_agent_ids=[detail["agentId"], peer["agentId"]],
    )
    participant = _participant_for(room, detail["agentId"])
    prepared, captured_agents = _capture_prepare_and_run(monkeypatch)
    # 精确模拟 agent_runtime 的无 promptTemplateId 分支：ensure 返回空 dict。
    monkeypatch.setattr(
        session_service,
        "_ensure_session_agent_prompt_snapshot",
        lambda *_args, **_kwargs: {},
    )

    chat_room_service._run_participant_agent(
        participant,
        "请发言",
        {
            "roomId": room["roomId"],
            "roundId": "round-fail-closed",
            "topic": "fail-closed",
            "purpose": "discussion",
        },
    )
    assert prepared and captured_agents
    agent = captured_agents[0]
    static_context = str(prepared[0].get("static_runtime_context") or "")
    assert "## Agent System Prompt Snapshot" not in static_context
    assert agent._core_prompt_snapshot_seeded_by_host is False

    excluded = agent._excluded_system_prompt_sections_for_turn(
        stable_session_prompt=False
    )
    assert "COMMON" not in excluded
    context = agent._prompt_assembly_context_for_turn()
    assert context is not None
    assert context.enforce_core_floor is True
    assert context.context_window == _WINDOW_32K

    # 三核心段留在装配清单且超 STABLE_CORE 预算：与线上一致的硬闸 raise。
    oversized = [
        _core_segment(name, "x" * 12_000)  # ~3000 tokens/段，3 段必超 3000 预算
        for name in ("COMMON", "SOUL", "AGENTS")
    ]
    with pytest.raises(PromptAssemblyBudgetError, match="protected_tier_over_budget"):
        PromptSectionResolver().resolve(oversized, context)


def test_budget_error_message_is_actionable_and_never_retried():
    """D：预算失败改写为双语可行动指引，errorType 保持可被零输出重试围栏排除。"""

    participant = {
        "participantId": "session-budget",
        "agentId": "agent-budget",
        "agentCode": "B001",
        "sessionId": "session-budget",
        "title": "预算发言者",
    }

    def failing_runner(_participant, _prompt, _context):
        raise PromptAssemblyBudgetError(
            "protected_tier_over_budget:stable_core:AGENTS:4224>3000"
        )

    context = {
        "roundId": "round-budget",
        "speakerStartedAtMonotonic": chat_room_service._perf_counter(),
    }
    message = chat_room_service._run_one_speaker(
        participant,
        "请发言",
        context,
        failing_runner,
    )

    assert message["status"] == "failed"
    assert message["content"] == ""
    assert message["errorType"] == "PromptAssemblyBudgetError"
    summary = str(message.get("summary") or "")
    assert "64k" in summary
    assert "预算闸" in summary or "budget gate" in summary
    # 原始闸门细节保留在括号里，便于定位具体超预算的段。
    assert "protected_tier_over_budget" in summary

    # 同一错误类型必须被零输出重试围栏排除：不再白烧一次同预算重试。
    assert (
        chat_room_service._speaker_turn_zero_output_after_per_call_fence(
            message, context
        )
        is False
    )
    assert "PromptAssemblyBudgetError" in chat_room_service._ZERO_OUTPUT_RETRY_EXCLUDED_ERROR_TYPES


def test_budget_error_rewrap_leaves_other_errors_untouched():
    helper = chat_room_service._speaker_budget_failure_exception
    budget = PromptAssemblyBudgetError("protected_tier_over_budget:stable_core:AGENTS:4224>3000")
    wrapped = helper(budget)
    assert isinstance(wrapped, PromptAssemblyBudgetError)
    assert wrapped is not budget
    assert "64k" in str(wrapped)

    other = RuntimeError("boom")
    assert helper(other) is other


def test_snapshot_ensure_returns_empty_without_prompt_template_id(tmp_path, monkeypatch):
    """agent_runtime 的无 promptTemplateId 分支：ensure 返回空 dict（fail-closed 输入）。"""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    from core.web.services.session.agent_runtime import _ensure_session_agent_prompt_snapshot

    agent = {"agentId": "agent-no-template", "displayName": "无模板"}
    assert _ensure_session_agent_prompt_snapshot("session-x", agent) == {}
    assert _ensure_session_agent_prompt_snapshot("session-x", None) == {}
    assert _ensure_session_agent_prompt_snapshot("", agent) == {}
