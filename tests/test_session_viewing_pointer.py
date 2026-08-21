from __future__ import annotations

import time

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


def test_select_only_writes_target_last_viewed_preference_without_touching_other_session_data(
    tmp_path, monkeypatch
) -> None:
    """`/select` semantics after ADR 0009: it records a last-viewed preference.

    It must never act as a window navigation authority: selecting B must not
    mutate A's persisted conversation data, and must not reorder the session
    list around the pointer.
    """
    _isolate_session_workspace(tmp_path, monkeypatch)
    first = session_service.create_chat_session(title="First", lightweight=True)
    second = session_service.create_chat_session(title="Second", lightweight=True)

    first_before = session_service.get_session_detail(first["id"])
    listed_before = [item["id"] for item in session_service.list_sessions()]
    own_order_before = [
        item for item in listed_before if item in {first["id"], second["id"]}
    ]

    session_service.select_chat_session(second["id"], lightweight=True)

    assert load_chat_state(tmp_path)["active_conversation_id"] == second["id"]

    first_after = session_service.get_session_detail(first["id"])
    assert first_after["title"] == first_before["title"]
    assert first_after["messages"] == first_before["messages"]
    # The pointer must not reorder the session list.
    listed_after = [item["id"] for item in session_service.list_sessions()]
    own_order_after = [
        item for item in listed_after if item in {first["id"], second["id"]}
    ]
    assert own_order_after == own_order_before


def test_session_list_order_is_recency_not_viewing_pointer(tmp_path, monkeypatch) -> None:
    _isolate_session_workspace(tmp_path, monkeypatch)
    older = session_service.create_chat_session(title="Older", lightweight=True)
    # Session timestamps are second-granular: force the two sessions onto
    # distinct seconds so list order is pinned by real recency instead of a
    # same-second tie that a late async directory write can reshuffle.
    time.sleep(1.1)
    newer = session_service.create_chat_session(title="Newer", lightweight=True)

    listed_before = [item["id"] for item in session_service.list_sessions()]
    own_order_before = [
        item for item in listed_before if item in {newer["id"], older["id"]}
    ]

    # The operator last viewed the *older* session; the list must keep its
    # pre-select order and must not pin the pointer to the top.
    session_service.select_chat_session(older["id"], lightweight=True)

    assert load_chat_state(tmp_path)["active_conversation_id"] == older["id"]
    listed_after = [item["id"] for item in session_service.list_sessions()]
    own_order_after = [
        item for item in listed_after if item in {newer["id"], older["id"]}
    ]
    assert own_order_after == own_order_before
