"""Fail-closed judgement-record contracts for the G12 calibration pilot.

Wiring contracts between the frozen audit sample manifest
(``audit_sampling``) and the pure G12 calibration statistics
(``calibration_stats``): one judgement record per sampled question, bound
to the manifest's sampling scope, aggregated into a bundle that is either
``pending`` (records still missing) or ``complete`` (every manifest
question judged exactly once).

Fail-closed rules (a malformed record must never fabricate gate evidence):

- a record's ``questionId`` must be one of the bound manifest's
  ``questionIds`` -- the sampling scope is the evidence scope;
- a record's ``sampleKind`` must equal the manifest's assignment for that
  question;
- ``autoDecision`` / ``humanDecision`` are closed enums mirroring the
  ``calibration_stats`` inputs; unknown values are rejected, never
  dropped;
- a bundle never carries two records for the same question, and a
  declared ``status`` that disagrees with record coverage is rejected.

No I/O, no state, no network; the bundle content hash follows the
audit-chain uppercase sha256 convention.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from core.research.competition.calibration_stats import (
    AUTO_DECISION_AUTO_APPROVE,
    AUTO_DECISION_AUTO_ESCALATE,
    HUMAN_DECISION_APPROVE,
    HUMAN_DECISION_ESCALATE,
)
from core.research.workflow.contracts._canonical import sha256_hex
from core.research.workflow.contracts._validation import ContractValidationError
from core.research.workflow.contracts.audit_sampling import (
    AuditSampleManifest,
    SampleKind,
    parse_sample_kind,
)

#: Closed decision enums; intentionally the exact values ``calibration_stats``
#: consumes so a stored record projects into the stats layer without
#: translation or silent coercion.
AUTO_DECISIONS: frozenset[str] = frozenset(
    {AUTO_DECISION_AUTO_APPROVE, AUTO_DECISION_AUTO_ESCALATE}
)
HUMAN_DECISIONS: frozenset[str] = frozenset(
    {HUMAN_DECISION_APPROVE, HUMAN_DECISION_ESCALATE}
)

BUNDLE_STATUS_PENDING = "pending"
BUNDLE_STATUS_COMPLETE = "complete"
BUNDLE_STATUSES: frozenset[str] = frozenset(
    {BUNDLE_STATUS_PENDING, BUNDLE_STATUS_COMPLETE}
)


class CalibrationRecordError(ValueError):
    """A judgement record or calibration bundle failed fail-closed validation."""


def _text(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise CalibrationRecordError(f"{key} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class G12JudgementRecord:
    """One per-question auto-vs-human judgement inside the G12 pilot.

    ``autoDecision`` is what the automation would have done
    (``auto_approve`` | ``auto_escalate``); ``humanDecision`` is what the
    G12 human review actually decided (``approve`` | ``escalate``).
    ``riskClass`` / ``domain`` mirror the pool metadata at judgement time
    and drive the stratified statistics; ``evidenceRef`` points at the
    stored review evidence without inlining it.
    """

    questionId: str
    sampleKind: SampleKind
    autoDecision: str
    humanDecision: str
    riskClass: str
    domain: str
    recordedAt: str
    evidenceRef: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> G12JudgementRecord:
        if not isinstance(payload, Mapping):
            raise CalibrationRecordError("judgement record must be a JSON object")
        auto = str(payload.get("autoDecision") or "").strip()
        if auto not in AUTO_DECISIONS:
            raise CalibrationRecordError(
                f"unknown autoDecision {auto or '<missing>'!r}; expected one of: "
                + ", ".join(sorted(AUTO_DECISIONS))
            )
        human = str(payload.get("humanDecision") or "").strip()
        if human not in HUMAN_DECISIONS:
            raise CalibrationRecordError(
                f"unknown humanDecision {human or '<missing>'!r}; expected one of: "
                + ", ".join(sorted(HUMAN_DECISIONS))
            )
        try:
            sample_kind = parse_sample_kind(payload.get("sampleKind"))
        except ContractValidationError as exc:
            raise CalibrationRecordError(str(exc)) from exc
        return cls(
            questionId=_text(payload, "questionId"),
            sampleKind=sample_kind,
            autoDecision=auto,
            humanDecision=human,
            riskClass=_text(payload, "riskClass"),
            domain=_text(payload, "domain"),
            recordedAt=_text(payload, "recordedAt"),
            evidenceRef=_text(payload, "evidenceRef"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "questionId": self.questionId,
            "sampleKind": self.sampleKind.value,
            "autoDecision": self.autoDecision,
            "humanDecision": self.humanDecision,
            "riskClass": self.riskClass,
            "domain": self.domain,
            "recordedAt": self.recordedAt,
            "evidenceRef": self.evidenceRef,
        }

    def stats_record(self) -> dict[str, str]:
        """Project into the exact Mapping shape ``calibration_stats`` consumes."""
        return {
            "autoDecision": self.autoDecision,
            "humanDecision": self.humanDecision,
            "riskClass": self.riskClass,
            "domain": self.domain,
        }


def _bound_records(
    manifest: AuditSampleManifest,
    raw_records: Sequence[G12JudgementRecord | Mapping[str, Any]],
) -> tuple[G12JudgementRecord, ...]:
    """Parse and bind records to the manifest scope (fail-closed, shared)."""

    allowed = set(manifest.questionIds)
    records: list[G12JudgementRecord] = []
    seen: set[str] = set()
    for raw in raw_records:
        record = (
            raw
            if isinstance(raw, G12JudgementRecord)
            else G12JudgementRecord.from_dict(raw)
        )
        if record.questionId not in allowed:
            raise CalibrationRecordError(
                f"judgement record question {record.questionId!r} is outside "
                "the bound manifest sampling scope"
            )
        expected_kind = manifest.sampleKinds.get(record.questionId)
        if expected_kind is not record.sampleKind:
            raise CalibrationRecordError(
                f"judgement record sampleKind {record.sampleKind.value!r} does "
                f"not match the manifest assignment "
                f"{expected_kind.value if expected_kind else '<missing>'!r} "
                f"for question {record.questionId!r}"
            )
        if record.questionId in seen:
            raise CalibrationRecordError(
                f"duplicate judgement record for question {record.questionId!r}"
            )
        seen.add(record.questionId)
        records.append(record)
    return tuple(records)


def _derived_status(
    manifest: AuditSampleManifest, records: Sequence[G12JudgementRecord]
) -> str:
    judged = {record.questionId for record in records}
    if judged == set(manifest.questionIds):
        return BUNDLE_STATUS_COMPLETE
    return BUNDLE_STATUS_PENDING


def _derived_bundle_id(
    manifest: AuditSampleManifest, records: Sequence[G12JudgementRecord]
) -> str:
    digest = sha256_hex(
        {
            "manifestHash": manifest.manifestHash,
            "manifestId": manifest.manifestId,
            "questionIds": sorted(record.questionId for record in records),
        }
    )
    return "bundle-" + digest[:24]


@dataclass(frozen=True, slots=True)
class G12CalibrationBundle:
    """A judgement collection bound to one G12 calibration manifest.

    The manifest is embedded (never re-declared) so policy binding and the
    sampling scope always come from the single authoritative contract.
    ``status`` is derived from record coverage, not trusted from input:
    ``complete`` only when every manifest question carries exactly one
    record.
    """

    bundleId: str
    manifest: AuditSampleManifest
    records: tuple[G12JudgementRecord, ...]
    status: str
    bundleHash: str = ""

    @classmethod
    def build(
        cls,
        *,
        manifest: AuditSampleManifest,
        records: Sequence[G12JudgementRecord | Mapping[str, Any]],
        bundle_id: str | None = None,
    ) -> G12CalibrationBundle:
        """Bind judgement records to a manifest (fail-closed constructor)."""

        if not isinstance(manifest, AuditSampleManifest):
            raise CalibrationRecordError(
                "calibration bundle manifest must be an AuditSampleManifest"
            )
        bound = _bound_records(manifest, records)
        resolved_id = str(bundle_id or "").strip() or _derived_bundle_id(manifest, bound)
        return cls(
            bundleId=resolved_id,
            manifest=manifest,
            records=bound,
            status=_derived_status(manifest, bound),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> G12CalibrationBundle:
        """Re-validate a persisted bundle, including its embedded manifest."""

        if not isinstance(payload, Mapping):
            raise CalibrationRecordError("calibration bundle must be a JSON object")
        manifest_payload = payload.get("manifest")
        if not isinstance(manifest_payload, Mapping):
            raise CalibrationRecordError(
                "calibration bundle requires an embedded manifest object"
            )
        try:
            manifest = AuditSampleManifest.from_dict(manifest_payload)
        except ContractValidationError as exc:
            raise CalibrationRecordError(f"bundle manifest is invalid: {exc}") from exc
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            raise CalibrationRecordError("calibration bundle records must be a list")
        records = _bound_records(manifest, raw_records)
        bundle_id = str(payload.get("bundleId") or "").strip()
        if not bundle_id:
            raise CalibrationRecordError("bundleId must be a non-empty string")
        status = _derived_status(manifest, records)
        declared_status = str(payload.get("status") or "").strip()
        if declared_status and declared_status != status:
            raise CalibrationRecordError(
                f"declared bundle status {declared_status!r} does not match "
                f"record coverage {status!r}"
            )
        bundle = cls(
            bundleId=bundle_id,
            manifest=manifest,
            records=records,
            status=status,
        )
        declared_hash = str(payload.get("bundleHash") or "").strip().upper()
        if declared_hash:
            if declared_hash != g12_calibration_bundle_hash(bundle):
                raise CalibrationRecordError(
                    "bundleHash does not match bundle content"
                )
            bundle = replace(bundle, bundleHash=declared_hash)
        return bundle

    @property
    def manifestId(self) -> str:
        return self.manifest.manifestId

    @property
    def policyId(self) -> str:
        return self.manifest.policyId

    @property
    def policyVersion(self) -> str:
        return self.manifest.policyVersion

    @property
    def policyContentHash(self) -> str:
        return self.manifest.policyContentHash

    def missing_question_ids(self) -> tuple[str, ...]:
        judged = {record.questionId for record in self.records}
        return tuple(
            question_id
            for question_id in sorted(self.manifest.questionIds)
            if question_id not in judged
        )

    def stats_records(self) -> list[dict[str, str]]:
        """Per-record payload list for the ``calibration_stats`` layer."""
        return [record.stats_record() for record in self.records]

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundleId": self.bundleId,
            "manifest": self.manifest.to_dict(),
            "records": [record.to_dict() for record in self.records],
            "status": self.status,
            "bundleHash": self.bundleHash,
        }


def g12_calibration_bundle_hash(bundle: G12CalibrationBundle) -> str:
    """UPPERCASE content hash over the canonical bundle payload (no self hash)."""

    payload = bundle.to_dict()
    payload.pop("bundleHash", None)
    return sha256_hex(payload).upper()


__all__ = [
    "AUTO_DECISIONS",
    "BUNDLE_STATUSES",
    "BUNDLE_STATUS_COMPLETE",
    "BUNDLE_STATUS_PENDING",
    "CalibrationRecordError",
    "G12CalibrationBundle",
    "G12JudgementRecord",
    "HUMAN_DECISIONS",
    "g12_calibration_bundle_hash",
]
