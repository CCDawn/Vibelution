from core.chatroom.store import ChatRoomStore
from core.web.services import chat_room_service


def test_read_snapshot_keeps_nested_mutations_local(tmp_path, monkeypatch):
    store = ChatRoomStore(root=tmp_path)
    store.save({"rooms": [{"id": "r1", "messages": [{"content": "original"}]}]})
    monkeypatch.setattr(chat_room_service, "_store", lambda: store)

    first = chat_room_service.read_chat_rooms_snapshot()
    first[0]["messages"][0]["content"] = "changed"
    first.append({"id": "new"})

    second = chat_room_service.read_chat_rooms_snapshot()
    assert second == [{"id": "r1", "messages": [{"content": "original"}]}]
    assert store.load()["rooms"] == second
