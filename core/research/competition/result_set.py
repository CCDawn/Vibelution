"""FullCatalogResultSet contract and question result locators.

Offline core contract layer for the Challenge Cup 125-question catalog.
This module never touches routes, runtime managers, models, or the network.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any, Iterable

from .resources import (
    CATALOG_ID,
    CATALOG_QUESTION_COUNT,
    CATALOG_SHA256,
    load_science_question_catalog,
)

CATALOG_VERSION = "1"
DEFAULT_TEMPLATE_VERSION = "challenge-question-v2"


class ResultSetContractError(ValueError):
    """A FullCatalogResultSet invariant was violated."""


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

    def to_dict(self) -> dict[str, Any]:
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
    def from_dict(cls, data: dict[str, Any]) -> "QuestionResult":
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
        reasons: list[str] = []
        if present != CATALOG_QUESTION_COUNT:
            reasons.append(f"present_count_{present}_required_{CATALOG_QUESTION_COUNT}")
        if missing:
            reasons.append(f"missing_official_questions_{len(missing)}")
        if eligible != CATALOG_QUESTION_COUNT:
            reasons.append(f"submission_eligible_count_{eligible}_required_{CATALOG_QUESTION_COUNT}")
        if self._duplicate_attempts:
            reasons.append(f"duplicate_attempts_{self.duplicate_count()}")
        return {
            "submission_ready": not reasons,
            "reasons": reasons,
            "present_count": present,
            "missing_count": len(missing),
            "submission_eligible_count": eligible,
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
        return {
            "catalog_id": self._scope.catalog_id,
            "catalog_version": self._scope.catalog_version,
            "scope_hash": self._scope.scope_hash,
            "official_question_count": CATALOG_QUESTION_COUNT,
            "present_count": self.present_count(),
            "missing_count": self.missing_count(),
            "duplicate_count": self.duplicate_count(),
            "submission_eligible_count": self.eligible_count(),
            "submission_ready": self.is_submission_ready(),
        }

    def to_checkpoint(self) -> dict[str, Any]:
        return {
            "scope": self._scope.to_dict(),
            "results": [result.to_dict() for result in self.results()],
            "duplicate_attempts": list(self._duplicate_attempts),
        }

    @classmethod
    def from_checkpoint(cls, data: dict[str, Any]) -> "FullCatalogResultSet":
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
            result_set.add_result(QuestionResult.from_dict(raw))
        duplicates = data.get("duplicate_attempts")
        if isinstance(duplicates, list):
            result_set._duplicate_attempts = [str(item) for item in duplicates]
        return result_set