from __future__ import annotations

import asyncio

from core.web import lifecycle
from tools import Key_Tools, web_search_tool


def test_key_tool_factory_reuses_static_definitions_but_returns_isolated_lists():
    first = Key_Tools.create_key_tools()
    second = Key_Tools.create_key_tools()
    cached = Key_Tools._cached_key_tools()

    assert first is not second
    assert first
    assert [tool.name for tool in first] == [tool.name for tool in second]
    assert [tool.name for tool in first] == [tool.name for tool in cached]
    assert all(left is not right for left, right in zip(first, second, strict=True))
    assert all(
        getattr(left, "func", None) is getattr(right, "func", None)
        for left, right in zip(first, second, strict=True)
    )


def test_llm_tool_filter_rechecks_runtime_availability_with_cached_definitions(monkeypatch):
    monkeypatch.setattr(Key_Tools, "_is_autoglm_search_tool_available", lambda: False)
    unavailable = {tool.name for tool in Key_Tools.create_llm_facing_tools()}
    monkeypatch.setattr(Key_Tools, "_is_autoglm_search_tool_available", lambda: True)
    available = {tool.name for tool in Key_Tools.create_llm_facing_tools()}

    assert "web_search_tool" not in unavailable
    assert "web_search_tool" in available


def test_startup_cache_prewarm_moves_tool_definition_build_out_of_first_turn(monkeypatch):
    calls = []
    monkeypatch.setattr(
        Key_Tools,
        "prewarm_key_tool_definitions",
        lambda: calls.append("tool_definitions"),
        raising=False,
    )
    monkeypatch.setattr(
        web_search_tool,
        "autoglm_search_tool_availability",
        lambda **_kwargs: calls.append("web_search_availability"),
    )
    asyncio.run(lifecycle.prewarm_ui_caches_on_startup())

    assert sorted(calls) == [
        "tool_definitions",
        "web_search_availability",
    ]
