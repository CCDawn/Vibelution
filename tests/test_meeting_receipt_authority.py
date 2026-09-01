from __future__ import annotations

from core.web.services.team_workflow.research_runtime import (
    meeting_receipt_authority,
)


def test_formal_grounded_generation_receipt_covers_candidate_and_revision() -> None:
    authority = {
        "schemaVersion": 1,
        "authorityKind": "workflow_run",
        "teamId": "team-formal",
        "questionId": "SCI-096",
        "workflowRunId": "run-formal",
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "wv-formal",
        "modelPolicySha256": "a" * 64,
    }

    receipt_context = meeting_receipt_authority.build_speaker_receipt_context(
        {"participantId": "participant-1", "agentId": "agent-1"},
        {
            "roundId": "round-1",
            "meetingRoundId": "meeting-1",
            "meetingType": "hypothesis_candidate_generation",
            "candidateAuthority": "formal_grounded_candidate",
            "teamId": "team-formal",
            "questionId": "SCI-096",
            "_modelInvocationReceiptAuthority": authority,
        },
        session_id="session-1",
        turn_identity="chat-room:round-1:participant-1",
        expected_model_route={
            "modelRef": "opencode/deepseek-v4-flash",
            "providerId": "opencode",
            "modelId": "deepseek-v4-flash",
        },
    )

    assert receipt_context is not None
    assert receipt_context["outcomeKinds"] == ["candidate", "revision"]
    assert receipt_context["questionStageBinding"]["questionStage"] == "generation"
