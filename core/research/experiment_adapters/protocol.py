"""Core ExperimentAdapter protocol and bounded evidence contract (D06).

Unified lifecycle for every experiment adapter:

    prepare -> validate -> execute -> collect -> evaluate -> emit_receipt

Each lifecycle method binds to the immutable ``ResearchScopeEnvelope``, an
explicit ``ExperimentContract`` and a fail-closed ``ControlledLocator``.  The
dispatcher threads prior phase outputs through keyword-only arguments, so the
pipeline ordering is enforced by shape rather than hidden adapter state.

Terminal outcomes are the five-state ``ExperimentOutcome``: ``completed``,
``partial``, ``failed``, ``unavailable`` and ``rejected``.  Evidence receipts
are bounded: log bytes, artifact counts and payload items are capped.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from ..workflow.contracts import ResearchScopeEnvelope, sha256_hex

LIFECYCLE_STAGES = ("prepare", "validate", "execute", "collect", "evaluate", "emit_receipt")

ALLOWED_LOCATOR_KINDS = ("offline", "workspace_relative")

DEFAULT_LOCATOR_MAX_DEPTH = 8


class ExperimentOutcome(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"


class AdapterError(ValueError):
    """Base error for experiment adapter protocol violations."""


class LocatorValidationError(AdapterError):
    """The controlled locator is unsafe or outside the bounded workspace."""


class AdapterUnavailableError(AdapterError):
    """The adapter cannot start (offline or environment unavailable)."""


class AdapterContractError(AdapterError):
    """The experiment contract is malformed or fails closed."""


_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:[/\\]")
_ENV_REFERENCE_RE = re.compile(r"[$%]")
_SHELL_METACHARACTER_RE = re.compile(r'[;&|`<>()\'"]')
_PATH_TRAVERSAL_RE = re.compile(r"(^|[/\\])\.\.([/\\]|$)")
_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._\-/ ]+$")


def validate_relative_path(relative_path: Any) -> None:
    """Fail-closed lexical validation for a controlled relative path.

    Rejects absolute paths, drive-qualified paths, backslashes, ``..``
    traversal, environment references, shell/command metacharacters and
    unsupported characters so a locator can never escape its workspace.
    """
    raw = str(relative_path or "").strip()
    if not raw:
        raise LocatorValidationError("relativePath must be a non-empty relative path.")
    if raw.startswith(("/", "\\")):
        raise LocatorValidationError("relativePath must be relative; absolute paths are rejected.")
    if _DRIVE_LETTER_RE.match(raw):
        raise LocatorValidationError("relativePath must be relative; drive-qualified paths are rejected.")
    if "\\" in raw:
        raise LocatorValidationError("relativePath must use forward slashes only.")
    if "//" in raw or raw.endswith("/"):
        raise LocatorValidationError("relativePath must not contain empty or trailing segments.")
    if _PATH_TRAVERSAL_RE.search(raw):
        raise LocatorValidationError("relativePath must not contain '..' traversal segments.")
    if _ENV_REFERENCE_RE.search(raw):
        raise LocatorValidationError("relativePath must not reference environment variables.")
    if _SHELL_METACHARACTER_RE.search(raw):
        raise LocatorValidationError("relativePath must not contain shell or command metacharacters.")
    if not _PATH_SEGMENT_RE.fullmatch(raw):
        raise LocatorValidationError("relativePath contains unsupported characters.")
    segments = [part for part in raw.split("/") if part]
    if any(part in (".", "..") for part in segments):
        raise LocatorValidationError("relativePath must not contain '.' or '..' segments.")


@dataclass(frozen=True, slots=True)
class ControlledLocator:
    """Immutable, fail-closed locator for a bounded offline workspace.

    Only a whitelisted kind and a lexically validated relative path are
    accepted; every other input is rejected at construction time.
    """

    kind: str
    relativePath: str
    maxDepth: int = DEFAULT_LOCATOR_MAX_DEPTH

    def __post_init__(self) -> None:
        kind = str(self.kind or "").strip().lower()
        if kind not in ALLOWED_LOCATOR_KINDS:
            raise LocatorValidationError(f"unsupported locator kind: {self.kind!r}")
        relative_path = str(self.relativePath or "").strip()
        validate_relative_path(relative_path)
        try:
            depth = int(self.maxDepth)
        except (TypeError, ValueError) as exc:
            raise LocatorValidationError("maxDepth must be an integer.") from exc
        if not 1 <= depth <= 64:
            raise LocatorValidationError("maxDepth must be between 1 and 64.")
        segments = [part for part in relative_path.split("/") if part]
        if len(segments) > depth:
            raise LocatorValidationError("relativePath exceeds the maximum depth.")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "relativePath", relative_path)
        object.__setattr__(self, "maxDepth", depth)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ControlledLocator:
        if not isinstance(payload, Mapping):
            raise LocatorValidationError("locator must be a mapping.")
        return cls(
            kind=str(payload.get("kind") or "").strip(),
            relativePath=str(payload.get("relativePath") or "").strip(),
            maxDepth=payload.get("maxDepth", DEFAULT_LOCATOR_MAX_DEPTH),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "relativePath": self.relativePath, "maxDepth": self.maxDepth}

    def content_hash(self) -> str:
        return sha256_hex(self.to_dict())


def require_controlled_locator(value: Any) -> ControlledLocator:
    """Coerce a mapping to a ControlledLocator or return it unchanged."""
    if isinstance(value, ControlledLocator):
        return value
    if isinstance(value, Mapping):
        return ControlledLocator.from_dict(value)
    raise LocatorValidationError("locator must be a ControlledLocator or a mapping.")


@dataclass(frozen=True, slots=True)
class ExperimentContract:
    """Immutable experiment contract with a canonical content hash.

    The generic identity fields (planId, teamId, experimentMethod) are
    required; the full payload is frozen as a sorted item tuple and hashed so
    the dispatcher can detect conflicting payloads on a shared idempotency key.
    """

    planId: str
    teamId: str
    methodId: str
    payload: tuple[tuple[str, Any], ...]
    contentHash: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ExperimentContract:
        if not isinstance(payload, Mapping):
            raise AdapterContractError("contract must be a mapping.")
        plan_id = _required_contract_text(payload, "planId")
        team_id = _required_contract_text(payload, "teamId")
        method_id = _required_contract_text(payload, "experimentMethod")
        canonical = copy.deepcopy(dict(payload))
        return cls(
            planId=plan_id,
            teamId=team_id,
            methodId=method_id,
            payload=tuple(sorted(canonical.items())),
            contentHash=sha256_hex(canonical),
        )

    def to_dict(self) -> dict[str, Any]:
        return {key: copy.deepcopy(value) for key, value in self.payload}


@dataclass(frozen=True, slots=True)
class BoundedEvidenceReceipt:
    """Bounded evidence receipt emitted after the unified lifecycle.

    Log bytes, artifact counts and payload items are capped by the dispatcher;
    the receipt also carries the no-process/no-GPU/no-network boundary claims.
    """

    receiptId: str
    outcome: ExperimentOutcome
    stage: str
    evidenceHash: str
    artifactCount: int
    logBytes: int
    maxArtifacts: int
    maxLogBytes: int
    boundaries: tuple[str, ...]
    payload: tuple[tuple[str, Any], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", _as_outcome(self.outcome))
        object.__setattr__(self, "boundaries", _as_tuple(self.boundaries))
        object.__setattr__(self, "payload", _as_tuple(self.payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "receiptId": self.receiptId,
            "outcome": self.outcome.value,
            "stage": self.stage,
            "evidenceHash": self.evidenceHash,
            "artifactCount": self.artifactCount,
            "logBytes": self.logBytes,
            "maxArtifacts": self.maxArtifacts,
            "maxLogBytes": self.maxLogBytes,
            "boundaries": list(self.boundaries),
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    """Immutable result of one dispatched experiment run."""

    resultId: str
    idempotencyKey: str
    scopeHash: str
    contractHash: str
    adapterId: str
    adapterVersion: str
    outcome: ExperimentOutcome
    stages: tuple[str, ...]
    stage: str
    phases: tuple[str, ...]
    message: str
    metrics: tuple[tuple[str, Any], ...]
    receipt: BoundedEvidenceReceipt
    boundaries: tuple[str, ...]
    reused: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", _as_outcome(self.outcome))
        object.__setattr__(self, "stages", _as_tuple(self.stages))
        object.__setattr__(self, "phases", _as_tuple(self.phases))
        object.__setattr__(self, "metrics", _as_tuple(self.metrics))
        object.__setattr__(self, "boundaries", _as_tuple(self.boundaries))

    def to_dict(self) -> dict[str, Any]:
        return {
            "resultId": self.resultId,
            "idempotencyKey": self.idempotencyKey,
            "scopeHash": self.scopeHash,
            "contractHash": self.contractHash,
            "adapterId": self.adapterId,
            "adapterVersion": self.adapterVersion,
            "outcome": self.outcome.value,
            "stages": list(self.stages),
            "stage": self.stage,
            "phases": list(self.phases),
            "message": self.message,
            "metrics": dict(self.metrics),
            "receipt": self.receipt.to_dict(),
            "boundaries": list(self.boundaries),
            "reused": self.reused,
        }


@runtime_checkable
class ExperimentAdapter(Protocol):
    """Stateless-per-phase adapter contract for the D06 dispatcher.

    Every phase is bound to the immutable ``ResearchScopeEnvelope``, the
    explicit ``ExperimentContract`` and the fail-closed ``ControlledLocator``.
    Prior phase outputs are threaded through keyword-only arguments so the
    lifecycle order is explicit and cannot be satisfied out of order.
    """

    adapterId: str
    adapterVersion: str
    methodId: str

    def prepare(
        self,
        scope: ResearchScopeEnvelope,
        contract: ExperimentContract,
        locator: ControlledLocator,
    ) -> dict[str, Any]: ...

    def validate(
        self,
        scope: ResearchScopeEnvelope,
        contract: ExperimentContract,
        locator: ControlledLocator,
        *,
        prepared: dict[str, Any],
    ) -> dict[str, Any]: ...

    def execute(
        self,
        scope: ResearchScopeEnvelope,
        contract: ExperimentContract,
        locator: ControlledLocator,
        *,
        prepared: dict[str, Any],
        validated: dict[str, Any],
    ) -> dict[str, Any]: ...

    def collect(
        self,
        scope: ResearchScopeEnvelope,
        contract: ExperimentContract,
        locator: ControlledLocator,
        *,
        executed: dict[str, Any],
    ) -> dict[str, Any]: ...

    def evaluate(
        self,
        scope: ResearchScopeEnvelope,
        contract: ExperimentContract,
        locator: ControlledLocator,
        *,
        collected: dict[str, Any],
    ) -> dict[str, Any]: ...

    def emit_receipt(
        self,
        scope: ResearchScopeEnvelope,
        contract: ExperimentContract,
        locator: ControlledLocator,
        *,
        evaluated: dict[str, Any],
    ) -> dict[str, Any]: ...


def phase_result(status: str, **fields: Any) -> dict[str, Any]:
    """Normalize a phase output; status is ok/partial/failed/unavailable."""
    normalized = str(status or "").strip().lower()
    if normalized not in ("ok", "partial", "failed", "unavailable"):
        raise AdapterError(f"invalid phase status: {status!r}")
    return {"status": normalized, **fields}


def _required_contract_text(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise AdapterContractError(f"contract field {key} is required.")
    return value


def _as_outcome(value: Any) -> ExperimentOutcome:
    if isinstance(value, ExperimentOutcome):
        return value
    try:
        return ExperimentOutcome(str(value or "").strip().lower())
    except ValueError as exc:
        raise AdapterError(f"invalid experiment outcome: {value!r}") from exc


def _as_tuple(value: Any) -> tuple[Any, ...]:
    if isinstance(value, tuple):
        return value
    if isinstance(value, Mapping):
        return tuple(sorted(value.items()))
    if isinstance(value, (list, set, frozenset)):
        return tuple(value)
    raise AdapterError(f"expected a sequence or mapping, got {type(value).__name__}")