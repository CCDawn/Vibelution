import json
from contextlib import contextmanager

from core.ui.chat_state import chat_state_path, load_chat_state, save_chat_state
from core.web.services import session_service


def test_save_chat_state_uses_valid_replace_target(tmp_path):
    payload = {"version": 1, "conversations": [{"conversation_id": "default", "messages": []}]}

    save_chat_state(tmp_path, payload)

    path = chat_state_path(tmp_path)
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_load_chat_state_backs_up_corrupt_json(tmp_path):
    path = chat_state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"version": 1, "conversations": [', encoding="utf-8")

    assert load_chat_state(tmp_path) == {}

    backups = list(path.parent.glob(f"{path.name}.corrupt.*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == '{"version": 1, "conversations": ['
    assert path.read_text(encoding="utf-8") == '{"version": 1, "conversations": ['


def test_load_conversations_runs_inside_chat_state_transaction(monkeypatch, tmp_path):
    events: list[str] = []

    @contextmanager
    def fake_transaction(project_root):
        events.append(f"enter:{project_root}")
        yield
        events.append(f"exit:{project_root}")

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "chat_state_transaction", fake_transaction)
    monkeypatch.setattr(
        session_service,
        "load_chat_state",
        lambda _project_root: {
            "version": 1,
            "active_conversation_id": "default",
            "conversations": [{"conversation_id": "default", "title": "Default", "messages": []}],
        },
    )

    active_id, conversations = session_service._load_conversations(
        repair=False,
        agent_by_id={},
        lightweight=True,
    )

    assert active_id == "default"
    assert len(conversations) == 1
    assert events == [f"enter:{tmp_path}", f"exit:{tmp_path}"]
