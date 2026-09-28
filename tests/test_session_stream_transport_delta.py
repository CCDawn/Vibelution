from __future__ import annotations

import json

from core.web.services.session.stream_transport_delta import SessionStreamItemDelta


def item(name="answer", **changes):
    return dict(version=3, id=name, itemId=name, sessionId="s", turnId="t", type="agent_message", revision=1, sequence=1, text="hello") | changes


def frame(*items, **changes):
    return dict(type="assistant_delta", sessionId="s", turnId="t", turnItems=list(items), done=False, stage="model_thinking") | changes


def test_only_changed_items_cross_the_wire_without_mutating_shared_snapshot():
    delta = SessionStreamItemDelta()
    first = frame(item("history"), item())
    assert delta.compact(first) == first
    second = frame(item("history"), item(text="hello world"), updatedAt="now")
    compact = delta.compact(second)
    assert compact["turnItems"] == [item(text="hello world")]
    assert len(second["turnItems"]) == 2
    assert compact["updatedAt"] == "now"
    assert delta.compact(second)["turnItems"] == []


def test_reconnect_and_new_turn_start_with_full_snapshot():
    delta = SessionStreamItemDelta()
    event = frame(item())
    delta.compact(event)
    assert SessionStreamItemDelta().compact(event) == event
    next_turn = frame(item(turnId="next"), turnId="next")
    assert delta.compact(next_turn) == next_turn


def test_detail_replacement_terminal_and_removed_identity_resend_full():
    delta = SessionStreamItemDelta()
    event = frame(item("one"), item("two"))
    delta.compact(event)
    detail = {"type": "session_detail", "detail": {}}
    assert delta.compact(detail) == detail
    assert delta.compact(event) == event
    final = event | {"done": True}
    assert delta.compact(final) == final
    removed = frame(item("two"))
    assert delta.compact(removed) == removed


def test_tool_call_identity_and_metadata_changes_are_not_lost():
    delta = SessionStreamItemDelta()
    tool = item("tool", type="tool_call", callId="call-1")
    delta.compact(frame(tool))
    updated = tool | {"metadata": {"executionStartedAtEpochMs": 123}}
    assert delta.compact(frame(updated))["turnItems"] == [updated]
    assert delta.compact(frame(updated))["turnItems"] == []


def test_noncanonical_frames_fail_open_and_reset_baseline():
    delta = SessionStreamItemDelta()
    good = frame(item())
    delta.compact(good)
    for malformed in (frame(item(version=2)), frame(item(), item()), frame(item(sessionId="other"))):
        assert delta.compact(malformed) == malformed
        assert delta.compact(good) == good


def test_skipped_queue_frames_do_not_break_last_delivered_baseline():
    delta = SessionStreamItemDelta()
    delta.compact(frame(item("one")))
    # Intermediate frames were coalesced/dropped upstream, not seen by compact.
    recovered = frame(item("one", text="changed"), item("two"), item("three"))
    assert delta.compact(recovered)["turnItems"] == recovered["turnItems"]


def test_long_turn_payload_reduction_preserves_reconstructed_items():
    delta = SessionStreamItemDelta()
    history = [item(str(i), text="x" * 2000, sequence=i) for i in range(50)]
    received = {}
    full_bytes = compact_bytes = 0
    for index in range(20):
        event = frame(*history, item(text="y" * (index + 1), sequence=51))
        compact = delta.compact(event)
        full_bytes += len(json.dumps(event))
        compact_bytes += len(json.dumps(compact))
        for value in compact["turnItems"]:
            received[value["itemId"]] = value
        assert list(received.values()) == event["turnItems"]
    assert compact_bytes < full_bytes * 0.1
