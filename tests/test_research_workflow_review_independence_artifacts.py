"""Contract tests for reviewer-independence and review-disagreement artifacts.

Covers decision #4 of the 13-decision contract: reviewer disagreement is a
first-class decision input next to the Pareto front and the hard gates, while
same-source pseudo-independence is rejected fail-closed and escalation is
marked only — never executed.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from core.research.workflow.contracts import ContractValidationError
from core.research.workflow.contracts.review_independence import (
    ESCALATION_STATUS_FLAGGED_ONLY,
    ReviewDisagreementArtifact,
    ReviewerIndependenceRecord,
    inconsistent_axes_for_pair,
    review_step_identity,
    reviewer_independence_summary,
    validate_step_independence,
)
from core.web.services.team_workflow.research_runtime import (
    review_independence_artifact_writer as writer,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _record() -> dict[str, Any]:
    return {
        "recordId": "reviewer-independence:reflection:ctx-1:H1",
        "teamId": "team-1",
        "workflowRunId": "wf-1",
        "reviewRoundId": "round-1",
        "reviewContextId": "ctx-1",
        "reviewStep": "reflection",
        "stepIdentity": review_step_identity("reflection", "ctx-1", ("H1",)),
        "reviewerId": "reviewer-a",
        "reviewerRole": "research_evidence_reviewer",
        "assignmentSource": "executor_role_default",
        "receiptRef": "",
        "executionMode": "dev",
    }


def _scores(values: dict[str, float]) -> dict[str, float]:
    base = {
        "novelty": 0.5,
        "competitionFit": 0.5,
        "falsifiability": 0.5,
        "evidenceSupport": 0.5,
        "feasibility": 0.5,
    }
    base.update(values)
    return base


def _review_payload() -> dict[str, Any]:
    """Executor-shaped review output: H2 only wins novelty vs H1, H3 loses everywhere."""

    return {
        "schemaVersion": 1,
        "executionMode": "dev",
        "reviewContextId": "ctx-1",
        "positionSeed": "seed-1",
        "candidates": [
            {
                "candidateId": "H1",
                "claim": "A",
                "scores": _scores(
                    {
                        "novelty": 0.9,
                        "competitionFit": 0.8,
                        "falsifiability": 0.7,
                        "evidenceSupport": 0.6,
                        "feasibility": 0.5,
                    }
                ),
                "reviewedBy": "reviewer-a",
                "status": "reviewed",
            },
            {
                "candidateId": "H2",
                "claim": "B",
                "scores": _scores(
                    {
                        "novelty": 0.2,
                        "competitionFit": 0.8,
                        "falsifiability": 0.2,
                        "evidenceSupport": 0.2,
                        "feasibility": 0.2,
                    }
                ),
                "reviewedBy": "reviewer-a",
                "status": "reviewed",
            },
            {
                "candidateId": "H3",
                "claim": "C",
                "scores": _scores(
                    {
                        "novelty": 0.3,
                        "competitionFit": 0.1,
                        "falsifiability": 0.1,
                        "evidenceSupport": 0.1,
                        "feasibility": 0.1,
                    }
                ),
                "reviewedBy": "reviewer-a",
                "status": "reviewed",
            },
        ],
        "pairwiseComparisons": [
            {
                "comparisonId": "cmp-1",
                "leftCandidateId": "H1",
                "rightCandidateId": "H2",
                "reviewerAgentId": "reviewer-b",
                "outcome": "right_wins",
                "justification": "H2 更新颖",
            },
            {
                "comparisonId": "cmp-2",
                "leftCandidateId": "H1",
                "rightCandidateId": "H3",
                "reviewerAgentId": "reviewer-b",
                "outcome": "left_wins",
                "justification": "H1 全面领先",
            },
            {
                "comparisonId": "cmp-3",
                "leftCandidateId": "H2",
                "rightCandidateId": "H3",
                "reviewerAgentId": "reviewer-b",
                "outcome": "tie",
                "justification": "各有取舍",
            },
        ],
        "pareto": {
            "paretoFrontCandidateIds": ["H1"],
            "dominatedCandidateIds": ["H2", "H3"],
            "analystAgentId": "reviewer-c",
            "notes": "H1 前沿。",
        },
        "metaReview": {
            "metaReviewId": "meta-1",
            "reviewerAgentId": "coordinator-1",
            "recommendationCandidateId": "H1",
            "rationale": "H1 前沿且胜出。",
            "riskNotes": "",
            "accepted": True,
        },
        "roles": {
            "reflection": "reviewer-a",
            "pairwise": "reviewer-b",
            "pareto": "reviewer-c",
            "metareview": "coordinator-1",
        },
    }


def _receipt_context(step: str, parts: tuple[str, ...]) -> dict[str, Any]:
    return {
        "receiptId": f"receipt:{step}:{'-'.join(parts)}",
        "evidenceLocator": {
            "reviewStep": step,
            "identityParts": list(parts),
            "reviewContextId": "ctx-1",
        },
    }


def _formal_receipt_contexts() -> list[dict[str, Any]]:
    contexts = [
        _receipt_context("reflection", (candidate,))
        for candidate in ("H1", "H2", "H3")
    ]
    contexts.extend(
        [
            _receipt_context("pairwise", ("H1", "H2")),
            _receipt_context("pairwise", ("H1", "H3")),
            _receipt_context("pairwise", ("H2", "H3")),
            _receipt_context("pareto", ("H1", "H2", "H3")),
            _receipt_context("metareview", ("H1", "H2", "H3")),
        ]
    )
    return contexts


def _fake_store(monkeypatch) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def fake_put(team_id: str, **kwargs):
        identity = kwargs["artifact_identity"]
        for existing in rows:
            if existing["recordId"] == identity:
                assert existing["contentHash"] == writer.canonical_sha256(kwargs["payload"])
                return existing
        record = {
            "recordId": identity,
            "teamId": team_id,
            "kind": kwargs["kind"],
            "workflowRunId": kwargs["workflow_run_id"],
            "sourceCollectionRunId": kwargs["source_collection_run_id"],
            "contentHash": writer.canonical_sha256(kwargs["payload"]),
            "payload": kwargs["payload"],
        }
        rows.append(record)
        return record

    monkeypatch.setattr(writer, "put_workflow_artifact", fake_put)
    return rows


def _forbidden_store(monkeypatch) -> None:
    def unexpected(*args, **kwargs):
        raise AssertionError("blocked projection must not touch the artifact store")

    monkeypatch.setattr(writer, "put_workflow_artifact", unexpected)


# ---------------------------------------------------------------------------
# Contract: independence record + same-source pseudo-independence gate
# ---------------------------------------------------------------------------


def test_independence_record_round_trips() -> None:
    record = ReviewerIndependenceRecord.from_dict(_record())
    assert record.is_receipt_bound() is False
    assert ReviewerIndependenceRecord.from_dict(record.to_dict()) == record


def test_same_reviewer_double_counted_for_one_step_is_rejected() -> None:
    payload = _record()
    records = [
        ReviewerIndependenceRecord.from_dict(payload),
        ReviewerIndependenceRecord.from_dict(
            {**payload, "recordId": "reviewer-independence:reflection:ctx-1:H1-replay"}
        ),
    ]
    with pytest.raises(ContractValidationError, match="pseudo-independence"):
        validate_step_independence(records)


def test_conflicting_reviewers_for_one_step_are_rejected() -> None:
    payload = _record()
    records = [
        ReviewerIndependenceRecord.from_dict(payload),
        ReviewerIndependenceRecord.from_dict(
            {**payload, "reviewerId": "reviewer-b", "recordId": "another"}
        ),
    ]
    with pytest.raises(ContractValidationError, match="multiple reviewers"):
        validate_step_independence(records)


def test_same_reviewer_across_distinct_steps_is_not_pseudo_independent() -> None:
    payload = _record()
    records = [
        ReviewerIndependenceRecord.from_dict(payload),
        ReviewerIndependenceRecord.from_dict(
            {
                **payload,
                "recordId": "reviewer-independence:reflection:ctx-1:H2",
                "stepIdentity": review_step_identity("reflection", "ctx-1", ("H2",)),
            }
        ),
    ]
    validate_step_independence(records)
    summary = reviewer_independence_summary(records)
    assert summary["singleSourcePseudoIndependence"] is True
    assert summary["uniqueStepCount"] == 2


def test_formal_record_requires_receipt_ref() -> None:
    with pytest.raises(ContractValidationError, match="receipt reference"):
        ReviewerIndependenceRecord.from_dict({**_record(), "executionMode": "formal"})


def test_step_identity_requires_known_step_and_context() -> None:
    with pytest.raises(ContractValidationError):
        review_step_identity("digest", "ctx-1", ("H1",))
    with pytest.raises(ContractValidationError):
        review_step_identity("reflection", "", ("H1",))


# ---------------------------------------------------------------------------
# Contract: disagreement artifact shape and mark-only escalation
# ---------------------------------------------------------------------------


def _disagreement_payload() -> dict[str, Any]:
    return {
        "reviewRoundId": "round-1",
        "reviewContextId": "ctx-1",
        "candidatePairs": [
            {
                "comparisonId": "cmp-1",
                "leftCandidateId": "H1",
                "rightCandidateId": "H2",
                "outcome": "right_wins",
                "inconsistentAxes": ["novelty", "falsifiability"],
            }
        ],
        "reviewerScoreRefs": [
            {
                "candidateId": "H1",
                "reviewerId": "reviewer-a",
                "scoreRef": "hypothesis_review:ctx-1/candidate/H1/scores",
            }
        ],
        "disagreementAxes": ["novelty", "falsifiability"],
        "disagreementMetrics": [
            {"axis": "novelty", "directionInconsistencyCount": 1},
            {"axis": "falsifiability", "directionInconsistencyCount": 1},
        ],
        "escalation": {
            "required": True,
            "reason": "pairwise outcome direction contradicts reflection score direction",
            "status": ESCALATION_STATUS_FLAGGED_ONLY,
        },
    }


def test_disagreement_artifact_round_trips() -> None:
    artifact = ReviewDisagreementArtifact.from_dict(_disagreement_payload())
    assert artifact.disagreementAxes == ("novelty", "falsifiability")
    assert ReviewDisagreementArtifact.from_dict(artifact.to_dict()) == artifact


def test_auxiliary_diagnostic_never_becomes_disagreement_axis() -> None:
    payload = _disagreement_payload()
    payload["disagreementAxes"] = ["novelty", "replicability"]
    payload["disagreementMetrics"] = [
        {"axis": "novelty", "directionInconsistencyCount": 1},
        {"axis": "replicability", "directionInconsistencyCount": 1},
    ]
    with pytest.raises(ContractValidationError, match="auxiliary diagnostics"):
        ReviewDisagreementArtifact.from_dict(payload)


def test_non_decision_axis_is_rejected() -> None:
    payload = _disagreement_payload()
    payload["disagreementAxes"] = ["novelty", "eloRank"]
    with pytest.raises(ContractValidationError, match="five decision dimensions"):
        ReviewDisagreementArtifact.from_dict(payload)


def test_escalation_is_mark_only_and_never_executed() -> None:
    payload = _disagreement_payload()
    payload["escalation"]["status"] = "executed"
    with pytest.raises(ContractValidationError, match="marked only"):
        ReviewDisagreementArtifact.from_dict(payload)
    artifact = ReviewDisagreementArtifact.from_dict(_disagreement_payload())
    assert artifact.escalation.status == ESCALATION_STATUS_FLAGGED_ONLY
    assert artifact.to_dict()["escalation"].keys() == {"required", "reason", "status"}


def test_escalation_requires_at_least_one_disagreement_axis() -> None:
    payload = _disagreement_payload()
    payload["disagreementAxes"] = []
    payload["disagreementMetrics"] = []
    with pytest.raises(ContractValidationError, match="at least one disagreement axis"):
        ReviewDisagreementArtifact.from_dict(payload)


def test_direction_inconsistency_detects_axis_level_conflicts() -> None:
    left = _scores({"novelty": 0.9, "feasibility": 0.8})
    right = _scores({"novelty": 0.2, "feasibility": 0.9})
    assert inconsistent_axes_for_pair(left, right, "left_wins") == ("feasibility",)
    assert inconsistent_axes_for_pair(left, right, "tie") == ()
    assert inconsistent_axes_for_pair(left, right, "right_wins") == ("novelty",)
    with pytest.raises(ContractValidationError):
        inconsistent_axes_for_pair(left, right, "both_win")


# ---------------------------------------------------------------------------
# Writer: pure projection + idempotent persistence
# ---------------------------------------------------------------------------


def _write(review: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return writer.write_review_independence_artifacts(
        team_id="team-1",
        workflow_run_id="wf-1",
        node_run_id="node-1",
        review_round_id="round-1",
        review=review,
        reviewer_assignments={"metareview": "coordinator-1"},
        **overrides,
    )


def test_writer_projects_independence_and_disagreement(monkeypatch) -> None:
    rows = _fake_store(monkeypatch)
    result = _write(_review_payload())

    assert result["status"] == "written"
    independence = result["reviewIndependence"]
    assert independence["recordCount"] == 8
    assert independence["summary"] == {
        "recordCount": 8,
        "uniqueReviewerCount": 4,
        "uniqueStepCount": 8,
        "receiptBoundRecordCount": 0,
        "singleSourcePseudoIndependence": False,
    }
    records = rows[0]["payload"]["records"]
    by_step = {record["stepIdentity"]: record for record in records}
    assert len(records) == 8
    reflection_record = by_step[review_step_identity("reflection", "ctx-1", ("H1",))]
    assert reflection_record["reviewerId"] == "reviewer-a"
    assert reflection_record["assignmentSource"] == "executor_role_default"
    pairwise_record = by_step[review_step_identity("pairwise", "ctx-1", ("H1", "H2"))]
    assert pairwise_record["reviewerId"] == "reviewer-b"
    metareview_record = by_step[
        review_step_identity("metareview", "ctx-1", ("H1", "H2", "H3"))
    ]
    assert metareview_record["reviewerId"] == "coordinator-1"
    assert metareview_record["assignmentSource"] == "reviewer_assignments"

    disagreement = result["reviewDisagreement"]
    assert disagreement["escalationRequired"] is True
    assert disagreement["escalationStatus"] == ESCALATION_STATUS_FLAGGED_ONLY
    payload = rows[1]["payload"]
    assert payload["disagreementAxes"] == [
        "novelty",
        "falsifiability",
        "evidenceSupport",
        "feasibility",
    ]
    assert payload["disagreementMetrics"] == [
        {"axis": "novelty", "directionInconsistencyCount": 1},
        {"axis": "falsifiability", "directionInconsistencyCount": 1},
        {"axis": "evidenceSupport", "directionInconsistencyCount": 1},
        {"axis": "feasibility", "directionInconsistencyCount": 1},
    ]
    axes_in_pairs = {
        pair["comparisonId"]: pair["inconsistentAxes"]
        for pair in payload["candidatePairs"]
    }
    assert axes_in_pairs["cmp-1"] == [
        "novelty",
        "falsifiability",
        "evidenceSupport",
        "feasibility",
    ]
    assert axes_in_pairs["cmp-2"] == []
    assert axes_in_pairs["cmp-3"] == []
    assert payload["escalation"]["status"] == ESCALATION_STATUS_FLAGGED_ONLY
    score_refs = {(ref["candidateId"], ref["reviewerId"]) for ref in payload["reviewerScoreRefs"]}
    assert score_refs == {("H1", "reviewer-a"), ("H2", "reviewer-a"), ("H3", "reviewer-a")}
    # Score bodies are referenced, never copied into the artifact.
    assert all(
        set(ref.keys()) == {"candidateId", "reviewerId", "scoreRef"}
        for ref in payload["reviewerScoreRefs"]
    )


def test_writer_is_idempotent_for_identical_review_output(monkeypatch) -> None:
    rows = _fake_store(monkeypatch)
    first = _write(_review_payload())
    replay = _write(_review_payload())

    assert first["status"] == "written"
    assert replay["status"] == "written"
    assert replay["reviewIndependence"]["artifact"]["canonicalHash"] == (
        first["reviewIndependence"]["artifact"]["canonicalHash"]
    )
    assert replay["reviewDisagreement"]["artifact"]["canonicalHash"] == (
        first["reviewDisagreement"]["artifact"]["canonicalHash"]
    )
    assert sorted(row["kind"] for row in rows) == ["review_disagreement", "review_independence"]
    assert len(rows) == 2


def test_writer_flags_single_source_review_without_failing(monkeypatch) -> None:
    rows = _fake_store(monkeypatch)
    review = _review_payload()
    review["pairwiseComparisons"] = [
        {**comparison, "reviewerAgentId": "reviewer-a"}
        for comparison in review["pairwiseComparisons"]
    ]
    review["pareto"]["analystAgentId"] = "reviewer-a"
    review["metaReview"]["reviewerAgentId"] = "reviewer-a"

    result = _write(review)

    assert result["status"] == "written"
    assert result["reviewIndependence"]["summary"]["singleSourcePseudoIndependence"] is True
    assert result["reviewDisagreement"]["escalationStatus"] == ESCALATION_STATUS_FLAGGED_ONLY
    assert len(rows) == 2


def test_writer_rejects_duplicated_step_instance(monkeypatch) -> None:
    _forbidden_store(monkeypatch)
    review = _review_payload()
    review["pairwiseComparisons"].append(deepcopy(review["pairwiseComparisons"][0]))

    result = _write(review)

    assert result["status"] == "blocked"
    assert "reviewer_pseudo_independence_double_count" in result["blockerCodes"]
    assert result["reviewIndependence"] is None
    assert result["reviewDisagreement"] is None


def test_writer_formal_mode_binds_receipt_refs(monkeypatch) -> None:
    rows = _fake_store(monkeypatch)
    review = _review_payload()
    review["executionMode"] = "formal"
    review["modelInvocationReceipts"] = [
        {"receiptId": f"provider-{index}"} for index in range(8)
    ]

    result = _write(review, receipt_contexts=_formal_receipt_contexts())

    assert result["status"] == "written"
    records = rows[0]["payload"]["records"]
    reflection_record = next(
        record
        for record in records
        if record["stepIdentity"]
        == review_step_identity("reflection", "ctx-1", ("H1",))
    )
    assert reflection_record["receiptRef"] == "receipt:reflection:H1"
    assert reflection_record["executionMode"] == "formal"
    assert result["reviewIndependence"]["summary"]["receiptBoundRecordCount"] == 8
    metareview_record = next(
        record
        for record in records
        if record["reviewStep"] == "metareview"
    )
    assert metareview_record["receiptRef"] == "receipt:metareview:H1-H2-H3"


def test_writer_formal_mode_blocks_without_receipt_contexts(monkeypatch) -> None:
    _forbidden_store(monkeypatch)
    review = _review_payload()
    review["executionMode"] = "formal"

    result = _write(review)

    assert result["status"] == "blocked"
    assert "review_independence_receipt_ref_missing" in result["blockerCodes"]


def test_writer_blocks_incomplete_binding_without_store_access(monkeypatch) -> None:
    _forbidden_store(monkeypatch)
    result = writer.write_review_independence_artifacts(
        team_id="team-1",
        workflow_run_id="wf-1",
        review_round_id="",
        review=_review_payload(),
    )

    assert result["status"] == "blocked"
    assert "reviewRoundId_missing" in result["blockerCodes"]


def test_writer_blocks_review_without_scores_or_comparisons(monkeypatch) -> None:
    _forbidden_store(monkeypatch)
    review = _review_payload()
    for candidate in review["candidates"]:
        candidate.pop("scores")
    review["pairwiseComparisons"] = []

    result = _write(review)

    assert result["status"] == "blocked"
    assert "review_disagreement_comparisons_missing" in result["blockerCodes"]
    assert "review_disagreement_candidate_scores_missing" in result["blockerCodes"]
