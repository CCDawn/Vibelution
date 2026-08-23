from __future__ import annotations

import asyncio
import json
import queue

import pytest

from core.web.services.session import publish


class _FakeSessionService:
    _SESSION_STREAM_QUEUE_SIZE = 2
    _SESSION_STREAM_HEARTBEAT_SECONDS = 0.01
    SessionNotFoundError = LookupError

    def __init__(self) -> None:
        self.lifecycle: list[tuple[str, dict]] = []

    def normalize_session_stream_initial_mode(self, initial: str, *, default: str) -> str:
        return str(initial or default)

    def get_session_stream_initial_state(self, session_id: str) -> dict:
        return {"sessionId": session_id, "status": "running"}

    def _register_session_stream_subscriber(self, session_id: str, subscriber) -> None:
        return None

    def _unregister_session_stream_subscriber(self, session_id: str, subscriber) -> None:
        return None

    def _encode_sse_event(self, event_name: str, payload: dict) -> str:
        return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"

    def record_runtime_scene_event(self, component: str, phase: str, event_code: str, **kwargs) -> None:
        self.lifecycle.append((event_code, dict(kwargs.get("fields") or {})))


def _event_codes(service: _FakeSessionService) -> list[str]:
    return [code for code, _fields in service.lifecycle]


def test_sync_session_stream_open_and_close_share_one_connection_id(monkeypatch) -> None:
    service = _FakeSessionService()
    monkeypatch.setattr(publish, "_service", lambda: service)

    stream = publish.stream_session_events("session-sync", initial="light")
    assert next(stream)
    stream.close()

    assert _event_codes(service) == [
        "session.stream.opened",
        "session.stream.closed",
    ]
    ids = {fields["streamConnectionId"] for _code, fields in service.lifecycle}
    assert len(ids) == 1
    assert all(fields["transport"] == "sse_sync" for _code, fields in service.lifecycle)


def test_async_session_stream_open_and_close_share_one_connection_id(monkeypatch) -> None:
    service = _FakeSessionService()
    monkeypatch.setattr(publish, "_service", lambda: service)

    async def exercise() -> None:
        stream = publish.stream_session_events_async("session-async", initial="light")
        assert await anext(stream)
        assert await anext(stream) == ": keep-alive\n\n"
        await stream.aclose()

    asyncio.run(exercise())

    assert _event_codes(service) == [
        "session.stream.opened",
        "session.stream.closed",
    ]
    ids = {fields["streamConnectionId"] for _code, fields in service.lifecycle}
    assert len(ids) == 1
    assert all(fields["transport"] == "sse_async" for _code, fields in service.lifecycle)
    closed = service.lifecycle[-1][1]
    for field in ("eventCount", "heartbeatCount", "durationMs"):
        assert field in closed
        assert closed[field] >= 0


def test_sync_session_stream_closed_log_is_kept_when_unregister_fails(monkeypatch) -> None:
    service = _FakeSessionService()
    monkeypatch.setattr(publish, "_service", lambda: service)

    def fail_unregister(_session_id: str, _subscriber) -> None:
        raise RuntimeError("unregister failed")

    monkeypatch.setattr(service, "_unregister_session_stream_subscriber", fail_unregister)
    stream = publish.stream_session_events("session-unregister-failed", initial="light")
    assert next(stream)
    with pytest.raises(RuntimeError, match="unregister failed"):
        stream.close()

    assert _event_codes(service) == [
        "session.stream.opened",
        "session.stream.closed",
    ]
    closed = service.lifecycle[-1][1]
    assert closed["eventCount"] == 1
    assert closed["heartbeatCount"] == 0
    assert closed["durationMs"] >= 0


def test_async_session_stream_closed_log_is_kept_when_unregister_fails(monkeypatch) -> None:
    service = _FakeSessionService()
    monkeypatch.setattr(publish, "_service", lambda: service)

    def fail_unregister(_session_id: str, _subscriber) -> None:
        raise RuntimeError("async unregister failed")

    monkeypatch.setattr(service, "_unregister_session_stream_subscriber", fail_unregister)

    async def exercise() -> None:
        stream = publish.stream_session_events_async("session-async-unregister-failed", initial="light")
        assert await anext(stream)
        with pytest.raises(RuntimeError, match="async unregister failed"):
            await stream.aclose()

    asyncio.run(exercise())

    assert _event_codes(service) == [
        "session.stream.opened",
        "session.stream.closed",
    ]
    closed = service.lifecycle[-1][1]
    assert closed["eventCount"] == 1
    assert closed["heartbeatCount"] == 0
    assert closed["durationMs"] >= 0


def test_sync_session_stream_failure_and_close_share_one_connection_id(monkeypatch) -> None:
    service = _FakeSessionService()
    monkeypatch.setattr(publish, "_service", lambda: service)

    def fail_get(_self, timeout=None):
        raise RuntimeError("transport failed")

    monkeypatch.setattr(queue.Queue, "get", fail_get)
    stream = publish.stream_session_events("session-sync-failed", initial="light")
    assert next(stream)
    with pytest.raises(RuntimeError, match="transport failed"):
        next(stream)

    assert _event_codes(service) == [
        "session.stream.opened",
        "session.stream.failed",
        "session.stream.closed",
    ]
    ids = {fields["streamConnectionId"] for _code, fields in service.lifecycle}
    assert len(ids) == 1
    failed = service.lifecycle[1][1]
    assert failed["errorType"] == "RuntimeError"
    assert "transport failed" not in json.dumps(failed)


def test_async_session_stream_failure_and_close_share_one_connection_id(monkeypatch) -> None:
    service = _FakeSessionService()
    monkeypatch.setattr(publish, "_service", lambda: service)

    async def fail_get_async(_self, *, timeout: float):
        raise RuntimeError("async transport failed")

    monkeypatch.setattr(publish._AsyncSessionStreamSubscriber, "get_async", fail_get_async)

    async def exercise() -> None:
        stream = publish.stream_session_events_async("session-async-failed", initial="light")
        assert await anext(stream)
        with pytest.raises(RuntimeError, match="async transport failed"):
            await anext(stream)

    asyncio.run(exercise())

    assert _event_codes(service) == [
        "session.stream.opened",
        "session.stream.failed",
        "session.stream.closed",
    ]
    ids = {fields["streamConnectionId"] for _code, fields in service.lifecycle}
    assert len(ids) == 1
    assert all(fields["transport"] == "sse_async" for _code, fields in service.lifecycle)


def test_sync_session_stream_preserves_transport_error_when_unregister_succeeds(monkeypatch) -> None:
    service = _FakeSessionService()
    monkeypatch.setattr(publish, "_service", lambda: service)

    def fail_get(_self, timeout=None):
        raise RuntimeError("transport failed")

    monkeypatch.setattr(queue.Queue, "get", fail_get)
    stream = publish.stream_session_events("session-transport-failed", initial="light")
    assert next(stream)
    with pytest.raises(RuntimeError, match="transport failed"):
        next(stream)

    assert _event_codes(service) == [
        "session.stream.opened",
        "session.stream.failed",
        "session.stream.closed",
    ]
    closed = service.lifecycle[-1][1]
    assert closed["closeReason"] == "error"
