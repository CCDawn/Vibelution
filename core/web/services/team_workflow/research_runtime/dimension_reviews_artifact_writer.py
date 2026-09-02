"""Materialize the Challenge Cup seven-dimension review authority.

``HypothesisRound`` is an executable review projection.  The v2 result
package, however, needs an independent canonical authority for
``dimension_reviews``.  This module is the narrow writer for that authority:
it accepts only explicit per-hypothesis/per-dimension rows and persists them
through the formal workflow artifact store.

Scores, totals, Pareto classifications, summaries, and model receipts are not
review rows.  When any binding or row is incomplete the writer returns a
structured ``NEEDS_CONTEXT`` result and does not write an artifact.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from core.research.competition.question_result_package import (
    REQUIRED_REVIEW_DIMENSIONS,
    REVIEW_DIMENSION_RATINGS,
)
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
    ModelInvocationStatus,
)

from .artifact_readback_registry import (
    build_canonical_ref,
    parse_canonical_ref,
    read_domain_artifact,
)
from .human_gate_artifacts import canonical_sha256
from .workflow_artifact_store import put_workflow_artifact

SCHEMA_VERSION = 1
ARTIFACT_KIND = "dimension_reviews"
SELECTION_COMPARISON_METHOD = "multi_dimension_pareto_plus_human_decision"
_ALLOWED_RATINGS = frozenset(REVIEW_DIMENSION_RATINGS)


def _text(value: Any) -> str:
    return str(value or "").strip()


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


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sha256(value: Any) -> str:
    text = _text(value).lower()
    return text if len(text) == 64 and all(char in "0123456789abcdef" for char in text) else ""


def _candidate_id(value: Mapping[str, Any]) -> str:
    return _text(value.get("candidateId") or value.get("candidate_id") or value.get("hypothesis_id"))


def _candidate_scope(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Keep stable candidate inputs in the deterministic input hash only."""

    return {
        "candidateId": _candidate_id(candidate),
        "claim": _text(candidate.get("claim") or candidate.get("statement")),
        "rationale": _text(candidate.get("rationale") or candidate.get("mechanism")),
        "differenceFromAlternatives": _text(
            candidate.get("differenceFromAlternatives")
            or candidate.get("novelty_basis")
        ),
        "lineageRefs": _string_list(candidate.get("lineageRefs") or candidate.get("lineage_refs")),
        "evidenceRefs": _string_list(
            candidate.get("evidenceRefs") or candidate.get("evidence_refs")
        ),
    }


def compute_input_hash(
    *,
    team_id: str,
    workflow_run_id: str,
    node_run_id: str,
    question_id: str,
    selection_id: str,
    review_round_id: str,
    input_refs: Sequence[str],
    input_snapshot_hash: str,
    source_collection_run_id: str = "",
    candidates: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Compute a stable hash of the review inputs, excluding review output."""

    return canonical_sha256(
        {
            "teamId": _text(team_id),
            "workflowRunId": _text(workflow_run_id),
            "nodeRunId": _text(node_run_id),
            "questionId": _text(question_id).upper(),
            "selectionId": _text(selection_id),
            "reviewRoundId": _text(review_round_id),
            "inputRefs": _string_list(input_refs),
            "inputSnapshotHash": _sha256(input_snapshot_hash),
            "sourceCollectionRunId": _text(source_collection_run_id),
            "candidates": [
                _candidate_scope(item)
                for item in candidates
                if isinstance(item, Mapping)
            ],
        }
    )


def _review_rows(review: Mapping[str, Any] | Sequence[Any] | None) -> list[dict[str, Any]]:
    """Extract explicit rows from the supported review result shapes.

    The current executor emits ``scores`` only.  It is intentionally ignored;
    only a direct ``dimensionReviews`` list or nested per-candidate rows can
    satisfy this authority.
    """

    if isinstance(review, Sequence) and not isinstance(review, (str, bytes, bytearray)):
        return [dict(item) for item in review if isinstance(item, Mapping)]
    source = _mapping(review)
    direct = source.get("dimensionReviews") or source.get("dimension_reviews")
    rows: list[dict[str, Any]] = []
    if isinstance(direct, (list, tuple)):
        rows.extend(dict(item) for item in direct if isinstance(item, Mapping))
    nested_candidates = source.get("candidates")
    if isinstance(nested_candidates, (list, tuple)):
        for candidate in nested_candidates:
            if not isinstance(candidate, Mapping):
                continue
            candidate_id = _candidate_id(candidate)
            nested = candidate.get("dimensionReviews") or candidate.get("dimension_reviews")
            if not isinstance(nested, (list, tuple)):
                continue
            for item in nested:
                if not isinstance(item, Mapping):
                    continue
                row = dict(item)
                if not _candidate_id(row) and candidate_id:
                    row["hypothesis_id"] = candidate_id
                rows.append(row)
    return rows


def _validate_rows(
    review: Mapping[str, Any] | Sequence[Any] | None,
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    candidate_id_list = [
        _candidate_id(item)
        for item in candidates
        if isinstance(item, Mapping) and _candidate_id(item)
    ]
    candidate_ids = {
        candidate_id for candidate_id in candidate_id_list if candidate_id
    }
    blockers: list[str] = []
    if len(candidate_id_list) != len(candidate_ids):
        blockers.append("hypotheses_duplicate")
    if len(candidate_ids) < 2:
        blockers.append("hypotheses_missing_or_not_unique")

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    raw_rows = _review_rows(review)
    if not raw_rows:
        blockers.append("dimension_reviews_missing")
    for raw in raw_rows:
        hypothesis_id = _candidate_id(raw)
        dimension = _text(raw.get("dimension"))
        rating = _text(raw.get("rating")).lower()
        rationale = _text(raw.get("rationale"))
        reviewer = _text(raw.get("reviewer") or raw.get("reviewerId") or raw.get("reviewerAgentId"))
        evidence_refs = _string_list(raw.get("evidence_refs") or raw.get("evidenceRefs"))
        key = (hypothesis_id, dimension)

        if not hypothesis_id:
            blockers.append("dimension_review_hypothesis_id_missing")
        elif hypothesis_id not in candidate_ids:
            blockers.append("dimension_review_unknown_hypothesis")
        if dimension not in REQUIRED_REVIEW_DIMENSIONS:
            blockers.append("dimension_review_unknown_dimension")
        if key in seen:
            blockers.append("dimension_review_duplicate")
        seen.add(key)
        if rating not in _ALLOWED_RATINGS:
            blockers.append("dimension_review_rating_invalid_or_missing")
        if not rationale:
            blockers.append("dimension_review_rationale_missing")
        if not reviewer:
            blockers.append("dimension_review_reviewer_missing")
        if not evidence_refs:
            blockers.append("dimension_review_evidence_refs_missing")
        for ref in evidence_refs:
            parsed = parse_canonical_ref(ref)
            if parsed is None or parsed.get("legacy") == "1":
                blockers.append("dimension_review_evidence_ref_invalid")
                continue
            try:
                readback = read_domain_artifact(ref)
            except Exception:
                readback = None
            if readback is None:
                blockers.append("dimension_review_evidence_ref_unreadable")
        rows.append(
            {
                "hypothesis_id": hypothesis_id,
                "dimension": dimension,
                "rating": rating,
                "rationale": rationale,
                "reviewer": reviewer,
                "evidence_refs": evidence_refs,
            }
        )

    expected = {
        (candidate_id, dimension)
        for candidate_id in candidate_ids
        for dimension in REQUIRED_REVIEW_DIMENSIONS
    }
    missing = expected - seen
    if missing:
        blockers.append("dimension_reviews_incomplete")
    unexpected = seen - expected
    if unexpected:
        blockers.append("dimension_reviews_out_of_scope")
    if len(rows) != len(seen):
        blockers.append("dimension_review_duplicate")
    return rows, list(dict.fromkeys(blockers))


def _selection_from_review(
    review: Mapping[str, Any] | Sequence[Any] | None,
    candidate_ids: Sequence[str],
) -> tuple[dict[str, Any] | None, list[str], dict[str, Any], dict[str, Any]]:
    """Build a pending selection from explicit Pareto and MetaReview facts.

    The selection is a proposal, not a human decision: the MetaReview
    recommendation supplies the proposed candidate while ``human_gate`` stays
    pending.  No score, score ordering, or generated rationale is consulted.
    """

    source = _mapping(review)
    if isinstance(source.get("round"), Mapping):
        nested = dict(source["round"])
        nested.update({key: value for key, value in source.items() if key != "round"})
        source = nested
    pareto = _mapping(source.get("pareto"))
    meta_review = _mapping(source.get("metaReview") or source.get("meta_review"))
    blockers: list[str] = []
    candidate_set = set(candidate_ids)
    raw_front = [
        _text(item)
        for item in list(
            pareto.get("paretoFrontCandidateIds")
            or pareto.get("pareto_front_candidate_ids")
            or []
        )
        if _text(item)
    ]
    raw_dominated = [
        _text(item)
        for item in list(
            pareto.get("dominatedCandidateIds")
            or pareto.get("dominated_candidate_ids")
            or []
        )
        if _text(item)
    ]
    front = _string_list(
        pareto.get("paretoFrontCandidateIds")
        or pareto.get("pareto_front_candidate_ids")
    )
    dominated = _string_list(
        pareto.get("dominatedCandidateIds")
        or pareto.get("dominated_candidate_ids")
    )
    if not front and not dominated:
        blockers.append("selection_pareto_missing")
    if len(raw_front) != len(front) or len(raw_dominated) != len(dominated):
        blockers.append("selection_pareto_duplicate_candidates")
    if set(front) & set(dominated):
        blockers.append("selection_pareto_overlap")
    if (set(front) | set(dominated)) - candidate_set:
        blockers.append("selection_pareto_unknown_candidate")
    if candidate_set - (set(front) | set(dominated)):
        blockers.append("selection_pareto_incomplete")

    recommendation = _text(
        meta_review.get("recommendationCandidateId")
        or meta_review.get("recommendation_candidate_id")
    )
    if not recommendation:
        blockers.append("selection_meta_review_recommendation_missing")
    elif recommendation not in candidate_set:
        blockers.append("selection_meta_review_unknown_candidate")
    elif recommendation not in set(front):
        blockers.append("selection_meta_review_recommendation_not_pareto_front")
    if not meta_review:
        blockers.append("selection_meta_review_missing")
    if meta_review and meta_review.get("accepted") is not True:
        blockers.append("selection_meta_review_not_accepted")
    meta_rationale = _text(meta_review.get("rationale"))
    risk_notes = _text(meta_review.get("riskNotes") or meta_review.get("risk_notes"))
    pareto_notes = _text(pareto.get("notes"))
    tradeoffs: list[str] = []
    if meta_rationale:
        tradeoffs.append(f"MetaReview rationale: {meta_rationale}")
    if risk_notes:
        tradeoffs.append(f"MetaReview risk notes: {risk_notes}")
    if pareto_notes:
        tradeoffs.append(f"Pareto notes: {pareto_notes}")
    if not tradeoffs:
        blockers.append("selection_basis_rationale_missing")

    if blockers:
        return None, list(dict.fromkeys(blockers)), pareto, meta_review

    rejected = []
    for candidate_id in candidate_ids:
        if candidate_id == recommendation:
            continue
        if candidate_id in set(dominated):
            reason = "Pareto classified this candidate as dominated; human selection remains pending."
        else:
            reason = (
                f"Pareto-front alternative to the explicit MetaReview recommendation {recommendation}; "
                "human selection remains pending."
            )
        rejected.append({"hypothesis_id": candidate_id, "reason": reason})
    selection = {
        "selected_hypothesis_id": recommendation,
        "comparison_method": SELECTION_COMPARISON_METHOD,
        "tradeoffs": tradeoffs,
        "rejected_hypotheses": rejected,
        "human_gate": {
            "required": True,
            "decision": "pending",
            "rationale": "The explicit MetaReview recommendation is awaiting human confirmation.",
        },
    }
    return selection, [], pareto, meta_review


def _review_receipt_bindings(
    review: Mapping[str, Any] | Sequence[Any] | None,
    *,
    workflow_run_id: str,
    candidate_ids: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]], list[str]]:
    """Bind FORMAL reflection receipts to the exact audit rows they produced."""

    source = _mapping(review)
    if _text(source.get("executionMode")).lower() != "formal":
        return [], [], []
    blockers: list[str] = []
    parsed_receipts: list[dict[str, Any]] = []
    reflection_receipts: dict[str, str] = {}
    for raw in list(source.get("modelInvocationReceipts") or []):
        if not isinstance(raw, Mapping):
            blockers.append("dimension_review_receipt_invalid")
            continue
        try:
            receipt = ModelInvocationReceipt.from_dict(raw)
        except (TypeError, ValueError):
            blockers.append("dimension_review_receipt_invalid")
            continue
        if (
            receipt.run_id != workflow_run_id
            or receipt.status
            not in {ModelInvocationStatus.SUCCEEDED, ModelInvocationStatus.RETRIED}
            or _text(receipt.metadata.get("questionStage")).lower() != "review"
        ):
            blockers.append("dimension_review_receipt_scope_invalid")
            continue
        parsed_receipts.append(receipt.to_dict())
        locator = _mapping(receipt.evidence_locator)
        if _text(locator.get("reviewStep")).lower() != "reflection":
            continue
        identity_parts = _string_list(locator.get("identityParts"))
        if len(identity_parts) != 1 or identity_parts[0] not in candidate_ids:
            blockers.append("dimension_review_receipt_candidate_invalid")
            continue
        candidate_id = identity_parts[0]
        if candidate_id in reflection_receipts:
            blockers.append("dimension_review_receipt_duplicate")
            continue
        reflection_receipts[candidate_id] = receipt.receipt_id
    if any(candidate_id not in reflection_receipts for candidate_id in candidate_ids):
        blockers.append("dimension_review_receipt_missing")
    bindings = [
        {
            "hypothesis_id": candidate_id,
            "receipt_id": reflection_receipts[candidate_id],
            "row_hash": canonical_sha256(
                [
                    dict(row)
                    for row in rows
                    if _candidate_id(row) == candidate_id
                ]
            ),
        }
        for candidate_id in candidate_ids
        if candidate_id in reflection_receipts
    ]
    return bindings, parsed_receipts, list(dict.fromkeys(blockers))


def _binding_blockers(
    *,
    team_id: str,
    workflow_run_id: str,
    node_run_id: str,
    question_id: str,
    selection_id: str,
    review_round_id: str,
    input_refs: Sequence[str],
    input_snapshot_hash: str,
    workflow_authority: Mapping[str, Any] | None,
) -> list[str]:
    blockers: list[str] = []
    required = {
        "teamId": team_id,
        "workflowRunId": workflow_run_id,
        "nodeRunId": node_run_id,
        "questionId": question_id,
        "selectionId": selection_id,
        "reviewRoundId": review_round_id,
        "inputSnapshotHash": input_snapshot_hash,
    }
    blockers.extend(
        f"{field[0].lower() + field[1:]}_missing"
        for field, value in required.items()
        if not _text(value)
    )
    if not _sha256(input_snapshot_hash):
        blockers.append("input_snapshot_hash_invalid")
    if not _string_list(input_refs):
        blockers.append("input_refs_missing")
    authority = _mapping(workflow_authority)
    if not authority:
        blockers.append("workflow_authority_missing")
        return list(dict.fromkeys(blockers))
    if _text(authority.get("teamId")) != _text(team_id):
        blockers.append("workflow_authority_team_mismatch")
    if _text(authority.get("workflowRunId")) != _text(workflow_run_id):
        blockers.append("workflow_authority_run_mismatch")
    if _text(authority.get("questionId")).upper() != _text(question_id).upper():
        blockers.append("workflow_authority_question_mismatch")
    authority_node = _text(authority.get("nodeRunId"))
    if authority_node and authority_node != _text(node_run_id):
        blockers.append("workflow_authority_node_mismatch")
    return list(dict.fromkeys(blockers))


def _artifact_descriptor(
    *,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
    payload: Mapping[str, Any],
    record: Mapping[str, Any],
) -> dict[str, Any]:
    envelope = {
        "teamId": team_id,
        "kind": ARTIFACT_KIND,
        "workflowRunId": _text(record.get("workflowRunId")) or workflow_run_id,
        "sourceCollectionRunId": _text(record.get("sourceCollectionRunId"))
        or source_collection_run_id,
        "payload": dict(payload),
    }
    canonical_hash = canonical_sha256(envelope)
    authority_run_id = _text(envelope["sourceCollectionRunId"])
    return {
        "recordId": _text(record.get("recordId")),
        "kind": ARTIFACT_KIND,
        "workflowRunId": _text(envelope["workflowRunId"]),
        "sourceCollectionRunId": authority_run_id,
        "contentHash": _text(record.get("contentHash")),
        "canonicalHash": canonical_hash,
        "canonicalRef": build_canonical_ref(
            kind=ARTIFACT_KIND,
            team_id=team_id,
            authority_run_id=authority_run_id,
            content_hash=canonical_hash,
        ),
    }


def _novelty_contrasts_from_review(
    review: Mapping[str, Any] | Sequence[Any] | None,
) -> dict[str, dict[str, Any]]:
    """Extract per-candidate structured novelty conclusions from a round.

    Reads the candidate-level ``noveltyContrast`` objects written by the
    reflection runner (via the executor).  Lenient by contract: anything
    missing or malformed is skipped, and candidates without a meaningful
    conclusion produce no entry.  The output is keyed by candidateId and
    carries only the three audited fields.
    """

    if not isinstance(review, Mapping):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for candidate in list(review.get("candidates") or []):
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = _candidate_id(candidate)
        raw = candidate.get("noveltyContrast")
        if not candidate_id or not isinstance(raw, Mapping):
            continue
        overlap = _string_list(raw.get("overlapPapers") or raw.get("overlap_papers"))
        delta = _text(raw.get("deltaStatement") or raw.get("delta_statement"))
        basis = _text(raw.get("basis")).lower()
        if basis not in {"retrieved", "degraded"}:
            continue
        if not overlap and not delta:
            continue
        result[candidate_id] = {
            "overlapPapers": overlap,
            "deltaStatement": delta,
            "basis": basis,
        }
    return result


def materialize_dimension_reviews_authority(
    *,
    team_id: Any,
    workflow_run_id: Any,
    node_run_id: Any = "",
    question_id: Any,
    selection_id: Any,
    review_round_id: Any,
    input_refs: Sequence[Any] = (),
    input_snapshot_hash: Any = "",
    candidates: Sequence[Mapping[str, Any]] = (),
    review: Mapping[str, Any] | Sequence[Any] | None = None,
    workflow_authority: Mapping[str, Any] | None = None,
    source_collection_run_id: Any = "",
) -> dict[str, Any]:
    """Write one immutable canonical ``dimension_reviews`` artifact.

    The function is deliberately fail-closed.  A blocked response is useful
    to readiness probes, but it is not a review artifact and never writes a
    placeholder payload.
    """

    team = _text(team_id)
    run = _text(workflow_run_id)
    node = _text(node_run_id) or _text(_mapping(workflow_authority).get("nodeRunId"))
    question = _text(question_id).upper()
    selection = _text(selection_id)
    review_round = _text(review_round_id)
    refs = _string_list(input_refs)
    snapshot_hash = _sha256(input_snapshot_hash)
    source_run = _text(source_collection_run_id) or run
    candidate_rows = [dict(item) for item in candidates if isinstance(item, Mapping)]
    binding = {
        "teamId": team,
        "workflowRunId": run,
        "nodeRunId": node,
        "questionId": question,
        "selectionId": selection,
        "reviewRoundId": review_round,
        "inputRefs": refs,
        "inputSnapshotHash": snapshot_hash,
        "sourceCollectionRunId": source_run,
    }
    input_hash = compute_input_hash(
        team_id=team,
        workflow_run_id=run,
        node_run_id=node,
        question_id=question,
        selection_id=selection,
        review_round_id=review_round,
        input_refs=refs,
        input_snapshot_hash=snapshot_hash,
        source_collection_run_id=source_run,
        candidates=candidate_rows,
    )
    blockers = _binding_blockers(
        team_id=team,
        workflow_run_id=run,
        node_run_id=node,
        question_id=question,
        selection_id=selection,
        review_round_id=review_round,
        input_refs=refs,
        input_snapshot_hash=snapshot_hash,
        workflow_authority=workflow_authority,
    )
    rows, row_blockers = _validate_rows(review, candidate_rows)
    blockers.extend(row_blockers)
    candidate_ids = [
        _candidate_id(item)
        for item in candidate_rows
        if isinstance(item, Mapping) and _candidate_id(item)
    ]
    selection, selection_blockers, pareto, meta_review = _selection_from_review(
        review,
        candidate_ids,
    )
    blockers.extend(selection_blockers)
    receipt_bindings, model_receipts, receipt_blockers = _review_receipt_bindings(
        review,
        workflow_run_id=run,
        candidate_ids=candidate_ids,
        rows=rows,
    )
    blockers.extend(receipt_blockers)
    blockers = list(dict.fromkeys(blockers))
    # Candidate-level structured novelty conclusions ride beside the audit
    # rows (never inside them).  Empty output keeps the payload — and its
    # hashes — byte-identical to the pre-contrast authority.
    novelty_contrasts = _novelty_contrasts_from_review(review)
    result: dict[str, Any] = {
        "status": "blocked",
        "reason": "NEEDS_CONTEXT",
        "blockerCodes": blockers,
        "missingAuthorities": [ARTIFACT_KIND] if blockers else [],
        "binding": binding,
        "inputHash": input_hash,
        "dimensionReviews": rows,
        "selection": selection,
        "reviewReceiptBindings": receipt_bindings,
        "artifact": None,
    }
    if not blockers:
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "artifactKind": ARTIFACT_KIND,
            **binding,
            "inputHash": input_hash,
            "dimensionReviews": deepcopy(rows),
            "reviewReceiptBindings": deepcopy(receipt_bindings),
            "modelInvocationReceipts": deepcopy(model_receipts),
            "selection": deepcopy(selection),
            "pareto": deepcopy(pareto),
            "metaReview": deepcopy(meta_review),
            **(
                {"noveltyContrastByCandidate": deepcopy(novelty_contrasts)}
                if novelty_contrasts
                else {}
            ),
        }
        record = put_workflow_artifact(
            team,
            kind=ARTIFACT_KIND,
            workflow_run_id=run,
            source_collection_run_id=source_run,
            artifact_identity=f"{ARTIFACT_KIND}:{node}:{review_round}:{input_hash}",
            payload=payload,
        )
        result["status"] = "written"
        result["reason"] = ""
        result["missingAuthorities"] = []
        result["artifact"] = _artifact_descriptor(
            team_id=team,
            workflow_run_id=run,
            source_collection_run_id=source_run,
            payload=payload,
            record=record,
        )
    result["authorityHash"] = canonical_sha256(
        {
            "status": result["status"],
            "reason": result["reason"],
            "blockerCodes": result["blockerCodes"],
            "binding": binding,
            "inputHash": input_hash,
            "dimensionReviews": rows,
            "selection": selection,
            "reviewReceiptBindings": receipt_bindings,
            "modelInvocationReceipts": model_receipts,
            "pareto": pareto,
            "metaReview": meta_review,
            "artifact": result["artifact"],
            **(
                {"noveltyContrastByCandidate": novelty_contrasts}
                if novelty_contrasts
                else {}
            ),
        }
    )
    return result


# A descriptive alias keeps callers independent from the storage verb.
write_dimension_reviews_artifact = materialize_dimension_reviews_authority


__all__ = [
    "ARTIFACT_KIND",
    "SCHEMA_VERSION",
    "SELECTION_COMPARISON_METHOD",
    "compute_input_hash",
    "materialize_dimension_reviews_authority",
    "write_dimension_reviews_artifact",
]
