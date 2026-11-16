"""Usage summary read-through cache: TTL reuse, single-flight, isolation."""

from __future__ import annotations

import threading
import time

import pytest

from core.infrastructure.read_through_cache import ReadThroughCache
from core.web.services import usage_summary_cache


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_ttl_reuse_and_expiry() -> None:
    clock = _FakeClock()
    cache = ReadThroughCache(name="t", clock=clock, wait_timeout_seconds=1.0)
    calls: list[int] = []

    def compute() -> str:
        calls.append(1)
        return f"value-{len(calls)}"

    assert cache.get_or_compute("k", compute, 8.0) == "value-1"
    clock.advance(7.9)
    assert cache.get_or_compute("k", compute, 8.0) == "value-1"
    assert len(calls) == 1

    clock.advance(0.2)
    assert cache.get_or_compute("k", compute, 8.0) == "value-2"
    assert len(calls) == 2


def test_distinct_keys_do_not_share_values() -> None:
    clock = _FakeClock()
    cache = ReadThroughCache(name="t", clock=clock, wait_timeout_seconds=1.0)
    seen: list[str] = []

    def compute_for(key: str):
        def compute() -> str:
            seen.append(key)
            return key.upper()

        return compute

    assert cache.get_or_compute("a", compute_for("a"), 8.0) == "A"
    assert cache.get_or_compute("b", compute_for("b"), 8.0) == "B"
    assert seen == ["a", "b"]


def test_concurrent_same_key_computes_once() -> None:
    clock = _FakeClock()
    cache = ReadThroughCache(name="t", clock=clock, wait_timeout_seconds=1.0)
    started = threading.Barrier(6)
    release = threading.Event()
    calls: list[int] = []
    results: list[str] = []
    guard = threading.Lock()

    def compute() -> str:
        with guard:
            calls.append(1)
        release.wait(2.0)
        return "shared"

    def worker() -> None:
        started.wait(2.0)
        value = cache.get_or_compute("k", compute, 8.0)
        with guard:
            results.append(value)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    release.set()
    for thread in threads:
        thread.join(5.0)

    assert results == ["shared"] * 6
    assert len(calls) == 1
    assert cache.stats()["joins"] >= 0


def test_failed_leader_is_not_shared() -> None:
    clock = _FakeClock()
    cache = ReadThroughCache(name="t", clock=clock, wait_timeout_seconds=1.0)
    release = threading.Event()
    attempts: list[str] = []
    outcomes: list[str] = []
    guard = threading.Lock()

    def failing() -> str:
        with guard:
            attempts.append("leader")
        release.wait(2.0)
        raise RuntimeError("leader boom")

    def succeeding() -> str:
        with guard:
            attempts.append("waiter")
        return "waiter-value"

    def leader() -> None:
        try:
            cache.get_or_compute("k", failing, 8.0)
        except RuntimeError:
            with guard:
                outcomes.append("leader-raised")

    thread = threading.Thread(target=leader)
    thread.start()
    # Give the leader time to enter its flight before the waiter arrives.
    for _ in range(200):
        if cache.stats()["flights"] == 1:
            break
        time.sleep(0.005)
    release.set()
    assert cache.get_or_compute("k", succeeding, 8.0) == "waiter-value"
    thread.join(5.0)

    assert outcomes == ["leader-raised"]
    assert "waiter" in attempts
    # A failed computation must not poison the next attempt.
    assert cache.get_or_compute("k", lambda: "later", 8.0) == "later"


def test_should_cache_can_reject_value() -> None:
    clock = _FakeClock()
    cache = ReadThroughCache(name="t", clock=clock, wait_timeout_seconds=1.0)
    calls: list[int] = []

    def empty() -> dict:
        calls.append(1)
        return {}

    assert cache.get_or_compute("k", empty, 8.0, should_cache=bool) == {}
    assert cache.get_or_compute("k", empty, 8.0, should_cache=bool) == {}
    assert len(calls) == 2


def test_usage_summary_callers_get_isolated_copies(monkeypatch) -> None:
    usage_summary_cache.reset_usage_summary_cache_for_tests()
    calls: list[int] = []

    def fake_summary(**kwargs) -> dict:
        calls.append(1)
        return {"scope": kwargs["scope"], "total": 7.0, "breakdowns": {"models": []}}

    monkeypatch.setattr(usage_summary_cache, "build_usage_summary", fake_summary)

    first = usage_summary_cache.get_usage_summary_cached(scope="global")
    first["total"] = 999.0
    first["breakdowns"]["models"].append({"name": "mutated"})

    second = usage_summary_cache.get_usage_summary_cached(scope="global")
    assert second["total"] == 7.0
    assert second["breakdowns"]["models"] == []
    assert len(calls) == 1


def test_usage_summary_cache_key_separates_filters() -> None:
    usage_summary_cache.reset_usage_summary_cache_for_tests()
    calls: list[tuple] = []

    def fake_summary(**kwargs) -> dict:
        calls.append((kwargs["scope"], kwargs["session_id"]))
        return {"scope": kwargs["scope"], "sessionId": kwargs["session_id"]}

    monkeypatch_target = usage_summary_cache.build_usage_summary
    try:
        usage_summary_cache.build_usage_summary = fake_summary

        a = usage_summary_cache.get_usage_summary_cached(scope="session", session_id="s1")
        b = usage_summary_cache.get_usage_summary_cached(scope="session", session_id="s2")
        a2 = usage_summary_cache.get_usage_summary_cached(scope="session", session_id="s1")
    finally:
        usage_summary_cache.build_usage_summary = monkeypatch_target

    assert a == {"scope": "session", "sessionId": "s1"}
    assert b == {"scope": "session", "sessionId": "s2"}
    assert a2 == a
    assert calls == [("session", "s1"), ("session", "s2")]


@pytest.fixture(autouse=True)
def _reset_usage_cache() -> None:
    usage_summary_cache.reset_usage_summary_cache_for_tests()
    yield
    usage_summary_cache.reset_usage_summary_cache_for_tests()
