# -*- coding: utf-8 -*-
"""Tests for composer next-prompt suggestions (prompt-suggestion fork)."""

from __future__ import annotations

import types

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.llm.payload_builder import (
    PayloadPolicyActions,
    _apply_anthropic_explicit_prompt_cache_markers,
    _select_qwen_prompt_cache_marker_index,
)
from core.llm.turn_request_capture import (
    PROMPT_CACHE_INHERITED_COUNT_METADATA_KEY,
    capture_turn_provider_message_count,
    capture_turn_request,
    record_turn_request_outcome,
    turn_request_capture_scope,
)
from core.llm.types import UsageStats
from core.web.services.session import composer_example_commands, prompt_suggestion


@pytest.fixture(autouse=True)
def _clean_registry():
    with prompt_suggestion._CAPTURE_LOCK:
        prompt_suggestion._CAPTURES.clear()
    yield
    with prompt_suggestion._CAPTURE_LOCK:
        prompt_suggestion._CAPTURES.clear()


def _parent_context(partition: str = "chat-agent-static-abc123") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        surface="chat_turn",
        agent_id="agent-1",
        llm_slot="dialogue",
        model_id="model-1",
        cache_scope="session_dialogue",
        cache_partition=partition,
    )


def _register(
    *,
    session_id: str = "session-1",
    turn_id: str = "turn-2",
    partition: str = "chat-agent-static-abc123",
    provider_count: int = 5,
    usage: UsageStats | None = None,
    reply: str = "修好了，测试也过了。",
    outcome_kind: str = "final_answer",
) -> dict:
    capture = {
        "client": object(),
        "messages": [
            SystemMessage(content="system"),
            HumanMessage(content="帮我修这个 bug"),
            AIMessage(content="已修复"),
        ],
        "invocationContext": _parent_context(partition),
        "providerMessageCount": provider_count,
        "usage": usage,
        "outcomeKind": outcome_kind,
    }
    prompt_suggestion.register_prompt_suggestion_capture(
        session_id=session_id,
        turn_id=turn_id,
        capture=capture,
        reply=reply,
    )
    return capture


def _install_fake_invoke(monkeypatch, text: str = "跑一下测试"):
    calls: list[dict] = []

    def fake_invoke(client, messages, *, context, **kwargs):
        calls.append({"client": client, "messages": list(messages), "context": context})
        if isinstance(text, Exception):
            raise text
        return types.SimpleNamespace(final_text=text, kind="final_answer")

    monkeypatch.setattr(prompt_suggestion, "invoke_llm_outcome", fake_invoke)
    return calls


def test_turn_request_capture_scope_collects_last_request():
    collector: dict = {}
    with turn_request_capture_scope(collector):
        capture_turn_request("client-1", ["a"])
        capture_turn_request("client-2", ["b", "c"])
        capture_turn_provider_message_count(7)
        record_turn_request_outcome(
            types.SimpleNamespace(
                kind="final_answer",
                events=(
                    types.SimpleNamespace(usage="u1"),
                    types.SimpleNamespace(usage="u2"),
                ),
            )
        )
    assert collector["client"] == "client-2"
    assert collector["messages"] == ["b", "c"]
    assert collector["providerMessageCount"] == 7
    assert collector["usage"] == "u2"
    assert collector["outcomeKind"] == "final_answer"

    capture_turn_request("client-3", ["d"])
    assert collector["client"] == "client-2"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", "empty"),
        ("done", "done"),
        ("No suggestion", "meta_text"),
        ("我没有建议", "meta_text"),
        ("(silence — nothing obvious)", "meta_wrapped"),
        ("[no suggestion]", "meta_wrapped"),
        ("建议：跑测试", "prefixed_label"),
        ("是", ""),
        ("继续", ""),
        ("/continue", ""),
        ("跑", "too_few_words"),
        ("a b c d e f g h i j k l m", "too_many_words"),
        ("x" * 99 + " y", "too_long"),
        ("跑测试。然后提交", "multiple_sentences"),
        ("有 **markdown**", "has_formatting"),
        ("看起来不错", "evaluative"),
        ("让我来修复", "claude_voice"),
        ("跑一下测试", ""),
        ("提交并推送", ""),
    ],
)
def test_suggestion_suppression_reason(text, expected):
    assert prompt_suggestion.suggestion_suppression_reason(text) == expected


def test_clean_prompt_suggestion_strips_wrapping_and_whitespace():
    assert prompt_suggestion.clean_prompt_suggestion('"跑一下测试"') == "跑一下测试"
    assert prompt_suggestion.clean_prompt_suggestion("  多行\n文本  ") == "多行 文本"
    assert prompt_suggestion.clean_prompt_suggestion(None) == ""


def test_generate_prompt_suggestion_forks_parent_request(monkeypatch):
    _register(usage=UsageStats(input_tokens=5_000, cached_input_tokens=4_000, output_tokens=200))
    calls = _install_fake_invoke(monkeypatch, "跑一下测试")
    monkeypatch.setattr(prompt_suggestion, "_assistant_turn_count", lambda _sid: 2)

    result = prompt_suggestion.generate_prompt_suggestion("session-1", after_turn_id="turn-2")

    assert result["suggestion"] == "跑一下测试"
    assert result["reason"] == "ok"
    assert len(calls) == 1
    call = calls[0]
    assert len(call["messages"]) == 5
    assert isinstance(call["messages"][-2], AIMessage)
    assert isinstance(call["messages"][-1], HumanMessage)
    assert "SUGGESTION MODE" in call["messages"][-1].content
    context = call["context"]
    assert context.cache_partition == "chat-agent-static-abc123"
    assert context.prompt_purpose == "main_reply"
    assert context.surface == "chat_turn"
    assert context.metadata[PROMPT_CACHE_INHERITED_COUNT_METADATA_KEY] == 5
    assert context.conversation_bound is True

    cached = prompt_suggestion.generate_prompt_suggestion("session-1", after_turn_id="turn-2")
    assert cached["suggestion"] == "跑一下测试"
    assert cached["reason"] == "ok"
    assert len(calls) == 1


def test_generate_prompt_suggestion_guards(monkeypatch):
    calls = _install_fake_invoke(monkeypatch, "跑一下测试")
    monkeypatch.setattr(prompt_suggestion, "_assistant_turn_count", lambda _sid: 2)

    assert prompt_suggestion.generate_prompt_suggestion("missing")["reason"] == "no_capture"

    _register(turn_id="turn-2")
    assert (
        prompt_suggestion.generate_prompt_suggestion("session-1", after_turn_id="turn-x")["reason"]
        == "stale_turn"
    )

    prompt_suggestion.clear_prompt_suggestion_capture("session-1")
    _register(usage=UsageStats(input_tokens=20_000, output_tokens=100))
    assert prompt_suggestion.generate_prompt_suggestion("session-1", after_turn_id="turn-2")["reason"] == "cache_cold"

    prompt_suggestion.clear_prompt_suggestion_capture("session-1")
    _register()
    assert (
        prompt_suggestion.generate_prompt_suggestion("session-1", after_turn_id="turn-2")["reason"]
        == "ok"
    )
    assert len(calls) == 1


def test_generate_prompt_suggestion_filters_and_failures(monkeypatch):
    monkeypatch.setattr(prompt_suggestion, "_assistant_turn_count", lambda _sid: 2)

    _install_fake_invoke(monkeypatch, "看起来不错")
    _register()
    result = prompt_suggestion.generate_prompt_suggestion("session-1", after_turn_id="turn-2")
    assert result["suggestion"] is None
    assert result["reason"] == "filtered:evaluative"

    prompt_suggestion.clear_prompt_suggestion_capture("session-1")
    _install_fake_invoke(monkeypatch, RuntimeError("boom"))
    _register()
    failed = prompt_suggestion.generate_prompt_suggestion("session-1", after_turn_id="turn-2")
    assert failed["suggestion"] is None
    assert failed["reason"] == "generation_failed"

    prompt_suggestion.clear_prompt_suggestion_capture("session-1")
    _install_fake_invoke(monkeypatch, "跑一下测试")
    _register(outcome_kind="incomplete")
    assert (
        prompt_suggestion.generate_prompt_suggestion("session-1", after_turn_id="turn-2")["reason"]
        == "incomplete_turn"
    )

    prompt_suggestion.clear_prompt_suggestion_capture("session-1")
    _install_fake_invoke(monkeypatch, "跑一下测试")
    _register(reply="")
    assert (
        prompt_suggestion.generate_prompt_suggestion("session-1", after_turn_id="turn-2")["reason"]
        == "empty_reply"
    )


def test_generate_prompt_suggestion_early_conversation(monkeypatch):
    _install_fake_invoke(monkeypatch, "跑一下测试")
    monkeypatch.setattr(prompt_suggestion, "_assistant_turn_count", lambda _sid: 1)
    _register()
    result = prompt_suggestion.generate_prompt_suggestion("session-1", after_turn_id="turn-2")
    assert result["reason"] == "early_conversation"


def _message_cache_marker_count(message: dict) -> int:
    from core.llm.payload_builder import _message_cache_marker_count as counter

    return counter(message)


def test_anthropic_markers_stay_inside_inherited_prefix():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "第一答"},
        {"role": "user", "content": "第二问"},
        {"role": "assistant", "content": "第二答"},
        {"role": "user", "content": "SUGGESTION MODE"},
    ]
    actions = PayloadPolicyActions()
    actions.prompt_cache_provider_strategy = "anthropic_explicit_cache_control"

    inherited = _apply_anthropic_explicit_prompt_cache_markers(
        messages,
        actions,
        candidate_end=5,
    )
    assert [
        index for index, message in enumerate(inherited) if _message_cache_marker_count(message)
    ] == [0, 2]

    plain = _apply_anthropic_explicit_prompt_cache_markers(messages, actions)
    assert [
        index for index, message in enumerate(plain) if _message_cache_marker_count(message)
    ] == [0, 4]


def test_qwen_marker_selection_uses_inherited_prefix():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "第一答"},
        {"role": "user", "content": "第二问"},
        {"role": "assistant", "content": "第二答"},
        {"role": "user", "content": "SUGGESTION MODE"},
    ]
    assert _select_qwen_prompt_cache_marker_index(messages, candidate_end=5) == (
        _select_qwen_prompt_cache_marker_index(messages[:5])
    )
    assert _select_qwen_prompt_cache_marker_index(messages) == 4


def test_pick_diverse_core_files_skips_non_core_and_spreads_dirs():
    paths = [
        "src/a.py",
        "src/b.py",
        "src/c.py",
        "web/x.ts",
        "web/y.ts",
        "README.md",
        "package-lock.json",
    ]
    assert composer_example_commands.pick_diverse_core_files(paths, 4) == [
        "a.py",
        "x.ts",
        "b.py",
        "y.ts",
    ]
    assert composer_example_commands.pick_diverse_core_files(["src/a.py"], 2) == []


def test_build_example_command_handles_missing_files():
    for _ in range(20):
        command = composer_example_commands.build_example_command([])
        assert command
        assert "{file}" not in command
    for _ in range(20):
        command = composer_example_commands.build_example_command(["agent.py"])
        assert command
        assert "{file}" not in command


def test_example_command_cache_reuses_git_scan(tmp_path, monkeypatch):
    calls = {"count": 0}

    def fake_frequently_modified(_root):
        calls["count"] += 1
        return ["agent.py"]

    monkeypatch.setattr(
        composer_example_commands,
        "frequently_modified_core_files",
        fake_frequently_modified,
    )
    composer_example_commands.reset_composer_example_cache()
    first = composer_example_commands.get_composer_example_command(tmp_path)
    second = composer_example_commands.get_composer_example_command(tmp_path)
    assert first and first == second
    assert calls["count"] == 1


def test_prompt_suggestion_route_reports_skip_reason(monkeypatch):
    from core.web.routes import sessions as session_routes

    result = session_routes.session_prompt_suggestion(
        "session-unknown",
        session_routes.SessionPromptSuggestionPayload(),
    )
    assert result["sessionId"] == "session-unknown"
    assert result["suggestion"] is None
    assert result["reason"] == "no_capture"


def test_composer_example_route_uses_current_project_root(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from core.web.routes import sessions as session_routes
    from core.web.services import session_service

    monkeypatch.setattr(session_routes, "get_session_detail", lambda *args, **kwargs: {})
    seen: list = []
    monkeypatch.setattr(
        session_routes,
        "get_composer_example_command",
        lambda root: seen.append(root) or "帮我修一下 {file}",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    assert session_routes.session_composer_example("session-1") == {"command": "帮我修一下 {file}"}
    assert seen == [tmp_path]

    def missing_session(*args, **kwargs):
        raise session_service.SessionNotFoundError("session not found")

    monkeypatch.setattr(session_routes, "get_session_detail", missing_session)
    with pytest.raises(HTTPException) as exc_info:
        session_routes.session_composer_example("missing")
    assert exc_info.value.status_code == 404
