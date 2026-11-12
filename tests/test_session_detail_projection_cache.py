"""Ledger projection snapshot cache: hit counting + window equivalence.

The detail transcript pipeline used to replay the full journal projection on
every request (branch analysis, model-visible messages, guidance restore,
stat-message normalization, timeline by-turn scan). The snapshot cache keys
the finished projections on the ledger signature, so an unchanged journal
skips the replay and an append rebuilds exactly once. These tests pin the
cache-hit behavior and the output equivalence between cached and rebuilt
reads.
"""

from __future__ import annotations

import copy

import pytest

from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_USER_MESSAGE,
    append_conversation_event,
)
from core.chat.turn_journal import EVENT_ASSISTANT_ITEM_COMMITTED
from core.web.services import session_service
from core.web.services.session import projection
from tests.test_agent_config_workspace_service import _use_tmp_project_root

SESSION_ID = "session-projection-cache"


@pytest.fixture(autouse=True)
def _clear_projection_cache():
    projection._LEDGER_PROJECTION_CACHE.clear()
    yield
    projection._LEDGER_PROJECTION_CACHE.clear()


def _append_turn(root, turn_id: str, user_text: str, assistant_text: str) -> None:
    append_conversation_event(
        root,
        SESSION_ID,
        turn_id,
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": user_text},
    )
    append_conversation_event(
        root,
        SESSION_ID,
        turn_id,
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": assistant_text},
    )


def _count_calls(monkeypatch: pytest.MonkeyPatch, attr_name: str) -> list[int]:
    calls: list[int] = []
    original = getattr(session_service, attr_name)

    def _wrapped(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(session_service, attr_name, _wrapped)
    return calls


def test_unchanged_ledger_reuses_visible_messages_snapshot(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _append_turn(tmp_path, "turn-1", "第一轮用户消息。", "第一轮助手回复。")

    calls = _count_calls(monkeypatch, "visible_messages_with_branch_info")
    first = session_service._ledger_visible_messages_for_session(SESSION_ID)
    second = session_service._ledger_visible_messages_for_session(SESSION_ID)

    assert len(first) == 2
    assert len(calls) == 1, "unchanged journal must reuse the cached projection"
    assert second == first

    # An append changes the ledger signature: exactly one rebuild, now including
    # the new turn.
    _append_turn(tmp_path, "turn-2", "第二轮用户消息。", "第二轮助手回复。")
    third = session_service._ledger_visible_messages_for_session(SESSION_ID)
    assert len(calls) == 2
    assert len(third) == 4
    assert third[-2]["content"] == "第二轮用户消息。"


def test_branch_metadata_shares_the_visible_snapshot(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _append_turn(tmp_path, "turn-1", "你好。", "你好，有什么可以帮你？")

    replay_calls = _count_calls(monkeypatch, "visible_messages_with_branch_info")
    analyze_calls = _count_calls(monkeypatch, "analyze_conversation_branches")

    session_service._ledger_visible_messages_for_session(SESSION_ID)
    leaf_id, branch_id = session_service._session_branch_metadata(SESSION_ID)

    assert len(replay_calls) == 1
    assert len(analyze_calls) == 0, "branch head must come from the shared snapshot"
    assert leaf_id
    assert branch_id


def test_window_output_is_identical_between_cached_and_rebuilt_reads(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    for index in range(4):
        _append_turn(
            tmp_path,
            f"turn-{index}",
            f"第 {index} 轮提问内容。",
            f"第 {index} 轮的完整回答内容。",
        )

    first = session_service._session_detail_messages_with_window(
        SESSION_ID,
        message_limit=3,
        before_message_index=0,
        transcript_scope="all",
    )
    # Second read hits every snapshot layer; the window payload must be
    # indistinguishable from the rebuilt one.
    second = session_service._session_detail_messages_with_window(
        SESSION_ID,
        message_limit=3,
        before_message_index=0,
        transcript_scope="all",
    )
    projection._LEDGER_PROJECTION_CACHE.clear()
    rebuilt = session_service._session_detail_messages_with_window(
        SESSION_ID,
        message_limit=3,
        before_message_index=0,
        transcript_scope="all",
    )

    assert second == first
    assert rebuilt == first


def test_stat_messages_hit_the_snapshot(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    for index in range(3):
        _append_turn(
            tmp_path,
            f"turn-{index}",
            f"第 {index} 轮提问。",
            f"第 {index} 轮回答。",
        )

    normalize_calls: list[int] = []
    original_normalize = session_service._normalize_messages

    def _counting_normalize(*args, **kwargs):
        normalize_calls.append(1)
        return original_normalize(*args, **kwargs)

    monkeypatch.setattr(session_service, "_normalize_messages", _counting_normalize)

    first = session_service._session_detail_messages_with_window(
        SESSION_ID, message_limit=2, transcript_scope="all",
    )
    first_normalizes = len(normalize_calls)
    second = session_service._session_detail_messages_with_window(
        SESSION_ID, message_limit=2, transcript_scope="all",
    )

    assert second == first
    # A warm window read still normalizes the window slice itself, but the
    # full-ledger stat projection must come from the snapshot instead of
    # re-normalizing every message again.
    assert len(normalize_calls) == first_normalizes + 1
    assert len(second[2]) == len(first[2])


def test_timeline_events_by_turn_hit_the_snapshot(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    append_conversation_event(
        tmp_path,
        SESSION_ID,
        "turn-timeline-1",
        EVENT_ASSISTANT_ITEM_COMMITTED,
        status="committed",
        payload={"kind": "commentary", "text": "第一条 commentary 过程输出。"},
    )

    events_calls: list[int] = []
    original_events = session_service._load_session_conversation_events_cached

    def _counting_events(session_id, **kwargs):
        events_calls.append(1)
        return original_events(session_id, **kwargs)

    monkeypatch.setattr(
        session_service, "_load_session_conversation_events_cached", _counting_events
    )

    first = session_service._assistant_timeline_events_by_turn(SESSION_ID)
    first_reads = len(events_calls)
    assert "turn-timeline-1" in first, "expected the commentary turn in the timeline"
    second = session_service._assistant_timeline_events_by_turn(SESSION_ID)
    assert second == first
    assert len(events_calls) == first_reads, (
        "unchanged journal must reuse the cached by-turn timeline projection"
    )

    append_conversation_event(
        tmp_path,
        SESSION_ID,
        "turn-timeline-2",
        EVENT_ASSISTANT_ITEM_COMMITTED,
        status="committed",
        payload={"kind": "commentary", "text": "第二条 commentary 过程输出。"},
    )
    third = session_service._assistant_timeline_events_by_turn(SESSION_ID)
    assert len(events_calls) == first_reads + 1
    assert "turn-timeline-2" in third
    assert "turn-timeline-1" in third


def test_projection_cache_key_includes_the_resolved_project_root(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()

    monkeypatch.setattr(session_service, "PROJECT_ROOT", root_a)
    key_a = projection._ledger_projection_cache_key(SESSION_ID)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", root_b)
    key_b = projection._ledger_projection_cache_key(SESSION_ID)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", root_a)
    key_a_again = projection._ledger_projection_cache_key(SESSION_ID)

    assert key_a != key_b
    assert key_a == key_a_again
    assert str(root_a.resolve()) in key_a
    assert str(root_b.resolve()) in key_b


def test_projection_cache_stays_bounded_by_lru_eviction(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    max_entries = projection._LEDGER_PROJECTION_CACHE_MAX_ENTRIES
    for index in range(max_entries + 3):
        projection._store_ledger_projection_cache_entry(
            f"session-lru-{index}",
            (f"sig-{index}", 0, 1, 1),
            messages=(),
        )
    # Re-store the first entry under its own signature (the merge path refreshes
    # last_access), then add one more entry: only the older middle entries may
    # be evicted.
    projection._store_ledger_projection_cache_entry(
        "session-lru-0",
        ("sig-0", 0, 1, 1),
        messages=(),
    )
    projection._store_ledger_projection_cache_entry(
        f"session-lru-{max_entries + 3}",
        (f"sig-{max_entries + 3}", 0, 1, 1),
        messages=(),
    )

    assert (
        len(projection._LEDGER_PROJECTION_CACHE)
        <= max_entries
    )
    surviving = [key for key in projection._LEDGER_PROJECTION_CACHE if key.endswith("session-lru-0")]
    assert surviving, "recently used entry must survive eviction"


def test_signature_change_between_build_and_fill_never_poisons_the_cache(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _append_turn(tmp_path, "turn-1", "先问一句。", "先答一句。")

    session_service._ledger_visible_messages_for_session(SESSION_ID)
    # Simulate a rebuild that raced an append: the captured signature is stale,
    # so the fill must be dropped instead of overwriting the fresh snapshot.
    projection._store_ledger_projection_cache_entry(
        SESSION_ID,
        ("stale-signature", 0, -1, -1),
        messages=(),
    )

    messages = session_service._ledger_visible_messages_for_session(SESSION_ID)
    assert len(messages) == 2


def test_concurrent_reads_of_one_session_stay_consistent(tmp_path, monkeypatch):
    import threading

    _use_tmp_project_root(tmp_path, monkeypatch)
    for index in range(3):
        _append_turn(
            tmp_path,
            f"turn-{index}",
            f"并发第 {index} 轮提问。",
            f"并发第 {index} 轮回答。",
        )

    results: list[list[dict]] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def _read():
        try:
            messages = session_service._ledger_visible_messages_for_session(SESSION_ID)
            with lock:
                results.append(messages)
        except BaseException as exc:  # surfaced below on purpose
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=_read) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(results) == 8
    assert all(result == results[0] for result in results)
    assert len(results[0]) == 6
