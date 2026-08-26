from __future__ import annotations

import pytest

from core.research.workflow.contracts import (
    ContractValidationError,
    PreformalCandidateReviewScopeV1,
    WorkflowDiscussionScopeV1,
    canonical_discussion_scope,
    discussion_scope_hash,
    discussion_scope_key,
    session_scope_key,
)


def _generation() -> WorkflowDiscussionScopeV1:
    return WorkflowDiscussionScopeV1.generation(
        teamId="team-1",
        researchProjectId="project-1",
        workflowRunId="run-1",
        workflowNodeId="hypothesis_design",
        questionId="SCI-096",
    )


def test_generation_scope_has_one_canonical_key_and_hash():
    scope = _generation()
    assert scope.key == (
        "v1|question_generation|team-1|project-1|run-1|hypothesis_design|SCI-096"
    )
    assert discussion_scope_key(scope.to_dict()) == scope.key
    assert discussion_scope_hash(scope.to_dict()) == scope.scope_hash
    assert canonical_discussion_scope(scope.to_dict()) == scope.canonical_json()
    assert "attempt" not in scope.to_dict()
    assert "round" not in scope.to_dict()
    assert "status" not in scope.to_dict()


def test_review_scope_requires_membership_and_new_selection_changes_identity():
    first = WorkflowDiscussionScopeV1.review(
        teamId="team-1",
        researchProjectId="project-1",
        workflowRunId="run-1",
        workflowNodeId="hypothesis_review",
        questionId="SCI-096",
        selectionId="selection-1",
        candidateId="H1",
    )
    first.validate_candidate_membership(["H1", "H2"])
    second = WorkflowDiscussionScopeV1.review(
        teamId="team-1",
        researchProjectId="project-1",
        workflowRunId="run-1",
        workflowNodeId="hypothesis_review",
        questionId="SCI-096",
        selectionId="selection-2",
        candidateId="H1",
    )
    second.validate_candidate_membership(["H1"])
    assert first.key != second.key
    assert first.scope_hash != second.scope_hash
    assert session_scope_key(first, "agent-1") != session_scope_key(
        first, "agent-2"
    )

    with pytest.raises(ContractValidationError, match="selectedCandidateIds"):
        first.validate_candidate_membership(None)
    with pytest.raises(ContractValidationError, match="selected candidate set"):
        first.validate_candidate_membership(["H2"])


def test_scope_parser_rejects_missing_and_unknown_fields():
    scope = _generation().to_dict()
    with pytest.raises(ContractValidationError, match="questionId"):
        WorkflowDiscussionScopeV1.from_mapping({**scope, "questionId": ""})
    with pytest.raises(ContractValidationError, match="unsupported fields"):
        WorkflowDiscussionScopeV1.from_mapping(
            {**scope, "attempt": 2, "roundIndex": 3, "status": "running"}
        )
    with pytest.raises(ContractValidationError, match="unsupported fields"):
        WorkflowDiscussionScopeV1.from_mapping(
            {**scope, "selectionId": "", "candidateId": ""}
        )


def test_preformal_review_scope_has_no_fake_formal_run_and_is_replay_stable():
    scope = PreformalCandidateReviewScopeV1.review(
        teamId="team-1",
        questionId="SCI-003",
        selectionId="selection-1",
        candidateId="H1",
        meetingRoundId="meeting-1",
        roomId="room-1",
    )
    replayed = PreformalCandidateReviewScopeV1.from_mapping(scope.to_dict())

    assert replayed == scope
    assert "workflowRunId" not in scope.to_dict()
    assert "researchProjectId" not in scope.to_dict()
    assert scope.scope_hash == replayed.scope_hash

    with pytest.raises(ContractValidationError, match="meetingRoundId"):
        PreformalCandidateReviewScopeV1.review(
            teamId="team-1",
            questionId="SCI-003",
            selectionId="selection-1",
            candidateId="H1",
            roomId="room-1",
        )


def test_preformal_scope_rejects_formal_or_unknown_fields():
    scope = {
        "version": 1,
        "kind": "preformal_candidate_review",
        "teamId": "team-1",
        "questionId": "SCI-003",
        "selectionId": "selection-1",
        "candidateId": "H1",
        "meetingRoundId": "meeting-1",
        "roomId": "room-1",
    }
    with pytest.raises(ContractValidationError, match="unsupported fields"):
        PreformalCandidateReviewScopeV1.from_mapping({**scope, "workflowRunId": "run-1"})
