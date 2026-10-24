"""Frozen meeting-round identity must not stop a later round in the same room."""
from copy import deepcopy
from unittest.mock import Mock

import pytest
from core.web.services import chat_room_service as rooms


@pytest.fixture
def native_round(monkeypatch):
    state = {"rooms": [{"roomId": "room-owned", "activeRoundId": "round-current",
        "status": "running", "rounds": [
            {"roundId": "round-old", "status": "completed"},
            {"roundId": "round-current", "status": "running"},
        ]}]}
    store = Mock()
    store.load.side_effect = lambda: deepcopy(state)
    store.save.side_effect = lambda value: state.update(deepcopy(value))
    monkeypatch.setattr(rooms, "_store", lambda: store)
    monkeypatch.setattr(rooms, "get_web_language", lambda: "zh")
    monkeypatch.setattr(rooms, "_room_to_api", lambda room: room)
    effects = {}
    for name in ["_request_chat_room_round_stop", "_persist_chat_room_work_run",
                 "_record_room_event", "_append_room_timeline_event", "_publish_chat_room_detail_snapshot"]:
        effects[name] = Mock()
        monkeypatch.setattr(rooms, name, effects[name])
    effects["reservation"] = Mock()
    monkeypatch.setattr(rooms.session_service, "cancel_agent_execution_reservation", effects["reservation"])
    return state, store, effects


@pytest.mark.parametrize("expected", ["round-old", "round-foreign", ""])
def test_frozen_round_mismatch_has_no_stop_or_persistence_side_effect(native_round, expected):
    state, store, effects = native_round
    before = deepcopy(state)
    with pytest.raises(rooms.ChatRoomBusyError):
        rooms.stop_chat_room_round("room-owned", expected_round_id=expected)
    assert state == before
    store.save.assert_not_called()
    for effect in effects.values():
        effect.assert_not_called()


@pytest.mark.parametrize("explicit", [False, True])
def test_current_round_stop_preserves_legacy_behavior_and_identity(native_round, explicit):
    state, store, effects = native_round
    kwargs = {"expected_round_id": "round-current"} if explicit else {}
    result = rooms.stop_chat_room_round("room-owned", reason="owned workflow cancelled", **kwargs)
    assert result["activeRoundId"] == "round-current"
    assert result["status"] == "stopping"
    assert state["rooms"][0]["rounds"][0]["status"] == "completed"
    effects["_request_chat_room_round_stop"].assert_called_once_with("round-current", "owned workflow cancelled")
    effects["reservation"].assert_called_once_with("round-current")
    store.save.assert_called_once()
