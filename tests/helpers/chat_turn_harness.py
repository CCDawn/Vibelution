from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Any, Callable


def wait_for_matching_event(
    events: list[dict[str, Any]],
    *,
    timeout_s: float,
    predicate: Callable[[dict[str, Any]], bool],
    condition: threading.Condition | None = None,
    interval_s: float = 0.01,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout_s

    if condition is not None:
        with condition:
            while time.monotonic() < deadline:
                for event in events:
                    if predicate(event):
                        return event
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                condition.wait(timeout=remaining)
            return None

    while time.monotonic() < deadline:
        for event in events:
            if predicate(event):
                return event
        time.sleep(interval_s)
    return None


def wait_for_chat_room_round_completed(
    client: Any,
    room_id: str,
    *,
    timeout_s: float,
    interval_s: float = 0.02,
    desired_status: str = "completed",
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    detail: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/chat-rooms/{room_id}")
        if response.status_code != 200:
            raise AssertionError(f"chat room query failed with {response.status_code}: {response.text}")
        detail = response.json()
        rounds = detail.get("rounds")
        if not rounds:
            time.sleep(interval_s)
            continue
        latest_round = rounds[-1]
        if latest_round.get("status") == desired_status:
            return detail
        time.sleep(interval_s)
    raise AssertionError(f"chat room round did not reach '{desired_status}': {detail}")


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
