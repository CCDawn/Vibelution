from __future__ import annotations

import pytest

from core.research.workflow.contracts.discussion_scope import (
    PreformalCandidateReviewScopeV1,
    WorkflowDiscussionScopeV1,
)
from core.web.services.team_workflow.active_discussion_anchor import (
    AMBIGUOUS_ACTIVE_CANDIDATE,
    MEETING_MISSING,
    ROOM_CLOSED,
    ROOM_SCOPE_MISMATCH,
    project_active_discussion_anchor,
)


def _preformal_scope(
    *,
    question_id: str = "SCI-003",
    selection_id: str = "selection-1",
    candidate_id: str = "h1",
    meeting_id: str = "meeting-h1",
    room_id: str = "room-h1",
) -> PreformalCandidateReviewScopeV1:
    return PreformalCandidateReviewScopeV1.review(
        teamId="research-team",
        questionId=question_id,
        selectionId=selection_id,
        candidateId=candidate_id,
        meetingRoundId=meeting_id,
        roomId=room_id,
    )


def _preformal_legacy_meeting(scope: PreformalCandidateReviewScopeV1) -> dict:
    return {
        "meetingRoundId": scope.meetingRoundId,
        "meetingType": "hypothesis_review",
        "question": scope.questionId,
        "status": "open",
        "linkedChatRoomId": scope.roomId,
        "inputArtifactRefs": [f"hypothesis_selection:{scope.selectionId}"],
        "discussionItemRefs": [f"hypothesis_candidate:{scope.candidateId}"],
    }


def _preformal_legacy_room(scope: PreformalCandidateReviewScopeV1) -> dict:
    return {
        "roomId": scope.roomId,
        "status": "ready",
        "config": {
            "source": "hypothesis_first_candidate_review.v1",
            "teamId": scope.teamId,
            "meetingRoundId": scope.meetingRoundId,
            "selectionId": scope.selectionId,
            "questionId": scope.questionId,
            "candidateId": scope.candidateId,
        },
    }


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


def test_preformal_chain_binding_projects_legacy_meeting_and_room() -> None:
    scope = _preformal_scope()
    room = _preformal_legacy_room(scope)
    room["config"]["scopeHash"] = "legacy-room-hash-that-is-not-a-v1-scope-hash"
    anchor = project_active_discussion_anchor(
        {"preformalBinding": scope.to_dict()},
        [_preformal_legacy_meeting(scope)],
        [room],
    )

    assert anchor["status"] == "ready"
    assert anchor["scope"] == scope.to_dict()
    assert anchor["scopeHash"] == scope.scope_hash
    assert anchor["roomId"] == scope.roomId
    assert anchor["meetingRoundId"] == scope.meetingRoundId
    assert "runId=" not in anchor["returnTo"]
    assert "questionId=SCI-003" in anchor["returnTo"]


def test_explicit_preformal_scope_missing_field_is_not_repaired_from_outer_data() -> None:
    scope = _preformal_scope()
    damaged_scope = dict(scope.to_dict())
    damaged_scope.pop("candidateId")
    anchor = project_active_discussion_anchor(
        {
            "preformalBinding": damaged_scope,
            "candidateId": scope.candidateId,
            "meetingRoundId": scope.meetingRoundId,
            "roomId": scope.roomId,
        },
        [_preformal_legacy_meeting(scope)],
        [_preformal_legacy_room(scope)],
    )

    assert anchor["status"] == "degraded"
    assert anchor["deepLink"] == ""


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selectionId", "selection-other"),
        ("candidateId", "h2"),
        ("meetingRoundId", "meeting-other"),
        ("roomId", "room-other"),
    ],
)
def test_preformal_binding_mismatch_never_promotes_sibling(
    field: str, value: str
) -> None:
    scope = _preformal_scope()
    binding = dict(scope.to_dict())
    binding[field] = value
    anchor = project_active_discussion_anchor(
        {"preformalBinding": binding},
        [_preformal_legacy_meeting(scope)],
        [_preformal_legacy_room(scope)],
    )

    assert anchor["status"] == "degraded"
    assert anchor["deepLink"] == ""


def test_preformal_room_scope_hash_and_full_scope_are_cross_checked() -> None:
    scope = _preformal_scope()
    room = _preformal_legacy_room(scope)
    room["config"].update(
        {
            "scopeAuthority": "preformal_candidate_review_scope.v1",
            "discussionScope": scope.to_dict(),
            "discussionScopeHash": scope.scope_hash,
            "scopeHash": scope.scope_hash,
        }
    )
    meeting = _preformal_legacy_meeting(scope)
    meeting.update(
        {
            "discussionScope": scope.to_dict(),
            "discussionScopeHash": scope.scope_hash,
        }
    )
    anchor = project_active_discussion_anchor(
        {"preformalBinding": scope.to_dict()}, [meeting], [room]
    )
    assert anchor["status"] == "ready"

    room["config"]["scopeHash"] = "0" * 64
    mismatched = project_active_discussion_anchor(
        {"preformalBinding": scope.to_dict()}, [meeting], [room]
    )
    assert mismatched["status"] == "degraded"
