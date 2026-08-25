from __future__ import annotations

from core.research.workflow.contracts.discussion_scope import WorkflowDiscussionScopeV1
from core.web.services.team_workflow.active_discussion_anchor import (
    AMBIGUOUS_ACTIVE_CANDIDATE,
    MEETING_MISSING,
    ROOM_CLOSED,
    ROOM_SCOPE_MISMATCH,
    project_active_discussion_anchor,
)


def _scope(candidate_id: str = "") -> WorkflowDiscussionScopeV1:
    fields = {
        "teamId": "research-team",
        "researchProjectId": "challenge-sci-096",
        "workflowRunId": "run-1",
        "workflowNodeId": "hypothesis-review",
        "questionId": "SCI-096",
    }
    if candidate_id:
        return WorkflowDiscussionScopeV1.review(
            **fields,
            selectionId="selection-1",
            candidateId=candidate_id,
        )
    return WorkflowDiscussionScopeV1.generation(**fields)


def _meeting(scope: WorkflowDiscussionScopeV1, meeting_id: str, room_id: str) -> dict:
    return {
        "meetingRoundId": meeting_id,
        "discussionScope": scope.to_dict(),
        "scopeHash": scope.scope_hash,
        "linkedChatRoomId": room_id,
        "status": "open",
    }


def _room(scope: WorkflowDiscussionScopeV1, room_id: str, *, status: str = "active") -> dict:
    return {
        "roomId": room_id,
        "status": status,
        "config": {
            "discussionScope": scope.to_dict(),
            "scopeHash": scope.scope_hash,
        },
    }


def test_projects_one_ready_anchor_from_matching_scoped_room() -> None:
    scope = _scope("h1")
    anchor = project_active_discussion_anchor(
        {"scope": scope.to_dict()},
        [_meeting(scope, "meeting-h1", "room-h1")],
        [_room(scope, "room-h1")],
    )

    assert anchor["status"] == "ready"
    assert anchor["roomId"] == "room-h1"
    assert anchor["meetingRoundId"] == "meeting-h1"
    assert anchor["candidateId"] == "h1"
    assert anchor["returnTo"] == (
        "/teams?teamId=research-team&researchView=workflow&runId=run-1&node=hypothesis-review"
    )
    assert anchor["returnLabel"] == "返回科研流程"
    assert anchor["deepLink"] == (
        "/chat?room=room-h1&returnTo="
        "%2Fteams%3FteamId%3Dresearch-team%26researchView%3Dworkflow%26runId%3Drun-1%26node%3Dhypothesis-review&"
        "returnLabel=%E8%BF%94%E5%9B%9E%E7%A7%91%E7%A0%94%E6%B5%81%E7%A8%8B"
    )
    assert anchor["degradedReason"] == ""


def test_explicit_active_candidate_wins_without_using_array_order() -> None:
    generation_scope = _scope()
    h1 = _scope("h1")
    h2 = _scope("h2")
    meetings = [_meeting(h1, "meeting-h1", "room-h1"), _meeting(h2, "meeting-h2", "room-h2")]
    rooms = [_room(h1, "room-h1"), _room(h2, "room-h2")]

    anchor = project_active_discussion_anchor(
        {
            "scope": generation_scope.to_dict(),
            "activeSelectionId": "selection-1",
            "activeCandidateId": "h2",
        },
        meetings,
        rooms,
    )

    assert anchor["status"] == "ready"
    assert anchor["candidateId"] == "h2"
    assert anchor["roomId"] == "room-h2"


def test_multiple_open_candidates_are_degraded_instead_of_guessing() -> None:
    generation_scope = _scope()
    h1 = _scope("h1")
    h2 = _scope("h2")
    anchor = project_active_discussion_anchor(
        {"scope": generation_scope.to_dict(), "selectionId": "selection-1"},
        [_meeting(h1, "meeting-h1", "room-h1"), _meeting(h2, "meeting-h2", "room-h2")],
        [_room(h1, "room-h1"), _room(h2, "room-h2")],
    )

    assert anchor["status"] == "degraded"
    assert anchor["degradedReason"] == AMBIGUOUS_ACTIVE_CANDIDATE
    assert anchor["deepLink"] == ""


def test_team_linked_room_is_never_a_fallback_anchor() -> None:
    scope = _scope("h1")
    anchor = project_active_discussion_anchor(
        {"scope": scope.to_dict(), "linkedChatRoomId": "legacy-room"},
        [],
        [],
    )

    assert anchor["status"] == "degraded"
    assert anchor["degradedReason"] == MEETING_MISSING
    assert anchor["roomId"] == ""


def test_room_scope_mismatch_and_closed_room_are_fail_closed() -> None:
    scope = _scope("h1")
    other_scope = _scope("h2")
    mismatched = project_active_discussion_anchor(
        {"scope": scope.to_dict()},
        [_meeting(scope, "meeting-h1", "room-h1")],
        [_room(other_scope, "room-h1")],
    )
    assert mismatched["degradedReason"] == ROOM_SCOPE_MISMATCH

    closed = project_active_discussion_anchor(
        {"scope": scope.to_dict()},
        [_meeting(scope, "meeting-h1", "room-h1")],
        [_room(scope, "room-h1", status="closed")],
    )
    assert closed["degradedReason"] == ROOM_CLOSED
