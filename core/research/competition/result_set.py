"""FullCatalogResultSet contract and question result locators.

Offline core contract layer for the Challenge Cup 125-question catalog.
This module never touches routes, runtime managers, models, or the network.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from .resources import (
    CATALOG_ID,
    CATALOG_QUESTION_COUNT,
    CATALOG_SHA256,
    load_science_question_catalog,
)

CATALOG_VERSION = "1"
DEFAULT_TEMPLATE_VERSION = "challenge-question-v2"
RESULT_SET_CHECKPOINT_SCHEMA_VERSION = 2
RESULT_MANIFEST_SCHEMA_VERSION = 1
REQUIRED_PACKAGE_RECEIPT_STAGES = ("generation", "review", "revision")
MANIFEST_EVIDENCE_LOCATOR_FIELDS = (
    "kind",
    "evidenceId",
    "outputRef",
    "outputSha256",
    "ref",
)

if TYPE_CHECKING:
    from .question_result_package import QuestionResultPackage


class ResultSetContractError(ValueError):
    """A FullCatalogResultSet invariant was violated."""


def _canonical_json(payload: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ResultSetContractError(
            "Catalog result payload must be canonical JSON."
        ) from exc


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest().upper()


def _checkpoint_body(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "checkpoint_sha256"}


def _validate_checkpoint_envelope(payload: Mapping[str, Any], *, label: str) -> bool:
    """Validate schema-v2 integrity while retaining unversioned legacy reads."""

    schema_version = payload.get("schema_version")
    if schema_version is None:
        return False
    if schema_version != RESULT_SET_CHECKPOINT_SCHEMA_VERSION:
        raise ResultSetContractError(
            f"{label} checkpoint schema version is unsupported."
        )
    supplied_hash = str(payload.get("checkpoint_sha256") or "").strip().upper()
    if not supplied_hash:
        raise ResultSetContractError(f"{label} checkpoint hash is required.")
    if supplied_hash != _canonical_sha256(_checkpoint_body(payload)):
        raise ResultSetContractError(f"{label} checkpoint hash does not match its content.")
    return True


def _manifest_evidence_locator(payload: Mapping[str, Any]) -> dict[str, str]:
    """Project only stable receipt identity fields, never free-form content."""

    identity: dict[str, str] = {}
    for field in MANIFEST_EVIDENCE_LOCATOR_FIELDS:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            identity[field] = value.strip()
    return identity


def compute_scope_hash(
    catalog_id: str = CATALOG_ID,
    catalog_version: str = CATALOG_VERSION,
    catalog_sha256: str = CATALOG_SHA256,
) -> str:
    payload = json.dumps(
        {
            "catalog_id": catalog_id,
            "catalog_version": catalog_version,
            "catalog_sha256": catalog_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()


@lru_cache(maxsize=1)
def _official_question_ids() -> tuple[str, ...]:
    catalog = load_science_question_catalog()
    questions = catalog.get("questions")
    if not isinstance(questions, list):
        raise ResultSetContractError("Question catalog resource is unavailable.")
    ids = tuple(str(item.get("id")) for item in questions if isinstance(item, dict))
    if len(ids) != CATALOG_QUESTION_COUNT or len(set(ids)) != CATALOG_QUESTION_COUNT:
        raise ResultSetContractError("Question catalog must expose 125 unique question ids.")
    return ids


def official_question_ids() -> tuple[str, ...]:
    return _official_question_ids()


def is_official_question_id(question_id: object) -> bool:
    return isinstance(question_id, str) and question_id in _official_question_ids()


@dataclass(frozen=True)
class CatalogScope:
    """Catalog identity that every result, locator, and checkpoint is bound to."""

    catalog_id: str
    catalog_version: str
    catalog_sha256: str
    scope_hash: str

    @classmethod
    def from_tracked_resources(cls) -> "CatalogScope":
        return cls(
            catalog_id=CATALOG_ID,
            catalog_version=CATALOG_VERSION,
            catalog_sha256=CATALOG_SHA256,
            scope_hash=compute_scope_hash(),
        )

    def locator_for(self, question_id: str) -> "QuestionResultLocator":
        return QuestionResultLocator(
            question_id=question_id,
            catalog_id=self.catalog_id,
            catalog_version=self.catalog_version,
            scope_hash=self.scope_hash,
        )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CatalogScope":
        try:
            scope = cls(
                catalog_id=str(data["catalog_id"]),
                catalog_version=str(data["catalog_version"]),
                catalog_sha256=str(data["catalog_sha256"]),
                scope_hash=str(data["scope_hash"]),
            )
        except (KeyError, TypeError) as exc:
            raise ResultSetContractError("CatalogScope checkpoint is malformed.") from exc
        expected = compute_scope_hash(scope.catalog_id, scope.catalog_version, scope.catalog_sha256)
        if scope.scope_hash != expected:
            raise ResultSetContractError("CatalogScope scope_hash does not match its identity.")
        return scope


@dataclass(frozen=True)
class QuestionResultLocator:
    """Identity of a single question result under one catalog scope.

    The identity always pairs the question id with the full scope hash; a
    question-number-only match is never sufficient.
    """

    question_id: str
    scope_hash: str
    catalog_id: str
    catalog_version: str

    def identity_key(self) -> tuple[str, str]:
        return (self.question_id, self.scope_hash)

    def matches(self, other: "QuestionResultLocator") -> bool:
        return self.identity_key() == other.identity_key()

    def cache_key(self) -> str:
        payload = json.dumps(
            {"question_id": self.question_id, "scope_hash": self.scope_hash},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class QuestionResult:
    """A bound single-question result eligible for the full catalog result set."""

    locator: QuestionResultLocator
    model_receipt_locator: str
    knowledge_locator: str
    template_version: str
    status: str = "submission_eligible"
    submission_eligible: bool = True
    _package_snapshot_json: str | None = None

    @classmethod
    def create(
        cls,
        *,
        scope: CatalogScope,
        question_id: str,
        model_receipt_locator: str,
        knowledge_locator: str,
        template_version: str = DEFAULT_TEMPLATE_VERSION,
        submission_eligible: bool = True,
        status: str = "submission_eligible",
    ) -> "QuestionResult":
        if not is_official_question_id(question_id):
            raise ResultSetContractError(f"Not an official catalog question: {question_id}.")
        return cls(
            locator=scope.locator_for(question_id),
            model_receipt_locator=str(model_receipt_locator),
            knowledge_locator=str(knowledge_locator),
            template_version=str(template_version),
            status=status,
            submission_eligible=bool(submission_eligible),
        )

    @classmethod
    def from_package(cls, package: QuestionResultPackage) -> QuestionResult:
        """Project a validated package without creating another content authority."""

        from .question_result_package import QuestionResultPackage

        if not isinstance(package, QuestionResultPackage):
            raise ResultSetContractError(
                "QuestionResult.from_package requires a validated QuestionResultPackage."
            )
        snapshot = package.to_dict()
        gate_decisions = (
            str(package.selection["human_gate"]["decision"]),
            str(package.research_plan["human_gate"]["decision"]),
        )
        quality_status = str(package.result_classification["status"])
        human_gate_approved = all(decision == "approved" for decision in gate_decisions)
        package_locator = f"question-result-package://{package.package_id}"
        return cls(
            locator=package.scope.locator_for(package.question_id),
            model_receipt_locator=f"{package_locator}#model-invocation-receipts",
            knowledge_locator=package_locator,
            template_version=DEFAULT_TEMPLATE_VERSION,
            status=quality_status,
            submission_eligible=quality_status == "approved" and human_gate_approved,
            _package_snapshot_json=_canonical_json(snapshot),
        )

    @property
    def question_id(self) -> str:
        return self.locator.question_id

    @property
    def scope_hash(self) -> str:
        return self.locator.scope_hash

    @property
    def catalog_id(self) -> str:
        return self.locator.catalog_id

    @property
    def catalog_version(self) -> str:
        return self.locator.catalog_version

    @property
    def package_snapshot(self) -> dict[str, Any] | None:
        if self._package_snapshot_json is None:
            return None
        value = json.loads(self._package_snapshot_json)
        if not isinstance(value, dict):
            raise ResultSetContractError("QuestionResult package snapshot is malformed.")
        return value

    @property
    def is_package_backed(self) -> bool:
        return self._package_snapshot_json is not None

    @property
    def quality_status(self) -> str:
        snapshot = self.package_snapshot
        if snapshot is None:
            return "legacy"
        classification = snapshot.get("result_classification")
        return (
            str(classification.get("status") or "")
            if isinstance(classification, dict)
            else ""
        )

    @property
    def human_gate_decisions(self) -> tuple[str, ...]:
        snapshot = self.package_snapshot
        if snapshot is None:
            return ()
        decisions: list[str] = []
        for section_name in ("selection", "research_plan"):
            section = snapshot.get(section_name)
            gate = section.get("human_gate") if isinstance(section, dict) else None
            decisions.append(
                str(gate.get("decision") or "") if isinstance(gate, dict) else ""
            )
        return (decisions[0], decisions[1])

    @property
    def human_gate_status(self) -> str:
        decisions = self.human_gate_decisions
        if not decisions:
            return "legacy"
        if all(decision == "approved" for decision in decisions):
            return "approved"
        if any(decision in {"rejected", "revision_requested"} for decision in decisions):
            return "blocked"
        return "pending"

    @property
    def receipt_complete(self) -> bool:
        snapshot = self.package_snapshot
        receipts = snapshot.get("model_invocation_receipts") if snapshot else None
        return isinstance(receipts, dict) and set(receipts) == set(
            REQUIRED_PACKAGE_RECEIPT_STAGES
        )

    def manifest_entry(self) -> dict[str, Any]:
        snapshot = self.package_snapshot
        if snapshot is None:
            raise ResultSetContractError(
                f"Question result {self.question_id} has no QuestionResultPackage."
            )
        receipts = snapshot.get("model_invocation_receipts")
        if not isinstance(receipts, dict):
            raise ResultSetContractError(
                f"Question result {self.question_id} has malformed package receipts."
            )
        receipt_identities: dict[str, dict[str, Any]] = {}
        for stage in REQUIRED_PACKAGE_RECEIPT_STAGES:
            receipt = receipts.get(stage)
            if not isinstance(receipt, dict):
                raise ResultSetContractError(
                    f"Question result {self.question_id} is missing package receipt {stage}."
                )
            evidence_locator = receipt.get("evidenceLocator")
            normalized_locator = _manifest_evidence_locator(
                evidence_locator if isinstance(evidence_locator, dict) else {}
            )
            receipt_identities[stage] = {
                "receipt_id": str(receipt.get("receiptId") or ""),
                "node_run_id": str(receipt.get("nodeRunId") or ""),
                "evidence_locator": normalized_locator,
                "evidence_locator_sha256": _canonical_sha256(normalized_locator),
            }
        gate_decisions = self.human_gate_decisions
        return {
            "question_id": self.question_id,
            "package_id": str(snapshot.get("package_id") or ""),
            "run_id": str(snapshot.get("run_id") or ""),
            "canonical_sha256": str(snapshot.get("canonical_sha256") or ""),
            "idempotency_key": str(snapshot.get("idempotency_key") or ""),
            "quality_status": self.quality_status,
            "human_gate_decisions": {
                "selection": gate_decisions[0],
                "research_plan": gate_decisions[1],
            },
            "receipts": receipt_identities,
        }

    def to_dict(self) -> dict[str, Any]:
        snapshot = self.package_snapshot
        if snapshot is not None:
            return {"package": snapshot}
        return {
            "question_id": self.question_id,
            "catalog_id": self.catalog_id,
            "catalog_version": self.catalog_version,
            "scope_hash": self.scope_hash,
            "model_receipt_locator": self.model_receipt_locator,
            "knowledge_locator": self.knowledge_locator,
            "template_version": self.template_version,
            "status": self.status,
            "submission_eligible": self.submission_eligible,
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        expected_model_policy_sha256: str | None = None,
    ) -> QuestionResult:
        raw_package = data.get("package")
        if raw_package is not None:
            if set(data) != {"package"}:
                raise ResultSetContractError(
                    "Package-backed QuestionResult cannot duplicate package content."
                )
            if not expected_model_policy_sha256:
                raise ResultSetContractError(
                    "Package checkpoint restore requires an externally authorized model policy hash."
                )
            if not isinstance(raw_package, dict):
                raise ResultSetContractError("QuestionResult package checkpoint is malformed.")
            try:
                from .question_result_package import QuestionResultPackage

                package = QuestionResultPackage.from_dict(
                    raw_package,
                    expected_model_policy_sha256=expected_model_policy_sha256,
                )
            except (TypeError, ValueError, KeyError) as exc:
                raise ResultSetContractError(
                    "QuestionResult package checkpoint failed canonical validation."
                ) from exc
            return cls.from_package(package)
        try:
            question_id = str(data["question_id"])
            scope_hash = str(data["scope_hash"])
            catalog_id = str(data["catalog_id"])
            catalog_version = str(data["catalog_version"])
        except (KeyError, TypeError) as exc:
            raise ResultSetContractError("QuestionResult checkpoint is malformed.") from exc
        if not is_official_question_id(question_id):
            raise ResultSetContractError(f"Not an official catalog question: {question_id}.")
        return cls(
            locator=QuestionResultLocator(
                question_id=question_id,
                scope_hash=scope_hash,
                catalog_id=catalog_id,
                catalog_version=catalog_version,
            ),
            model_receipt_locator=str(data["model_receipt_locator"]),
            knowledge_locator=str(data["knowledge_locator"]),
            template_version=str(data["template_version"]),
            status=str(data.get("status") or "submission_eligible"),
            submission_eligible=bool(data.get("submission_eligible", True)),
        )


class FullCatalogResultSet:
    """Ordered, deduplicated, scope-bound container for the 125-question result set."""

    def __init__(self, *, scope: CatalogScope):
        self._scope = scope
        self._results: dict[tuple[str, str], QuestionResult] = {}
        self._duplicate_attempts: list[str] = []

    @property
    def scope(self) -> CatalogScope:
        return self._scope

    @property
    def catalog_id(self) -> str:
        return self._scope.catalog_id

    @property
    def catalog_version(self) -> str:
        return self._scope.catalog_version

    @property
    def scope_hash(self) -> str:
        return self._scope.scope_hash

    def _validate_binding(self, result: QuestionResult) -> None:
        if result.locator.scope_hash != self._scope.scope_hash:
            raise ResultSetContractError(
                f"Result scope hash does not match the result set: {result.question_id}."
            )
        if result.locator.catalog_id != self._scope.catalog_id:
            raise ResultSetContractError(
                f"Result catalog id does not match the result set: {result.question_id}."
            )
        if result.locator.catalog_version != self._scope.catalog_version:
            raise ResultSetContractError(
                f"Result catalog version does not match the result set: {result.question_id}."
            )

    def add_result(self, result: QuestionResult) -> None:
        self._validate_binding(result)
        key = result.locator.identity_key()
        if key in self._results:
            self._duplicate_attempts.append(result.question_id)
            raise ResultSetContractError(f"Duplicate result for {result.question_id}.")
        self._results[key] = result

    def upsert_result(self, result: QuestionResult) -> None:
        self._validate_binding(result)
        self._results[result.locator.identity_key()] = result

    def add_results(self, results: Iterable[QuestionResult]) -> None:
        for result in results:
            self.add_result(result)

    def has_result(self, question_id: str) -> bool:
        return (question_id, self._scope.scope_hash) in self._results

    def get_result(self, question_id: str) -> QuestionResult | None:
        return self._results.get((question_id, self._scope.scope_hash))

    def results(self) -> tuple[QuestionResult, ...]:
        return tuple(
            self._results[key] for key in sorted(self._results, key=lambda pair: pair[0])
        )

    def present_count(self) -> int:
        return len(self._results)

    def missing_question_ids(self) -> tuple[str, ...]:
        return tuple(
            question_id
            for question_id in official_question_ids()
            if (question_id, self._scope.scope_hash) not in self._results
        )

    def missing_count(self) -> int:
        return len(self.missing_question_ids())

    def eligible_count(self) -> int:
        return sum(1 for result in self._results.values() if result.submission_eligible)

    def non_eligible_question_ids(self) -> tuple[str, ...]:
        return tuple(result.question_id for result in self.results() if not result.submission_eligible)

    def duplicate_count(self) -> int:
        return len(self._duplicate_attempts)

    def submission_state(self) -> dict[str, Any]:
        present = self.present_count()
        eligible = self.eligible_count()
        missing = self.missing_question_ids()
        package_backed = sum(
            1 for result in self._results.values() if result.is_package_backed
        )
        quality_approved = sum(
            1
            for result in self._results.values()
            if result.is_package_backed and result.quality_status == "approved"
        )
        human_gate_approved = sum(
            1
            for result in self._results.values()
            if result.is_package_backed and result.human_gate_status == "approved"
        )
        receipt_complete = sum(
            1
            for result in self._results.values()
            if result.is_package_backed and result.receipt_complete
        )
        reasons: list[str] = []
        if present != CATALOG_QUESTION_COUNT:
            reasons.append(f"present_count_{present}_required_{CATALOG_QUESTION_COUNT}")
        if missing:
            reasons.append(f"missing_official_questions_{len(missing)}")
        if eligible != CATALOG_QUESTION_COUNT:
            reasons.append(f"submission_eligible_count_{eligible}_required_{CATALOG_QUESTION_COUNT}")
        if package_backed != CATALOG_QUESTION_COUNT:
            reasons.append(
                f"package_backed_count_{package_backed}_required_{CATALOG_QUESTION_COUNT}"
            )
        if quality_approved != CATALOG_QUESTION_COUNT:
            reasons.append(
                f"quality_approved_count_{quality_approved}_required_{CATALOG_QUESTION_COUNT}"
            )
        if human_gate_approved != CATALOG_QUESTION_COUNT:
            reasons.append(
                "human_gate_approved_count_"
                f"{human_gate_approved}_required_{CATALOG_QUESTION_COUNT}"
            )
        if receipt_complete != CATALOG_QUESTION_COUNT:
            reasons.append(
                f"receipt_complete_count_{receipt_complete}_required_{CATALOG_QUESTION_COUNT}"
            )
        if self._duplicate_attempts:
            reasons.append(f"duplicate_attempts_{self.duplicate_count()}")
        return {
            "submission_ready": not reasons,
            "reasons": reasons,
            "present_count": present,
            "missing_count": len(missing),
            "submission_eligible_count": eligible,
            "package_backed_count": package_backed,
            "quality_approved_count": quality_approved,
            "human_gate_approved_count": human_gate_approved,
            "receipt_complete_count": receipt_complete,
            "required_question_count": CATALOG_QUESTION_COUNT,
            "duplicate_count": self.duplicate_count(),
        }

    def is_submission_ready(self) -> bool:
        return self.submission_state()["submission_ready"]

    def assert_submission_ready(self) -> dict[str, Any]:
        state = self.submission_state()
        if not state["submission_ready"]:
            raise ResultSetContractError(
                "FullCatalogResultSet is not submission-ready: " + "; ".join(state["reasons"]) + "."
            )
        return state

    def export_counts(self) -> dict[str, Any]:
        state = self.submission_state()
        return {
            "catalog_id": self._scope.catalog_id,
            "catalog_version": self._scope.catalog_version,
            "scope_hash": self._scope.scope_hash,
            "official_question_count": CATALOG_QUESTION_COUNT,
            "present_count": self.present_count(),
            "missing_count": self.missing_count(),
            "duplicate_count": self.duplicate_count(),
            "submission_eligible_count": state["submission_eligible_count"],
            "package_backed_count": state["package_backed_count"],
            "quality_approved_count": state["quality_approved_count"],
            "human_gate_approved_count": state["human_gate_approved_count"],
            "receipt_complete_count": state["receipt_complete_count"],
            "submission_ready": state["submission_ready"],
        }

    def manifest(self) -> dict[str, Any]:
        """Return a stable identity-only manifest; packages remain the content SSOT."""

        body = {
            "schema_version": RESULT_MANIFEST_SCHEMA_VERSION,
            "scope": self._scope.to_dict(),
            "required_question_count": CATALOG_QUESTION_COUNT,
            "entries": [
                result.manifest_entry()
                for result in self.results()
                if result.is_package_backed
            ],
        }
        return {**body, "manifest_sha256": _canonical_sha256(body)}

    def to_checkpoint(self) -> dict[str, Any]:
        body = {
            "schema_version": RESULT_SET_CHECKPOINT_SCHEMA_VERSION,
            "scope": self._scope.to_dict(),
            "results": [result.to_dict() for result in self.results()],
            "duplicate_attempts": list(self._duplicate_attempts),
        }
        return {**body, "checkpoint_sha256": _canonical_sha256(body)}

    @classmethod
    def from_checkpoint(
        cls,
        data: dict[str, Any],
        *,
        expected_model_policy_sha256: str | None = None,
    ) -> FullCatalogResultSet:
        _validate_checkpoint_envelope(data, label="FullCatalogResultSet")
        try:
            scope = CatalogScope.from_dict(data["scope"])
        except (KeyError, TypeError) as exc:
            raise ResultSetContractError("FullCatalogResultSet checkpoint is malformed.") from exc
        result_set = cls(scope=scope)
        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            raise ResultSetContractError("FullCatalogResultSet checkpoint results must be an array.")
        for raw in raw_results:
            if not isinstance(raw, dict):
                raise ResultSetContractError("FullCatalogResultSet checkpoint result is malformed.")
            result_set.add_result(
                QuestionResult.from_dict(
                    raw,
                    expected_model_policy_sha256=expected_model_policy_sha256,
                )
            )
        duplicates = data.get("duplicate_attempts")
        if isinstance(duplicates, list):
            result_set._duplicate_attempts = [str(item) for item in duplicates]
        return result_set
