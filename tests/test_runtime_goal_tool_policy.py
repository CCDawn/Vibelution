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
