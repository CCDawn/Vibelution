from __future__ import annotations

import copy

from core.web.services import chat_room_service


class _RoomStore:
    def __init__(self) -> None:
        self.state = {
            "rooms": [
                {"roomId": "research-room", "config": {"teamId": "research-team"}, "status": "ready"},
                {"roomId": "other-room", "config": {"teamId": "other-team"}, "status": "ready"},
            ]
        }

    def load(self):
        return copy.deepcopy(self.state)

    def save(self, state):
        self.state = copy.deepcopy(state)


def test_team_room_reset_is_scoped_reversible_and_finalizable(monkeypatch) -> None:
    store = _RoomStore()
    monkeypatch.setattr(chat_room_service, "_store", lambda: store)

    stage = chat_room_service.prepare_team_chat_room_reset(
        "research-team", reset_id="reset-room-1", room_ids=["research-room"]
    )
    assert [item["roomId"] for item in store.state["rooms"]] == ["other-room"]

    chat_room_service.purge_team_chat_room_reset(stage, reset_id="reset-room-1")
    restored = chat_room_service.restore_team_chat_room_reset(stage, reset_id="reset-room-1")
    assert restored["restoredCount"] == 1
    assert {item["roomId"] for item in store.state["rooms"]} == {"research-room", "other-room"}

    second = chat_room_service.prepare_team_chat_room_reset(
        "research-team", reset_id="reset-room-2", room_ids=["research-room"]
    )
    chat_room_service.purge_team_chat_room_reset(second, reset_id="reset-room-2")
    finalized = chat_room_service.destroy_team_chat_room_reset(second, reset_id="reset-room-2")
    assert finalized["status"] == "destroyed"
    assert [item["roomId"] for item in store.state["rooms"]] == ["other-room"]
