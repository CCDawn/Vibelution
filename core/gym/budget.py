# -*- coding: utf-8 -*-
"""Idempotent local budget accounting for proposal-only evolution work."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


class BudgetLimitExceeded(ValueError):
    """Raised before a budget event would exceed a configured hard limit."""


@dataclass(frozen=True)
class BudgetUsage:
    candidates: int = 0
    model_calls: int = 0
    metric_calls: int = 0
    cost: float = 0.0
    wall_seconds: float = 0.0

    def __post_init__(self) -> None:
        for field_name, value in asdict(self).items():
            if float(value) < 0:
                raise ValueError(f"Budget usage {field_name} cannot be negative")

    def plus(self, other: "BudgetUsage") -> "BudgetUsage":
        return BudgetUsage(**{key: getattr(self, key) + getattr(other, key) for key in asdict(self)})


@dataclass(frozen=True)
class EvolutionBudget:
    max_candidates: int = 0
    max_model_calls: int = 0
    max_metric_calls: int = 0
    max_cost: float = 0.0
    max_wall_seconds: float = 0.0

    def __post_init__(self) -> None:
        for field_name, value in asdict(self).items():
            if float(value) < 0:
                raise ValueError(f"Budget limit {field_name} cannot be negative")


class EvolutionBudgetLedger:
    """Deduplicates event IDs so recovery cannot charge the same work twice."""

    def __init__(self, budget: EvolutionBudget) -> None:
        self.budget = budget
        self.usage = BudgetUsage()
        self._events: dict[str, BudgetUsage] = {}

    def consume(self, event_id: str, usage: BudgetUsage) -> bool:
        event_id = str(event_id or "").strip()
        if not event_id:
            raise ValueError("Budget events require event_id")
        if not isinstance(usage, BudgetUsage):
            raise TypeError("Budget usage must be BudgetUsage")
        if event_id in self._events:
            return False
        proposed = self.usage.plus(usage)
        self._assert_within_limits(proposed)
        self._events[event_id] = usage
        self.usage = proposed
        return True

    def to_snapshot(self) -> dict[str, Any]:
        return {"usage": asdict(self.usage), "events": {key: asdict(value) for key, value in self._events.items()}}

    @classmethod
    def from_snapshot(cls, budget: EvolutionBudget, snapshot: dict[str, Any]) -> "EvolutionBudgetLedger":
        ledger = cls(budget)
        events = snapshot.get("events") if isinstance(snapshot, dict) else {}
        if not isinstance(events, dict):
            raise ValueError("Budget snapshot events must be an object")
        for event_id in sorted(events):
            ledger.consume(event_id, BudgetUsage(**events[event_id]))
        return ledger

    def _assert_within_limits(self, usage: BudgetUsage) -> None:
        limits = {
            "max_candidates": usage.candidates,
            "max_model_calls": usage.model_calls,
            "max_metric_calls": usage.metric_calls,
            "max_cost": usage.cost,
            "max_wall_seconds": usage.wall_seconds,
        }
        for limit_name, value in limits.items():
            limit = getattr(self.budget, limit_name)
            if limit and value > limit:
                raise BudgetLimitExceeded(f"Budget limit exceeded: {limit_name}")


__all__ = ["BudgetLimitExceeded", "BudgetUsage", "EvolutionBudget", "EvolutionBudgetLedger"]
