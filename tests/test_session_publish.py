from __future__ import annotations

import asyncio
import json
import queue
import threading
from types import SimpleNamespace

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

    def _encode_sse_event(self, event_name: str, payload: dict, *, event_seq: int = 0) -> str:
        return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"

    def record_runtime_scene_event(self, component: str, phase: str, event_code: str, **kwargs) -> None:
        self.lifecycle.append((event_code, dict(kwargs.get("fields") or {})))


def _event_codes(service: _FakeSessionService) -> list[str]:
    return [code for code, _fields in service.lifecycle]


@pytest.mark.parametrize("asynchronous", [False, True])
def test_stream_compacts_only_after_dequeue_and_resends_after_reconnect(monkeypatch, asynchronous):
    item = {"version": 3, "id": "a", "itemId": "a", "sessionId": "s", "turnId": "t", "type": "agent_message", "text": "hello"}
    event = {"type": "assistant_delta", "sessionId": "s", "turnId": "t", "turnItems": [item], "done": False}

    class Service(_FakeSessionService):
        def _register_session_stream_subscriber(self, session_id, subscriber):
            subscriber.put_nowait(event)
            subscriber.put_nowait(event)

    monkeypatch.setattr(publish, "_service", lambda: Service())

    def payload(encoded):
        return json.loads(encoded.split("data: ", 1)[1])

    async def run_async():
        for _ in range(2):
            stream = publish.stream_session_events_async("s", initial="light")
            await anext(stream)
            assert payload(await anext(stream))["turnItems"] == [item]
            assert payload(await anext(stream))["turnItems"] == []
            await stream.aclose()

    if asynchronous:
        asyncio.run(run_async())
    else:
        for _ in range(2):
            stream = publish.stream_session_events("s", initial="light")
            next(stream)
            assert payload(next(stream))["turnItems"] == [item]
            assert payload(next(stream))["turnItems"] == []
            stream.close()
    assert event["turnItems"] == [item]


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


class _AssistantDeltaSeqService:
    """Minimal service facade binding the real publish-layer delta helpers."""

    _SESSION_STREAM_SUBSCRIBERS_LOCK = threading.Lock()
    _SESSION_STREAM_SUBSCRIBERS: dict = {}
    _SESSION_STREAM_DELTA_SEQ: dict = {}
    _SESSION_STREAM_LAST_SNAPSHOT_LOCK = threading.Lock()
    _SESSION_STREAM_LAST_SNAPSHOT_AT: dict = {}
    _SESSION_STREAM_THROTTLED_COUNTS: dict = {}

    _next_session_delta_seq = staticmethod(publish._next_session_delta_seq)
    _merge_session_assistant_delta_events = staticmethod(publish._merge_session_assistant_delta_events)
    _assistant_delta_recovery_stream_event = staticmethod(publish._assistant_delta_recovery_stream_event)
    _coalesce_session_assistant_delta_queue = staticmethod(publish._coalesce_session_assistant_delta_queue)
    _put_session_stream_event = staticmethod(publish._put_session_stream_event)

    def __init__(self, ledger_seq: int = 5) -> None:
        self.ledger_seq = ledger_seq

    def _perf_counter(self) -> float:
        return 0.0

    def _elapsed_ms(self, _started_at: float) -> int:
        return 0

    def _now_timestamp(self) -> str:
        return "2026-10-06T00:00:00Z"

    def _session_ledger_sequence(self, _session_id: str) -> int:
        return self.ledger_seq

    def _live_assistant_message_id(self, session_id: str, turn_id: str) -> str:
        return f"{session_id}-message-{turn_id}"

    def _build_codex_transcript_projection(self, **_kwargs) -> list:
        return []

    def _build_session_turn_items_projection(self, **kwargs) -> list:
        return [{"itemId": "answer", "type": "agent_message", "text": str(kwargs.get("content") or "")}]

    def _record_session_assistant_delta_published_event(self, **_kwargs) -> None:
        return None


def _delta_publish_state(content: str = "a"):
    return SimpleNamespace(
        turn_id="turn-1",
        stage="responding",
        updated_at="",
        content=content,
        thought="",
        mental_snapshot=None,
        feedback_events=[],
        tool_calls=[],
    )


def test_assistant_delta_seq_stays_dense_across_journal_watermark_jumps(monkeypatch) -> None:
    """Mid-turn journal appends (reasoning commits, tool events) advance the
    ledger watermark between frames; the frame's own deltaSeq must stay dense."""

    service = _AssistantDeltaSeqService()
    subscriber = queue.Queue()
    monkeypatch.setattr(publish, "_service", lambda: service)
    publish._register_session_stream_subscriber("session-live", subscriber)
    try:
        publish._publish_session_assistant_delta("session-live", _delta_publish_state("a"))
        first = subscriber.get_nowait()
        service.ledger_seq = 12  # journal boundary append between two deltas
        publish._publish_session_assistant_delta("session-live", _delta_publish_state("ab"))
        second = subscriber.get_nowait()
        # Slow consumer: the third frame is still queued when the fourth is
        # published, so the queue coalesces them into one covered range.
        publish._publish_session_assistant_delta("session-live", _delta_publish_state("abc"))
        service.ledger_seq = 20  # another journal boundary append
        publish._publish_session_assistant_delta("session-live", _delta_publish_state("abcd"))
        merged = subscriber.get_nowait()
    finally:
        publish._unregister_session_stream_subscriber("session-live", subscriber)

    assert (first["deltaSeq"], first["deltaSeqFrom"]) == (1, 1)
    assert (second["deltaSeq"], second["deltaSeqFrom"]) == (2, 2)
    assert first["ledgerSeq"] == 5
    assert second["ledgerSeq"] == 12
    assert (merged["deltaSeq"], merged["deltaSeqFrom"]) == (4, 3)
    assert merged["ledgerSeq"] == 20


def test_assistant_delta_seq_is_shared_across_subscribers(monkeypatch) -> None:
    service = _AssistantDeltaSeqService()
    first_subscriber = queue.Queue()
    second_subscriber = queue.Queue()
    monkeypatch.setattr(publish, "_service", lambda: service)
    publish._register_session_stream_subscriber("session-live", first_subscriber)
    publish._register_session_stream_subscriber("session-live", second_subscriber)
    try:
        publish._publish_session_assistant_delta("session-live", _delta_publish_state("a"))
    finally:
        publish._unregister_session_stream_subscriber("session-live", first_subscriber)
        publish._unregister_session_stream_subscriber("session-live", second_subscriber)

    assert first_subscriber.get_nowait()["deltaSeq"] == 1
    assert second_subscriber.get_nowait()["deltaSeq"] == 1


def test_assistant_delta_coalesce_widens_delta_seq_coverage(monkeypatch) -> None:
    service = _AssistantDeltaSeqService()
    monkeypatch.setattr(publish, "_service", lambda: service)
    subscriber = queue.Queue()
    subscriber.put_nowait(
        {
            "type": "assistant_delta",
            "sessionId": "session-live",
            "turnId": "turn-1",
            "deltaSeq": 1,
            "deltaSeqFrom": 1,
            "turnItems": [{"itemId": "answer", "type": "agent_message", "text": "你"}],
        }
    )

    merged, dropped = publish._coalesce_session_assistant_delta_queue(
        subscriber,
        {
            "type": "assistant_delta",
            "sessionId": "session-live",
            "turnId": "turn-1",
            "deltaSeq": 4,
            "deltaSeqFrom": 4,
            "turnItems": [{"itemId": "answer", "type": "agent_message", "text": "你好"}],
        },
    )

    assert dropped == 1
    assert merged["deltaSeq"] == 4
    assert merged["deltaSeqFrom"] == 1


def test_assistant_delta_seq_restarts_after_last_subscriber_leaves(monkeypatch) -> None:
    service = _AssistantDeltaSeqService()
    subscriber = queue.Queue()
    monkeypatch.setattr(publish, "_service", lambda: service)

    publish._register_session_stream_subscriber("session-live", subscriber)
    publish._publish_session_assistant_delta("session-live", _delta_publish_state("a"))
    publish._unregister_session_stream_subscriber("session-live", subscriber)

    publish._register_session_stream_subscriber("session-live", subscriber)
    try:
        publish._publish_session_assistant_delta("session-live", _delta_publish_state("ab"))
    finally:
        publish._unregister_session_stream_subscriber("session-live", subscriber)

    assert subscriber.get_nowait()["deltaSeq"] == 1


def test_assistant_delta_coalesce_keeps_legacy_frames_field_clean(monkeypatch) -> None:
    service = _AssistantDeltaSeqService()
    monkeypatch.setattr(publish, "_service", lambda: service)
    subscriber = queue.Queue()
    subscriber.put_nowait(
        {
            "type": "assistant_delta",
            "sessionId": "session-live",
            "turnId": "turn-1",
            "turnItems": [{"itemId": "answer", "type": "agent_message", "text": "你"}],
        }
    )

    merged, dropped = publish._coalesce_session_assistant_delta_queue(
        subscriber,
        {
            "type": "assistant_delta",
            "sessionId": "session-live",
            "turnId": "turn-1",
            "turnItems": [{"itemId": "answer", "type": "agent_message", "text": "你好"}],
        },
    )

    assert dropped == 1
    assert "deltaSeq" not in merged
    assert "deltaSeqFrom" not in merged


def test_session_detail_coalesce_rejects_older_ledger_snapshot(monkeypatch) -> None:
    class Service:
        _SESSION_STREAM_COALESCED_EVENT_TYPES = {"session_detail"}

    monkeypatch.setattr(publish, "_service", lambda: Service())
    subscriber = queue.Queue()
    subscriber.put_nowait({"type": "session_detail", "ledgerSeq": 18, "detail": {"version": "new"}})

    dropped, should_enqueue = publish._coalesce_session_stream_queue_with_outcome(
        subscriber,
        event_type="session_detail",
        incoming_ledger_seq=17,
    )

    assert should_enqueue is False
    assert dropped == 1
    assert subscriber.get_nowait()["ledgerSeq"] == 18


def test_session_detail_coalesce_orders_same_ledger_control_state_by_generation(monkeypatch) -> None:
    class Service:
        _SESSION_STREAM_COALESCED_EVENT_TYPES = {"session_detail"}

    monkeypatch.setattr(publish, "_service", lambda: Service())
    subscriber = queue.Queue()
    subscriber.put_nowait(
        {"type": "session_detail", "ledgerSeq": 18, "detail": {"currentPhase": "completed"}}
    )
    publish._remember_session_stream_detail_watermark(
        subscriber,
        session_id="session-a",
        ledger_seq=18,
        generation=10,
    )

    dropped, should_enqueue = publish._coalesce_session_stream_queue_with_outcome(
        subscriber,
        event_type="session_detail",
        session_id="session-a",
        incoming_ledger_seq=18,
        incoming_generation=9,
    )

    assert should_enqueue is False
    assert dropped == 1
    assert subscriber.get_nowait()["detail"]["currentPhase"] == "completed"

    dropped, should_enqueue = publish._coalesce_session_stream_queue_with_outcome(
        subscriber,
        event_type="session_detail",
        session_id="session-a",
        incoming_ledger_seq=18,
        incoming_generation=11,
    )

    assert should_enqueue is True
    assert dropped == 0
    assert subscriber.empty()


@pytest.mark.parametrize("old_seq", [19, 20])
@pytest.mark.parametrize("new_finishes_first,consume_new", [(False, False), (True, False), (True, True)])
def test_overlapping_detail_hydration_keeps_latest_snapshot(monkeypatch, old_seq, new_finishes_first, consume_new):
    from core.web.services import session_service as service

    session_id = "hydration-race"
    subscriber = queue.Queue(maxsize=4)
    entered = threading.Event()
    release = threading.Event()
    errors = []
    old = {"ledgerSeq": old_seq, "activeTurnId": "old", "currentPhase": "completed"}
    new = {"ledgerSeq": 20, "activeTurnId": "new", "currentPhase": "ready"}
    monkeypatch.setattr(publish, "_service", lambda: service)
    monkeypatch.setattr(service, "_SESSION_STREAM_SUBSCRIBERS", {session_id: {subscriber}})
    monkeypatch.setattr(service, "_is_session_running", lambda _id: False)
    monkeypatch.setattr(service, "_record_session_detail_snapshot_published_event", lambda **kwargs: None)
    monkeypatch.setattr(publish, "_clear_session_detail_snapshot_slot", lambda *args, **kwargs: 0)

    def hydrate(_id, **kwargs):
        entered.set()
        assert release.wait(3), "test failed to release hydration"
        return old

    monkeypatch.setattr(service, "get_session_detail", hydrate)

    def publish_old():
        try:
            publish._publish_session_detail_snapshot(session_id)
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=publish_old)
    thread.start()
    try:
        assert entered.wait(3)
        if new_finishes_first:
            publish._publish_session_detail_snapshot(session_id, detail=new)
            if consume_new:
                assert subscriber.get_nowait()["detail"] == new
        release.set()
        thread.join(3)
        assert not thread.is_alive()
        if not new_finishes_first:
            publish._publish_session_detail_snapshot(session_id, detail=new)
        assert errors == []
        if consume_new:
            assert subscriber.empty()
        else:
            assert subscriber.qsize() == 1
            assert subscriber.get_nowait()["detail"] == new
    finally:
        release.set()
        thread.join(3)


def test_subscriber_replacement_does_not_receive_an_old_hydration(monkeypatch):
    from core.web.services import session_service as service

    session_id = "subscriber-replacement"
    old_subscriber = queue.Queue()
    new_subscriber = queue.Queue()
    entered = threading.Event()
    release = threading.Event()
    errors = []
    registry = {session_id: {old_subscriber}}
    monkeypatch.setattr(publish, "_service", lambda: service)
    monkeypatch.setattr(service, "_SESSION_STREAM_SUBSCRIBERS", registry)
    monkeypatch.setattr(service, "_is_session_running", lambda _id: False)
    monkeypatch.setattr(service, "_record_session_detail_snapshot_published_event", lambda **kwargs: None)
    monkeypatch.setattr(publish, "_clear_session_detail_snapshot_slot", lambda *args, **kwargs: 0)

    def hydrate(_id, **kwargs):
        entered.set()
        assert release.wait(3)
        return {"ledgerSeq": 19, "currentPhase": "completed"}

    monkeypatch.setattr(service, "get_session_detail", hydrate)

    def publish_old():
        try:
            publish._publish_session_detail_snapshot(session_id)
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=publish_old)
    thread.start()
    try:
        assert entered.wait(3)
        with service._SESSION_STREAM_SUBSCRIBERS_LOCK:
            registry[session_id] = {new_subscriber}
        new = {"ledgerSeq": 20, "currentPhase": "ready"}
        publish._publish_session_detail_snapshot(session_id, detail=new)
        release.set()
        thread.join(3)
        assert not thread.is_alive()
        assert errors == []
        assert old_subscriber.empty()
        assert new_subscriber.qsize() == 1
        assert new_subscriber.get_nowait()["detail"] == new
    finally:
        release.set()
        thread.join(3)


def test_assistant_delta_publish_holds_per_subscriber_publish_lock(monkeypatch) -> None:
    """Delta coalesce+put must sit inside the same per-subscriber critical
    section as the detail path: an interleaved publisher could otherwise drain
    and refill the queue between coalesce and put and strand or reorder frames."""

    service = _AssistantDeltaSeqService()
    subscriber = queue.Queue()
    monkeypatch.setattr(publish, "_service", lambda: service)
    publish._register_session_stream_subscriber("session-live", subscriber)
    observed: list[tuple[str, bool]] = []
    publish_lock = publish._session_stream_publish_lock(subscriber)
    real_coalesce = service._coalesce_session_assistant_delta_queue
    real_put = service._put_session_stream_event

    def spy_coalesce(sub, event):
        observed.append(("coalesce", publish_lock.locked()))
        return real_coalesce(sub, event)

    def spy_put(sub, event, **kwargs):
        observed.append(("put", publish_lock.locked()))
        return real_put(sub, event, **kwargs)

    monkeypatch.setattr(service, "_coalesce_session_assistant_delta_queue", spy_coalesce)
    monkeypatch.setattr(service, "_put_session_stream_event", spy_put)
    try:
        publish._publish_session_assistant_delta("session-live", _delta_publish_state("a"))
    finally:
        publish._unregister_session_stream_subscriber("session-live", subscriber)

    assert observed == [("coalesce", True), ("put", True)]
    assert not publish_lock.locked()
    assert subscriber.get_nowait()["turnItems"]


def test_session_initial_state_stamps_ledger_before_content_read(monkeypatch) -> None:
    """The initial frame's ledgerSeq doubles as the SSE id cursor; journal
    events appended between the content read and the stamp would be marked seen
    without ever being delivered, so the stamp must precede the reads."""

    class Service:
        _RUNNING_SESSIONS_LOCK = threading.Lock()
        _SESSION_ACTIVE_TURN_IDS: dict = {}
        _RUNNING_SESSION_IDS: set = set()

        def __init__(self) -> None:
            self.ledger_calls = 0
            self.ledger_seq_at_content_read: int | None = None

        def _session_ledger_sequence(self, _session_id: str) -> int:
            # The journal watermark advances on every read, like live appends.
            self.ledger_calls += 1
            return self.ledger_calls * 10

        def _agent_lookup_for_conversations(self) -> dict:
            return {}

        def _load_conversation_detail_target(self, _session_id: str, **_kwargs) -> dict:
            return {"id": "session-live"}

        def _build_session_summary(self, _target, *, hydrate_agent: bool) -> dict:
            return {"currentPhase": "ready"}

        def _session_stream_initial_latest_message_payload(self, _session_id: str) -> dict:
            self.ledger_seq_at_content_read = self.ledger_calls * 10
            return {"role": "assistant", "text": "hello"}

    service = Service()
    monkeypatch.setattr(publish, "_service", lambda: service)

    state = publish.get_session_stream_initial_state("session-live")

    assert state["ledgerSeq"] == 10
    assert service.ledger_seq_at_content_read is not None
    assert state["ledgerSeq"] <= service.ledger_seq_at_content_read
