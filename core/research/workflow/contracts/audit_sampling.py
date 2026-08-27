"""Challenge Cup audit sampling contracts (R4.4).

Data carriers for the frozen decision-#5/#13 audit review system: the
cumulative G12 calibration pilot, G125 sequential batches, the three rolling
drift sentinels drawn from the second half of the G125 low-risk questions,
risk/anomaly-triggered full reviews, and the final manifest-level approval.

These contracts only record WHAT was sampled, under WHICH policy snapshot and
seed, and WHO approved the manifest afterwards.  They never execute work and
never approve anything by themselves; every payload is fail-closed validated
so a malformed sample can never enter the audit chain.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from ._canonical import sha256_hex
from ._validation import (
    ContractValidationError,
    require_int,
    require_list,
    require_mapping,
    require_text,
)

# Challenge Cup policy contentHashes are UPPERCASE hex (policy JSONs and
# automation_policy.compute_policy_content_hash); every hash this contract
# stores or self-signs follows the same uppercase form. Lowercase input is
# accepted and normalized to uppercase so cross-system comparisons never see
# two spellings of the same digest.
_SHA256_UPPER_RE = re.compile(r"^[0-9A-F]{64}$")


class SampleKind(str, Enum):
    """Why a question is part of an audit sample manifest."""

    G12_CALIBRATION = "g12_calibration"
    G125_SEQUENTIAL = "g125_sequential"
    DRIFT_SENTINEL = "drift_sentinel"
    RISK_TRIGGERED_FULL_REVIEW = "risk_triggered_full_review"
    ANOMALY_FULL_REVIEW = "anomaly_full_review"


SAMPLE_KIND_VALUES = frozenset(item.value for item in SampleKind)

GATES = frozenset({"G1", "G5", "G12", "G125"})

# Stratification axes follow the frozen HumanReviewPolicy v2
# ``postG12LowRiskSampling.stratificationAxes``; unknown axes are rejected.
STRATA_AXES = frozenset({"risk_class", "catalog_domain", "run_phase"})

RUN_PHASE_VALUES = frozenset({"first_half", "second_half"})

# Decision record §3.1: exactly three rolling drift sentinels.
DRIFT_SENTINEL_COUNT = 3

DRIFT_SENTINEL_GATE = "G125"

REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_APPROVED = "approved"
REVIEW_STATUS_REJECTED = "rejected"
REVIEW_STATUSES = frozenset({REVIEW_STATUS_PENDING, REVIEW_STATUS_APPROVED, REVIEW_STATUS_REJECTED})
_TERMINAL_REVIEW_STATUSES = frozenset({REVIEW_STATUS_APPROVED, REVIEW_STATUS_REJECTED})


def parse_sample_kind(value: Any) -> SampleKind:
    """Parse a fail-closed sample kind; unknown values are rejected."""

    if isinstance(value, SampleKind):
        return value
    text = str(value or "").strip().lower()
    try:
        return SampleKind(text)
    except ValueError as exc:
        raise ContractValidationError(
            "unknown sampleKind: "
            + (text or "<missing>")
            + " (expected one of: "
            + ", ".join(sorted(SAMPLE_KIND_VALUES))
            + ")"
        ) from exc


def require_sha256_upper(payload: Mapping[str, Any], key: str) -> str:
    """Require a sha256 hex digest stored in the domain-wide UPPERCASE form.

    Lowercase input is accepted and normalized to uppercase, matching the
    Challenge Cup policy contentHash rule so a manifest reference and the
    policy it cites always compare equal byte-for-byte.
    """

    value = str(payload.get(key) or "").strip().upper()
    if not _SHA256_UPPER_RE.fullmatch(value):
        raise ContractValidationError(
            f"{key} must be a sha256 hex digest (stored uppercase)"
        )
    return value


@dataclass(frozen=True, slots=True)
class QuestionSampleAssignment:
    """One sampled question and why it was sampled."""

    questionId: str
    sampleKind: SampleKind

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> QuestionSampleAssignment:
        if not isinstance(payload, Mapping):
            raise ContractValidationError("sample assignment must be a JSON object")
        question_id = str(payload.get("questionId") or "").strip()
        if not question_id:
            raise ContractValidationError("sample assignment questionId must be a non-empty string")
        return cls(questionId=question_id, sampleKind=parse_sample_kind(payload.get("sampleKind")))

    def to_dict(self) -> dict[str, Any]:
        return {"questionId": self.questionId, "sampleKind": self.sampleKind.value}


@dataclass(frozen=True, slots=True)
class AuditSampleManifest:
    """One reproducible audit sample drawn under a frozen policy snapshot.

    ``policyId``/``policyVersion``/``policyContentHash`` bind the manifest to
    the exact policy snapshot used at generation time.  ``reviewStatus`` is a
    one-way state machine: ``pending`` may become ``approved`` or ``rejected``
    exactly once; terminal states are immutable (decision #5: one final
    manifest-level approval, never per-question sign-off).
    """

    manifestId: str
    gate: str
    batchIndex: int
    policyId: str
    policyVersion: str
    policyContentHash: str
    seed: str
    samplingRuleVersion: str
    generatedAt: str
    questionIds: tuple[str, ...]
    sampleKinds: Mapping[str, SampleKind]
    strata: Mapping[str, tuple[str, ...]]
    reviewStatus: str = REVIEW_STATUS_PENDING
    reviewedBy: str = ""
    reviewedAt: str = ""
    manifestHash: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AuditSampleManifest:
        if not isinstance(payload, Mapping):
            raise ContractValidationError("audit sample manifest must be a JSON object")
        manifest_id = require_text(payload, "manifestId")
        gate = require_text(payload, "gate")
        if gate not in GATES:
            raise ContractValidationError(
                "gate must be one of: " + ", ".join(sorted(GATES))
            )
        policy_id = require_text(payload, "policyId")
        policy_version = require_text(payload, "policyVersion")
        policy_hash = require_sha256_upper(payload, "policyContentHash")
        seed = require_text(payload, "seed")
        rule_version = require_text(payload, "samplingRuleVersion")
        generated_at = require_text(payload, "generatedAt")
        batch_index = require_int(payload, "batchIndex", minimum=1)

        question_ids: list[str] = []
        for item in require_list(payload, "questionIds", non_empty=True):
            question_id = str(item or "").strip()
            if not question_id:
                raise ContractValidationError("questionIds entries must be non-empty strings")
            if question_id in question_ids:
                raise ContractValidationError(
                    f"duplicate questionId in audit sample: {question_id}"
                )
            question_ids.append(question_id)

        sample_kinds = _parse_sample_kinds(payload, frozenset(question_ids))
        strata = _parse_strata(payload)

        review_status = str(payload.get("reviewStatus") or REVIEW_STATUS_PENDING).strip().lower()
        if review_status not in REVIEW_STATUSES:
            raise ContractValidationError(
                "reviewStatus must be one of: " + ", ".join(sorted(REVIEW_STATUSES))
            )
        reviewed_by = str(payload.get("reviewedBy") or "").strip()
        reviewed_at = str(payload.get("reviewedAt") or "").strip()
        if review_status in _TERMINAL_REVIEW_STATUSES:
            if not reviewed_by or not reviewed_at:
                raise ContractValidationError(
                    "approved/rejected manifests require reviewedBy and reviewedAt"
                )
        elif reviewed_by or reviewed_at:
            raise ContractValidationError(
                "pending manifests must not carry reviewer identity"
            )

        manifest = cls(
            manifestId=manifest_id,
            gate=gate,
            batchIndex=batch_index,
            policyId=policy_id,
            policyVersion=policy_version,
            policyContentHash=policy_hash,
            seed=seed,
            samplingRuleVersion=rule_version,
            generatedAt=generated_at,
            questionIds=tuple(question_ids),
            sampleKinds=sample_kinds,
            strata=strata,
            reviewStatus=review_status,
            reviewedBy=reviewed_by,
            reviewedAt=reviewed_at,
            manifestHash="",
        )
        declared_hash = str(payload.get("manifestHash") or "").strip().upper()
        if declared_hash:
            if declared_hash != audit_sample_manifest_hash(manifest):
                raise ContractValidationError(
                    "manifestHash does not match manifest content"
                )
            manifest = replace(manifest, manifestHash=declared_hash)
        return manifest

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifestId": self.manifestId,
            "gate": self.gate,
            "batchIndex": self.batchIndex,
            "policyId": self.policyId,
            "policyVersion": self.policyVersion,
            "policyContentHash": self.policyContentHash,
            "seed": self.seed,
            "samplingRuleVersion": self.samplingRuleVersion,
            "generatedAt": self.generatedAt,
            "questionIds": list(self.questionIds),
            "sampleAssignments": [
                {
                    "questionId": question_id,
                    "sampleKind": self.sampleKinds[question_id].value,
                }
                for question_id in sorted(self.questionIds)
            ],
            "strata": {
                axis: list(values) for axis, values in sorted(self.strata.items())
            },
            "reviewStatus": self.reviewStatus,
            "reviewedBy": self.reviewedBy,
            "reviewedAt": self.reviewedAt,
            "manifestHash": self.manifestHash,
        }

    def sample_kind_for(self, question_id: str) -> SampleKind:
        kind = self.sampleKinds.get(str(question_id or "").strip())
        if kind is None:
            raise ContractValidationError(
                f"question is not part of this manifest: {question_id}"
            )
        return kind

    def drift_sentinel_question_ids(self) -> tuple[str, ...]:
        return tuple(
            question_id
            for question_id in self.questionIds
            if self.sampleKinds[question_id] is SampleKind.DRIFT_SENTINEL
        )

    def with_review_decision(
        self, *, status: str, reviewed_by: str, reviewed_at: str
    ) -> AuditSampleManifest:
        """Record the one allowed manifest-level decision (pending -> terminal)."""

        normalized = str(status or "").strip().lower()
        if normalized not in _TERMINAL_REVIEW_STATUSES:
            raise ContractValidationError(
                "manifest review decision must be approved or rejected"
            )
        if self.reviewStatus != REVIEW_STATUS_PENDING:
            raise ContractValidationError(
                "manifest review already decided ("
                + self.reviewStatus
                + "); only pending -> approved/rejected is allowed"
            )
        reviewer = str(reviewed_by or "").strip()
        decided_at = str(reviewed_at or "").strip()
        if not reviewer or not decided_at:
            raise ContractValidationError(
                "manifest review decision requires reviewedBy and reviewedAt"
            )
        decided = replace(
            self,
            reviewStatus=normalized,
            reviewedBy=reviewer,
            reviewedAt=decided_at,
        )
        return replace(decided, manifestHash=audit_sample_manifest_hash(decided))


def audit_sample_manifest_hash(manifest: AuditSampleManifest) -> str:
    """UPPERCASE content hash over the canonical manifest payload (no self hash)."""

    payload = manifest.to_dict()
    payload.pop("manifestHash", None)
    return sha256_hex(payload).upper()


def _parse_sample_kinds(
    payload: Mapping[str, Any], question_id_set: frozenset[str]
) -> dict[str, SampleKind]:
    raw_assignments = payload.get("sampleAssignments")
    kinds: dict[str, SampleKind] = {}
    if raw_assignments is not None:
        if not isinstance(raw_assignments, list) or not raw_assignments:
            raise ContractValidationError("sampleAssignments must be a non-empty list")
        for item in raw_assignments:
            assignment = QuestionSampleAssignment.from_dict(item)
            if assignment.questionId in kinds:
                raise ContractValidationError(
                    "conflicting sampleKind assignments for question "
                    + assignment.questionId
                )
            kinds[assignment.questionId] = assignment.sampleKind
    else:
        raw_kinds = payload.get("sampleKinds")
        if not isinstance(raw_kinds, Mapping) or not raw_kinds:
            raise ContractValidationError(
                "sampleKinds must map questionId to sampleKind"
            )
        for question_id, raw_kind in raw_kinds.items():
            key = str(question_id or "").strip()
            if not key:
                raise ContractValidationError("sampleKinds keys must be non-empty strings")
            kinds[key] = parse_sample_kind(raw_kind)
    if set(kinds) != question_id_set:
        raise ContractValidationError(
            "sampleKinds must cover questionIds exactly (no missing, no extra)"
        )
    sentinel_ids = [
        question_id
        for question_id, kind in kinds.items()
        if kind is SampleKind.DRIFT_SENTINEL
    ]
    if sentinel_ids and len(sentinel_ids) != DRIFT_SENTINEL_COUNT:
        raise ContractValidationError(
            f"a manifest carrying drift sentinels must carry exactly "
            f"{DRIFT_SENTINEL_COUNT}, got {len(sentinel_ids)}"
        )
    return kinds


def _parse_strata(payload: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    raw = require_mapping(payload, "strata")
    strata: dict[str, tuple[str, ...]] = {}
    for axis, raw_values in raw.items():
        axis_text = str(axis or "").strip()
        if axis_text not in STRATA_AXES:
            raise ContractValidationError(
                "unknown strata axis: "
                + (axis_text or "<missing>")
                + " (expected subset of: "
                + ", ".join(sorted(STRATA_AXES))
                + ")"
            )
        if not isinstance(raw_values, list) or not raw_values:
            raise ContractValidationError(f"strata.{axis_text} must be a non-empty list")
        values: list[str] = []
        for raw_value in raw_values:
            value = str(raw_value or "").strip()
            if not value:
                raise ContractValidationError(
                    f"strata.{axis_text} entries must be non-empty strings"
                )
            if value in values:
                raise ContractValidationError(
                    f"strata.{axis_text} contains duplicate values"
                )
            if axis_text == "run_phase" and value not in RUN_PHASE_VALUES:
                raise ContractValidationError(
                    "strata.run_phase values must be one of: "
                    + ", ".join(sorted(RUN_PHASE_VALUES))
                )
            values.append(value)
        strata[axis_text] = tuple(values)
    return strata


@dataclass(frozen=True, slots=True)
class SentinelExclusion:
    """One question excluded before the drift-sentinel draw, with reason."""

    questionId: str
    reason: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SentinelExclusion:
        if not isinstance(payload, Mapping):
            raise ContractValidationError("sentinel exclusion must be a JSON object")
        question_id = str(payload.get("questionId") or "").strip()
        reason = str(payload.get("reason") or "").strip()
        if not question_id or not reason:
            raise ContractValidationError(
                "sentinel exclusions require non-empty questionId and reason"
            )
        return cls(questionId=question_id, reason=reason)

    def to_dict(self) -> dict[str, Any]:
        return {"questionId": self.questionId, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class DriftSentinelSelection:
    """Deterministic record of the three rolling drift sentinels (decision #5).

    ``candidatePool`` is the final draw pool: the second half of the G125
    ordering, low-risk only, minus ``preDrawExclusions`` such as questions
    already sampled in the current batch.  ``exclusions`` records why every
    non-selected candidate lost the draw.  The record is reproducible from
    (seed, candidate pool, rule version).
    """

    selectionId: str
    manifestId: str
    gate: str
    seed: str
    candidatePool: tuple[str, ...]
    secondHalfStartIndex: int
    selectedQuestionIds: tuple[str, ...]
    exclusions: Mapping[str, str]
    preDrawExclusions: tuple[SentinelExclusion, ...]
    selectionRuleVersion: str
    selectedAt: str
    selectionHash: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> DriftSentinelSelection:
        if not isinstance(payload, Mapping):
            raise ContractValidationError("drift sentinel selection must be a JSON object")
        selection_id = require_text(payload, "selectionId")
        manifest_id = str(payload.get("manifestId") or "").strip()
        gate = require_text(payload, "gate")
        if gate != DRIFT_SENTINEL_GATE:
            raise ContractValidationError(
                f"drift sentinels can only be drawn from {DRIFT_SENTINEL_GATE}"
            )
        seed = require_text(payload, "seed")
        candidate_pool: list[str] = []
        for item in require_list(payload, "candidatePool", non_empty=True):
            question_id = str(item or "").strip()
            if not question_id:
                raise ContractValidationError(
                    "candidatePool entries must be non-empty strings"
                )
            if question_id in candidate_pool:
                raise ContractValidationError(
                    f"duplicate questionId in sentinel candidate pool: {question_id}"
                )
            candidate_pool.append(question_id)
        second_half_start = require_int(payload, "secondHalfStartIndex", minimum=0)
        selected: list[str] = []
        for item in require_list(payload, "selectedQuestionIds", non_empty=True):
            question_id = str(item or "").strip()
            if not question_id:
                raise ContractValidationError(
                    "selectedQuestionIds entries must be non-empty strings"
                )
            if question_id in selected:
                raise ContractValidationError(
                    f"duplicate selected drift sentinel: {question_id}"
                )
            selected.append(question_id)
        if len(selected) != DRIFT_SENTINEL_COUNT:
            raise ContractValidationError(
                f"a drift sentinel selection must select exactly "
                f"{DRIFT_SENTINEL_COUNT}, got {len(selected)}"
            )
        pool_set = set(candidate_pool)
        selected_set = set(selected)
        missing_from_pool = sorted(selected_set - pool_set)
        if missing_from_pool:
            raise ContractValidationError(
                "selected drift sentinels must come from the candidate pool: "
                + ", ".join(missing_from_pool)
            )
        raw_exclusions = require_mapping(payload, "exclusions")
        exclusions: dict[str, str] = {}
        for raw_id, raw_reason in raw_exclusions.items():
            question_id = str(raw_id or "").strip()
            reason = str(raw_reason or "").strip()
            if not question_id or not reason:
                raise ContractValidationError(
                    "sentinel exclusions require non-empty questionId and reason"
                )
            exclusions[question_id] = reason
        expected_exclusions = pool_set - selected_set
        if set(exclusions) != expected_exclusions:
            raise ContractValidationError(
                "exclusions must cover exactly the non-selected candidates"
            )
        pre_draw: list[SentinelExclusion] = []
        pre_draw_ids: set[str] = set()
        for item in require_list(payload, "preDrawExclusions"):
            exclusion = SentinelExclusion.from_dict(item)
            if exclusion.questionId in pre_draw_ids:
                raise ContractValidationError(
                    f"duplicate pre-draw sentinel exclusion: {exclusion.questionId}"
                )
            if exclusion.questionId in selected_set:
                raise ContractValidationError(
                    "selected sentinels must not appear in preDrawExclusions"
                )
            pre_draw_ids.add(exclusion.questionId)
            pre_draw.append(exclusion)
        rule_version = require_text(payload, "selectionRuleVersion")
        selected_at = require_text(payload, "selectedAt")

        selection = cls(
            selectionId=selection_id,
            manifestId=manifest_id,
            gate=gate,
            seed=seed,
            candidatePool=tuple(candidate_pool),
            secondHalfStartIndex=second_half_start,
            selectedQuestionIds=tuple(selected),
            exclusions=exclusions,
            preDrawExclusions=tuple(pre_draw),
            selectionRuleVersion=rule_version,
            selectedAt=selected_at,
            selectionHash="",
        )
        declared_hash = str(payload.get("selectionHash") or "").strip().upper()
        if declared_hash:
            if declared_hash != drift_sentinel_selection_hash(selection):
                raise ContractValidationError(
                    "selectionHash does not match selection content"
                )
            selection = replace(selection, selectionHash=declared_hash)
        return selection

    def to_dict(self) -> dict[str, Any]:
        return {
            "selectionId": self.selectionId,
            "manifestId": self.manifestId,
            "gate": self.gate,
            "seed": self.seed,
            "candidatePool": list(self.candidatePool),
            "secondHalfStartIndex": self.secondHalfStartIndex,
            "selectedQuestionIds": list(self.selectedQuestionIds),
            "exclusions": dict(sorted(self.exclusions.items())),
            "preDrawExclusions": [
                exclusion.to_dict() for exclusion in self.preDrawExclusions
            ],
            "selectionRuleVersion": self.selectionRuleVersion,
            "selectedAt": self.selectedAt,
            "selectionHash": self.selectionHash,
        }


def drift_sentinel_selection_hash(selection: DriftSentinelSelection) -> str:
    """UPPERCASE content hash over the canonical selection payload (no self hash)."""

    payload = selection.to_dict()
    payload.pop("selectionHash", None)
    return sha256_hex(payload).upper()


__all__ = [
    "DRIFT_SENTINEL_COUNT",
    "DRIFT_SENTINEL_GATE",
    "GATES",
    "REVIEW_STATUSES",
    "RUN_PHASE_VALUES",
    "SAMPLE_KIND_VALUES",
    "STRATA_AXES",
    "AuditSampleManifest",
    "DriftSentinelSelection",
    "QuestionSampleAssignment",
    "SampleKind",
    "SentinelExclusion",
    "audit_sample_manifest_hash",
    "drift_sentinel_selection_hash",
    "parse_sample_kind",
    "require_sha256_upper",
]
