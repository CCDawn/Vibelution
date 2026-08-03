from __future__ import annotations

from core.orchestration.tool_budget_profiles import (
    detect_model_family,
    resolve_max_calls_per_turn,
)
from core.orchestration.turn_status_bar import (
    TURN_STATUS_BAR_HEADER,
    build_turn_status_bar_message,
    collect_turn_status_snapshot,
    format_turn_status_bar,
    is_turn_status_bar_message,
    strip_turn_status_bar_messages,
    upsert_turn_status_bar_message,
)
from core.runtime_status_flags import (
    default_agent_runtime_status_policy,
    is_runtime_status_inject_enabled,
)
from langchain_core.messages import HumanMessage, SystemMessage


def test_detect_model_family_for_common_vendors():
    assert detect_model_family(model="deepseek-chat") == "deepseek"
    assert detect_model_family(provider="anthropic", model="claude-sonnet") == "claude"
    assert detect_model_family(model="gpt-4.1") == "openai"
    assert detect_model_family(model="unknown-x") == "default"


def test_resolve_max_calls_prefers_family_map():
    max_calls, family = resolve_max_calls_per_turn(
        {
            "maxCallsPerTurn": 32,
            "maxCallsPerTurnByModelFamily": {"deepseek": 64, "default": 32},
        },
        model="deepseek-v3",
    )
    assert family == "deepseek"
    assert max_calls == 64


def test_resolve_max_calls_unlimited_stays_zero():
    max_calls, _ = resolve_max_calls_per_turn({"maxCallsPerTurn": 0}, model="deepseek-chat")
    assert max_calls == 0


def test_turn_status_bar_message_and_upsert():
    snapshot = collect_turn_status_snapshot(
        iteration=2,
        model="deepseek-chat",
        tool_policy={"maxCallsPerTurn": 32, "maxCallsPerTurnByModelFamily": {"deepseek": 64}},
    )
    text = format_turn_status_bar(snapshot)
    assert text.startswith(TURN_STATUS_BAR_HEADER)
    assert "budget_profile: deepseek" in text
    assert "tools:" in text

    message = build_turn_status_bar_message(snapshot)
    assert is_turn_status_bar_message(message)

    messages = [
        SystemMessage(content="stable"),
        HumanMessage(content="hello"),
    ]
    updated = upsert_turn_status_bar_message(messages, message)
    assert len(updated) == 3
    assert is_turn_status_bar_message(updated[1])
    # Second upsert replaces rather than stacks.
    updated_again = upsert_turn_status_bar_message(updated, message)
    assert len(updated_again) == 3
    assert len(strip_turn_status_bar_messages(updated_again)) == 2


def test_runtime_status_default_enabled_with_agent_metadata_off():
    assert is_runtime_status_inject_enabled(agent=None, requested=None) is True
    agent = {
        "metadata": {
            "runtimeStatus": default_agent_runtime_status_policy() | {"enabled": False},
        }
    }
    assert is_runtime_status_inject_enabled(agent=agent, requested=True) is False
    assert is_runtime_status_inject_enabled(agent=None, requested=False) is False
