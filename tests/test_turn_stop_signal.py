"""Stop event delivery for the current model request and command."""

from __future__ import annotations

import threading
import time

from core.llm.client import _wait_cancel_watch_tick
from core.orchestration.turn_stop_signal import bind_stop_probe
from core.web.services.session_service import SessionTurnControl


def test_request_stop_wakes_the_stop_event_and_keeps_the_first_reason() -> None:
    control = SessionTurnControl(session_id="session-1", turn_id="turn-1")
    assert control.stop_event.is_set() is False

    control.request_stop("操作者请求停止当前轮。")
    control.request_stop("later")

    assert control.stop_event.is_set() is True
    assert control.stop_reason == "操作者请求停止当前轮。"
    fresh = SessionTurnControl(session_id="session-1", turn_id="turn-2")
    assert fresh.stop_event.is_set() is False
    assert fresh.stop_event is not control.stop_event


def test_bind_stop_probe_copies_the_event_onto_the_callable_the_watcher_holds() -> None:
    event = threading.Event()

    def source() -> str:
        return "操作者请求停止当前轮。"

    source._vibelution_stop_event = event  # type: ignore[attr-defined]

    def reason() -> str:
        return source()

    probe = bind_stop_probe(reason, source)
    assert probe is not None
    assert probe is not reason
    assert probe() == "操作者请求停止当前轮。"
    assert getattr(probe, "_vibelution_stop_event", None) is event
    assert bind_stop_probe(reason, reason) is reason


def test_cancel_watch_wakes_when_the_stop_event_is_set() -> None:
    finished = threading.Event()
    stop = threading.Event()

    def checker() -> str:
        return ""

    checker._vibelution_stop_event = stop  # type: ignore[attr-defined]

    def _set_stop() -> None:
        time.sleep(0.02)
        stop.set()

    threading.Thread(target=_set_stop, daemon=True).start()
    started = time.monotonic()
    finished_first = _wait_cancel_watch_tick(checker, finished, 2.0)
    elapsed = time.monotonic() - started

    assert finished_first is False
    assert elapsed < 0.3


def test_cancel_watch_without_a_stop_event_still_waits_for_finish() -> None:
    finished = threading.Event()

    def checker() -> str:
        return ""

    threading.Timer(0.02, finished.set).start()
    assert _wait_cancel_watch_tick(checker, finished, 1.0) is True
