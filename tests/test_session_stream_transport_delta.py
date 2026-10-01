from __future__ import annotations

import json

from core.web.services.session.stream_transport_delta import SessionStreamItemDelta


def item(name="answer", **changes):
    return dict(version=3, id=name, itemId=name, sessionId="s", turnId="t", type="agent_message", revision=1, sequence=1, text="hello") | changes


def frame(*items, **changes):
    return dict(type="assistant_delta", sessionId="s", turnId="t", turnItems=list(items), done=False, stage="model_thinking") | changes


def reassembled(received: dict[str, dict], compact: dict) -> list[dict]:
    """Rebuild full items the way the append-aware consumer does."""

    rebuilt = {key: dict(value) for key, value in received.items()}
    for value in compact.get("turnItems") or []:
        rebuilt[value["itemId"]] = dict(value)
    for entry in compact.get("turnItemAppends") or []:
        base = dict(rebuilt[entry["itemId"]])
        base["text"] = base.get("text", "") + entry["appendedText"]
        rebuilt[entry["itemId"]] = base
    return [rebuilt[value["itemId"]] for value in sorted(rebuilt.values(), key=lambda v: v["sequence"])]


def test_only_changed_items_cross_the_wire_without_mutating_shared_snapshot():
    delta = SessionStreamItemDelta()
    first = frame(item("history"), item())
    assert delta.compact(first) == first
    second = frame(item("history"), item(text="hello world"), updatedAt="now")
    compact = delta.compact(second)
    # The grown body travels as an append fragment, not a re-sent full row.
    assert compact["turnItems"] == []
    assert compact["turnItemAppends"] == [
        {
            "kind": "append",
            "itemId": "answer",
            "itemType": "agent_message",
            "baseLength": 5,
            "appendedLength": 6,
            "appendedText": " world",
        }
    ]
    assert compact["streamEncoding"] == "append-v1"
    assert len(second["turnItems"]) == 2
    assert compact["updatedAt"] == "now"
    replayed = delta.compact(second)
    assert replayed.get("turnItems") == []
    assert replayed.get("turnItemAppends") is None
    assert "streamEncoding" not in replayed


def test_append_chain_reconstructs_the_authoritative_text():
    delta = SessionStreamItemDelta()
    received: dict[str, dict] = {}
    for text in ("h", "hel", "hello", "hello world"):
        compact = delta.compact(frame(item(text=text)))
        for value in reassembled(received, compact):
            received[value["itemId"]] = value
    assert received["answer"]["text"] == "hello world"


def test_text_rewrite_shrink_and_first_send_fall_back_to_full_rows():
    delta = SessionStreamItemDelta()
    delta.compact(frame(item(text="hello world")))
    # Rewrite: equal-length text with different content must resend full.
    rewritten = delta.compact(frame(item(text="helloworld")))
    assert rewritten["turnItems"] == [item(text="helloworld")]
    assert "turnItemAppends" not in rewritten
    # Shrink: content got shorter, an append cannot express it.
    shrunk = delta.compact(frame(item(text="hi")))
    assert shrunk["turnItems"] == [item(text="hi")]
    assert "turnItemAppends" not in shrunk
    # Regrowth after a rewrite appends from the new baseline.
    regrown = delta.compact(frame(item(text="hi there")))
    assert regrown["turnItems"] == []
    assert regrown["turnItemAppends"][0]["baseLength"] == 2
    assert regrown["turnItemAppends"][0]["appendedText"] == " there"


def test_reasoning_items_use_the_same_append_channel():
    delta = SessionStreamItemDelta()
    thought = item("thought-1", type="reasoning", text="thinking")
    assert delta.compact(frame(thought)) == frame(thought)
    grown = delta.compact(frame(item("thought-1", type="reasoning", text="thinking hard")))
    assert grown["turnItems"] == []
    assert grown["turnItemAppends"] == [
        {
            "kind": "append",
            "itemId": "thought-1",
            "itemType": "reasoning",
            "baseLength": 8,
            "appendedLength": 5,
            "appendedText": " hard",
        }
    ]


def test_non_text_items_and_new_items_still_travel_as_full_rows():
    delta = SessionStreamItemDelta()
    delta.compact(frame(item()))
    tool = item("tool", type="tool_call", callId="call-1")
    compact = delta.compact(frame(item(), tool))
    # The unchanged answer row stays omitted; the new tool row appears in full.
    assert compact["turnItems"] == [tool]
    assert "turnItemAppends" not in compact
    updated_tool = tool | {"metadata": {"executionStartedAtEpochMs": 123}}
    assert delta.compact(frame(updated_tool))["turnItems"] == [updated_tool]
    assert delta.compact(frame(updated_tool))["turnItems"] == []


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
    # Intermediate frames were coalesced/dropped upstream, not seen by compact;
    # the cursor still points at the last DELIVERED text, so the recovered
    # frame covers the whole skipped span with one full row + full new rows.
    recovered = frame(item("one", text="changed"), item("two"), item("three"))
    assert delta.compact(recovered)["turnItems"] == recovered["turnItems"]


def test_long_turn_append_payload_stays_bounded_and_reconstructs_items():
    delta = SessionStreamItemDelta()
    history = [item(str(i), text="x" * 2000, sequence=i) for i in range(50)]
    received = {}
    full_bytes = compact_bytes = 0
    for index in range(20):
        event = frame(*history, item(text="y" * (index + 1), sequence=51))
        compact = delta.compact(event)
        full_bytes += len(json.dumps(event))
        compact_bytes += len(json.dumps(compact))
        for value in reassembled(received, compact):
            received[value["itemId"]] = value
        assert list(received.values()) == event["turnItems"]
    assert compact_bytes < full_bytes * 0.1
