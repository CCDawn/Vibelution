#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from core.infrastructure.reading_strategy import build_reading_strategy
from core.infrastructure.tool_intents import get_tool_intent
from tools.search_tools import grep_search_tool


def _bind_visible_tools(monkeypatch, visible_tools):
    from types import SimpleNamespace
    from core.authorization import tool_authorization_service
    from core.web.services import agent_directory_service

    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": "agent-test", "turnId": "turn-test", "toolPolicy": {}},
    )
    tool_authorization_service.install_execution_authorization(
        SimpleNamespace(decision=SimpleNamespace(
            agent_id="agent-test",
            turn_id="turn-test",
            decision_fingerprint="decision-test",
            executable_tools=tuple(visible_tools),
        ))
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


def test_tool_intent_filters_hidden_range_reader(monkeypatch):
    _bind_visible_tools(monkeypatch, ["cli_tool"])

    intent = get_tool_intent("inspect_range")

    assert intent is not None
    assert intent.recommended_tools == []
