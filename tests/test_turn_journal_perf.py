# -*- coding: utf-8 -*-
"""性能与回归测试：turn_journal 写入路径优化（阶段 1）。

覆盖：
1. fsync 分级：易失事件（VOLATILE_MODEL_EVENT_TYPES）不再触发 os.fsync
2. terminal 检查缓存：追加事件不再对每个事件全文件扫描
3. mkdir 去重：同一 journal 父目录只 mkdir 一次
4. 行为回归：terminal 后追加 POST_TERMINAL 事件仍抛 ValueError；
   rewrite 失效缓存后允许再次追加
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.infrastructure import developer_sandbox
from core.chat import turn_journal
from core.chat.turn_journal import (
    EVENT_ASSISTANT_PARTIAL,
    EVENT_TOOL_RESULT,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    append_turn_event,
)


def _projection_event(sequence, event_type, *, event_id=None, turn_id="turn", payload=None):
    return turn_journal.TurnJournalEvent.from_dict({
        "eventId": event_id or f"event-{sequence}", "sessionId": "session", "turnId": turn_id,
        "sequence": sequence, "eventType": event_type, "status": "completed",
        "timestamp": f"2026-10-22T00:00:{sequence:02d}Z", "payload": payload or {},
    })


@pytest.mark.parametrize("operation", ["edit", "regenerate", "head_select"])
@pytest.mark.parametrize("duplicate_sequence", [False, True])
def test_detail_active_projection_matches_raw_entry_points(operation, duplicate_sequence, monkeypatch):
    from core.web.services.session import projection, turn_steer
    from core.web.services import session_service

    events = [
        _projection_event(1, "user_message"),
        _projection_event(2, "assistant_item_committed", payload={
            "kind": "tool_call", "itemId": "tool", "callId": "call", "status": "ready",
            "metadata": {"nested": {"value": "original"}},
        }),
        _projection_event(3, "tool_call_started", payload={"toolCall": {"callId": "call"}}),
        _projection_event(4, "turn_steer", payload={
            "disposition": "display_item_started", "itemId": "answer", "kind": "agent_message",
            "contentOffset": 3, "projectionItemId": "alias",
        }),
        _projection_event(5, "assistant_item_committed", payload={
            "kind": "assistant_message", "itemId": "answer", "text": "original",
        }),
        _projection_event(6, "tool_result", payload={
            "toolCall": {"callId": "call", "status": "done", "summary": "result"},
        }),
        _projection_event(7, "turn_completed"),
        _projection_event(8, "branch_rebase", payload={
            "operation": "edit", "fromEventId": "event-3", "branchId": "other",
        }),
        _projection_event(9, "assistant_item_committed", payload={
            "kind": "assistant_message", "itemId": "alternative", "text": "alternative",
        }),
        _projection_event(10, "branch_rebase", payload={
            "operation": operation, "fromEventId": "event-7" if operation == "head_select" else "event-3",
        }),
        _projection_event(11, "turn_failed"),
        _projection_event(12, "turn_steer", payload={
            "disposition": "display_content_rebased", "itemId": "answer",
        }),
    ]
    if duplicate_sequence:
        # The two public entry points deliberately have distinct tie ordering.
        events[4] = _projection_event(4, "assistant_item_committed", event_id="a-tied", payload={
            "kind": "assistant_message", "itemId": "answer", "text": "original",
        })
    monkeypatch.setattr(session_service, "_load_session_conversation_events_cached", lambda _: events)
    snapshot = projection._SessionJournalProjection("session")
    expected_items = turn_journal.session_turn_items_from_events(events, turn_id="turn")
    expected_order = turn_steer.display_item_order_provenance(events, "turn")
    tree_calls = []
    build_tree = turn_journal.build_journal_event_tree

    def counted_tree(rows):
        tree_calls.append(1)
        return build_tree(rows)

    monkeypatch.setattr(turn_journal, "build_journal_event_tree", counted_tree)
    items, order = snapshot.for_turn("session", "turn")
    assert len(tree_calls) == (2 if duplicate_sequence else 1)
    assert items == expected_items
    assert order == expected_order
    # Cached dictionaries, including nested metadata and alias records, cannot
    # become owned by a message/live merge or by the caller.
    items[0]["metadata"]["nested"]["value"] = "mutated"
    order["injected"] = {"orderSequence": 999}
    if "alias" in order:
        order["alias"]["contentOffset"] = 999
    assert snapshot.for_turn("session", "turn") == (expected_items, expected_order)
    # The same active slices may feed multiple message identities and live
    # content merges; no returned item/alias may retain the first message.
    for source, done in [("session_detail", True), ("assistant_delta", False)]:
        kwargs = dict(
            session_id="session", turn_id="turn", message_id="first", content="prefix-answer",
            thought="reasoning", source=source, done=done,
        )
        expected = projection._build_session_turn_items_projection(**kwargs)
        first = projection._build_session_turn_items_projection(**kwargs, journal_projection=snapshot)
        assert first == expected
        first[0]["messageId"] = "mutated"
        kwargs["message_id"] = "second"
        second = projection._build_session_turn_items_projection(**kwargs, journal_projection=snapshot)
        assert second == projection._build_session_turn_items_projection(**kwargs)
        # The v3 DTO may omit messageId, but must never inherit an earlier
        # message's identity or a caller's injected value.
        assert all(item.get("messageId") not in {"first", "mutated"} for item in second)
    with pytest.raises(ValueError, match="session"):
        snapshot.for_turn("different-session", "turn")
    with pytest.raises(ValueError, match="session"):
        projection._build_session_turn_items_projection(
            session_id="different-session", turn_id="turn", message_id="message",
            metadata={"kind": "context_compression_marker"}, journal_projection=snapshot,
        )


@pytest.fixture(autouse=True)
def isolate_developer_sandbox(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        developer_sandbox,
        "resolve_workspace_home",
        lambda *args, **kwargs: tmp_path / "workspace",
    )
    status = developer_sandbox.get_developer_mode_status(
        config_path=config_path, project_root=tmp_path
    )
    developer_sandbox.update_developer_mode_status(
        False,
        base_hash=status["configHash"],
        config_path=config_path,
        project_root=tmp_path,
    )


@pytest.fixture(autouse=True)
def reset_journal_caches():
    turn_journal._TERMINAL_SET_CACHE.clear()
    turn_journal._MKDIR_CACHE.clear()
    turn_journal._SEQUENCE_CACHE.clear()
    yield


def test_fsync_skipped_for_volatile_events(tmp_path, monkeypatch):
    fsync_calls = []
    real_fsync = os.fsync

    def counting_fsync(fd):
        fsync_calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)

    append_turn_event(tmp_path, "sess", "turn-1", EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "sess", "turn-1", EVENT_USER_MESSAGE, status="recorded")
    append_turn_event(tmp_path, "sess", "turn-1", EVENT_ASSISTANT_PARTIAL, status="running")
    append_turn_event(tmp_path, "sess", "turn-1", EVENT_ASSISTANT_PARTIAL, status="running")
    append_turn_event(tmp_path, "sess", "turn-1", EVENT_TOOL_RESULT, status="done")
    append_turn_event(tmp_path, "sess", "turn-1", EVENT_TURN_COMPLETED, status="done")

    # 6 个事件：3 个关键（fsync）+ 2 个易失（仅 flush）+ turn_started（flush-only，可从 work-run 重构）
    assert len(fsync_calls) == 3, fsync_calls


def test_terminal_check_cache_avoids_full_scan(tmp_path, monkeypatch):
    scan_calls = []
    real_scan = turn_journal._scan_terminal_turn_ids

    def counting_scan(path):
        scan_calls.append(path)
        return real_scan(path)

    monkeypatch.setattr(turn_journal, "_scan_terminal_turn_ids", counting_scan)

    append_turn_event(tmp_path, "sess", "turn-a", EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "sess", "turn-a", EVENT_USER_MESSAGE, status="recorded")
    # 第一次 POST_TERMINAL 检查：缓存 miss，扫描一次构建
    append_turn_event(tmp_path, "sess", "turn-a", EVENT_TOOL_RESULT, status="done")
    # 后续 POST_TERMINAL 检查：缓存命中，不再扫描
    append_turn_event(tmp_path, "sess", "turn-a", EVENT_TOOL_RESULT, status="done")
    append_turn_event(tmp_path, "sess", "turn-a", EVENT_TOOL_RESULT, status="done")

    assert len(scan_calls) == 1, scan_calls


def test_mkdir_deduplicated(tmp_path, monkeypatch):
    ensure_calls: list[tuple[str, bool]] = []
    real_ensure = turn_journal._ensure_journal_parent

    def counting_ensure(path):
        key = str(path.parent)
        with turn_journal._MKDIR_CACHE_LOCK:
            was_cached = key in turn_journal._MKDIR_CACHE
        ensure_calls.append((key, was_cached))
        return real_ensure(path)

    monkeypatch.setattr(turn_journal, "_ensure_journal_parent", counting_ensure)

    append_turn_event(tmp_path, "sess", "t1", EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "sess", "t1", EVENT_USER_MESSAGE, status="recorded")
    append_turn_event(tmp_path, "sess", "t1", EVENT_TOOL_RESULT, status="done")

    assert ensure_calls, "expected journal parent ensure calls"
    assert ensure_calls[0][1] is False
    assert all(was_cached for _, was_cached in ensure_calls[1:]), ensure_calls
    assert len({key for key, _ in ensure_calls}) == 1
    assert len(turn_journal._MKDIR_CACHE) == 1


def test_terminal_check_still_blocks_post_terminal_events(tmp_path):
    append_turn_event(tmp_path, "sess", "t1", EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "sess", "t1", EVENT_USER_MESSAGE, status="recorded")
    append_turn_event(tmp_path, "sess", "t1", EVENT_TURN_COMPLETED, status="done")

    # 首次：走缓存路径（terminal 已被 remember 合并进缓存）
    with pytest.raises(ValueError):
        append_turn_event(tmp_path, "sess", "t1", EVENT_TOOL_RESULT, status="done")
    # 再次：缓存命中，仍应阻止
    with pytest.raises(ValueError):
        append_turn_event(tmp_path, "sess", "t1", EVENT_TOOL_RESULT, status="done")


def test_rewrite_invalidates_terminal_cache(tmp_path):
    append_turn_event(tmp_path, "sess", "t1", EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "sess", "t1", EVENT_TURN_COMPLETED, status="done")

    # 重写：移除 terminal 事件（仅保留 started）
    events = turn_journal.load_turn_events(tmp_path, "sess")
    events = [event for event in events if event.event_type != EVENT_TURN_COMPLETED]
    turn_journal.rewrite_turn_events(tmp_path, "sess", events)

    # 重写后应允许 POST_TERMINAL 事件（不再有 terminal）
    append_turn_event(tmp_path, "sess", "t1", EVENT_TOOL_RESULT, status="done")
