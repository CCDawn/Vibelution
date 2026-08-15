"""Regression tests for intentional-delete tombstone safety on chat sessions.

Covers:
- T1: materialize guard blocks resurrection from a stale agent direct binding.
- T2: select after delete raises SessionNotFoundError (no resurrection).
- T3: repeated delete is idempotent (no 404 on second delete).
- T4: tombstone write failure is surfaced as a warning event (not silent).
- T5: normal (non-deleted) sessions still materialize successfully.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.ui.chat_state import load_chat_state, load_session_chat_state, save_chat_state
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    agent_bulk_delete_service,
    agent_directory_service,
    agent_mode_binding_service,
    chat_room_service,
    session_service,
    team_service,
)


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_bulk_delete_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)


def _create_direct_session(title: str = "Tombstone Safety Agent") -> tuple[dict, str]:
    session = session_service.create_chat_session(title=title)
    return session, str(session["agentId"])


def test_t1_materialize_guard_blocks_resurrection_from_stale_binding(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session, agent_id = _create_direct_session()

    session_service._delete_chat_session_state(session["id"])
    assert session_service._is_session_workspace_intentionally_deleted(session["id"]) is True

    # Simulate an unbind failure / race: agent still points at the deleted session.
    agent_directory_service.update_agent_instance(agent_id, direct_session_id=session["id"])

    # Materialization must be blocked by the tombstone, not resurrect the session.
    recovered = session_service._ensure_session_conversation_record(
        session["id"],
        source="session.llm_options",
    )
    assert recovered is False
    assert session_service.get_session_detail(session["id"]) is None
    session_ids = {item["id"] for item in session_service.list_sessions()}
    assert session["id"] not in session_ids


def test_t2_select_deleted_session_raises_not_found(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session, agent_id = _create_direct_session()

    session_service._delete_chat_session_state(session["id"])
    agent_directory_service.update_agent_instance(agent_id, direct_session_id=session["id"])

    with pytest.raises(session_service.SessionNotFoundError):
        session_service.select_chat_session(session["id"])
    assert session_service.get_session_detail(session["id"]) is None


def test_t3_repeated_delete_is_idempotent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session, _ = _create_direct_session()

    first = session_service._delete_chat_session_state(session["id"])
    assert "nextActiveSessionId" in first

    # Second delete on an already-tombstoned session must succeed, not 404.
    second = session_service._delete_chat_session_state(session["id"])
    assert "nextActiveSessionId" in second


def test_t4_tombstone_write_failure_is_surfaced(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session, _ = _create_direct_session()

    recorded: list[dict] = []

    def fake_record(event_type, phase, code, **kwargs):
        recorded.append({"eventType": event_type, "phase": phase, "code": code, **kwargs})

    def failing_workspace(session_id: str):
        raise PermissionError("workspace locked")

    monkeypatch.setattr(session_service, "record_runtime_scene_event", fake_record)
    monkeypatch.setattr(session_service, "_ensure_session_workspace", failing_workspace)

    marked = session_service._mark_session_workspace_intentionally_deleted(
        session["id"],
        reason="test_failure",
    )
    assert marked is False
    assert any(item["eventType"] == "conversation" and item["phase"] == "chat_state" for item in recorded)
    assert any(item["code"] == "conversation.tombstone_write_failed" for item in recorded)


def test_t5_normal_session_still_materializes(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session, _ = _create_direct_session()

    assert session_service._is_session_workspace_intentionally_deleted(session["id"]) is False
    # Select on an existing session must succeed.
    detail = session_service.select_chat_session(session["id"])
    assert detail.get("id") == session["id"]


class _BoomChatStateLock:
    def __enter__(self):
        raise AssertionError("ghost session path must not enter _CHAT_STATE_LOCK")

    def __exit__(self, exc_type, exc, tb):
        return False


def test_ghost_directory_session_select_404s_without_chat_state_lock(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(session_service, "_CHAT_STATE_LOCK", _BoomChatStateLock())
    with pytest.raises(session_service.SessionNotFoundError):
        session_service.select_chat_session("session-ghost-directory-only")


def test_ghost_directory_session_delete_succeeds_without_chat_state_lock(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(session_service, "_CHAT_STATE_LOCK", _BoomChatStateLock())
    result = session_service._delete_chat_session_state("session-ghost-directory-only")
    assert "nextActiveSessionId" in result


def test_ghost_directory_session_detail_skips_chat_state_lock(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(session_service, "_CHAT_STATE_LOCK", _BoomChatStateLock())
    assert session_service.get_session_detail("session-ghost-directory-only") is None


def test_workspace_recoverable_session_select_still_opens(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session, agent_id = _create_direct_session()
    session_id = session["id"]
    workspace = session_service._ensure_session_workspace(session_id)
    Path(workspace).joinpath("turn_journal.jsonl").write_text(
        '{"eventType":"user_message"}\n',
        encoding="utf-8",
    )
    agent_directory_service.update_agent_instance(agent_id, direct_session_id="")
    state = load_chat_state(tmp_path)
    conversations = []
    for item in state.get("conversations") or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("conversation_id") or item.get("conversationId") or "").strip()
        if item_id != session_id:
            conversations.append(item)
    state["conversations"] = conversations
    if str(state.get("active_conversation_id") or "").strip() == session_id:
        state["active_conversation_id"] = ""
    save_chat_state(tmp_path, state)
    assert load_session_chat_state(tmp_path, session_id) is None
    assert session_service._session_has_openable_body(session_id) is True
    detail = session_service.select_chat_session(session_id)
    assert detail.get("id") == session_id
