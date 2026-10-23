# -*- coding: utf-8 -*-
"""预算注入文案与授权层解析的一致性契约。

授权层（``install_execution_authorization``）按「会话覆盖
（sessionBudgetParameters）> 模型家族（``resolve_max_calls_per_turn``）
> 策略 base」得到执行额度。SPEC_DIGEST、ENV_INFO、runtime goal 包与
Agent Runtime Context 投影写进 prompt 的数字必须等于该终值，
禁止回退写死「常见 32 次」（DeepSeek 家族实际执行 64）。
"""

from pathlib import Path

from core.infrastructure.runtime_input import build_chat_user_message
from core.orchestration.agent_modes import AgentMode, ModePolicy
from core.orchestration.runtime_goal import build_runtime_goal_packet
from core.orchestration.session_budget_resolve import SessionBudgetParameters
from core.orchestration.tool_budget_profiles import resolve_max_calls_per_turn
from core.orchestration.tool_budget_text import (
    resolve_current_runtime_max_calls_per_turn,
    resolve_effective_max_calls_per_turn,
)
from core.prompt_manager.sections import (
    make_env_info_section,
    make_spec_digest_section,
)
from core.prompt_manager.types import BuildContext


def _chat_policy() -> ModePolicy:
    return ModePolicy(
        mode=AgentMode.CHAT,
        orchestrator_kind="chat",
        keep_multi_turn_context=True,
        allow_auto_loop=True,
        capture_chat_dataset_candidates=True,
        reset_context_before_turn=False,
        reset_context_between_cases=False,
        allow_direct_supervised_payload=False,
        finish_after_direct_response=False,
        runtime_input_builder=build_chat_user_message,
    )


_BASE_POLICY = {
    "allowedTools": ["cli_tool", "code_symbol_tool", "grep_search_tool"],
    "maxCallsPerTurn": 32,
    "writeScopes": ["private"],
    "mutationAccess": "limited",
}


def _fake_runtime(model: str = "", session_id: str = "", agent: dict | None = None) -> dict:
    runtime: dict = {
        "agentId": "agent-budget-text",
        "turnId": "turn-1",
        "toolPolicy": dict(_BASE_POLICY),
    }
    if model:
        runtime["model"] = model
    if session_id:
        runtime["sessionId"] = session_id
    if agent is not None:
        runtime["agent"] = agent
        runtime["toolPolicy"] = agent.get("toolPolicy") or runtime["toolPolicy"]
    return runtime


def _set_current_runtime(monkeypatch, runtime: dict) -> None:
    from core.web.services import agent_directory_service

    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: dict(runtime))


def _authorization_layer_math(policy: dict, model: str, session_override: int) -> tuple[int, str]:
    """复刻 install_execution_authorization 的优先级数学，作为对照权威。"""

    resolved, family = resolve_max_calls_per_turn(policy, model=model)
    if session_override > 0:
        resolved = session_override
    return resolved, family


def _render_all_surfaces(monkeypatch, runtime: dict) -> dict:
    _set_current_runtime(monkeypatch, runtime)
    policy = dict(_BASE_POLICY)
    packet = build_runtime_goal_packet(
        _chat_policy(),
        "修复预算注入文案口径",
        agent_tool_policy=policy,
    )
    spec_digest = make_spec_digest_section(
        BuildContext(prompt_mode="execute", runtime_goal_packet=packet)
    ).compute()
    env_info = make_env_info_section(Path(".")).compute()
    return {
        "packet": packet,
        "packet_render": packet.render(),
        "spec_digest": spec_digest,
        "env_info": env_info,
    }


def _render_projection_block(tmp_path, monkeypatch, runtime: dict) -> str:
    from core.web.services import agent_directory_service
    from core.web.services.agent_directory import projections

    _set_current_runtime(monkeypatch, runtime)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent_snapshot = {
        "agentId": "agent-budget-text",
        "displayName": "Budget Text",
        "toolPolicy": dict(_BASE_POLICY),
    }
    return projections.build_agent_runtime_context_block(
        "agent-budget-text",
        agent_snapshot=agent_snapshot,
        group_events_snapshot=[],
        inbox_messages_snapshot=[],
        episodic_events_snapshot=[],
        memory_policy_snapshot={"enabled": False},
    )


def test_deepseek_family_text_matches_authorization_resolution(monkeypatch, tmp_path):
    expected, family = _authorization_layer_math(_BASE_POLICY, "deepseek-chat", 0)
    assert expected == 64 and family == "deepseek"

    _set_current_runtime(monkeypatch, _fake_runtime(model="deepseek-chat"))
    resolved, resolved_family = resolve_current_runtime_max_calls_per_turn(_BASE_POLICY)
    assert (resolved, resolved_family) == (expected, family)

    surfaces = _render_all_surfaces(monkeypatch, _fake_runtime(model="deepseek-chat"))
    assert surfaces["packet"].max_calls_per_turn == expected
    assert f"本回合最多 {expected} 次" in surfaces["packet_render"]
    assert f"**{expected}** 次" in surfaces["spec_digest"]
    assert f"本回合 {expected} 次" in surfaces["env_info"]

    block = _render_projection_block(
        tmp_path, monkeypatch, _fake_runtime(model="deepseek-chat")
    )
    assert f"ToolCallBudget: maxCallsPerTurn={expected}" in block
    assert "maxCallsPerTurn=32" not in block


def test_default_family_keeps_policy_base_everywhere(monkeypatch, tmp_path):
    expected, family = _authorization_layer_math(_BASE_POLICY, "mystery-model-v1", 0)
    assert expected == 32 and family == "default"

    surfaces = _render_all_surfaces(monkeypatch, _fake_runtime(model="mystery-model-v1"))
    assert surfaces["packet"].max_calls_per_turn == expected
    assert f"**{expected}** 次" in surfaces["spec_digest"]
    assert f"本回合 {expected} 次" in surfaces["env_info"]
    assert "常见 32 次" not in surfaces["env_info"]
    assert "常见 32 次" not in surfaces["spec_digest"]

    block = _render_projection_block(
        tmp_path, monkeypatch, _fake_runtime(model="mystery-model-v1")
    )
    assert f"ToolCallBudget: maxCallsPerTurn={expected}" in block


def test_session_override_wins_over_family_everywhere(monkeypatch, tmp_path):
    from core.orchestration import session_budget_resolve

    def fake_parameters(session_id: str):
        if session_id == "sess-budget-override":
            return SessionBudgetParameters(maxCallsPerTurn=48)
        return None

    monkeypatch.setattr(
        session_budget_resolve,
        "get_session_budget_parameters",
        fake_parameters,
    )
    runtime = _fake_runtime(
        model="deepseek-chat",
        session_id="sess-budget-override",
        agent={"toolPolicy": dict(_BASE_POLICY), "agentId": "agent-budget-text"},
    )
    expected, family = _authorization_layer_math(_BASE_POLICY, "deepseek-chat", 48)
    assert expected == 48 and family == "deepseek"

    _set_current_runtime(monkeypatch, runtime)
    resolved, resolved_family = resolve_current_runtime_max_calls_per_turn(_BASE_POLICY)
    assert (resolved, resolved_family) == (expected, family)

    surfaces = _render_all_surfaces(monkeypatch, runtime)
    assert surfaces["packet"].max_calls_per_turn == 48
    assert "本回合最多 48 次" in surfaces["packet_render"]
    assert "**48** 次" in surfaces["spec_digest"]
    assert "本回合 48 次" in surfaces["env_info"]
    assert "64 次" not in surfaces["spec_digest"]
    assert "64 次" not in surfaces["env_info"]

    block = _render_projection_block(tmp_path, monkeypatch, runtime)
    assert "ToolCallBudget: maxCallsPerTurn=48" in block
    assert "maxCallsPerTurn=64" not in block


def test_unresolvable_budget_prints_no_number(monkeypatch):
    _set_current_runtime(monkeypatch, {})

    resolved, _family = resolve_current_runtime_max_calls_per_turn()
    assert resolved == 0

    env_info = make_env_info_section(Path(".")).compute()
    assert "以授权层执行为准" in env_info
    assert "常见 32 次" not in env_info

    spec_digest = make_spec_digest_section(
        BuildContext(prompt_mode="orient", runtime_goal_packet=None)
    ).compute()
    assert "以授权层执行为准" in spec_digest
    assert "常见 32 次" not in spec_digest

    packet = build_runtime_goal_packet(
        _chat_policy(),
        "继续",
        agent_tool_policy={"maxCallsPerTurn": 0, "allowedTools": ["web_search_tool"]},
    )
    assert packet.max_calls_per_turn == 0
    assert "常见 32" not in packet.render()


def test_explicit_low_base_stays_as_written_without_identity():
    policy = {"maxCallsPerTurn": 5, "allowedTools": ["cli_tool"]}
    resolved, _family = resolve_effective_max_calls_per_turn(policy)
    assert resolved == 5


def _memo_session_reads(monkeypatch, *, override: int | None) -> dict[str, int]:
    """计数会话覆盖权威解析背后的真实 store 读（chat-state + agent registry）。"""

    from core.web.services import session_service

    reads = {"chat_state": 0, "agent": 0}

    def fake_load(_project_root, session_id, *_args, **_kwargs):
        reads["chat_state"] += 1
        return {"agent_id": "agent-budget-text", "sessionId": session_id}

    def fake_get_agent(agent_id, *_args, **_kwargs):
        reads["agent"] += 1
        metadata = (
            {"sessionBudgetParameters": {"maxCallsPerTurn": override}}
            if override is not None
            else {}
        )
        return {"agentId": agent_id, "metadata": metadata}

    monkeypatch.setattr(session_service, "load_session_chat_state", fake_load)
    monkeypatch.setattr(session_service, "get_agent", fake_get_agent)
    return reads


def _memo_runtime(session_id: str, *, revision: int = 3, config_hash: str = "hash-t1") -> dict:
    runtime = _fake_runtime(
        model="deepseek-chat",
        session_id=session_id,
        agent={"toolPolicy": dict(_BASE_POLICY), "agentId": "agent-budget-text"},
    )
    if revision >= 1 and config_hash:
        runtime["agentConfigSnapshot"] = {
            "configRevision": revision,
            "configHash": config_hash,
        }
    return runtime


def test_session_override_hot_path_serves_repeat_calls_from_memo(monkeypatch):
    """热轮路径：同键二次调用零真实 store 读，终值与首次一致。

    读缓存在每轮 chat-state 写后被 epoch 失效，直查在稳态回合近似每轮
    真实 I/O；prompt 侧会话覆盖读取必须与授权层共用同一份 memo。
    """

    from core.authorization import tool_authorization_service as auth

    auth.clear_session_override_memo()
    try:
        reads = _memo_session_reads(monkeypatch, override=48)
        runtime = _memo_runtime("sess-memo-hot")

        first, family = resolve_effective_max_calls_per_turn(
            dict(_BASE_POLICY), runtime=dict(runtime)
        )
        assert (first, family) == (48, "deepseek")
        assert reads["chat_state"] == 1 and reads["agent"] == 1

        for _ in range(2):
            again, again_family = resolve_effective_max_calls_per_turn(
                dict(_BASE_POLICY), runtime=dict(runtime)
            )
            assert (again, again_family) == (48, "deepseek")
        # 第二次同键调用零读：只允许首次解析的 1 次 chat-state 读 +
        # 1 次 agent registry 读。
        assert reads["chat_state"] == 1 and reads["agent"] == 1
    finally:
        auth.clear_session_override_memo()


def test_session_override_without_snapshot_identity_keeps_direct_read(monkeypatch):
    """无可信快照身份（缺 revision/hash）时不 memo：与直接查询行为等价。"""

    from core.authorization import tool_authorization_service as auth

    auth.clear_session_override_memo()
    try:
        reads = _memo_session_reads(monkeypatch, override=48)
        runtime = _memo_runtime("sess-memo-direct", revision=0, config_hash="")

        for _ in range(3):
            resolved, _family = resolve_effective_max_calls_per_turn(
                dict(_BASE_POLICY), runtime=dict(runtime)
            )
            assert resolved == 48
        assert reads["chat_state"] == 3 and reads["agent"] == 3
    finally:
        auth.clear_session_override_memo()
