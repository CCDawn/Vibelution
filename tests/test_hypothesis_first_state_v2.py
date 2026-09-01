from __future__ import annotations

import subprocess
import sys
import time
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, Request, Response
from pydantic import ValidationError

from core.web.routes.team_workflows import hypothesis_first as hypothesis_first_routes
from core.web.routes.team_workflows.hypothesis_first_state_models import (
    CollectionChildRunPayload,
    HypothesisFirstCommandRequest,
    HypothesisFirstStateV2,
    PhaseState,
)
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_state_v2 as hf_state_v2_module,
)
from core.web.services.team_workflow.research_runtime.hypothesis_first_state_v2 import (
    finalize_state_versions,
    project_state_from_records,
)
from tests.helpers.managed_processes import managed_processes

_REAL_CLAIM_BELIEF_GATE_VERDICT = hf_state_v2_module._claim_belief_gate_verdict


@pytest.fixture(autouse=True)
def _allow_claim_belief_gate(monkeypatch: pytest.MonkeyPatch):
    """Default v2 projections to a gate-allowed context.

    The claim belief hard gate itself is covered end-to-end by the claim-gate
    and materialization suites; these unit tests stub the convergence seam so
    they keep testing action/phase projection.  The consistency tests below
    re-bind the real (or a blocked) verdict explicitly.
    """
    monkeypatch.setattr(
        hf_state_v2_module,
        "_claim_belief_gate_verdict",
        lambda _team_id, _question_id, candidate_id: {
            "candidateId": candidate_id,
            "status": "allowed",
            "reason": "",
            "claims": [],
            "blockedClaims": [],
        },
    )


def _blocked_claim_belief_gate(monkeypatch: pytest.MonkeyPatch, reason: str) -> None:
    monkeypatch.setattr(
        hf_state_v2_module,
        "_claim_belief_gate_verdict",
        lambda _team_id, _question_id, candidate_id: {
            "candidateId": candidate_id,
            "status": "blocked",
            "reason": reason,
            "claims": [],
            "blockedClaims": [
                {"claimId": "claim-1", "beliefState": "contradicted"}
            ],
        },
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
        "awaitingHumanCount": 0,
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
        "direction1ASubmissionReady": False,
        "direction1aSubmission": {
            "source": "not_materialized",
            "submissionReady": False,
            "g1RequiredUnmet": [
                "official_core_hypothesis_novelty_coherence",
                "official_plan_executability_six_facets",
                "official_two_round_revision",
            ],
            "notYetEvidenced": [
                "official_core_hypothesis_novelty_coherence",
                "official_plan_executability_six_facets",
                "official_two_round_revision",
                "official_scale_out_125_questions",
                "official_technical_depth_multimodal",
                "official_application_evidence",
                "official_submission_materials",
                "official_phase2_experiments",
            ],
            "items": [],
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


def test_top_level_completed_requires_all_h1_h4_gates_approved() -> None:
    payload = _initial_snapshot()
    payload["isInitial"] = False
    payload["currentPhase"] = "completed"
    payload["overall"] = _phase(
        lifecycle="completed",
        outcome="succeeded",
        actionability="terminal",
    )
    payload["programDelivery"].update(
        {
            **_phase(
                lifecycle="completed",
                outcome="succeeded",
                actionability="terminal",
            ),
            "deliveryStatus": "succeeded",
            "handoffStatus": "registered",
            "humanReviewStatus": "approved",
        }
    )

    with pytest.raises(ValidationError, match="all H1-H4 gates approved"):
        HypothesisFirstStateV2.model_validate(payload)


def test_record_projection_distinguishes_initial_from_empty_generation() -> None:
    initial = HypothesisFirstStateV2.model_validate(project_state_from_records(
        team_id="team-1",
        question_id="SCI-001",
        reset_boundary=None,
        chain_records=[],
        selection_records=[],
        meeting_records=[],
        digest_records=[],
        decision_records=[],
        hypothesis_round_records=[],
    ))
    empty = HypothesisFirstStateV2.model_validate(project_state_from_records(
        team_id="team-1",
        question_id="SCI-001",
        reset_boundary=None,
        chain_records=[],
        selection_records=[],
        meeting_records=[
            {
                "meetingRoundId": "generation-1",
                "meetingType": "hypothesis_candidate_generation",
                "question": "SCI-001",
                "status": "closed",
                "createdAt": "2026-08-25T00:00:00Z",
                "updatedAt": "2026-08-25T00:05:00Z",
            }
        ],
        digest_records=[],
        decision_records=[],
        hypothesis_round_records=[],
    ))

    assert initial.isInitial is True
    assert initial.generation.lifecycle == "not_started"
    assert empty.isInitial is False
    assert empty.generation.lifecycle == "completed"
    assert empty.generation.outcome == "empty"
    assert empty.stateVersion != initial.stateVersion


def test_generation_attempt_projects_queued_without_generation_missing() -> None:
    queued = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "generation_attempt",
                    "attemptId": "attempt-1",
                    "attemptNumber": 1,
                    "questionId": "SCI-001",
                    "meetingRoundId": "meeting-1",
                    "lifecycle": "queued",
                    "outcome": "none",
                    "queuedAt": "2026-08-25T00:00:00Z",
                    "startedAt": "",
                    "heartbeatAt": "",
                    "finishedAt": "",
                    "supersedesAttemptId": "",
                    "updatedAt": "2026-08-25T00:00:00Z",
                }
            ],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
        )
    )

    assert queued.isInitial is False
    assert queued.currentPhase == "generation"
    assert queued.generation.lifecycle == "queued"
    assert queued.generation.actionability == "waiting_system"
    assert queued.generation.attempt is not None
    assert queued.generation.attempt.attemptId == "attempt-1"
    assert all(problem.code != "generation_missing" for problem in queued.problems)


def test_same_round_index_keeps_each_candidate_in_review_aggregate() -> None:
    state = HypothesisFirstStateV2.model_validate(project_state_from_records(
        team_id="team-1",
        question_id="SCI-001",
        reset_boundary=None,
        chain_records=[
            {
                "recordKind": "hypothesis_candidate",
                "candidateId": candidate_id,
                "questionId": "SCI-001",
                "createdAt": "2026-08-25T00:00:00Z",
            }
            for candidate_id in ("candidate-a", "candidate-b")
        ]
        + [
            {
                "recordKind": "review_round_link",
                "linkId": f"link-{candidate_id}",
                "questionId": "SCI-001",
                "selectionId": "selection-1",
                "candidateId": candidate_id,
                "candidateOrder": order,
                "roundIndex": 1,
                "meetingRoundId": f"meeting-{candidate_id}",
                "createdAt": "2026-08-25T00:02:00Z",
            }
            for order, candidate_id in enumerate(("candidate-a", "candidate-b"))
        ],
        selection_records=[
            {
                "selectionId": "selection-1",
                "questionId": "SCI-001",
                "selectedCandidateIds": ["candidate-a", "candidate-b"],
                "createdAt": "2026-08-25T00:01:00Z",
            }
        ],
        meeting_records=[
            {
                "meetingRoundId": f"meeting-{candidate_id}",
                "meetingType": "hypothesis_review",
                "question": "SCI-001",
                "selectionId": "selection-1",
                "status": "awaiting_approval",
                "linkedChatRoomId": f"room-{candidate_id}",
                "createdAt": "2026-08-25T00:03:00Z",
            }
            for candidate_id in ("candidate-a", "candidate-b")
        ],
        digest_records=[],
        decision_records=[],
        hypothesis_round_records=[],
        return_to="/teams/team-1/research?question=SCI-001",
    ))

    assert state.currentPhase == "review"
    assert state.review.aggregate.total == 2
    assert state.review.aggregate.pending == 2
    assert state.awaitingHumanCount == 2
    assert [item.candidateId for item in state.review.candidates] == [
        "candidate-a",
        "candidate-b",
    ]


def test_succeeded_formal_run_with_missing_delivery_stays_program_delivery_blocked() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            formal_runs=[
                {
                    "runId": "run-1",
                    "teamId": "team-1",
                    "questionId": "SCI-001",
                    "status": "succeeded",
                    "runVersion": 7,
                    "completionKind": "completed",
                    "parentRunId": None,
                    "createdAt": "2026-08-25T00:00:00Z",
                    "updatedAt": "2026-08-25T01:00:00Z",
                }
            ],
            formal_snapshots={"run-1": {"deliveryStatus": None}},
        )
    )

    assert state.currentPhase == "program_delivery"
    assert state.formalRuntime.lifecycle == "completed"
    assert state.formalRuntime.outcome == "succeeded"
    assert state.formalRuntime.runStatus == "succeeded"
    assert state.programDelivery.actionability == "blocked"
    assert any(
        problem.code == "formal_result_package_missing" for problem in state.problems
    )


def test_branched_parent_preserves_succeeded_authority() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            formal_runs=[
                {
                    "runId": "run-parent",
                    "teamId": "team-1",
                    "questionId": "SCI-001",
                    "status": "succeeded",
                    "runVersion": 8,
                    "completionKind": "branched_revision",
                    "parentRunId": None,
                    "childRunIds": ["run-child"],
                    "createdAt": "2026-08-25T00:00:00Z",
                    "updatedAt": "2026-08-25T01:00:00Z",
                }
            ],
        )
    )

    assert state.formalRuntime.lifecycle == "completed"
    assert state.formalRuntime.outcome == "succeeded"
    assert state.formalRuntime.lineageDisposition == "branched_parent"
    assert state.formalRuntime.isCurrentRevision is False
    assert state.formalRuntime.childRunIds == ["run-child"]


def test_conflicting_current_formal_revisions_block_downstream_delivery_actions() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            formal_runs=[
                {
                    "runId": run_id,
                    "teamId": "team-1",
                    "questionId": "SCI-001",
                    "status": "succeeded",
                    "runVersion": 2,
                    "updatedAt": updated_at,
                }
                for run_id, updated_at in (
                    ("run-a", "2026-08-25T00:00:00Z"),
                    ("run-b", "2026-08-25T01:00:00Z"),
                )
            ],
            formal_snapshots={
                "run-a": {"deliveryStatus": "succeeded"},
                "run-b": {"deliveryStatus": "succeeded"},
            },
            program_output={
                "record": {
                    "recordId": "output-b",
                    "runId": "run-b",
                    "validation": {
                        "schemaValidation": "passed",
                        "citationValidation": "passed",
                        "semanticValidation": "passed",
                        "officialModelCall": True,
                    },
                    "humanGates": {"decisions": {}},
                }
            },
        )
    )

    assert state.currentPhase == "formal_runtime"
    assert state.formalRuntime.lineageDisposition == "conflicted"
    assert state.formalRuntime.actionability == "blocked"
    assert any(problem.code == "formal_run_lineage_conflict" for problem in state.problems)
    archive_actions = [
        action
        for action in state.allowedActions
        if action.kind == "command" and action.command == "archive_run"
    ]
    assert {action.payload.runId for action in archive_actions} == {"run-a", "run-b"}
    assert all(action.requiresConfirmation for action in archive_actions)


@pytest.mark.parametrize("run_status", ["failed", "cancelled"])
def test_terminal_formal_run_offers_archive_instead_of_reconcile(
    run_status: str,
) -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[{
                "roundId": "round-accepted",
                "question": "SCI-001",
                "roundIndex": 1,
                "status": "closed",
                "metaReview": {
                    "accepted": True,
                    "recommendationCandidateId": "candidate-confirmed",
                },
            }],
            formal_runs=[{
                "runId": "run-terminal",
                "teamId": "team-1",
                "questionId": "SCI-001",
                "status": run_status,
                "runVersion": 3,
            }],
        )
    )

    commands = [
        action.command for action in state.allowedActions if action.kind == "command"
    ]
    assert commands == ["archive_run"]


@pytest.mark.parametrize("run_status", ["blocked", "running"])
def test_formal_run_projects_available_retry_node_offer(
    run_status: str,
) -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[{
                "roundId": "round-accepted",
                "question": "SCI-001",
                "roundIndex": 1,
                "status": "closed",
                "metaReview": {
                    "accepted": True,
                    "recommendationCandidateId": "candidate-confirmed",
                },
            }],
            formal_runs=[{
                "runId": "run-retry",
                "teamId": "team-1",
                "questionId": "SCI-001",
                "status": run_status,
                "runVersion": 7,
                "activeNodeId": "source_extraction",
            }],
            formal_snapshots={
                "run-retry": {
                    "activeNodeIds": ["source_extraction"],
                    "commandOffers": [{
                        "command": "retry_node",
                        "nodeId": "source_extraction",
                        "available": True,
                        "label": "重试 资料提炼",
                        "reasonCode": "retry_available",
                        "idempotencyKey": "offer:retry",
                        "expectedRunVersion": 7,
                        "payload": {"retryKind": "same_node"},
                    }],
                }
            },
        )
    )

    actions = [
        action for action in state.allowedActions if action.kind == "command"
    ]
    expected = (
        ["retry_formal_node", "cancel_run"]
        if run_status == "blocked"
        else ["retry_formal_node"]
    )
    assert [action.command for action in actions] == expected
    assert actions[0].targetNodeId == "source_extraction"
    assert actions[0].idempotencyKey == "offer:retry"
    assert actions[0].payload.runId == "run-retry"
    assert actions[0].payload.nodeId == "source_extraction"
    assert actions[0].model_dump(mode="json")["payload"] == {
        "runId": "run-retry",
        "nodeId": "source_extraction",
    }


@pytest.mark.parametrize("run_status", ["blocked", "failed"])
def test_ordinary_formal_failure_does_not_project_reconcile_action(
    run_status: str,
) -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[{
                "roundId": "round-accepted",
                "question": "SCI-001",
                "roundIndex": 1,
                "status": "closed",
                "metaReview": {
                    "accepted": True,
                    "recommendationCandidateId": "candidate-confirmed",
                },
            }],
            formal_runs=[{
                "runId": "run-no-retry",
                "teamId": "team-1",
                "questionId": "SCI-001",
                "status": run_status,
                "runVersion": 7,
            }],
            formal_snapshots={"run-no-retry": {"commandOffers": []}},
        )
    )

    commands = [
        action.command
        for action in state.allowedActions
        if action.kind == "command"
    ]
    assert "reconcile_formal_run" not in commands
    if run_status == "failed":
        assert commands == ["archive_run"]
    else:
        # blocked keeps the confirmed retirement offer even without retries
        assert commands == ["cancel_run"]


_RECONCILE_OFFER = {
    "command": "reconcile_run",
    "nodeId": None,
    "available": True,
    "label": "对账运行",
    "reasonCode": "ready",
    "idempotencyKey": "offer:reconcile:v7",
    "expectedRunVersion": 7,
    "payload": {},
}


def _retry_offer(node_id: str = "source_extraction") -> dict[str, Any]:
    return {
        "command": "retry_node",
        "nodeId": node_id,
        "available": True,
        "label": f"重试 {node_id}",
        "reasonCode": "retry_available",
        "idempotencyKey": f"offer:retry:{node_id}:v7",
        "expectedRunVersion": 7,
        "payload": {"retryKind": "same_node"},
    }


def _project_formal_commands(
    *,
    run_id: str,
    run_status: str,
    command_offers: list[dict[str, Any]],
) -> list[Any]:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[{
                "roundId": "round-accepted",
                "question": "SCI-001",
                "roundIndex": 1,
                "status": "closed",
                "metaReview": {
                    "accepted": True,
                    "recommendationCandidateId": "candidate-confirmed",
                },
            }],
            formal_runs=[{
                "runId": run_id,
                "teamId": "team-1",
                "questionId": "SCI-001",
                "status": run_status,
                "runVersion": 7,
            }],
            formal_snapshots={
                run_id: {"commandOffers": [dict(offer) for offer in command_offers]}
            },
        )
    )
    return [
        action for action in state.allowedActions if action.kind == "command"
    ]


def test_blocked_formal_run_without_retry_projects_reconcile_offer() -> None:
    """生产 run-d02722658d8b 形态：blocked 且无可用节点 retry。

    ledger 的 reconcile offer 必须原样透传成 V2 动作，操作员才有恢复入口；
    blocked 运行同时保留确认式 cancel 退役入口（冻结路由永久不可达时用）。
    """
    actions = _project_formal_commands(
        run_id="run-blocked-reconcile",
        run_status="blocked",
        command_offers=[_RECONCILE_OFFER],
    )

    assert [action.command for action in actions] == [
        "reconcile_formal_run",
        "cancel_run",
    ]
    reconcile = actions[0]
    assert reconcile.actionId == "reconcile-formal-run:run-blocked-reconcile"
    assert reconcile.idempotencyKey == "offer:reconcile:v7"
    assert reconcile.payload.runId == "run-blocked-reconcile"
    assert reconcile.enabled is True
    cancel = actions[1]
    assert cancel.payload.runId == "run-blocked-reconcile"
    assert cancel.requiresConfirmation is True


def test_blocked_formal_run_keeps_reconcile_alongside_retry_actions() -> None:
    """SCI-003 回归：blocked + 有节点 retry 时不得再丢弃 reconcile offer。"""
    actions = _project_formal_commands(
        run_id="run-blocked-mixed",
        run_status="blocked",
        command_offers=[_retry_offer(), _RECONCILE_OFFER],
    )

    assert [action.command for action in actions] == [
        "retry_formal_node",
        "reconcile_formal_run",
        "cancel_run",
    ]
    retry, reconcile, cancel = actions
    assert retry.idempotencyKey == "offer:retry:source_extraction:v7"
    assert reconcile.idempotencyKey == "offer:reconcile:v7"
    assert cancel.actionId == "cancel-formal-run:run-blocked-mixed"
    assert cancel.requiresConfirmation is True


def test_reconciliation_required_with_retry_co_projects_both_recovery_paths() -> None:
    """reconciliation_required 且 retry 可用时，两个授权动作并存且 retry 优先。"""
    actions = _project_formal_commands(
        run_id="run-recon-mixed",
        run_status="reconciliation_required",
        command_offers=[_retry_offer(), _RECONCILE_OFFER],
    )

    assert [action.command for action in actions] == [
        "retry_formal_node",
        "reconcile_formal_run",
    ]


@pytest.mark.parametrize("run_status", ["running", "waiting_human"])
def test_active_formal_runs_do_not_project_reconcile_action(
    run_status: str,
) -> None:
    """ledger 对非 blocked/reconciliation_required 不授权 reconcile，不误出。"""
    actions = _project_formal_commands(
        run_id=f"run-active-{run_status}",
        run_status=run_status,
        command_offers=[
            _retry_offer(),
            {**_RECONCILE_OFFER, "available": False, "reasonCode": "reconcile_not_needed", "idempotencyKey": ""},
        ],
    )

    assert [action.command for action in actions] == ["retry_formal_node"]
    assert all(action.command != "reconcile_formal_run" for action in actions)


@pytest.mark.parametrize("run_status", ["succeeded"])
def test_succeeded_formal_run_does_not_project_reconcile_action(
    run_status: str,
) -> None:
    commands = [
        action.command
        for action in _project_formal_commands(
            run_id="run-done",
            run_status=run_status,
            command_offers=[
                {**_RECONCILE_OFFER, "available": False, "reasonCode": "reconcile_not_needed"}
            ],
        )
        if action.kind == "command"
    ]
    assert "reconcile_formal_run" not in commands


def test_reconciliation_required_formal_run_keeps_reconcile_action() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[{
                "roundId": "round-accepted",
                "question": "SCI-001",
                "roundIndex": 1,
                "status": "closed",
                "metaReview": {
                    "accepted": True,
                    "recommendationCandidateId": "candidate-confirmed",
                },
            }],
            formal_runs=[{
                "runId": "run-reconcile",
                "teamId": "team-1",
                "questionId": "SCI-001",
                "status": "reconciliation_required",
                "runVersion": 7,
            }],
            formal_snapshots={"run-reconcile": {"commandOffers": []}},
        )
    )

    commands = [
        action.command
        for action in state.allowedActions
        if action.kind == "command"
    ]
    assert commands == ["reconcile_formal_run"]


def test_created_formal_run_offers_cancel_before_archive() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[{
                "roundId": "round-accepted",
                "question": "SCI-001",
                "roundIndex": 1,
                "status": "closed",
                "metaReview": {
                    "accepted": True,
                    "recommendationCandidateId": "candidate-confirmed",
                },
            }],
            formal_runs=[{
                "runId": "run-created",
                "teamId": "team-1",
                "questionId": "SCI-001",
                "status": "created",
                "runVersion": 1,
            }],
        )
    )

    actions = [
        action for action in state.allowedActions if action.kind == "command"
    ]
    assert [action.command for action in actions] == ["cancel_run"]
    assert actions[0].payload.runId == "run-created"
    assert actions[0].requiresConfirmation is True


def test_archived_formal_run_no_longer_suppresses_rebuild() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[{
                "roundId": "round-accepted",
                "question": "SCI-001",
                "roundIndex": 1,
                "status": "closed",
                "metaReview": {
                    "accepted": True,
                    "recommendationCandidateId": "candidate-confirmed",
                },
            }],
            formal_runs=[{
                "runId": "run-archived",
                "teamId": "team-1",
                "questionId": "SCI-001",
                "status": "archived",
                "runVersion": 4,
            }],
        )
    )

    assert state.formalRuntime.runId is None
    create_actions = [
        action
        for action in state.allowedActions
        if action.kind == "command" and action.command == "create_formal_run"
    ]
    assert len(create_actions) == 1
    # 归档后重建必须换 create 幂等键：同一 round 的旧键已绑定被退役 run 的
    # create fingerprint，环境变化后的重建会撞 run_id。
    assert create_actions[0].actionId == "create-formal-run-v2:round-accepted:1"


def test_converged_chain_does_not_offer_duplicate_formal_run() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[
                {
                    "roundId": "round-1",
                    "question": "SCI-001",
                    "roundIndex": 1,
                    "status": "closed",
                    "metaReview": {"accepted": True},
                    "createdAt": "2026-08-25T00:00:00Z",
                }
            ],
            formal_runs=[
                {
                    "runId": "run-1",
                    "teamId": "team-1",
                    "questionId": "SCI-001",
                    "status": "running",
                    "runVersion": 1,
                    "createdAt": "2026-08-25T00:01:00Z",
                }
            ],
        )
    )

    assert state.currentPhase == "formal_runtime"
    assert state.convergence.lifecycle == "completed"
    assert state.convergence.outcome == "succeeded"
    assert not any(
        action.kind == "command" and action.command == "create_formal_run"
        for action in state.allowedActions
    )


def test_legacy_running_formal_run_does_not_hide_unstarted_hypothesis_generation() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            formal_runs=[
                {
                    "runId": "legacy-container-run",
                    "teamId": "team-1",
                    "questionId": "SCI-001",
                    "status": "running",
                    "runVersion": 1,
                    "activeNodeId": "problem_understanding",
                    "createdAt": "2026-08-25T00:01:00Z",
                }
            ],
        )
    )

    assert state.currentPhase == "generation"
    assert state.formalRuntime.runId == "legacy-container-run"
    assert any(
        action.kind == "command" and action.command == "open_generation"
        for action in state.allowedActions
    )


@pytest.mark.parametrize(
    ("round_index", "expected_command"),
    [(3, "open_next_review"), (5, "human_adjudication")],
)
def test_unaccepted_closed_round_uses_budget_before_human_adjudication(
    round_index: int,
    expected_command: str,
) -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "hypothesis_candidate",
                    "candidateId": "candidate-1",
                    "questionId": "SCI-001",
                },
                {
                    "recordKind": "review_round_link",
                    "linkId": f"link-{round_index}",
                    "selectionId": "selection-1",
                    "candidateId": "candidate-1",
                    "candidateOrder": 0,
                    "roundIndex": round_index,
                    "roundBudget": 3,
                    "meetingRoundId": f"review-{round_index}",
                    "questionId": "SCI-001",
                },
            ],
            selection_records=[
                {
                    "selectionId": "selection-1",
                    "questionId": "SCI-001",
                    "selectedCandidateIds": ["candidate-1"],
                }
            ],
            meeting_records=[
                {
                    "meetingRoundId": f"review-{round_index}",
                    "meetingType": "hypothesis_review",
                    "question": "SCI-001",
                    "status": "closed",
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[
                {
                    "roundId": f"round-{round_index}",
                    "question": "SCI-001",
                    "roundIndex": round_index,
                    "status": "closed",
                    "metaReview": {"accepted": False},
                    "createdAt": "2026-08-25T00:00:00Z",
                }
            ],
        )
    )

    commands = {
        action.command: action
        for action in state.allowedActions
        if action.kind == "command"
    }
    assert state.currentPhase == "convergence"
    assert expected_command in commands
    assert ({"open_next_review", "human_adjudication"} - {expected_command}).isdisjoint(
        commands
    )
    if expected_command == "open_next_review":
        action = commands[expected_command]
        assert action.payload.previousMeetingRoundId == f"review-{round_index}"
        assert action.payload.roundBudget == 5
        assert state.convergence.lifecycle == "waiting_human"
        assert state.convergence.outcome == "none"
    else:
        assert state.convergence.lifecycle == "completed"
        assert state.convergence.outcome == "exhausted"


def test_rejected_human_adjudication_is_terminal_and_not_reoffered() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "hypothesis_candidate",
                    "candidateId": "candidate-1",
                    "questionId": "SCI-001",
                },
                {
                    "recordKind": "review_round_link",
                    "linkId": "link-3",
                    "selectionId": "selection-1",
                    "candidateId": "candidate-1",
                    "candidateOrder": 0,
                    "roundIndex": 3,
                    "roundBudget": 3,
                    "meetingRoundId": "review-3",
                    "questionId": "SCI-001",
                },
                {
                    "recordKind": "human_adjudication",
                    "adjudicationId": "adjudication-1",
                    "hypothesisRoundId": "round-3",
                    "decision": "rejected",
                    "questionId": "SCI-001",
                    "updatedAt": "2026-08-25T00:05:00Z",
                },
            ],
            selection_records=[
                {
                    "selectionId": "selection-1",
                    "questionId": "SCI-001",
                    "selectedCandidateIds": ["candidate-1"],
                }
            ],
            meeting_records=[
                {
                    "meetingRoundId": "review-3",
                    "meetingType": "hypothesis_review",
                    "question": "SCI-001",
                    "status": "closed",
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[
                {
                    "roundId": "round-3",
                    "question": "SCI-001",
                    "roundIndex": 3,
                    "status": "closed",
                    "metaReview": {"accepted": False},
                    "createdAt": "2026-08-25T00:00:00Z",
                }
            ],
        )
    )

    assert state.currentPhase == "convergence"
    assert state.convergence.lifecycle == "completed"
    assert state.convergence.outcome == "rejected"
    assert state.convergence.actionability == "terminal"
    assert not any(action.kind == "command" for action in state.allowedActions)


# ---------------------------------------------------------------------------
# Convergence dual predicate: budget-exhausted rounds with new evidence
# requests must reach the human adjudication exit and converge after an
# accepted adjudication (mirrors the v1 chain_state clauses exactly).
# ---------------------------------------------------------------------------


def _convergence_round_record(
    round_index: int,
    *,
    accepted: bool = True,
) -> dict[str, object]:
    return {
        "roundId": f"round-{round_index}",
        "question": "SCI-001",
        "roundIndex": round_index,
        "status": "closed",
        "metaReview": {
            "accepted": accepted,
            "recommendationCandidateId": "candidate-1",
        },
        "meetingRefs": [{"kind": "meeting_round", "id": f"review-{round_index}"}],
        "createdAt": "2026-08-25T00:00:00Z",
    }


def _convergence_link_record(round_index: int) -> dict[str, object]:
    return {
        "recordKind": "review_round_link",
        "linkId": f"link-{round_index}",
        "selectionId": "selection-1",
        "candidateId": "candidate-1",
        "candidateOrder": 0,
        "roundIndex": round_index,
        "roundBudget": 3,
        "meetingRoundId": f"review-{round_index}",
        "questionId": "SCI-001",
    }


def _convergence_request_record(
    request_id: str,
    round_index: int,
    *,
    handed_off: bool,
) -> dict[str, object]:
    return {
        "recordKind": "collection_request",
        "requestId": request_id,
        "questionId": "SCI-001",
        "meetingRoundId": f"review-{round_index}",
        "status": "handed_off" if handed_off else "pending",
        "collectionRunId": f"child-{request_id}",
        "collectionRunStatus": "succeeded",
        "searchEnvelope": {"keywords": ["water"]},
        "createdAt": "2026-08-25T00:01:00Z",
    }


def _convergence_adjudication_record(
    round_index: int,
    decision: str,
) -> dict[str, object]:
    return {
        "recordKind": "human_adjudication",
        "adjudicationId": f"adjudication-{decision}-{round_index}",
        "hypothesisRoundId": f"round-{round_index}",
        "decision": decision,
        "questionId": "SCI-001",
        "meetingRoundIds": [f"review-{round_index}"],
        "updatedAt": "2026-08-25T00:05:00Z",
    }


def _convergence_commands(state: HypothesisFirstStateV2) -> dict[str, Any]:
    return {
        action.command: action
        for action in state.allowedActions
        if action.kind == "command"
    }


def test_accepted_adjudication_with_all_requests_handed_off_converges() -> None:
    """Budget-exhausted round: accepted adjudication + every new evidence
    request handed off -> the v2 projection converges green and switches to
    the formal-run creation exit instead of re-offering adjudication."""
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "hypothesis_candidate",
                    "candidateId": "candidate-1",
                    "questionId": "SCI-001",
                },
                _convergence_link_record(5),
                _convergence_request_record("request-1", 5, handed_off=True),
                _convergence_adjudication_record(5, "accepted"),
            ],
            selection_records=[
                {
                    "selectionId": "selection-1",
                    "questionId": "SCI-001",
                    "selectedCandidateIds": ["candidate-1"],
                }
            ],
            meeting_records=[
                {
                    "meetingRoundId": "review-5",
                    "meetingType": "hypothesis_review",
                    "question": "SCI-001",
                    "status": "closed",
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[_convergence_round_record(5)],
        )
    )

    commands = _convergence_commands(state)
    # A converged chain that offers create_formal_run derives its current
    # phase from that offer (formal_runtime); the convergence payload is the
    # authority under test here.
    assert state.convergence.accepted is True
    assert state.convergence.lifecycle == "completed"
    assert state.convergence.outcome == "succeeded"
    assert state.convergence.actionability == "terminal"
    assert "human_adjudication" not in commands
    assert "create_formal_run" in commands


def test_accepted_adjudication_with_pending_request_stays_unconverged() -> None:
    """An accepted adjudication can never waive unfinished collection: one
    request that has not been handed off keeps the projection unconverged."""
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "hypothesis_candidate",
                    "candidateId": "candidate-1",
                    "questionId": "SCI-001",
                },
                _convergence_link_record(5),
                _convergence_request_record("request-1", 5, handed_off=True),
                _convergence_request_record("request-2", 5, handed_off=False),
                _convergence_adjudication_record(5, "accepted"),
            ],
            selection_records=[
                {
                    "selectionId": "selection-1",
                    "questionId": "SCI-001",
                    "selectedCandidateIds": ["candidate-1"],
                }
            ],
            meeting_records=[
                {
                    "meetingRoundId": "review-5",
                    "meetingType": "hypothesis_review",
                    "question": "SCI-001",
                    "status": "closed",
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[_convergence_round_record(5)],
        )
    )

    # The pending handoff pulls currentPhase to "collection"; the convergence
    # payload is the authority under test here.
    assert state.convergence.accepted is False
    assert state.convergence.outcome == "exhausted"


def test_unadjudicated_new_requests_budget_exhausted_offers_human_adjudication() -> None:
    """Meta review accepted, round budget exhausted, new evidence requests all
    handed off but no human decision yet -> the projection must NOT fake
    convergence and must surface the human adjudication offer."""
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "hypothesis_candidate",
                    "candidateId": "candidate-1",
                    "questionId": "SCI-001",
                },
                _convergence_link_record(5),
                _convergence_request_record("request-1", 5, handed_off=True),
            ],
            selection_records=[
                {
                    "selectionId": "selection-1",
                    "questionId": "SCI-001",
                    "selectedCandidateIds": ["candidate-1"],
                }
            ],
            meeting_records=[
                {
                    "meetingRoundId": "review-5",
                    "meetingType": "hypothesis_review",
                    "question": "SCI-001",
                    "status": "closed",
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[_convergence_round_record(5)],
        )
    )

    commands = _convergence_commands(state)
    assert state.currentPhase == "convergence"
    assert state.convergence.accepted is False
    assert state.convergence.lifecycle == "completed"
    assert state.convergence.outcome == "exhausted"
    assert "human_adjudication" in commands
    assert "open_next_review" not in commands
    assert commands["human_adjudication"].payload.hypothesisRoundId == "round-5"


def test_unadjudicated_new_requests_within_budget_offers_open_next_review() -> None:
    """Same unconverged shape but inside the round budget -> the projection
    offers the next review round, not the adjudication exit."""
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "hypothesis_candidate",
                    "candidateId": "candidate-1",
                    "questionId": "SCI-001",
                },
                _convergence_link_record(3),
                _convergence_request_record("request-1", 3, handed_off=True),
            ],
            selection_records=[
                {
                    "selectionId": "selection-1",
                    "questionId": "SCI-001",
                    "selectedCandidateIds": ["candidate-1"],
                }
            ],
            meeting_records=[
                {
                    "meetingRoundId": "review-3",
                    "meetingType": "hypothesis_review",
                    "question": "SCI-001",
                    "status": "closed",
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[_convergence_round_record(3)],
        )
    )

    commands = _convergence_commands(state)
    assert state.currentPhase == "convergence"
    assert state.convergence.accepted is False
    assert state.convergence.lifecycle == "waiting_human"
    assert "open_next_review" in commands
    assert "human_adjudication" not in commands


def test_program_output_waits_for_exact_h1_h4_review() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            formal_runs=[
                {
                    "runId": "run-1",
                    "teamId": "team-1",
                    "questionId": "SCI-001",
                    "status": "succeeded",
                    "runVersion": 7,
                    "completionKind": "completed",
                    "parentRunId": None,
                }
            ],
            formal_snapshots={
                "run-1": {
                    "deliveryStatus": "succeeded",
                    "artifactSummary": {
                        "finalArtifactLocator": "artifact://delivery/run-1"
                    },
                }
            },
            program_output={
                "record": {
                    "recordId": "output-1",
                    "runId": "run-1",
                    "status": "validated",
                    "validation": {
                        "schemaValidation": "passed",
                        "citationValidation": "passed",
                        "semanticValidation": "passed",
                        "officialModelCall": True,
                    },
                    "humanGates": {
                        "decisions": {
                            "H1_problem_understanding": "pending",
                            "H2_hypothesis_selection": "pending",
                            "H3_research_plan": "pending",
                            "H4_external_output": "pending",
                        },
                        "approvedCount": 0,
                    },
                }
            },
        )
    )

    assert state.currentPhase == "program_delivery"
    assert state.programDelivery.lifecycle == "waiting_human"
    assert state.programDelivery.humanReviewStatus == "waiting_human"
    assert any(
        action.kind == "command" and action.command == "record_program_review"
        for action in state.allowedActions
    )


def test_program_output_validation_failure_blocks_human_review() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            formal_runs=[
                {
                    "runId": "run-1",
                    "teamId": "team-1",
                    "questionId": "SCI-001",
                    "status": "succeeded",
                    "runVersion": 7,
                    "completionKind": "completed",
                }
            ],
            formal_snapshots={"run-1": {"deliveryStatus": "succeeded"}},
            program_output={
                "record": {
                    "recordId": "output-1",
                    "runId": "run-1",
                    "validation": {
                        "schemaValidation": "passed",
                        "citationValidation": "failed",
                        "semanticValidation": "passed",
                        "officialModelCall": True,
                    },
                    "humanGates": {"decisions": {}},
                }
            },
        )
    )

    assert state.currentPhase == "program_delivery"
    assert state.programDelivery.actionability == "blocked"
    assert state.programDelivery.humanReviewStatus == "not_started"
    assert any(
        problem.code == "program_candidate_validation_failed"
        for problem in state.problems
    )
    assert not any(
        action.kind == "command" and action.command == "record_program_review"
        for action in state.allowedActions
    )
    assert any(
        action.kind == "command" and action.command == "archive_run"
        for action in state.allowedActions
    )


def test_succeeded_run_with_missing_delivery_event_retries_program_handoff() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            formal_runs=[{
                "runId": "run-delivery-gap",
                "teamId": "team-1",
                "questionId": "SCI-001",
                "status": "succeeded",
                "runVersion": 5,
            }],
            formal_snapshots={"run-delivery-gap": {}},
        )
    )

    commands = [
        action.command for action in state.allowedActions if action.kind == "command"
    ]
    assert commands == ["retry_program_handoff"]


def test_revision_requested_keeps_create_revision_action_in_program_phase() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            formal_runs=[
                {
                    "runId": "run-1",
                    "teamId": "team-1",
                    "questionId": "SCI-001",
                    "status": "succeeded",
                    "runVersion": 7,
                    "completionKind": "completed",
                }
            ],
            formal_snapshots={"run-1": {"deliveryStatus": "succeeded"}},
            program_output={
                "record": {
                    "recordId": "output-1",
                    "runId": "run-1",
                    "validation": {
                        "schemaValidation": "passed",
                        "citationValidation": "passed",
                        "semanticValidation": "passed",
                        "officialModelCall": True,
                    },
                    "humanGates": {
                        "decisions": {
                            "H1_problem_understanding": "approved",
                            "H2_hypothesis_selection": "revision_requested",
                            "H3_research_plan": "approved",
                            "H4_external_output": "approved",
                        }
                    },
                }
            },
        )
    )

    actions = [
        action
        for action in state.allowedActions
        if action.kind == "command" and action.command == "create_formal_revision"
    ]
    assert state.currentPhase == "program_delivery"
    assert len(actions) == 1
    assert actions[0].targetPhase == "program_delivery"


def test_imported_program_output_is_visible_without_a_formal_run() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            program_output={
                "record": {
                    "recordId": "SCI-001:manual-run",
                    "questionId": "SCI-001",
                    "runId": "manual-run",
                    "registeredAt": "2026-08-25T00:00:00Z",
                    "validation": {
                        "schemaValidation": "passed",
                        "citationValidation": "passed",
                        "semanticValidation": "passed",
                        "officialModelCall": True,
                    },
                    "humanGates": {
                        "decisions": {
                            "H1_problem_understanding": "pending",
                            "H2_hypothesis_selection": "pending",
                            "H3_research_plan": "pending",
                            "H4_external_output": "pending",
                        }
                    },
                }
            },
        )
    )

    assert state.isInitial is False
    assert state.currentPhase == "program_delivery"
    assert state.programDelivery.outputRunId == "manual-run"
    assert state.programDelivery.humanReviewStatus == "waiting_human"
    assert any(
        action.kind == "command" and action.command == "record_program_review"
        for action in state.allowedActions
    )


def test_default_review_return_route_uses_the_canonical_team_workspace_url() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "hypothesis_candidate",
                    "questionId": "SCI-001",
                    "candidateId": "candidate-1",
                    "candidateOrder": 0,
                },
                {
                    "recordKind": "review_round_link",
                    "questionId": "SCI-001",
                    "linkId": "link-1",
                    "selectionId": "selection-1",
                    "candidateId": "candidate-1",
                    "roundIndex": 1,
                    "meetingRoundId": "meeting-1",
                },
            ],
            selection_records=[
                {
                    "selectionId": "selection-1",
                    "questionId": "SCI-001",
                    "selectedCandidateIds": ["candidate-1"],
                }
            ],
            meeting_records=[
                {
                    "meetingRoundId": "meeting-1",
                    "meetingType": "hypothesis_review",
                    "status": "awaiting_approval",
                    "linkedChatRoomId": "room-1",
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
        )
    )

    anchor = state.review.candidates[0].discussionAnchor
    assert anchor is not None
    assert anchor.returnTo == (
        "/teams?teamId=team-1&researchView=workflow&"
        "workflowId=challenge-cup-research&questionId=SCI-001&panel=node"
    )
    assert "returnTo=%2Fteams%3FteamId%3Dteam-1" in str(anchor.deepLink)


def test_generation_waiting_human_exposes_approval_and_room_navigation() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[
                {
                    "meetingRoundId": "generation-1",
                    "meetingType": "hypothesis_candidate_generation",
                    "question": "SCI-001",
                    "status": "awaiting_approval",
                    "linkedChatRoomId": "room-generation",
                    "digestDraft": {"contentHash": "digest-hash"},
                    "createdAt": "2026-08-25T00:00:00Z",
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            return_to="/teams?teamId=team-1&researchView=workflow",
        )
    )

    commands = {
        action.command
        for action in state.allowedActions
        if action.kind == "command"
    }
    navigation = [
        action
        for action in state.allowedActions
        if action.kind == "navigation"
    ]
    assert "approve_summary" in commands
    assert len(navigation) == 1
    assert navigation[0].navigation.meetingRoundId == "generation-1"
    assert navigation[0].navigation.returnTo.startswith("/teams?")


def test_stalled_review_exposes_precise_discussion_recovery_actions() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "hypothesis_candidate",
                    "candidateId": "candidate-1",
                    "questionId": "SCI-001",
                },
                {
                    "recordKind": "review_round_link",
                    "linkId": "link-1",
                    "selectionId": "selection-1",
                    "candidateId": "candidate-1",
                    "candidateOrder": 0,
                    "roundIndex": 1,
                    "meetingRoundId": "review-1",
                    "questionId": "SCI-001",
                },
            ],
            selection_records=[
                {
                    "selectionId": "selection-1",
                    "questionId": "SCI-001",
                    "selectedCandidateIds": ["candidate-1"],
                }
            ],
            meeting_records=[
                {
                    "meetingRoundId": "review-1",
                    "meetingType": "hypothesis_review",
                    "question": "SCI-001",
                    "selectionId": "selection-1",
                    "status": "blocked",
                    "stalledReason": "discussion driver stopped",
                    "linkedChatRoomId": "room-review",
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
        )
    )

    commands = {
        action.command
        for action in state.allowedActions
        if action.kind == "command"
    }
    assert {"resume_discussion", "stop_discussion", "regenerate_summary"} <= commands


def test_stopped_linked_chat_round_projects_guarded_review_reopen() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "hypothesis_candidate",
                    "candidateId": "candidate-1",
                    "questionId": "SCI-001",
                },
                {
                    "recordKind": "review_round_link",
                    "linkId": "link-1",
                    "selectionId": "selection-1",
                    "candidateId": "candidate-1",
                    "candidateOrder": 0,
                    "roundIndex": 1,
                    "meetingRoundId": "review-1",
                    "questionId": "SCI-001",
                },
            ],
            selection_records=[
                {
                    "selectionId": "selection-1",
                    "questionId": "SCI-001",
                    "selectedCandidateIds": ["candidate-1"],
                }
            ],
            meeting_records=[
                {
                    "meetingRoundId": "review-1",
                    "meetingType": "hypothesis_review",
                    "question": "SCI-001",
                    "selectionId": "selection-1",
                    "status": "open",
                    "linkedChatRoomId": "room-review",
                    "chatRoomRoundIds": ["room-round-1"],
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            chat_room_round_snapshots={
                "room-round-1": {
                    "runId": "room-round-1",
                    "runKind": "chat_room_round",
                    "status": "stopped",
                    "currentPhase": "stopped",
                    "runtimeStatus": "orphan_reconciled",
                    "reconciliationSource": "missing_process_controller",
                    "summary": "群聊轮次已停止：0/4 位 Agent 已发言。后端进程已重启。",
                    "updatedAt": "2026-08-26T02:17:41Z",
                    "finishedAt": "2026-08-26T02:17:41Z",
                }
            },
        )
    )

    candidate = state.review.candidates[0]
    assert candidate.lifecycle == "failed"
    assert candidate.actionability == "blocked"
    assert candidate.discussion.lifecycle == "failed"
    assert candidate.discussion.actionability == "blocked"
    assert state.review.lifecycle == "failed"
    assert state.review.actionability == "blocked"
    assert state.currentPhase == "review"
    assert any(
        problem.code == "discussion_round_orphaned"
        and "后端进程已重启" in problem.message
        for problem in state.problems
    )

    commands = {
        action.command
        for action in state.allowedActions
        if action.kind == "command"
    }
    assert "reopen_review" in commands
    assert "resume_discussion" not in commands
    assert "retry_review_dispatch" not in commands


def test_summarizing_generation_with_all_terminal_bound_rounds_exposes_summary_retry() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-002",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[
                {
                    "meetingRoundId": "generation-1",
                    "meetingType": "hypothesis_candidate_generation",
                    "question": "SCI-002",
                    "status": "summarizing",
                    "linkedChatRoomId": "room-generation",
                    "chatRoomRoundIds": ["round-completed", "round-stopped"],
                    "summaryStartedAt": "2026-08-26T02:00:00Z",
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            chat_room_round_snapshots={
                "round-completed": {
                    "runId": "round-completed",
                    "runKind": "chat_room_round",
                    "status": "completed",
                },
                "round-stopped": {
                    "runId": "round-stopped",
                    "runKind": "chat_room_round",
                    "status": "stopped",
                    "runtimeStatus": "orphan_reconciled",
                },
            },
        )
    )

    commands = [
        action.command
        for action in state.allowedActions
        if action.kind == "command"
    ]
    assert state.currentPhase == "generation"
    assert state.generation.lifecycle == "failed"
    assert commands == ["regenerate_summary"]
    retry = next(
        action
        for action in state.allowedActions
        if action.kind == "command" and action.command == "regenerate_summary"
    )
    assert retry.payload.meetingRoundId == "generation-1"


def test_summarizing_review_with_all_terminal_bound_rounds_exposes_summary_retry() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "hypothesis_candidate",
                    "candidateId": "candidate-1",
                    "questionId": "SCI-001",
                },
                {
                    "recordKind": "review_round_link",
                    "linkId": "link-1",
                    "selectionId": "selection-1",
                    "candidateId": "candidate-1",
                    "candidateOrder": 0,
                    "roundIndex": 1,
                    "meetingRoundId": "review-1",
                    "questionId": "SCI-001",
                },
            ],
            selection_records=[
                {
                    "selectionId": "selection-1",
                    "questionId": "SCI-001",
                    "selectedCandidateIds": ["candidate-1"],
                }
            ],
            meeting_records=[
                {
                    "meetingRoundId": "review-1",
                    "meetingType": "hypothesis_review",
                    "question": "SCI-001",
                    "selectionId": "selection-1",
                    "status": "summarizing",
                    "linkedChatRoomId": "room-review",
                    "chatRoomRoundIds": ["round-completed", "round-stopped"],
                    "summaryStartedAt": "2026-08-26T02:00:00Z",
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            chat_room_round_snapshots={
                "round-completed": {
                    "runId": "round-completed",
                    "runKind": "chat_room_round",
                    "status": "completed",
                },
                "round-stopped": {
                    "runId": "round-stopped",
                    "runKind": "chat_room_round",
                    "status": "stopped",
                    "runtimeStatus": "orphan_reconciled",
                },
            },
        )
    )

    commands = {
        action.command
        for action in state.allowedActions
        if action.kind == "command"
    }
    assert state.currentPhase == "review"
    assert "regenerate_summary" in commands
    assert "reopen_review" not in commands


@pytest.mark.parametrize(
    "chat_room_round_snapshots",
    [
        {
            "round-completed": {
                "runId": "round-completed",
                "runKind": "chat_room_round",
                "status": "completed",
            },
            "round-running": {
                "runId": "round-running",
                "runKind": "chat_room_round",
                "status": "running",
            },
        },
        {
            "round-completed": {
                "runId": "round-completed",
                "runKind": "chat_room_round",
                "status": "completed",
            }
        },
    ],
    ids=["bound-round-running", "bound-round-snapshot-missing"],
)
def test_summarizing_generation_requires_every_bound_round_terminal_snapshot(
    chat_room_round_snapshots: dict[str, dict[str, str]],
) -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-002",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[
                {
                    "meetingRoundId": "generation-1",
                    "meetingType": "hypothesis_candidate_generation",
                    "question": "SCI-002",
                    "status": "summarizing",
                    "linkedChatRoomId": "room-generation",
                    "chatRoomRoundIds": ["round-completed", "round-running"],
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            chat_room_round_snapshots=chat_room_round_snapshots,
        )
    )

    assert "regenerate_summary" not in {
        action.command
        for action in state.allowedActions
        if action.kind == "command"
    }


def test_v2_reopen_review_command_uses_guarded_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_service
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain,
        hypothesis_first_state_v2,
    )

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hypothesis_first_chain, "PROJECT_ROOT", tmp_path)
    snapshot = {
        "stateVersion": "hf2-action:orphaned-review",
        "allowedActions": [
            {
                "kind": "command",
                "actionId": "reopen-review:review-1",
                "command": "reopen_review",
                "payload": {"meetingRoundId": "review-1"},
                "enabled": True,
                "idempotencyKey": "hf2:reopen-review:review-1",
            }
        ],
    }
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    calls: list[tuple[str, str]] = []

    def reopen(team_id: str, meeting_round_id: str, **_kwargs):
        calls.append((team_id, meeting_round_id))
        return {"status": "reopened", "meetingRoundId": "review-2"}

    monkeypatch.setattr(hypothesis_first_chain, "reopen_failed_review_meeting", reopen)
    result = hypothesis_first_chain.execute_v2_command(
        "team-1",
        {
            "actionId": "reopen-review:review-1",
            "idempotencyKey": "hf2:reopen-review:review-1",
            "expectedStateVersion": "hf2-action:orphaned-review",
            "command": "reopen_review",
            "payload": {"meetingRoundId": "review-1"},
        },
        question_id="SCI-001",
    )

    assert result["result"]["status"] == "reopened"
    assert calls == [("team-1", "review-1")]


def test_v2_archive_run_command_uses_formal_command_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_service
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain,
        hypothesis_first_state_v2,
    )

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hypothesis_first_chain, "PROJECT_ROOT", tmp_path)
    snapshot = {
        "stateVersion": "hf2-action:terminal-run",
        "allowedActions": [{
            "kind": "command",
            "actionId": "archive-formal-run:run-terminal",
            "command": "archive_run",
            "payload": {"runId": "run-terminal"},
            "enabled": True,
            "idempotencyKey": "hf2:archive-formal-run:run-terminal",
        }],
    }
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    calls: list[tuple[str, str, str, str]] = []

    def submit(
        team_id: str,
        *,
        run_id: str,
        command: str,
        idempotency_key: str,
        **_kwargs,
    ):
        calls.append((team_id, run_id, command, idempotency_key))
        return {"status": "accepted"}

    monkeypatch.setattr(hypothesis_first_chain, "_submit_formal_v2_command", submit)
    result = hypothesis_first_chain.execute_v2_command(
        "team-1",
        {
            "actionId": "archive-formal-run:run-terminal",
            "idempotencyKey": "hf2:archive-formal-run:run-terminal",
            "expectedStateVersion": "hf2-action:terminal-run",
            "command": "archive_run",
            "payload": {"runId": "run-terminal"},
        },
        question_id="SCI-001",
    )

    assert result["result"]["status"] == "accepted"
    assert calls == [(
        "team-1",
        "run-terminal",
        "archive_run",
        "hf2:archive-formal-run:run-terminal",
    )]


def test_v2_cancel_run_command_uses_formal_command_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_service
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain,
        hypothesis_first_state_v2,
    )

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hypothesis_first_chain, "PROJECT_ROOT", tmp_path)
    snapshot = {
        "stateVersion": "hf2-action:created-run",
        "allowedActions": [{
            "kind": "command",
            "actionId": "cancel-formal-run:run-created",
            "command": "cancel_run",
            "payload": {"runId": "run-created"},
            "enabled": True,
            "idempotencyKey": "hf2:cancel-formal-run:run-created",
        }],
    }
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    calls: list[tuple[str, str, str, str]] = []

    def submit(team_id: str, *, run_id: str, command: str, idempotency_key: str, **_kwargs):
        calls.append((team_id, run_id, command, idempotency_key))
        return {"status": "accepted"}

    monkeypatch.setattr(hypothesis_first_chain, "_submit_formal_v2_command", submit)
    result = hypothesis_first_chain.execute_v2_command(
        "team-1",
        {
            "actionId": "cancel-formal-run:run-created",
            "idempotencyKey": "hf2:cancel-formal-run:run-created",
            "expectedStateVersion": "hf2-action:created-run",
            "command": "cancel_run",
            "payload": {"runId": "run-created"},
        },
        question_id="SCI-001",
    )

    assert result["result"]["status"] == "accepted"
    assert calls == [(
        "team-1",
        "run-created",
        "cancel_run",
        "hf2:cancel-formal-run:run-created",
    )]


@pytest.mark.parametrize(
    "offers",
    [
        [{
            "command": "retry_node",
            "nodeId": "source_extraction",
            "available": False,
            "payload": {"retryKind": "same_node"},
        }],
        [{
            "command": "retry_node",
            "nodeId": "different_node",
            "available": True,
            "payload": {"retryKind": "same_node"},
        }],
        [{
            "command": "retry_node",
            "nodeId": "source_extraction",
            "available": True,
            "payload": {"retryKind": "same_node"},
        }],
    ],
    ids=["unavailable", "tampered-node", "missing-idempotency"],
)
def test_submit_formal_retry_rejects_unavailable_or_tampered_offer(
    offers: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from core.web.services.team_workflow.research_runtime import (
        formal_read_runtime,
        hypothesis_first_chain,
        runtime_factory,
    )

    run = SimpleNamespace(run_id="run-retry", team_id="team-1", run_version=7)

    class Query:
        def get_snapshot(self, *, team_id: str, run_id: str):
            assert (team_id, run_id) == ("team-1", "run-retry")
            return {"commandOffers": offers}

    class CommandService:
        def submit(self, _request):
            pytest.fail("an unavailable or mismatched retry offer must not submit")

    runtime = SimpleNamespace(
        store=SimpleNamespace(get_run=lambda run_id: run if run_id == run.run_id else None),
        command_service=CommandService(),
    )
    monkeypatch.setattr(runtime_factory, "production_workflow_runtime", lambda: runtime)
    monkeypatch.setattr(formal_read_runtime, "get_query_service", lambda: Query())

    with pytest.raises(hypothesis_first_chain.HypothesisFirstChainError):
        hypothesis_first_chain._submit_formal_v2_command(
            "team-1",
            run_id="run-retry",
            node_id="source_extraction",
            command="retry_node",
            idempotency_key="hf2:retry-formal-node:run-retry:source-extraction",
        )


def test_submit_formal_retry_uses_current_offer_payload_and_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from core.research.workflow.contracts import WorkflowCommandKind
    from core.web.services.team_workflow.research_runtime import (
        formal_read_runtime,
        hypothesis_first_chain,
        runtime_factory,
    )

    run = SimpleNamespace(run_id="run-retry", team_id="team-1", run_version=7)
    snapshot = {
        "run": {"runVersion": 7},
        "commandOffers": [{
            "command": "retry_node",
            "nodeId": "source_extraction",
            "available": True,
            "idempotencyKey": "offer:run-retry:source_extraction:retry_node:a2:v7",
            "payload": {"retryKind": "same_node"},
        }],
    }
    calls: list[object] = []

    class Query:
        def get_snapshot(self, *, team_id: str, run_id: str):
            assert (team_id, run_id) == ("team-1", "run-retry")
            return snapshot

    class CommandService:
        def submit(self, request):
            calls.append(request)
            return SimpleNamespace(to_dict=lambda: {"status": "accepted"})

    runtime = SimpleNamespace(
        store=SimpleNamespace(get_run=lambda run_id: run if run_id == run.run_id else None),
        command_service=CommandService(),
    )
    monkeypatch.setattr(runtime_factory, "production_workflow_runtime", lambda: runtime)
    monkeypatch.setattr(formal_read_runtime, "get_query_service", lambda: Query())

    result = hypothesis_first_chain._submit_formal_v2_command(
        "team-1",
        run_id="run-retry",
        node_id="source_extraction",
        command="retry_node",
        idempotency_key="hf2:retry-formal-node:run-retry:source-extraction",
    )

    assert result == {"status": "accepted"}
    assert len(calls) == 1
    request = calls[0]
    assert request.command is WorkflowCommandKind.RETRY_NODE
    assert request.run_id == "run-retry"
    assert request.team_id == "team-1"
    assert request.node_id == "source_extraction"
    assert request.expected_run_version == 7
    assert request.idempotency_key == (
        "offer:run-retry:source_extraction:retry_node:a2:v7"
    )
    assert request.payload == {"retryKind": "same_node"}


def test_submit_formal_retry_keeps_readiness_rejection_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A readiness-blocked retry must surface its blockers, not a flat message."""
    from types import SimpleNamespace

    from core.research.workflow.contracts import ReadinessBlocker
    from core.web.services.team_workflow.research_runtime import (
        command_service as runtime_command_service,
        formal_read_runtime,
        hypothesis_first_chain,
        runtime_factory,
    )

    blocker = ReadinessBlocker(
        code="auto_advance_not_ready",
        title="缺少来源候选",
        detail="auto_advance_not_ready/source_candidates_missing",
    )
    rejection = runtime_command_service.NodeNotReadyError(
        SimpleNamespace(blockers=(blocker,)),
        run_version=7,
    )

    run = SimpleNamespace(run_id="run-retry", team_id="team-1", run_version=7)
    snapshot = {
        "commandOffers": [{
            "command": "retry_node",
            "nodeId": "source_extraction",
            "available": True,
            "idempotencyKey": "offer:run-retry:source_extraction:retry_node:a2:v7",
            "payload": {"retryKind": "same_node"},
        }],
    }

    class Query:
        def get_snapshot(self, *, team_id: str, run_id: str):
            return snapshot

    class CommandService:
        def submit(self, _request):
            raise rejection

    runtime = SimpleNamespace(
        store=SimpleNamespace(get_run=lambda run_id: run if run_id == run.run_id else None),
        command_service=CommandService(),
    )
    monkeypatch.setattr(runtime_factory, "production_workflow_runtime", lambda: runtime)
    monkeypatch.setattr(formal_read_runtime, "get_query_service", lambda: Query())

    with pytest.raises(hypothesis_first_chain.FormalCommandRejectedError) as excinfo:
        hypothesis_first_chain._submit_formal_v2_command(
            "team-1",
            run_id="run-retry",
            node_id="source_extraction",
            command="retry_node",
            idempotency_key="hf2:retry-formal-node:run-retry:source-extraction",
        )

    error = excinfo.value
    assert error.code == "node_not_ready"
    assert error.status_code == 412
    assert error.blockers == [blocker.to_dict()]


@pytest.mark.parametrize(
    "offers",
    [
        [{
            "command": "start_node",
            "nodeId": "problem_understanding",
            "available": False,
            "payload": {},
        }],
        [{
            "command": "start_node",
            "nodeId": "hypothesis_design",
            "available": True,
            "payload": {},
        }],
        [{
            "command": "retry_node",
            "nodeId": "problem_understanding",
            "available": True,
            "idempotencyKey": "offer:run-fresh:problem_understanding:retry_node:a2:v1",
            "payload": {"retryKind": "same_node"},
        }],
        [],
    ],
    ids=["unavailable", "tampered-node", "wrong-command", "no-offers"],
)
def test_submit_formal_start_rejects_unavailable_or_mismatched_offer(
    offers: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from core.web.services.team_workflow.research_runtime import (
        formal_read_runtime,
        hypothesis_first_chain,
        runtime_factory,
    )

    run = SimpleNamespace(run_id="run-fresh", team_id="team-1", run_version=1)

    class Query:
        def get_snapshot(self, *, team_id: str, run_id: str):
            assert (team_id, run_id) == ("team-1", "run-fresh")
            return {"commandOffers": offers}

    class CommandService:
        def submit(self, _request):
            pytest.fail("an unavailable or mismatched start offer must not submit")

    runtime = SimpleNamespace(
        store=SimpleNamespace(get_run=lambda run_id: run if run_id == run.run_id else None),
        command_service=CommandService(),
    )
    monkeypatch.setattr(runtime_factory, "production_workflow_runtime", lambda: runtime)
    monkeypatch.setattr(formal_read_runtime, "get_query_service", lambda: Query())

    with pytest.raises(hypothesis_first_chain.HypothesisFirstChainError):
        hypothesis_first_chain._submit_formal_v2_command(
            "team-1",
            run_id="run-fresh",
            node_id="problem_understanding",
            command="start_node",
            idempotency_key="hf2:create-formal-run:round-accepted:1",
        )


def test_submit_formal_start_uses_current_offer_payload_and_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from core.research.workflow.contracts import WorkflowCommandKind
    from core.web.services.team_workflow.research_runtime import (
        formal_read_runtime,
        hypothesis_first_chain,
        runtime_factory,
    )

    run = SimpleNamespace(run_id="run-fresh", team_id="team-1", run_version=1)
    snapshot = {
        "run": {"runVersion": 1},
        "commandOffers": [{
            "command": "start_node",
            "nodeId": "problem_understanding",
            "available": True,
            "idempotencyKey": "offer:run-fresh:problem_understanding:start_node:v1",
            "payload": {},
        }],
    }
    calls: list[object] = []

    class Query:
        def get_snapshot(self, *, team_id: str, run_id: str):
            assert (team_id, run_id) == ("team-1", "run-fresh")
            return snapshot

    class CommandService:
        def submit(self, request):
            calls.append(request)
            return SimpleNamespace(to_dict=lambda: {"status": "accepted"})

    runtime = SimpleNamespace(
        store=SimpleNamespace(get_run=lambda run_id: run if run_id == run.run_id else None),
        command_service=CommandService(),
    )
    monkeypatch.setattr(runtime_factory, "production_workflow_runtime", lambda: runtime)
    monkeypatch.setattr(formal_read_runtime, "get_query_service", lambda: Query())

    result = hypothesis_first_chain._submit_formal_v2_command(
        "team-1",
        run_id="run-fresh",
        node_id="problem_understanding",
        command="start_node",
        idempotency_key="hf2:create-formal-run:round-accepted:1",
    )

    assert result == {"status": "accepted"}
    assert len(calls) == 1
    request = calls[0]
    assert request.command is WorkflowCommandKind.START_NODE
    assert request.run_id == "run-fresh"
    assert request.team_id == "team-1"
    assert request.node_id == "problem_understanding"
    assert request.expected_run_version == 1
    # The offer's own idempotency key (not the chain action key) makes replays
    # of the same start land on the command service idempotency fence.
    assert request.idempotency_key == "offer:run-fresh:problem_understanding:start_node:v1"
    assert request.payload == {}


def _patch_create_formal_run_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    offers: list[dict[str, object]],
    runtime: Any = None,
) -> tuple[list[object], list[tuple[str, dict[str, Any]]]]:
    """Shared scaffolding: v2 envelope for create_formal_run + runtime fakes.

    Returns ``(submit_calls, scene_events)``.  ``runtime=None`` simulates the
    command-line path where no production runtime (command service) exists.
    """
    from types import SimpleNamespace

    from core.research.workflow.definition import (
        build_challenge_cup_workflow_definition,
    )
    from core.research.workflow.definition_registry import definition_identity
    from core.web.services import team_service
    from core.web.services.team_workflow.research_runtime import (
        formal_read_runtime,
        hypothesis_first_chain,
        hypothesis_first_state_v2,
        run_creation,
        runtime_factory,
    )

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hypothesis_first_chain, "PROJECT_ROOT", tmp_path)
    snapshot = {
        "stateVersion": "hf2-action:converged-round",
        "allowedActions": [{
            "kind": "command",
            "actionId": "create-formal-run-v2:round-accepted:1",
            "command": "create_formal_run",
            "payload": {"hypothesisRoundId": "round-accepted"},
            "enabled": True,
            "idempotencyKey": "hf2:create-formal-run:round-accepted:1",
        }],
    }
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    identity = definition_identity(build_challenge_cup_workflow_definition())
    created_run = {
        "runId": "run-fresh",
        "workflowId": identity.workflowId,
        "workflowVersionId": identity.workflowVersionId,
        "structureHash": identity.structureHash,
        "teamId": "team-1",
        "questionId": "SCI-001",
        "status": "queued",
        "runVersion": 1,
    }
    monkeypatch.setattr(
        run_creation,
        "create_question_run",
        lambda *_args, **_kwargs: dict(created_run),
    )

    class Query:
        def get_snapshot(self, *, team_id: str, run_id: str):
            assert (team_id, run_id) == ("team-1", "run-fresh")
            return {"commandOffers": offers}

    monkeypatch.setattr(formal_read_runtime, "get_query_service", lambda: Query())

    submit_calls: list[object] = []

    class CommandService:
        def submit(self, request):
            submit_calls.append(request)
            return SimpleNamespace(to_dict=lambda: {"status": "accepted"})

    run = SimpleNamespace(run_id="run-fresh", team_id="team-1", run_version=1)
    runtime_with_commands = SimpleNamespace(
        store=SimpleNamespace(get_run=lambda run_id: run if run_id == run.run_id else None),
        command_service=CommandService(),
    )
    monkeypatch.setattr(
        runtime_factory,
        "production_workflow_runtime",
        lambda: runtime_with_commands if runtime is not None else None,
    )

    scene_events: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        hypothesis_first_chain,
        "_record_scene_event",
        lambda event_code, **kwargs: scene_events.append((event_code, dict(kwargs))),
    )
    return submit_calls, scene_events


_CREATE_FORMAL_RUN_REQUEST = {
    "actionId": "create-formal-run-v2:round-accepted:1",
    "idempotencyKey": "hf2:create-formal-run:round-accepted:1",
    "expectedStateVersion": "hf2-action:converged-round",
    "command": "create_formal_run",
    "payload": {"hypothesisRoundId": "round-accepted"},
}

_START_OFFER = {
    "command": "start_node",
    "nodeId": "problem_understanding",
    "available": True,
    "idempotencyKey": "offer:run-fresh:problem_understanding:start_node:v1",
    "payload": {},
    "expectedRunVersion": 1,
}


def test_create_formal_run_auto_submits_entry_start_node_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.research.workflow.contracts import WorkflowCommandKind
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain

    submit_calls, scene_events = _patch_create_formal_run_envelope(
        monkeypatch, tmp_path, offers=[dict(_START_OFFER)], runtime=object()
    )

    result = hypothesis_first_chain.execute_v2_command(
        "team-1",
        dict(_CREATE_FORMAL_RUN_REQUEST),
        question_id="SCI-001",
    )

    # The create result envelope is unchanged and the start was submitted
    # exactly once, riding the entry node's start offer.
    assert result["result"]["runId"] == "run-fresh"
    assert result["command"] == "create_formal_run"
    assert len(submit_calls) == 1
    request = submit_calls[0]
    assert request.command is WorkflowCommandKind.START_NODE
    assert request.run_id == "run-fresh"
    assert request.team_id == "team-1"
    assert request.node_id == "problem_understanding"
    assert request.idempotency_key == "offer:run-fresh:problem_understanding:start_node:v1"
    submitted = [
        event for event, _fields in scene_events
        if event == "formal_run_auto_start_submitted"
    ]
    assert submitted == ["formal_run_auto_start_submitted"]


def test_create_formal_run_auto_start_replay_uses_offer_idempotency_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replays ride the same offer idempotencyKey, so the service never re-runs."""
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain

    submit_calls, _scene_events = _patch_create_formal_run_envelope(
        monkeypatch, tmp_path, offers=[dict(_START_OFFER)], runtime=object()
    )

    for _ in range(2):
        hypothesis_first_chain.execute_v2_command(
            "team-1",
            dict(_CREATE_FORMAL_RUN_REQUEST),
            question_id="SCI-001",
        )

    assert len(submit_calls) == 2
    keys = {request.idempotency_key for request in submit_calls}
    assert keys == {"offer:run-fresh:problem_understanding:start_node:v1"}


def test_create_formal_run_auto_start_waits_when_offer_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A readiness-blocked start offer must keep the historical manual wait."""
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain

    blocked = dict(_START_OFFER, available=False)
    submit_calls, scene_events = _patch_create_formal_run_envelope(
        monkeypatch, tmp_path, offers=[blocked], runtime=object()
    )

    result = hypothesis_first_chain.execute_v2_command(
        "team-1",
        dict(_CREATE_FORMAL_RUN_REQUEST),
        question_id="SCI-001",
    )

    # Create still succeeds, nothing is submitted, and the wait is observable.
    assert result["result"]["runId"] == "run-fresh"
    assert submit_calls == []
    waited = [
        fields for event, fields in scene_events
        if event == "formal_run_auto_start_waited"
    ]
    assert len(waited) == 1
    assert waited[0]["outcome"] == "waited_for_manual_start"
    assert waited[0]["fields"]["runId"] == "run-fresh"


def test_create_formal_run_auto_start_skips_without_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No production runtime (command-line path): skip quietly, create stands."""
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain

    submit_calls, scene_events = _patch_create_formal_run_envelope(
        monkeypatch, tmp_path, offers=[dict(_START_OFFER)], runtime=None
    )

    result = hypothesis_first_chain.execute_v2_command(
        "team-1",
        dict(_CREATE_FORMAL_RUN_REQUEST),
        question_id="SCI-001",
    )

    assert result["result"]["runId"] == "run-fresh"
    assert submit_calls == []
    waited = [
        fields for event, fields in scene_events
        if event == "formal_run_auto_start_waited"
    ]
    assert len(waited) == 1


def test_formal_command_rejection_maps_runtime_guard_errors() -> None:
    from core.research.workflow.ledger import CommandNotAllowedError
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain,
    )

    converted = hypothesis_first_chain._formal_command_rejection(
        CommandNotAllowedError("attempt running 不可重试")
    )
    assert isinstance(converted, hypothesis_first_chain.FormalCommandRejectedError)
    assert converted.code == "command_not_allowed"
    assert converted.status_code == 409
    assert converted.blockers == []

    fallback = hypothesis_first_chain._formal_command_rejection(ValueError("boom"))
    assert type(fallback) is hypothesis_first_chain.HypothesisFirstChainError
    assert str(fallback) == "boom"


def test_v2_retry_formal_node_command_uses_formal_command_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_service
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain,
        hypothesis_first_state_v2,
    )

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hypothesis_first_chain, "PROJECT_ROOT", tmp_path)
    snapshot = {
        "stateVersion": "hf2-action:running-retry",
        "allowedActions": [{
            "kind": "command",
            "actionId": "retry-formal-node:run-retry:source-extraction",
            "command": "retry_formal_node",
            "payload": {
                "runId": "run-retry",
                "nodeId": "source_extraction",
            },
            "enabled": True,
            "idempotencyKey": "hf2:retry-formal-node:run-retry:source-extraction",
        }],
    }
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    calls: list[tuple[str, str, str, str, str]] = []

    def submit(
        team_id: str,
        *,
        run_id: str,
        node_id: str,
        command: str,
        idempotency_key: str,
        **_kwargs,
    ):
        calls.append((team_id, run_id, node_id, command, idempotency_key))
        return {"status": "accepted"}

    monkeypatch.setattr(hypothesis_first_chain, "_submit_formal_v2_command", submit)
    result = hypothesis_first_chain.execute_v2_command(
        "team-1",
        {
            "actionId": "retry-formal-node:run-retry:source-extraction",
            "idempotencyKey": "hf2:retry-formal-node:run-retry:source-extraction",
            "expectedStateVersion": "hf2-action:running-retry",
            "command": "retry_formal_node",
            "payload": {
                "runId": "run-retry",
                "nodeId": "source_extraction",
            },
        },
        question_id="SCI-001",
    )

    assert result["result"]["status"] == "accepted"
    assert calls == [(
        "team-1",
        "run-retry",
        "source_extraction",
        "retry_node",
        "hf2:retry-formal-node:run-retry:source-extraction",
    )]


@pytest.mark.parametrize("current_round_status", ["running", "closed"])
def test_historical_stopped_linked_chat_round_does_not_block_current_round(
    current_round_status: str,
) -> None:
    """Only the latest bound room round can block an open meeting."""

    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "hypothesis_candidate",
                    "candidateId": "candidate-1",
                    "questionId": "SCI-001",
                },
                {
                    "recordKind": "review_round_link",
                    "linkId": "link-1",
                    "selectionId": "selection-1",
                    "candidateId": "candidate-1",
                    "candidateOrder": 0,
                    "roundIndex": 1,
                    "meetingRoundId": "review-1",
                    "questionId": "SCI-001",
                },
            ],
            selection_records=[
                {
                    "selectionId": "selection-1",
                    "questionId": "SCI-001",
                    "selectedCandidateIds": ["candidate-1"],
                }
            ],
            meeting_records=[
                {
                    "meetingRoundId": "review-1",
                    "meetingType": "hypothesis_review",
                    "question": "SCI-001",
                    "selectionId": "selection-1",
                    "status": "open",
                    "linkedChatRoomId": "room-review",
                    "chatRoomRoundIds": ["room-round-old", "room-round-current"],
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            chat_room_round_snapshots={
                "room-round-old": {
                    "runId": "room-round-old",
                    "runKind": "chat_room_round",
                    "status": "stopped",
                    "currentPhase": "stopped",
                    "runtimeStatus": "orphan_reconciled",
                    "reconciliationSource": "missing_process_controller",
                },
                "room-round-current": {
                    "runId": "room-round-current",
                    "runKind": "chat_room_round",
                    "status": current_round_status,
                    "currentPhase": current_round_status,
                    "runtimeStatus": current_round_status,
                },
            },
        )
    )

    assert state.review.candidates[0].lifecycle == "running"
    assert state.review.candidates[0].actionability == "executing"
    assert state.review.lifecycle == "running"
    assert state.review.actionability == "waiting_system"
    assert not any(
        problem.code
        in {
            "discussion_round_orphaned",
            "discussion_round_stopped",
            "discussion_round_failed",
        }
        for problem in state.problems
    )


def test_missing_linked_chat_round_snapshot_does_not_guess_that_open_meeting_stopped() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "hypothesis_candidate",
                    "candidateId": "candidate-1",
                    "questionId": "SCI-001",
                },
                {
                    "recordKind": "review_round_link",
                    "linkId": "link-1",
                    "selectionId": "selection-1",
                    "candidateId": "candidate-1",
                    "candidateOrder": 0,
                    "roundIndex": 1,
                    "meetingRoundId": "review-1",
                    "questionId": "SCI-001",
                },
            ],
            selection_records=[
                {
                    "selectionId": "selection-1",
                    "questionId": "SCI-001",
                    "selectedCandidateIds": ["candidate-1"],
                }
            ],
            meeting_records=[
                {
                    "meetingRoundId": "review-1",
                    "meetingType": "hypothesis_review",
                    "question": "SCI-001",
                    "selectionId": "selection-1",
                    "status": "open",
                    "linkedChatRoomId": "room-review",
                    "chatRoomRoundIds": ["room-round-missing"],
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            chat_room_round_snapshots={},
        )
    )

    assert state.review.candidates[0].lifecycle == "running"
    assert state.review.candidates[0].actionability == "executing"
    assert state.review.lifecycle == "running"
    assert state.review.actionability == "waiting_system"


def _iso_minute_offset(minutes: float) -> str:
    moment = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _generation_heartbeat_fixture(
    *,
    heartbeat_minutes_ago: float,
) -> dict[str, object]:
    heartbeat_at = _iso_minute_offset(heartbeat_minutes_ago)
    return HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-003",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "generation_attempt",
                    "attemptId": "attempt-1",
                    "attemptNumber": 1,
                    "questionId": "SCI-003",
                    "meetingRoundId": "candgen-1",
                    "lifecycle": "running",
                    "queuedAt": _iso_minute_offset(heartbeat_minutes_ago + 5),
                    "startedAt": heartbeat_at,
                    "heartbeatAt": heartbeat_at,
                    "createdAt": _iso_minute_offset(heartbeat_minutes_ago + 5),
                    "updatedAt": heartbeat_at,
                }
            ],
            selection_records=[],
            meeting_records=[
                {
                    "meetingRoundId": "candgen-1",
                    "meetingType": "hypothesis_candidate_generation",
                    "question": "SCI-003",
                    "status": "open",
                    "linkedChatRoomId": "room-generation",
                    "chatRoomRoundIds": ["room-round-1"],
                    "createdAt": _iso_minute_offset(heartbeat_minutes_ago + 5),
                    "updatedAt": heartbeat_at,
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            chat_room_round_snapshots={
                "room-round-1": {
                    "runId": "room-round-1",
                    "runKind": "chat_room_round",
                    "status": "running",
                    "updatedAt": heartbeat_at,
                }
            },
        )
    )


def test_generation_running_with_fresh_heartbeat_keeps_executing() -> None:
    state = _generation_heartbeat_fixture(heartbeat_minutes_ago=1)

    assert state.generation.lifecycle == "running"
    assert state.generation.actionability == "executing"
    assert not any(
        problem.code.endswith("_heartbeat_stale") for problem in state.problems
    )
    assert "retry_generation" not in {
        action.command for action in state.allowedActions if action.kind == "command"
    }
    assert any(
        action.kind == "navigation" and action.actionId == "open-generation-room:candgen-1"
        for action in state.allowedActions
    )


def test_stale_generation_heartbeat_blocks_and_offers_retry() -> None:
    state = _generation_heartbeat_fixture(heartbeat_minutes_ago=30 * 60)

    assert state.generation.lifecycle == "running"
    assert state.generation.actionability == "blocked"
    stale = next(
        problem for problem in state.problems if problem.code == "generation_heartbeat_stale"
    )
    assert stale.category == "stale"
    # The stale verdict is computed from the same durable activity that the
    # phase reports, so the problem timestamp must equal the phase heartbeat.
    assert stale.lastHeartbeatAt == state.generation.updatedAt
    assert stale.recoverable is True
    assert state.currentPhase == "generation"
    retry = next(
        action
        for action in state.allowedActions
        if action.kind == "command" and action.command == "retry_generation"
    )
    assert retry.payload.questionId == "SCI-003"
    assert retry.payload.previousAttemptId == "attempt-1"
    assert retry.expectedStateVersion == state.stateVersion


def test_generation_heartbeat_stale_window_is_tunable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_state_v2 as state_v2,
    )

    monkeypatch.setattr(
        state_v2,
        "_EXECUTION_HEARTBEAT_STALE_AFTER_SECONDS",
        10 * 24 * 3600,
    )
    state = _generation_heartbeat_fixture(heartbeat_minutes_ago=30 * 60)

    assert state.generation.actionability == "executing"
    assert "retry_generation" not in {
        action.command for action in state.allowedActions if action.kind == "command"
    }


def _review_meeting_fixture(*, updated_minutes_ago: float) -> dict[str, object]:
    updated_at = _iso_minute_offset(updated_minutes_ago)
    return HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "hypothesis_candidate",
                    "candidateId": "candidate-1",
                    "questionId": "SCI-001",
                },
                {
                    "recordKind": "review_round_link",
                    "linkId": "link-1",
                    "selectionId": "selection-1",
                    "candidateId": "candidate-1",
                    "candidateOrder": 0,
                    "roundIndex": 1,
                    "meetingRoundId": "review-1",
                    "questionId": "SCI-001",
                },
            ],
            selection_records=[
                {
                    "selectionId": "selection-1",
                    "questionId": "SCI-001",
                    "selectedCandidateIds": ["candidate-1"],
                }
            ],
            meeting_records=[
                {
                    "meetingRoundId": "review-1",
                    "meetingType": "hypothesis_review",
                    "question": "SCI-001",
                    "selectionId": "selection-1",
                    "status": "open",
                    "linkedChatRoomId": "room-review",
                    "chatRoomRoundIds": ["room-round-review"],
                    "createdAt": _iso_minute_offset(updated_minutes_ago + 5),
                    "updatedAt": updated_at,
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            chat_room_round_snapshots={
                "room-round-review": {
                    "runId": "room-round-review",
                    "runKind": "chat_room_round",
                    "status": "running",
                    "updatedAt": updated_at,
                }
            },
        )
    )


def test_stale_review_meeting_blocks_candidate_and_offers_reopen() -> None:
    state = _review_meeting_fixture(updated_minutes_ago=30 * 60)

    candidate = state.review.candidates[0]
    assert candidate.lifecycle == "running"
    assert candidate.actionability == "blocked"
    assert candidate.discussion.actionability == "blocked"
    assert state.review.actionability == "blocked"
    stale = next(
        problem
        for problem in state.problems
        if problem.code == "review_heartbeat_stale"
    )
    assert stale.category == "stale"
    assert stale.lastHeartbeatAt == candidate.updatedAt
    assert state.currentPhase == "review"
    commands = {
        action.command for action in state.allowedActions if action.kind == "command"
    }
    assert "reopen_review" in commands
    assert "resume_discussion" not in commands
    assert "retry_review_dispatch" not in commands


def test_fresh_review_heartbeat_keeps_executing() -> None:
    state = _review_meeting_fixture(updated_minutes_ago=2)

    assert state.review.candidates[0].actionability == "executing"
    assert state.review.actionability == "waiting_system"
    assert not any(
        problem.code.endswith("_heartbeat_stale") for problem in state.problems
    )
    assert "reopen_review" not in {
        action.command for action in state.allowedActions if action.kind == "command"
    }


def test_stale_review_dispatch_intent_offers_retry_dispatch() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "hypothesis_candidate",
                    "candidateId": "candidate-1",
                    "questionId": "SCI-001",
                },
                {
                    "recordKind": "review_dispatch_attempt",
                    "attemptId": "dispatch-1",
                    "attemptNumber": 1,
                    "selectionId": "selection-1",
                    "candidateId": "candidate-1",
                    "roundIndex": 1,
                    "questionId": "SCI-001",
                    "lifecycle": "running",
                    "createdAt": _iso_minute_offset(30 * 60 + 5),
                    "updatedAt": _iso_minute_offset(30 * 60),
                },
            ],
            selection_records=[
                {
                    "selectionId": "selection-1",
                    "questionId": "SCI-001",
                    "selectedCandidateIds": ["candidate-1"],
                }
            ],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
        )
    )

    candidate = state.review.candidates[0]
    assert candidate.lifecycle == "queued"
    assert candidate.actionability == "blocked"
    stale = next(
        problem
        for problem in state.problems
        if problem.code == "review_dispatch_heartbeat_stale"
    )
    assert stale.sourceId == "dispatch-1"
    assert stale.lastHeartbeatAt == candidate.updatedAt
    assert state.currentPhase == "review"
    retry = next(
        action
        for action in state.allowedActions
        if action.kind == "command" and action.command == "retry_review_dispatch"
    )
    assert retry.payload.selectionId == "selection-1"
    assert retry.payload.candidateIds == ["candidate-1"]


def test_v2_retry_generation_command_opens_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_service
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain,
        hypothesis_first_state_v2,
    )

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hypothesis_first_chain, "PROJECT_ROOT", tmp_path)
    snapshot = {
        "stateVersion": "hf2-action:stale-generation",
        "allowedActions": [
            {
                "kind": "command",
                "actionId": "retry-generation",
                "command": "retry_generation",
                "payload": {
                    "questionId": "SCI-003",
                    "previousAttemptId": "attempt-1",
                },
                "enabled": True,
                "idempotencyKey": "hf2:retry-generation:attempt-1",
            }
        ],
    }
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    calls: list[tuple[str, str]] = []

    def open_generation(team_id: str, question_id: str, **_kwargs):
        calls.append((team_id, question_id))
        return {"status": "created", "generationAttemptId": "attempt-2"}

    monkeypatch.setattr(
        hypothesis_first_chain, "open_candidate_generation_meeting", open_generation
    )
    result = hypothesis_first_chain.execute_v2_command(
        "team-1",
        {
            "actionId": "retry-generation",
            "idempotencyKey": "hf2:retry-generation:attempt-1",
            "expectedStateVersion": "hf2-action:stale-generation",
            "command": "retry_generation",
            "payload": {
                "questionId": "SCI-003",
                "previousAttemptId": "attempt-1",
            },
        },
        question_id="SCI-003",
    )

    assert result["result"]["status"] == "created"
    assert calls == [("team-1", "SCI-003")]


def test_v2_stage_one_generation_opens_formal_grounded_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_service
    from core.web.services.team_workflow import research_project_hypothesis_context
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain,
        hypothesis_first_state_v2,
    )
    from core.web.services.team_workflow.research_runtime import (
        meeting_receipt_authority,
    )

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hypothesis_first_chain, "PROJECT_ROOT", tmp_path)
    snapshot = {
        "stateVersion": "hf2-action:stage-one-generation",
        "allowedActions": [
            {
                "kind": "command",
                "actionId": "open-stage-one-generation",
                "command": "open_generation",
                "payload": {"questionId": "SCI-091"},
                "enabled": True,
                "idempotencyKey": "hf2:open-stage-one-generation",
            }
        ],
    }
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    context = {
        "status": "ready",
        "allowedEvidenceRefs": ["evidence:accepted-1"],
        "evidenceClaims": [
            {"sourceRef": "evidence:accepted-1", "claim": "accepted claim"}
        ],
        "knowledgePackage": {"sourceArtifactIds": ["knowledge_package:pkg-1"]},
    }
    monkeypatch.setattr(
        research_project_hypothesis_context,
        "build_stage_one_grounded_generation_context",
        lambda *_args, **_kwargs: context,
    )
    monkeypatch.setattr(
        meeting_receipt_authority,
        "resolve_active_question_authority",
        lambda *_args, **_kwargs: {
            "workflowRunId": "run-stage-one",
            "sourceCollectionRunId": "source-stage-one",
        },
    )
    monkeypatch.setattr(
        hypothesis_first_chain,
        "_question_research_project",
        lambda *_args, **_kwargs: {"projectId": "project-stage-one"},
    )
    captured: dict[str, object] = {}

    def open_generation(_team_id: str, _question_id: str, **kwargs):
        captured.update(kwargs)
        return {"status": "created", "generationAttemptId": "attempt-r1"}

    monkeypatch.setattr(
        hypothesis_first_chain, "open_candidate_generation_meeting", open_generation
    )
    result = hypothesis_first_chain.execute_v2_command(
        "team-1",
        {
            "actionId": "open-stage-one-generation",
            "idempotencyKey": "hf2:open-stage-one-generation",
            "expectedStateVersion": "hf2-action:stage-one-generation",
            "command": "open_generation",
            "payload": {"questionId": "SCI-091"},
        },
        question_id="SCI-091",
        workflow_run_id="run-stage-one",
    )

    assert result["result"]["status"] == "created"
    assert captured["_candidate_authority"] == "formal_grounded_candidate"
    assert captured["_generation_context"] == context


def test_collection_failed_and_completed_states_expose_retry_and_handoff() -> None:
    running = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "collection_request",
                    "requestId": "request-running",
                    "questionId": "SCI-001",
                    "status": "pending",
                    "collectionRunId": "child-running",
                    "collectionRunStatus": "running",
                    "searchEnvelope": {"keywords": ["water"]},
                }
            ],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
        )
    )
    stop = next(
        action
        for action in running.allowedActions
        if action.kind == "command" and action.command == "stop_collection"
    )
    assert stop.payload.requestId == "request-running"
    assert stop.requiresConfirmation is True

    needs_continue = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "collection_request",
                    "requestId": "request-needs-continue",
                    "questionId": "SCI-001",
                    "status": "pending",
                    "collectionRunId": "child-needs-continue",
                    "collectionRunStatus": "needs_continue",
                    "searchEnvelope": {"keywords": ["water"]},
                }
            ],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
        )
    )
    assert needs_continue.currentPhase == "collection"
    assert needs_continue.collection.lifecycle == "running"
    assert needs_continue.collection.actionability == "blocked"
    assert needs_continue.collection.requests[0].lifecycle == "failed"
    assert needs_continue.collection.requests[0].actionability == "blocked"
    assert needs_continue.collection.problems[0].code == "collection_run_needs_continue"
    continuation = next(
        action
        for action in needs_continue.allowedActions
        if action.kind == "command" and action.command == "continue_collection"
    )
    assert continuation.payload.requestId == "request-needs-continue"
    assert continuation.payload.childRunId == "child-needs-continue"

    failed = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "collection_request",
                    "requestId": "request-failed",
                    "questionId": "SCI-001",
                    "status": "active",
                    "collectionRunId": "child-failed",
                    "collectionRunStatus": "failed",
                    "searchEnvelope": {"keywords": ["water"]},
                }
            ],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
        )
    )
    assert any(
        action.kind == "command"
        and action.command == "retry_collection"
        and action.payload.requestId == "request-failed"
        for action in failed.allowedActions
    )

    completed = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "collection_request",
                    "requestId": "request-completed",
                    "questionId": "SCI-001",
                    "status": "active",
                    "collectionRunId": "child-completed",
                    "collectionRunStatus": "succeeded",
                    "searchEnvelope": {"keywords": ["water"]},
                }
            ],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
        )
    )
    assert any(
        action.kind == "command"
        and action.command == "handoff_collection"
        and action.payload.requestId == "request-completed"
        for action in completed.allowedActions
    )


def _collection_request_chain_record(
    request_id: str,
    *,
    run_id: str,
    status: str = "pending",
    collection_run_status: str = "running",
) -> dict[str, object]:
    return {
        "recordKind": "collection_request",
        "requestId": request_id,
        "questionId": "SCI-001",
        "status": status,
        "collectionRunId": run_id,
        "collectionRunStatus": collection_run_status,
        "searchEnvelope": {"keywords": ["water"]},
    }


def _collection_source_fact(**overrides: object) -> dict[str, object]:
    fact: dict[str, object] = {
        "lifecycle": "completed",
        "outcome": "succeeded",
        "actionability": "terminal",
        "attempt": None,
        "updatedAt": "2026-08-26T10:00:07Z",
        "problems": [],
        "sourceId": "q1",
        "label": "alpha transformers",
        "itemCount": 2,
        "error": None,
    }
    fact.update(overrides)
    return fact


def _collection_search_failed_error() -> dict[str, object]:
    return {
        "code": "collection_source_search_failed",
        "category": "execution",
        "severity": "warning",
        "message": "Crossref HTTP 503",
        "recoverable": True,
        "sourceKind": "collection_source",
        "sourceId": "q2",
        "detectedAt": "2026-08-26T10:01:00Z",
    }


def test_collection_request_projects_real_per_source_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_state_v2 as state_module,
    )

    requested_team_ids: list[str] = []

    def fake_loader(team_id: str, run_ids: list[str]) -> dict[str, list[dict[str, object]]]:
        requested_team_ids.append(team_id)
        return {
            "child-running": [
                _collection_source_fact(),
                _collection_source_fact(
                    lifecycle="failed",
                    outcome="none",
                    actionability="available",
                    updatedAt="2026-08-26T10:01:00Z",
                    sourceId="q2",
                    label="beta cortex",
                    itemCount=0,
                    error=_collection_search_failed_error(),
                ),
            ]
        }

    monkeypatch.setattr(state_module, "_load_collection_source_facts", fake_loader)

    snapshot = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[_collection_request_chain_record("request-1", run_id="child-running")],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
        )
    )

    request_state = snapshot.collection.requests[0]
    assert [source.sourceId for source in request_state.sources] == ["q1", "q2"]
    first, failed_source = request_state.sources
    assert first.label == "alpha transformers"
    assert first.itemCount == 2
    assert first.lifecycle == "completed"
    assert first.outcome == "succeeded"
    assert first.actionability == "terminal"
    assert first.error is None
    assert failed_source.itemCount == 0
    assert failed_source.error is not None
    assert failed_source.error.code == "collection_source_search_failed"
    assert failed_source.error.sourceId == "q2"
    # Per-source progress stays telemetry: the request keeps its own phase.
    assert request_state.lifecycle == "running"
    # A source failure never replaces the child-run signal.
    assert request_state.childRun.runId == "child-running"
    # Loader receives the run ids referenced by durable requests only once per read.
    assert requested_team_ids == ["team-1"] * len(requested_team_ids)


def test_collection_source_states_from_groups_covers_partial_empty_and_retry() -> None:
    from core.web.services.team_workflow.research_runtime.hypothesis_first_state_v2 import (
        _collection_source_states_from_events,
    )

    events: list[dict[str, object]] = [
        {
            "eventId": "e1",
            "eventType": "search.failed",
            "status": "blocked",
            "queryId": "q-retry",
            "query": "beta cortex",
            "summary": "provider timeout",
            "createdAt": "2026-08-26T09:00:00Z",
        },
        {
            "eventId": "e2",
            "eventType": "search.executed",
            "status": "returned",
            "queryId": "q-empty",
            "query": "gamma empty",
            "createdAt": "2026-08-26T09:30:00Z",
        },
        {
            "eventId": "e3",
            "eventType": "search.executed",
            "status": "completed",
            "queryId": "q-retry",
            "query": "beta cortex",
            "createdAt": "2026-08-26T10:00:00Z",
        },
        {
            "eventId": "e4",
            "eventType": "storage.data_record_written",
            "status": "completed",
            "queryId": "q-retry",
            "refs": ["rec-1"],
            "createdAt": "2026-08-26T10:00:04Z",
        },
        {
            "eventId": "e5",
            "eventType": "storage.data_record_written",
            "status": "completed",
            "queryId": "q-retry",
            "refs": ["rec-2"],
            "createdAt": "2026-08-26T10:00:05Z",
        },
        {
            "eventId": "e6",
            "eventType": "search.low_quality_rejected",
            "status": "blocked",
            "queryId": "q-retry",
            "title": "Rejected low-quality source",
            "createdAt": "2026-08-26T10:00:06Z",
        },
        {
            "eventId": "e7",
            "eventType": "assignment.no_query",
            "status": "blocked",
            "queryId": "",
            "createdAt": "2026-08-26T10:00:07Z",
        },
    ]

    sources = {source["sourceId"]: source for source in _collection_source_states_from_events(events)}

    # Query order follows durable event order, never dictionary luck.
    assert list(sources) == ["q-retry", "q-empty"]
    retried = sources["q-retry"]
    # A later successful attempt supersedes an earlier failure.
    assert retried["lifecycle"] == "completed"
    assert retried["outcome"] == "succeeded"
    assert retried["actionability"] == "terminal"
    assert retried["error"] is None
    assert retried["itemCount"] == 2
    # updatedAt tracks the newest observation for this source.
    assert retried["updatedAt"] == "2026-08-26T10:00:06Z"

    empty = sources["q-empty"]
    assert empty["lifecycle"] == "completed"
    assert empty["outcome"] == "empty"
    assert empty["itemCount"] == 0


def test_source_progress_is_representation_only_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_state_v2 as state_module,
    )

    chain_records = [_collection_request_chain_record("request-1", run_id="child-running")]

    def projected(facts: dict[str, list[dict[str, object]]]) -> HypothesisFirstStateV2:
        monkeypatch.setattr(
            state_module,
            "_load_collection_source_facts",
            lambda _team_id, _run_ids: facts,
        )
        return HypothesisFirstStateV2.model_validate(
            project_state_from_records(
                team_id="team-1",
                question_id="SCI-001",
                reset_boundary=None,
                chain_records=deepcopy(chain_records),
                selection_records=[],
                meeting_records=[],
                digest_records=[],
                decision_records=[],
                hypothesis_round_records=[],
            )
        )

    before_facts = {
        "child-running": [
            _collection_source_fact(itemCount=2),
            _collection_source_fact(
                lifecycle="failed",
                outcome="none",
                actionability="available",
                sourceId="q2",
                label="beta cortex",
                itemCount=0,
                error=_collection_search_failed_error(),
            ),
        ]
    }
    after_facts = {
        "child-running": [
            _collection_source_fact(itemCount=5),
            # Same identity made progress past its failure during the round.
            _collection_source_fact(
                sourceId="q2",
                label="beta cortex",
                updatedAt="2026-08-26T11:01:00Z",
            ),
        ]
    }

    before = projected(before_facts)
    after = projected(after_facts)

    assert before.representationVersion is not None
    assert before.representationVersion != after.representationVersion
    assert before.stateVersion == after.stateVersion

    # Identical facts stay byte-for-byte stable across replays.
    replayed = projected(before_facts)
    assert replayed.stateVersion == before.stateVersion
    assert replayed.representationVersion == before.representationVersion


def test_collection_source_facts_degrade_without_durable_search_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json as json_module

    from core.web.services.team_workflow.source_collection import (
        residual as sc_residual,
    )

    run_dir = tmp_path / "source_collection_runs" / "child-run-9"
    run_dir.mkdir(parents=True)
    events_path = run_dir / "search_events.jsonl"
    events_path.write_text(
        "\n".join(
            json_module.dumps(event)
            for event in (
                {
                    "eventId": "e1",
                    "eventType": "search.executed",
                    "status": "completed",
                    "queryId": "q1",
                    "query": "alpha transformers",
                    "createdAt": "2026-08-26T10:00:00Z",
                },
                {
                    "eventId": "e2",
                    "eventType": "storage.data_record_written",
                    "status": "completed",
                    "queryId": "q1",
                    "refs": ["rec-1"],
                    "createdAt": "2026-08-26T10:00:02Z",
                },
            )
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sc_residual,
        "_source_collection_storage_artifact_paths",
        lambda team_id, run_id: {"searchEventsPath": tmp_path / "source_collection_runs" / run_id / "search_events.jsonl"},
    )

    def project() -> HypothesisFirstStateV2:
        return HypothesisFirstStateV2.model_validate(
            project_state_from_records(
                team_id="team-1",
                question_id="SCI-001",
                reset_boundary=None,
                chain_records=[
                    _collection_request_chain_record("request-1", run_id="child-run-9")
                ],
                selection_records=[],
                meeting_records=[],
                digest_records=[],
                decision_records=[],
                hypothesis_round_records=[],
            )
        )

    populated = project()
    sources = populated.collection.requests[0].sources
    assert [source.sourceId for source in sources] == ["q1"]
    assert sources[0].label == "alpha transformers"
    assert sources[0].itemCount == 1

    # Missing log: the child simply has no per-source progress yet.
    events_path.unlink()
    degraded = project()
    assert degraded.collection.requests[0].sources == []
    assert degraded.collection.requests[0].childRun.runId == "child-run-9"


def test_scope_cas_rejects_stale_state_version(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain,
        hypothesis_first_state_v2,
    )

    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: {"stateVersion": "hf2-action:actual:new"},
    )

    with pytest.raises(hypothesis_first_chain.StateVersionConflictError) as raised:
        hypothesis_first_chain.assert_expected_state_version(
            "team-1", "SCI-001", "hf2-action:stale:old"
        )

    assert raised.value.code == "state_version_conflict"
    assert raised.value.expected == "hf2-action:stale:old"
    assert raised.value.actual == "hf2-action:actual:new"


def test_active_review_without_selection_context_stays_locked() -> None:
    """A durable review binding must not reopen selection when its record is missing."""

    state = project_state_from_records(
        team_id="team-1",
        question_id="SCI-001",
        reset_boundary=None,
        chain_records=[
            {
                "recordKind": "review_round_link",
                "linkId": "link-a",
                "selectionId": "selection-1",
                "selectionVersion": "selection-version-1",
                "candidateId": "candidate-a",
                "candidateOrder": 0,
                "roundIndex": 1,
                "meetingRoundId": "review-a",
                "questionId": "SCI-001",
            },
            {
                "recordKind": "review_round_link",
                "linkId": "link-b",
                "selectionId": "selection-1",
                "selectionVersion": "selection-version-1",
                "candidateId": "candidate-b",
                "candidateOrder": 1,
                "roundIndex": 1,
                "meetingRoundId": "review-b",
                "questionId": "SCI-001",
            },
        ],
        # Simulate a selection-context read that lost the selection record while
        # the append-only review binding remains durable.
        selection_records=[],
        meeting_records=[
            {
                "meetingRoundId": "review-a",
                "meetingType": "hypothesis_review",
                "question": "SCI-001",
                "status": "open",
                "linkedChatRoomId": "room-a",
                "chatRoomRoundIds": ["room-round-a"],
            },
            {
                "meetingRoundId": "review-b",
                "meetingType": "hypothesis_review",
                "question": "SCI-001",
                "status": "open",
                "linkedChatRoomId": "room-b",
                "chatRoomRoundIds": ["room-round-b"],
            },
        ],
        digest_records=[],
        decision_records=[],
        hypothesis_round_records=[],
    )

    assert state["selection"]["selectionId"] == "selection-1"
    assert state["selection"]["selectedCandidateIds"] == [
        "candidate-a",
        "candidate-b",
    ]
    assert state["review"]["aggregate"]["total"] == 2
    assert not any(
        action.get("command") == "record_selection"
        for action in state["allowedActions"]
        if action.get("kind") == "command"
    )


def test_same_selection_version_with_two_active_bindings_fails_closed() -> None:
    """Conflicting active bindings never reopen a new selection action."""

    state = project_state_from_records(
        team_id="team-1",
        question_id="SCI-001",
        reset_boundary=None,
        chain_records=[
            {
                "recordKind": "review_round_link",
                "linkId": "link-a",
                "selectionId": "selection-1",
                "selectionVersion": "selection-version-1",
                "candidateId": "candidate-a",
                "candidateOrder": 0,
                "roundIndex": 1,
                "meetingRoundId": "review-a",
                "questionId": "SCI-001",
            },
            {
                "recordKind": "review_round_link",
                "linkId": "link-b",
                "selectionId": "selection-2",
                "selectionVersion": "selection-version-1",
                "candidateId": "candidate-a",
                "candidateOrder": 0,
                "roundIndex": 1,
                "meetingRoundId": "review-b",
                "questionId": "SCI-001",
            },
        ],
        selection_records=[],
        meeting_records=[
            {
                "meetingRoundId": "review-a",
                "meetingType": "hypothesis_review",
                "question": "SCI-001",
                "status": "open",
                "linkedChatRoomId": "room-a",
                "chatRoomRoundIds": ["room-round-a"],
            },
            {
                "meetingRoundId": "review-b",
                "meetingType": "hypothesis_review",
                "question": "SCI-001",
                "status": "open",
                "linkedChatRoomId": "room-b",
                "chatRoomRoundIds": ["room-round-b"],
            },
        ],
        digest_records=[],
        decision_records=[],
        hypothesis_round_records=[],
    )

    assert any(
        problem["code"] == "active_review_binding_conflict"
        for problem in state["problems"]
    )
    assert state["review"]["lifecycle"] == "running"
    assert state["review"]["actionability"] == "blocked"
    assert not any(
        action.get("command") == "record_selection"
        for action in state["allowedActions"]
        if action.get("kind") == "command"
    )


def _record_selection_command_request(
    *,
    key: str,
    candidates: list[str],
    expected_state_version: str = "hf2-action:origin:selection",
) -> dict[str, object]:
    return {
        "actionId": "record-selection",
        "idempotencyKey": key,
        "expectedStateVersion": expected_state_version,
        "command": "record_selection",
        "payload": {
            "questionId": "SCI-001",
            "generationAttemptId": "attempt-1",
        },
        "input": {"candidateIds": candidates},
    }


def test_v2_selection_command_replays_original_ids_before_stale_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_service
    from core.web.services.team_workflow import hypothesis_selection
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain,
        hypothesis_first_state_v2,
    )

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hypothesis_first_chain, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        hypothesis_first_chain,
        "_question_scope_envelope",
        lambda *_args: {
            "program": "program",
            "theme": "theme",
            "campaign": "campaign",
            "question": "SCI-001",
            "branch": "main",
            "workflow": "hypothesis_first",
            "agentId": "operator",
            "mode": "dev",
        },
    )
    snapshot = {
        "stateVersion": "hf2-action:origin:selection",
        "resetBoundary": {"resetId": "origin"},
        "allowedActions": [
            {
                "kind": "command",
                "actionId": "record-selection",
                "command": "record_selection",
                "payload": {
                    "questionId": "SCI-001",
                    "generationAttemptId": "attempt-1",
                },
                "enabled": True,
                "idempotencyKey": "selection-command-1",
            }
        ],
    }
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    calls: list[dict[str, object]] = []

    def record_selection(_team_id: str, payload: dict[str, object], **_kwargs):
        calls.append(dict(payload))
        return {
            "status": "created",
            "selection": {
                "selectionId": "selection-1",
                "questionId": "SCI-001",
                "selectedCandidateIds": ["candidate-a", "candidate-b"],
            },
            "reviewMeeting": {
                "status": "opened",
                "meetingRound": {"meetingRoundId": "review-1"},
                "roomId": "room-1",
            },
        }

    monkeypatch.setattr(
        hypothesis_selection,
        "record_hypothesis_selection",
        record_selection,
    )
    first = hypothesis_first_chain.execute_v2_command(
        "team-1",
        _record_selection_command_request(
            key="selection-command-1",
            candidates=[" candidate-b ", "candidate-a"],
        ),
        question_id="SCI-001",
    )
    replayed = hypothesis_first_chain.execute_v2_command(
        "team-1",
        _record_selection_command_request(
            key="selection-command-1",
            candidates=["candidate-a", " candidate-b "],
            expected_state_version="hf2-action:stale:after-selection",
        ),
        question_id="SCI-001",
    )

    assert first["result"]["selection"]["selectionId"] == "selection-1"
    assert replayed["status"] == "reused"
    assert replayed["result"]["selectionId"] == "selection-1"
    assert replayed["result"]["meetingRoundId"] == "review-1"
    assert replayed["result"]["roomId"] == "room-1"
    assert len(calls) == 1
    assert calls[0]["selectedCandidateIds"] == ["candidate-a", "candidate-b"]

    competing_key = hypothesis_first_chain.execute_v2_command(
        "team-1",
        _record_selection_command_request(
            key="selection-command-1-competing-key",
            candidates=["candidate-b", "candidate-a"],
            expected_state_version="hf2-action:stale:after-selection",
        ),
        question_id="SCI-001",
    )
    assert competing_key["status"] == "reused"
    assert competing_key["result"]["selectionId"] == "selection-1"
    assert len(calls) == 1


def test_stage_one_selection_screens_before_persisting_or_opening_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_service
    from core.web.services.team_workflow import hypothesis_selection
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain,
        hypothesis_first_state_v2,
    )

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hypothesis_first_chain, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        hypothesis_first_chain,
        "_question_scope_envelope",
        lambda *_args: {
            "program": "program",
            "theme": "theme",
            "campaign": "campaign",
            "question": "SCI-001",
            "branch": "main",
            "workflow": "hypothesis_first",
            "agentId": "operator",
            "mode": "formal",
        },
    )
    snapshot = {
        "stateVersion": "hf2-action:origin:selection",
        "resetBoundary": {"resetId": "origin"},
        "allowedActions": [
            {
                "kind": "command",
                "actionId": "record-selection",
                "command": "record_selection",
                "payload": {
                    "questionId": "SCI-001",
                    "generationAttemptId": "attempt-1",
                },
                "enabled": True,
                "idempotencyKey": "selection-stage-one",
            }
        ],
    }
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    order: list[str] = []

    def screen(**kwargs):
        order.append("screen")
        assert kwargs["selected_candidate_ids"] == ["cand-a", "cand-b", "cand-c", "cand-d"]
        return {
            "candidateIds": ["cand-b", "cand-c", "cand-d"],
            "artifactRef": "candidate_screening://team-1/run-stage-one/hash",
        }

    def record(_team_id, payload, **_kwargs):
        order.append("record")
        assert payload["selectedCandidateIds"] == ["cand-b", "cand-c", "cand-d"]
        return {
            "status": "created",
            "selection": {
                "selectionId": "selection-stage-one",
                "questionId": "SCI-001",
                "selectedCandidateIds": list(payload["selectedCandidateIds"]),
            },
            "reviewMeeting": {"status": "opened"},
        }

    monkeypatch.setattr(
        hypothesis_first_chain,
        "_screen_stage_one_selection_candidates",
        screen,
    )
    monkeypatch.setattr(hypothesis_selection, "record_hypothesis_selection", record)

    result = hypothesis_first_chain.execute_v2_command(
        "team-1",
        _record_selection_command_request(
            key="selection-stage-one",
            candidates=["cand-d", "cand-c", "cand-b", "cand-a"],
        ),
        question_id="SCI-001",
        workflow_run_id="run-stage-one",
    )

    assert order == ["screen", "record"]
    assert result["result"]["selection"]["selectedCandidateIds"] == [
        "cand-b",
        "cand-c",
        "cand-d",
    ]


def test_stage_one_diversity_collapse_writes_no_selection_or_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_service
    from core.web.services.team_workflow import hypothesis_selection
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain,
        hypothesis_first_state_v2,
    )

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hypothesis_first_chain, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        hypothesis_first_chain,
        "_question_scope_envelope",
        lambda *_args: {"question": "SCI-001"},
    )
    snapshot = {
        "stateVersion": "hf2-action:origin:selection",
        "resetBoundary": {"resetId": "origin"},
        "allowedActions": [
            {
                "kind": "command",
                "actionId": "record-selection",
                "command": "record_selection",
                "payload": {
                    "questionId": "SCI-001",
                    "generationAttemptId": "attempt-1",
                },
                "enabled": True,
                "idempotencyKey": "selection-collapse",
            }
        ],
    }
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    persisted = 0

    def record(*_args, **_kwargs):
        nonlocal persisted
        persisted += 1
        return {}

    def collapse(**_kwargs):
        raise hypothesis_first_chain.StageOneCandidateScreeningError(
            "diversity_collapse",
            artifact_ref="candidate_screening://team-1/run-stage-one/hash",
        )

    monkeypatch.setattr(hypothesis_selection, "record_hypothesis_selection", record)
    monkeypatch.setattr(
        hypothesis_first_chain,
        "_screen_stage_one_selection_candidates",
        collapse,
    )

    with pytest.raises(
        hypothesis_first_chain.StageOneCandidateScreeningError,
        match="diversity_collapse",
    ):
        hypothesis_first_chain.execute_v2_command(
            "team-1",
            _record_selection_command_request(
                key="selection-collapse",
                candidates=["cand-a", "cand-b"],
            ),
            question_id="SCI-001",
            workflow_run_id="run-stage-one",
        )

    assert persisted == 0


def test_v2_selection_command_rejects_same_key_with_different_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services import team_service
    from core.web.services.team_workflow import hypothesis_selection
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain,
        hypothesis_first_state_v2,
    )

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hypothesis_first_chain, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        hypothesis_first_chain,
        "_question_scope_envelope",
        lambda *_args: {"question": "SCI-001"},
    )
    snapshot = {
        "stateVersion": "hf2-action:origin:selection",
        "resetBoundary": {"resetId": "origin"},
        "allowedActions": [
            {
                "kind": "command",
                "actionId": "record-selection",
                "command": "record_selection",
                "payload": {
                    "questionId": "SCI-001",
                    "generationAttemptId": "attempt-1",
                },
                "enabled": True,
                "idempotencyKey": "selection-command-2",
            }
        ],
    }
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    calls = 0

    def record_selection(_team_id: str, payload: dict[str, object], **_kwargs):
        nonlocal calls
        calls += 1
        return {
            "status": "created",
            "selection": {
                "selectionId": "selection-2",
                "questionId": "SCI-001",
                "selectedCandidateIds": list(payload["selectedCandidateIds"]),
            },
            "reviewMeeting": {
                "status": "opened",
                "meetingRound": {"meetingRoundId": "review-2"},
                "roomId": "room-2",
            },
        }

    monkeypatch.setattr(
        hypothesis_selection,
        "record_hypothesis_selection",
        record_selection,
    )
    hypothesis_first_chain.execute_v2_command(
        "team-1",
        _record_selection_command_request(
            key="selection-command-2",
            candidates=["candidate-a", "candidate-b"],
        ),
        question_id="SCI-001",
    )

    with pytest.raises(hypothesis_first_chain.IdempotencyConflictError) as raised:
        hypothesis_first_chain.execute_v2_command(
            "team-1",
            _record_selection_command_request(
                key="selection-command-2",
                candidates=["candidate-a", "candidate-c"],
                expected_state_version="hf2-action:stale:after-selection",
            ),
            question_id="SCI-001",
        )

    assert raised.value.code == "idempotency_conflict"
    assert calls == 1


def test_v2_command_route_maps_idempotency_conflict_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conflict = hypothesis_first_routes.hypothesis_first_chain.IdempotencyConflictError(
        action_id="record-selection",
        idempotency_key="selection-command-3",
        expected_input_digest="digest-a",
        actual_input_digest="digest-b",
    )
    monkeypatch.setattr(
        hypothesis_first_routes.hypothesis_first_chain,
        "execute_v2_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(conflict),
    )
    monkeypatch.setattr(
        hypothesis_first_routes,
        "server_operator_scope_from_http",
        lambda _request: nullcontext(),
    )
    payload = HypothesisFirstCommandRequest.model_validate(
        {
            "actionId": "record-selection",
            "idempotencyKey": "selection-command-3",
            "expectedStateVersion": "hf2-action:origin:selection",
            "payload": {
                "questionId": "SCI-001",
                "generationAttemptId": "attempt-1",
            },
            "input": {"candidateIds": ["candidate-a", "candidate-b"]},
        }
    )

    with pytest.raises(HTTPException) as raised:
        hypothesis_first_routes.team_workflow_hypothesis_first_command(
            "team-1",
            payload,
            Request({"type": "http", "method": "POST", "path": "/"}),
            question_id="SCI-001",
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "idempotency_conflict"


def test_v2_scope_lock_serializes_cross_process_claim_and_side_effect(
    tmp_path: Path,
) -> None:
    """Two workers sharing one old snapshot may enter a V2 side effect once."""

    root = str(Path(__file__).resolve().parents[1])
    claim = tmp_path / "claim.txt"
    active = tmp_path / "side-effect-active.txt"
    overlap = tmp_path / "side-effect-overlap.txt"
    start = tmp_path / "start.txt"
    worker_script = f"""
import sys
import time
from pathlib import Path

sys.path.insert(0, {root!r})
from core.web.services.team_workflow.research_runtime import hypothesis_first_chain as chain
from core.web.services import team_service
from core.web.services.team_workflow.research_runtime import hypothesis_first_state_v2

chain.PROJECT_ROOT = Path({str(tmp_path)!r})
claim = Path({str(claim)!r})
active = Path({str(active)!r})
overlap = Path({str(overlap)!r})
start = Path({str(start)!r})
result = Path(sys.argv[1])
ready = result.with_suffix(".ready")
team_service.assert_team_exists = lambda team_id: team_id
hypothesis_first_state_v2.project_hypothesis_first_state_v2 = lambda *_args, **_kwargs: {{
    "stateVersion": "hf2-action:old-snapshot",
    "allowedActions": [{{
        "kind": "command",
        "actionId": "retry-program-handoff",
        "command": "retry_program_handoff",
        "payload": {{"runId": "run-1"}},
        "enabled": True,
        "idempotencyKey": "hf2:retry-program-handoff:old-snapshot",
    }}],
}}
def fake_retry(_team_id, *, run_id, idempotency_key):
    assert run_id == "run-1"
    assert idempotency_key == "hf2:retry-program-handoff:old-snapshot"
    if claim.exists():
        return {{"status": "reused"}}
    if active.exists():
        overlap.write_text("overlap", encoding="utf-8")
        return {{"status": "overlap"}}
    active.write_text("active", encoding="utf-8")
    try:
        # Hold the protected side-effect window open long enough that a
        # concurrently released worker would observe ``active`` without the
        # inter-process scope lock.
        time.sleep(0.5)
        claim.write_text("claimed", encoding="utf-8")
        return {{"status": "created"}}
    finally:
        active.unlink(missing_ok=True)
chain._retry_program_delivery = fake_retry
ready.write_text("ready", encoding="utf-8")
while not start.exists():
    time.sleep(0.01)
response = chain.execute_v2_command(
    "team-1",
    {{
        "actionId": "retry-program-handoff",
        "idempotencyKey": "hf2:retry-program-handoff:old-snapshot",
        "expectedStateVersion": "hf2-action:old-snapshot",
        "command": "retry_program_handoff",
        "payload": {{"runId": "run-1"}},
    }},
    question_id="SCI-001",
)
result.write_text(str(response["result"]["status"]), encoding="utf-8")
"""

    result_paths = [tmp_path / f"result-{index}.txt" for index in range(2)]
    with managed_processes() as workers:
        workers.extend(
            subprocess.Popen(
                [sys.executable, "-c", worker_script, str(result_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            for result_path in result_paths
        )
        ready_paths = [path.with_suffix(".ready") for path in result_paths]
        deadline = time.monotonic() + 10
        while not all(path.exists() for path in ready_paths):
            assert time.monotonic() < deadline, "workers did not reach the start barrier"
            time.sleep(0.01)
        start.write_text("start", encoding="utf-8")
        for worker in workers:
            _, stderr = worker.communicate(timeout=30)
            assert worker.returncode == 0, stderr.decode("utf-8", "replace")

    outcomes = [path.read_text(encoding="utf-8") for path in result_paths]
    assert outcomes.count("created") == 1
    assert outcomes.count("reused") == 1
    assert not overlap.exists()


def test_v2_command_route_maps_stale_version_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conflict = hypothesis_first_routes.hypothesis_first_chain.StateVersionConflictError(
        expected="hf2-action:stale:old",
        actual="hf2-action:actual:new",
        snapshot_path="/teams/team-1/workflow-orchestration/hypothesis-first/chain/state-v2?questionId=SCI-001",
    )
    monkeypatch.setattr(
        hypothesis_first_routes.hypothesis_first_chain,
        "execute_v2_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(conflict),
    )
    monkeypatch.setattr(
        hypothesis_first_routes,
        "server_operator_scope_from_http",
        lambda _request: nullcontext(),
    )
    payload = HypothesisFirstCommandRequest.model_validate(
        {
            "actionId": "open-generation",
            "idempotencyKey": "hf2:open-generation:test",
            "expectedStateVersion": "hf2-action:stale:old",
            "payload": {"questionId": "SCI-001"},
        }
    )

    with pytest.raises(HTTPException) as raised:
        hypothesis_first_routes.team_workflow_hypothesis_first_command(
            "team-1",
            payload,
            Request({"type": "http", "method": "POST", "path": "/"}),
            question_id="SCI-001",
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "state_version_conflict"
    assert raised.value.detail["actualStateVersion"] == "hf2-action:actual:new"


def test_v2_command_route_maps_invalid_control_auth_to_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(_request):
        raise PermissionError("command_forbidden")

    monkeypatch.setattr(
        hypothesis_first_routes,
        "server_operator_scope_from_http",
        forbidden,
    )
    payload = HypothesisFirstCommandRequest.model_validate(
        {
            "actionId": "open-generation",
            "idempotencyKey": "hf2:open-generation:test",
            "expectedStateVersion": "hf2-action:origin:test",
            "payload": {"questionId": "SCI-001"},
        }
    )

    with pytest.raises(HTTPException) as raised:
        hypothesis_first_routes.team_workflow_hypothesis_first_command(
            "team-1",
            payload,
            Request({"type": "http", "method": "POST", "path": "/"}),
            question_id="SCI-001",
        )

    assert raised.value.status_code == 403
    assert raised.value.detail["code"] == "command_forbidden"


def test_command_request_keeps_handoff_payload_identity() -> None:
    request = HypothesisFirstCommandRequest.model_validate(
        {
            "actionId": "handoff-collection:request-1",
            "idempotencyKey": "hf2:handoff-collection:request-1",
            "expectedStateVersion": "hf2-action:origin:test",
            "payload": {"requestId": "request-1", "childRunId": "child-1"},
        }
    )

    assert type(request.payload) is CollectionChildRunPayload


def test_production_projector_reads_formal_and_program_authorities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_module = hypothesis_first_routes.hypothesis_first_state_v2
    monkeypatch.setattr(
        "core.web.services.team_service.assert_team_exists",
        lambda team_id: team_id,
    )
    monkeypatch.setattr(
        state_module.hypothesis_first_chain,
        "_question_reset_snapshot",
        lambda *_args: {
            "targetMeetingIds": [],
            "targetRoundIds": [],
            "chainRecords": [],
            "selectionRecords": [],
            "meetingRecords": [],
            "digestRecords": [],
            "decisionRecords": [],
            "hypothesisRoundRecords": [],
        },
    )

    class QueryService:
        def list_runs(self, **_kwargs):
            return {
                "runs": [
                    {
                        "runId": "run-1",
                        "teamId": "team-1",
                        "questionId": "SCI-001",
                        "status": "succeeded",
                        "runVersion": 2,
                    }
                ]
            }

        def get_snapshot(self, **_kwargs):
            return {
                "deliveryStatus": "succeeded",
                "artifactSummary": {
                    "finalArtifactLocator": "artifact://delivery/run-1"
                },
            }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.formal_read_runtime.get_query_service",
        lambda: QueryService(),
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.challenge_question_runs.get_challenge_question_run_detail",
        lambda *_args, **_kwargs: {
            "record": {
                "recordId": "SCI-001:run-1",
                "questionId": "SCI-001",
                "runId": "run-1",
                "humanGates": {
                    "decisions": {
                        "H1_problem_understanding": "pending",
                        "H2_hypothesis_selection": "pending",
                        "H3_research_plan": "pending",
                        "H4_external_output": "pending",
                    }
                },
            }
        },
    )

    state = HypothesisFirstStateV2.model_validate(
        state_module.project_hypothesis_first_state_v2("team-1", "SCI-001")
    )

    assert state.formalRuntime.runId == "run-1"
    assert state.currentPhase == "program_delivery"
    assert state.programDelivery.outputRunId == "run-1"


def test_scope_records_keeps_question_boundary_without_run_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy question reads remain question-scoped while run scope is optional."""

    state_module = hypothesis_first_routes.hypothesis_first_state_v2
    state_module.clear_hypothesis_first_state_v2_cache()
    monkeypatch.setattr(
        state_module.hypothesis_first_chain,
        "_question_reset_snapshot",
        lambda *_args: {
            "targetMeetingIds": {"meeting-target"},
            "targetRoundIds": {"round-target"},
            "chainRecords": [],
            "selectionRecords": [],
            "meetingRecords": [
                {"meetingRoundId": "meeting-target"},
                {"meetingRoundId": "meeting-other"},
            ],
            "digestRecords": [],
            "decisionRecords": [],
            "hypothesisRoundRecords": [
                {"roundId": "round-target"},
                {"roundId": "round-other"},
            ],
        },
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.formal_read_runtime.get_query_service",
        lambda: type(
            "QueryService",
            (),
            {"list_runs": lambda self, **_kwargs: {"runs": []}},
        )(),
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.challenge_question_runs.get_challenge_question_run_detail",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("challenge_question_run_not_found")
        ),
    )

    sources = state_module._scope_records("team-question-scope", "SCI-001")

    assert [item["meetingRoundId"] for item in sources["meeting_records"]] == [
        "meeting-target"
    ]
    assert [item["roundId"] for item in sources["hypothesis_round_records"]] == [
        "round-target"
    ]
    state_module.clear_hypothesis_first_state_v2_cache()


def test_production_projector_reads_bound_chat_round_work_run_without_room_reconcile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_module = hypothesis_first_routes.hypothesis_first_state_v2
    state_module.clear_hypothesis_first_state_v2_cache()
    monkeypatch.setattr(
        "core.web.services.team_service.assert_team_exists",
        lambda team_id: team_id,
    )
    monkeypatch.setattr(
        state_module.hypothesis_first_chain,
        "_question_reset_snapshot",
        lambda *_args: {
            "targetMeetingIds": {"review-1"},
            "targetRoundIds": set(),
            "chainRecords": [
                {
                    "recordKind": "hypothesis_candidate",
                    "candidateId": "candidate-1",
                    "questionId": "SCI-001",
                },
                {
                    "recordKind": "review_round_link",
                    "linkId": "link-1",
                    "selectionId": "selection-1",
                    "candidateId": "candidate-1",
                    "candidateOrder": 0,
                    "roundIndex": 1,
                    "meetingRoundId": "review-1",
                    "questionId": "SCI-001",
                },
            ],
            "selectionRecords": [
                {
                    "selectionId": "selection-1",
                    "questionId": "SCI-001",
                    "selectedCandidateIds": ["candidate-1"],
                }
            ],
            "meetingRecords": [
                {
                    "meetingRoundId": "review-1",
                    "meetingType": "hypothesis_review",
                    "question": "SCI-001",
                    "selectionId": "selection-1",
                    "status": "open",
                    "linkedChatRoomId": "room-review",
                    "chatRoomRoundIds": ["room-round-1"],
                }
            ],
            "digestRecords": [],
            "decisionRecords": [],
            "hypothesisRoundRecords": [],
        },
    )

    loaded: list[str] = []

    def load_chat_round_snapshot(round_id: str) -> dict[str, object]:
        loaded.append(round_id)
        return {
            "runId": round_id,
            "runKind": "chat_room_round",
            "status": "stopped",
            "currentPhase": "stopped",
            "runtimeStatus": "orphan_reconciled",
            "reconciliationSource": "missing_process_controller",
            "summary": "后端进程已重启，已收口没有当前进程控制器的群聊轮次。",
            "finishedAt": "2026-08-26T02:17:41Z",
        }

    monkeypatch.setattr(
        state_module,
        "_load_chat_room_round_snapshot",
        load_chat_round_snapshot,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.formal_read_runtime.get_query_service",
        lambda: type(
            "QueryService",
            (),
            {"list_runs": lambda self, **_kwargs: {"runs": []}},
        )(),
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.challenge_question_runs.get_challenge_question_run_detail",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("challenge_question_run_not_found")
        ),
    )

    state = HypothesisFirstStateV2.model_validate(
        state_module.project_hypothesis_first_state_v2("team-1", "SCI-001")
    )

    assert loaded == ["room-round-1"]
    assert state.review.lifecycle == "failed"
    assert state.review.actionability == "blocked"
    assert state.review.candidates[0].discussion.actionability == "blocked"
    assert any(
        problem.code == "discussion_round_orphaned" for problem in state.problems
    )
    state_module.clear_hypothesis_first_state_v2_cache()


def test_production_projector_reads_all_bound_rounds_for_summarizing_meeting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_module = hypothesis_first_routes.hypothesis_first_state_v2
    state_module.clear_hypothesis_first_state_v2_cache()
    monkeypatch.setattr(
        "core.web.services.team_service.assert_team_exists",
        lambda team_id: team_id,
    )
    monkeypatch.setattr(
        state_module.hypothesis_first_chain,
        "_question_reset_snapshot",
        lambda *_args: {
            "targetMeetingIds": {"generation-1"},
            "targetRoundIds": set(),
            "chainRecords": [],
            "selectionRecords": [],
            "meetingRecords": [
                {
                    "meetingRoundId": "generation-1",
                    "meetingType": "hypothesis_candidate_generation",
                    "question": "SCI-002",
                    "status": "summarizing",
                    "linkedChatRoomId": "room-generation",
                    "chatRoomRoundIds": ["round-old", "round-current"],
                }
            ],
            "digestRecords": [],
            "decisionRecords": [],
            "hypothesisRoundRecords": [],
        },
    )
    loaded: list[str] = []

    def load_chat_round_snapshot(round_id: str) -> dict[str, object]:
        loaded.append(round_id)
        return {
            "runId": round_id,
            "runKind": "chat_room_round",
            "status": "completed",
        }

    monkeypatch.setattr(
        state_module,
        "_load_chat_room_round_snapshot",
        load_chat_round_snapshot,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.formal_read_runtime.get_query_service",
        lambda: type(
            "QueryService",
            (),
            {"list_runs": lambda self, **_kwargs: {"runs": []}},
        )(),
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.challenge_question_runs.get_challenge_question_run_detail",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("challenge_question_run_not_found")
        ),
    )

    sources = state_module._scope_records("team-1", "SCI-002")

    assert set(loaded) == {"round-old", "round-current"}
    assert set(sources["chat_room_round_snapshots"]) == {
        "round-old",
        "round-current",
    }
    state_module.clear_hypothesis_first_state_v2_cache()


def test_v2_route_maps_unavailable_authority_to_structured_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_module = hypothesis_first_routes.hypothesis_first_state_v2

    def unavailable(*_args, **_kwargs):
        raise state_module.HypothesisFirstStateSourceError("formal ledger unavailable")

    monkeypatch.setattr(state_module, "project_hypothesis_first_state_v2", unavailable)

    with pytest.raises(HTTPException) as raised:
        hypothesis_first_routes.team_workflow_hypothesis_first_chain_state_v2(
            "team-1",
            Response(),
            question_id="SCI-001",
            if_none_match=None,
            include_source_cursor=False,
        )

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "state_source_unavailable"


def test_telemetry_changes_representation_version_without_changing_state_version() -> None:
    first = _initial_snapshot()
    first["computedAt"] = "2026-08-25T00:00:00Z"
    second = deepcopy(first)
    second["computedAt"] = "2026-08-25T00:00:05Z"
    second["generation"]["updatedAt"] = "2026-08-25T00:00:05Z"

    first_versioned = finalize_state_versions(first, reset_id="origin")
    second_versioned = finalize_state_versions(second, reset_id="origin")

    assert first_versioned["stateVersion"] == second_versioned["stateVersion"]
    assert (
        first_versioned["representationVersion"]
        != second_versioned["representationVersion"]
    )


def test_question_source_replay_cache_is_bound_to_durable_file_cursors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_module = hypothesis_first_routes.hypothesis_first_state_v2
    state_module.clear_hypothesis_first_state_v2_cache()
    signature = [("chain.jsonl", 10, 100)]
    reads = 0

    def read_snapshot(*_args):
        nonlocal reads
        reads += 1
        return {
            "chainRecords": [
                {
                    "recordKind": "hypothesis_candidate",
                    "questionId": f"SCI-{index + 100:03d}",
                    "candidateId": f"unrelated-{index}",
                }
                for index in range(10_000)
            ]
            + [
                {
                    "recordKind": "hypothesis_candidate",
                    "questionId": "SCI-001",
                    "candidateId": f"candidate-{reads}",
                }
            ],
            "selectionRecords": [],
            "meetingRecords": [],
            "digestRecords": [],
            "decisionRecords": [],
            "hypothesisRoundRecords": [],
            "targetMeetingIds": set(),
            "targetRoundIds": set(),
        }

    monkeypatch.setattr(
        state_module,
        "_question_snapshot_signature",
        lambda _team_id: tuple(signature),
    )
    monkeypatch.setattr(
        state_module.hypothesis_first_chain,
        "_question_reset_snapshot",
        read_snapshot,
    )

    first = state_module._cached_question_reset_snapshot("team-1", "SCI-001")
    first["chainRecords"].append({"mutated": True})
    second = state_module._cached_question_reset_snapshot("team-1", "SCI-001")
    assert reads == 1
    assert second["chainRecords"] == [
        {
            "recordKind": "hypothesis_candidate",
            "questionId": "SCI-001",
            "candidateId": "candidate-1",
        }
    ]

    signature[0] = ("chain.jsonl", 11, 101)
    third = state_module._cached_question_reset_snapshot("team-1", "SCI-001")
    assert reads == 2
    assert third["chainRecords"][0]["candidateId"] == "candidate-2"
    state_module.clear_hypothesis_first_state_v2_cache()


def test_v2_route_uses_representation_version_for_etag(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = finalize_state_versions(_initial_snapshot(), reset_id="origin")
    monkeypatch.setattr(
        hypothesis_first_routes.hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    response = Response()

    result = hypothesis_first_routes.team_workflow_hypothesis_first_chain_state_v2(
        "team-1",
        response,
        question_id="SCI-001",
        if_none_match=None,
        include_source_cursor=False,
    )

    assert result == snapshot
    assert response.headers["etag"] == f'"{snapshot["representationVersion"]}"'

    not_modified = hypothesis_first_routes.team_workflow_hypothesis_first_chain_state_v2(
        "team-1",
        Response(),
        question_id="SCI-001",
        if_none_match=f'"{snapshot["representationVersion"]}"',
        include_source_cursor=False,
    )
    assert isinstance(not_modified, Response)
    assert not_modified.status_code == 304


def test_v2_diagnostic_route_is_no_store_and_never_returns_304(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = finalize_state_versions(_initial_snapshot(), reset_id="origin")
    snapshot["sourceCursor"] = {"chain": "cursor-1"}
    monkeypatch.setattr(
        hypothesis_first_routes.hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    response = Response()

    result = hypothesis_first_routes.team_workflow_hypothesis_first_chain_state_v2(
        "team-1",
        response,
        question_id="SCI-001",
        if_none_match=f'"{snapshot["representationVersion"]}"',
        include_source_cursor=True,
    )

    assert result == snapshot
    assert response.headers["cache-control"] == "no-store"
    assert "etag" not in response.headers


def test_generation_attempt_does_not_hide_awaiting_human_meeting() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "generation_attempt",
                    "attemptId": "attempt-1",
                    "attemptNumber": 1,
                    "questionId": "SCI-001",
                    "meetingRoundId": "generation-1",
                    "lifecycle": "running",
                    "outcome": "none",
                }
            ],
            selection_records=[],
            meeting_records=[
                {
                    "meetingRoundId": "generation-1",
                    "meetingType": "hypothesis_candidate_generation",
                    "question": "SCI-001",
                    "status": "awaiting_approval",
                    "linkedChatRoomId": "room-generation",
                    "digestDraft": {"contentHash": "digest-hash"},
                }
            ],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
        )
    )

    assert state.generation.lifecycle == "waiting_human"
    assert state.generation.actionability == "waiting_user"


def test_reset_audit_without_business_facts_is_initial() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary={
                "resetId": "reset-1",
                "resetAt": "2026-08-25T00:00:00Z",
            },
            chain_records=[
                {
                    "recordKind": "question_reset_audit",
                    "questionId": "SCI-001",
                    "resetId": "reset-1",
                }
            ],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
        )
    )

    assert state.isInitial is True
    assert state.currentPhase == "generation"


def test_program_delivery_needs_context_exposes_only_retry_handoff() -> None:
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
            formal_runs=[
                {
                    "runId": "run-1",
                    "teamId": "team-1",
                    "questionId": "SCI-001",
                    "status": "succeeded",
                    "runVersion": 1,
                }
            ],
            formal_snapshots={
                "run-1": {
                    "deliveryStatus": "blocked",
                    "artifactSummary": {
                        "finalArtifactLocator": "artifact://delivery/run-1"
                    },
                    "programCandidateHandoff": {"status": "NEEDS_CONTEXT"},
                }
            },
        )
    )

    assert state.currentPhase == "program_delivery"
    assert state.programDelivery.deliveryStatus == "blocked"
    assert state.programDelivery.handoffStatus == "needs_context"
    commands = {
        action.command
        for action in state.allowedActions
        if action.kind == "command"
    }
    assert commands == {"retry_program_handoff"}
    assert "open_generation" not in commands


# ---------------------------------------------------------------------------
# SCI-096 route-layer fixes
# ---------------------------------------------------------------------------


def _command_request_body(**overrides) -> dict[str, Any]:
    body: dict[str, Any] = {
        "actionId": "open-generation",
        "idempotencyKey": "hf2:team-1:SCI-001:open-generation",
        "expectedStateVersion": "hf2-action:origin:action-hash",
        "payload": {"questionId": "SCI-001"},
    }
    body.update(overrides)
    return body


def test_command_request_accepts_omitted_input() -> None:
    request = HypothesisFirstCommandRequest.model_validate(_command_request_body())
    assert request.input is None


def test_command_request_treats_empty_input_object_as_omitted() -> None:
    """``input: {}`` must behave like an omitted input, not a 422.

    Generic clients send an empty object for actions that take no
    declaration input; every ActionInput variant has required fields, so the
    empty object can never match the strict union and must be normalized to
    ``None`` (SCI-096 UX finding, 2026-08-28).
    """

    request = HypothesisFirstCommandRequest.model_validate(
        _command_request_body(input={})
    )
    assert request.input is None

    # A non-empty declaration input keeps validating against its variant.
    approve = HypothesisFirstCommandRequest.model_validate(
        _command_request_body(
            actionId="approve-summary:review-1",
            idempotencyKey="hf2:team-1:SCI-001:approve-summary",
            payload={"meetingRoundId": "review-1"},
            input={"decision": "accepted"},
        )
    )
    assert approve.input is not None
    assert approve.input.decision == "accepted"


def test_route_maps_chat_room_busy_error_to_conflict() -> None:
    """A busy linked chat room on a V2 retry path is 409, never a 500.

    ``retry_generation`` / ``resume_discussion`` / ``reopen_review`` restart
    room rounds; when the room already runs one, the service raises
    ``ChatRoomBusyError`` which previously escaped the route as HTTP 500.
    """

    from core.web.services import chat_room_service

    assert chat_room_service.ChatRoomBusyError in (
        hypothesis_first_routes._DOMAIN_ERRORS
    )
    with pytest.raises(HTTPException) as exc_info:
        hypothesis_first_routes._map_domain_error(
            "hypothesis_first.command",
            "team-1",
            chat_room_service.ChatRoomBusyError(
                "Chat room already has an active round."
            ),
        )
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# v1/v2 convergence consistency (claim belief hard gate)
# ---------------------------------------------------------------------------


def _converged_chain_records() -> list[dict[str, object]]:
    return [
        {
            "recordKind": "hypothesis_round",
            "roundId": "round-accepted",
            "question": "SCI-001",
            "roundIndex": 1,
            "status": "closed",
            "createdAt": "2026-08-25T00:00:00Z",
            "metaReview": {
                "accepted": True,
                "recommendationCandidateId": "candidate-confirmed",
            },
        }
    ]


def test_gate_blocked_round_no_longer_projects_converged_or_create_formal_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v2 must agree with the v1 chain gate: a blocked candidate is not converged.

    Before the consistency fix, v2 projected ``converged`` from structural
    facts alone and kept offering ``create_formal_run`` while the v1 chain
    state (readiness authority) stayed blocked on the same claim data.
    """
    _blocked_claim_belief_gate(monkeypatch, "claim_data_missing")
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=_converged_chain_records(),
            formal_runs=[],
        )
    )

    assert state.convergence.accepted is False
    assert state.convergence.claimBeliefGate is not None
    assert state.convergence.claimBeliefGate["status"] == "blocked"
    assert state.convergence.claimBeliefGate["reason"] == "claim_data_missing"
    assert not any(
        action.kind == "command" and action.command == "create_formal_run"
        for action in state.allowedActions
    )
    assert state.currentPhase == "convergence"


def test_v2_convergence_matches_real_claim_ledger_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real claim-ledger gate decides v2 convergence (no seam stub)."""
    from core.research.evidence import ClaimEvidenceStore
    from core.research.workflow.contracts import scope_hash_for
    from core.web.services import team_service
    from core.web.services.team_workflow import claim_ledger
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain as chain,
    )

    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(claim_ledger, "PROJECT_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(
        hf_state_v2_module,
        "_claim_belief_gate_verdict",
        _REAL_CLAIM_BELIEF_GATE_VERDICT,
    )
    team_id = team_service.create_team(name="v2 convergence gate team")["teamId"]
    scope = chain._question_scope_envelope(team_id, "SCI-001")
    identity = {
        field: scope[field]
        for field in ("program", "theme", "campaign", "question", "branch", "workflow")
    }
    scope_hash = scope_hash_for(
        **identity, agent_id=scope["agentId"], mode=scope["mode"]
    )
    created = claim_ledger.propose_claim(
        team_id,
        {
            **identity,
            "agentId": scope["agentId"],
            "mode": scope["mode"],
            "claim": "Candidate candidate-confirmed carries a review-supported core claim.",
            "createdBy": scope["agentId"],
            "source": "agent",
        },
    )
    claim_id = created["claim"]["claimId"]
    evidence_id = "ce-v2-convergence-1"
    claim_ledger.support_claim(
        team_id,
        claim_id,
        {
            "evidenceRefs": [
                {
                    "claimEvidenceId": evidence_id,
                    "scopeHash": scope_hash,
                    "reviewStatus": "accepted",
                    "supportLevel": "supports",
                    "sourceId": "fixture:v2-convergence",
                }
            ],
            "supportedBy": scope["agentId"],
        },
    )
    # The candidate bridge the gate consumes comes from the evidence store
    # under the same project root the chain reads.
    monkeypatch.setattr(
        chain,
        "_claim_evidence_records",
        lambda _team_id: [
            {
                "claimEvidenceId": evidence_id,
                "claimId": claim_id,
                "candidateId": "candidate-confirmed",
                "sourceId": "fixture:v2-convergence",
                "reviewStatus": "accepted",
                "supportLevel": "supports",
                "scopeHash": scope_hash,
            }
        ],
    )

    # v1 chain gate verdict and v2 convergence must agree on the same data.
    assert chain.evaluate_claim_belief_gate(
        team_id, "SCI-001", ["candidate-confirmed"]
    )["candidate-confirmed"]["status"] == "allowed"
    state = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id=team_id,
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=_converged_chain_records(),
            formal_runs=[],
        )
    )

    assert state.convergence.accepted is True
    assert state.convergence.claimBeliefGate is not None
    assert state.convergence.claimBeliefGate["status"] == "allowed"
    assert state.convergence.claimBeliefGate["candidateId"] == "candidate-confirmed"
    assert any(
        action.kind == "command" and action.command == "create_formal_run"
        for action in state.allowedActions
    )
    # The real evidence store is untouched by the projection.
    assert ClaimEvidenceStore(tmp_path).list(team_id) == []


def test_awaiting_handoff_collection_exposes_confirm_and_retry_actions() -> None:
    """The handoff actions stay reachable: the projection emits a real status.

    Regression lock: ``collection_request_state`` used to omit
    ``handoffStatus`` entirely, which made the "重试资料交接" elif branch
    read a key that never existed (dead branch).  The status is now derived
    from the request's own child-run / handoff facts.
    """
    # Child completed, no handoff recorded yet -> awaiting human acceptance.
    awaiting = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "collection_request",
                    "requestId": "request-awaiting",
                    "questionId": "SCI-001",
                    "status": "active",
                    "collectionRunId": "child-done",
                    "collectionRunStatus": "succeeded",
                    "searchEnvelope": {"keywords": ["water"]},
                }
            ],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
        )
    )
    request_state = awaiting.collection.requests[0]
    assert request_state.handoffStatus == "pending"
    confirm = next(
        action
        for action in awaiting.allowedActions
        if action.kind == "command" and action.command == "handoff_collection"
    )
    assert confirm.label == "确认资料交接"
    assert confirm.payload.requestId == "request-awaiting"
    assert confirm.payload.childRunId == "child-done"

    # A previously failed handoff attempt (recorded handoffError) offers the
    # explicit retry-handoff recovery instead of a plain confirmation.
    failed_handoff = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "collection_request",
                    "requestId": "request-handoff-failed",
                    "questionId": "SCI-001",
                    "status": "active",
                    "collectionRunId": "child-handoff-failed",
                    "collectionRunStatus": "succeeded",
                    "searchEnvelope": {"keywords": ["water"]},
                    "handoffError": {"code": "handoff_write_failed"},
                }
            ],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
        )
    )
    assert failed_handoff.collection.requests[0].handoffStatus == "failed"
    retry = next(
        action
        for action in failed_handoff.allowedActions
        if action.kind == "command" and action.command == "handoff_collection"
    )
    assert retry.label == "重试资料交接"
    assert retry.payload.childRunId == "child-handoff-failed"

    # No child run bound -> needs_context, handed_off -> accepted.
    assert awaiting.collection.requests[0].handoffStatus != "needs_context"
    orphan = HypothesisFirstStateV2.model_validate(
        project_state_from_records(
            team_id="team-1",
            question_id="SCI-001",
            reset_boundary=None,
            chain_records=[
                {
                    "recordKind": "collection_request",
                    "requestId": "request-orphan",
                    "questionId": "SCI-001",
                    "status": "pending",
                    "collectionRunId": "",
                    "collectionRunStatus": "",
                    "searchEnvelope": {"keywords": ["water"]},
                }
            ],
            selection_records=[],
            meeting_records=[],
            digest_records=[],
            decision_records=[],
            hypothesis_round_records=[],
        )
    )
    assert orphan.collection.requests[0].handoffStatus == "needs_context"
