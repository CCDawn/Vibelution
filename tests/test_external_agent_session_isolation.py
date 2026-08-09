from __future__ import annotations

from core.infrastructure import developer_sandbox
from core.ui.chat_state import load_chat_state
from core.web.services import agent_directory_service, session_service


def test_external_task_session_is_hidden_and_does_not_change_active_conversation(
    tmp_path,
    monkeypatch,
) -> None:
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
    visible = session_service.create_chat_session(
        title="Visible conversation", lightweight=True
    )
    before = load_chat_state(tmp_path)

    external = session_service.create_chat_session(
        title="External task",
        agent_id=visible["agentId"],
        created_by="external_agent_task",
        conversation_index_kind=agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN,
        session_metadata={
            "source": "external_agent_task",
            "externalTaskId": "eat-1",
            "effectivePermissionProfile": "read_only",
        },
        lightweight=True,
        activate=False,
    )
    session_service.submit_session_message(
        external["id"],
        "External acceptance task",
        message_source="external_agent_task",
        message_metadata={
            "source": "external_agent_task",
            "taskId": "eat-1",
            "effectivePermissionProfile": "read_only",
        },
        lightweight_response=True,
    )

    after = load_chat_state(tmp_path)
    assert (
        before["active_conversation_id"]
        == after["active_conversation_id"]
        == visible["id"]
    )
    assert external["id"] != visible["id"]
    assert external["hiddenFromIndex"] is True
    assert (
        external["conversationIndexKind"]
        == agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN
    )
    assert external["id"] not in {
        item["id"] for item in session_service.list_sessions()
    }
    raw = next(
        item
        for item in after["conversations"]
        if item.get("conversation_id") == external["id"]
    )
    assert raw["metadata"] == {
        "source": "external_agent_task",
        "externalTaskId": "eat-1",
        "effectivePermissionProfile": "read_only",
    }
