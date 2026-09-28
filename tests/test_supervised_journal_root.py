# -*- coding: utf-8 -*-
"""Regression: conversation summaries must load turn journals from the owning project root.

复跑/自改的 harness ``repo_root`` 是候选 worktree；按 worktree 根解析
turn journal 会落到另一个实例 workspace（worktree 缺主 checkout 的实例
身份），读不到任何工具事件——证据包变成零工具轨迹，Judge 只能按缺证
判罚（swte-38cfc2b63358：复跑会话 306 个工具调用，Judge 看到 0 个）。
修复后 journal 解析使用主项目根（``journal_project_root``）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.web.services import supervised_conversation_harness_adapter as adapter


def _fake_journal_event(name: str = "open_evolution_transaction_tool") -> SimpleNamespace:
    return SimpleNamespace(
        event_type="tool_result",
        payload={"toolCall": {"name": name, "status": "done", "arguments": {}}},
        timestamp="2026-09-18T00:00:00+00:00",
        sequence=1,
        event_id="e1",
    )


def test_evolution_summary_resolves_journal_from_given_root(
    monkeypatch,
) -> None:
    called_roots: list[Path] = []
    monkeypatch.setattr(
        adapter,
        "load_turn_events",
        lambda root, session_id: called_roots.append(Path(root)) or [],
    )
    detail = {"id": "session-journal-probe"}

    adapter._conversation_harness_evolution_summary(
        detail,
        assistant_text="done",
        restart_expected=False,
        repo_root=Path(r"C:\fake\main-root"),
    )

    assert called_roots == [Path(r"C:\fake\main-root")]


def test_journal_tool_events_reach_tool_trace(monkeypatch) -> None:
    monkeypatch.setattr(
        adapter,
        "load_turn_events",
        lambda root, session_id: [_fake_journal_event()],
    )
    detail = {"id": "session-journal-probe"}

    summary = adapter._conversation_harness_evolution_summary(
        detail,
        assistant_text="done",
        restart_expected=False,
        repo_root=Path(r"C:\fake\main-root"),
    )

    trace = summary.get("tool_trace") or []
    assert any(
        str(item.get("toolName") or "") == "open_evolution_transaction_tool"
        for item in trace
        if isinstance(item, dict)
    )
