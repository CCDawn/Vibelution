# -*- coding: utf-8 -*-
"""Integration contract: fork a new session from one node of a journal.

Covers the roadmap exit of the branch feature: the copied journal must replay
self-consistently (messages, branch analysis, continuation), both scopes must
respect their boundaries, provenance metadata must be recorded, running or
unsettled source turns must be rejected, and the source journal must stay
byte-identical.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.chat.session_catalog import notify_session_catalog_dirty
from core.chat.conversation_branches import (
    sibling_node_ids,
    visible_messages_with_branch_info,
)
from core.chat.turn_journal import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_BRANCH_REBASE,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    latest_open_turn_id,
    load_turn_events,
)
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import session_service
from core.web.services.session.branch_head import switch_session_head
from core.web.services.session.fork_session import (
    FORK_SCOPE_VISIBLE_PATH,
    FORK_SCOPE_WITH_BRANCHES,
    fork_session_from_node,
)


def _replay_rows(root: Path, session_id: str) -> list[tuple[str, str]]:
    """Authoritative active-path ledger replay as (role, content) rows."""

    messages, _leaf_id, _branch_id = visible_messages_with_branch_info(
        load_turn_events(root, session_id)
    )
    return [
        (str(message.get("role") or ""), str(message.get("content") or ""))
        for message in messages
    ]


@pytest.fixture()
def fork_root(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    return tmp_path


def _append(session_id: str, turn_id: str, event_type: str, **kwargs):
    return session_service._append_session_conversation_event(
        session_id,
        turn_id,
        event_type,
        source="test",
        **kwargs,
    )


def _turn(session_id: str, turn_id: str, user_text: str, answer_text: str) -> dict:
    _append(session_id, turn_id, EVENT_TURN_STARTED, visible_in_model=False)
    user_event = _append(
        session_id,
        turn_id,
        EVENT_USER_MESSAGE,
        payload={"content": user_text},
    )
    answer_event = _append(
        session_id,
        turn_id,
        EVENT_ASSISTANT_MESSAGE,
        payload={"content": answer_text},
    )
    _append(session_id, turn_id, EVENT_TURN_COMPLETED, visible_in_model=False)
    return {"user": user_event, "answer": answer_event}


def _regenerate(
    session_id: str,
    turn_id: str,
    from_event_id: str,
    user_text: str,
    answer_text: str,
) -> dict:
    _append(
        session_id,
        turn_id,
        EVENT_BRANCH_REBASE,
        status="recorded",
        payload={
            "operation": "regenerate",
            "branchId": "branch-regen",
            "fromEventId": from_event_id,
            "replacedTurnIds": [],
        },
        visible_in_model=False,
        projection_kind="session_branch_rebase",
        parent_event_id=from_event_id,
    )
    return _turn(session_id, turn_id, user_text, answer_text)


def _source_session(root: Path) -> tuple[str, dict, dict]:
    """Two settled turns plus one regenerate branch off the first answer."""

    created = session_service.create_chat_session(title="源会话")
    session_id = str(created["id"])
    turn1 = _turn(session_id, "turn-1", "原始需求", "原始回答")
    turn2 = _turn(session_id, "turn-2", "后续追问", "后续回答")
    branch = _regenerate(
        session_id,
        "turn-3",
        turn1["answer"].event_id,
        "重问",
        "重答",
    )
    notify_session_catalog_dirty(root, session_id, "test-seed")
    return session_id, turn1, {**turn2, "branch": branch}


def _node_id_for(session_id: str, event_id: str) -> str:
    detail = session_service.get_session_detail(session_id) or {}
    for message in detail.get("messages") or []:
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if str(metadata.get("eventId") or "") == event_id:
            return str(message.get("nodeId") or "")
    return ""


def _source_journal(root: Path, session_id: str):
    return [event.to_dict() for event in load_turn_events(root, session_id)]


def test_fork_visible_path_replays_prefix_and_continues(fork_root) -> None:
    session_id, turn1, _rest = _source_session(fork_root)
    before = _source_journal(fork_root, session_id)
    node_id = _node_id_for(session_id, turn1["answer"].event_id)
    assert node_id

    detail = fork_session_from_node(session_id, node_id, scope=FORK_SCOPE_VISIBLE_PATH)
    new_id = str(detail["id"])
    assert new_id and new_id != session_id
    assert "分叉" in detail["title"] or "fork" in detail["title"].lower()

    # Replay is self-consistent: exactly the path up to the target answer.
    # (Assistant text lives in ledger replay; detail surfaces it via turnItems.)
    assert _replay_rows(fork_root, new_id) == [
        ("user", "原始需求"),
        ("assistant", "原始回答"),
    ]
    messages = detail.get("messages") or []
    assert [str(message.get("role") or "") for message in messages] == ["user", "assistant"]

    # Branch analysis works and the copy carries no dangling open turn.
    new_events = load_turn_events(fork_root, new_id)
    assert latest_open_turn_id(new_events) == ""
    view = session_service.analyze_conversation_branches(new_events)
    assert view.active_leaf_id

    # Node lineage is preserved: the forked answer keeps the source node id.
    forked_detail = session_service.get_session_detail(new_id) or {}
    assert str(forked_detail["messages"][1].get("nodeId") or "") == node_id

    # The forked session is a normal session: it can continue with new turns.
    _append(new_id, "turn-new-1", EVENT_TURN_STARTED, visible_in_model=False)
    _append(
        new_id,
        "turn-new-1",
        EVENT_USER_MESSAGE,
        payload={"content": "继续追问"},
    )
    _append(
        new_id,
        "turn-new-1",
        EVENT_ASSISTANT_MESSAGE,
        payload={"content": "继续回答"},
    )
    _append(new_id, "turn-new-1", EVENT_TURN_COMPLETED, visible_in_model=False)
    continued = session_service.get_session_detail(new_id) or {}
    assert _replay_rows(fork_root, new_id) == [
        ("user", "原始需求"),
        ("assistant", "原始回答"),
        ("user", "继续追问"),
        ("assistant", "继续回答"),
    ]
    assert [str(message.get("role") or "") for message in continued.get("messages") or []] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]

    # Source journal stays untouched.
    assert _source_journal(fork_root, session_id) == before


def test_fork_from_user_message_leaves_closed_journal(fork_root) -> None:
    session_id, _turn1, rest = _source_session(fork_root)
    branch = rest["branch"]
    node_id = _node_id_for(session_id, branch["user"].event_id)
    assert node_id

    detail = fork_session_from_node(session_id, node_id)
    new_id = str(detail["id"])
    new_events = load_turn_events(fork_root, new_id)
    # The tail turn was cut at its user message: no scaffolding, no open turn.
    assert latest_open_turn_id(new_events) == ""
    assert not [
        event
        for event in new_events
        if event.event_type == EVENT_TURN_STARTED and event.turn_id == "turn-3"
    ]
    assert _replay_rows(fork_root, new_id) == [
        ("user", "原始需求"),
        ("assistant", "原始回答"),
        ("user", "重问"),
    ]


def test_fork_scope_boundary_between_visible_path_and_branches(fork_root) -> None:
    session_id, _turn1, rest = _source_session(fork_root)
    branch = rest["branch"]
    answer_node = _node_id_for(session_id, branch["answer"].event_id)
    assert answer_node

    plain = fork_session_from_node(session_id, answer_node, scope=FORK_SCOPE_VISIBLE_PATH)
    plain_messages = plain.get("messages") or []
    assert [str(message.get("role") or "") for message in plain_messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert _replay_rows(fork_root, str(plain["id"]))[-1] == ("assistant", "重答")
    plain_events = load_turn_events(fork_root, str(plain["id"]))
    assert not [event for event in plain_events if event.event_type == EVENT_BRANCH_REBASE]

    with_branches = fork_session_from_node(
        session_id,
        answer_node,
        scope=FORK_SCOPE_WITH_BRANCHES,
    )
    branch_events = load_turn_events(fork_root, str(with_branches["id"]))
    assert [event for event in branch_events if event.event_type == EVENT_BRANCH_REBASE]
    # Active path still ends at the forked answer.
    assert _replay_rows(fork_root, str(with_branches["id"]))[-1] == ("assistant", "重答")

    # Scope boundary shows up in the sibling grouping of the regenerated user
    # message: visible_path carries it alone, with_branches keeps the
    # superseded sibling version addressable next to it.
    plain_view = session_service.analyze_conversation_branches(plain_events)
    plain_rows, _leaf, _branch = visible_messages_with_branch_info(plain_events)
    plain_regenerated_node = next(
        str(message.get("nodeId") or "")
        for message in plain_rows
        if message.get("role") == "user" and message.get("content") == "重问"
    )
    assert plain_regenerated_node
    assert sibling_node_ids(plain_view, plain_regenerated_node) == (plain_regenerated_node,)

    branch_view = session_service.analyze_conversation_branches(branch_events)
    branch_rows, _leaf, _branch = visible_messages_with_branch_info(branch_events)
    branch_regenerated_node = next(
        str(message.get("nodeId") or "")
        for message in branch_rows
        if message.get("role") == "user" and message.get("content") == "重问"
    )
    branch_siblings = sibling_node_ids(branch_view, branch_regenerated_node)
    assert len(branch_siblings) == 2
    assert branch_regenerated_node in branch_siblings


def test_fork_records_forked_from_metadata(fork_root) -> None:
    session_id, turn1, _rest = _source_session(fork_root)
    node_id = _node_id_for(session_id, turn1["answer"].event_id)
    detail = fork_session_from_node(session_id, node_id, scope=FORK_SCOPE_WITH_BRANCHES)
    new_id = str(detail["id"])
    state = session_service.load_session_chat_state(fork_root, new_id) or {}
    forked_from = state.get("forkedFrom")
    assert isinstance(forked_from, dict)
    assert forked_from.get("sessionId") == session_id
    assert forked_from.get("nodeId") == node_id
    assert forked_from.get("scope") == FORK_SCOPE_WITH_BRANCHES
    assert str(forked_from.get("forkedAt") or "").strip()


def test_fork_rejects_running_source_session(fork_root, monkeypatch) -> None:
    session_id, turn1, _rest = _source_session(fork_root)
    node_id = _node_id_for(session_id, turn1["answer"].event_id)
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: True)
    with pytest.raises(session_service.SessionBusyError):
        fork_session_from_node(session_id, node_id)


def test_fork_rejects_unsettled_journal_turn(fork_root) -> None:
    session_id, turn1, _rest = _source_session(fork_root)
    node_id = _node_id_for(session_id, turn1["answer"].event_id)
    # Resolve the node before appending the open turn: a detail read would
    # reconcile (close) the open turn, which is exactly the production flow.
    _append(session_id, "turn-open", EVENT_TURN_STARTED, visible_in_model=False)
    with pytest.raises(session_service.SessionBusyError):
        fork_session_from_node(session_id, node_id)


def test_fork_validates_node_scope_and_session(fork_root) -> None:
    session_id, _turn1, _rest = _source_session(fork_root)
    with pytest.raises(session_service.SessionValidationError):
        fork_session_from_node(session_id, "node-missing")
    node_id = _node_id_for(session_id, "")
    with pytest.raises(session_service.SessionValidationError):
        fork_session_from_node(session_id, node_id or "x", scope="everything")
    with pytest.raises(session_service.SessionNotFoundError):
        fork_session_from_node("session-missing", "node-x")


def test_head_switch_still_works_after_fork_module_lands(fork_root) -> None:
    """Guard: fork does not alter the sibling head-switch contract."""

    session_id, _turn1, rest = _source_session(fork_root)
    branch = rest["branch"]
    head_node = _node_id_for(session_id, branch["user"].event_id)
    detail = switch_session_head(session_id, head_node)
    assert _replay_rows(fork_root, session_id) == [
        ("user", "原始需求"),
        ("assistant", "原始回答"),
        ("user", "重问"),
        ("assistant", "重答"),
    ]
    messages = detail.get("messages") or []
    assert [str(message.get("role") or "") for message in messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_fork_http_route_contract(fork_root, monkeypatch) -> None:
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})
    session_id, turn1, _rest = _source_session(fork_root)
    node_id = _node_id_for(session_id, turn1["answer"].event_id)

    response = client.post(
        f"/api/sessions/{session_id}/fork",
        json={"nodeId": node_id, "scope": FORK_SCOPE_VISIBLE_PATH},
    )
    assert response.status_code == 201
    payload = response.json()
    new_id = str(payload.get("id") or "")
    assert new_id and new_id != session_id

    detail_response = client.get(f"/api/sessions/{new_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert [str(message.get("role") or "") for message in detail_payload.get("messages") or []] == [
        "user",
        "assistant",
    ]
    assert _replay_rows(fork_root, new_id) == [
        ("user", "原始需求"),
        ("assistant", "原始回答"),
    ]

    busy = client.post(
        f"/api/sessions/{session_id}/fork",
        json={"nodeId": node_id},
    )
    assert busy.status_code != 409
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: True)
    conflict = client.post(
        f"/api/sessions/{session_id}/fork",
        json={"nodeId": node_id},
    )
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: False)
    assert conflict.status_code == 409
    assert "分叉" in conflict.json()["detail"] or "fork" in conflict.json()["detail"].lower()

    invalid_scope = client.post(
        f"/api/sessions/{session_id}/fork",
        json={"nodeId": node_id, "scope": "everything"},
    )
    assert invalid_scope.status_code == 422

    missing = client.post(
        "/api/sessions/session-missing/fork",
        json={"nodeId": node_id},
    )
    assert missing.status_code == 404
