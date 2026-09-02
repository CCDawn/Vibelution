"""Global per-provider rate limiting and bounded retry/backoff tests.

Covers the C6 source-collection search transport: parallel worker threads
must share one rate-limit window per provider, transient HTTP failures must
retry with exponential backoff (429 honoring Retry-After), and one provider's
throttle must never block another provider's requests.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest
from pyrate_limiter import Rate

from core.web.services.team_workflow.source_collection import search_execution

_CROSSREF_PAYLOAD = {
    "message": {
        "items": [
            {"DOI": "10.5555/rate-limit-test", "title": ["Rate limiting under concurrency"]}
        ]
    }
}


class _FakeJsonResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._body


@pytest.fixture
def unlimited_rate_limits(monkeypatch):
    """Replace the real per-provider windows with effectively unlimited ones.

    Individual tests re-inject a small window when they need to observe the
    throttle itself; clearing the registry after each test keeps lazily
    created limiters from leaking across tests.
    """
    monkeypatch.setattr(
        search_execution,
        "_SOURCE_COLLECTION_PROVIDER_RATE_LIMITS",
        {
            "arxiv_api": Rate(1000, 1),
            "crossref_rest_api": Rate(1000, 1),
            "openalex_api": Rate(1000, 1),
        },
    )
    search_execution._SOURCE_COLLECTION_RATE_LIMITERS.clear()
    yield
    search_execution._SOURCE_COLLECTION_RATE_LIMITERS.clear()


@pytest.fixture(autouse=True)
def clear_429_cooldown_windows():
    """Keep the process-wide 429 cooldown registry from leaking across tests."""
    search_execution._SOURCE_COLLECTION_429_COOLDOWNS.clear()
    yield
    search_execution._SOURCE_COLLECTION_429_COOLDOWNS.clear()


def _install_fake_transport(monkeypatch, handler) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", handler)


def _crossref_handler(recorder, sequence: list):
    def _handler(request, timeout=0):
        recorder.append(request.full_url)
        item = sequence.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return _handler


def _run_crossref_query(provider: str = "crossref_rest_api") -> dict:
    return search_execution._execute_source_collection_query(
        {"query": "rate limiting under concurrency", "sourceType": "paper"},
        max_results=2,
        provider=provider,
    )


# ---------------------------------------------------------------------------
# 1. Parallel threads share one rate-limit window per provider.
# ---------------------------------------------------------------------------


def test_parallel_threads_share_one_rate_limit_window(monkeypatch, unlimited_rate_limits):
    monkeypatch.setitem(
        search_execution._SOURCE_COLLECTION_PROVIDER_RATE_LIMITS,
        "crossref_rest_api",
        Rate(1, 200),
    )
    search_execution._SOURCE_COLLECTION_RATE_LIMITERS.clear()
    stamps: list[float] = []

    def _handler(request, timeout=0):
        stamps.append(time.monotonic())
        return _FakeJsonResponse(_CROSSREF_PAYLOAD)

    _install_fake_transport(monkeypatch, _handler)

    barrier = threading.Barrier(4)
    errors: list[Exception] = []

    def _worker():
        try:
            barrier.wait(timeout=5)
            response = _run_crossref_query()
            assert not response.get("error"), response.get("error")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not errors
    assert len(stamps) == 4
    ordered = sorted(stamps)
    gaps = [later - earlier for earlier, later in zip(ordered, ordered[1:])]
    # A 1-permit / 200ms window must space real HTTP attempts out; the small
    # tolerance absorbs the limiter's 50ms buffer and scheduler jitter.
    assert all(gap >= 0.14 for gap in gaps), gaps


# ---------------------------------------------------------------------------
# 2. Bounded retry with exponential backoff.
# ---------------------------------------------------------------------------


def test_transient_url_errors_retry_with_exponential_backoff(monkeypatch, unlimited_rate_limits):
    recorder: list[str] = []
    delays: list[float] = []
    monkeypatch.setattr(search_execution, "_source_collection_backoff_sleep", delays.append)
    sequence = [
        urllib.error.URLError("connection reset"),
        urllib.error.URLError("connection reset"),
        _FakeJsonResponse(_CROSSREF_PAYLOAD),
    ]
    _install_fake_transport(monkeypatch, _crossref_handler(recorder, sequence))

    response = _run_crossref_query()

    assert not response.get("error")
    assert len(recorder) == 3
    assert delays == [1.0, 2.0]
    results = response.get("results") or []
    assert len(results) == 1
    assert "Rate limiting" in str(results[0].get("title"))


def test_rate_limit_429_honors_retry_after_header(monkeypatch, unlimited_rate_limits):
    recorder: list[str] = []
    delays: list[float] = []
    monkeypatch.setattr(search_execution, "_source_collection_backoff_sleep", delays.append)
    sequence = [
        urllib.error.HTTPError(
            "https://api.crossref.org/works",
            429,
            "Too Many Requests",
            {"Retry-After": "7"},
            None,
        ),
        _FakeJsonResponse(_CROSSREF_PAYLOAD),
    ]
    _install_fake_transport(monkeypatch, _crossref_handler(recorder, sequence))

    response = _run_crossref_query()

    assert not response.get("error")
    assert len(recorder) == 2
    assert delays == [7.0]


def test_rate_limit_429_without_header_uses_default_backoff(monkeypatch, unlimited_rate_limits):
    recorder: list[str] = []
    delays: list[float] = []
    monkeypatch.setattr(search_execution, "_source_collection_backoff_sleep", delays.append)
    sequence = [
        urllib.error.HTTPError(
            "https://api.crossref.org/works",
            429,
            "Too Many Requests",
            {},
            None,
        ),
        _FakeJsonResponse(_CROSSREF_PAYLOAD),
    ]
    _install_fake_transport(monkeypatch, _crossref_handler(recorder, sequence))

    response = _run_crossref_query()

    assert not response.get("error")
    assert len(recorder) == 2
    assert delays == [5.0]


def test_server_errors_retry_three_times_then_fail(monkeypatch, unlimited_rate_limits):
    recorder: list[str] = []
    delays: list[float] = []
    monkeypatch.setattr(search_execution, "_source_collection_backoff_sleep", delays.append)
    sequence = [
        urllib.error.HTTPError("https://api.crossref.org/works", 500, "boom", {}, None)
        for _ in range(4)
    ]
    _install_fake_transport(monkeypatch, _crossref_handler(recorder, sequence))

    response = _run_crossref_query()

    assert response.get("error")
    assert len(recorder) == 4
    assert delays == [1.0, 2.0, 4.0]


def test_client_error_does_not_retry(monkeypatch, unlimited_rate_limits):
    recorder: list[str] = []
    delays: list[float] = []
    monkeypatch.setattr(search_execution, "_source_collection_backoff_sleep", delays.append)
    sequence = [
        urllib.error.HTTPError("https://api.crossref.org/works", 404, "not found", {}, None)
    ]
    _install_fake_transport(monkeypatch, _crossref_handler(recorder, sequence))

    response = _run_crossref_query()

    assert response.get("error")
    assert len(recorder) == 1
    assert delays == []


# ---------------------------------------------------------------------------
# 3. One provider's throttle must not block another provider.
# ---------------------------------------------------------------------------


def test_limiters_are_independent_per_provider(monkeypatch, unlimited_rate_limits):
    monkeypatch.setitem(
        search_execution._SOURCE_COLLECTION_PROVIDER_RATE_LIMITS,
        "arxiv_api",
        Rate(1, 1000),
    )
    search_execution._SOURCE_COLLECTION_RATE_LIMITERS.clear()

    limiter_arxiv = search_execution._source_collection_rate_limiter("arxiv_api")
    limiter_crossref = search_execution._source_collection_rate_limiter("crossref_rest_api")
    assert limiter_arxiv is not None
    assert limiter_crossref is not None
    assert limiter_arxiv is not limiter_crossref

    # Occupy the arXiv window, then prove a crossref permit is still served
    # immediately while another thread sits blocked on arXiv.
    limiter_arxiv.try_acquire("arxiv_api")
    blocked = threading.Thread(target=lambda: limiter_arxiv.try_acquire("arxiv_api"))
    blocked.start()
    time.sleep(0.05)
    start = time.monotonic()
    limiter_crossref.try_acquire("crossref_rest_api")
    elapsed = time.monotonic() - start
    assert elapsed < 0.5, elapsed
    blocked.join(timeout=5)
    assert not blocked.is_alive()


# ---------------------------------------------------------------------------
# 4. Crossref requests carry the polite-pool mailto contact.
# ---------------------------------------------------------------------------


def test_crossref_request_url_carries_mailto(monkeypatch, unlimited_rate_limits):
    recorder: list[str] = []
    _install_fake_transport(
        monkeypatch, _crossref_handler(recorder, [_FakeJsonResponse(_CROSSREF_PAYLOAD)])
    )

    response = _run_crossref_query()

    assert not response.get("error")
    assert "mailto=" in recorder[0]
    # The contact is injected on the wire only; the reported searchUrl stays
    # free of it so execution-event refs stay clean.
    assert "mailto=" not in str(response.get("searchUrl"))


def test_url_with_mailto_is_idempotent():
    url = "https://api.crossref.org/works?query=test"
    once = search_execution._source_collection_url_with_mailto(url)
    twice = search_execution._source_collection_url_with_mailto(once)
    assert once.count("mailto=") == 1
    assert twice == once


# ---------------------------------------------------------------------------
# 5. Retry-After clamping and the per-execution backoff budget.
#
# Production incident 2026-09-02: OpenAlex answered a 429 with a huge
# Retry-After and two background collectors slept on it indefinitely,
# hanging the run at "资料搜集 7/9".  A server Retry-After is honored only
# up to a cap, and one search execution may spend at most a bounded total
# budget sleeping in backoff.
# ---------------------------------------------------------------------------


def test_huge_retry_after_is_clamped_to_cap(monkeypatch, unlimited_rate_limits):
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_RETRY_AFTER_MAX_SECONDS", "30")
    assert search_execution._source_collection_retry_after_seconds({"Retry-After": "3600"}) == 30.0

    recorder: list[str] = []
    delays: list[float] = []
    monkeypatch.setattr(search_execution, "_source_collection_backoff_sleep", delays.append)
    sequence = [
        urllib.error.HTTPError(
            "https://api.crossref.org/works",
            429,
            "Too Many Requests",
            {"Retry-After": "3600"},
            None,
        ),
        _FakeJsonResponse(_CROSSREF_PAYLOAD),
    ]
    _install_fake_transport(monkeypatch, _crossref_handler(recorder, sequence))

    response = _run_crossref_query()

    # The provider asked for an hour; the wait actually taken is the cap.
    assert not response.get("error")
    assert len(recorder) == 2
    assert delays == [30.0]


def test_retry_after_cap_env_is_configurable(monkeypatch):
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_RETRY_AFTER_MAX_SECONDS", "45")
    assert search_execution._source_collection_retry_after_seconds({"Retry-After": "3600"}) == 45.0
    assert search_execution._source_collection_retry_after_seconds({"Retry-After": "44.5"}) == 44.5


def test_retry_after_invalid_or_missing_keeps_existing_semantics(monkeypatch):
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_RETRY_AFTER_MAX_SECONDS", "30")
    # No header / HTTP-date form / negative seconds keep the legacy default
    # (parse failures and the pre-existing max(0.0, ...) clamp) unchanged.
    assert search_execution._source_collection_retry_after_seconds(None) == 5.0
    assert search_execution._source_collection_retry_after_seconds({}) == 5.0
    assert search_execution._source_collection_retry_after_seconds({"Retry-After": "soon"}) == 5.0
    assert search_execution._source_collection_retry_after_seconds({"Retry-After": "-3"}) == 0.0
    # Values at or below the cap pass through untouched.
    assert search_execution._source_collection_retry_after_seconds({"Retry-After": "7"}) == 7.0
    assert search_execution._source_collection_retry_after_seconds({"Retry-After": "30"}) == 30.0


def test_backoff_budget_exhausted_stops_sleeping_and_fails(monkeypatch, unlimited_rate_limits):
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_RETRY_AFTER_MAX_SECONDS", "30")
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_BACKOFF_BUDGET_SECONDS", "5")
    recorder: list[str] = []
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    sequence = [
        urllib.error.HTTPError(
            "https://api.crossref.org/works",
            429,
            "Too Many Requests",
            {"Retry-After": "10"},
            None,
        )
        for _ in range(8)
    ]
    _install_fake_transport(monkeypatch, _crossref_handler(recorder, sequence))

    search_execution._source_collection_activate_backoff_budget()
    try:
        response = _run_crossref_query()
    finally:
        search_execution._source_collection_clear_backoff_budget()

    # The first 429 spends min(10, 5) = 5s of budget; afterwards no sleep at
    # all, the bounded retry loop burns its remaining attempts immediately,
    # and the last error surfaces through the existing per-query error path.
    assert slept == [5.0]
    assert response.get("error")
    assert len(recorder) == search_execution._SOURCE_COLLECTION_SEARCH_HTTP_MAX_ATTEMPTS


def test_backoff_sleep_charges_budget_and_resets_per_execution(monkeypatch):
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_BACKOFF_BUDGET_SECONDS", "120")
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)

    search_execution._source_collection_activate_backoff_budget()
    assert search_execution._SOURCE_COLLECTION_BACKOFF_BUDGET_STATE.remaining_seconds == 120.0
    search_execution._source_collection_backoff_sleep(30)
    assert slept == [30.0]
    assert search_execution._SOURCE_COLLECTION_BACKOFF_BUDGET_STATE.remaining_seconds == 90.0
    search_execution._source_collection_clear_backoff_budget()

    # A fresh execution starts with the full budget again.
    search_execution._source_collection_activate_backoff_budget()
    assert search_execution._SOURCE_COLLECTION_BACKOFF_BUDGET_STATE.remaining_seconds == 120.0
    search_execution._source_collection_clear_backoff_budget()


def test_search_execution_impl_scopes_backoff_budget(monkeypatch):
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_BACKOFF_BUDGET_SECONDS", "120")
    seen: list[float | None] = []

    def _fake_body(team_id, run_id, payload=None):
        seen.append(
            getattr(search_execution._SOURCE_COLLECTION_BACKOFF_BUDGET_STATE, "remaining_seconds", None)
        )
        return {"status": "executed"}

    monkeypatch.setattr(search_execution, "_execute_source_collection_search_body", _fake_body)

    result = search_execution._execute_source_collection_search_impl("team", "run")

    # The budget is active for the whole execution body and cleared after it,
    # including on failure, so other threads and later calls are unaffected.
    assert result == {"status": "executed"}
    assert seen == [120.0]
    assert getattr(search_execution._SOURCE_COLLECTION_BACKOFF_BUDGET_STATE, "remaining_seconds", None) is None


def test_search_execution_impl_clears_budget_on_failure(monkeypatch):
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_BACKOFF_BUDGET_SECONDS", "120")

    def _failing_body(team_id, run_id, payload=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(search_execution, "_execute_source_collection_search_body", _failing_body)

    with pytest.raises(RuntimeError):
        search_execution._execute_source_collection_search_impl("team", "run")
    assert getattr(search_execution._SOURCE_COLLECTION_BACKOFF_BUDGET_STATE, "remaining_seconds", None) is None


def test_search_execution_budget_default_without_env(monkeypatch):
    monkeypatch.delenv("VIBELUTION_SOURCE_COLLECTION_BACKOFF_BUDGET_SECONDS", raising=False)
    monkeypatch.delenv("VIBELUTION_SOURCE_COLLECTION_RETRY_AFTER_MAX_SECONDS", raising=False)
    assert search_execution._source_collection_backoff_budget_seconds() == 120.0
    assert search_execution._source_collection_retry_after_max_seconds() == 30.0
    # Invalid or non-positive env values fall back to the defaults.
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_BACKOFF_BUDGET_SECONDS", "nonsense")
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_RETRY_AFTER_MAX_SECONDS", "0")
    assert search_execution._source_collection_backoff_budget_seconds() == 120.0
    assert search_execution._source_collection_retry_after_max_seconds() == 30.0


# ---------------------------------------------------------------------------
# 6. Provider-level 429 cooldown windows.
#
# Live evidence 2026-09-02: openalex_api answered 429 through an entire run
# while every retry still waited out its Retry-After clamp, burning 1-2
# minutes of wall-clock per query.  A provider that proves hard-throttled is
# skipped without any HTTP call for a cooldown window instead; the window
# expires on its own, escalates on relapse, and any successful call resets
# the provider completely.
# ---------------------------------------------------------------------------


def _throttled_crossref_errors(count: int, headers: dict | None = None) -> list:
    return [
        urllib.error.HTTPError(
            "https://api.crossref.org/works",
            429,
            "Too Many Requests",
            headers or {},
            None,
        )
        for _ in range(count)
    ]


def test_429_exhaustion_cools_provider_and_next_query_fast_fails(monkeypatch, unlimited_rate_limits):
    recorder: list[str] = []
    delays: list[float] = []
    monkeypatch.setattr(search_execution, "_source_collection_backoff_sleep", delays.append)
    # No Retry-After header: the provider is throttled but never says for how
    # long, so the cooldown opens only once the whole retry ladder failed.
    sequence = _throttled_crossref_errors(8)
    _install_fake_transport(monkeypatch, _crossref_handler(recorder, sequence))

    throttled = _run_crossref_query()
    assert throttled.get("error")
    assert len(recorder) == search_execution._SOURCE_COLLECTION_SEARCH_HTTP_MAX_ATTEMPTS
    assert search_execution._source_collection_provider_cooldown_remaining("crossref_rest_api") > 0

    # The next query skips the provider entirely: no HTTP call, no backoff.
    cooled = _run_crossref_query()
    assert cooled.get("errorReason") == "cooldown"
    assert "cooldown" in str(cooled.get("error"))
    assert len(recorder) == search_execution._SOURCE_COLLECTION_SEARCH_HTTP_MAX_ATTEMPTS
    # 429 waits follow Retry-After (5s default without a header), not the
    # exponential ladder; the cooled second query adds no waits at all.
    assert delays == [5.0, 5.0, 5.0]


def test_retry_after_beyond_cap_enters_cooldown_at_first_429(monkeypatch, unlimited_rate_limits):
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_RETRY_AFTER_MAX_SECONDS", "30")
    recorder: list[str] = []
    delays: list[float] = []
    monkeypatch.setattr(search_execution, "_source_collection_backoff_sleep", delays.append)
    sequence = [
        *_throttled_crossref_errors(1, {"Retry-After": "3600"}),
        _FakeJsonResponse(_CROSSREF_PAYLOAD),
    ]
    _install_fake_transport(monkeypatch, _crossref_handler(recorder, sequence))

    response = _run_crossref_query()
    # The lucky retry still succeeds within this call, but the provider asked
    # for an hour: the cooldown window stays open so concurrent or follow-up
    # queries skip the clamp ladder instead of repeating it.
    assert not response.get("error")
    assert search_execution._source_collection_provider_cooldown_remaining("crossref_rest_api") > 0

    cooled = _run_crossref_query()
    assert cooled.get("errorReason") == "cooldown"
    assert len(recorder) == 2


def test_cooldown_expiry_recovers_and_success_resets_state(monkeypatch, unlimited_rate_limits):
    recorder: list[str] = []
    monkeypatch.setattr(search_execution, "_source_collection_backoff_sleep", lambda _seconds: None)
    sequence = _throttled_crossref_errors(4)
    _install_fake_transport(monkeypatch, _crossref_handler(recorder, sequence))
    assert _run_crossref_query().get("error")
    assert search_execution._source_collection_provider_cooldown_remaining("crossref_rest_api") > 0

    # Simulate the cooldown window elapsing.
    search_execution._SOURCE_COLLECTION_429_COOLDOWNS["crossref_rest_api"]["until"] = time.monotonic() - 1.0

    sequence.append(_FakeJsonResponse(_CROSSREF_PAYLOAD))
    recovered = _run_crossref_query()
    assert not recovered.get("error")
    assert len(recorder) == 5
    # The successful call resets the cooldown state and escalation streak.
    assert search_execution._SOURCE_COLLECTION_429_COOLDOWNS.get("crossref_rest_api") is None


def test_consecutive_cooldowns_escalate_and_success_resets_streak(monkeypatch):
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_429_COOLDOWN_SECONDS", "60")
    assert search_execution._source_collection_enter_provider_cooldown("openalex_api") == 60.0
    search_execution._SOURCE_COLLECTION_429_COOLDOWNS["openalex_api"]["until"] = time.monotonic() - 1.0
    assert search_execution._source_collection_enter_provider_cooldown("openalex_api") == 120.0
    search_execution._SOURCE_COLLECTION_429_COOLDOWNS["openalex_api"]["until"] = time.monotonic() - 1.0
    assert search_execution._source_collection_enter_provider_cooldown("openalex_api") == 240.0

    # A successful call resets the streak back to the base window.
    search_execution._source_collection_clear_provider_cooldown("openalex_api")
    assert search_execution._source_collection_enter_provider_cooldown("openalex_api") == 60.0


def test_cooldown_escalation_is_capped_at_30_minutes(monkeypatch):
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_429_COOLDOWN_SECONDS", "300")
    search_execution._SOURCE_COLLECTION_429_COOLDOWNS["openalex_api"] = {
        "until": time.monotonic() - 1.0,
        "streak": 12.0,
    }
    assert search_execution._source_collection_enter_provider_cooldown("openalex_api") == 1800.0


def test_429_cooldown_env_is_clamped_or_defaults(monkeypatch):
    monkeypatch.delenv("VIBELUTION_SOURCE_COLLECTION_429_COOLDOWN_SECONDS", raising=False)
    assert search_execution._source_collection_429_cooldown_seconds() == 300.0
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_429_COOLDOWN_SECONDS", "10")
    assert search_execution._source_collection_429_cooldown_seconds() == 60.0
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_429_COOLDOWN_SECONDS", "99999")
    assert search_execution._source_collection_429_cooldown_seconds() == 1800.0
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_429_COOLDOWN_SECONDS", "nonsense")
    assert search_execution._source_collection_429_cooldown_seconds() == 300.0
    monkeypatch.setenv("VIBELUTION_SOURCE_COLLECTION_429_COOLDOWN_SECONDS", "0")
    assert search_execution._source_collection_429_cooldown_seconds() == 300.0


def test_cooldown_is_scoped_per_provider(monkeypatch, unlimited_rate_limits):
    search_execution._source_collection_enter_provider_cooldown("openalex_api")
    assert search_execution._source_collection_provider_cooldown_error("openalex_api")
    # Another provider is untouched and still performs real HTTP.
    assert search_execution._source_collection_provider_cooldown_error("crossref_rest_api") == ""
    recorder: list[str] = []
    _install_fake_transport(
        monkeypatch, _crossref_handler(recorder, [_FakeJsonResponse(_CROSSREF_PAYLOAD)])
    )
    response = _run_crossref_query()
    assert not response.get("error")
    assert len(recorder) == 1


def test_execution_event_carries_reason_field():
    assignment = {"agentRole": "source_finder", "agentId": "agent-1", "assignmentId": "asg-1"}
    event = search_execution._source_collection_execution_event(
        "search.failed",
        assignment=assignment,
        title="Search failed: predictive coding",
        summary="crossref_rest_api is in a 429 cooldown window for another 240s.",
        status="blocked",
        query={"queryId": "q-1", "query": "predictive coding"},
        refs=["q-1", "crossref_rest_api"],
        provider="crossref_rest_api",
        reason="cooldown",
    )
    # The cooldown skip reuses the blocked search.failed shape plus a reason.
    assert event["eventType"] == "search.failed"
    assert event["status"] == "blocked"
    assert event["reason"] == "cooldown"
    default_event = search_execution._source_collection_execution_event(
        "search.executed",
        assignment=assignment,
        title="Searched crossref_rest_api",
        summary="Fetched 1 metadata result(s).",
        status="completed",
    )
    assert default_event["reason"] == ""
