"""Chat-room speaker delta capture: contract, ordering, and isolation tests."""

import queue
import threading
import time

import pytest

from core.web.services import chat_room_service
from core.web.services import chat_room_stream_capture as capture
from core.web.services.session import stream_capture as session_stream_capture


_EVENT_FIELDS = {
    "type",
    "roomId",
    "roundId",
    "participantId",
    "sessionId",
    "turnId",
    "seq",
    "stage",
    "content",
    "done",
    "status",
}


class _Collector:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.lock = threading.Lock()

    def __call__(self, event: dict) -> None:
        with self.lock:
            self.events.append(event)

    def snapshot(self) -> list[dict]:
        with self.lock:
            return list(self.events)


@pytest.fixture()
def collector():
    collected = _Collector()
    capture.set_delta_publisher(collected)
    yield collected
    capture.set_delta_publisher(None)


@pytest.fixture()
def fast_throttle(monkeypatch):
    monkeypatch.setattr(capture, "CHAT_ROOM_SPEAKER_DELTA_MIN_INTERVAL_SECONDS", 0.0)


class _FakeUi:
    def __init__(self) -> None:
        self.streamed: list[tuple[str, bool]] = []
        self.original_response_calls = 0

    def stream_response(self, text: str, done: bool = False):
        self.streamed.append((text, done))
        self.original_response_calls += 1


def _capture_kwargs(**overrides):
    kwargs = {
        "room_id": "room-1",
        "round_id": "round-1",
        "participant_id": "participant-1",
        "session_id": "session-1",
        "turn_id": "chat-room:round-1:participant-1",
    }
    kwargs.update(overrides)
    return kwargs


def _delta_events(events: list[dict]) -> list[dict]:
    return [event for event in events if event.get("type") == "chat_room_speaker_delta"]


# ---------------------------------------------------------------------------
# 1. schema contract: field-set and value types are pinned
# ---------------------------------------------------------------------------


def test_delta_event_schema_contract(collector, fast_throttle):
    from core.ui import get_ui

    with capture.speaker_delta_capture(**_capture_kwargs()):
        get_ui().stream_response("hello", done=False)
        get_ui().stream_response("hello world", done=True)

    events = _delta_events(collector.snapshot())
    assert len(events) == 2, f"expected two delta frames, got {events}"
    for event in events:
        assert set(event.keys()) == _EVENT_FIELDS
        assert event["type"] == "chat_room_speaker_delta"
        assert event["roomId"] == "room-1"
        assert event["roundId"] == "round-1"
        assert event["participantId"] == "participant-1"
        assert event["sessionId"] == "session-1"
        assert event["turnId"] == "chat-room:round-1:participant-1"
        assert isinstance(event["seq"], int)
        assert event["stage"] == "answer"
        assert isinstance(event["content"], str)
        assert isinstance(event["done"], bool)
        assert event["status"] in {"running", "completed", "failed", "stopped", "aborted"}


def test_terminal_completed_frame_from_caller(collector, fast_throttle):
    from core.ui import get_ui

    with capture.speaker_delta_capture(**_capture_kwargs(round_id="round-done")):
        get_ui().stream_response("完整发言", done=False)
        # caller-side normal completion: caller closes the ticket
        capture.close_speaker_delta(
            round_id="round-done", participant_id="participant-1", status="completed"
        )

    events = _delta_events(collector.snapshot())
    assert events[-1]["done"] is True
    assert events[-1]["status"] == "completed"
    assert events[-1]["content"] == "完整发言"
    assert events[-1]["seq"] > events[0]["seq"]


# ---------------------------------------------------------------------------
# 2. seq monotonic + content is the accumulated prefix-consistent text
# ---------------------------------------------------------------------------


def test_delta_seq_increases_and_content_accumulates(collector, fast_throttle):
    with capture.speaker_delta_capture(**_capture_kwargs()):
        from core.ui import get_ui

        get_ui().stream_response("第一段", done=False)
        get_ui().stream_response("第一段第二段", done=False)
        get_ui().stream_response("第一段第二段第三段", done=True)

    events = _delta_events(collector.snapshot())
    assert len(events) == 3
    seqs = [event["seq"] for event in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    contents = [event["content"] for event in events]
    assert contents[0] == "第一段"
    assert contents[1] == "第一段第二段"
    assert contents[2] == "第一段第二段第三段"
    for previous, current in zip(contents, contents[1:]):
        assert current.startswith(previous)


def test_delta_throttles_to_latest_frame_within_window(collector):
    # default 0.12s cadence: callbacks inside one window collapse into a
    # single published frame per window, and the next window's frame carries
    # the full accumulated text (latest-wins, no lossy merge).
    with capture.speaker_delta_capture(**_capture_kwargs()):
        from core.ui import get_ui

        for index in range(10):
            get_ui().stream_response(f"chunk-{index} ", done=False)
        inside_window_frames = _delta_events(collector.snapshot())
        assert 1 <= len(inside_window_frames) <= 2
        time.sleep(0.16)
        get_ui().stream_response("chunk-10 done", done=True)

    events = _delta_events(collector.snapshot())
    running = [event for event in events if event["status"] == "running"]
    assert len(running) <= 3
    final = events[-1]
    assert final["done"] is True
    assert final["content"].endswith("chunk-10 done")


# ---------------------------------------------------------------------------
# 3. watchdog abandonment: late deltas dropped + aborted terminal frame
# ---------------------------------------------------------------------------


def test_watchdog_abandon_drops_late_delta_and_emits_aborted(
    collector, fast_throttle, monkeypatch
):
    from core.ui import get_ui

    late_frame_dropped = threading.Event()
    late_sent = threading.Event()

    def runner(participant, prompt, context):
        with capture.speaker_delta_capture(
            room_id="room-watch",
            round_id="round-watch",
            participant_id="participant-watch",
            session_id="session-watch",
            turn_id="chat-room:round-watch:participant-watch",
            enabled=True,
        ):
            get_ui().stream_response("early ", done=False)
            entered_frames = len(_delta_events(collector.snapshot()))
            assert entered_frames >= 1
            # Watchdog budget is 1.0s (patched below); oversleep it, then
            # emit a late delta from the abandoned thread.
            time.sleep(1.6)
            before = len(collector.snapshot())
            get_ui().stream_response("early late-frame", done=False)
            time.sleep(0.2)
            if len(collector.snapshot()) == before:
                late_frame_dropped.set()
            late_sent.set()

    # Plain-room watchdog: no per-call deadline key in the context, so the
    # abandoned call maps to ``aborted`` (no round/challenge stop applies).
    context = {
        "roundId": "round-watch",
        "speakerStartedAtMonotonic": chat_room_service._perf_counter(),
    }
    participant = {
        "participantId": "participant-watch",
        "agentId": "agent-watch",
        "sessionId": "session-watch",
    }
    monkeypatch.setattr(chat_room_service, "_speaker_call_timeout_seconds", lambda _c: 1.0)
    message = chat_room_service._run_one_speaker(participant, "prompt", context, runner)
    assert message["errorType"] == "SpeakerCallWatchdogTimeout"
    assert message["status"] == "failed"

    assert late_sent.wait(timeout=5), "runner thread never reached the late frame"
    events = _delta_events(collector.snapshot())
    statuses = [event["status"] for event in events]
    assert "aborted" in statuses, f"expected aborted terminal frame, got {statuses}"
    aborted = next(event for event in events if event["status"] == "aborted")
    assert aborted["done"] is True
    assert aborted["content"] == "early "  # frozen at the last live frame
    assert events[-1]["status"] == "aborted"
    assert all(
        event["content"] != "early late-frame"
        for event in events
        if event["status"] == "running"
    )
    assert late_frame_dropped.is_set(), "the late running delta was published after invalidation"


def test_close_speaker_delta_is_idempotent(collector, fast_throttle):
    opened = threading.Event()

    def runner(*_args):
        with capture.speaker_delta_capture(**_capture_kwargs(round_id="round-idem")):
            opened.set()
            time.sleep(0.4)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    assert opened.wait(timeout=2)
    capture.close_speaker_delta(
        round_id="round-idem", participant_id="participant-1", status="completed"
    )
    capture.close_speaker_delta(
        round_id="round-idem", participant_id="participant-1", status="failed"
    )
    thread.join(timeout=3)

    events = _delta_events(collector.snapshot())
    terminal = [event for event in events if event["done"] and event["status"] != "running"]
    assert len(terminal) == 1
    assert terminal[0]["status"] == "completed"


# ---------------------------------------------------------------------------
# 4. round stop: deltas stop after the stop boundary
# ---------------------------------------------------------------------------


def test_round_stop_emits_stopped_terminal_and_stops_deltas(
    collector, fast_throttle, monkeypatch
):
    from core.ui import get_ui

    monkeypatch.setattr(
        chat_room_service,
        "_chat_room_round_stop_reason",
        lambda _round_id: "stopped_by_user",
    )

    def runner(_participant, _prompt, _context):
        with capture.speaker_delta_capture(**_capture_kwargs(round_id="round-stop")):
            get_ui().stream_response("被截断的发言", done=False)
            raise RuntimeError("interrupted by stop")

    participant = {
        "participantId": "participant-1",
        "agentId": "agent-1",
        "sessionId": "session-1",
    }
    message = chat_room_service._run_one_speaker(
        participant, "prompt", {"roundId": "round-stop"}, runner
    )
    assert message["status"] == "stopped"

    events = _delta_events(collector.snapshot())
    assert events[-1]["status"] == "stopped"
    assert events[-1]["done"] is True
    published_before = len(events)

    # ticket invalidated: any later close attempt stays a no-op
    capture.close_speaker_delta(
        round_id="round-stop", participant_id="participant-1", status="failed"
    )
    assert len(_delta_events(collector.snapshot())) == published_before


# ---------------------------------------------------------------------------
# 5. challenge rooms never stream deltas
# ---------------------------------------------------------------------------


def _plain_room():
    return {"roomId": "room-plain", "purpose": "discussion"}


def test_speaker_delta_gate_disables_challenge_rooms(monkeypatch):
    assert chat_room_service._speaker_delta_capture_enabled(
        _plain_room(), {}, "round_robin", {}, None
    )

    challenge_discussion_room = {
        "config": {
            "scopeAuthority": "workflow_discussion_scope.v1",
            "discussionScope": {"questionId": "Q1"},
            "discussionScopeHash": "hash-1",
        }
    }
    assert not chat_room_service._speaker_delta_capture_enabled(
        challenge_discussion_room, {}, "round_robin", {}, None
    )
    # receipt authority present (formal challenge meeting)
    assert not chat_room_service._speaker_delta_capture_enabled(
        _plain_room(), {}, "round_robin", {}, {"schemaVersion": 1}
    )
    # challenge meeting types in round config or room payload config
    for meeting_config in (
        {"meetingType": "hypothesis_review"},
        {"meetingType": "hypothesis_candidate_generation"},
    ):
        assert not chat_room_service._speaker_delta_capture_enabled(
            _plain_room(), {"config": meeting_config}, "round_robin", meeting_config, None
        )
    # kill switch off (service-side binding is what the gate reads)
    monkeypatch.setattr(chat_room_service, "CHAT_ROOM_SPEAKER_DELTA_ENABLED", False)
    assert not chat_room_service._speaker_delta_capture_enabled(
        _plain_room(), {}, "round_robin", {}, None
    )
    monkeypatch.undo()
    # non-ordinary mode
    assert not chat_room_service._speaker_delta_capture_enabled(
        _plain_room(), {}, "debate", {}, None
    )


def test_round_context_wiring_for_plain_and_challenge_rooms(monkeypatch):
    captured_contexts: list[dict] = []

    def fake_runner(participant, prompt, context):
        captured_contexts.append(dict(context))
        return {"status": "completed", "raw_output": "ok", "summary": "ok"}

    participants = [
        {"participantId": "participant-1", "agentId": "agent-1", "sessionId": "session-1"}
    ]

    def run_round(room, round_payload):
        chat_room_service._execute_chat_room_round(
            room["roomId"],
            round_payload["roundId"],
            room,
            round_payload,
            participants,
            fake_runner,
            "zh",
            None,
        )

    # Common mocks so the round engine can run without stores/work-runs.
    def apply_common_mocks():
        monkeypatch.setattr(chat_room_service, "_record_room_event", lambda *a, **k: None)
        monkeypatch.setattr(chat_room_service, "_persist_chat_room_work_run", lambda *a, **k: None)
        monkeypatch.setattr(
            chat_room_service, "_publish_chat_room_detail_snapshot", lambda *a, **k: None
        )
        monkeypatch.setattr(
            chat_room_service, "_stopped_chat_room_round_detail", lambda *a, **k: None
        )
        monkeypatch.setattr(
            chat_room_service, "_request_challenge_room_execution_stop", lambda *a, **k: ""
        )
        monkeypatch.setattr(
            chat_room_service, "_meeting_digest_ttl_mute_for_context", lambda *a, **k: None
        )
        monkeypatch.setattr(
            chat_room_service,
            "_build_participant_prompt",
            lambda *a, **k: "prompt",
        )
        monkeypatch.setattr(
            chat_room_service, "_speaker_call_timeout_seconds", lambda _context: 5.0
        )
        monkeypatch.setattr(
            chat_room_service, "_clear_chat_room_round_control", lambda *a, **k: None
        )

    def fake_store_load():
        return {
            "rooms": [
                {
                    "roomId": current_room["roomId"],
                    "rounds": [dict(current_round)],
                }
            ]
        }

    current_room: dict = {}
    current_round: dict = {}

    class _FakeStore:
        def load(self):
            return fake_store_load()

        def save(self, state):
            return None

    monkeypatch.setattr(chat_room_service, "_store", lambda: _FakeStore())

    apply_common_mocks()

    # plain room: capture enabled
    current_room = _plain_room()
    current_round = {
        "roundId": "round-plain",
        "mode": "round_robin",
        "topic": "t",
        "purpose": "discussion",
        "status": "running",
        "messages": [],
    }
    run_round(
        current_room,
        {**current_round, "caseState": {}, "config": {}},
    )
    assert captured_contexts, "plain room runner never invoked"
    assert captured_contexts[0]["_speakerDeltaCapture"] is True

    # challenge room: capture disabled
    captured_contexts.clear()
    current_room = {
        "roomId": "room-challenge",
        "purpose": "discussion",
        "config": {
            "scopeAuthority": "workflow_discussion_scope.v1",
            "discussionScope": {"questionId": "Q1"},
            "discussionScopeHash": "hash-1",
        },
    }
    current_round = {
        "roundId": "round-challenge",
        "mode": "round_robin",
        "topic": "challenge",
        "purpose": "discussion",
        "status": "running",
        "messages": [],
    }
    run_round(
        current_room,
        {**current_round, "caseState": {}, "config": {}},
    )
    assert captured_contexts, "challenge room runner never invoked"
    assert captured_contexts[0]["_speakerDeltaCapture"] is False


# ---------------------------------------------------------------------------
# 6. snapshot frames are never evicted by delta fan-out
# ---------------------------------------------------------------------------


def test_delta_fanout_never_evicts_snapshot_frames(monkeypatch):
    subscriber: queue.Queue = queue.Queue(maxsize=chat_room_service._CHAT_ROOM_STREAM_QUEUE_SIZE)
    room_id = "room-full"
    monkeypatch.setattr(
        chat_room_service,
        "_CHAT_ROOM_STREAM_SUBSCRIBERS",
        {room_id: {subscriber}},
    )

    snapshot = {
        "type": "chat_room_detail",
        "roomId": room_id,
        "detail": {"rooms": []},
    }
    for _ in range(chat_room_service._CHAT_ROOM_STREAM_QUEUE_SIZE):
        subscriber.put_nowait(snapshot)

    delta_event = {
        "type": "chat_room_speaker_delta",
        "roomId": room_id,
        "roundId": "round-1",
        "participantId": "participant-1",
        "sessionId": "session-1",
        "turnId": "turn-1",
        "seq": 1,
        "stage": "answer",
        "content": "text",
        "done": False,
        "status": "running",
    }
    chat_room_service._publish_chat_room_speaker_delta(delta_event)

    frames = [subscriber.get_nowait() for _ in range(subscriber.qsize())]
    assert subscriber.empty()
    assert all(frame["type"] == "chat_room_detail" for frame in frames), (
        "snapshot frames must never be evicted by delta fan-out"
    )
    # a second snapshot published through the real path also lands
    monkeypatch.setattr(
        chat_room_service, "get_chat_room_detail", lambda _room_id: {"roomId": room_id}
    )
    chat_room_service._publish_chat_room_detail_snapshot(room_id)
    assert subscriber.qsize() == 1
    assert subscriber.get_nowait()["type"] == "chat_room_detail"


def test_delta_reaches_subscriber_queue(collector, fast_throttle, monkeypatch):
    subscriber: queue.Queue = queue.Queue(maxsize=chat_room_service._CHAT_ROOM_STREAM_QUEUE_SIZE)
    room_id = "room-1"
    monkeypatch.setattr(
        chat_room_service,
        "_CHAT_ROOM_STREAM_SUBSCRIBERS",
        {room_id: {subscriber}},
    )
    # Route the sink through the real fan-out for this end-to-end check.
    capture.set_delta_publisher(chat_room_service._publish_chat_room_speaker_delta)
    with capture.speaker_delta_capture(**_capture_kwargs()):
        from core.ui import get_ui

        get_ui().stream_response("流式内容", done=False)
    frames = []
    while not subscriber.empty():
        frames.append(subscriber.get_nowait())
    types = [frame["type"] for frame in frames]
    assert "chat_room_speaker_delta" in types


# ---------------------------------------------------------------------------
# 7. direct-chat capture context and chat-room capture coexist
# ---------------------------------------------------------------------------


def test_install_orders_both_preserve_direct_chat_layer():
    # Order A: chat-room proxy first, direct-chat wrap afterwards.
    ui_a = _FakeUi()
    capture._ensure_chat_room_ui_capture_proxy(ui_a)
    assert getattr(ui_a, "_vibelution_chat_room_capture_wrapped") is True
    session_stream_capture._ensure_session_ui_capture_hooks(ui_a)
    assert bool(getattr(ui_a, "_vibelution_session_capture_wrapped", False))

    # Order B: direct-chat wrap first, chat-room proxy layered on top.
    ui_b = _FakeUi()
    session_stream_capture._ensure_session_ui_capture_hooks(ui_b)
    assert bool(getattr(ui_b, "_vibelution_session_capture_wrapped", False))
    capture._ensure_chat_room_ui_capture_proxy(ui_b)
    assert getattr(ui_b, "_vibelution_chat_room_capture_wrapped") is True
    # idempotent re-entry must not double-wrap
    capture._ensure_chat_room_ui_capture_proxy(ui_b)


def test_chat_room_delta_silent_without_capture_context(collector, fast_throttle):
    fake_ui = _FakeUi()
    capture._ensure_chat_room_ui_capture_proxy(fake_ui)
    # no chat-room capture context on this thread: no deltas
    fake_ui.stream_response("没有上下文", done=True)
    assert _delta_events(collector.snapshot()) == []
    # the underlying original still ran
    assert fake_ui.original_response_calls == 1


def test_direct_chat_and_chat_room_contexts_coexist(
    monkeypatch, fast_throttle, collector
):
    fake_ui = _FakeUi()
    live_output_writes: list[dict] = []
    monkeypatch.setattr(
        session_stream_capture,
        "_service",
        lambda: session_service_stub(live_output_writes),
    )

    # Order B: direct-chat wrap first, chat-room proxy layered on top.
    session_stream_capture._ensure_session_ui_capture_hooks(fake_ui)
    capture._ensure_chat_room_ui_capture_proxy(fake_ui)

    session_turn = session_stream_capture.SessionTurnCapture(
        session_id="session-direct",
        turn_id="turn-direct",
    )
    token = session_stream_capture._SESSION_UI_CAPTURE_CONTEXT.set(
        {"ui": fake_ui, "sessionId": "session-direct", "capture": session_turn}
    )
    try:
        with capture.speaker_delta_capture(**_capture_kwargs()):
            fake_ui.stream_response("直聊同线程共存", done=True)
    finally:
        session_stream_capture._SESSION_UI_CAPTURE_CONTEXT.reset(token)

    # direct-chat capture recorded the content (behavior unchanged)
    assert "直聊同线程共存" in str(session_turn.content)
    # the direct-chat live-output path executed as usual
    assert live_output_writes, "expected direct-chat live output write"
    # chat-room layer observed the same callback chain
    events = _delta_events(collector.snapshot())
    assert events and events[-1]["content"] == "直聊同线程共存"


def session_service_stub(live_output_writes: list[dict]):
    """Minimal session_service stand-in for the direct-chat proxy path."""

    class _Stub:
        def _sanitize_message_content(self, role: str, text: str) -> str:
            return str(text or "")

        def _set_session_live_output(self, session_id, **kwargs):
            live_output_writes.append({"sessionId": session_id, **kwargs})

        def _sanitize_thought_delta_text(self, text: str) -> str:
            return str(text or "")

        def _set_session_model_thinking_live_output(self, *args, **kwargs):
            return None

        def _is_mental_model_enabled_for_turn(self, value):
            return False

        def _live_mental_snapshot(self, *args, **kwargs):
            return None

        def get_web_language(self):
            return "zh"

        def record_runtime_scene_event(self, *args, **kwargs):
            return {"accepted": True}

        def get_event_bus(self):
            class _Bus:
                def subscribe(self, *args, **kwargs):
                    return "cb"

                def unsubscribe_by_id(self, *args, **kwargs):
                    return None

            return _Bus()

    return _Stub()


def test_chat_room_context_is_thread_scoped(collector, fast_throttle):
    from core.ui import get_ui

    other_thread_events: list[int] = []

    with capture.speaker_delta_capture(**_capture_kwargs()):
        get_ui().stream_response("主线程帧", done=False)
        baseline = len(collector.snapshot())

        def other_thread():
            # ContextVar default is empty in a fresh thread: no deltas.
            get_ui().stream_response("别的线程帧", done=True)
            other_thread_events.append(len(collector.snapshot()) - baseline)

        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join(timeout=3)

    assert other_thread_events == [0]
