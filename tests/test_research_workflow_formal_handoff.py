from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.contracts import SCORE_DIMENSIONS, scope_hash_for
from core.research.workflow.contracts.run_input import WorkflowRunInputSnapshot
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow import hypothesis_rounds, meeting_rounds
from core.web.services.team_workflow.research_runtime import (
    formal_hypothesis_fanout,
    run_creation,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
)


def _closed_round(*, accepted: bool = True) -> dict:
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

    def candidate(candidate_id: str, claim: str) -> dict:
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
    accepted: bool = True,
    decision_resolves: bool = True,
) -> None:
    monkeypatch.setattr(
        hypothesis_rounds,
        "get_hypothesis_round",
        lambda _team_id, _round_id: {"round": _closed_round(accepted=accepted)},
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
            else ([{"decisionId": "decision-final"}] if decision_resolves else [])
        ),
    )


def test_formal_handoff_freezes_only_the_confirmed_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_handoff_authorities(monkeypatch)

    handoff = run_creation._formal_hypothesis_handoff(
        "research-team",
        "SCI-003",
        hypothesis_round_id="hround-final",
    )

    selection = handoff["hypothesisSelection"]
    assert selection["selectionId"] == "selection-reviewed"
    assert selection["selectedCandidateIds"] == ["candidate-confirmed"]
    assert [item["candidateId"] for item in selection["candidateSnapshots"]] == [
        "candidate-confirmed"
    ]
    assert handoff["hypothesisConvergenceHandoff"]["evidenceRefs"] == [
        "hypothesis_round:hround-final",
        "meeting_round:meeting-final",
        "meeting_digest:digest-final",
        "decision_record:decision-final",
    ]


def test_formal_handoff_fails_closed_when_review_evidence_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_handoff_authorities(monkeypatch, decision_resolves=False)

    with pytest.raises(ResearchWorkflowError) as exc_info:
        run_creation._formal_hypothesis_handoff(
            "research-team",
            "SCI-003",
            hypothesis_round_id="hround-final",
        )

    assert exc_info.value.code == "formal_hypothesis_handoff_incomplete"


def test_question_run_does_not_persist_when_formal_handoff_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_calls: list[dict] = []
    monkeypatch.setattr(run_creation, "assert_writes_allowed", lambda *_args, **_kwargs: None)
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
        "_formal_hypothesis_handoff",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ResearchWorkflowError(
                "missing handoff",
                code="formal_hypothesis_handoff_incomplete",
            )
        ),
    )
    monkeypatch.setattr(
        run_creation,
        "create_run",
        lambda *_args, **kwargs: create_calls.append(kwargs),
    )

    with pytest.raises(ResearchWorkflowError):
        run_creation.create_question_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            team_id="research-team",
            question_id="SCI-003",
            safety_limits={},
            idempotency_key="formal-create",
            formal_hypothesis_round_id="hround-final",
        )

    assert create_calls == []


def test_run_input_preserves_handoff_and_frozen_selection() -> None:
    payload = {
        "teamId": "research-team",
        "projectId": "project-sci003",
        "questionId": "SCI-003",
        "workflowVersionId": "workflow-v1",
        "researchBriefHash": "brief-hash",
        "datasetRefs": ["dataset:1"],
        "metricContract": {"primary": "coverage"},
        "constraintSnapshot": {},
        "competitionRuleRef": "challenge-cup",
        "competitionRuleVersion": "v1",
        "trackAndRubricSnapshot": {"track": "science"},
        "researchObjectiveContract": {"question": "SCI-003"},
        "sourcePolicy": {"minimumPrimarySources": 3},
        "budgetPolicy": {"tokens": 100},
        "stopPolicy": {"maxNoImprovementRounds": 2},
        "environmentSnapshotRef": "environment:1",
        "modelRoutingPolicy": {"profile": "formal"},
        "evaluationContract": {"minimumClaimEvidenceCoverage": 0.9},
        "agentBindingSnapshot": [{"snapshotId": "binding-1"}],
        "createdBy": "operator",
        "createdAt": "2026-08-27T00:00:00Z",
        "hypothesisSelection": {
            "selectionId": "selection-reviewed",
            "selectedCandidateIds": ["candidate-confirmed"],
            "candidateSnapshots": [{"candidateId": "candidate-confirmed"}],
        },
        "hypothesisConvergenceHandoff": {
            "roundId": "hround-final",
            "confirmedCandidateId": "candidate-confirmed",
        },
    }

    snapshot = WorkflowRunInputSnapshot.from_dict(payload)
    frozen = snapshot.to_dict()

    assert frozen["hypothesisSelection"]["selectedCandidateIds"] == [
        "candidate-confirmed"
    ]
    assert formal_hypothesis_fanout._selection_from_snapshot(frozen) == {
        "selectionId": "selection-reviewed",
        "selectedCandidateIds": ["candidate-confirmed"],
        "candidateSnapshots": [{"candidateId": "candidate-confirmed"}],
    }
    assert frozen["hypothesisConvergenceHandoff"]["roundId"] == "hround-final"
