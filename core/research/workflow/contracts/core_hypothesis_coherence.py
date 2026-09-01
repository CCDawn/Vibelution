"""Fail-closed contract for the stage-one core-hypothesis coherence gate."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ._validation import ContractValidationError

CORE_HYPOTHESIS_COHERENCE_CONTRACT_VERSION = "core-hypothesis-coherence-v1"
CORE_HYPOTHESIS_COHERENCE_CHECK_IDS = (
    "causal_chain_consistent",
    "prediction_entails_mechanism",
    "falsifier_targets_mechanism",
    "scope_consistent",
    "alternative_boundary_distinct",
)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _refs(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractValidationError(f"{field} must be a list")
    refs = tuple(_text(item) for item in value)
    if any(not item for item in refs):
        raise ContractValidationError(f"{field} must not contain empty entries")
    if len(set(refs)) != len(refs):
        raise ContractValidationError(f"{field} must contain unique entries")
    return refs


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CoreHypothesisCoherenceCheck:
    checkId: str
    passed: bool
    rationale: str
    claimRefs: tuple[str, ...]
    evidenceRefs: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CoreHypothesisCoherenceCheck":
        check_id = _text(payload.get("checkId"))
        if check_id not in CORE_HYPOTHESIS_COHERENCE_CHECK_IDS:
            raise ContractValidationError(
                f"unsupported core hypothesis coherence check: {check_id}"
            )
        passed = payload.get("passed")
        if not isinstance(passed, bool):
            raise ContractValidationError("coherence check passed must be a boolean")
        rationale = _text(payload.get("rationale"))
        if not rationale:
            raise ContractValidationError("coherence check rationale is required")
        claim_refs = _refs(payload.get("claimRefs", []), field="claimRefs")
        evidence_refs = _refs(payload.get("evidenceRefs", []), field="evidenceRefs")
        if not claim_refs and not evidence_refs:
            raise ContractValidationError(
                "coherence check requires at least one claimRef or evidenceRef"
            )
        return cls(
            checkId=check_id,
            passed=passed,
            rationale=rationale,
            claimRefs=claim_refs,
            evidenceRefs=evidence_refs,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkId": self.checkId,
            "passed": self.passed,
            "rationale": self.rationale,
            "claimRefs": list(self.claimRefs),
            "evidenceRefs": list(self.evidenceRefs),
        }


@dataclass(frozen=True, slots=True)
class CoreHypothesisCoherenceResult:
    contractVersion: str
    candidateId: str
    checks: tuple[CoreHypothesisCoherenceCheck, ...]
    reviewer: str
    receiptRef: str
    passed: bool
    artifactHash: str

    @classmethod
    def from_review_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        candidate_id: str,
        reviewer: str,
        receipt_ref: str = "",
    ) -> "CoreHypothesisCoherenceResult":
        raw = {
            "contractVersion": CORE_HYPOTHESIS_COHERENCE_CONTRACT_VERSION,
            "candidateId": _text(payload.get("candidateId") or candidate_id),
            "checks": list(payload.get("checks") or []),
            "reviewer": _text(payload.get("reviewer") or reviewer),
            "receiptRef": _text(payload.get("receiptRef") or receipt_ref),
        }
        parsed_checks = tuple(
            CoreHypothesisCoherenceCheck.from_dict(item)
            for item in raw["checks"]
            if isinstance(item, Mapping)
        )
        canonical = {
            **raw,
            "checks": [item.to_dict() for item in parsed_checks],
            "passed": all(item.passed for item in parsed_checks),
        }
        canonical["artifactHash"] = _canonical_hash(canonical)
        return cls.from_dict(canonical)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CoreHypothesisCoherenceResult":
        version = _text(payload.get("contractVersion"))
        if version != CORE_HYPOTHESIS_COHERENCE_CONTRACT_VERSION:
            raise ContractValidationError(
                f"unsupported core hypothesis coherence contract: {version}"
            )
        candidate_id = _text(payload.get("candidateId"))
        reviewer = _text(payload.get("reviewer"))
        if not candidate_id or not reviewer:
            raise ContractValidationError(
                "core hypothesis coherence requires candidateId and reviewer"
            )
        raw_checks = payload.get("checks")
        if not isinstance(raw_checks, Sequence) or isinstance(
            raw_checks, (str, bytes, bytearray)
        ):
            raise ContractValidationError("core hypothesis coherence checks must be a list")
        checks = tuple(
            CoreHypothesisCoherenceCheck.from_dict(item)
            for item in raw_checks
            if isinstance(item, Mapping)
        )
        check_ids = [item.checkId for item in checks]
        if tuple(check_ids) != CORE_HYPOTHESIS_COHERENCE_CHECK_IDS:
            raise ContractValidationError(
                "core hypothesis coherence must cover the five checks in canonical order"
            )
        passed = payload.get("passed")
        expected_passed = all(item.passed for item in checks)
        if not isinstance(passed, bool) or passed is not expected_passed:
            raise ContractValidationError(
                "core hypothesis coherence passed must equal all check results"
            )
        supplied_hash = _text(payload.get("artifactHash")).lower()
        canonical = {
            "contractVersion": version,
            "candidateId": candidate_id,
            "checks": [item.to_dict() for item in checks],
            "reviewer": reviewer,
            "receiptRef": _text(payload.get("receiptRef")),
            "passed": passed,
        }
        if supplied_hash != _canonical_hash(canonical):
            raise ContractValidationError(
                "core hypothesis coherence artifactHash does not match its content"
            )
        return cls(
            contractVersion=version,
            candidateId=candidate_id,
            checks=checks,
            reviewer=reviewer,
            receiptRef=canonical["receiptRef"],
            passed=passed,
            artifactHash=supplied_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contractVersion,
            "candidateId": self.candidateId,
            "checks": [item.to_dict() for item in self.checks],
            "reviewer": self.reviewer,
            "receiptRef": self.receiptRef,
            "passed": self.passed,
            "artifactHash": self.artifactHash,
        }


__all__ = [
    "CORE_HYPOTHESIS_COHERENCE_CHECK_IDS",
    "CORE_HYPOTHESIS_COHERENCE_CONTRACT_VERSION",
    "CoreHypothesisCoherenceCheck",
    "CoreHypothesisCoherenceResult",
]
