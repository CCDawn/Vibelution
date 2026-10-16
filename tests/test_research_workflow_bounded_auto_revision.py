"""R2.2 direct claim-belief gate on the formal hypothesis handoff.

The bounded auto-revision fork execution on the 3.0.0-only
``iteration_decision`` node was removed together with its permanently dead
trigger path; this file now covers the surviving live contract in
``run_creation``: a blocked handoff hypothesis raises
``ClaimBeliefGateBlockedError`` before any run is created, an allowed one
freezes the handoff and reaches run creation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow import hypothesis_rounds, meeting_rounds
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain,
    run_creation,
    workflow_artifact_store,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope,
)


@pytest.fixture(autouse=True)
def _bind_server_operator(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    with server_operator_scope("test-operator", roles=("operator",)):
        yield


def _closed_round(*, accepted: bool = True) -> dict[str, Any]:
    from core.research.workflow.contracts import SCORE_DIMENSIONS, scope_hash_for

    scope = {
        "program": "XH-202619",
        "theme": "challenge-cup",
        "campaign": "challenge-cup-research",
        "question": "SCI-003",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agentId": "agent-meta",
        "mode": "formal",
    }
    scope_hash = scope_hash_for(
        program=scope["program"],
        theme=scope["theme"],
        campaign=scope["campaign"],
        question=scope["question"],
        branch=scope["branch"],
        workflow=scope["workflow"],
        agent_id=scope["agentId"],
        mode=scope["mode"],
    )

    def candidate(candidate_id: str, claim: str) -> dict[str, Any]:
        return {
            "candidateId": candidate_id,
            "claim": claim,
            "rationale": f"rationale-{candidate_id}",
            "differenceFromAlternatives": f"difference-{candidate_id}",
            "lineageRefs": [],
            "scores": {dimension: 0.8 for dimension in SCORE_DIMENSIONS},
            "reviewedBy": f"reviewer-{candidate_id}",
            "status": "proposed",
        }

    return {
        "roundId": "hround-final",
        **scope,
        "scopeHash": scope_hash,
        "status": "closed",
        "candidates": [
            candidate("candidate-confirmed", "confirmed mechanism"),
            candidate("candidate-rejected", "alternative mechanism"),
        ],
        "pairwiseComparisons": [
            {
                "comparisonId": "cmp-final",
                "leftCandidateId": "candidate-confirmed",
                "rightCandidateId": "candidate-rejected",
                "reviewerAgentId": "agent-pairwise",
                "outcome": "left_wins",
                "justification": "confirmed candidate has stronger evidence",
            }
        ],
        "pareto": {
            "paretoFrontCandidateIds": ["candidate-confirmed"],
            "dominatedCandidateIds": ["candidate-rejected"],
            "analystAgentId": "agent-pareto",
            "notes": "complete classification",
        },
        "metaReview": {
            "metaReviewId": "meta-final",
            "reviewerAgentId": "agent-meta",
            "recommendationCandidateId": "candidate-confirmed",
            "rationale": "best supported candidate",
            "riskNotes": "bounded risk",
            "accepted": accepted,
        },
        "lineage": [{"kind": "candidate", "id": "candidate-confirmed"}],
        "meetingRefs": [
            {"kind": "meeting_round", "id": "meeting-final"},
            {"kind": "meeting_digest", "id": "digest-final"},
            {"kind": "decision_record", "id": "decision-final"},
        ],
        "createdAt": "2026-08-27T00:00:00Z",
        "closedAt": "2026-08-27T00:10:00Z",
        "closedBy": "agent-meta",
    }


def _install_handoff_authorities(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gate_verdicts: dict[str, dict[str, Any]],
) -> None:
    monkeypatch.setattr(
        hypothesis_rounds,
        "get_hypothesis_round",
        lambda _team_id, _round_id: {"round": _closed_round()},
    )
    monkeypatch.setattr(
        hypothesis_first_chain,
        "evaluate_claim_belief_gate",
        lambda _team_id, _question_id, candidate_ids: {
            candidate_id: gate_verdicts[candidate_id]
            for candidate_id in candidate_ids
        },
    )
    monkeypatch.setattr(
        meeting_rounds,
        "get_meeting_round",
        lambda _team_id, _meeting_id: {
            "meetingRound": {
                "meetingRoundId": "meeting-final",
                "meetingType": "hypothesis_review",
                "status": "closed",
                "question": "SCI-003",
                "digestId": "digest-final",
                "decisionRefs": ["decision-final"],
                "inputArtifactRefs": ["hypothesis_selection:selection-reviewed"],
            }
        },
    )
    monkeypatch.setattr(meeting_rounds, "_digests_path", lambda _team_id: Path("digests"))
    monkeypatch.setattr(
        meeting_rounds,
        "_decisions_path",
        lambda _team_id: Path("decisions"),
    )
    monkeypatch.setattr(
        meeting_rounds,
        "_read_jsonl",
        lambda path: (
            [{"digestId": "digest-final"}]
            if str(path) == "digests"
            else [{"decisionId": "decision-final"}]
        ),
    )


def _blocked_verdict() -> dict[str, dict[str, Any]]:
    return {
        "candidate-confirmed": {
            "candidateId": "candidate-confirmed",
            "status": "blocked",
            "reason": "claim_belief_state_blocked",
            "claims": [],
            "blockedClaims": [
                {"claimId": "claim-1", "beliefState": "contradicted"}
            ],
        }
    }


def _allowed_verdict() -> dict[str, dict[str, Any]]:
    return {
        "candidate-confirmed": {
            "candidateId": "candidate-confirmed",
            "status": "allowed",
            "reason": "",
            "claims": [],
            "blockedClaims": [],
        }
    }


def test_formal_handoff_blocked_hypothesis_raises_claim_belief_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_handoff_authorities(monkeypatch, gate_verdicts=_blocked_verdict())

    with pytest.raises(hypothesis_first_chain.ClaimBeliefGateBlockedError) as exc_info:
        run_creation._formal_hypothesis_handoff(
            "research-team",
            "SCI-003",
            hypothesis_round_id="hround-final",
        )

    assert exc_info.value.code == "claim_belief_gate_blocked"
    assert exc_info.value.stage == "formal_run_handoff"
    assert exc_info.value.candidate_id == "candidate-confirmed"
    blockers = exc_info.value.blockers
    assert blockers and blockers[0]["reason"] == "claim_belief_state_blocked"
    assert blockers[0]["claims"][0]["claimId"] == "claim-1"


def test_formal_handoff_allowed_hypothesis_freezes_and_creates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_handoff_authorities(monkeypatch, gate_verdicts=_allowed_verdict())

    handoff = run_creation._formal_hypothesis_handoff(
        "research-team",
        "SCI-003",
        hypothesis_round_id="hround-final",
    )

    assert (
        handoff["hypothesisConvergenceHandoff"]["confirmedCandidateId"]
        == "candidate-confirmed"
    )
    assert handoff["hypothesisSelection"]["selectedCandidateIds"] == [
        "candidate-confirmed"
    ]

    created_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        run_creation, "assert_writes_allowed", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(run_creation, "get_write_store", lambda: object())
    monkeypatch.setattr(
        run_creation,
        "build_question_run_input",
        lambda *_args, **_kwargs: {
            "teamId": "research-team",
            "questionId": "SCI-003",
            "researchScopeEnvelope": {},
            "catalogScope": {},
        },
    )
    monkeypatch.setattr(
        run_creation,
        "create_run",
        lambda *_args, **kwargs: created_calls.append(kwargs)
        or {"runId": "run-created"},
    )

    created = run_creation.create_question_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        team_id="research-team",
        question_id="SCI-003",
        safety_limits={},
        idempotency_key="formal-create",
        formal_hypothesis_round_id="hround-final",
    )

    assert created["runId"] == "run-created"
    assert len(created_calls) == 1
    run_input = created_calls[0]["run_input"]
    assert (
        run_input["hypothesisConvergenceHandoff"]["confirmedCandidateId"]
        == "candidate-confirmed"
    )


def test_formal_handoff_gate_failure_blocks_run_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_handoff_authorities(monkeypatch, gate_verdicts=_blocked_verdict())
    created_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        run_creation, "assert_writes_allowed", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(run_creation, "get_write_store", lambda: object())
    monkeypatch.setattr(
        run_creation,
        "build_question_run_input",
        lambda *_args, **_kwargs: {
            "researchScopeEnvelope": {},
            "catalogScope": {},
        },
    )
    monkeypatch.setattr(
        run_creation,
        "create_run",
        lambda *_args, **kwargs: created_calls.append(kwargs),
    )

    with pytest.raises(hypothesis_first_chain.ClaimBeliefGateBlockedError):
        run_creation.create_question_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            team_id="research-team",
            question_id="SCI-003",
            safety_limits={},
            idempotency_key="formal-create",
            formal_hypothesis_round_id="hround-final",
        )

    assert created_calls == []
