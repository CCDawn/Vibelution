"""Guidance rows must reach a settled state instead of waiting forever."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.chat.turn_journal import EVENT_TURN_STEER, EVENT_USER_MESSAGE
from core.web.services.session import turn_steer


@pytest.fixture(autouse=True)
def _clear_consumed_keys():
    turn_steer._CONSUMED_GUIDE_KEYS.clear()
    yield
    turn_steer._CONSUMED_GUIDE_KEYS.clear()


def _guide(
    event_id: str = "evt-guide",
    *,
    turn_id: str = "turn-1",
    sequence: int = 10,
    steer_id: str = "steer-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        event_id=event_id,
        event_type=EVENT_USER_MESSAGE,
        turn_id=turn_id,
        sequence=sequence,
        payload={
            "content": "check the queue contract",
            "metadata": {"kind": "user_guidance", "steerId": steer_id},
        },
    )


def _steer_like(
    disposition: str,
    *,
    sequence: int,
    turn_id: str = "turn-1",
    steer_id: str = "steer-1",
    delivery: str = "queue",
    user_event_id: str = "evt-guide",
    user_sequence: int = 10,
) -> SimpleNamespace:
    payload = {
        "schema": "turn_steer.v1",
        "steerId": steer_id,
        "delivery": delivery,
        "disposition": disposition,
        "targetTurnId": turn_id,
    }
    if disposition == "drained":
        payload["userMessageEventId"] = user_event_id
        payload["userMessageSequence"] = user_sequence
    return SimpleNamespace(
        event_id=f"steer-evt-{disposition}",
        event_type=EVENT_TURN_STEER,
        turn_id=turn_id,
        sequence=sequence,
        payload=payload,
    )


def test_delivery_change_settles_the_row_as_queued() -> None:
    state = turn_steer.guidance_metadata_from_events(
        [_guide(), _steer_like("delivery_changed", sequence=20)]
    )

    assert state["evt-guide"]["guidanceState"] == "queued"
    assert state["evt-guide"]["guidanceDelivery"] == "queue"


def test_promotion_wins_over_delivery_change() -> None:
    state = turn_steer.guidance_metadata_from_events(
        [
            _guide(),
            _steer_like("delivery_changed", sequence=20),
            _steer_like("promoted", sequence=40),
        ]
    )

    assert state["evt-guide"]["guidanceState"] == "promoted"


def test_drained_receipt_records_the_consuming_turn() -> None:
    state = turn_steer.guidance_metadata_from_events(
        [_guide(), _steer_like("drained", sequence=20, delivery="guide")]
    )

    assert state["evt-guide"]["guidanceState"] == "drained"
    assert state["evt-guide"]["guidanceDrainedTurnId"] == "turn-1"


def test_guided_text_is_not_replayed_by_a_second_worker(monkeypatch) -> None:
    monkeypatch.setattr(turn_steer, "append_turn_steer_event", lambda *a, **k: None)
    events = [_guide()]

    first = turn_steer.drain_guidance_events("session-scope", "turn-1", events, set())
    second = turn_steer.drain_guidance_events("session-scope", "turn-1", events, set())

    assert len(first) == 1
    assert second == []


def test_a_new_process_replays_after_restart(monkeypatch) -> None:
    monkeypatch.setattr(turn_steer, "append_turn_steer_event", lambda *a, **k: None)
    events = [_guide()]

    assert len(turn_steer.drain_guidance_events("session-restart", "turn-1", events, set())) == 1
    # 模拟进程重启：会话级集合丢失，同一个 turn 的新 worker 必须还能拿到文本。
    turn_steer._CONSUMED_GUIDE_KEYS.clear()

    assert len(turn_steer.drain_guidance_events("session-restart", "turn-1", events, set())) == 1


def test_drained_receipt_names_the_injected_message(monkeypatch) -> None:
    receipts: list[tuple[dict, str]] = []

    def _capture(_session_id, _turn_id, receipt, *, correlation_id=""):
        receipts.append((dict(receipt), correlation_id))

    monkeypatch.setattr(turn_steer, "append_turn_steer_event", _capture)
    drained = turn_steer.drain_guidance_events("session-anchor", "turn-1", [_guide()], set())

    assert len(drained) == 1
    item = drained[0]
    assert item["steerId"] == "steer-1"
    assert item["injectedMessageId"] == "guidance-steer-1"
    assert item["text"].endswith("check the queue contract")
    assert receipts, "drained receipt must be written"
    receipt, correlation = receipts[0]
    assert correlation == "evt-guide"
    assert receipt["userMessageEventId"] == "evt-guide"
    assert receipt["injectedMessageIds"] == ["guidance-steer-1"]
