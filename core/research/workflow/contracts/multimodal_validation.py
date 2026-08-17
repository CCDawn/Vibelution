"""MultimodalValidationReport: fail-closed validation contract for multimodal
input used as research evidence.

Records the input modality types, parsability, citation locating, per-claim
supports/refutes verdicts and any failure reasons. Invalid modalities,
over-limit inputs and missing citations must be recorded and force the report
invalid/rejected; a failure-free valid report always requires at least one
citation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ._validation import ContractValidationError


class Modality(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    UNKNOWN = "unknown"


class Verdict(str, Enum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    NEUTRAL = "neutral"
    REJECTED = "rejected"


class ValidationFailureCode(str, Enum):
    INVALID_MODALITY = "invalid_modality"
    OVER_LIMIT = "over_limit"
    MISSING_CITATION = "missing_citation"
    UNPARSABLE = "unparsable"


@dataclass(frozen=True, slots=True)
class CitationLocator:
    citation_id: str
    modality: Modality
    offset: int
    length: int
    source_ref: str
    snippet_hash: str

    def __post_init__(self) -> None:
        if not self.citation_id.strip() or not self.source_ref.strip():
            raise ContractValidationError(
                "citationId and sourceRef must be non-empty"
            )
        if self.offset < 0 or self.length < 0:
            raise ContractValidationError(
                "citation offset/length must be non-negative"
            )
        digest = self.snippet_hash
        if len(digest) != 64 or any(
            char not in "0123456789abcdef" for char in digest
        ):
            raise ContractValidationError(
                "snippetHash must be a lowercase sha256 hex digest"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "citationId": self.citation_id,
            "modality": self.modality.value,
            "offset": self.offset,
            "length": self.length,
            "sourceRef": self.source_ref,
            "snippetHash": self.snippet_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CitationLocator:
        try:
            modality = Modality(str(payload.get("modality") or ""))
        except ValueError as exc:
            raise ContractValidationError(
                f"unsupported citation modality: {payload.get('modality')}"
            ) from exc
        return cls(
            citation_id=str(payload.get("citationId") or ""),
            modality=modality,
            offset=int(payload.get("offset") or 0),
            length=int(payload.get("length") or 0),
            source_ref=str(payload.get("sourceRef") or ""),
            snippet_hash=str(payload.get("snippetHash") or ""),
        )


@dataclass(frozen=True, slots=True)
class ClaimVerdict:
    claim_ref: str
    verdict: Verdict
    evidence_refs: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        if not self.claim_ref.strip():
            raise ContractValidationError("claimRef must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claimRef": self.claim_ref,
            "verdict": self.verdict.value,
            "evidenceRefs": list(self.evidence_refs),
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ClaimVerdict:
        try:
            verdict = Verdict(str(payload.get("verdict") or ""))
        except ValueError as exc:
            raise ContractValidationError(
                f"unsupported claim verdict: {payload.get('verdict')}"
            ) from exc
        return cls(
            claim_ref=str(payload.get("claimRef") or ""),
            verdict=verdict,
            evidence_refs=tuple(
                str(item) for item in payload.get("evidenceRefs") or []
            ),
            rationale=str(payload.get("rationale") or ""),
        )


@dataclass(frozen=True, slots=True)
class ValidationFailure:
    code: ValidationFailureCode
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, ValidationFailureCode):
            raise ContractValidationError("failure code must be a known code")

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "detail": self.detail}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ValidationFailure:
        code_raw = str(payload.get("code") or "")
        try:
            code = ValidationFailureCode(code_raw)
        except ValueError as exc:
            raise ContractValidationError(
                f"unsupported failure code: {code_raw}"
            ) from exc
        return cls(
            code=code,
            detail=str(payload.get("detail") or ""),
        )


@dataclass(frozen=True, slots=True)
class MultimodalValidationReport:
    report_id: str
    run_id: str
    node_run_id: str
    scope: Mapping[str, str]
    input_types: tuple[Modality, ...]
    parsed: bool
    parse_error: str
    input_byte_size: int
    input_max_bytes: int
    citations: tuple[CitationLocator, ...]
    verdicts: tuple[ClaimVerdict, ...]
    failures: tuple[ValidationFailure, ...]
    verdict: Verdict
    valid: bool
    created_at_ms: int

    def __post_init__(self) -> None:
        if (
            not self.report_id.strip()
            or not self.run_id.strip()
            or not self.node_run_id.strip()
        ):
            raise ContractValidationError(
                "reportId, runId and nodeRunId must be non-empty"
            )
        if not self.scope:
            raise ContractValidationError("scope must not be empty")
        if not self.input_types:
            raise ContractValidationError("inputTypes must not be empty")
        if self.input_byte_size < 0 or self.input_max_bytes < 0:
            raise ContractValidationError(
                "inputByteSize and inputMaxBytes must be non-negative"
            )
        if self.created_at_ms < 0:
            raise ContractValidationError("createdAtMs must be non-negative")

        codes = {failure.code for failure in self.failures}

        if not self.parsed:
            if ValidationFailureCode.UNPARSABLE not in codes:
                raise ContractValidationError(
                    "unparsable: unparsed input must be recorded as a failure"
                )
        else:
            if ValidationFailureCode.UNPARSABLE in codes:
                raise ContractValidationError(
                    "unparsable: parsed input cannot carry an unparsable failure"
                )

        if Modality.UNKNOWN in self.input_types:
            if ValidationFailureCode.INVALID_MODALITY not in codes:
                raise ContractValidationError(
                    "invalid_modality: unknown modality must be recorded as a failure"
                )

        if self.input_byte_size > self.input_max_bytes:
            if ValidationFailureCode.OVER_LIMIT not in codes:
                raise ContractValidationError(
                    "over_limit: oversized input must be recorded as a failure"
                )

        for claim_verdict in self.verdicts:
            if (
                claim_verdict.verdict in (Verdict.SUPPORTS, Verdict.REFUTES)
                and not claim_verdict.evidence_refs
            ):
                if ValidationFailureCode.MISSING_CITATION not in codes:
                    raise ContractValidationError(
                        "missing_citation: supports/refutes verdicts require "
                        "evidence citations"
                    )

        if codes:
            if self.valid is not False:
                raise ContractValidationError(
                    "fail-closed: reports with failures must be invalid"
                )
            if self.verdict is not Verdict.REJECTED:
                raise ContractValidationError(
                    "fail-closed: reports with failures must be rejected"
                )
        else:
            if not self.valid:
                raise ContractValidationError(
                    "failure-free reports must be valid"
                )
            if self.verdict is Verdict.REJECTED:
                raise ContractValidationError(
                    "failure-free reports cannot be rejected"
                )
            if not self.citations:
                raise ContractValidationError(
                    "missing_citation: valid reports require at least one citation"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "reportId": self.report_id,
            "runId": self.run_id,
            "nodeRunId": self.node_run_id,
            "scope": dict(self.scope),
            "inputTypes": [modality.value for modality in self.input_types],
            "parsed": self.parsed,
            "parseError": self.parse_error,
            "inputByteSize": self.input_byte_size,
            "inputMaxBytes": self.input_max_bytes,
            "citations": [citation.to_dict() for citation in self.citations],
            "verdicts": [verdict.to_dict() for verdict in self.verdicts],
            "failures": [failure.to_dict() for failure in self.failures],
            "verdict": self.verdict.value,
            "valid": self.valid,
            "createdAtMs": self.created_at_ms,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> MultimodalValidationReport:
        try:
            input_types = tuple(
                Modality(item) for item in payload.get("inputTypes") or []
            )
        except ValueError as exc:
            raise ContractValidationError(
                f"unsupported input modality: {payload.get('inputTypes')}"
            ) from exc
        try:
            verdict = Verdict(str(payload.get("verdict") or ""))
        except ValueError as exc:
            raise ContractValidationError(
                f"unsupported report verdict: {payload.get('verdict')}"
            ) from exc
        return cls(
            report_id=str(payload.get("reportId") or ""),
            run_id=str(payload.get("runId") or ""),
            node_run_id=str(payload.get("nodeRunId") or ""),
            scope=dict(payload.get("scope") or {}),
            input_types=input_types,
            parsed=bool(payload.get("parsed")),
            parse_error=str(payload.get("parseError") or ""),
            input_byte_size=int(payload.get("inputByteSize") or 0),
            input_max_bytes=int(payload.get("inputMaxBytes") or 0),
            citations=tuple(
                CitationLocator.from_dict(item) for item in payload.get("citations") or []
            ),
            verdicts=tuple(
                ClaimVerdict.from_dict(item) for item in payload.get("verdicts") or []
            ),
            failures=tuple(
                ValidationFailure.from_dict(item)
                for item in payload.get("failures") or []
            ),
            verdict=verdict,
            valid=bool(payload.get("valid")),
            created_at_ms=int(payload.get("createdAtMs") or 0),
        )