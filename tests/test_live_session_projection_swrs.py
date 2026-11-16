"""Live-session detail projection stale-while-revalidate + recovery stagger.

A resumed live session appends to its turn_journal constantly, so every poll
missed the ledger projection snapshot cache and replayed the full journal on
the request thread. With several sessions resumed at once (startup recovery
used to submit every candidate in parallel) those replays interleave on the
GIL, starve the asyncio loop's SSE heartbeats, and clients reconnect-storm.

These tests pin the two fixes:

- running sessions serve the previous projection inside a short stale window
  and queue exactly one rebuild on the dedicated single-worker executor;
  idle sessions and the rebuild thread keep exact rebuild semantics;
- startup recovery still recovers every candidate but submits them with a
  fixed stagger instead of an all-at-once burst.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_USER_MESSAGE,
    append_conversation_event,
)
from core.chat.turn_journal import EVENT_ASSISTANT_ITEM_COMMITTED
from core.web.services import session_service
from core.web.services.session import projection, startup_recovery
from tests.test_agent_config_workspace_service import _use_tmp_project_root

SESSION_ID = "session-live-swr"
SESSION_B_ID = "session-live-swr-b"


def _wait_rebuild_idle(timeout: float = 15.0) -> None:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        with projection._SWR_REBUILD_LOCK:
            if not projection._SWR_REBUILD_IN_FLIGHT:
                return
        time.sleep(0.02)
    raise AssertionError("projection rebuild executor did not go idle in time")


@pytest.fixture(autouse=True)
def _isolated_projection_swrs(monkeypatch):
    projection._LEDGER_PROJECTION_CACHE.clear()
    projection._LEDGER_PROJECTION_SWR_DECISIONS.clear()
    with projection._SWR_REBUILD_LOCK:
        projection._SWR_REBUILD_IN_FLIGHT.clear()
    # Generous window so test pacing never flips a case into the expiry path;
    # the expiry test overrides it explicitly.
    monkeypatch.setattr(projection, "_LEDGER_PROJECTION_STALE_SERVE_SECONDS", 30.0)
    yield
    _wait_rebuild_idle()
    projection._LEDGER_PROJECTION_CACHE.clear()
    projection._LEDGER_PROJECTION_SWR_DECISIONS.clear()
    with projection._SWR_REBUILD_LOCK:
        projection._SWR_REBUILD_IN_FLIGHT.clear()


@pytest.fixture
def running_sessions(monkeypatch):
    running: set[str] = {SESSION_ID}

    def _is_running(session_id: str) -> bool:
        return str(session_id or "").strip() in running

    monkeypatch.setattr(session_service, "_is_session_running", _is_running)
    return running


def _append_turn(root, session_id: str, turn_id: str, user_text: str, assistant_text: str) -> None:
    append_conversation_event(
        root,
        session_id,
        turn_id,
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": user_text},
    )
    append_conversation_event(
        root,
        session_id,
        turn_id,
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": assistant_text},
    )


def _count_sync_rebuilds(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    original = session_service.visible_messages_with_branch_info

    def _wrapped(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(session_service, "visible_messages_with_branch_info", _wrapped)
    return calls


def _instrument_rebuilds(monkeypatch: pytest.MonkeyPatch, *, block_until: threading.Event | None = None):
    started = threading.Event()
    executions: list[str] = []
    original = projection._run_ledger_projection_rebuild

    def _wrapped(session_id, cache_key):
        executions.append(str(session_id))
        started.set()
        if block_until is not None:
            assert block_until.wait(timeout=30), "rebuild block event never released"
        return original(session_id, cache_key)

    monkeypatch.setattr(projection, "_run_ledger_projection_rebuild", _wrapped)
    return executions, started


def test_stale_window_serves_previous_projection_without_sync_rebuild(tmp_path, monkeypatch, running_sessions):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _append_turn(tmp_path, SESSION_ID, "turn-1", "第一轮提问。", "第一轮回答。")

    sync_calls = _count_sync_rebuilds(monkeypatch)
    executions, _started = _instrument_rebuilds(monkeypatch)

    first = session_service._ledger_visible_messages_for_session(SESSION_ID)
    assert len(first) == 2
    assert len(sync_calls) == 1, "cold read builds the snapshot once"

    _append_turn(tmp_path, SESSION_ID, "turn-2", "第二轮提问。", "第二轮回答。")

    stale = session_service._ledger_visible_messages_for_session(SESSION_ID)
    assert [m["content"] for m in stale] == ["第一轮提问。", "第一轮回答。"], (
        "inside the stale window the previous projection is served as-is"
    )
    assert len(sync_calls) == 1, "stale serve must not rebuild on the request thread"

    _wait_rebuild_idle()
    assert executions == [SESSION_ID], "exactly one background rebuild for the session"

    fresh = session_service._ledger_visible_messages_for_session(SESSION_ID)
    assert len(fresh) == 4
    assert fresh[-2]["content"] == "第二轮提问。"
    assert len(sync_calls) == 2, "only the background rebuild ran; the fresh read is a hit"
    assert (
        projection._ledger_projection_cache_entry(
            SESSION_ID,
            session_service._session_conversation_events_signature(SESSION_ID),
        )
        is not None
    ), "the rebuild lands under the new ledger signature"


def test_concurrent_misses_single_flight_one_rebuild(tmp_path, monkeypatch, running_sessions):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _append_turn(tmp_path, SESSION_ID, "turn-1", "并发提问。", "并发回答。")

    sync_calls = _count_sync_rebuilds(monkeypatch)
    session_service._ledger_visible_messages_for_session(SESSION_ID)

    _append_turn(tmp_path, SESSION_ID, "turn-2", "并发第二轮。", "并发第二轮回答。")

    release = threading.Event()
    executions, _started = _instrument_rebuilds(monkeypatch, block_until=release)

    results: list[list[dict]] = []
    errors: list[BaseException] = []
    timings: list[float] = []
    start_barrier = threading.Barrier(8)
    lock = threading.Lock()

    def _read():
        try:
            start_barrier.wait(timeout=10)
            began = time.perf_counter()
            messages = session_service._ledger_visible_messages_for_session(SESSION_ID)
            with lock:
                results.append(messages)
                timings.append(time.perf_counter() - began)
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
    # The rebuild blocks on purpose: every request must still return the stale
    # snapshot quickly instead of waiting for the executor queue.
    assert all(len(result) == 2 for result in results), (
        "every concurrent read serves the same stale generation while the rebuild is queued"
    )
    assert max(timings) < 1.0, "executor queue wait must not block request returns"
    assert len(executions) == 1, "N concurrent misses deduplicate into one queued rebuild"
    assert len(sync_calls) == 1, "no request thread performs a synchronous rebuild"

    release.set()
    _wait_rebuild_idle()
    fresh = session_service._ledger_visible_messages_for_session(SESSION_ID)
    assert len(fresh) == 4
    assert len(sync_calls) == 2


def test_expired_stale_age_falls_back_to_synchronous_rebuild(tmp_path, monkeypatch, running_sessions):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(projection, "_LEDGER_PROJECTION_STALE_SERVE_SECONDS", 0.0)
    _append_turn(tmp_path, SESSION_ID, "turn-1", "过期提问。", "过期回答。")

    sync_calls = _count_sync_rebuilds(monkeypatch)
    session_service._ledger_visible_messages_for_session(SESSION_ID)
    _append_turn(tmp_path, SESSION_ID, "turn-2", "过期第二轮。", "过期第二轮回答。")

    messages = session_service._ledger_visible_messages_for_session(SESSION_ID)
    assert len(messages) == 4
    assert messages[-2]["content"] == "过期第二轮。"
    assert len(sync_calls) == 2, "no stale snapshot: first-read semantics rebuild synchronously"
    with projection._SWR_REBUILD_LOCK:
        assert projection._SWR_REBUILD_IN_FLIGHT == set(), "expiry path never queues a rebuild"


def test_stale_serve_is_limited_to_running_sessions(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(session_service, "_is_session_running", lambda session_id: False)
    _append_turn(tmp_path, SESSION_ID, "turn-1", "静止提问。", "静止回答。")

    sync_calls = _count_sync_rebuilds(monkeypatch)
    session_service._ledger_visible_messages_for_session(SESSION_ID)
    _append_turn(tmp_path, SESSION_ID, "turn-2", "静止第二轮。", "静止第二轮回答。")

    messages = session_service._ledger_visible_messages_for_session(SESSION_ID)
    assert len(messages) == 4
    assert len(sync_calls) == 2, "idle sessions keep the exact rebuild-on-miss semantics"
    with projection._SWR_REBUILD_LOCK:
        assert projection._SWR_REBUILD_IN_FLIGHT == set()


def test_rebuild_decisions_are_isolated_per_session(tmp_path, monkeypatch, running_sessions):
    _use_tmp_project_root(tmp_path, monkeypatch)
    running_sessions.add(SESSION_B_ID)
    _append_turn(tmp_path, SESSION_ID, "turn-1", "甲会话提问。", "甲会话回答。")
    _append_turn(tmp_path, SESSION_B_ID, "turn-1", "乙会话提问。", "乙会话回答。")

    sync_calls = _count_sync_rebuilds(monkeypatch)
    executions, _started = _instrument_rebuilds(monkeypatch)
    assert len(session_service._ledger_visible_messages_for_session(SESSION_ID)) == 2
    assert len(session_service._ledger_visible_messages_for_session(SESSION_B_ID)) == 2
    assert len(sync_calls) == 2

    _append_turn(tmp_path, SESSION_ID, "turn-2", "甲会话第二轮。", "甲会话第二轮回答。")

    stale_a = session_service._ledger_visible_messages_for_session(SESSION_ID)
    assert len(stale_a) == 2
    fresh_b = session_service._ledger_visible_messages_for_session(SESSION_B_ID)
    assert [m["content"] for m in fresh_b] == ["乙会话提问。", "乙会话回答。"], (
        "session B must keep its own hit instead of joining session A's stale window"
    )

    _wait_rebuild_idle()
    assert executions == [SESSION_ID], "session B schedules no rebuild"
    assert len(sync_calls) == 3, "only session A's snapshot rebuilds"
    assert len(session_service._ledger_visible_messages_for_session(SESSION_B_ID)) == 2


def test_detail_consumers_share_one_stale_generation(tmp_path, monkeypatch, running_sessions):
    _use_tmp_project_root(tmp_path, monkeypatch)
    append_conversation_event(
        tmp_path,
        SESSION_ID,
        "turn-1",
        EVENT_ASSISTANT_ITEM_COMMITTED,
        status="committed",
        payload={"kind": "commentary", "text": "第一轮 commentary。"},
    )
    _append_turn(tmp_path, SESSION_ID, "turn-1", "共享提问。", "共享回答。")

    sync_calls = _count_sync_rebuilds(monkeypatch)
    events_calls: list[int] = []
    original_events = session_service._load_session_conversation_events_cached

    def _counting_events(session_id, **kwargs):
        events_calls.append(1)
        return original_events(session_id, **kwargs)

    monkeypatch.setattr(session_service, "_load_session_conversation_events_cached", _counting_events)

    # A real detail poll builds messages + stat together; branch head and the
    # by-turn timeline join the same snapshot right after.
    session_service._session_detail_messages_with_window(
        SESSION_ID,
        message_limit=5,
        before_message_index=0,
        transcript_scope="all",
    )
    session_service._session_branch_metadata(SESSION_ID)
    timeline = session_service._assistant_timeline_events_by_turn(SESSION_ID)
    assert set(timeline) == {"turn-1"}
    assert len(sync_calls) == 1
    warm_loads = len(events_calls)

    # The rebuild blocks until released so every consumer below deterministically
    # observes the stale generation instead of one whose rebuild already landed.
    _append_turn(tmp_path, SESSION_ID, "turn-2", "共享第二轮。", "共享第二轮回答。")
    append_conversation_event(
        tmp_path,
        SESSION_ID,
        "turn-2",
        EVENT_ASSISTANT_ITEM_COMMITTED,
        status="committed",
        payload={"kind": "commentary", "text": "第二轮 commentary。"},
    )
    release = threading.Event()
    _executions, _started = _instrument_rebuilds(monkeypatch, block_until=release)

    stale_messages = session_service._ledger_visible_messages_for_session(SESSION_ID)
    assert len(stale_messages) == 2
    # Every other detail consumer joins the memoized serve-stale verdict: same
    # generation as the messages, no synchronous rebuild anywhere.
    leaf_id, branch_id = session_service._session_branch_metadata(SESSION_ID)
    assert leaf_id and branch_id
    stale_timeline = session_service._assistant_timeline_events_by_turn(SESSION_ID)
    assert set(stale_timeline) == {"turn-1"}, "timeline serves the stale generation"
    assert len(events_calls) == warm_loads, "stale consumers never rescan the journal themselves"
    _detail, _window, stat_messages = session_service._session_detail_messages_with_window(
        SESSION_ID,
        message_limit=5,
        before_message_index=0,
        transcript_scope="all",
    )
    assert len(stat_messages) == 2, "stat projection joins the stale generation"
    assert len(sync_calls) == 1, "no consumer falls back to a synchronous rebuild"

    release.set()
    _wait_rebuild_idle()
    fresh = session_service._ledger_visible_messages_for_session(SESSION_ID)
    assert len(fresh) == 4
    fresh_timeline = session_service._assistant_timeline_events_by_turn(SESSION_ID)
    assert set(fresh_timeline) == {"turn-1", "turn-2"}


def test_rebuild_bundle_fills_one_skeleton_under_drifting_signatures(
    tmp_path, monkeypatch, running_sessions
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _append_turn(tmp_path, SESSION_ID, "turn-1", "同代提问。", "同代回答。")
    append_conversation_event(
        tmp_path,
        SESSION_ID,
        "turn-1",
        EVENT_ASSISTANT_ITEM_COMMITTED,
        status="committed",
        payload={"kind": "commentary", "text": "同代 commentary。"},
    )
    original_signature_fn = session_service._session_conversation_events_signature
    session_service._session_detail_messages_with_window(
        SESSION_ID,
        message_limit=5,
        before_message_index=0,
        transcript_scope="all",
    )
    session_service._assistant_timeline_events_by_turn(SESSION_ID)
    projection._LEDGER_PROJECTION_CACHE.clear()
    projection._LEDGER_PROJECTION_SWR_DECISIONS.clear()

    # A live session appends while the rebuild executes, so every step would
    # capture a different signature if it re-read one. The bundle must capture
    # a single signature at entry and fill all three stores onto that same
    # skeleton — a per-step replace would wipe the previous step's fields and
    # leave a one-field entry that misses again on the next read.
    signature_calls: list[tuple] = []

    def _drifting_signature(session_id):
        signature = (f"drift-{len(signature_calls)}", 0, 0, 0)
        signature_calls.append(signature)
        return signature

    monkeypatch.setattr(
        session_service, "_session_conversation_events_signature", _drifting_signature
    )
    cache_key = projection._ledger_projection_cache_key(SESSION_ID)
    projection._run_ledger_projection_rebuild(SESSION_ID, cache_key)

    assert len(signature_calls) == 1, "the bundle captures the signature exactly once"
    entry = projection._LEDGER_PROJECTION_CACHE.get(cache_key)
    assert entry is not None
    assert tuple(entry["signature"]) == signature_calls[0], (
        "all three stores share the entry-captured signature"
    )
    assert entry.get("messages") is not None, "messages must survive the later steps"
    assert entry.get("timeline_events_by_turn") is not None, (
        "timeline must land on the same skeleton"
    )
    assert entry.get("stat_messages") is not None, "stat must land on the same skeleton"
    assert entry.get("active_leaf_id") and entry.get("active_branch_id")

    # Self-heal: back on the real signature, the read misses, serves the fresh
    # stale snapshot and queues one rebuild that lands under the live signature.
    monkeypatch.setattr(
        session_service, "_session_conversation_events_signature", original_signature_fn
    )
    stale = session_service._ledger_visible_messages_for_session(SESSION_ID)
    assert len(stale) == 2, "the one-generation-behind bundle is served stale"
    _wait_rebuild_idle()
    fresh = session_service._ledger_visible_messages_for_session(SESSION_ID)
    assert len(fresh) == 2
    healed = projection._LEDGER_PROJECTION_CACHE.get(cache_key)
    assert tuple(healed["signature"]) == original_signature_fn(SESSION_ID), (
        "the follow-up rebuild transitions the snapshot to the live signature"
    )
    assert healed.get("messages") is not None
    assert healed.get("timeline_events_by_turn") is not None
    assert healed.get("stat_messages") is not None


def test_recovery_candidates_are_staggered_not_burst(monkeypatch):
    recovered: list[str] = []

    def _fake_recover(_s, session_id, **_kwargs):
        recovered.append(str(session_id))

    monkeypatch.setattr(startup_recovery, "_recover_session_on_startup", _fake_recover)
    sleeps: list[float] = []
    monkeypatch.setattr(startup_recovery, "_stagger_sleep", lambda seconds: sleeps.append(seconds))

    session_ids = [f"session-{index}" for index in range(5)]
    summaries = startup_recovery._run_session_candidates(
        SimpleNamespace(),
        session_ids,
        worker_count=4,
        companion_session_ids=set(),
        should_stop=None,
        active_turn_session_ids=set(),
        pending_turn_ids=set(),
    )

    assert sorted(recovered) == session_ids, "every candidate is still recovered exactly once"
    assert len(summaries) == 5
    assert sleeps == [startup_recovery._RECOVERY_STAGGER_SECONDS] * (len(session_ids) - 1), (
        "candidates roll in with a fixed gap instead of an all-at-once burst"
    )


def test_recovery_stagger_sleeps_are_skipped_when_shutdown_requested(monkeypatch):
    recovered: list[str] = []

    def _fake_recover(_s, session_id, **_kwargs):
        recovered.append(str(session_id))

    monkeypatch.setattr(startup_recovery, "_recover_session_on_startup", _fake_recover)
    sleeps: list[float] = []
    monkeypatch.setattr(startup_recovery, "_stagger_sleep", lambda seconds: sleeps.append(seconds))

    session_ids = [f"session-{index}" for index in range(3)]
    startup_recovery._run_session_candidates(
        SimpleNamespace(),
        session_ids,
        worker_count=3,
        companion_session_ids=set(),
        should_stop=lambda: True,
        active_turn_session_ids=set(),
        pending_turn_ids=set(),
    )

    assert recovered == session_ids, "shutdown must not drop pending candidates"
    assert sleeps == []


def test_serial_recovery_path_never_staggers(monkeypatch):
    recovered: list[str] = []

    def _fake_recover(_s, session_id, **_kwargs):
        recovered.append(str(session_id))

    monkeypatch.setattr(startup_recovery, "_recover_session_on_startup", _fake_recover)
    sleeps: list[float] = []
    monkeypatch.setattr(startup_recovery, "_stagger_sleep", lambda seconds: sleeps.append(seconds))

    session_ids = [f"session-{index}" for index in range(3)]
    startup_recovery._run_session_candidates(
        SimpleNamespace(),
        session_ids,
        worker_count=1,
        companion_session_ids=set(),
        should_stop=None,
        active_turn_session_ids=set(),
        pending_turn_ids=set(),
    )

    assert recovered == session_ids
    assert sleeps == [], "the serial path is staggered by construction"
