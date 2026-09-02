"""Focused contract checks for the independent seven-dimension authority."""

from __future__ import annotations

from copy import deepcopy

import pytest

from core.research.workflow.contracts import SCORE_DIMENSIONS, ContractValidationError
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
)
from core.web.services.team_workflow import hypothesis_review_executor
from core.web.services.team_workflow.research_runtime import (
    dimension_reviews_artifact_writer as writer,
)

_EVIDENCE_REF = "evidence_card_batch://team-1/source-1/0123456789abcdef0123456789abcdef"
_AUTHORITY = {
    "authorityKind": "workflow_run",
    "teamId": "team-1",
    "questionId": "SCI-001",
    "workflowRunId": "wf-1",
}
_BASE = {
    "team_id": "team-1",
    "workflow_run_id": "wf-1",
    "node_run_id": "node-1",
    "question_id": "SCI-001",
    "selection_id": "selection-1",
    "review_round_id": "round-1",
    "input_refs": ["hypothesis_selection:selection-1", _EVIDENCE_REF],
    "input_snapshot_hash": "a" * 64,
    "candidates": [
        {"candidateId": "H1", "claim": "claim one"},
        {"candidateId": "H2", "claim": "claim two"},
    ],
    "workflow_authority": _AUTHORITY,
}


def _review_rows() -> list[dict[str, str | list[str]]]:
    return [
        {
            "hypothesis_id": candidate,
            "dimension": dimension,
            "rating": "adequate",
            "rationale": f"{candidate} {dimension} rationale",
            "reviewer": "reviewer-1",
            "evidence_refs": [_EVIDENCE_REF],
        }
        for candidate in ("H1", "H2")
        for dimension in writer.REQUIRED_REVIEW_DIMENSIONS
    ]


def _review_payload() -> dict[str, object]:
    return {
        "dimensionReviews": _review_rows(),
        "pareto": {
            "paretoFrontCandidateIds": ["H1"],
            "dominatedCandidateIds": ["H2"],
            "analystAgentId": "synthesizer-1",
            "notes": "H1 is the explicit Pareto-front candidate.",
        },
        "metaReview": {
            "metaReviewId": "meta-1",
            "reviewerAgentId": "coordinator-1",
            "recommendationCandidateId": "H1",
            "rationale": "The explicit review recommends H1 for human confirmation.",
            "riskNotes": "H2 remains a dominated alternative.",
            "accepted": True,
        },
    }


def _reflection_receipt(candidate_id: str) -> dict[str, object]:
    return ModelInvocationReceipt.from_invocation(
        receipt_id=f"receipt-reflection-{candidate_id}",
        run_id="wf-1",
        node_run_id="node-1",
        scope={"teamId": "team-1", "questionId": "SCI-001"},
        provider="formal-provider",
        model="formal-review-model",
        requested_model="formal-review-model",
        request_content={"candidateId": candidate_id},
        response_content={"dimensionReviews": f"seven rows for {candidate_id}"},
        started_at_ms=100,
        finished_at_ms=120,
        metadata={"questionStage": "review"},
        evidence_locator={
            "reviewStep": "reflection",
            "identityParts": [candidate_id],
        },
    ).to_dict()


def test_missing_node_binding_blocks_without_writing(monkeypatch):
    writes = []
    monkeypatch.setattr(writer, "put_workflow_artifact", lambda *args, **kwargs: writes.append(1))
    request = deepcopy(_BASE)
    request["node_run_id"] = ""
    result = writer.materialize_dimension_reviews_authority(**request, review=_review_payload())

    assert result["status"] == "blocked"
    assert "nodeRunId_missing" in result["blockerCodes"]
    assert writes == []


def test_score_only_review_is_not_promoted(monkeypatch):
    writes = []
    monkeypatch.setattr(writer, "put_workflow_artifact", lambda *args, **kwargs: writes.append(1))
    result = writer.materialize_dimension_reviews_authority(
        **_BASE,
        review={
            "candidates": [
                {"candidateId": "H1", "scores": {dimension: 0.8 for dimension in writer.REQUIRED_REVIEW_DIMENSIONS}},
                {"candidateId": "H2", "scores": {dimension: 0.7 for dimension in writer.REQUIRED_REVIEW_DIMENSIONS}},
            ]
        },
    )

    assert result["status"] == "blocked"
    assert "dimension_reviews_missing" in result["blockerCodes"]
    assert writes == []


def test_duplicate_pareto_candidate_blocks_selection(monkeypatch):
    writes = []
    monkeypatch.setattr(writer, "put_workflow_artifact", lambda *args, **kwargs: writes.append(1))
    payload = _review_payload()
    payload["pareto"]["paretoFrontCandidateIds"] = ["H1", "H1"]

    result = writer.materialize_dimension_reviews_authority(**_BASE, review=payload)

    assert result["status"] == "blocked"
    assert "selection_pareto_duplicate_candidates" in result["blockerCodes"]
    assert writes == []


def test_missing_or_duplicate_dimension_blocks(monkeypatch):
    writes = []
    monkeypatch.setattr(writer, "put_workflow_artifact", lambda *args, **kwargs: writes.append(1))
    payload = _review_payload()
    rows = payload["dimensionReviews"]
    assert isinstance(rows, list)
    rows.pop()
    rows.append(dict(rows[0]))
    result = writer.materialize_dimension_reviews_authority(**_BASE, review=payload)

    assert result["status"] == "blocked"
    assert "dimension_review_duplicate" in result["blockerCodes"]
    assert "dimension_reviews_incomplete" in result["blockerCodes"]
    assert writes == []


def test_complete_explicit_rows_write_deterministically(monkeypatch):
    writes = []

    def fake_put(team_id, **kwargs):
        writes.append((team_id, kwargs))
        return {
            "recordId": kwargs["artifact_identity"],
            "workflowRunId": kwargs["workflow_run_id"],
            "sourceCollectionRunId": kwargs["source_collection_run_id"],
            "contentHash": writer.canonical_sha256(kwargs["payload"]),
        }

    monkeypatch.setattr(writer, "put_workflow_artifact", fake_put)
    monkeypatch.setattr(writer, "read_domain_artifact", lambda ref: object())
    request = {**_BASE, "review": _review_payload()}
    first = writer.materialize_dimension_reviews_authority(**request)
    second = writer.materialize_dimension_reviews_authority(**request)

    assert first["status"] == "written"
    assert second["status"] == "written"
    assert first["inputHash"] == second["inputHash"]
    assert first["artifact"]["canonicalRef"] == second["artifact"]["canonicalRef"]
    assert writes[0][1]["artifact_identity"] == writes[1][1]["artifact_identity"]
    payload = writes[0][1]["payload"]
    assert payload["selection"]["selected_hypothesis_id"] == "H1"
    assert payload["selection"]["human_gate"]["decision"] == "pending"
    assert payload["pareto"]["paretoFrontCandidateIds"] == ["H1"]


def test_novelty_contrast_rides_beside_rows_and_keeps_rows_clean(monkeypatch):
    writes = []

    def fake_put(team_id, **kwargs):
        writes.append((team_id, kwargs))
        return {
            "recordId": kwargs["artifact_identity"],
            "workflowRunId": kwargs["workflow_run_id"],
            "sourceCollectionRunId": kwargs["source_collection_run_id"],
            "contentHash": writer.canonical_sha256(kwargs["payload"]),
        }

    monkeypatch.setattr(writer, "put_workflow_artifact", fake_put)
    monkeypatch.setattr(writer, "read_domain_artifact", lambda ref: object())
    review = _review_payload()
    review["candidates"] = [
        {
            "candidateId": "H1",
            "claim": "claim one",
            "literatureContrast": {"papers": [{"title": "T"}], "degraded": False},
            "noveltyContrast": {
                "overlapPapers": ["T"],
                "deltaStatement": "机制不同",
                "basis": "retrieved",
            },
        },
        {"candidateId": "H2", "claim": "claim two"},
    ]

    result = writer.materialize_dimension_reviews_authority(
        **_BASE,
        review=review,
    )

    assert result["status"] == "written"
    payload = writes[0][1]["payload"]
    # The structured conclusion rides beside the rows, keyed by candidate.
    assert payload["noveltyContrastByCandidate"] == {
        "H1": {
            "overlapPapers": ["T"],
            "deltaStatement": "机制不同",
            "basis": "retrieved",
        }
    }
    # The audit rows themselves never gain contrast fields.
    assert all(
        set(row) == {
            "hypothesis_id",
            "dimension",
            "rating",
            "rationale",
            "reviewer",
            "evidence_refs",
        }
        for row in payload["dimensionReviews"]
    )


def test_novelty_contrast_key_absent_without_contrast(monkeypatch):
    writes = []

    def fake_put(team_id, **kwargs):
        writes.append((team_id, kwargs))
        return {
            "recordId": kwargs["artifact_identity"],
            "workflowRunId": kwargs["workflow_run_id"],
            "sourceCollectionRunId": kwargs["source_collection_run_id"],
            "contentHash": writer.canonical_sha256(kwargs["payload"]),
        }

    monkeypatch.setattr(writer, "put_workflow_artifact", fake_put)
    monkeypatch.setattr(writer, "read_domain_artifact", lambda ref: object())
    result = writer.materialize_dimension_reviews_authority(
        **_BASE,
        review=_review_payload(),
    )

    assert result["status"] == "written"
    assert "noveltyContrastByCandidate" not in writes[0][1]["payload"]


def test_formal_rows_bind_each_candidate_to_reflection_receipt(monkeypatch):
    writes = []

    def fake_put(team_id, **kwargs):
        writes.append((team_id, kwargs))
        return {
            "recordId": kwargs["artifact_identity"],
            "workflowRunId": kwargs["workflow_run_id"],
            "sourceCollectionRunId": kwargs["source_collection_run_id"],
            "contentHash": writer.canonical_sha256(kwargs["payload"]),
        }

    monkeypatch.setattr(writer, "put_workflow_artifact", fake_put)
    monkeypatch.setattr(writer, "read_domain_artifact", lambda ref: object())
    review = _review_payload()
    review["executionMode"] = "formal"
    review["modelInvocationReceipts"] = [
        _reflection_receipt("H1"),
        _reflection_receipt("H2"),
    ]

    result = writer.materialize_dimension_reviews_authority(
        **_BASE,
        review=review,
    )

    assert result["status"] == "written"
    payload = writes[0][1]["payload"]
    bindings = payload["reviewReceiptBindings"]
    assert [binding["hypothesis_id"] for binding in bindings] == ["H1", "H2"]
    assert [binding["receipt_id"] for binding in bindings] == [
        "receipt-reflection-H1",
        "receipt-reflection-H2",
    ]
    assert all(len(binding["row_hash"]) == 64 for binding in bindings)
    assert payload["modelInvocationReceipts"] == review["modelInvocationReceipts"]


def test_formal_rows_block_when_candidate_reflection_receipt_is_missing(monkeypatch):
    writes = []
    monkeypatch.setattr(
        writer,
        "put_workflow_artifact",
        lambda *args, **kwargs: writes.append((args, kwargs)),
    )
    monkeypatch.setattr(writer, "read_domain_artifact", lambda ref: object())
    review = _review_payload()
    review["executionMode"] = "formal"
    review["modelInvocationReceipts"] = [_reflection_receipt("H1")]

    result = writer.materialize_dimension_reviews_authority(
        **_BASE,
        review=review,
    )

    assert result["status"] == "blocked"
    assert "dimension_review_receipt_missing" in result["blockerCodes"]
    assert writes == []


def test_executor_preserves_only_runner_dimension_rows():
    def reflection_runner(candidate, _context):
        return {
            "scores": {dimension: 0.8 for dimension in SCORE_DIMENSIONS},
            "dimensionReviews": [
                {
                    "hypothesis_id": candidate["candidateId"],
                    "dimension": dimension,
                    "rating": "adequate",
                    "rationale": f"{candidate['candidateId']} explicit {dimension}",
                    "reviewer": "reviewer-1",
                    "evidence_refs": [_EVIDENCE_REF],
                }
                for dimension in writer.REQUIRED_REVIEW_DIMENSIONS
            ],
        }

    result = hypothesis_review_executor.execute_hypothesis_review(
        {
            "contextId": "review-context-1",
            "candidates": [
                {"candidateId": "H1", "claim": "claim one", "differenceFromAlternatives": "path one"},
                {"candidateId": "H2", "claim": "claim two", "differenceFromAlternatives": "path two"},
            ],
        },
        round_id="round-1",
        reflection_runner=reflection_runner,
        reviewer_assignments={"metareview": "coordinator-1"},
    )

    assert all("dimensionReviews" in candidate for candidate in result["candidates"])
    assert len(result["candidates"][0]["dimensionReviews"]) == 7


def test_executor_rejects_explicit_rows_outside_audit_dimension_authority():
    def reflection_runner(candidate, _context):
        return {
            "scores": {dimension: 0.8 for dimension in SCORE_DIMENSIONS},
            "dimensionReviews": [
                {
                    "hypothesis_id": candidate["candidateId"],
                    "dimension": dimension,
                    "rating": "adequate",
                    "rationale": f"{candidate['candidateId']} wrong {dimension}",
                    "reviewer": "reviewer-1",
                    "evidence_refs": [],
                }
                for dimension in SCORE_DIMENSIONS
            ],
        }

    with pytest.raises(ContractValidationError, match="audit dimensions"):
        hypothesis_review_executor.execute_hypothesis_review(
            {
                "contextId": "review-context-wrong-authority",
                "candidates": [
                    {
                        "candidateId": "H1",
                        "claim": "claim one",
                        "differenceFromAlternatives": "path one",
                    },
                    {
                        "candidateId": "H2",
                        "claim": "claim two",
                        "differenceFromAlternatives": "path two",
                    },
                ],
            },
            round_id="round-wrong-authority",
            reflection_runner=reflection_runner,
            reviewer_assignments={"metareview": "coordinator-1"},
        )
