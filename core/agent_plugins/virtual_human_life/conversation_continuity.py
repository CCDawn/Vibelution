"""Proactive candidate policy and unfinished-topic lifecycle."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from .causal_contracts import CAUSAL_SCHEMA_VERSION


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


def _topic_key(event: Mapping[str, Any]) -> str:
    raw = f"{event.get('activityKind') or ''}:{event.get('title') or ''}".strip().lower()
    readable = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "-", raw).strip("-")[:48]
    return readable or hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def build_proactive_candidate(
    event: Mapping[str, Any],
    *,
    drive_projection: Mapping[str, Any],
    affect_projection: Mapping[str, Any],
    relationship: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    event_id = str(event.get("eventId") or "").strip()
    topic_key = _topic_key(event)
    source_value = 40 if str(event.get("kind") or "") == "activity_completed" else 0
    drive_value = 15 if event_id in set(drive_projection.get("processedEventIds") or []) else 5
    mood = affect_projection.get("mood") if isinstance(affect_projection.get("mood"), Mapping) else {}
    baseline = (
        affect_projection.get("baselineMood")
        if isinstance(affect_projection.get("baselineMood"), Mapping)
        else {}
    )
    baseline_valence = (
        int(baseline["valence"]) if baseline.get("valence") is not None else 12
    )
    affect_value = min(
        15,
        abs(int(mood.get("valence") or 0) - baseline_valence) // 2,
    )
    relationship_value = 15 if str(relationship.get("relationshipStage") or "") in {"friend", "close"} else 6
    score = min(100, source_value + drive_value + affect_value + relationship_value)
    digest = hashlib.sha256(f"{event_id}:{topic_key}".encode()).hexdigest()[:20]
    return {
        "schemaVersion": CAUSAL_SCHEMA_VERSION,
        "candidateId": f"candidate-{digest}",
        "sourceEventId": event_id,
        "topicKey": topic_key,
        "reason": f"想自然地分享：{str(event.get('title') or '刚才的生活片段')[:160]}",
        "score": score,
        "scoreBreakdown": {
            "sourceValue": source_value,
            "driveValue": drive_value,
            "affectValue": affect_value,
            "relationshipValue": relationship_value,
        },
        "status": "pending",
        "createdAt": _iso(now),
        "validUntil": _iso(now + timedelta(minutes=45)),
    }


def evaluate_proactive_candidate(
    candidate: Mapping[str, Any],
    *,
    now: datetime,
    quiet_hours: bool,
    sleep_state: str,
    busy: bool,
    recent_topic_keys: set[str],
    unanswered_count: int,
) -> dict[str, Any]:
    result = deepcopy(dict(candidate))
    current = now.astimezone(timezone.utc)
    valid_until = _parse(result.get("validUntil"))
    reason = ""
    if valid_until is None or current > valid_until:
        reason = "expired"
        result["status"] = "expired"
        result["decision"] = "expire"
    elif quiet_hours:
        reason = "quiet_hours"
    elif str(sleep_state or "").lower() in {"sleeping", "resting"}:
        reason = "sleeping"
    elif busy:
        reason = "busy"
    elif str(result.get("topicKey") or "") in recent_topic_keys:
        reason = "duplicate_topic"
    elif int(unanswered_count or 0) >= 2:
        reason = "unanswered_backoff"
    elif int(result.get("score") or 0) < 45:
        reason = "low_value"
    if reason and reason != "expired":
        result["status"] = "suppressed"
        result["decision"] = "suppress"
    if reason:
        result["suppressionReason"] = reason
        result["evaluatedAt"] = _iso(current)
        return result
    result["status"] = "eligible"
    result["decision"] = "eligible"
    result["suppressionReason"] = ""
    result["evaluatedAt"] = _iso(current)
    return result


def upsert_open_loop(
    rows: list[Mapping[str, Any]],
    *,
    loop_id: str,
    topic_key: str,
    kind: str,
    summary: str,
    source_turn_id: str,
    source_event_id: str = "",
    now: datetime,
    expires_at: datetime,
) -> list[dict[str, Any]]:
    updated = [deepcopy(dict(item)) for item in rows]
    normalized_topic = str(topic_key or "").strip()[:120]
    for item in updated:
        if str(item.get("topicKey") or "") != normalized_topic or str(item.get("status") or "") != "open":
            continue
        source_ids = [str(value) for value in list(item.get("sourceTurnIds") or []) if str(value)]
        if source_turn_id and source_turn_id not in source_ids:
            source_ids.append(source_turn_id)
        item["sourceTurnIds"] = source_ids[-16:]
        event_ids = [str(value) for value in list(item.get("sourceEventIds") or []) if str(value)]
        if source_event_id and source_event_id not in event_ids:
            event_ids.append(source_event_id)
        item["sourceEventIds"] = event_ids[-16:]
        item["repeatCount"] = max(1, int(item.get("repeatCount") or 1)) + 1
        item["summary"] = str(summary or item.get("summary") or "")[:300]
        item["expiresAt"] = _iso(max(expires_at, _parse(item.get("expiresAt")) or expires_at))
        item["updatedAt"] = _iso(now)
        return updated
    updated.append(
        {
            "schemaVersion": CAUSAL_SCHEMA_VERSION,
            "loopId": str(loop_id or "").strip()[:200],
            "topicKey": normalized_topic,
            "kind": str(kind or "topic").strip()[:40],
            "summary": str(summary or "").strip()[:300],
            "status": "open",
            "repeatCount": 1,
            "sourceTurnIds": [str(source_turn_id).strip()] if str(source_turn_id).strip() else [],
            "sourceEventIds": [str(source_event_id).strip()] if str(source_event_id).strip() else [],
            "createdAt": _iso(now),
            "updatedAt": _iso(now),
            "expiresAt": _iso(expires_at),
        }
    )
    return updated[-256:]


def resolve_open_loop(
    rows: list[Mapping[str, Any]],
    *,
    topic_key: str,
    resolution: str,
    source_turn_id: str,
    now: datetime,
) -> list[dict[str, Any]]:
    updated = [deepcopy(dict(item)) for item in rows]
    for item in updated:
        if str(item.get("topicKey") or "") != str(topic_key or "").strip() or str(item.get("status") or "") != "open":
            continue
        item["status"] = "resolved"
        item["resolution"] = str(resolution or "").strip()[:300]
        item["resolvedByTurnId"] = str(source_turn_id or "").strip()[:200]
        item["resolvedAt"] = _iso(now)
        item["updatedAt"] = _iso(now)
    return updated


def project_open_loops(rows: list[Mapping[str, Any]], *, now: datetime) -> dict[str, Any]:
    current = now.astimezone(timezone.utc)
    open_rows: list[dict[str, Any]] = []
    resolved_rows: list[dict[str, Any]] = []
    expired_rows: list[dict[str, Any]] = []
    for raw in rows:
        item = deepcopy(dict(raw))
        status = str(item.get("status") or "open")
        expires_at = _parse(item.get("expiresAt"))
        if status == "open" and expires_at is not None and current > expires_at:
            item["status"] = "expired"
            item["expiredAt"] = _iso(current)
            status = "expired"
        if status == "open":
            open_rows.append(item)
        elif status == "resolved":
            resolved_rows.append(item)
        elif status == "expired":
            expired_rows.append(item)
    return {
        "open": open_rows,
        "resolved": resolved_rows,
        "expired": expired_rows,
        "updatedAt": _iso(current),
    }


__all__ = [
    "build_proactive_candidate",
    "evaluate_proactive_candidate",
    "project_open_loops",
    "resolve_open_loop",
    "upsert_open_loop",
]
