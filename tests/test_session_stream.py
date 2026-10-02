from __future__ import annotations

import queue
import threading
import uuid

from core.web.services import session_service


def test_last_session_stream_subscriber_cleans_snapshot_throttle_state():
    session_id = f"stream-cleanup-{uuid.uuid4()}"
    subscriber = queue.Queue()
    session_service._register_session_stream_subscriber(session_id, subscriber)
    with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
        session_service._SESSION_STREAM_LAST_SNAPSHOT_AT[session_id] = session_service._perf_counter()
        session_service._SESSION_STREAM_THROTTLED_COUNTS[session_id] = 4

    session_service._unregister_session_stream_subscriber(session_id, subscriber)

    with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
        assert session_id not in session_service._SESSION_STREAM_LAST_SNAPSHOT_AT
        assert session_id not in session_service._SESSION_STREAM_THROTTLED_COUNTS


def test_snapshot_throttle_state_lives_until_the_last_subscriber_disconnects():
    session_id = f"stream-multiple-subscribers-{uuid.uuid4()}"
    first_subscriber = queue.Queue()
    second_subscriber = queue.Queue()
    session_service._register_session_stream_subscriber(session_id, first_subscriber)
    session_service._register_session_stream_subscriber(session_id, second_subscriber)
    with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
        session_service._SESSION_STREAM_LAST_SNAPSHOT_AT[session_id] = session_service._perf_counter()
        session_service._SESSION_STREAM_THROTTLED_COUNTS[session_id] = 3

    session_service._unregister_session_stream_subscriber(session_id, first_subscriber)

    with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
        assert session_id in session_service._SESSION_STREAM_LAST_SNAPSHOT_AT
        assert session_service._SESSION_STREAM_THROTTLED_COUNTS[session_id] == 3

    session_service._unregister_session_stream_subscriber(session_id, second_subscriber)

    with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
        assert session_id not in session_service._SESSION_STREAM_LAST_SNAPSHOT_AT
        assert session_id not in session_service._SESSION_STREAM_THROTTLED_COUNTS


def test_stale_snapshot_publisher_cannot_repopulate_state_for_replacement_subscriber(monkeypatch):
    session_id = f"stream-replaced-{uuid.uuid4()}"
    old_subscriber = queue.Queue()
    replacement_subscriber = queue.Queue()
    entered_running_check = threading.Event()
    finish_running_check = threading.Event()

    session_service._register_session_stream_subscriber(session_id, old_subscriber)
    with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
        session_service._SESSION_STREAM_LAST_SNAPSHOT_AT[session_id] = session_service._perf_counter()
        session_service._SESSION_STREAM_THROTTLED_COUNTS[session_id] = 2

    def hold_running_check(_session_id: str) -> bool:
        entered_running_check.set()
        assert finish_running_check.wait(timeout=3)
        return True

    monkeypatch.setattr(session_service, "_is_session_running", hold_running_check)
    publisher = threading.Thread(
        target=session_service._publish_session_detail_snapshot,
        args=(session_id,),
        daemon=True,
    )
    publisher.start()
    assert entered_running_check.wait(timeout=2)

    session_service._unregister_session_stream_subscriber(session_id, old_subscriber)
    session_service._register_session_stream_subscriber(session_id, replacement_subscriber)
    finish_running_check.set()
    publisher.join(timeout=3)

    try:
        assert not publisher.is_alive()
        with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
            assert session_id not in session_service._SESSION_STREAM_LAST_SNAPSHOT_AT
            assert session_id not in session_service._SESSION_STREAM_THROTTLED_COUNTS
        assert replacement_subscriber.empty()
    finally:
        session_service._unregister_session_stream_subscriber(session_id, replacement_subscriber)


def test_many_completed_session_streams_do_not_accumulate_throttle_state(monkeypatch):
    with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
        initial_snapshot_keys = set(session_service._SESSION_STREAM_LAST_SNAPSHOT_AT)
        initial_throttled_keys = set(session_service._SESSION_STREAM_THROTTLED_COUNTS)
    monkeypatch.setattr(
        session_service,
        "_record_session_detail_snapshot_published_event",
        lambda **_kwargs: None,
    )

    for index in range(100):
        session_id = f"stream-lifecycle-{uuid.uuid4()}-{index}"
        subscriber = queue.Queue()
        session_service._register_session_stream_subscriber(session_id, subscriber)
        try:
            session_service._publish_session_detail_snapshot(
                session_id,
                detail={"currentPhase": "completed", "ledgerSeq": index + 1, "messages": []},
            )
            assert not subscriber.empty()
        finally:
            session_service._unregister_session_stream_subscriber(session_id, subscriber)

    with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
        assert set(session_service._SESSION_STREAM_LAST_SNAPSHOT_AT) == initial_snapshot_keys
        assert set(session_service._SESSION_STREAM_THROTTLED_COUNTS) == initial_throttled_keys
    with session_service._SESSION_STREAM_SUBSCRIBERS_LOCK:
        assert not any(session_id.startswith("stream-lifecycle-") for session_id in session_service._SESSION_STREAM_SUBSCRIBERS)
