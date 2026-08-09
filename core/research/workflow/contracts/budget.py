"""Per-stage research budget ledger contract."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._validation import ContractValidationError, require_mapping, require_text


@dataclass(frozen=True, slots=True)
class ResearchBudgetLedger:
    budgetLedgerId: str
    runId: str
    stageId: str
    policySnapshotHash: str
    limits: dict[str, int]
    reserved: dict[str, int]
    consumed: dict[str, int]
    stopReason: str
    updatedAt: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ResearchBudgetLedger:
        limits = _integer_budget_map(require_mapping(payload, "limits"), "limits")
        reserved = _integer_budget_map(
            require_mapping(payload, "reserved", non_empty=False), "reserved"
        )
        consumed = _integer_budget_map(
            require_mapping(payload, "consumed", non_empty=False), "consumed"
        )
        unknown = (set(reserved) | set(consumed)) - set(limits)
        if unknown:
            raise ContractValidationError(
                f"budget counters missing limits: {', '.join(sorted(unknown))}"
            )
        for key, limit in limits.items():
            if reserved.get(key, 0) + consumed.get(key, 0) > limit:
                raise ContractValidationError(f"budget exceeded for {key}")
        return cls(
            budgetLedgerId=require_text(payload, "budgetLedgerId"),
            runId=require_text(payload, "runId"),
            stageId=require_text(payload, "stageId"),
            policySnapshotHash=require_text(payload, "policySnapshotHash"),
            limits=limits,
            reserved=reserved,
            consumed=consumed,
            stopReason=str(payload.get("stopReason") or "").strip(),
            updatedAt=require_text(payload, "updatedAt"),
        )

    def remaining(self) -> dict[str, int]:
        return {
            key: limit - self.reserved.get(key, 0) - self.consumed.get(key, 0)
            for key, limit in self.limits.items()
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "budgetLedgerId": self.budgetLedgerId,
            "runId": self.runId,
            "stageId": self.stageId,
            "policySnapshotHash": self.policySnapshotHash,
            "limits": copy.deepcopy(self.limits),
            "reserved": copy.deepcopy(self.reserved),
            "consumed": copy.deepcopy(self.consumed),
            "remaining": self.remaining(),
            "stopReason": self.stopReason,
            "updatedAt": self.updatedAt,
        }


def _integer_budget_map(payload: Mapping[str, Any], field: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, value in payload.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ContractValidationError(f"{field}.{key} must be an integer >= 0")
        result[str(key)] = value
    return result
