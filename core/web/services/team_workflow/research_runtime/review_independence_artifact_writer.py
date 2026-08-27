"""Canonical reviewer-independence and review-disagreement artifact writer.

This is the narrow projection writer behind decision #4 of the 13-decision
contract: the selection decision is made jointly by the Pareto front, the
hard gates, and reviewer disagreement — reviewer scores never collapse into a
total.  The module projects an already-executed
``hypothesis_review_executor`` output (candidates, pairwise comparisons,
roles) plus the review receipt contexts into two immutable canonical
artifacts:

- ``review_independence`` — one :class:`ReviewerIndependenceRecord` per unique
  review-step instance, with the fail-closed same-source pseudo-independence
  gate (a duplicated step instance is never silently deduplicated).
- ``review_disagreement`` — the :class:`ReviewDisagreementArtifact` payload:
  candidate pairs, per-reviewer five-dimension score references, decision-axis
  disagreement metrics, and an escalation that is marked only.

This writer never re-runs or re-scores a review step; incomplete input
produces a structured ``NEEDS_CONTEXT`` result without writing anything.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core.research.workflow.contracts import ContractValidationError
from core.research.workflow.contracts.hypothesis_round import COMPARISON_OUTCOMES
from core.research.workflow.contracts.review_independence import (
    ESCALATION_STATUS_FLAGGED_ONLY,
    REVIEW_DISAGREEMENT_SCHEMA_VERSION,
    REVIEW_INDEPENDENCE_SCHEMA_VERSION,
    ReviewDisagreementArtifact,
    ReviewPairDisagreement,
    ReviewScoreRef,
    ReviewerIndependenceRecord,
    inconsistent_axes_for_pair,
    review_step_identity,
    reviewer_independence_summary,
    validate_step_independence,
)

from .artifact_readback_registry import build_canonical_ref
from .human_gate_artifacts import canonical_sha256
from .workflow_artifact_store import put_workflow_artifact

SCHEMA_VERSION = 1
ARTIFACT_KIND = "review_independence"
DISAGREEMENT_ARTIFACT_KIND = "review_disagreement"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sha256(value: Any) -> str:
    text = _text(value).lower()
    return text if len(text) == 64 and all(char in "0123456789abcdef" for char in text) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _text(item)
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def compute_independence_input_hash(
    *,
    team_id: str,
    workflow_run_id: str,
    node_run_id: str,
    review_round_id: str,
    review_context_id: str,
    step_identities: Sequence[str],
    reviewer_ids: Sequence[str],
) -> str:
    """Hash the independence inputs, excluding any disagreement conclusion."""

    return canonical_sha256(
        {
            "teamId": _text(team_id),
            "workflowRunId": _text(workflow_run_id),
            "nodeRunId": _text(node_run_id),
            "reviewRoundId": _text(review_round_id),
            "reviewContextId": _text(review_context_id),
            "stepIdentities": _string_list(step_identities),
            "reviewerIds": _string_list(reviewer_ids),
        }
    )


def _binding_blockers(
    *,
    team_id: str,
    workflow_run_id: str,
    node_run_id: str,
    review_round_id: str,
    review_context_id: str,
) -> list[str]:
    required = {
        "teamId": team_id,
        "workflowRunId": workflow_run_id,
        "reviewRoundId": review_round_id,
        "reviewContextId": review_context_id,
    }
    return [
        f"{field[0].lower() + field[1:]}_missing"
        for field, value in required.items()
        if not value
    ]


def _receipt_ref_for_step(
    *,
    review_step: str,
    identity_parts: Sequence[str],
    receipt_contexts: Sequence[Mapping[str, Any]],
) -> str:
    """Match one step instance to its minted receipt context invocation id."""

    for receipt_context in receipt_contexts:
        locator = _mapping(_mapping(receipt_context).get("evidenceLocator"))
        if _text(locator.get("reviewStep")) != review_step:
            continue
        context_parts = _string_list(locator.get("identityParts"))
        if list(context_parts) != [str(part or "").strip() for part in identity_parts]:
            continue
        invocation_id = _text(_mapping(receipt_context).get("invocationId"))
        if invocation_id:
            return invocation_id
    return ""


def _candidate_map(review: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _text(item.get("candidateId")): dict(item)
        for item in list(review.get("candidates") or [])
        if isinstance(item, Mapping) and _text(item.get("candidateId"))
    }


def _independence_records(
    *,
    review: Mapping[str, Any],
    reviewer_assignments: Mapping[str, Any],
    receipt_contexts: Sequence[Mapping[str, Any]],
    team_id: str,
    workflow_run_id: str,
    review_round_id: str,
    review_context_id: str,
    execution_mode: str,
) -> tuple[list[ReviewerIndependenceRecord], list[str]]:
    """Project one record per unique review-step instance (fail-closed)."""

    blockers: list[str] = []
    roles = _mapping(review.get("roles"))
    assignments = {key: _text(value) for key, value in _mapping(reviewer_assignments).items()}
    records: list[ReviewerIndependenceRecord] = []
    step_identities: list[str] = []
    reviewer_ids: list[str] = []

    def _source(step: str) -> str:
        return "reviewer_assignments" if assignments.get(step) else "executor_role_default"

    def _role(step: str) -> str:
        return _text(roles.get(step)) or step

    def _append(
        step: str,
        identity_parts: tuple[str, ...],
        reviewer_id: str,
        *,
        blocker: str,
    ) -> None:
        reviewer = _text(reviewer_id)
        if not reviewer:
            blockers.append(blocker)
            return
        identity = review_step_identity(step, review_context_id, identity_parts)
        receipt_ref = ""
        if execution_mode == "formal":
            receipt_ref = _receipt_ref_for_step(
                review_step=step,
                identity_parts=identity_parts,
                receipt_contexts=receipt_contexts,
            )
            if not receipt_ref:
                blockers.append("review_independence_receipt_ref_missing")
                return
        records.append(
            ReviewerIndependenceRecord.from_dict(
                {
                    "recordId": f"reviewer-independence:{identity}",
                    "teamId": team_id,
                    "workflowRunId": workflow_run_id,
                    "reviewRoundId": review_round_id,
                    "reviewContextId": review_context_id,
                    "reviewStep": step,
                    "stepIdentity": identity,
                    "reviewerId": reviewer,
                    "reviewerRole": _role(step),
                    "assignmentSource": _source(step),
                    "receiptRef": receipt_ref,
                    "executionMode": execution_mode,
                }
            )
        )
        step_identities.append(identity)
        reviewer_ids.append(reviewer)

    candidates = _candidate_map(review)
    for candidate_id, candidate in candidates.items():
        _append(
            "reflection",
            (candidate_id,),
            _text(candidate.get("reviewedBy")),
            blocker="review_independence_reflection_reviewer_missing",
        )
    for comparison in list(review.get("pairwiseComparisons") or []):
        row = _mapping(comparison)
        left = _text(row.get("leftCandidateId"))
        right = _text(row.get("rightCandidateId"))
        if not left or not right:
            blockers.append("review_independence_comparison_incomplete")
            continue
        _append(
            "pairwise",
            (left, right),
            _text(row.get("reviewerAgentId")),
            blocker="review_independence_pairwise_reviewer_missing",
        )
    pareto = _mapping(review.get("pareto"))
    if pareto:
        _append(
            "pareto",
            ("round",),
            _text(pareto.get("analystAgentId")),
            blocker="review_independence_pareto_reviewer_missing",
        )
    else:
        blockers.append("review_independence_pareto_missing")
    meta_review = _mapping(review.get("metaReview"))
    if meta_review:
        _append(
            "metareview",
            (_text(meta_review.get("metaReviewId")) or "round",),
            _text(meta_review.get("reviewerAgentId")),
            blocker="review_independence_metareview_reviewer_missing",
        )
    else:
        blockers.append("review_independence_metareview_missing")

    if not records:
        blockers.append("review_independence_records_missing")
        return records, blockers

    # Fail-closed same-source pseudo-independence gate: a repeated step
    # instance (same reviewer or conflicting reviewers) rejects the write
    # instead of being counted as an extra independent review.
    try:
        validate_step_independence(records)
    except ContractValidationError:
        blockers.append("reviewer_pseudo_independence_double_count")
        return [], list(dict.fromkeys(blockers))

    summary = reviewer_independence_summary(records)
    if summary["uniqueStepCount"] != len(step_identities):  # pragma: no cover - defensive
        blockers.append("reviewer_pseudo_independence_double_count")
    return records, list(dict.fromkeys(blockers))


def _disagreement_artifact(
    *,
    review: Mapping[str, Any],
    review_round_id: str,
    review_context_id: str,
) -> tuple[ReviewDisagreementArtifact | None, list[str]]:
    """Project the disagreement payload from reflection scores vs pairwise outcomes."""

    blockers: list[str] = []
    candidates = _candidate_map(review)
    comparisons = [
        _mapping(item)
        for item in list(review.get("pairwiseComparisons") or [])
        if isinstance(item, Mapping)
    ]
    if not comparisons:
        blockers.append("review_disagreement_comparisons_missing")
    score_refs: list[ReviewScoreRef] = []
    for candidate_id, candidate in candidates.items():
        scores = candidate.get("scores")
        if not isinstance(scores, Mapping) or not scores:
            blockers.append("review_disagreement_candidate_scores_missing")
            continue
        reviewer = _text(candidate.get("reviewedBy"))
        if not reviewer:
            blockers.append("review_disagreement_candidate_reviewer_missing")
            continue
        score_refs.append(
            ReviewScoreRef.from_dict(
                {
                    "candidateId": candidate_id,
                    "reviewerId": reviewer,
                    "scoreRef": (
                        f"hypothesis_review:{review_context_id}"
                        f"/candidate/{candidate_id}/scores"
                    ),
                }
            )
        )
    if not score_refs:
        blockers.append("review_disagreement_score_refs_missing")

    pair_rows: list[ReviewPairDisagreement] = []
    axis_counts: dict[str, int] = {}
    for comparison in comparisons:
        comparison_id = _text(comparison.get("comparisonId"))
        left_id = _text(comparison.get("leftCandidateId"))
        right_id = _text(comparison.get("rightCandidateId"))
        outcome = _text(comparison.get("outcome")).lower()
        if not comparison_id or not left_id or not right_id:
            blockers.append("review_disagreement_comparison_incomplete")
            continue
        if outcome not in COMPARISON_OUTCOMES:
            blockers.append("review_disagreement_comparison_outcome_invalid")
            continue
        if left_id == right_id or left_id not in candidates or right_id not in candidates:
            blockers.append("review_disagreement_comparison_unknown_candidate")
            continue
        left_scores = _mapping(candidates[left_id].get("scores"))
        right_scores = _mapping(candidates[right_id].get("scores"))
        inconsistent = inconsistent_axes_for_pair(left_scores, right_scores, outcome)
        pair_rows.append(
            ReviewPairDisagreement.from_dict(
                {
                    "comparisonId": comparison_id,
                    "leftCandidateId": left_id,
                    "rightCandidateId": right_id,
                    "outcome": outcome,
                    "inconsistentAxes": list(inconsistent),
                }
            )
        )
        for axis in inconsistent:
            axis_counts[axis] = axis_counts.get(axis, 0) + 1

    ordered_axes = tuple(axis for axis in (
        "novelty",
        "competitionFit",
        "falsifiability",
        "evidenceSupport",
        "feasibility",
    ) if axis in axis_counts)
    metrics = [
        {"axis": axis, "directionInconsistencyCount": axis_counts[axis]}
        for axis in ordered_axes
    ]
    escalation_reason = ""
    if ordered_axes:
        escalation_reason = (
            "pairwise outcome direction contradicts reflection score direction on: "
            + ", ".join(ordered_axes)
        )
    if blockers:
        return None, list(dict.fromkeys(blockers))
    artifact = ReviewDisagreementArtifact.from_dict(
        {
            "reviewRoundId": review_round_id,
            "reviewContextId": review_context_id,
            "candidatePairs": [item.to_dict() for item in pair_rows],
            "reviewerScoreRefs": [item.to_dict() for item in score_refs],
            "disagreementAxes": list(ordered_axes),
            "disagreementMetrics": metrics,
            "escalation": {
                "required": bool(ordered_axes),
                "reason": escalation_reason,
                "status": ESCALATION_STATUS_FLAGGED_ONLY,
            },
        }
    )
    return artifact, []


def _artifact_descriptor(
    *,
    team_id: str,
    kind: str,
    source_collection_run_id: str,
    payload: Mapping[str, Any],
    record: Mapping[str, Any],
) -> dict[str, Any]:
    envelope = {
        "teamId": team_id,
        "kind": kind,
        "workflowRunId": _text(record.get("workflowRunId")),
        "sourceCollectionRunId": _text(record.get("sourceCollectionRunId"))
        or source_collection_run_id,
        "payload": dict(payload),
    }
    canonical_hash = canonical_sha256(envelope)
    return {
        "recordId": _text(record.get("recordId")),
        "kind": kind,
        "workflowRunId": _text(envelope["workflowRunId"]),
        "sourceCollectionRunId": _text(envelope["sourceCollectionRunId"]),
        "contentHash": _text(record.get("contentHash")),
        "canonicalHash": canonical_hash,
        "canonicalRef": build_canonical_ref(
            kind=kind,
            team_id=team_id,
            authority_run_id=_text(envelope["sourceCollectionRunId"]),
            content_hash=canonical_hash,
        ),
    }


def write_review_independence_artifacts(
    *,
    team_id: Any,
    workflow_run_id: Any,
    node_run_id: Any = "",
    review_round_id: Any,
    review: Mapping[str, Any] | None = None,
    reviewer_assignments: Mapping[str, Any] | None = None,
    receipt_contexts: Sequence[Mapping[str, Any]] = (),
    source_collection_run_id: Any = "",
) -> dict[str, Any]:
    """Write the ``review_independence`` and ``review_disagreement`` artifacts.

    Pure projection + persistence: the review itself is never re-executed and
    no score is recomputed.  Exact replay with the same inputs reuses the
    stored artifact record (idempotent), while any blocker yields a structured
    ``NEEDS_CONTEXT`` result without writing anything.
    """

    team = _text(team_id)
    run = _text(workflow_run_id)
    node = _text(node_run_id)
    review_round = _text(review_round_id)
    review_payload = _mapping(review)
    review_context_id = _text(review_payload.get("reviewContextId"))
    execution_mode = (
        _text(review_payload.get("executionMode")).lower() or "dev"
    )
    source_run = _text(source_collection_run_id) or run
    binding = {
        "teamId": team,
        "workflowRunId": run,
        "nodeRunId": node,
        "reviewRoundId": review_round,
        "reviewContextId": review_context_id,
        "sourceCollectionRunId": source_run,
    }
    blockers = _binding_blockers(
        team_id=team,
        workflow_run_id=run,
        node_run_id=node,
        review_round_id=review_round,
        review_context_id=review_context_id,
    )
    if not review_payload:
        blockers.append("review_output_missing")
    if execution_mode not in ("dev", "formal"):
        blockers.append("review_execution_mode_invalid")

    records: list[ReviewerIndependenceRecord] = []
    independence_payload: dict[str, Any] | None = None
    disagreement_payload: dict[str, Any] | None = None
    summary: dict[str, Any] = {}
    disagreement: ReviewDisagreementArtifact | None = None
    if review_payload and execution_mode in ("dev", "formal"):
        try:
            records, record_blockers = _independence_records(
                review=review_payload,
                reviewer_assignments=_mapping(reviewer_assignments),
                receipt_contexts=[_mapping(item) for item in receipt_contexts],
                team_id=team,
                workflow_run_id=run,
                review_round_id=review_round,
                review_context_id=review_context_id,
                execution_mode=execution_mode,
            )
        except ContractValidationError:
            records, record_blockers = [], ["review_independence_invalid"]
        blockers.extend(record_blockers)
        if records:
            summary = reviewer_independence_summary(records)
            input_hash = compute_independence_input_hash(
                team_id=team,
                workflow_run_id=run,
                node_run_id=node,
                review_round_id=review_round,
                review_context_id=review_context_id,
                step_identities=[record.stepIdentity for record in records],
                reviewer_ids=[record.reviewerId for record in records],
            )
            independence_payload = {
                "schemaVersion": REVIEW_INDEPENDENCE_SCHEMA_VERSION,
                "artifactKind": ARTIFACT_KIND,
                **binding,
                "inputHash": input_hash,
                "records": [record.to_dict() for record in records],
                "summary": summary,
            }
        try:
            disagreement, artifact_blockers = _disagreement_artifact(
                review=review_payload,
                review_round_id=review_round,
                review_context_id=review_context_id,
            )
        except ContractValidationError:
            disagreement, artifact_blockers = None, ["review_disagreement_invalid"]
        blockers.extend(artifact_blockers)
        if disagreement is not None:
            input_hash = canonical_sha256(disagreement.to_dict())
            disagreement_payload = {
                "schemaVersion": REVIEW_DISAGREEMENT_SCHEMA_VERSION,
                "artifactKind": DISAGREEMENT_ARTIFACT_KIND,
                **binding,
                "inputHash": input_hash,
                **disagreement.to_dict(),
            }

    result: dict[str, Any] = {
        "status": "blocked",
        "reason": "NEEDS_CONTEXT",
        "blockerCodes": list(dict.fromkeys(blockers)),
        "binding": binding,
        "reviewIndependence": None,
        "reviewDisagreement": None,
    }
    if blockers or independence_payload is None or disagreement_payload is None:
        return result

    independence_record = put_workflow_artifact(
        team,
        kind=ARTIFACT_KIND,
        workflow_run_id=run,
        source_collection_run_id=source_run,
        artifact_identity=(
            f"{ARTIFACT_KIND}:{node}:{review_round}:{independence_payload['inputHash']}"
        ),
        payload=independence_payload,
    )
    disagreement_record = put_workflow_artifact(
        team,
        kind=DISAGREEMENT_ARTIFACT_KIND,
        workflow_run_id=run,
        source_collection_run_id=source_run,
        artifact_identity=(
            f"{DISAGREEMENT_ARTIFACT_KIND}:{node}:{review_round}"
            f":{disagreement_payload['inputHash']}"
        ),
        payload=disagreement_payload,
    )
    result["status"] = "written"
    result["reason"] = ""
    result["blockerCodes"] = []
    result["reviewIndependence"] = {
        "artifact": _artifact_descriptor(
            team_id=team,
            kind=ARTIFACT_KIND,
            source_collection_run_id=source_run,
            payload=independence_payload,
            record=independence_record,
        ),
        "recordCount": len(records),
        "summary": summary,
    }
    result["reviewDisagreement"] = {
        "artifact": _artifact_descriptor(
            team_id=team,
            kind=DISAGREEMENT_ARTIFACT_KIND,
            source_collection_run_id=source_run,
            payload=disagreement_payload,
            record=disagreement_record,
        ),
        "disagreementAxes": list(disagreement.disagreementAxes),
        "escalationRequired": disagreement.escalation.required,
        "escalationStatus": disagreement.escalation.status,
    }
    return result


# A descriptive alias keeps callers independent from the storage verb.
write_independence_artifacts = write_review_independence_artifacts


__all__ = [
    "ARTIFACT_KIND",
    "DISAGREEMENT_ARTIFACT_KIND",
    "SCHEMA_VERSION",
    "compute_independence_input_hash",
    "review_step_identity",
    "write_independence_artifacts",
    "write_review_independence_artifacts",
]
