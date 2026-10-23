"""Global session-index delta stream (summary fan-out for the session rail)."""

from __future__ import annotations

import json

import pytest

from core.web.services.session import session_index_stream as stream


@pytest.fixture(autouse=True)
def _clear_subscribers():
    with stream._SUBSCRIBERS_LOCK:
        stream._SUBSCRIBERS.clear()
    try:
        yield
    finally:
        with stream._SUBSCRIBERS_LOCK:
            stream._SUBSCRIBERS.clear()


def test_publish_without_subscribers_is_a_noop():
    assert stream.publish_session_index_delta("session-1", "upsert") == 0


def test_publish_fans_out_to_every_subscriber():
    first = stream.subscribe_session_index_events()
    second = stream.subscribe_session_index_events()

    assert stream.publish_session_index_delta("session-1", "upsert") == 2

    for subscriber in (first, second):
        payload = subscriber.get_nowait()
        assert payload["type"] == stream.SESSION_INDEX_CHANGE_UPSERTED
        assert payload["sessionId"] == "session-1"
        assert payload["at"]


def test_publish_skips_blank_session_id():
    stream.subscribe_session_index_events()
    assert stream.publish_session_index_delta("   ", "upsert") == 0


@pytest.mark.parametrize(
    ("change_type", "expected"),
    [
        ("upsert", stream.SESSION_INDEX_CHANGE_UPSERTED),
        ("", stream.SESSION_INDEX_CHANGE_UPSERTED),
        ("metadata", stream.SESSION_INDEX_CHANGE_UPSERTED),
        ("delete", stream.SESSION_INDEX_CHANGE_REMOVED),
        ("archive", stream.SESSION_INDEX_CHANGE_REMOVED),
        ("REMOVED", stream.SESSION_INDEX_CHANGE_REMOVED),
    ],
)
def test_change_type_mapping(change_type, expected):
    assert stream.normalize_session_index_change_type(change_type) == expected


def test_sse_frame_is_event_typed_and_json():
    frame = stream.encode_session_index_sse_frame(
        {
            "type": stream.SESSION_INDEX_CHANGE_REMOVED,
            "sessionId": "s-1",
            "at": "2026-01-01T00:00:00+00:00",
        }
    )

    assert frame.startswith(f"event: {stream.SESSION_INDEX_CHANGE_REMOVED}\ndata: ")
    assert frame.endswith("\n\n")
    body = json.loads(frame.split("data: ", 1)[1].strip())
    assert body["sessionId"] == "s-1"


def test_full_queue_drops_oldest_frame_instead_of_blocking():
    subscriber = stream.subscribe_session_index_events()
    for index in range(stream._QUEUE_SIZE + 1):
        stream.publish_session_index_delta(f"session-{index}", "upsert")

    # A stalled reader must never back-pressure the publishing turn: the oldest
    # frame is dropped and the newest stays readable.
    first = subscriber.get_nowait()
    assert first["sessionId"] == "session-1"
    assert subscriber.qsize() == stream._QUEUE_SIZE - 1


def test_unsubscribe_stops_delivery():
    subscriber = stream.subscribe_session_index_events()
    stream.unsubscribe_session_index_events(subscriber)

    assert stream.session_index_subscriber_count() == 0
    assert stream.publish_session_index_delta("session-1", "upsert") == 0
