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


def test_string_allowed_tools_count_as_one_code_tool_not_characters():
    packet = build_runtime_goal_packet(
        _chat_policy(),
        "审查当前代码结构",
        agent_tool_policy={
            "allowedTools": "grep_search_tool",
            "writeScopes": "private",
            "mutationAccess": "none",
        },
    )
    assert packet.allow_code_context is True
    assert "CODEBASE_MAP" in packet.allowed_components("SOUL,CODEBASE_MAP".split(","))
    assert packet.allowed_components("SOUL") == {"SOUL"}


def test_invalid_max_calls_renders_without_crashing():
    packet = build_runtime_goal_packet(
        _chat_policy(),
        "继续",
        agent_tool_policy={"maxCallsPerTurn": "nope", "allowedTools": ["web_search_tool"]},
    )
    assert packet.max_calls_per_turn == 0
    rendered = packet.render()
    assert "未从策略解析到上限" in rendered


def test_runtime_goal_coerces_json_policy_bytes_goal_and_false_budget():
    packet = build_runtime_goal_packet(
        _chat_policy(),
        b"do not modify files; keep this read-only",
        agent_tool_policy='{"allowed_tools":["web_search_tool"],"write_scopes":[],"mutation_access":"none","max_calls_per_turn":"24"}',
    )
    assert packet.allow_file_writes is False
    assert packet.allow_code_context is False
    assert packet.max_calls_per_turn == 24
    assert packet.goal.startswith("do not modify files")

    bool_budget = build_runtime_goal_packet(
        _chat_policy(),
        "继续",
        agent_tool_policy={"maxCallsPerTurn": True},
    )
    assert bool_budget.max_calls_per_turn == 0

    parsed_list = build_runtime_goal_packet(
        _chat_policy(),
        "审查当前代码结构",
        agent_tool_policy={"allowedTools": '["grep_search_tool"]', "mutationAccess": "none"},
    )
    assert parsed_list.allow_code_context is True
    assert "CODEBASE_MAP" in parsed_list.allowed_components(["SOUL", "CODEBASE_MAP"])


def test_runtime_goal_unwraps_policy_envelopes_and_skips_disabled_tools():
    packet = build_runtime_goal_packet(
        _chat_policy(),
        {"goal": "do not modify files; keep this read-only"},
        agent_tool_policy={
            "policy": {
                "allowedTools": {
                    "items": [
                        {"name": "grep_search_tool", "enabled": False},
                        {"name": "web_search_tool", "enabled": True},
                    ]
                },
                "writeScopes": [],
                "mutationAccess": "none",
                "maxCallsPerTurn": "24",
            }
        },
    )
    assert packet.goal.startswith("do not modify files")
    assert packet.allow_file_writes is False
    assert packet.allow_code_context is False
    assert packet.max_calls_per_turn == 24

    enabled = build_runtime_goal_packet(
        _chat_policy(),
        "审查当前代码结构",
        agent_tool_policy={
            "allowedTools": {"grep_search_tool": {"enabled": False}, "web_search_tool": True},
            "writeScopes": [],
            "mutationAccess": "none",
        },
    )
    assert enabled.allow_code_context is False
    assert "CODEBASE_MAP" not in enabled.allowed_components(
        {"SOUL": True, "CODEBASE_MAP": {"enabled": True}}
    )

    wrapped = build_runtime_goal_packet(
        _chat_policy(),
        '{"goal":"审查当前代码结构"}',
        agent_tool_policy='{"allowed_tools":{"items":["grep_search_tool"]},"mutation_access":"none"}',
    )
    assert wrapped.allow_code_context is True
    assert wrapped.goal == "审查当前代码结构"
    assert "CODEBASE_MAP" not in wrapped.allowed_components(
        {"SOUL": True, "CODEBASE_MAP": {"enabled": False}}
    )
    assert "SOUL" in wrapped.allowed_components(
        {"SOUL": True, "CODEBASE_MAP": {"enabled": False}}
    )
