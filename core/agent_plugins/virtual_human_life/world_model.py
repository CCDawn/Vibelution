"""Small Agent-scoped catalog for familiar places, routes, and important items."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .causal_contracts import CAUSAL_SCHEMA_VERSION


def _iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat()


def _catalog(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload) if isinstance(payload, dict) else {}
    result["schemaVersion"] = CAUSAL_SCHEMA_VERSION
    for key in ("places", "routes", "importantItems"):
        result[key] = [item for item in list(result.get(key) or []) if isinstance(item, dict)]
    return result


def record_place_visit(
    catalog: dict[str, Any],
    *,
    place_id: str,
    label: str,
    source_event_id: str,
    occurred_at: datetime,
    route_from: str = "",
    route_minutes: int = 0,
    living_space: bool = False,
) -> dict[str, Any]:
    result = _catalog(catalog)
    normalized_id = str(place_id or "").strip()[:160]
    source_id = str(source_event_id or "").strip()[:200]
    if not normalized_id or not str(label or "").strip() or not source_id:
        raise ValueError("Place visit requires place id, label, and source event id.")
    place = next(
        (item for item in result["places"] if str(item.get("placeId") or "") == normalized_id),
        None,
    )
    if place is None:
        place = {
            "placeId": normalized_id,
            "label": str(label).strip()[:160],
            "livingSpace": bool(living_space),
            "visitCount": 0,
            "firstVisitedAt": _iso(occurred_at),
            "lastVisitedAt": "",
            "sourceEventIds": [],
        }
        result["places"].append(place)
    if source_id not in place["sourceEventIds"]:
        place["sourceEventIds"].append(source_id)
        place["visitCount"] = int(place.get("visitCount") or 0) + 1
    place["lastVisitedAt"] = max(str(place.get("lastVisitedAt") or ""), _iso(occurred_at))
    place["livingSpace"] = bool(place.get("livingSpace")) or bool(living_space)
    origin = str(route_from or "").strip()[:160]
    if origin:
        route = next(
            (
                item
                for item in result["routes"]
                if str(item.get("fromPlaceId") or "") == origin
                and str(item.get("toPlaceId") or "") == normalized_id
            ),
            None,
        )
        if route is None:
            route = {
                "routeId": f"{origin}->{normalized_id}",
                "fromPlaceId": origin,
                "toPlaceId": normalized_id,
                "typicalMinutes": max(1, min(1_440, int(route_minutes or 1))),
                "sourceEventIds": [],
            }
            result["routes"].append(route)
        if source_id not in route["sourceEventIds"]:
            route["sourceEventIds"].append(source_id)
    result["updatedAt"] = _iso(occurred_at)
    return result


def record_important_item(
    catalog: dict[str, Any],
    *,
    item_id: str,
    label: str,
    place_id: str,
    source_kind: str,
    source_ref: str,
    significance: str,
    recorded_at: datetime,
) -> dict[str, Any]:
    result = _catalog(catalog)
    normalized_id = str(item_id or "").strip()[:160]
    kind = str(source_kind or "").strip()[:40]
    ref = str(source_ref or "").strip()[:240]
    if not normalized_id or not str(label or "").strip() or not ref:
        raise ValueError("Important item requires id, label, and source reference.")
    if kind not in {"activity_outcome", "operator", "artifact_receipt"}:
        raise ValueError("Important item source kind is not allowed.")
    item = {
        "itemId": normalized_id,
        "label": str(label).strip()[:160],
        "placeId": str(place_id or "").strip()[:160],
        "significance": str(significance or "").strip()[:300],
        "sourceKind": kind,
        "sourceRef": ref,
        "recordedAt": _iso(recorded_at),
    }
    existing_index = next(
        (
            index
            for index, existing in enumerate(result["importantItems"])
            if str(existing.get("itemId") or "") == normalized_id
        ),
        -1,
    )
    if existing_index >= 0:
        result["importantItems"][existing_index] = item
    else:
        result["importantItems"].append(item)
    result["updatedAt"] = _iso(recorded_at)
    return result


__all__ = ["record_important_item", "record_place_visit"]
