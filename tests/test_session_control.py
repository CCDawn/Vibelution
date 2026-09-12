"""Focused tests for session stop / interrupt control."""

from __future__ import annotations

from core.web.services import session_service
from core.web.services.session import control


def _install_running_stop_fixtures(
    monkeypatch,
    *,
    turn_control,
    order: list[str],
    queued_turn_cancelled: bool,
    publish=None,
) -> None:
    original_request_stop = turn_control.request_stop

    def tracked_request_stop(reason: str) -> None:
        order.append("stop")
        original_request_stop(reason)

    turn_control.request_stop = tracked_request_stop  # type: ignore[method-assign]

    monkeypatch.setattr(session_service, "get_web_language", lambda: "zh")
    monkeypatch.setattr(session_service, "text_for", lambda lang, zh="", en="": zh)
    monkeypatch.setattr(session_service, "_is_session_running", lambda session_id: True)
    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda session_id: turn_control)
    monkeypatch.setattr(
        session_service,
        "_cancel_queued_session_turn",
        lambda session_id, turn_id: queued_turn_cancelled,
    )
    monkeypatch.setattr(session_service, "_record_chat_next_state_signal", lambda **kwargs: None)
    if publish is not None:
        monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", publish)


def test_running_stop_fast_ack_skips_detail_rebuild_and_publish(monkeypatch) -> None:
    order: list[str] = []
    turn_control = session_service.SessionTurnControl(session_id="session-live", turn_id="turn-1")

    def forbidden_detail(*args, **kwargs):
        raise AssertionError("running stop fast ack must not rebuild session detail")

    def forbidden_publish(*args, **kwargs):
        raise AssertionError("running stop fast ack must not publish a snapshot")

    _install_running_stop_fixtures(
        monkeypatch,
        turn_control=turn_control,
        order=order,
        queued_turn_cancelled=False,
        publish=forbidden_publish,
    )
    monkeypatch.setattr(session_service, "get_session_detail", forbidden_detail)

    payload = control.request_stop_session_turn(
        "session-live",
        expected_turn_id="turn-1",
        fast_ack=True,
    )

    # The worker owns the stopped snapshot and publishes it once it observes the
    # request; the HTTP path only acknowledges the stop.
    assert order == ["stop"]
    assert payload == {
        "id": "session-live",
        "currentPhase": "stopping",
        "stopRequested": True,
        "stopRequestedAt": turn_control.snapshot().get("stopRequestedAt") or "",
        "activeTurnId": "turn-1",
    }
    assert turn_control.stop_requested is True


def test_running_stop_default_still_returns_hydrated_detail(monkeypatch) -> None:
    order: list[str] = []
    turn_control = session_service.SessionTurnControl(session_id="session-live", turn_id="turn-1")
    detail_calls: list[str] = []

    def tracked_detail(session_id, **kwargs):
        detail_calls.append(session_id)
        return {"id": session_id, "currentPhase": "stopping", "messages": []}

    def tracked_publish(session_id, **kwargs):
        order.append("publish")

    _install_running_stop_fixtures(
        monkeypatch,
        turn_control=turn_control,
        order=order,
        queued_turn_cancelled=False,
        publish=tracked_publish,
    )
    monkeypatch.setattr(session_service, "get_session_detail", tracked_detail)

    payload = control.request_stop_session_turn("session-live", expected_turn_id="turn-1")

    assert order == ["stop", "publish"]
    assert detail_calls == ["session-live"]
    assert payload["messages"] == []
    assert turn_control.stop_requested is True


def test_queued_stop_still_persists_snapshot_and_returns_detail(monkeypatch) -> None:
    order: list[str] = []
    turn_control = session_service.SessionTurnControl(session_id="session-live", turn_id="turn-1")

    def tracked_persist(session_id, snapshot, *, lang):
        order.append("persist")

    def tracked_publish(session_id, **kwargs):
        order.append("publish")

    _install_running_stop_fixtures(
        monkeypatch,
        turn_control=turn_control,
        order=order,
        queued_turn_cancelled=True,
        publish=tracked_publish,
    )
    monkeypatch.setattr(session_service, "_persist_session_interrupted_snapshot", tracked_persist)
    monkeypatch.setattr(
        session_service,
        "_set_session_running",
        lambda session_id, running, turn_id=None: order.append("release"),
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda session_id, **kwargs: {
            "id": session_id,
            "currentPhase": "stopping",
            "stopRequested": True,
        },
    )

    payload = control.request_stop_session_turn("session-live", expected_turn_id="turn-1")

    assert order[0] == "stop"
    assert order.index("persist") < order.index("publish")
    assert order.index("release") < order.index("publish")
    assert payload["currentPhase"] == "stopping"
    assert turn_control.stop_requested is True
