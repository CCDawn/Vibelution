"""Deterministic draft-pool screening over the R2.3 candidate contract.

Pure judgment layer for ruling 2026-08-28 item 2: the draft pool is screened
by grounding, hard thresholds, and five-axis diversity dedup before at most
``finalistLimit`` candidates enter pairwise review.  The functions here are
total, randomness-free, and order-independent: identical inputs always produce
identical artifacts (the caller supplies ``screeningId`` and ``createdAt`` so
they never inject hidden nondeterminism).

Gate order (each candidate falls to the first failed gate):

1. grounding — an ungrounded draft can never enter pairwise review (plan §4.3
   is unconditional, so there is no risk-flag exception);
2. hard thresholds — every required threshold id needs a passed record;
3. dedup — eligible candidates are clustered over the five structural axes;
   each cluster keeps exactly one representative (strongest grounding
   evidence, then stable ``candidateId`` tie-break) and merged candidates
   keep their lineage in the artifact snapshot;
4. finalist cut — surviving representatives beyond ``finalistLimit`` are
   rejected as ``finalist_overflow``.

Shortage handling (fewer than two mechanism-distinct survivors) is a flow
concern (regeneration / ``diversity_collapse`` escalation) and is NOT decided
here: this layer only produces the auditable artifact.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core.research.workflow.contracts import (
    CANDIDATE_SCREENING_CONTRACT_VERSION,
    ContractValidationError,
    CandidateScreeningArtifact,
    CandidateScreeningDraft,
    CandidateMergeRecord,
    CandidateRejectionRecord,
    DiversityAxis,
    DiversityMergeKind,
    ScreeningRejectionReason,
    ScreeningThresholds,
)
from core.research.workflow.contracts.research_scope import scope_hash_for


def _parse_drafts(
    drafts: Sequence[Mapping[str, Any] | CandidateScreeningDraft],
) -> tuple[CandidateScreeningDraft, ...]:
    if not drafts:
        raise ContractValidationError(
            "draft pool is empty; screening requires at least one draft candidate"
        )
    parsed = tuple(
        draft
        if isinstance(draft, CandidateScreeningDraft)
        else CandidateScreeningDraft.from_dict(draft)
        for draft in drafts
    )
    ids = [draft.candidateId for draft in parsed]
    if len(set(ids)) != len(ids):
        raise ContractValidationError("draft pool contains duplicate candidateIds")
    return parsed


def _representative_order_key(draft: CandidateScreeningDraft):
    """Deterministic representative ranking: strongest grounding first."""

    return (-len(draft.groundingEvidenceRefs), draft.candidateId)


def _cluster_eligible(
    eligible: Sequence[CandidateScreeningDraft], thresholds: ScreeningThresholds
) -> list[dict[str, Any]]:
    """Greedy leader clustering over the five-axis profiles.

    Candidates are visited in representative-rank order (strongest grounding
    evidence first, then stable ``candidateId`` tie-break) and either join the
    first cluster whose leader matches on all five axes (homogeneous) or on at
    least ``approximateMatchAxes`` axes (approximate, when enabled), or start
    a new cluster as its leader.  The leader therefore always is the
    best-ranked member of its cluster ("每簇只保留接地最好的代表"), every
    merged member has a direct, recorded match with its leader, and the whole
    clustering is deterministic and input-order independent.
    """

    clusters: list[dict[str, Any]] = []
    for draft in sorted(eligible, key=_representative_order_key):
        target: dict[str, Any] | None = None
        matched_axes: tuple[DiversityAxis, ...] = ()
        match_kind: DiversityMergeKind | None = None
        for cluster in clusters:
            leader: CandidateScreeningDraft = cluster["representative"]
            matched = draft.axisProfile.matching_axes(leader.axisProfile)
            if len(matched) == len(DiversityAxis):
                target, matched_axes, match_kind = cluster, matched, (
                    DiversityMergeKind.HOMOGENEOUS
                )
            elif thresholds.enableApproximateMerge and (
                len(matched) >= thresholds.approximateMatchAxes
            ):
                target, matched_axes, match_kind = cluster, matched, (
                    DiversityMergeKind.APPROXIMATE
                )
            if target is not None:
                break
        if target is None:
            clusters.append({"representative": draft, "members": [(draft, None, None)]})
        else:
            target["members"].append((draft, matched_axes, match_kind))
    return clusters


def screen_candidate_drafts(
    *,
    screening_id: str,
    question_id: str,
    program: str,
    theme: str,
    campaign: str,
    question: str,
    branch: str,
    workflow: str,
    agent_id: str,
    mode: str,
    drafts: Sequence[Mapping[str, Any] | CandidateScreeningDraft],
    thresholds: ScreeningThresholds | Mapping[str, Any] | None = None,
    screened_by: str,
    created_at: str,
) -> CandidateScreeningArtifact:
    """Screen one draft pool into the immutable screening artifact."""

    parsed_thresholds = (
        thresholds
        if isinstance(thresholds, ScreeningThresholds)
        else ScreeningThresholds.from_dict(thresholds)
    )
    parsed_drafts = _parse_drafts(drafts)

    rejected: dict[str, CandidateRejectionRecord] = {}
    eligible: list[CandidateScreeningDraft] = []
    for draft in sorted(parsed_drafts, key=lambda item: item.candidateId):
        if not draft.grounded:
            rejected[draft.candidateId] = CandidateRejectionRecord(
                candidateId=draft.candidateId,
                reason=ScreeningRejectionReason.UNGROUNDED,
                detail=(
                    "candidate is ungrounded and must not enter pairwise review"
                ),
            )
            continue
        failed = draft.failed_required_thresholds(
            parsed_thresholds.requiredThresholdIds
        )
        if failed:
            rejected[draft.candidateId] = CandidateRejectionRecord(
                candidateId=draft.candidateId,
                reason=ScreeningRejectionReason.HARD_THRESHOLD_FAILED,
                detail="failed or missing hard thresholds: " + ", ".join(failed),
            )
            continue
        eligible.append(draft)

    clusters = _cluster_eligible(eligible, parsed_thresholds)

    merges: list[CandidateMergeRecord] = []
    representatives: list[CandidateScreeningDraft] = []
    for cluster in clusters:
        representative: CandidateScreeningDraft = cluster["representative"]
        representatives.append(representative)
        merged_members = [
            (draft, matched, match_kind)
            for draft, matched, match_kind in cluster["members"]
            if draft.candidateId != representative.candidateId
        ]
        if not merged_members:
            continue
        by_kind: dict[DiversityMergeKind, list[tuple[CandidateScreeningDraft, tuple[DiversityAxis, ...]]]] = {}
        for draft, matched, match_kind in merged_members:
            by_kind.setdefault(match_kind, []).append((draft, matched))
            rejected[draft.candidateId] = CandidateRejectionRecord(
                candidateId=draft.candidateId,
                reason=ScreeningRejectionReason(
                    {
                        DiversityMergeKind.HOMOGENEOUS: (
                            ScreeningRejectionReason.HOMOGENEOUS_MERGED
                        ),
                        DiversityMergeKind.APPROXIMATE: (
                            ScreeningRejectionReason.APPROXIMATE_MERGED
                        ),
                    }[match_kind]
                ),
                detail=(
                    f"variant of representative {representative.candidateId} "
                    f"matching axes: {', '.join(axis.value for axis in matched)}"
                ),
                mergedIntoCandidateId=representative.candidateId,
            )
        for match_kind, members in by_kind.items():
            merges.append(
                CandidateMergeRecord(
                    representativeId=representative.candidateId,
                    mergedCandidateIds=tuple(
                        draft.candidateId
                        for draft, _ in sorted(
                            members, key=lambda item: item[0].candidateId
                        )
                    ),
                    matchedAxes=members[0][1],
                    matchKind=match_kind,
                )
            )

    pairwise_ids = [
        representative.candidateId
        for representative in representatives[: parsed_thresholds.finalistLimit]
    ]
    for representative in representatives[parsed_thresholds.finalistLimit :]:
        rejected[representative.candidateId] = CandidateRejectionRecord(
            candidateId=representative.candidateId,
            reason=ScreeningRejectionReason.FINALIST_OVERFLOW,
            detail=(
                f"finalistLimit={parsed_thresholds.finalistLimit} reached; "
                "representative ranked below the finalist cut"
            ),
        )

    identity = {
        "program": program,
        "theme": theme,
        "campaign": campaign,
        "question": question,
        "branch": branch,
        "workflow": workflow,
    }
    payload: dict[str, Any] = {
        "contractVersion": CANDIDATE_SCREENING_CONTRACT_VERSION,
        "screeningId": screening_id,
        **identity,
        "agentId": agent_id,
        "mode": mode,
        "scopeHash": scope_hash_for(
            **identity, agent_id=agent_id, mode=mode
        ),
        "questionId": question_id,
        "finalistLimit": parsed_thresholds.finalistLimit,
        "thresholds": parsed_thresholds.to_dict(),
        "draftPoolSize": len(parsed_drafts),
        "candidates": [
            draft.to_dict()
            for draft in sorted(parsed_drafts, key=lambda item: item.candidateId)
        ],
        "merges": [merge.to_dict() for merge in merges],
        "rejections": [
            rejected[candidate_id].to_dict()
            for candidate_id in sorted(rejected)
        ],
        "pairwiseCandidateIds": pairwise_ids,
        "screenedBy": screened_by,
        "createdAt": created_at,
    }
    # Re-validate through the contract so the artifact is the single
    # fail-closed authority over its own shape and invariants.
    return CandidateScreeningArtifact.from_dict(payload)


__all__ = ["screen_candidate_drafts"]
