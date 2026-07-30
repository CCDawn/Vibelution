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
