from __future__ import annotations

import subprocess
import sys
import time
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path

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
from core.web.services.team_workflow.research_runtime.hypothesis_first_state_v2 import (
    finalize_state_versions,
    project_state_from_records,
)
from tests.helpers.managed_processes import managed_processes


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
                "metaReview": {"accepted": True},
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
                "metaReview": {"accepted": True},
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
    assert any(
        action.kind == "command" and action.command == "create_formal_run"
        for action in state.allowedActions
    )


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
    [(1, "open_next_review"), (3, "human_adjudication")],
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
        assert action.payload.roundBudget == 3
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

    def submit(team_id: str, *, run_id: str, command: str, idempotency_key: str, **_kwargs):
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


def test_collection_failed_and_completed_states_expose_retry_and_handoff() -> None:
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
