#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from core.infrastructure.reading_strategy import build_reading_strategy
from core.infrastructure.tool_intents import get_tool_intent
from core.infrastructure.tool_recommender import decide_next_tools
from tools.search_tools import grep_search_tool


def _bind_visible_tools(monkeypatch, visible_tools):
    from core.web.services import agent_directory_service

    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": "agent-test"},
    )
    monkeypatch.setattr(
        agent_directory_service,
        "effective_visible_tool_names_for_current_agent",
        lambda _tools=None: list(visible_tools),
    )


def test_search_result_guidance_does_not_hardcode_read_tools(tmp_path):
    target = tmp_path / "demo.py"
    target.write_text("def demo():\n    return 'needle'\n", encoding="utf-8")

    result = grep_search_tool("needle", ".py", str(tmp_path))

    assert "[搜索] 阅读策略:" in result
    assert "read_file_tool" not in result
    assert "code_symbol_tool" not in result


def test_reading_strategy_filters_tools_hidden_by_current_agent(monkeypatch):
    _bind_visible_tools(monkeypatch, ["run_test_for_tool", "python_lint_tool"])

    strategy = build_reading_strategy("pytest failed with traceback")

    assert strategy.task_type == "verify"
    assert strategy.recommended_tools == ["python_lint_tool"]


def test_tool_recommender_filters_recommendations_and_fallbacks(monkeypatch):
    _bind_visible_tools(monkeypatch, ["run_test_for_tool", "python_lint_tool", "cli_tool"])

    decision = decide_next_tools(
        {
            "reading_task": "verify",
            "reading_sufficiency": "",
            "read_ranges": {},
            "read_entities": {},
            "read_searches": [],
            "recent_blockers": [],
            "recent_validation_results": [{"status": "failed"}],
            "pending_continuations": [],
        }
    )

    assert decision.recommended_tools == ["run_test_for_tool"]
    assert decision.avoid_tools == ["cli_tool"]
    assert decision.fallback_if_failed == ["python_lint_tool"]


def test_tool_intent_filters_hidden_range_reader(monkeypatch):
    _bind_visible_tools(monkeypatch, ["cli_tool"])

    intent = get_tool_intent("inspect_range")

    assert intent is not None
    assert intent.recommended_tools == []

