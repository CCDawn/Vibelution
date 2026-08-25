from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from core.web.routes.team_workflows.hypothesis_first_state_models import (
    HypothesisFirstStateV2,
    PhaseState,
)


def _phase(
    *,
    lifecycle: str = "not_started",
    outcome: str = "none",
    actionability: str = "idle",
) -> dict[str, object]:
    return {
        "lifecycle": lifecycle,
        "outcome": outcome,
        "actionability": actionability,
        "attempt": None,
        "updatedAt": None,
        "problems": [],
    }


def _initial_snapshot() -> dict[str, object]:
    idle = _phase()
    return {
        "schemaVersion": 2,
        "contract": "hypothesis-first-state/v2",
        "teamId": "team-1",
        "questionId": "SCI-001",
        "stateVersion": "hf2-action:origin:action-hash",
        "representationVersion": "hf2-repr:origin:representation-hash",
        "computedAt": "2026-08-25T00:00:00Z",
        "scope": {
            "questionInOfficialCatalog": True,
            "catalogId": "challenge-cup-2026",
            "catalogSha256": "sha256:catalog",
        },
        "resetBoundary": {
            "resetId": "origin",
            "resetAt": None,
            "source": "origin",
        },
        "isInitial": True,
        "currentPhase": "generation",
        "overall": _phase(actionability="available"),
        "generation": {
            **_phase(actionability="available"),
            "generationMeetingId": None,
            "candidateCount": 0,
            "candidateIds": [],
        },
        "selection": {
            **idle,
            "selectionId": None,
            "selectedCandidateIds": [],
        },
        "review": {
            **idle,
            "activeRoundIndex": None,
            "aggregate": {
                "total": 0,
                "completed": 0,
                "pending": 0,
                "failed": 0,
                "blocked": 0,
            },
            "candidates": [],
        },
        "collection": {
            **idle,
            "aggregate": {
                "total": 0,
                "completed": 0,
                "pending": 0,
                "failed": 0,
                "blocked": 0,
            },
            "requests": [],
        },
        "convergence": {
            **idle,
            "latestHypothesisRoundId": None,
            "accepted": False,
            "roundIndex": 0,
            "roundBudget": 3,
        },
        "formalRuntime": {
            **idle,
            "runId": None,
            "runVersion": None,
            "runStatus": None,
            "completionKind": None,
            "lineageDisposition": None,
            "isCurrentRevision": False,
            "parentRunId": None,
            "childRunIds": [],
            "currentNodeIds": [],
        },
        "programDelivery": {
            **idle,
            "deliveryStatus": "not_started",
            "deliveryArtifactRef": None,
            "handoffStatus": "not_started",
            "outputRecordId": None,
            "outputRunId": None,
            "humanReviewStatus": "not_started",
            "humanGates": {
                "decisions": {
                    "H1_problem_understanding": "pending",
                    "H2_hypothesis_selection": "pending",
                    "H3_research_plan": "pending",
                    "H4_external_output": "pending",
                },
                "reviewer": None,
                "rationale": None,
                "decidedAt": None,
            },
            "approvedGateCount": 0,
            "requiredGateCount": 4,
        },
        "allowedActions": [
            {
                "kind": "command",
                "actionId": "open-generation",
                "label": "开始生成候选",
                "enabled": True,
                "disabledReason": None,
                "targetPhase": "generation",
                "targetNodeId": "hypothesis-generation",
                "command": "open_generation",
                "payload": {"questionId": "SCI-001"},
                "inputSchemaRef": None,
                "idempotencyKey": "hf2:team-1:SCI-001:open-generation",
                "expectedStateVersion": "hf2-action:origin:action-hash",
                "requiresConfirmation": False,
                "confirmationText": None,
            }
        ],
        "problems": [],
    }


def test_initial_snapshot_is_a_real_generation_state() -> None:
    snapshot = HypothesisFirstStateV2.model_validate(_initial_snapshot())

    assert snapshot.isInitial is True
    assert snapshot.currentPhase == "generation"
    assert snapshot.generation.lifecycle == "not_started"
    assert snapshot.generation.outcome == "none"
    assert snapshot.generation.candidateCount == 0
    assert snapshot.allowedActions[0].kind == "command"
    assert snapshot.allowedActions[0].command == "open_generation"
    assert snapshot.stateVersion != snapshot.representationVersion


@pytest.mark.parametrize(
    ("lifecycle", "outcome"),
    [("completed", "none"), ("running", "succeeded")],
)
def test_lifecycle_outcome_invalid_combinations_are_rejected(
    lifecycle: str,
    outcome: str,
) -> None:
    with pytest.raises(ValidationError):
        PhaseState.model_validate(
            _phase(lifecycle=lifecycle, outcome=outcome, actionability="executing")
        )


def test_v2_models_reject_unknown_fields() -> None:
    payload = _initial_snapshot()
    payload["generationMissing"] = True

    with pytest.raises(ValidationError, match="generationMissing"):
        HypothesisFirstStateV2.model_validate(payload)


def test_review_aggregate_must_match_candidate_states() -> None:
    payload = _initial_snapshot()
    review = payload["review"]
    assert isinstance(review, dict)
    review.update(
        {
            **_phase(lifecycle="waiting_human", actionability="waiting_user"),
            "activeRoundIndex": 1,
            "aggregate": {
                "total": 1,
                "completed": 1,
                "pending": 0,
                "failed": 0,
                "blocked": 0,
            },
            "candidates": [
                {
                    **_phase(
                        lifecycle="waiting_human",
                        actionability="waiting_user",
                    ),
                    "candidateId": "candidate-1",
                    "candidateOrder": 0,
                    "selectionId": "selection-1",
                    "roundIndex": 1,
                    "meetingRoundId": "meeting-1",
                    "discussionAnchor": {
                        "status": "ready",
                        "degradedReason": None,
                        "roomId": "room-1",
                        "meetingRoundId": "meeting-1",
                        "questionId": "SCI-001",
                        "selectionId": "selection-1",
                        "candidateId": "candidate-1",
                        "deepLink": "/chat?room=room-1",
                        "returnTo": "/teams/team-1/research?question=SCI-001",
                        "returnLabel": "返回挑战杯流程",
                    },
                    "discussion": _phase(
                        lifecycle="completed",
                        outcome="succeeded",
                        actionability="terminal",
                    ),
                    "summarization": _phase(
                        lifecycle="completed",
                        outcome="succeeded",
                        actionability="terminal",
                    ),
                    "approval": _phase(
                        lifecycle="waiting_human",
                        actionability="waiting_user",
                    ),
                }
            ],
        }
    )

    with pytest.raises(ValidationError, match="review aggregate"):
        HypothesisFirstStateV2.model_validate(payload)


def test_navigation_action_has_return_route_but_no_cas_fields() -> None:
    payload = _initial_snapshot()
    payload["allowedActions"] = [
        {
            "kind": "navigation",
            "actionId": "open-review-room",
            "label": "进入候选评审室",
            "enabled": True,
            "disabledReason": None,
            "targetPhase": "review",
            "targetNodeId": "candidate-review",
            "navigation": {
                "status": "ready",
                "degradedReason": None,
                "roomId": "room-1",
                "meetingRoundId": "meeting-1",
                "questionId": "SCI-001",
                "selectionId": "selection-1",
                "candidateId": "candidate-1",
                "deepLink": "/chat?room=room-1",
                "returnTo": "/teams/team-1/research?question=SCI-001",
                "returnLabel": "返回挑战杯流程",
            },
        }
    ]

    snapshot = HypothesisFirstStateV2.model_validate(payload)
    action = snapshot.allowedActions[0]

    assert action.kind == "navigation"
    assert action.navigation.returnTo.startswith("/teams/")
    assert not hasattr(action, "expectedStateVersion")

    invalid = deepcopy(payload)
    invalid["allowedActions"][0]["expectedStateVersion"] = payload["stateVersion"]
    with pytest.raises(ValidationError, match="expectedStateVersion"):
        HypothesisFirstStateV2.model_validate(invalid)


def test_program_human_gate_keys_are_exact_and_approved_count_is_recomputed() -> None:
    payload = _initial_snapshot()
    delivery = payload["programDelivery"]
    assert isinstance(delivery, dict)
    delivery["humanGates"]["decisions"]["H1"] = "approved"

    with pytest.raises(ValidationError):
        HypothesisFirstStateV2.model_validate(payload)
