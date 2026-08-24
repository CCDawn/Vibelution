from __future__ import annotations

from typing import Any

import pytest

from core.research.workflow.contracts.discussion_scope import (
    WorkflowDiscussionScopeV1,
    session_scope_key,
)
from core.web.services.team_workflow.discussion_room_runtime import (
    DiscussionRoomBindingError,
    resolve_scoped_discussion_room,
)


class _FakeRooms:
    def __init__(self) -> None:
        self.rooms: dict[str, dict[str, Any]] = {}
        self.created = 0

    def list_chat_rooms(self) -> list[dict[str, Any]]:
        return list(self.rooms.values())

    def get_chat_room_detail(self, room_id: str) -> dict[str, Any] | None:
        return self.rooms.get(room_id)

    def create_chat_room(self, **payload: Any) -> dict[str, Any]:
        self.created += 1
        participants = [
            {"agentId": f"agent-{index}", "sessionId": session_id}
            for index, session_id in enumerate(payload["participant_session_ids"], start=1)
        ]
        room = {
            "roomId": payload["room_id"],
            "config": payload["config"],
            "participants": participants,
        }
        self.rooms[room["roomId"]] = room
        return room


def _scope(candidate: str = "H1") -> WorkflowDiscussionScopeV1:
    return WorkflowDiscussionScopeV1.review(
        teamId="research-team",
        researchProjectId="challenge-sci-096",
        workflowRunId="run-1",
        workflowNodeId="hypothesis_design",
        questionId="SCI-096",
        selectionId="selection-1",
        candidateId=candidate,
    )


def _bindings(scope: WorkflowDiscussionScopeV1) -> list[dict[str, Any]]:
    return [
        {
            "agentId": f"agent-{index}",
            "sessionId": f"session-{scope.candidateId}-{index}",
            "discussionScope": scope.to_dict(),
            "discussionScopeHash": scope.scope_hash,
            "discussionSessionScopeKey": session_scope_key(scope, f"agent-{index}"),
        }
        for index in range(1, 3)
    ]


def test_scoped_room_replay_reuses_exact_room_and_sessions() -> None:
    port = _FakeRooms()
    scope = _scope()

    first = resolve_scoped_discussion_room(scope, _bindings(scope), port=port)
    second = resolve_scoped_discussion_room(scope, _bindings(scope), port=port)

    assert first["roomId"] == second["roomId"]
    assert first["status"] == "created"
    assert second["status"] == "reused"
    assert port.created == 1


def test_new_candidate_scope_creates_another_room() -> None:
    port = _FakeRooms()
    first_scope = _scope("H1")
    second_scope = _scope("H2")

    first = resolve_scoped_discussion_room(first_scope, _bindings(first_scope), port=port)
    second = resolve_scoped_discussion_room(second_scope, _bindings(second_scope), port=port)

    assert first["roomId"] != second["roomId"]
    assert port.created == 2


def test_scoped_room_rejects_participant_from_sibling_scope() -> None:
    port = _FakeRooms()
    scope = _scope("H1")
    sibling = _scope("H2")

    with pytest.raises(DiscussionRoomBindingError, match="different discussion scope"):
        resolve_scoped_discussion_room(scope, _bindings(sibling), port=port)
