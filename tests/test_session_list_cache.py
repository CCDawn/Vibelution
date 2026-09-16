"""Focused tests for session list cache slice."""

from __future__ import annotations

import threading

from core.web.services.session import list_cache


def test_session_list_cache_roundtrip_and_invalidate() -> None:
    signature = ("test-signature", True)
    list_cache.invalidate_session_list_cache()
    assert (
        list_cache.get_session_list_cache(now=100.0, signature=signature) is None
    )

    sessions = [
        {
            "id": "s1",
            "title": "alpha",
            "childSessionIds": ["c1"],
            "resultCard": {"changedFiles": ["a.py"], "validations": ["ok"]},
        }
    ]
    list_cache.set_session_list_cache(
        sessions,
        now=100.0,
        signature=signature,
        conversation_count=1,
        agent_count=2,
    )
    cached = list_cache.get_session_list_cache(now=101.0, signature=signature)
    assert cached is not None
    snapshot, age_ms, conversation_count, agent_count = cached
    assert conversation_count == 1
    assert agent_count == 2
    assert age_ms >= 0
    assert snapshot[0]["id"] == "s1"
    # defensive copy
    snapshot[0]["childSessionIds"].append("mutated")
    cached_again = list_cache.get_session_list_cache(now=101.0, signature=signature)
    assert cached_again is not None
    assert cached_again[0][0]["childSessionIds"] == ["c1"]

    list_cache.invalidate_session_list_cache()
    assert list_cache.get_session_list_cache(now=102.0, signature=signature) is None


def test_session_list_cache_single_flight_begin_finish() -> None:
    signature = ("inflight-signature", False)
    list_cache.invalidate_session_list_cache()
    cached, should_build, waited = list_cache.begin_session_list_cache_build(
        now=200.0,
        signature=signature,
    )
    assert cached is None
    assert should_build is True
    assert waited is False
    list_cache.finish_session_list_cache_build(
        signature=signature,
        sessions=[{"id": "built", "title": "t"}],
        started_at=200.0,
        conversation_count=3,
        agent_count=1,
    )
    hit = list_cache.get_session_list_cache(now=200.5, signature=signature)
    assert hit is not None
    assert hit[0][0]["id"] == "built"
    list_cache.invalidate_session_list_cache()


def test_session_list_cache_keeps_distinct_signature_build_owners() -> None:
    visible_signature = ("shared-source", False)
    hidden_signature = ("shared-source", True)
    list_cache.invalidate_session_list_cache()

    visible_cached, visible_should_build, visible_waited = (
        list_cache.begin_session_list_cache_build(
            now=200.0,
            signature=visible_signature,
        )
    )
    hidden_cached, hidden_should_build, hidden_waited = (
        list_cache.begin_session_list_cache_build(
            now=200.1,
            signature=hidden_signature,
        )
    )

    assert visible_cached is None
    assert visible_should_build is True
    assert visible_waited is False
    assert hidden_cached is None
    assert hidden_should_build is True
    assert hidden_waited is False

    list_cache.finish_session_list_cache_build(
        signature=visible_signature,
        sessions=[{"id": "visible", "title": "visible"}],
        started_at=200.0,
        conversation_count=1,
        agent_count=2,
    )
    list_cache.finish_session_list_cache_build(
        signature=hidden_signature,
        sessions=[{"id": "hidden", "title": "hidden"}],
        started_at=200.1,
        conversation_count=2,
        agent_count=2,
    )

    visible_hit = list_cache.get_session_list_cache(
        now=200.5,
        signature=visible_signature,
    )
    hidden_hit = list_cache.get_session_list_cache(
        now=200.5,
        signature=hidden_signature,
    )

    assert visible_hit is not None
    assert visible_hit[0][0]["id"] == "visible"
    assert hidden_hit is not None
    assert hidden_hit[0][0]["id"] == "hidden"
    list_cache.invalidate_session_list_cache()


def test_session_list_cache_bounds_distinct_signature_snapshots() -> None:
    list_cache.invalidate_session_list_cache()
    signatures = [
        (f"source-{index}", bool(index % 2))
        for index in range(list_cache._SESSION_LIST_CACHE_MAX_ENTRIES + 2)
    ]

    for index, signature in enumerate(signatures):
        list_cache.set_session_list_cache(
            [{"id": f"session-{index}", "title": f"session-{index}"}],
            now=100.0 + index,
            signature=signature,
            conversation_count=index + 1,
            agent_count=2,
        )

    with list_cache._SESSION_LIST_CACHE_LOCK:
        entries = list_cache._SESSION_LIST_CACHE["entries"]
        assert len(entries) == list_cache._SESSION_LIST_CACHE_MAX_ENTRIES
        assert signatures[0] not in entries
        assert signatures[1] not in entries
        assert signatures[-1] in entries
    list_cache.invalidate_session_list_cache()


def test_session_list_cache_serves_last_good_snapshot_on_signature_churn() -> None:
    project_root = "C:/project-root"
    seeded_signature = (
        (
            project_root,
            ("store.sqlite3", 1, 10),
            ("store.sqlite3-wal", 1, 10),
            ("agents.json", 1, 10),
        ),
        False,
    )
    churned_signature = (
        (
            project_root,
            ("store.sqlite3", 1, 11),
            ("store.sqlite3-wal", 1, 12),
            ("agents.json", 1, 13),
        ),
        False,
    )
    list_cache.invalidate_session_list_cache()
    list_cache.set_session_list_cache(
        [{"id": "s1", "title": "alpha"}],
        now=500.0,
        signature=seeded_signature,
        conversation_count=1,
        agent_count=2,
    )

    # Signature churn (SQLite/WAL/registry writes) misses the exact entry but
    # keeps the stale snapshot for the same source.
    assert list_cache.get_session_list_cache(now=501.0, signature=churned_signature) is None
    stale = list_cache.get_last_good_session_list_snapshot(
        now=530.0,
        signature=churned_signature,
    )
    assert stale is not None
    sessions, age_ms, conversation_count, agent_count = stale
    assert sessions[0]["id"] == "s1"
    assert age_ms == 30000
    assert conversation_count == 1
    assert agent_count == 2

    # A different source must not inherit the snapshot.
    assert (
        list_cache.get_last_good_session_list_snapshot(
            now=530.0,
            signature=((("C:/other-root", ("store", 1, 1)), False)),
        )
        is None
    )
    expired = list_cache.get_last_good_session_list_snapshot(
        now=500.0 + list_cache.SESSION_LIST_STALE_SERVE_MAX_SECONDS + 1.0,
        signature=churned_signature,
    )
    assert expired is None

    # Explicit mutations purge the stale slot so the next read rebuilds.
    list_cache.invalidate_session_list_cache()
    assert (
        list_cache.get_last_good_session_list_snapshot(
            now=531.0,
            signature=churned_signature,
        )
        is None
    )
    with list_cache._SESSION_LIST_CACHE_LOCK:
        list_cache._SESSION_LIST_CACHE.clear()


def test_reserve_session_list_refresh_coalesces_and_releases() -> None:
    signature = ("refresh-signature", False)
    with list_cache._SESSION_LIST_CACHE_LOCK:
        list_cache._SESSION_LIST_CACHE.clear()

    first = list_cache.reserve_session_list_refresh(now=700.0, signature=signature)
    assert first == 700.0
    assert list_cache.is_session_list_refresh_reserved(signature=signature) is True
    # Second caller coalesces into the running refresh.
    assert list_cache.reserve_session_list_refresh(now=701.0, signature=signature) is None
    # A different source has its own refresh worker.
    assert (
        list_cache.reserve_session_list_refresh(now=701.0, signature=("other", True))
        == 701.0
    )

    list_cache.release_session_list_refresh(started_at=first, signature=signature)
    assert list_cache.is_session_list_refresh_reserved(signature=signature) is False
    assert (
        list_cache.reserve_session_list_refresh(now=702.0, signature=signature) == 702.0
    )
    list_cache.release_session_list_refresh(started_at=702.0, signature=signature)
    with list_cache._SESSION_LIST_CACHE_LOCK:
        list_cache._SESSION_LIST_CACHE.clear()


def test_begin_reserves_under_caller_timestamp_after_waiting(monkeypatch) -> None:
    signature = ("waited-owner-signature", False)
    with list_cache._SESSION_LIST_CACHE_LOCK:
        list_cache._SESSION_LIST_CACHE.clear()
    cached, should_build, waited = list_cache.begin_session_list_cache_build(
        now=10.0,
        signature=signature,
    )
    assert (cached, should_build, waited) == (None, True, False)

    waiter_entered = threading.Event()
    original_wait = list_cache._SESSION_LIST_CACHE_CONDITION.wait

    def observed_wait(timeout=None):
        waiter_entered.set()
        return original_wait(timeout)

    monkeypatch.setattr(
        list_cache._SESSION_LIST_CACHE_CONDITION,
        "wait",
        observed_wait,
    )
    monkeypatch.setattr(list_cache, "_perf_counter", lambda: 10.25)

    results: list[tuple[object, bool, bool]] = []
    waiter = threading.Thread(
        target=lambda: results.append(
            list_cache.begin_session_list_cache_build(
                now=10.2,
                signature=signature,
            )
        )
    )
    waiter.start()
    assert waiter_entered.wait(timeout=1.0)

    # The original owner abandons the slot without publishing.
    list_cache.finish_session_list_cache_build(signature=signature)
    waiter.join(timeout=1.0)
    assert not waiter.is_alive()
    assert results == [(None, True, True)]

    # The waiter now owns the slot under its own request timestamp.
    list_cache.finish_session_list_cache_build(
        signature=signature,
        sessions=[{"id": "waited-built", "title": "complete"}],
        started_at=10.2,
        conversation_count=1,
        agent_count=1,
    )
    published = list_cache.get_session_list_cache(now=10.3, signature=signature)
    assert published is not None
    assert published[0][0]["id"] == "waited-built"
    with list_cache._SESSION_LIST_CACHE_LOCK:
        list_cache._SESSION_LIST_CACHE.clear()


def test_session_list_cache_keeps_slow_live_builder_as_single_owner(monkeypatch) -> None:
    signature = ("slow-inflight-signature", False)
    list_cache.invalidate_session_list_cache()
    cached, should_build, waited = list_cache.begin_session_list_cache_build(
        now=10.0,
        signature=signature,
    )
    assert cached is None
    assert should_build is True
    assert waited is False

    waiter_count = 9
    all_waiters_started = threading.Event()
    waiting_thread_ids: set[int] = set()
    waiting_thread_ids_lock = threading.Lock()
    original_wait = list_cache._SESSION_LIST_CACHE_CONDITION.wait

    def observed_wait(timeout=None):
        with waiting_thread_ids_lock:
            waiting_thread_ids.add(threading.get_ident())
            if len(waiting_thread_ids) == waiter_count:
                all_waiters_started.set()
        return original_wait(timeout)

    monkeypatch.setattr(
        list_cache._SESSION_LIST_CACHE_CONDITION,
        "wait",
        observed_wait,
    )
    monkeypatch.setattr(list_cache, "_perf_counter", lambda: 13.0)

    results: list[tuple[object, bool, bool]] = []
    waiters = [
        threading.Thread(
            target=lambda: results.append(
                list_cache.begin_session_list_cache_build(
                    now=13.0,
                    signature=signature,
                )
            )
        )
        for _ in range(waiter_count)
    ]
    for waiter in waiters:
        waiter.start()

    assert all_waiters_started.wait(timeout=1.0)
    list_cache.finish_session_list_cache_build(
        signature=signature,
        sessions=[{"id": "slow-built", "title": "complete"}],
        started_at=10.0,
        conversation_count=1,
        agent_count=1,
    )
    for waiter in waiters:
        waiter.join(timeout=1.0)

    assert all(not waiter.is_alive() for waiter in waiters)
    assert len(results) == waiter_count
    for cached, should_build, waited in results:
        assert should_build is False
        assert waited is True
        assert cached is not None
        assert cached[0][0]["id"] == "slow-built"
    list_cache.invalidate_session_list_cache()
