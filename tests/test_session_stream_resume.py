"""Last-Event-ID resume replay: parser, window plan, frame encoding, prelude."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.web.services import session_service
from core.web.services.session.publish import (
    SESSION_STREAM_RESUME_MAX_EVENTS,
    SESSION_STREAM_RESUME_MAX_PAYLOAD_CHARS,
    _encode_sse_event,
    _session_stream_resume_frames,
    _session_stream_resume_prelude,
    build_session_stream_resume,
    parse_session_stream_last_event_id,
)


def journal_event(sequence: int, *, event_type="assistant_item_committed", payload=None, turn_id="turn-1"):
    return SimpleNamespace(
        sequence=sequence,
        event_id=f"evt-{sequence:06d}",
        turn_id=turn_id,
        event_type=event_type,
        status="completed",
        timestamp=f"2026-01-01T00:00:{sequence % 60:02d}",
        payload=payload if payload is not None else {"n": sequence},
    )


@pytest.fixture
def journal(monkeypatch):
    """Fake facade journal: events + watermark, both monkeypatchable per test."""

    state: dict = {"events": [], "watermark": 0}

    def _watermark(session_id: str) -> int:
        return int(state["watermark"])

    def _events(session_id: str) -> list:
        return list(state["events"])

    monkeypatch.setattr(session_service, "_session_ledger_sequence", _watermark)
    monkeypatch.setattr(session_service, "_load_session_conversation_events_cached", _events)
    return state


def test_parse_last_event_id_accepts_blank_and_nonnegative_integers():
    assert parse_session_stream_last_event_id(None) == 0
    assert parse_session_stream_last_event_id("  ") == 0
    assert parse_session_stream_last_event_id("42") == 42
    with pytest.raises(ValueError):
        parse_session_stream_last_event_id("abc")
    with pytest.raises(ValueError):
        parse_session_stream_last_event_id("-1")


def test_encode_sse_event_emits_monotonic_id_line_from_seq_or_payload():
    assert _encode_sse_event("assistant_delta", {"type": "assistant_delta"}) == (
        "event: assistant_delta\ndata: {\"type\": \"assistant_delta\"}\n\n"
    )
    assert _encode_sse_event("assistant_delta", {"ledgerSeq": 7}).startswith("id: 7\n")
    assert _encode_sse_event("session_journal_event", {"seq": 9}, event_seq=9).startswith("id: 9\n")
    # Explicit event_seq wins over the payload watermark.
    assert _encode_sse_event("stream_resume", {"seq": 3}, event_seq=12).startswith("id: 12\n")


def test_resume_plan_replays_the_closed_interval_from_last_event_id(journal):
    journal["events"] = [journal_event(n) for n in range(1, 6)]
    journal["watermark"] = 5
    plan = build_session_stream_resume("s1", 2)
    assert plan["resume"] == "replayed"
    assert plan["fromSeq"] == 2
    assert plan["toSeq"] == 5
    assert [event["seq"] for event in plan["events"]] == [3, 4, 5]
    assert plan["replayedCount"] == 3


def test_resume_plan_without_gap_reports_replayed_with_zero_events(journal):
    journal["events"] = [journal_event(1), journal_event(2)]
    journal["watermark"] = 2
    plan = build_session_stream_resume("s1", 2)
    assert plan["resume"] == "replayed"
    assert plan["events"] == []
    assert plan["replayedCount"] == 0


def test_resume_plan_degrades_to_partial_when_gap_exceeds_retention_window(journal):
    count = SESSION_STREAM_RESUME_MAX_EVENTS + 10
    journal["events"] = [journal_event(n) for n in range(1, count + 1)]
    journal["watermark"] = count
    plan = build_session_stream_resume("s1", 0)
    assert plan["resume"] == "partial"
    assert len(plan["events"]) == SESSION_STREAM_RESUME_MAX_EVENTS
    assert plan["events"][0]["seq"] == count - SESSION_STREAM_RESUME_MAX_EVENTS + 1
    assert plan["replayedCount"] == 0


def test_resume_plan_degrades_to_partial_when_the_journal_is_unreadable(journal, monkeypatch):
    journal["events"] = []
    journal["watermark"] = 9

    def _raise(session_id: str) -> list:
        raise OSError("journal unavailable")

    monkeypatch.setattr(session_service, "_load_session_conversation_events_cached", _raise)
    plan = build_session_stream_resume("s1", 2)
    # An empty replay must not masquerade as covered.
    assert plan["resume"] == "partial"
    assert plan["events"] == []


def test_resume_frames_replay_journal_events_then_close_with_marker(journal):
    journal["events"] = [journal_event(n) for n in range(1, 4)]
    journal["watermark"] = 3
    plan = build_session_stream_resume("s1", 1)
    frames = _session_stream_resume_frames(plan)
    assert len(frames) == 3
    assert frames[0].startswith("id: 2\n")
    assert "event: session_journal_event\n" in frames[0]
    first_payload = json.loads(frames[0].split("data: ", 1)[1].strip())
    assert first_payload["type"] == "session_journal_event"
    assert first_payload["seq"] == 2
    assert first_payload["eventType"] == "assistant_item_committed"
    assert first_payload["payload"] == {"n": 2}
    marker = frames[-1]
    assert marker.startswith("id: 3\n")
    assert "event: stream_resume\n" in marker
    marker_payload = json.loads(marker.split("data: ", 1)[1].strip())
    assert marker_payload == {
        "type": "stream_resume",
        "sessionId": "s1",
        "resume": "replayed",
        "fromSeq": 1,
        "toSeq": 3,
        "replayedCount": 2,
    }


def test_resume_frames_bound_oversized_journal_payloads(journal):
    oversized = {"blob": "x" * (SESSION_STREAM_RESUME_MAX_PAYLOAD_CHARS + 1)}
    journal["events"] = [journal_event(1, payload=oversized)]
    journal["watermark"] = 1
    plan = build_session_stream_resume("s1", 0)
    frames = _session_stream_resume_frames(plan)
    payload = json.loads(frames[0].split("data: ", 1)[1].strip())
    assert "payload" not in payload
    assert payload["payloadTruncated"] is True
    assert len(frames[0]) < SESSION_STREAM_RESUME_MAX_PAYLOAD_CHARS


def test_resume_prelude_without_header_stays_empty(journal):
    assert _session_stream_resume_prelude("s1", 0) == []


def test_resume_prelude_partial_mode_sends_marked_light_initial(journal, monkeypatch):
    count = SESSION_STREAM_RESUME_MAX_EVENTS + 10
    journal["events"] = [journal_event(n) for n in range(1, count + 1)]
    journal["watermark"] = count
    monkeypatch.setattr(
        session_service,
        "get_session_stream_initial_state",
        lambda session_id: {"type": "session_initial", "sessionId": session_id, "ledgerSeq": journal["watermark"]},
    )
    # A gap wider than the retention window degrades: no journal replay frames,
    # one marked light initial + the partial resume marker with the watermark.
    frames = _session_stream_resume_prelude("s1", 1)
    assert len(frames) == 2
    assert "event: session_initial\n" in frames[0]
    initial_payload = json.loads(frames[0].split("data: ", 1)[1].strip())
    assert initial_payload["resume"] == "partial"
    marker_payload = json.loads(frames[-1].split("data: ", 1)[1].strip())
    assert marker_payload["resume"] == "partial"
    assert marker_payload["toSeq"] == journal["watermark"]
