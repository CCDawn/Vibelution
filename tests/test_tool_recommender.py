#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from core.infrastructure.tool_recommender import decide_next_tools
from core.infrastructure.tool_intents import TOOL_INTENTS, get_tool_intent, humanize_tool_name
from tools.Key_Tools import create_llm_facing_tools

LEGACY_AGENT_TOOL_NAMES = {
    "read_file",
    "list_directory",
    "check_python_syntax",
    "create_file",
    "execute_shell_command",
    "run_powershell",
    "run_batch",
    "find_definitions_tool",
    "find_function_calls_tool",
    "get_file_entities",
    "get_file_entities_tool",
    "list_file_entities_tool",
    "get_code_entity_tool",
    "python_symbol_tool",
}


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


def test_locate_defaults_to_search_then_symbol():
    decision = decide_next_tools({
        "reading_task": "locate",
        "reading_sufficiency": "",
        "read_ranges": {},
        "read_entities": {},
        "read_searches": [],
        "recent_blockers": [],
        "recent_validation_results": [],
    })

    assert decision.next_intent == "locate_text"
    assert "grep_search_tool" in decision.recommended_tools
    assert "cli_tool" in decision.avoid_tools


def test_tool_intents_recommend_only_llm_facing_canonical_tools(monkeypatch):
    _bind_visible_tools(monkeypatch, {tool.name for tool in create_llm_facing_tools()})

    visible_names = {tool.name for tool in create_llm_facing_tools()}
    for name in TOOL_INTENTS:
        intent = get_tool_intent(name)
        assert intent is not None
        recommended = set(intent.recommended_tools)
        assert not (recommended & LEGACY_AGENT_TOOL_NAMES)
        assert recommended <= visible_names



    for legacy_name in LEGACY_AGENT_TOOL_NAMES:
        assert humanize_tool_name(legacy_name) == legacy_name


def test_pending_continuation_guides_target_selection_without_forcing_range_read():
    decision = decide_next_tools({
        "reading_task": "analyze",
        "reading_sufficiency": "",
        "read_ranges": {},
        "read_entities": {},
        "read_searches": [{"query": "Demo", "scope": "core"}],
        "recent_blockers": [{"kind": "partial_read", "summary": "需要补读"}],
        "recent_validation_results": [],
        "pending_continuations": [
            {
                "tool_name": "grep_search_tool",
                "hint": 'read_file_tool(file_path="core/demo.py", offset=0, max_lines=80)',
                "path": "core/demo.py",
            }
        ],
    })

    assert decision.next_intent == "choose_read_target"
    assert "grep_search_tool" in decision.recommended_tools
    assert "code_symbol_tool" in decision.recommended_tools
    assert "read_file_tool" not in decision.recommended_tools
    assert "read_file_tool" in decision.avoid_tools
    assert "cli_tool" in decision.avoid_tools
    assert "core/demo.py" in decision.reason


def test_locate_synthesizes_after_search_and_detail():
    decision = decide_next_tools({
        "reading_task": "locate",
        "reading_sufficiency": "定位证据已初步足够，可综合判断、转入修改或明确缺口。",
        "read_ranges": {"core/demo.py": [{"start_line": 10, "end_line": 40}]},
        "read_entities": {},
        "read_searches": [{"query": "Demo", "scope": "core"}],
        "recent_blockers": [],
        "recent_validation_results": [],
        "pending_continuations": [],
    })

    assert decision.next_intent == "synthesize_answer"
    assert decision.recommended_tools == []
    assert "read_file_tool" in decision.avoid_tools


def test_duplicate_read_redirects_to_synthesis():
    decision = decide_next_tools({
        "reading_task": "analyze",
        "reading_sufficiency": "读取没有新增证据；现有证据可形成结论或明确缺口，不要继续顺序读取。",
        "read_ranges": {"core/demo.py": [{"start_line": 10, "end_line": 40}]},
        "read_entities": {},
        "read_searches": [{"query": "Demo", "scope": "core"}],
        "recent_blockers": [{"kind": "duplicate_read_soft_redirect", "summary": "重复读取"}],
        "recent_validation_results": [],
        "pending_continuations": [],
    })

    assert decision.next_intent == "synthesize_answer"
    assert decision.recommended_tools == []
    assert "read_file_tool" in decision.avoid_tools


def test_modify_switches_to_edit_when_sufficient():
    decision = decide_next_tools({
        "reading_task": "modify",
        "reading_sufficiency": "修改上下文已足够，可开始动手并保留验证闭环。",
        "read_ranges": {"a.py": [{"start_line": 1, "end_line": 20}]},
        "read_entities": {"a.py": ["Foo.run"]},
        "read_searches": [],
        "recent_blockers": [],
        "recent_validation_results": [],
        "pending_continuations": [],
    })

    assert decision.next_intent == "edit_target"
    assert "apply_diff_edit_tool" in decision.recommended_tools
    assert "read_file_tool" in decision.avoid_tools
