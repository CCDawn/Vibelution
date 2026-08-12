"""ActionAdapter protocol and registry (spec 10.1).

Adapters receive the stable actionId as their idempotency identity, read
back inputs before side effects, reserve budget before creating any task,
and only produce verified receipts after domain read-back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from core.research.workflow.contracts import PendingAction


@dataclass(frozen=True)
class AdapterPreflight:
    ready: bool
    blockers: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "blockers": list(self.blockers)}


@dataclass(frozen=True)
class BudgetReservation:
    reservation_id: str
    action_id: str
    stage_id: str
    reserved: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reservationId": self.reservation_id,
            "actionId": self.action_id,
            "stageId": self.stage_id,
            "reserved": dict(self.reserved),
        }


@dataclass(frozen=True)
class AdapterResult:
    action_id: str
    outcome: str
    materialized_refs: tuple[dict[str, str], ...] = ()
    anchor: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    reserved: dict[str, Any] = field(default_factory=dict)
    problem: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "actionId": self.action_id,
            "outcome": self.outcome,
            "materializedRefs": list(self.materialized_refs),
            "usage": dict(self.usage),
        }
        if self.anchor:
            payload["anchor"] = dict(self.anchor)
        if self.reserved:
            payload["reserved"] = dict(self.reserved)
        if self.problem:
            payload["problem"] = dict(self.problem)
        return payload


@dataclass(frozen=True)
class VerifiedDomainResult:
    action_id: str
    artifact_receipts: tuple[dict[str, Any], ...]
    anchor: dict[str, Any] | None
    budget_receipt: dict[str, Any] | None
    outcome: str
    problem: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "actionId": self.action_id,
            "outcome": self.outcome,
            "artifactReceipts": list(self.artifact_receipts),
        }
        if self.anchor:
            payload["anchor"] = dict(self.anchor)
        if self.budget_receipt:
            payload["budgetReceipt"] = dict(self.budget_receipt)
        if self.problem:
            payload["problem"] = dict(self.problem)
        return payload


class ActionAdapter(Protocol):
    action_kind: str

    def preflight(self, action: PendingAction) -> AdapterPreflight: ...

    def execute(self, action: PendingAction) -> AdapterResult: ...

    def verify(self, action: PendingAction, result: AdapterResult) -> VerifiedDomainResult: ...


class ActionRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ActionAdapter] = {}

    def register(self, adapter: ActionAdapter) -> None:
        self._adapters[adapter.action_kind] = adapter

    def get(self, action_kind: str) -> ActionAdapter | None:
        return self._adapters.get(action_kind)

    def assert_registered(self, action_kinds: set[str]) -> None:
        missing = sorted(action_kinds - set(self._adapters))
        if missing:
            raise AssertionError(f"missing adapters for action kinds: {missing}")

    def kinds(self) -> set[str]:
        return set(self._adapters)
