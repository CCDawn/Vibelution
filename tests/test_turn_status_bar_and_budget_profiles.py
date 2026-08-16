from __future__ import annotations

from core.orchestration.tool_budget_profiles import (
    detect_model_family,
    normalize_max_calls_by_model_family,
    resolve_max_calls_per_turn,
)
from core.orchestration.turn_status_bar import (
    TURN_STATUS_BAR_HEADER,
    build_turn_status_bar_message,
    collect_turn_status_snapshot,
    collect_turn_status_tail_extras,
    format_turn_status_bar,
    is_turn_status_bar_message,
    strip_turn_status_bar_messages,
    upsert_turn_status_bar_message,
)
from core.runtime_status_flags import (
    default_agent_runtime_status_policy,
    is_runtime_status_enabled,
    is_runtime_status_inject_enabled,
    is_runtime_status_rail_enabled,
    runtime_status_enabled_override,
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


def test_budget_profiles_coerce_bytes_case_and_snake_case():
    assert detect_model_family(model=b"deepseek-chat") == "deepseek"
    max_calls, family = resolve_max_calls_per_turn(
        {
            "maxCallsPerTurn": "32",
            "maxCallsPerTurnByModelFamily": {"DeepSeek": 80},
        },
        model=b"deepseek-v3",
    )
    assert family == "deepseek"
    assert max_calls == 80
    snake_calls, _ = resolve_max_calls_per_turn(
        {"max_calls_per_turn": "16"},
        model="gpt-4.1",
    )
    assert snake_calls == 16
    assert normalize_max_calls_by_model_family('{"Claude": "40"}') == {"claude": 40}
    bool_calls, _ = resolve_max_calls_per_turn({"maxCallsPerTurn": True}, model="gpt-4.1")
    assert bool_calls == 0


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
    # Status bar must trail the user/tool path so DeepSeek prefix cache can grow.
    assert is_turn_status_bar_message(updated[-1])
    assert not is_turn_status_bar_message(updated[1])
    # Second upsert replaces rather than stacks.
    updated_again = upsert_turn_status_bar_message(updated, message)
    assert len(updated_again) == 3
    assert is_turn_status_bar_message(updated_again[-1])
    assert len(strip_turn_status_bar_messages(updated_again)) == 2


def test_turn_status_bar_trails_tool_messages_for_prefix_cache():
    """Changing status bar must not sit between history and growing tool trail."""
    from langchain_core.messages import AIMessage, ToolMessage

    bar1 = build_turn_status_bar_message(
        collect_turn_status_snapshot(iteration=1, model="deepseek-chat", tool_policy={"maxCallsPerTurn": 8})
    )
    bar2 = build_turn_status_bar_message(
        collect_turn_status_snapshot(iteration=2, model="deepseek-chat", tool_policy={"maxCallsPerTurn": 8})
    )
    base = [
        SystemMessage(content="stable system"),
        HumanMessage(content="do relations"),
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "source_collection_context_tool", "args": {}}]),
        ToolMessage(content="page0", tool_call_id="c1"),
    ]
    step1 = upsert_turn_status_bar_message(base, bar1)
    # Pure-append tool step then rewrite status: common prefix must include tools.
    step2_msgs = list(strip_turn_status_bar_messages(step1)) + [
        AIMessage(content="", tool_calls=[{"id": "c2", "name": "source_collection_context_tool", "args": {}}]),
        ToolMessage(content="page1", tool_call_id="c2"),
    ]
    step2 = upsert_turn_status_bar_message(step2_msgs, bar2)
    assert is_turn_status_bar_message(step2[-1])
    # Everything except the final status bar is a pure prefix of step2 without bar.
    body1 = strip_turn_status_bar_messages(step1)
    body2 = strip_turn_status_bar_messages(step2)
    assert body2[: len(body1)] == body1
    assert len(body2) == len(body1) + 2


def test_runtime_status_default_enabled_with_agent_metadata_off():
    assert is_runtime_status_inject_enabled(agent=None, requested=None) is True
    agent = {
        "metadata": {
            "runtimeStatus": default_agent_runtime_status_policy() | {"enabled": False},
        }
    }
    assert is_runtime_status_inject_enabled(agent=agent, requested=True) is False
    assert is_runtime_status_inject_enabled(agent=None, requested=False) is False


def test_runtime_status_coerces_bytes_false_json_and_snake_case():
    empty = {}
    assert is_runtime_status_inject_enabled(
        public_config=empty,
        agent={"metadata": {"runtimeStatus": {"enabled": b"false"}}},
    ) is False
    assert is_runtime_status_enabled(
        public_config=empty,
        agent={"metadata": {"runtime_status": {"enabled": "off"}}},
    ) is False
    agent = {
        "runtimeStatus": '{"enabled": true, "injectIntoModel": "false", "showInStatusRail": true}',
    }
    assert is_runtime_status_enabled(public_config=empty, agent=agent) is True
    assert is_runtime_status_inject_enabled(public_config=empty, agent=agent) is False
    assert is_runtime_status_rail_enabled(public_config=empty, agent=agent) is True
    assert is_runtime_status_inject_enabled(public_config=empty, requested="false") is False
    assert is_runtime_status_inject_enabled(public_config=empty, requested=b"off") is False
    with runtime_status_enabled_override("false"):
        assert is_runtime_status_inject_enabled(public_config=empty) is False
    with runtime_status_enabled_override(b"false"):
        assert is_runtime_status_inject_enabled(public_config=empty) is False
    assert is_runtime_status_enabled(
        public_config=empty,
        agent={"metadata": '{"runtimeStatus": {"enabled": false}}'},
    ) is False



def test_collect_snapshot_prefers_live_auth_cap_and_current_model_family():
    from types import SimpleNamespace

    auth = SimpleNamespace(
        max_calls_per_turn=8,
        call_count=6,
        budget_profile="openai",
        turn_id="turn-live",
        agent_id="agent-live",
    )
    snapshot = collect_turn_status_snapshot(
        iteration=3,
        model="deepseek-chat",
        tool_policy={"maxCallsPerTurn": 64, "maxCallsPerTurnByModelFamily": {"deepseek": 64}},
        authorization=auth,
    )
    assert snapshot.tools_max == 8
    assert snapshot.tools_used == 6
    assert snapshot.tools_remaining == 2
    assert snapshot.budget_profile == "deepseek"
    assert snapshot.budget_status == "tight"
    assert snapshot.turn_id == "turn-live"
    text = format_turn_status_bar(snapshot)
    assert "budget_status: tight" in text
    assert "budget tight" in text


def test_collect_snapshot_marks_exhausted_and_unlimited():
    from types import SimpleNamespace

    exhausted = collect_turn_status_snapshot(
        model="gpt-4.1",
        authorization=SimpleNamespace(max_calls_per_turn=4, call_count=4, budget_profile="openai"),
    )
    assert exhausted.budget_status == "exhausted"
    assert "budget exhausted" in format_turn_status_bar(exhausted)

    unlimited = collect_turn_status_snapshot(
        model="gpt-4.1",
        tool_policy={"maxCallsPerTurn": 0},
        authorization=None,
    )
    assert unlimited.tools_max == 0
    assert unlimited.budget_status == "unlimited"

    ok = collect_turn_status_snapshot(
        model="gpt-4.1",
        authorization=SimpleNamespace(max_calls_per_turn=32, call_count=1, budget_profile="openai"),
    )
    assert ok.budget_status == "ok"
    assert "prefer structured tools" in format_turn_status_bar(ok)


def test_collect_snapshot_coerces_invalid_auth_counters():
    from types import SimpleNamespace

    snapshot = collect_turn_status_snapshot(
        iteration="nope",
        model="deepseek-chat",
        authorization=SimpleNamespace(
            max_calls_per_turn="bad",
            call_count="also-bad",
            budget_profile="deepseek",
        ),
    )
    assert snapshot.iteration == 0
    assert snapshot.tools_used == 0
    assert snapshot.tools_max == 0
    assert snapshot.budget_status == "unlimited"


def test_status_bar_coerces_false_flags_json_extras_and_rejects_character_split():
    from types import SimpleNamespace

    snapshot = collect_turn_status_snapshot(
        iteration=b"3",
        model=b"deepseek-chat",
        tool_policy='{"maxCallsPerTurn":"8"}',
        mental_enabled="false",
        mental_model=SimpleNamespace(diagnose=lambda: SimpleNamespace(state="anxious", intervention="stop")),
        authorization=SimpleNamespace(
            max_calls_per_turn=b"8",
            call_count=b"1",
            budget_profile=b"deepseek",
            turn_id=b"turn-1",
            agent_id=b"agent-1",
        ),
    )
    assert snapshot.iteration == 3
    assert snapshot.model == "deepseek-chat"
    assert snapshot.mental_enabled is False
    assert snapshot.turn_id == "turn-1"
    assert snapshot.tools_max == 8

    extras = {
        "git": {
            "available": "true",
            "dirty": "false",
            "branch": b"main",
            "upstream": {"ahead": "2", "behind": "bad"},
        },
        "runDigest": {"task": b"fix", "recentTools": "grep_search_tool"},
        "identity": {"sessionId": b"session-1"},
    }
    text = format_turn_status_bar(
        snapshot,
        config={
            "blocks": {
                "budget": True,
                "clock": False,
                "git_brief": True,
                "run_digest": True,
                "identity": True,
            }
        },
        extras=extras,
    )
    assert "dirty: no" in text
    assert "ahead_behind: +2/-0" in text
    assert "recent_tools: grep_search_tool" in text
    assert "session: session-1" in text

    assert strip_turn_status_bar_messages("not-a-list") == []
    extras_payload = collect_turn_status_tail_extras(
        session_id=b"s1",
        recent_tools="cli_tool",
        include_git="false",
        cache_hint='{"cacheReadTokens": 12}',
    )
    assert extras_payload["runDigest"]["recentTools"] == ["cli_tool"]
    assert extras_payload["cacheHint"]["cacheReadTokens"] == 12
    assert "git" not in extras_payload
