from core.orchestration.agent_modes import AgentMode, ModePolicy
from core.orchestration.runtime_goal import build_runtime_goal_packet
from core.infrastructure.runtime_input import build_chat_user_message


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


def test_research_tool_policy_disables_codebase_map_component():
    packet = build_runtime_goal_packet(
        _chat_policy(),
        "资料搜集阶段任务：搜索神经预测编码资料",
        agent_tool_policy={
            "allowedTools": [
                "agent_message_tool",
                "research_knowledge_query_tool",
                "web_search_tool",
                "batch_web_search_tool",
            ],
            "writeScopes": [],
            "mutationAccess": "none",
        },
    )

    assert packet.allow_file_writes is True
    assert packet.allow_code_context is False
    assert "CODEBASE_MAP" not in packet.allowed_components(["SOUL", "CODEBASE_MAP"])


def test_code_tool_policy_allows_codebase_map_component():
    packet = build_runtime_goal_packet(
        _chat_policy(),
        "审查 prompt 拼接架构和调用链",
        agent_tool_policy={
            "allowedTools": ["grep_search_tool", "code_symbol_tool", "cli_tool"],
            "writeScopes": ["private"],
            "mutationAccess": "limited",
        },
    )

    assert packet.allow_code_context is True
    assert "CODEBASE_MAP" in packet.allowed_components(["SOUL", "CODEBASE_MAP"])


def test_readonly_code_tool_policy_still_allows_codebase_map_component():
    packet = build_runtime_goal_packet(
        _chat_policy(),
        "只读审查当前代码结构",
        agent_tool_policy={
            "allowedTools": ["grep_search_tool", "code_symbol_tool"],
            "writeScopes": [],
            "mutationAccess": "none",
        },
    )

    assert packet.allow_code_context is True
    assert "CODEBASE_MAP" in packet.allowed_components(["SOUL", "CODEBASE_MAP"])


def test_runtime_goal_packet_renders_max_calls_per_turn_budget():
    packet = build_runtime_goal_packet(
        _chat_policy(),
        "修复 shell 路由并跑测试",
        agent_tool_policy={
            "allowedTools": ["cli_tool", "code_symbol_tool", "grep_search_tool"],
            "maxCallsPerTurn": 32,
            "writeScopes": ["private"],
            "mutationAccess": "limited",
        },
    )

    assert packet.max_calls_per_turn == 32
    rendered = packet.render()
    assert "maxCallsPerTurn" in rendered or "本回合最多 32 次" in rendered
    assert "用尽即停" in rendered or "重新计数" in rendered
    assert "code_symbol_tool" in rendered or "grep_search_tool" in rendered
