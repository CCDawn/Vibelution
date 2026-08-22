"""Offline 125-question batch state machine and DEV fixture plans.

Pure contract layer: no routes, runtime managers, models, or network access.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from .resources import load_full_catalog_execution_core, load_science_question_catalog
from .result_set import (
    CatalogScope,
    FullCatalogResultSet,
    QuestionResult,
    official_question_ids,
)

if TYPE_CHECKING:
    from .question_result_package import QuestionResultPackage


CATALOG_EXECUTION_CHECKPOINT_SCHEMA_VERSION = 2


class CatalogExecutionError(ValueError):
    """A catalog execution contract was violated."""


class QuestionBlockedError(CatalogExecutionError):
    """A single question is blocked and must not re-run automatically."""


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CatalogExecutionError(
            "Catalog execution checkpoint must be canonical JSON."
        ) from exc
    return hashlib.sha256(encoded).hexdigest().upper()


def _validate_checkpoint_envelope(data: Mapping[str, Any]) -> bool:
    schema_version = data.get("schema_version")
    if schema_version is None:
        return False
    if schema_version != CATALOG_EXECUTION_CHECKPOINT_SCHEMA_VERSION:
        raise CatalogExecutionError(
            "CatalogExecutionState checkpoint schema version is unsupported."
        )
    supplied_hash = str(data.get("checkpoint_sha256") or "").strip().upper()
    if not supplied_hash:
        raise CatalogExecutionError("CatalogExecutionState checkpoint hash is required.")
    body = {key: value for key, value in data.items() if key != "checkpoint_sha256"}
    if supplied_hash != _canonical_sha256(body):
        raise CatalogExecutionError(
            "CatalogExecutionState checkpoint hash does not match its content."
        )
    return True


class QuestionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class CatalogExecutionPlan:
    """An ordered selection of official questions for one DEV fixture plan."""

    plan_id: str
    gate_id: str
    question_ids: tuple[str, ...]

    @property
    def question_count(self) -> int:
        return len(self.question_ids)


_PLAN_GATES = {
    "dev-0": "G0_DEV",
    "dev-1": "G1",
    "dev-5": "G5",
    "dev-12": "G12",
    "dev-125": "G125",
}
DEV_PLAN_IDS = tuple(_PLAN_GATES)


@lru_cache(maxsize=1)
def _progressive_gates() -> dict[str, dict[str, Any]]:
    core = load_full_catalog_execution_core()
    gates = core.get("progressiveGates")
    if not isinstance(gates, list):
        raise CatalogExecutionError("Full Catalog execution core has no progressive gates.")
    return {str(gate.get("gateId")): gate for gate in gates if isinstance(gate, dict)}


def _gate_question_ids(gate_id: str) -> tuple[str, ...]:
    gate = _progressive_gates().get(gate_id)
    if gate is None:
        raise CatalogExecutionError(f"Unknown gate id: {gate_id}.")
    declared = gate.get("questionIds")
    if isinstance(declared, list):
        ids = [str(item) for item in declared]
    else:
        catalog = load_science_question_catalog()
        questions = catalog.get("questions")
        if not isinstance(questions, list):
            raise CatalogExecutionError("Question catalog resource is unavailable.")
        ids = [str(item.get("id")) for item in questions if isinstance(item, dict)]
    if len(set(ids)) != len(ids):
        raise CatalogExecutionError(f"Gate {gate_id} declares duplicate question ids.")
    return tuple(ids)


def dev_plan(plan_id: str) -> CatalogExecutionPlan:
    if plan_id not in _PLAN_GATES:
        raise CatalogExecutionError(f"Unknown DEV plan: {plan_id}.")
    gate_id = _PLAN_GATES[plan_id]
    return CatalogExecutionPlan(
        plan_id=plan_id,
        gate_id=gate_id,
        question_ids=_gate_question_ids(gate_id),
    )


def catalog_plan(plan_id: str, gate_id: str) -> CatalogExecutionPlan:
    """Build a named plan over one progressive gate's frozen question ids."""
    normalized_plan_id = str(plan_id or "").strip()
    if not normalized_plan_id:
        raise CatalogExecutionError("Plan id must not be empty.")
    return CatalogExecutionPlan(
        plan_id=normalized_plan_id,
        gate_id=gate_id,
        question_ids=_gate_question_ids(gate_id),
    )


def dev_plans() -> tuple[CatalogExecutionPlan, ...]:
    return tuple(dev_plan(plan_id) for plan_id in DEV_PLAN_IDS)


@dataclass
class QuestionRunRecord:
    question_id: str
    status: QuestionStatus = QuestionStatus.PENDING
    attempts: int = 0
    invalidated: bool = False
    last_error: str | None = None
    result: QuestionResult | None = None

    def to_checkpoint(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "status": self.status.value,
            "attempts": self.attempts,
            "invalidated": self.invalidated,
            "last_error": self.last_error,
            "result": self.result.to_dict() if self.result is not None else None,
        }

    @classmethod
    def from_checkpoint(
        cls,
        data: dict[str, Any],
        *,
        expected_model_policy_sha256: str | None = None,
    ) -> QuestionRunRecord:
        try:
            record = cls(
                question_id=str(data["question_id"]),
                status=QuestionStatus(str(data["status"])),
                attempts=int(data["attempts"]),
                invalidated=bool(data["invalidated"]),
                last_error=str(data["last_error"]) if data.get("last_error") is not None else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CatalogExecutionError("QuestionRunRecord checkpoint is malformed.") from exc
        raw_result = data.get("result")
        if raw_result is not None:
            try:
                record.result = QuestionResult.from_dict(
                    raw_result,
                    expected_model_policy_sha256=expected_model_policy_sha256,
                )
            except (TypeError, ValueError, KeyError) as exc:
                raise CatalogExecutionError(
                    "QuestionRunRecord package checkpoint requires an authorized model policy and valid canonical content."
                ) from exc
        return record


def _package_identity(result: QuestionResult, field: str) -> str:
    snapshot = result.package_snapshot
    return str(snapshot.get(field) or "") if snapshot is not None else ""


def _validate_record_semantics(
    record: QuestionRunRecord,
    *,
    is_v2: bool,
) -> None:
    result = record.result
    if record.status is QuestionStatus.SUCCEEDED and result is None:
        raise CatalogExecutionError(
            "CatalogExecutionState SUCCEEDED record requires a result."
        )
    if (
        is_v2
        and record.invalidated
        and record.status not in {QuestionStatus.FAILED, QuestionStatus.BLOCKED}
    ):
        raise CatalogExecutionError(
            "CatalogExecutionState invalidated v2 record semantics are invalid."
        )
    if not is_v2 and (result is None or not result.is_package_backed):
        return
    if result is not None and not result.is_package_backed:
        raise CatalogExecutionError(
            "CatalogExecutionState v2 result records must be package-backed."
        )
    if result is None:
        if record.status in {
            QuestionStatus.PENDING,
            QuestionStatus.RUNNING,
            QuestionStatus.FAILED,
            QuestionStatus.BLOCKED,
        }:
            return
        raise CatalogExecutionError(
            "CatalogExecutionState v2 record semantics are invalid."
        )

    quality_status = result.quality_status
    human_gate_status = result.human_gate_status
    valid = {
        QuestionStatus.PENDING: False,
        QuestionStatus.RUNNING: (
            quality_status == "approved" and human_gate_status == "pending"
        ),
        QuestionStatus.SUCCEEDED: (
            quality_status == "approved" and human_gate_status == "approved"
        ),
        QuestionStatus.FAILED: quality_status == "failed",
        QuestionStatus.BLOCKED: (
            quality_status == "blocked" or human_gate_status == "blocked"
        ),
    }[record.status]
    if not valid:
        raise CatalogExecutionError(
            "CatalogExecutionState v2 record semantics are invalid."
        )


class CatalogExecutionState:
    """Idempotent per-question batch state machine bound to one catalog scope."""

    def __init__(self, *, plan: CatalogExecutionPlan, scope: CatalogScope):
        if len(plan.question_ids) != len(set(plan.question_ids)):
            raise CatalogExecutionError("Plan declares duplicate question ids.")
        official = set(official_question_ids())
        unknown = [question_id for question_id in plan.question_ids if question_id not in official]
        if unknown:
            raise CatalogExecutionError(f"Plan declares non-official question ids: {unknown}.")
        self._plan = plan
        self._scope = scope
        self._records: dict[str, QuestionRunRecord] = {}
        for question_id in plan.question_ids:
            self._records[question_id] = QuestionRunRecord(question_id=question_id)

    @property
    def plan(self) -> CatalogExecutionPlan:
        return self._plan

    @property
    def scope(self) -> CatalogScope:
        return self._scope

    def _require_in_plan(self, question_id: str) -> None:
        if question_id not in self._records:
            raise CatalogExecutionError(f"Question is not part of the plan: {question_id}.")

    def identity_key(self, question_id: str) -> tuple[str, str]:
        return (question_id, self._scope.scope_hash)

    def result_cache_key(self, question_id: str) -> str:
        self._require_in_plan(question_id)
        return self._scope.locator_for(question_id).cache_key()

    def status(self, question_id: str) -> QuestionStatus:
        self._require_in_plan(question_id)
        return self._records[question_id].status

    def attempts(self, question_id: str) -> int:
        self._require_in_plan(question_id)
        return self._records[question_id].attempts

    def _needs_run(self, question_id: str) -> bool:
        record = self._records[question_id]
        if record.invalidated:
            return True
        return record.status in (QuestionStatus.PENDING, QuestionStatus.RUNNING)

    def pending_question_ids(self) -> tuple[str, ...]:
        return tuple(
            question_id
            for question_id in self._plan.question_ids
            if self._needs_run(question_id)
        )

    def mark_running(self, question_id: str) -> None:
        self._require_in_plan(question_id)
        record = self._records[question_id]
        if record.result is not None and record.result.is_package_backed:
            raise CatalogExecutionError(
                f"Question {question_id} has a package-backed attempt; "
                "use record_package after explicit invalidation."
            )
        record.status = QuestionStatus.RUNNING
        record.invalidated = False
        record.attempts += 1

    def _begin_package_attempt(self, question_id: str) -> None:
        record = self._records[question_id]
        if (
            record.result is not None
            and record.result.is_package_backed
            and not record.invalidated
        ):
            raise CatalogExecutionError(
                f"Question {question_id} package attempt requires explicit "
                "invalidation."
            )
        record.status = QuestionStatus.RUNNING
        record.invalidated = False
        record.attempts += 1
        record.last_error = None
        record.result = None

    def _begin_batch_attempt(self, question_id: str) -> None:
        self._require_in_plan(question_id)
        record = self._records[question_id]
        if record.result is not None and record.result.is_package_backed:
            if not record.invalidated:
                raise CatalogExecutionError(
                    f"Question {question_id} package-backed batch attempt "
                    "requires explicit invalidation."
                )
            self._begin_package_attempt(question_id)
            return
        self.mark_running(question_id)

    def record_success(self, question_id: str, result: QuestionResult) -> None:
        self._require_in_plan(question_id)
        if result.locator.identity_key() != self.identity_key(question_id):
            raise CatalogExecutionError(
                f"Result locator does not match question and scope: {question_id}."
            )
        if result.is_package_backed:
            raise CatalogExecutionError(
                f"Question {question_id} package-backed result must be recorded "
                "through record_package."
            )
        record = self._records[question_id]
        if record.result is not None and record.result.is_package_backed:
            raise CatalogExecutionError(
                f"Question {question_id} package-backed attempt cannot be "
                "overwritten by a legacy result."
            )
        record.status = QuestionStatus.SUCCEEDED
        record.invalidated = False
        record.last_error = None
        record.result = result

    def record_failure(
        self,
        question_id: str,
        reason: str,
        *,
        result: QuestionResult | None = None,
    ) -> None:
        self._require_in_plan(question_id)
        record = self._records[question_id]
        if result is not None and result.is_package_backed:
            raise CatalogExecutionError(
                f"Question {question_id} package-backed result must be recorded "
                "through record_package."
            )
        if record.result is not None and record.result.is_package_backed:
            raise CatalogExecutionError(
                f"Question {question_id} package-backed attempt must advance "
                "through record_package."
            )
        record.status = QuestionStatus.FAILED
        record.last_error = str(reason)
        record.result = result

    def record_blocked(
        self,
        question_id: str,
        reason: str,
        *,
        result: QuestionResult | None = None,
    ) -> None:
        self._require_in_plan(question_id)
        record = self._records[question_id]
        if result is not None and result.is_package_backed:
            raise CatalogExecutionError(
                f"Question {question_id} package-backed result must be recorded "
                "through record_package."
            )
        if record.result is not None and record.result.is_package_backed:
            raise CatalogExecutionError(
                f"Question {question_id} package-backed attempt must advance "
                "through record_package."
            )
        record.status = QuestionStatus.BLOCKED
        record.last_error = str(reason)
        record.result = result

    def record_package(self, package: QuestionResultPackage) -> None:
        """Map package quality and human decisions onto the existing state machine."""

        result = QuestionResult.from_package(package)
        question_id = result.question_id
        self._require_in_plan(question_id)
        if result.locator.identity_key() != self.identity_key(question_id):
            raise CatalogExecutionError(
                f"Package locator does not match question and scope: {question_id}."
            )
        record = self._records[question_id]
        existing_result = record.result
        if record.status is QuestionStatus.SUCCEEDED:
            existing_hash = (
                _package_identity(existing_result, "canonical_sha256")
                if existing_result is not None and existing_result.is_package_backed
                else ""
            )
            incoming_hash = _package_identity(result, "canonical_sha256")
            if existing_hash and existing_hash == incoming_hash:
                return
            raise CatalogExecutionError(
                f"Question {question_id} already succeeded with a different package."
            )
        if (
            record.status in {QuestionStatus.FAILED, QuestionStatus.BLOCKED}
            and not record.invalidated
        ):
            raise CatalogExecutionError(
                f"Question {question_id} must be explicitly invalidated before recording a new package."
            )

        starts_new_attempt = record.status is QuestionStatus.PENDING or record.invalidated
        if starts_new_attempt:
            self._begin_package_attempt(question_id)
            record = self._records[question_id]
        elif record.status is QuestionStatus.RUNNING and existing_result is not None:
            if (
                not existing_result.is_package_backed
                or existing_result.human_gate_status != "pending"
            ):
                raise CatalogExecutionError(
                    f"Question {question_id} has invalid RUNNING package state."
                )
            if _package_identity(
                existing_result, "idempotency_key"
            ) != _package_identity(result, "idempotency_key"):
                raise CatalogExecutionError(
                    f"Question {question_id} pending package idempotency identity does not match."
                )
        quality_status = result.quality_status
        human_gate_status = result.human_gate_status
        if quality_status == "failed":
            package_snapshot = result.package_snapshot
            failure = package_snapshot.get("failure") if package_snapshot else None
            reason = (
                str(failure.get("message") or "package failed")
                if isinstance(failure, dict)
                else "package failed"
            )
            record.status = QuestionStatus.FAILED
            record.invalidated = False
            record.last_error = reason
            record.result = result
            return
        if quality_status == "blocked" or human_gate_status == "blocked":
            record.status = QuestionStatus.BLOCKED
            record.invalidated = False
            record.last_error = "package blocked by quality or human review"
            record.result = result
            return
        if quality_status != "approved":
            raise CatalogExecutionError(
                f"Package has unsupported quality status: {quality_status}."
            )
        if human_gate_status == "approved":
            record.status = QuestionStatus.SUCCEEDED
            record.invalidated = False
            record.last_error = None
            record.result = result
            return
        record.status = QuestionStatus.RUNNING
        record.invalidated = False
        record.last_error = None
        record.result = result

    def invalidate(self, question_id: str, reason: str) -> None:
        self._require_in_plan(question_id)
        record = self._records[question_id]
        if (
            record.status is QuestionStatus.SUCCEEDED
            and record.result is not None
            and record.result.is_package_backed
        ):
            raise CatalogExecutionError(
                f"Question {question_id} succeeded package cannot be invalidated; "
                "only exact canonical replay is allowed."
            )
        record.invalidated = True
        record.last_error = str(reason)

    def result_for(self, question_id: str) -> QuestionResult | None:
        self._require_in_plan(question_id)
        return self._records[question_id].result

    def succeeded_results(self) -> tuple[QuestionResult, ...]:
        return tuple(
            self._records[question_id].result
            for question_id in self._plan.question_ids
            if self._records[question_id].status is QuestionStatus.SUCCEEDED
            and self._records[question_id].result is not None
        )

    def outcome_summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {status.value: 0 for status in QuestionStatus}
        for record in self._records.values():
            counts[record.status.value] += 1
        return {
            **counts,
            "invalidated": sum(1 for record in self._records.values() if record.invalidated),
            "total_attempts": sum(record.attempts for record in self._records.values()),
            "question_count": len(self._records),
        }

    def package_quality_summary(self) -> dict[str, int]:
        summary = {
            "approved": 0,
            "blocked": 0,
            "failed": 0,
            "pendingHumanGate": 0,
            "packageBacked": 0,
        }
        for record in self._records.values():
            result = record.result
            if result is None or not result.is_package_backed:
                continue
            summary["packageBacked"] += 1
            if result.quality_status in {"approved", "blocked", "failed"}:
                summary[result.quality_status] += 1
            if result.quality_status == "approved" and result.human_gate_status == "pending":
                summary["pendingHumanGate"] += 1
        return summary

    def to_checkpoint(self) -> dict[str, Any]:
        records = list(self._records.values())
        legacy_result_present = any(
            record.result is not None and not record.result.is_package_backed
            for record in records
        )
        for record in records:
            _validate_record_semantics(record, is_v2=not legacy_result_present)
        body = {
            "plan": {
                "plan_id": self._plan.plan_id,
                "gate_id": self._plan.gate_id,
                "question_ids": list(self._plan.question_ids),
            },
            "scope": self._scope.to_dict(),
            "records": [record.to_checkpoint() for record in records],
        }
        if legacy_result_present:
            return body
        v2_body = {
            "schema_version": CATALOG_EXECUTION_CHECKPOINT_SCHEMA_VERSION,
            **body,
        }
        return {**v2_body, "checkpoint_sha256": _canonical_sha256(v2_body)}

    @classmethod
    def from_checkpoint(
        cls,
        data: dict[str, Any],
        *,
        expected_model_policy_sha256: str | None = None,
    ) -> CatalogExecutionState:
        is_v2 = _validate_checkpoint_envelope(data)
        try:
            plan_data = data["plan"]
            plan = CatalogExecutionPlan(
                plan_id=str(plan_data["plan_id"]),
                gate_id=str(plan_data["gate_id"]),
                question_ids=tuple(str(item) for item in plan_data["question_ids"]),
            )
            scope = CatalogScope.from_dict(data["scope"])
        except (KeyError, TypeError) as exc:
            raise CatalogExecutionError("CatalogExecutionState checkpoint is malformed.") from exc
        state = cls(plan=plan, scope=scope)
        raw_records = data.get("records")
        if not isinstance(raw_records, list):
            raise CatalogExecutionError("CatalogExecutionState checkpoint records must be an array.")
        seen_question_ids: set[str] = set()
        for raw in raw_records:
            if not isinstance(raw, dict):
                raise CatalogExecutionError("CatalogExecutionState checkpoint record is malformed.")
            record = QuestionRunRecord.from_checkpoint(
                raw,
                expected_model_policy_sha256=expected_model_policy_sha256,
            )
            if record.question_id in seen_question_ids:
                raise CatalogExecutionError(
                    f"CatalogExecutionState checkpoint repeats record: {record.question_id}."
                )
            seen_question_ids.add(record.question_id)
            if record.question_id not in state._records:
                raise CatalogExecutionError(
                    f"Checkpoint record is not part of the plan: {record.question_id}."
                )
            if record.result is not None:
                if record.result.locator.scope_hash != state._scope.scope_hash:
                    raise CatalogExecutionError(
                        f"Checkpoint result scope hash does not match: {record.question_id}."
                    )
                if record.result.question_id != record.question_id:
                    raise CatalogExecutionError(
                        "Checkpoint result question id does not match its record."
                    )
            _validate_record_semantics(record, is_v2=is_v2)
            state._records[record.question_id] = record
        if is_v2 and seen_question_ids != set(state._records):
            raise CatalogExecutionError(
                "CatalogExecutionState checkpoint must contain exactly one record per plan question."
            )
        return state


def run_pending_batch(
    state: CatalogExecutionState,
    execute_question: Callable[[str], QuestionResult],
    *,
    max_items: int | None = None,
) -> dict[str, Any]:
    """Run every pending item once; a failing item never pollutes its neighbors."""
    pending = list(state.pending_question_ids())
    if max_items is not None:
        if max_items < 0:
            raise CatalogExecutionError("max_items must be non-negative.")
        pending = pending[:max_items]
    outcomes: list[dict[str, Any]] = []
    for question_id in pending:
        state._begin_batch_attempt(question_id)
        try:
            result = execute_question(question_id)
            if result.is_package_backed:
                from .question_result_package import QuestionResultPackage

                package_snapshot = result.package_snapshot
                if package_snapshot is None:
                    raise CatalogExecutionError(
                        "Package-backed result has no package snapshot."
                    )
                state.record_package(QuestionResultPackage.create(package_snapshot))
                outcome = state.status(question_id).value
            else:
                state.record_success(question_id, result)
                outcome = "succeeded"
            outcomes.append({"question_id": question_id, "outcome": outcome})
        except QuestionBlockedError as exc:
            state.record_blocked(question_id, str(exc))
            outcomes.append({"question_id": question_id, "outcome": "blocked"})
        except Exception as exc:
            state.record_failure(question_id, str(exc))
            outcomes.append({"question_id": question_id, "outcome": "failed"})
    return {
        "attempted": [item["question_id"] for item in outcomes],
        "outcomes": outcomes,
        "summary": state.outcome_summary(),
    }


def build_result_set(state: CatalogExecutionState) -> FullCatalogResultSet:
    result_set = FullCatalogResultSet(scope=state.scope)
    for result in state.succeeded_results():
        result_set.add_result(result)
    return result_set
