"""Authorized environment facts and time-backed location continuity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from .causal_contracts import CAUSAL_SCHEMA_VERSION

AUTHORIZED_SOURCE_KINDS = {
    "operator",
    "sensor",
    "tool",
    "schedule_outcome",
}


def _iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat()


def _parse(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bounded_int(value: object, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def append_environment_fact(
    rows: Sequence[Mapping[str, Any]],
    *,
    fact_id: str,
    fact_key: str,
    value: Any,
    source_kind: str,
    source_ref: str,
    confidence: int,
    observed_at: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    normalized_id = str(fact_id or "").strip()[:200]
    normalized_key = str(fact_key or "").strip()[:160]
    normalized_source = str(source_kind or "").strip().lower()[:40]
    normalized_ref = str(source_ref or "").strip()[:300]
    if not normalized_id or not normalized_key:
        raise ValueError("Environment factId and factKey are required.")
    if normalized_source not in AUTHORIZED_SOURCE_KINDS or not normalized_ref:
        raise ValueError("Environment facts require an authorized sourceKind and sourceRef.")
    updated = [deepcopy(dict(item)) for item in rows]
    for item in updated:
        if str(item.get("factId") or "") == normalized_id:
            return updated, deepcopy(item)
    projection = project_environment(updated)
    previous = next(
        (
            item
            for item in projection["currentFacts"]
            if str(item.get("factKey") or "") == normalized_key
        ),
        None,
    )
    supersedes = []
    superseded_by = ""
    if previous is not None:
        previous_observed_at = _parse(previous.get("observedAt"))
        normalized_observed_at = observed_at.astimezone(timezone.utc)
        if previous_observed_at is not None and normalized_observed_at < previous_observed_at:
            superseded_by = str(previous.get("factId") or "")
        elif previous.get("value") != value:
            supersedes = [str(previous.get("factId") or "")]
    fact = {
        "schemaVersion": CAUSAL_SCHEMA_VERSION,
        "factId": normalized_id,
        "factKey": normalized_key,
        "value": deepcopy(value),
        "sourceKind": normalized_source,
        "sourceRef": normalized_ref,
        "confidence": _bounded_int(confidence, 0, 100, 80),
        "observedAt": _iso(observed_at),
        "supersedes": supersedes,
    }
    if superseded_by:
        fact["supersededBy"] = superseded_by
    updated.append(fact)
    return updated[-512:], deepcopy(fact)


def project_environment(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        item = deepcopy(dict(raw))
        fact_id = str(item.get("factId") or "").strip()
        if not fact_id or fact_id in seen:
            continue
        seen.add(fact_id)
        unique.append(item)
    superseded_by: dict[str, str] = {}
    for item in unique:
        fact_id = str(item.get("factId") or "")
        explicit_successor = str(item.get("supersededBy") or "").strip()
        if fact_id and explicit_successor:
            superseded_by[fact_id] = explicit_successor
        for previous in list(item.get("supersedes") or []):
            previous_id = str(previous or "").strip()
            if previous_id:
                superseded_by[previous_id] = str(item.get("factId") or "")
    current_by_key: dict[str, dict[str, Any]] = {}
    history: list[dict[str, Any]] = []
    for item in sorted(unique, key=lambda row: str(row.get("observedAt") or "")):
        fact_id = str(item.get("factId") or "")
        item["status"] = "superseded" if fact_id in superseded_by else "current"
        if fact_id in superseded_by:
            item["supersededBy"] = superseded_by[fact_id]
        history.append(item)
        if item["status"] == "current":
            current_by_key[str(item.get("factKey") or "")] = deepcopy(item)
    return {
        "schemaVersion": CAUSAL_SCHEMA_VERSION,
        "currentFacts": list(current_by_key.values()),
        "history": history[-128:],
    }


def start_location_movement(
    state: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    movement_id: str,
    destination: str,
    source_kind: str,
    source_ref: str,
    travel_minutes: int,
    now: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    normalized_id = str(movement_id or "").strip()[:200]
    normalized_destination = str(destination or "").strip()[:160]
    normalized_source = str(source_kind or "").strip().lower()[:40]
    normalized_ref = str(source_ref or "").strip()[:300]
    if not normalized_id or not normalized_destination:
        raise ValueError("Location movementId and destination are required.")
    if normalized_source not in AUTHORIZED_SOURCE_KINDS or not normalized_ref:
        raise ValueError("Location movement requires an authorized sourceKind and sourceRef.")
    updated_rows = [deepcopy(dict(item)) for item in rows]
    existing = next(
        (item for item in updated_rows if str(item.get("movementId") or "") == normalized_id),
        None,
    )
    if existing is not None:
        return deepcopy(dict(state)), updated_rows, deepcopy(existing)
    if any(str(item.get("status") or "") == "moving" for item in updated_rows):
        raise ValueError("Another location movement is already active.")
    next_state = deepcopy(dict(state))
    origin = str(next_state.get("currentLocation") or "home").strip()[:160] or "home"
    duration = _bounded_int(travel_minutes, 1, 1_440, 15)
    movement = {
        "schemaVersion": CAUSAL_SCHEMA_VERSION,
        "movementId": normalized_id,
        "fromLocation": origin,
        "toLocation": normalized_destination,
        "status": "moving",
        "sourceKind": normalized_source,
        "sourceRef": normalized_ref,
        "startedAt": _iso(now),
        "earliestArrivalAt": _iso(now + timedelta(minutes=duration)),
    }
    updated_rows.append(movement)
    next_state["locationStatus"] = "moving"
    next_state["activeMovementId"] = normalized_id
    next_state["movingTo"] = normalized_destination
    return next_state, updated_rows[-256:], deepcopy(movement)


def complete_location_movement(
    state: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    movement_id: str,
    now: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    normalized_id = str(movement_id or "").strip()[:200]
    updated_rows = [deepcopy(dict(item)) for item in rows]
    movement = next(
        (item for item in updated_rows if str(item.get("movementId") or "") == normalized_id),
        None,
    )
    if movement is None:
        raise ValueError("Location movement was not found.")
    if str(movement.get("status") or "") == "completed":
        return deepcopy(dict(state)), updated_rows, deepcopy(movement)
    earliest = _parse(movement.get("earliestArrivalAt"))
    if earliest is None or now.astimezone(timezone.utc) < earliest:
        raise ValueError("Location movement cannot complete before earliestArrivalAt.")
    next_state = deepcopy(dict(state))
    movement["status"] = "completed"
    movement["arrivedAt"] = _iso(now)
    next_state["currentLocation"] = str(movement.get("toLocation") or "").strip()
    next_state["locationStatus"] = "stationary"
    next_state["activeMovementId"] = ""
    next_state["movingTo"] = ""
    next_state["locationSource"] = {
        "movementId": normalized_id,
        "sourceKind": str(movement.get("sourceKind") or ""),
        "sourceRef": str(movement.get("sourceRef") or ""),
        "arrivedAt": str(movement.get("arrivedAt") or ""),
    }
    return next_state, updated_rows, deepcopy(movement)


__all__ = [
    "AUTHORIZED_SOURCE_KINDS",
    "append_environment_fact",
    "complete_location_movement",
    "project_environment",
    "start_location_movement",
]
