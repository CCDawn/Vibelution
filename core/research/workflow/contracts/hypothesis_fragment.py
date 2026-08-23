"""Scoped, immutable hypothesis fragment contract.

Each hypothesis-design child session produces one fragment.  The fragment is
the only input accepted by the fan-in aggregator; conversation messages are
deliberately not part of this contract.  Identity fields are kept explicit so
that a fragment can be rejected before it is allowed to cross a workflow
scope boundary.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._canonical import sha256_hex
from ._validation import (
    ContractValidationError,
    require_int,
    require_list,
    require_mapping,
    require_score,
    require_text,
)

# Adding the v2 hypothesis semantics is a breaking contract change: old
# fragments do not contain the required novelty/boundary facts and therefore
# must not be replayed as formal Challenge Cup evidence.
HYPOTHESIS_FRAGMENT_SCHEMA_VERSION = 2
HYPOTHESIS_FRAGMENT_KIND = "hypothesis_fragment"

_PORTFOLIO_SCORE_KEYS = (
    "novelty",
    "competitionFit",
    "falsifiability",
    "evidenceSupport",
    "feasibility",
)


def _string_list(
    payload: Mapping[str, Any], key: str, *, non_empty: bool = False
) -> tuple[str, ...]:
    values = require_list(payload, key, non_empty=non_empty)
    result = tuple(str(item or "").strip() for item in values)
    if any(not item for item in result):
        raise ContractValidationError(f"{key} must not contain empty entries")
    if len(set(result)) != len(result):
        raise ContractValidationError(f"{key} values must be unique")
    return result


def _aliased_value(
    payload: Mapping[str, Any], canonical: str, *aliases: str
) -> Any:
    """Return one canonical field while rejecting conflicting aliases."""

    keys = (canonical, *aliases)
    present = [(key, payload[key]) for key in keys if key in payload]
    if not present:
        raise ContractValidationError(f"missing required hypothesis field: {canonical}")
    first_key, first_value = present[0]
    for key, value in present[1:]:
        if value != first_value:
            raise ContractValidationError(
                f"hypothesis field aliases {first_key} and {key} disagree"
            )
    return first_value


def _aliased_text(
    payload: Mapping[str, Any], canonical: str, *aliases: str
) -> str:
    value = _aliased_value(payload, canonical, *aliases)
    normalized = str(value or "").strip()
    if not normalized:
        raise ContractValidationError(f"{canonical} must be a non-empty string")
    return normalized


def _aliased_string_list(
    payload: Mapping[str, Any], canonical: str, *aliases: str
) -> tuple[str, ...]:
    value = _aliased_value(payload, canonical, *aliases)
    # ``_string_list`` expects a mapping so that its error names stay tied to
    # the canonical v2 field; aliases are resolved before this point.
    return _string_list({canonical: value}, canonical, non_empty=True)


def _content_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the hash input without the caller-supplied digest."""
    result = dict(payload)
    result.pop("contentHash", None)
    return result


@dataclass(frozen=True, slots=True)
class HypothesisFragment:
    """One candidate-scoped hypothesis result from a child session."""

    schemaVersion: int
    kind: str
    workflowRunId: str
    workflowNodeId: str
    nodeRunId: str
    selectionId: str
    candidateId: str
    sessionId: str
    sessionAttempt: int
    taskId: str
    provenance: dict[str, Any]
    statement: str
    mechanism: str
    novelty_basis: str
    predictions: tuple[str, ...]
    falsificationCriteria: tuple[str, ...]
    evidenceRefs: tuple[str, ...]
    counterEvidenceRefs: tuple[str, ...]
    boundary_conditions: tuple[str, ...]
    scores: dict[str, float]
    contentHash: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HypothesisFragment:
        if not isinstance(payload, Mapping):
            raise ContractValidationError("hypothesis fragment must be an object")
        payload = dict(payload)
        schema_version = payload.get("schemaVersion")
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != HYPOTHESIS_FRAGMENT_SCHEMA_VERSION
        ):
            raise ContractValidationError(
                f"schemaVersion must be {HYPOTHESIS_FRAGMENT_SCHEMA_VERSION}"
            )
        kind = require_text(payload, "kind")
        if kind != HYPOTHESIS_FRAGMENT_KIND:
            raise ContractValidationError(
                f"kind must be {HYPOTHESIS_FRAGMENT_KIND}"
            )
        raw_scores = require_mapping(payload, "scores")
        missing_scores = [key for key in _PORTFOLIO_SCORE_KEYS if key not in raw_scores]
        if missing_scores:
            raise ContractValidationError(
                "missing hypothesis fragment scores: " + ", ".join(missing_scores)
            )
        fragment = cls(
            schemaVersion=schema_version,
            kind=kind,
            workflowRunId=require_text(payload, "workflowRunId"),
            workflowNodeId=require_text(payload, "workflowNodeId"),
            nodeRunId=require_text(payload, "nodeRunId"),
            selectionId=require_text(payload, "selectionId"),
            candidateId=require_text(payload, "candidateId"),
            sessionId=require_text(payload, "sessionId"),
            sessionAttempt=require_int(payload, "sessionAttempt", minimum=1),
            taskId=require_text(payload, "taskId"),
            provenance=require_mapping(payload, "provenance"),
            statement=require_text(payload, "statement"),
            mechanism=require_text(payload, "mechanism"),
            novelty_basis=_aliased_text(payload, "novelty_basis", "noveltyBasis"),
            predictions=_string_list(payload, "predictions", non_empty=True),
            falsificationCriteria=_string_list(
                payload, "falsificationCriteria", non_empty=True
            ),
            evidenceRefs=_string_list(payload, "evidenceRefs"),
            counterEvidenceRefs=_string_list(payload, "counterEvidenceRefs"),
            boundary_conditions=_aliased_string_list(
                payload, "boundary_conditions", "boundaryConditions"
            ),
            scores={
                key: require_score(raw_scores[key], f"scores.{key}")
                for key in _PORTFOLIO_SCORE_KEYS
            },
            contentHash=require_text(payload, "contentHash").lower(),
        )
        expected_hash = sha256_hex(_content_payload(fragment.to_dict(include_hash=False)))
        if fragment.contentHash != expected_hash:
            raise ContractValidationError(
                "contentHash does not match the hypothesis fragment content"
            )
        return fragment

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        result = {
            "schemaVersion": self.schemaVersion,
            "kind": self.kind,
            "workflowRunId": self.workflowRunId,
            "workflowNodeId": self.workflowNodeId,
            "nodeRunId": self.nodeRunId,
            "selectionId": self.selectionId,
            "candidateId": self.candidateId,
            "sessionId": self.sessionId,
            "sessionAttempt": self.sessionAttempt,
            "taskId": self.taskId,
            "provenance": copy.deepcopy(self.provenance),
            "statement": self.statement,
            "mechanism": self.mechanism,
            "novelty_basis": self.novelty_basis,
            "predictions": list(self.predictions),
            "falsificationCriteria": list(self.falsificationCriteria),
            "evidenceRefs": list(self.evidenceRefs),
            "counterEvidenceRefs": list(self.counterEvidenceRefs),
            "boundary_conditions": list(self.boundary_conditions),
            "scores": copy.deepcopy(self.scores),
        }
        if include_hash:
            result["contentHash"] = self.contentHash
        return result

    def with_computed_hash(self) -> HypothesisFragment:
        """Return the same fragment with its canonical content hash."""
        content_hash = sha256_hex(self.to_dict(include_hash=False))
        return HypothesisFragment(
            schemaVersion=self.schemaVersion,
            kind=self.kind,
            workflowRunId=self.workflowRunId,
            workflowNodeId=self.workflowNodeId,
            nodeRunId=self.nodeRunId,
            selectionId=self.selectionId,
            candidateId=self.candidateId,
            sessionId=self.sessionId,
            sessionAttempt=self.sessionAttempt,
            taskId=self.taskId,
            provenance=copy.deepcopy(self.provenance),
            statement=self.statement,
            mechanism=self.mechanism,
            novelty_basis=self.novelty_basis,
            predictions=self.predictions,
            falsificationCriteria=self.falsificationCriteria,
            evidenceRefs=self.evidenceRefs,
            counterEvidenceRefs=self.counterEvidenceRefs,
            boundary_conditions=self.boundary_conditions,
            scores=copy.deepcopy(self.scores),
            contentHash=content_hash,
        )

def canonical_fragment_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a raw fragment and return a hash-bound canonical payload."""
    raw = dict(payload)
    raw.setdefault("schemaVersion", HYPOTHESIS_FRAGMENT_SCHEMA_VERSION)
    raw.setdefault("kind", HYPOTHESIS_FRAGMENT_KIND)
    # Ignore model-only adornments at the contract boundary.  Otherwise a
    # caller could hash fields that the immutable contract does not retain and
    # every subsequent read would fail its own digest check.
    known = {
        "schemaVersion",
        "kind",
        "workflowRunId",
        "workflowNodeId",
        "nodeRunId",
        "selectionId",
        "candidateId",
        "sessionId",
        "sessionAttempt",
        "taskId",
        "provenance",
        "statement",
        "mechanism",
        "novelty_basis",
        "noveltyBasis",
        "predictions",
        "falsificationCriteria",
        "evidenceRefs",
        "counterEvidenceRefs",
        "boundary_conditions",
        "boundaryConditions",
        "scores",
    }
    normalized = {key: value for key, value in raw.items() if key in known}
    for canonical, aliases in (
        ("novelty_basis", ("noveltyBasis",)),
        ("boundary_conditions", ("boundaryConditions",)),
    ):
        # Resolve against the raw payload before removing aliases so a caller
        # cannot submit two conflicting spellings and hash only one of them.
        normalized[canonical] = _aliased_value(raw, canonical, *aliases)
        for alias in aliases:
            normalized.pop(alias, None)
    normalized["contentHash"] = sha256_hex(normalized)
    return HypothesisFragment.from_dict(normalized).to_dict()


__all__ = [
    "HYPOTHESIS_FRAGMENT_KIND",
    "HYPOTHESIS_FRAGMENT_SCHEMA_VERSION",
    "HypothesisFragment",
    "canonical_fragment_payload",
]
