"""Candidate structural-diversity axes and draft-pool screening contract.

R2.3 contract layer for the zero-click hypothesis flow (ruling 2026-08-28
item 2): a draft pool is screened by grounding, dedup, and hard thresholds
before at most ``MAX_FINALIST_LIMIT`` candidates enter pairwise review.

Structural diversity is expressed over the closed five-axis vocabulary from
the frozen plan (§4.3/§4.5): mechanism, intervention, observable, population,
boundary.  Two candidates whose axis profiles match are homogeneous variants
of one idea and are merged behind a single representative; merged candidates
keep their lineage in the artifact snapshot and are never silently deleted.

The contract fails closed:

- a candidate without a complete five-axis profile is rejected at parse time;
- an ungrounded candidate may exist in the snapshot but can never appear in
  the pairwise output (the plan is unconditional: ungrounded drafts are
  marked and "不得直接入围", so there is no risk-flag exception);
- ``finalistLimit`` above ``MAX_FINALIST_LIMIT`` (3) is rejected;
- a screening output with more than ``finalistLimit`` candidates is rejected;
- every candidate is exactly one of pairwise / merged / rejected, so the
  artifact always carries a complete, auditable accounting.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ._validation import (
    ContractValidationError,
    require_int,
    require_list,
    require_mapping,
    require_text,
)
from .research_scope import REQUIRED_SCOPE_FIELDS, parse_scope_mode, scope_hash_for

CANDIDATE_SCREENING_CONTRACT_VERSION = "candidate-screening-v1"

#: Closed five-axis vocabulary for structural hypothesis diversity (§4.5 Q4).
DIVERSITY_AXES = (
    "mechanism",
    "intervention",
    "observable",
    "population",
    "boundary",
)

#: Ruling 2026-08-28 item 2: at most three candidates enter pairwise review.
MAX_FINALIST_LIMIT = 3
DEFAULT_FINALIST_LIMIT = 3

#: G12-calibrated interval (ruling 2026-08-28 §3.2).  These are target-range
#: documentation constants, not hard gates: the pool size stays tunable until
#: G12 calibration freezes the final value.
CANDIDATE_COUNT_RANGE_MIN = 2
CANDIDATE_COUNT_RANGE_MAX = 6
DEFAULT_DRAFT_POOL_SIZE = 10

#: Structural hard thresholds every draft must carry records for.  Basis:
#: the plan (§4.3) requires every candidate to state a falsifiable hypothesis
#: and failure conditions; these are checkable without domain reasoning, so
#: they are the minimal draft-layer gates.  Claim-level grounding hard gates
#: belong to Q3 (upstream of this screening layer).
DEFAULT_REQUIRED_THRESHOLD_IDS = ("falsifiable_hypothesis", "failure_condition_stated")

#: Approximate dedup default: merge when at least 4 of 5 axes match.  Basis:
#: the frozen plan mandates approximate clustering (§4.5 step 3, "立即采用")
#: to stop wording variants; candidates differing in at most one structural
#: axis are exactly the "同义改写 / 换人群不换机制" anti-patterns the plan names.
DEFAULT_APPROXIMATE_MATCH_AXES = 4


class DiversityAxis(str, Enum):
    """Closed set of structural axes along which candidates must differ."""

    MECHANISM = "mechanism"
    INTERVENTION = "intervention"
    OBSERVABLE = "observable"
    POPULATION = "population"
    BOUNDARY = "boundary"


class DiversityMergeKind(str, Enum):
    """Why merged candidates were judged variants of one idea."""

    HOMOGENEOUS = "homogeneous"
    APPROXIMATE = "approximate"


class ScreeningRejectionReason(str, Enum):
    """Closed classification of why a draft did not enter pairwise review."""

    UNGROUNDED = "ungrounded"
    HARD_THRESHOLD_FAILED = "hard_threshold_failed"
    HOMOGENEOUS_MERGED = "homogeneous_merged"
    APPROXIMATE_MERGED = "approximate_merged"
    FINALIST_OVERFLOW = "finalist_overflow"


_MERGE_KIND_TO_REJECTION = {
    DiversityMergeKind.HOMOGENEOUS: ScreeningRejectionReason.HOMOGENEOUS_MERGED,
    DiversityMergeKind.APPROXIMATE: ScreeningRejectionReason.APPROXIMATE_MERGED,
}

_MERGE_REJECTION_TO_KIND = {
    reason: kind for kind, reason in _MERGE_KIND_TO_REJECTION.items()
}


def normalize_axis_text(value: Any) -> str:
    """Canonical axis text: whitespace-collapsed, stripped, non-empty."""

    normalized = " ".join(str(value or "").split()).strip()
    if not normalized:
        raise ContractValidationError("axis value must be a non-empty string")
    return normalized


def parse_diversity_axis(value: Any) -> DiversityAxis:
    try:
        return DiversityAxis(str(value or "").strip())
    except ValueError as exc:
        raise ContractValidationError(f"unsupported diversity axis: {value}") from exc


def parse_merge_kind(value: Any) -> DiversityMergeKind:
    try:
        return DiversityMergeKind(str(value or "").strip())
    except ValueError as exc:
        raise ContractValidationError(f"unsupported merge kind: {value}") from exc


def parse_rejection_reason(value: Any) -> ScreeningRejectionReason:
    try:
        return ScreeningRejectionReason(str(value or "").strip())
    except ValueError as exc:
        raise ContractValidationError(
            f"unsupported screening rejection reason: {value}"
        ) from exc


def _require_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ContractValidationError(f"{key} must be a boolean")
    return value


@dataclass(frozen=True, slots=True)
class HypothesisAxisProfile:
    """Five-axis structural description of one candidate hypothesis.

    Axis values are normalized free text; equality decisions compare the
    normalized values exactly, so near-identical wording stays distinct here
    and approximate matching is an explicit, configured layer on top.
    """

    mechanism: str
    intervention: str
    observable: str
    population: str
    boundary: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HypothesisAxisProfile:
        values: dict[str, str] = {}
        unknown = sorted(set(payload) - set(DIVERSITY_AXES))
        if unknown:
            raise ContractValidationError(
                "unsupported hypothesis axis fields: " + ", ".join(unknown)
            )
        missing = [axis for axis in DIVERSITY_AXES if axis not in payload]
        if missing:
            raise ContractValidationError(
                "hypothesis axis profile is incomplete, missing axes: "
                + ", ".join(missing)
            )
        for axis in DIVERSITY_AXES:
            values[axis] = normalize_axis_text(payload.get(axis))
        return cls(
            mechanism=values["mechanism"],
            intervention=values["intervention"],
            observable=values["observable"],
            population=values["population"],
            boundary=values["boundary"],
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "mechanism": self.mechanism,
            "intervention": self.intervention,
            "observable": self.observable,
            "population": self.population,
            "boundary": self.boundary,
        }

    def axis_value(self, axis: DiversityAxis) -> str:
        return getattr(self, axis.value)

    def axis_vector(self) -> tuple[str, ...]:
        """Ordered normalized axis values, aligned with ``DIVERSITY_AXES``."""

        return tuple(self.axis_value(axis) for axis in DiversityAxis)

    def matching_axes(self, other: HypothesisAxisProfile) -> tuple[DiversityAxis, ...]:
        """Axes whose normalized values are exactly equal in both profiles."""

        return tuple(
            axis
            for axis in DiversityAxis
            if self.axis_value(axis) == other.axis_value(axis)
        )


@dataclass(frozen=True, slots=True)
class HardThresholdCheck:
    """One hard-threshold evaluation record carried by a draft candidate."""

    thresholdId: str
    passed: bool
    detail: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HardThresholdCheck:
        passed = _require_bool(payload, "passed")
        detail = " ".join(str(payload.get("detail") or "").split()).strip()
        if not passed and not detail:
            raise ContractValidationError(
                "failed hard threshold checks must carry a non-empty detail"
            )
        return cls(
            thresholdId=require_text(payload, "thresholdId"),
            passed=passed,
            detail=detail,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "thresholdId": self.thresholdId,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class CandidateScreeningDraft:
    """Immutable snapshot of one draft candidate entering screening."""

    candidateId: str
    axisProfile: HypothesisAxisProfile
    grounded: bool
    groundingEvidenceRefs: tuple[str, ...]
    hardThresholdChecks: tuple[HardThresholdCheck, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CandidateScreeningDraft:
        refs_raw = require_list(payload, "groundingEvidenceRefs")
        refs = tuple(
            " ".join(str(ref or "").split()).strip() for ref in refs_raw
        )
        if any(not ref for ref in refs):
            raise ContractValidationError(
                "groundingEvidenceRefs must not contain empty entries"
            )
        if len(set(refs)) != len(refs):
            raise ContractValidationError("groundingEvidenceRefs must be unique")
        grounded = _require_bool(payload, "grounded")
        if grounded and not refs:
            raise ContractValidationError(
                "grounded=true requires at least one groundingEvidenceRef"
            )
        checks_raw = require_list(payload, "hardThresholdChecks")
        checks = tuple(
            HardThresholdCheck.from_dict(check) for check in checks_raw
        )
        check_ids = [check.thresholdId for check in checks]
        if len(set(check_ids)) != len(check_ids):
            raise ContractValidationError(
                "hardThresholdChecks must not repeat a thresholdId"
            )
        return cls(
            candidateId=require_text(payload, "candidateId"),
            axisProfile=HypothesisAxisProfile.from_dict(
                require_mapping(payload, "axisProfile")
            ),
            grounded=grounded,
            groundingEvidenceRefs=refs,
            hardThresholdChecks=checks,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidateId": self.candidateId,
            "axisProfile": self.axisProfile.to_dict(),
            "grounded": self.grounded,
            "groundingEvidenceRefs": list(self.groundingEvidenceRefs),
            "hardThresholdChecks": [check.to_dict() for check in self.hardThresholdChecks],
        }

    def threshold_check(self, threshold_id: str) -> HardThresholdCheck | None:
        for check in self.hardThresholdChecks:
            if check.thresholdId == threshold_id:
                return check
        return None

    def failed_required_thresholds(
        self, required_threshold_ids: tuple[str, ...]
    ) -> tuple[str, ...]:
        """Required threshold ids that are missing or recorded as failed."""

        failed: list[str] = []
        for threshold_id in required_threshold_ids:
            check = self.threshold_check(threshold_id)
            if check is None or not check.passed:
                failed.append(threshold_id)
        return tuple(failed)


@dataclass(frozen=True, slots=True)
class ScreeningThresholds:
    """Deterministic screening configuration (no randomness anywhere).

    Validated in ``__post_init__`` so direct construction and dict parsing
    enforce the same fail-closed bounds; ``finalistLimit`` can never exceed
    ``MAX_FINALIST_LIMIT``.
    """

    finalistLimit: int = DEFAULT_FINALIST_LIMIT
    requiredThresholdIds: tuple[str, ...] = DEFAULT_REQUIRED_THRESHOLD_IDS
    enableApproximateMerge: bool = True
    approximateMatchAxes: int = DEFAULT_APPROXIMATE_MATCH_AXES

    def __post_init__(self) -> None:
        if isinstance(self.finalistLimit, bool) or not isinstance(
            self.finalistLimit, int
        ):
            raise ContractValidationError("finalistLimit must be an integer")
        if self.finalistLimit < 1 or self.finalistLimit > MAX_FINALIST_LIMIT:
            raise ContractValidationError(
                f"finalistLimit must be between 1 and {MAX_FINALIST_LIMIT}"
            )
        if not isinstance(self.requiredThresholdIds, tuple) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.requiredThresholdIds
        ):
            raise ContractValidationError(
                "requiredThresholdIds must be a tuple of non-empty strings"
            )
        if len(set(self.requiredThresholdIds)) != len(self.requiredThresholdIds):
            raise ContractValidationError("requiredThresholdIds must be unique")
        if not isinstance(self.enableApproximateMerge, bool):
            raise ContractValidationError("enableApproximateMerge must be a boolean")
        if (
            isinstance(self.approximateMatchAxes, bool)
            or not isinstance(self.approximateMatchAxes, int)
            or self.approximateMatchAxes < 1
            or self.approximateMatchAxes > len(DIVERSITY_AXES)
        ):
            raise ContractValidationError(
                "approximateMatchAxes must be an integer between 1 and "
                f"{len(DIVERSITY_AXES)}"
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None = None) -> ScreeningThresholds:
        payload = payload or {}
        required_raw = payload.get(
            "requiredThresholdIds", list(DEFAULT_REQUIRED_THRESHOLD_IDS)
        )
        if not isinstance(required_raw, list):
            raise ContractValidationError("requiredThresholdIds must be a list")
        required = tuple(
            " ".join(str(item or "").split()).strip() for item in required_raw
        )
        return cls(
            finalistLimit=payload.get("finalistLimit", DEFAULT_FINALIST_LIMIT),
            requiredThresholdIds=required,
            enableApproximateMerge=payload.get("enableApproximateMerge", True),
            approximateMatchAxes=payload.get(
                "approximateMatchAxes", DEFAULT_APPROXIMATE_MATCH_AXES
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "finalistLimit": self.finalistLimit,
            "requiredThresholdIds": list(self.requiredThresholdIds),
            "enableApproximateMerge": self.enableApproximateMerge,
            "approximateMatchAxes": self.approximateMatchAxes,
        }


@dataclass(frozen=True, slots=True)
class CandidateMergeRecord:
    """Dedup decision: one representative stands in for merged variants."""

    representativeId: str
    mergedCandidateIds: tuple[str, ...]
    matchedAxes: tuple[DiversityAxis, ...]
    matchKind: DiversityMergeKind

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CandidateMergeRecord:
        axes_raw = require_list(payload, "matchedAxes", non_empty=True)
        axes = tuple(parse_diversity_axis(axis) for axis in axes_raw)
        if len(set(axes)) != len(axes):
            raise ContractValidationError("matchedAxes must not repeat an axis")
        merged_raw = require_list(payload, "mergedCandidateIds", non_empty=True)
        merged = tuple(str(item or "").strip() for item in merged_raw)
        if any(not item for item in merged):
            raise ContractValidationError(
                "mergedCandidateIds must not contain empty entries"
            )
        if len(set(merged)) != len(merged):
            raise ContractValidationError("mergedCandidateIds must be unique")
        match_kind = parse_merge_kind(payload.get("matchKind"))
        if match_kind is DiversityMergeKind.HOMOGENEOUS and len(axes) != len(
            DIVERSITY_AXES
        ):
            raise ContractValidationError(
                "homogeneous merges must match all five diversity axes"
            )
        if match_kind is DiversityMergeKind.APPROXIMATE and len(axes) >= len(
            DIVERSITY_AXES
        ):
            raise ContractValidationError(
                "approximate merges must not claim a full five-axis match"
            )
        return cls(
            representativeId=require_text(payload, "representativeId"),
            mergedCandidateIds=merged,
            matchedAxes=axes,
            matchKind=match_kind,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "representativeId": self.representativeId,
            "mergedCandidateIds": list(self.mergedCandidateIds),
            "matchedAxes": [axis.value for axis in self.matchedAxes],
            "matchKind": self.matchKind.value,
        }


@dataclass(frozen=True, slots=True)
class CandidateRejectionRecord:
    """Why one draft candidate did not enter pairwise review."""

    candidateId: str
    reason: ScreeningRejectionReason
    detail: str
    mergedIntoCandidateId: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CandidateRejectionRecord:
        reason = parse_rejection_reason(payload.get("reason"))
        merged_into = str(payload.get("mergedIntoCandidateId") or "").strip()
        if reason in _MERGE_REJECTION_TO_KIND:
            if not merged_into:
                raise ContractValidationError(
                    f"rejection reason {reason.value} requires mergedIntoCandidateId"
                )
        elif merged_into:
            raise ContractValidationError(
                f"rejection reason {reason.value} must not set mergedIntoCandidateId"
            )
        return cls(
            candidateId=require_text(payload, "candidateId"),
            reason=reason,
            detail=require_text(payload, "detail"),
            mergedIntoCandidateId=merged_into,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidateId": self.candidateId,
            "reason": self.reason.value,
            "detail": self.detail,
            "mergedIntoCandidateId": self.mergedIntoCandidateId,
        }


@dataclass(frozen=True, slots=True)
class CandidateScreeningArtifact:
    """Immutable snapshot of one draft-pool screening run.

    ``candidates`` is the full draft snapshot sorted by ``candidateId`` (so the
    artifact is canonical and input-order independent); ``merges`` records the
    dedup decisions with representatives and merged-away lineages; ``rejections``
    and ``pairwiseCandidateIds`` together account for every candidate exactly
    once.
    """

    contractVersion: str
    screeningId: str
    program: str
    theme: str
    campaign: str
    question: str
    branch: str
    workflow: str
    agentId: str
    mode: str
    scopeHash: str
    questionId: str
    finalistLimit: int
    thresholds: ScreeningThresholds
    draftPoolSize: int
    candidates: tuple[CandidateScreeningDraft, ...]
    merges: tuple[CandidateMergeRecord, ...]
    rejections: tuple[CandidateRejectionRecord, ...]
    pairwiseCandidateIds: tuple[str, ...]
    screenedBy: str
    createdAt: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CandidateScreeningArtifact:
        identity = {field: require_text(payload, field) for field in REQUIRED_SCOPE_FIELDS}
        identity["agentId"] = require_text(payload, "agentId")
        identity["mode"] = parse_scope_mode(payload).value
        supplied_hash = require_text(payload, "scopeHash").lower()
        expected_hash = scope_hash_for(
            **{field: identity[field] for field in REQUIRED_SCOPE_FIELDS},
            agent_id=identity["agentId"],
            mode=identity["mode"],
        )
        if supplied_hash != expected_hash:
            raise ContractValidationError(
                "scopeHash does not match the screening scope identity"
            )

        version = require_text(payload, "contractVersion")
        if version != CANDIDATE_SCREENING_CONTRACT_VERSION:
            raise ContractValidationError(
                f"unsupported candidate screening contract version: {version}"
            )

        thresholds = ScreeningThresholds.from_dict(
            require_mapping(payload, "thresholds")
        )
        finalist_limit = require_int(payload, "finalistLimit", minimum=1)
        if finalist_limit > MAX_FINALIST_LIMIT:
            raise ContractValidationError(
                f"finalistLimit must not exceed {MAX_FINALIST_LIMIT}"
            )
        if finalist_limit != thresholds.finalistLimit:
            raise ContractValidationError(
                "finalistLimit must agree with the recorded thresholds"
            )

        candidates_raw = require_list(payload, "candidates", non_empty=True)
        candidates = tuple(
            CandidateScreeningDraft.from_dict(item) for item in candidates_raw
        )
        candidate_ids = [candidate.candidateId for candidate in candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ContractValidationError("candidates must have unique candidateIds")
        candidates = tuple(
            sorted(candidates, key=lambda candidate: candidate.candidateId)
        )
        candidates_by_id = {
            candidate.candidateId: candidate for candidate in candidates
        }

        draft_pool_size = require_int(payload, "draftPoolSize", minimum=1)
        if draft_pool_size != len(candidates):
            raise ContractValidationError(
                "draftPoolSize must equal the number of snapshotted candidates"
            )

        pairwise_raw = require_list(payload, "pairwiseCandidateIds")
        pairwise = tuple(str(item or "").strip() for item in pairwise_raw)
        if any(not item for item in pairwise):
            raise ContractValidationError(
                "pairwiseCandidateIds must not contain empty entries"
            )
        if len(set(pairwise)) != len(pairwise):
            raise ContractValidationError("pairwiseCandidateIds must be unique")
        if len(pairwise) > finalist_limit:
            raise ContractValidationError(
                f"screening produced {len(pairwise)} pairwise candidates, "
                f"exceeding finalistLimit {finalist_limit}"
            )
        for candidate_id in pairwise:
            if candidate_id not in candidates_by_id:
                raise ContractValidationError(
                    f"pairwiseCandidateIds references unknown candidate: {candidate_id}"
                )
            candidate = candidates_by_id[candidate_id]
            if not candidate.grounded:
                raise ContractValidationError(
                    "ungrounded candidates must not enter pairwise review: "
                    + candidate_id
                )
            failed = candidate.failed_required_thresholds(
                thresholds.requiredThresholdIds
            )
            if failed:
                raise ContractValidationError(
                    "pairwise candidate failed required thresholds "
                    f"({', '.join(failed)}): {candidate_id}"
                )

        merges_raw = require_list(payload, "merges")
        merges = tuple(CandidateMergeRecord.from_dict(item) for item in merges_raw)
        merged_ids: set[str] = set()
        for merge in merges:
            if merge.representativeId not in candidates_by_id:
                raise ContractValidationError(
                    "merge representative is not a snapshotted candidate: "
                    + merge.representativeId
                )
            if merge.matchKind is DiversityMergeKind.APPROXIMATE and len(
                merge.matchedAxes
            ) < thresholds.approximateMatchAxes:
                raise ContractValidationError(
                    "approximate merge matches fewer axes than approximateMatchAxes"
                )
            for merged_id in merge.mergedCandidateIds:
                if merged_id not in candidates_by_id:
                    raise ContractValidationError(
                        f"merge references unknown candidate: {merged_id}"
                    )
                if merged_id == merge.representativeId:
                    raise ContractValidationError(
                        "a merge cannot merge the representative into itself"
                    )
                if merged_id in merged_ids:
                    raise ContractValidationError(
                        f"candidate is merged more than once: {merged_id}"
                    )
                merged_ids.add(merged_id)
        if merged_ids & set(pairwise):
            raise ContractValidationError(
                "merged candidates must not enter pairwise review: "
                + ", ".join(sorted(merged_ids & set(pairwise)))
            )

        rejections_raw = require_list(payload, "rejections")
        rejections = tuple(
            CandidateRejectionRecord.from_dict(item) for item in rejections_raw
        )
        rejections_by_candidate: dict[str, CandidateRejectionRecord] = {}
        for rejection in rejections:
            if rejection.candidateId not in candidates_by_id:
                raise ContractValidationError(
                    f"rejection references unknown candidate: {rejection.candidateId}"
                )
            if rejection.candidateId in rejections_by_candidate:
                raise ContractValidationError(
                    "a candidate must carry at most one rejection record: "
                    + rejection.candidateId
                )
            rejections_by_candidate[rejection.candidateId] = rejection
        expected_reject_ids = set(candidates_by_id) - set(pairwise)
        recorded_reject_ids = set(rejections_by_candidate)
        if recorded_reject_ids != expected_reject_ids:
            missing = sorted(expected_reject_ids - recorded_reject_ids)
            extra = sorted(recorded_reject_ids - expected_reject_ids)
            raise ContractValidationError(
                "rejection accounting is incomplete: "
                f"missing={missing} unexpected={extra}"
            )
        merge_kind_by_merged_id = {
            merged_id: merge.matchKind
            for merge in merges
            for merged_id in merge.mergedCandidateIds
        }
        for rejection in rejections:
            merge_kind = merge_kind_by_merged_id.get(rejection.candidateId)
            if merge_kind is not None:
                expected_reason = _MERGE_KIND_TO_REJECTION[merge_kind]
                if rejection.reason is not expected_reason:
                    raise ContractValidationError(
                        "merge rejection reason does not match the merge kind: "
                        + rejection.candidateId
                    )
                merge_for_candidate = next(
                    merge
                    for merge in merges
                    if rejection.candidateId in merge.mergedCandidateIds
                )
                if rejection.mergedIntoCandidateId != merge_for_candidate.representativeId:
                    raise ContractValidationError(
                        "mergedIntoCandidateId must point at the cluster representative: "
                        + rejection.candidateId
                    )

        return cls(
            contractVersion=version,
            screeningId=require_text(payload, "screeningId"),
            **identity,
            scopeHash=supplied_hash,
            questionId=require_text(payload, "questionId"),
            finalistLimit=finalist_limit,
            thresholds=thresholds,
            draftPoolSize=draft_pool_size,
            candidates=candidates,
            merges=merges,
            rejections=rejections,
            pairwiseCandidateIds=pairwise,
            screenedBy=require_text(payload, "screenedBy"),
            createdAt=require_text(payload, "createdAt"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contractVersion,
            "screeningId": self.screeningId,
            "program": self.program,
            "theme": self.theme,
            "campaign": self.campaign,
            "question": self.question,
            "branch": self.branch,
            "workflow": self.workflow,
            "agentId": self.agentId,
            "mode": self.mode,
            "scopeHash": self.scopeHash,
            "questionId": self.questionId,
            "finalistLimit": self.finalistLimit,
            "thresholds": self.thresholds.to_dict(),
            "draftPoolSize": self.draftPoolSize,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "merges": [merge.to_dict() for merge in self.merges],
            "rejections": [
                rejection.to_dict() for rejection in self.rejections
            ],
            "pairwiseCandidateIds": list(self.pairwiseCandidateIds),
            "screenedBy": self.screenedBy,
            "createdAt": self.createdAt,
        }

    def candidate_by_id(self, candidate_id: str) -> CandidateScreeningDraft | None:
        for candidate in self.candidates:
            if candidate.candidateId == candidate_id:
                return candidate
        return None


__all__ = [
    "CANDIDATE_COUNT_RANGE_MAX",
    "CANDIDATE_COUNT_RANGE_MIN",
    "CANDIDATE_SCREENING_CONTRACT_VERSION",
    "DEFAULT_APPROXIMATE_MATCH_AXES",
    "DEFAULT_DRAFT_POOL_SIZE",
    "DEFAULT_FINALIST_LIMIT",
    "DEFAULT_REQUIRED_THRESHOLD_IDS",
    "DIVERSITY_AXES",
    "MAX_FINALIST_LIMIT",
    "CandidateMergeRecord",
    "CandidateRejectionRecord",
    "CandidateScreeningArtifact",
    "CandidateScreeningDraft",
    "DiversityAxis",
    "DiversityMergeKind",
    "HardThresholdCheck",
    "HypothesisAxisProfile",
    "ScreeningRejectionReason",
    "ScreeningThresholds",
    "normalize_axis_text",
    "parse_diversity_axis",
    "parse_merge_kind",
    "parse_rejection_reason",
]
