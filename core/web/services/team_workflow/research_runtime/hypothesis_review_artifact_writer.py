"""Write the Challenge Cup v2 dimension-review authority.

The hypothesis round remains a review projection. This module only promotes
explicit seven-dimension rows whose evidence refs can be read back from an
existing canonical authority. Feedback iterations deliberately stay blocked
until an official revision producer/readback resolver is available; a request
payload (including ``revisionReceipt``) is never treated as that authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from .artifact_readback_registry import (
    build_canonical_ref,
    parse_canonical_ref,
    read_domain_artifact,
)
from .human_gate_artifacts import canonical_sha256
from .workflow_artifact_store import put_workflow_artifact

SCHEMA_VERSION = 1
REVIEW_DIMENSIONS = (
    "evidence_support",
    "factual_accuracy",
    "novelty",
    "falsifiability",
    "plan_feasibility",
    "risk_and_ethics",
    "counterexample_coverage",
)
_REVIEWER_ROLE = "challenge_cup_evaluator"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return list(dict.fromkeys(_text(item) for item in value if _text(item)))


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _candidate_scope(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only stable, explicit candidate inputs in the scope hash."""

    return {
        "candidateId": _text(candidate.get("candidateId") or candidate.get("hypothesis_id")),
        "claim": _text(candidate.get("claim") or candidate.get("statement")),
        "rationale": _text(candidate.get("rationale") or candidate.get("mechanism")),
        "differenceFromAlternatives": _text(
            candidate.get("differenceFromAlternatives") or candidate.get("novelty_basis")
        ),
        "lineageRefs": _string_list(candidate.get("lineageRefs")),
        "evidenceRefs": _string_list(
            candidate.get("evidenceRefs") or candidate.get("evidence_refs")
        ),
        "supportingEvidenceRefs": _string_list(
            candidate.get("supportingEvidenceRefs")
            or candidate.get("supporting_evidence_refs")
        ),
        "challengingEvidenceRefs": _string_list(
            candidate.get("challengingEvidenceRefs")
            or candidate.get("challenging_evidence_refs")
        ),
    }


def compute_input_scope_hash(
    *,
    team_id: str,
    workflow_run_id: str,
    question_id: str,
    round_id: str,
    selection_id: str = "",
    source_collection_run_id: str = "",
    candidates: Sequence[Mapping[str, Any]] = (),
    context: Mapping[str, Any] | None = None,
) -> str:
    """Hash the immutable review inputs, excluding review outputs."""

    context_map = _mapping(context)
    context_seed = {
        key: deepcopy(context_map.get(key))
        for key in (
            "contextId",
            "meetingRoundId",
            "meetingType",
            "digest",
            "decisions",
            "evidenceRefs",
            "priorRound",
        )
        if key in context_map
    }
    return canonical_sha256(
        {
            "teamId": _text(team_id),
            "workflowRunId": _text(workflow_run_id),
            "sourceCollectionRunId": _text(source_collection_run_id) or _text(workflow_run_id),
            "questionId": _text(question_id),
            "roundId": _text(round_id),
            "selectionId": _text(selection_id),
            "candidates": [
                _candidate_scope(item)
                for item in candidates
                if isinstance(item, Mapping)
            ],
            "context": context_seed,
        }
    )


def _participant_role_map(meeting: Mapping[str, Any] | None) -> dict[str, str]:
    row = _mapping(meeting)
    result: dict[str, str] = {}
    snapshot = row.get("participantRoleSnapshot")
    if isinstance(snapshot, (list, tuple)):
        for item in snapshot:
            if not isinstance(item, Mapping):
                continue
            role = _text(item.get("roleId") or item.get("ownerId") or item.get("role"))
            agent = _text(item.get("agentId") or item.get("participantId"))
            if role and agent:
                result[role] = agent
    for role, agent in zip(
        _string_list(row.get("participantRoleIds")),
        _string_list(row.get("participants")),
    ):
        result.setdefault(role, agent)
    return result


def _dimension_rows(
    review: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    meeting: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate explicit rows and replace self-reported reviewer identity."""

    candidate_ids = {
        _text(item.get("candidateId") or item.get("hypothesis_id"))
        for item in candidates
        if isinstance(item, Mapping)
    }
    expected_reviewer = _participant_role_map(meeting).get(_REVIEWER_ROLE, "")
    blockers: list[str] = []
    if not expected_reviewer:
        blockers.append("reviewer_roster_missing")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    reviewed_candidates = [
        item for item in list(review.get("candidates") or []) if isinstance(item, Mapping)
    ]
    for candidate in reviewed_candidates:
        candidate_id = _text(candidate.get("candidateId") or candidate.get("hypothesis_id"))
        if candidate_id not in candidate_ids:
            blockers.append("dimension_review_unknown_candidate")
            continue
        raw_rows = candidate.get("dimensionReviews") or candidate.get("dimension_reviews")
        if not isinstance(raw_rows, (list, tuple)):
            blockers.append("dimension_reviews_missing")
            continue
        for raw in raw_rows:
            if not isinstance(raw, Mapping):
                blockers.append("dimension_review_row_invalid")
                continue
            hypothesis_id = _text(raw.get("hypothesis_id") or raw.get("candidateId")) or candidate_id
            dimension = _text(raw.get("dimension"))
            evidence_refs = _string_list(raw.get("evidence_refs") or raw.get("evidenceRefs"))
            key = (hypothesis_id, dimension)
            if hypothesis_id != candidate_id:
                blockers.append("dimension_review_candidate_mismatch")
            if dimension not in REVIEW_DIMENSIONS:
                blockers.append("dimension_review_unknown_dimension")
            if key in seen:
                blockers.append("dimension_review_duplicate")
            seen.add(key)
            if not _text(raw.get("rating")):
                blockers.append("dimension_review_rating_missing")
            if not _text(raw.get("rationale")):
                blockers.append("dimension_review_rationale_missing")
            if not evidence_refs:
                blockers.append("evidence_refs_missing")
            for ref in evidence_refs:
                if parse_canonical_ref(ref) is None or read_domain_artifact(ref) is None:
                    blockers.append("evidence_ref_unreadable")
            # Reviewer is server-bound to the frozen meeting role snapshot;
            # do not trust or copy a model-provided reviewer field.
            rows.append(
                {
                    "hypothesis_id": hypothesis_id,
                    "dimension": dimension,
                    "rating": _text(raw.get("rating")),
                    "rationale": _text(raw.get("rationale")),
                    "evidence_refs": evidence_refs,
                    "reviewer": expected_reviewer,
                }
            )
    expected = {
        (candidate_id, dimension)
        for candidate_id in candidate_ids
        for dimension in REVIEW_DIMENSIONS
    }
    if expected - seen:
        blockers.append("dimension_reviews_incomplete")
    if len(rows) != len(seen):
        blockers.append("dimension_reviews_duplicate")
    return rows, list(dict.fromkeys(blockers))


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
        "kind": "dimension_reviews",
        "workflowRunId": workflow_run_id,
        "sourceCollectionRunId": source_collection_run_id,
        "payload": dict(payload),
    }
    envelope_hash = canonical_sha256(envelope)
    return {
        "recordId": _text(record.get("recordId")),
        "kind": "dimension_reviews",
        "workflowRunId": workflow_run_id,
        "sourceCollectionRunId": source_collection_run_id,
        "contentHash": _text(record.get("contentHash")),
        "canonicalHash": envelope_hash,
        "canonicalRef": build_canonical_ref(
            kind="dimension_reviews",
            team_id=team_id,
            authority_run_id=source_collection_run_id,
            content_hash=envelope_hash,
        ),
    }


def materialize_hypothesis_review_authority(
    *,
    team_id: str,
    workflow_run_id: str,
    question_id: str,
    round_id: str,
    selection_id: str = "",
    source_collection_run_id: str = "",
    candidates: Sequence[Mapping[str, Any]] = (),
    review: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    meeting: Mapping[str, Any] | None = None,
    # Kept as compatibility inputs so callers can pass untrusted request
    # values. They are intentionally never read or stored.
    revision_receipt_ref: Any = None,
    revision_receipt: Any = None,
) -> dict[str, Any]:
    """Write dimension_reviews when its evidence and roster gates pass.

    Overall status is always blocked in this slice because the official
    feedback-iteration producer/readback contract is not wired yet.
    """

    del revision_receipt_ref, revision_receipt
    team = _text(team_id)
    run = _text(workflow_run_id)
    source_run = _text(source_collection_run_id) or run
    question = _text(question_id)
    round_value = _text(round_id)
    selection = _text(selection_id)
    binding = {
        "teamId": team,
        "runId": run,
        "sourceCollectionRunId": source_run,
        "questionId": question,
        "roundId": round_value,
        "selectionId": selection,
    }
    binding["inputScopeHash"] = compute_input_scope_hash(
        team_id=team,
        workflow_run_id=run,
        source_collection_run_id=source_run,
        question_id=question,
        round_id=round_value,
        selection_id=selection,
        candidates=candidates,
        context=context,
    )
    rows, blockers = _dimension_rows(_mapping(review), candidates, meeting=meeting)
    missing: list[str] = []
    artifacts: dict[str, Any] = {}
    if not run or not question or not round_value:
        blockers.append("review_scope_incomplete")
    if blockers or not rows:
        missing.append("dimension_reviews")
    else:
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "artifactKind": "dimension_reviews",
            **binding,
            "dimensionReviews": rows,
        }
        record = put_workflow_artifact(
            team,
            kind="dimension_reviews",
            workflow_run_id=run,
            source_collection_run_id=source_run,
            artifact_identity=f"dimension_reviews:{canonical_sha256(binding)}",
            payload=payload,
        )
        artifacts["dimension_reviews"] = _artifact_descriptor(
            team_id=team,
            workflow_run_id=run,
            source_collection_run_id=source_run,
            payload=payload,
            record=record,
        )

    blockers = list(dict.fromkeys(blockers))
    missing.append("feedback_iterations")
    authority = {
        "status": "blocked",
        "reason": "NEEDS_CONTEXT",
        "blockerCodes": blockers or ["feedback_iterations_missing"],
        "missingAuthorities": list(dict.fromkeys(missing)),
        "artifacts": artifacts,
        "dimensionReviews": rows,
        "feedbackIterations": [],
        "binding": binding,
    }
    authority["authorityHash"] = canonical_sha256(
        {
            "status": authority["status"],
            "reason": authority["reason"],
            "blockerCodes": authority["blockerCodes"],
            "missingAuthorities": authority["missingAuthorities"],
            "artifacts": artifacts,
            "binding": binding,
            "dimensionReviews": rows,
            "feedbackIterations": [],
        }
    )
    return authority


__all__ = [
    "REVIEW_DIMENSIONS",
    "compute_input_scope_hash",
    "materialize_hypothesis_review_authority",
]
