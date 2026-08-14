from __future__ import annotations

from core.infrastructure import developer_sandbox
from core.ui.chat_state import load_chat_state
from core.web.services import agent_directory_service, session_service


def _isolate_session_workspace(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda _context: None)
    monkeypatch.setattr(
        session_service,
        "_enqueue_direct_session_submit_kernel_trace",
        lambda **_kwargs: None,
    )


def test_submit_on_background_session_does_not_steal_viewing_pointer(tmp_path, monkeypatch) -> None:
    _isolate_session_workspace(tmp_path, monkeypatch)
    viewing = session_service.create_chat_session(title="Viewing", lightweight=True)
    background = session_service.create_chat_session(title="Background", lightweight=True)
    assert load_chat_state(tmp_path)["active_conversation_id"] == background["id"]

    session_service.select_chat_session(viewing["id"], lightweight=True)
    assert load_chat_state(tmp_path)["active_conversation_id"] == viewing["id"]

    session_service.submit_session_message(
        background["id"],
        "Run in the background",
        lightweight_response=True,
    )

    assert load_chat_state(tmp_path)["active_conversation_id"] == viewing["id"]


def test_create_child_session_defaults_do_not_switch_viewing_pointer(tmp_path, monkeypatch) -> None:
    _isolate_session_workspace(tmp_path, monkeypatch)
    parent = session_service.create_chat_session(title="Parent", lightweight=True)
    session_service.select_chat_session(parent["id"], lightweight=True)

    result = session_service.create_child_session(
        parent["id"],
        user_request="Independent side task",
        task_title="Side task",
        split_reason="Keep the parent viewing pointer",
    )

    assert result["switched"] is False
    assert load_chat_state(tmp_path)["active_conversation_id"] == parent["id"]
    assert result["childSessionId"] != parent["id"]
