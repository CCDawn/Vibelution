from __future__ import annotations

import threading

from core.web.services import runtime_service


def test_runtime_summary_http_requests_share_initial_computation(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def build_summary():
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=2)
        return {"status": "ready"}

    runtime_service._reset_runtime_summary_http_cache()
    monkeypatch.setattr(runtime_service, "get_runtime_summary", build_summary)

    first = runtime_service.get_runtime_summary_http_future()
    assert started.wait(timeout=1)
    second = runtime_service.get_runtime_summary_http_future()

    assert first is second
    assert calls == 1
    release.set()
    assert first.result(timeout=1) == {"status": "ready"}

    cached = runtime_service.get_runtime_summary_http_future()
    assert cached.done()
    assert cached.result() == {"status": "ready"}
    assert calls == 1
    runtime_service._reset_runtime_summary_http_cache()


def test_runtime_summary_http_returns_stale_snapshot_while_refreshing(monkeypatch):
    refresh_started = threading.Event()
    refresh_release = threading.Event()

    runtime_service._reset_runtime_summary_http_cache()
    runtime_service._RUNTIME_SUMMARY_HTTP_SNAPSHOT = {"status": "stale"}
    runtime_service._RUNTIME_SUMMARY_HTTP_SNAPSHOT_AT = 0.0

    def refresh_summary():
        refresh_started.set()
        assert refresh_release.wait(timeout=2)
        return {"status": "fresh"}

    monkeypatch.setattr(runtime_service, "get_runtime_summary", refresh_summary)

    stale = runtime_service.get_runtime_summary_http_future()
    assert stale.done()
    assert stale.result() == {"status": "stale"}
    assert refresh_started.wait(timeout=1)

    concurrent = runtime_service.get_runtime_summary_http_future()
    assert concurrent.done()
    assert concurrent.result() == {"status": "stale"}
    refresh_release.set()
    runtime_service._RUNTIME_SUMMARY_HTTP_INFLIGHT.result(timeout=1)
    runtime_service._reset_runtime_summary_http_cache()
