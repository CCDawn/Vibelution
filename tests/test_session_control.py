"""Focused tests for session stop / interrupt control."""

from __future__ import annotations

from core.web.services import session_service
from core.web.services.session import control


def test_running_stop_signals_controller_before_session_detail(monkeypatch) -> None:
    order: list[str] = []
    turn_control = session_service.SessionTurnControl(session_id="session-live", turn_id="turn-1")

    original_request_stop = turn_control.request_stop

    def tracked_request_stop(reason: str) -> None:
        order.append("stop")
        original_request_stop(reason)

    turn_control.request_stop = tracked_request_stop  # type: ignore[method-assign]

    monkeypatch.setattr(session_service, "get_web_language", lambda: "zh")
    monkeypatch.setattr(session_service, "text_for", lambda lang, zh="", en="": zh)
    monkeypatch.setattr(session_service, "_is_session_running", lambda session_id: True)
    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda session_id: turn_control)
    monkeypatch.setattr(session_service, "_cancel_queued_session_turn", lambda session_id, turn_id: False)
    monkeypatch.setattr(session_service, "_record_chat_next_state_signal", lambda **kwargs: None)
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda session_id, **kwargs: order.append("detail") or {
            "id": session_id,
            "currentPhase": "stopping",
            "stopRequested": True,
        },
    )
    monkeypatch.setattr(
        session_service,
        "_publish_session_detail_snapshot",
        lambda session_id, **kwargs: order.append("publish"),
    )

    payload = control.request_stop_session_turn("session-live", expected_turn_id="turn-1")

    assert order[0] == "stop"
    assert order.index("stop") < order.index("detail")
    assert payload["currentPhase"] == "stopping"
    assert turn_control.stop_requested is True
