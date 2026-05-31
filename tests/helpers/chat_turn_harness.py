from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


def wait_for_condition(
    label: str,
    *,
    timeout_s: float,
    predicate: Callable[[], bool],
    interval_s: float = 0.01,
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval_s)
    raise AssertionError(f"Timed out waiting for {label} after {timeout_s:.2f}s")


@dataclass
class FakeTurnRunner:
    submitted: list[dict[str, Any]] = field(default_factory=list)
    released: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    def submit(self, context: dict[str, Any]) -> None:
        self.submitted.append(dict(context))

    def release(self, context: dict[str, Any]) -> None:
        self.released.append(dict(context))

    def record_event(self, context: dict[str, Any], phase: str, outcome: str, fields: dict[str, Any] | None) -> None:
        self.events.append(
            {
                "turn_id": context.get("turn_id"),
                "phase": phase,
                "outcome": outcome,
                "fields": fields or {},
            }
        )
