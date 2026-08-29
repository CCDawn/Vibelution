"""Source-backed nightly reflection and memory-strength projection."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .causal_contracts import CAUSAL_SCHEMA_VERSION

REFLECTION_TARGET_KINDS = {
    "memory_reinforcement",
    "preference",
    "habit",
    "skill",
    "self_narrative",
    "episodic_insert",
    "episodic_supersede",
    "environment_fact",
    "external_fact",
    "location_fact",
}
REFLECTION_TERMINAL_STATUSES = {"approved", "rejected", "superseded"}


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


def _bounded_int(value: object, minimum: int, maximum: int, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def validate_reflection_proposal(
    proposal: Mapping[str, Any],
    *,
    valid_event_ids: set[str],
    valid_fact_ids: set[str],
    now: datetime,
) -> dict[str, Any]:
    """Validate one proposal without allowing reflection to invent facts."""

    result = deepcopy(dict(proposal))
    proposal_id = str(result.get("proposalId") or "").strip()[:200]
    source_kind = str(result.get("sourceKind") or "").strip().lower()[:40]
    target_kind = str(result.get("targetKind") or "").strip().lower()[:60]
    text = str(result.get("text") or "").strip()[:1200]
    event_ids = list(
        dict.fromkeys(
            str(item).strip()
            for item in list(result.get("sourceEventIds") or [])
            if str(item).strip()
        )
    )[:16]
    fact_ids = list(
        dict.fromkeys(
            str(item).strip()
            for item in list(result.get("sourceFactIds") or [])
            if str(item).strip()
        )
    )[:16]
    supersedes_episode_id = str(
        result.get("supersedesEpisodeId") or ""
    ).strip()[:200]
    supersedes_proposal_id = str(
        result.get("supersedesProposalId") or ""
    ).strip()[:200]
    result.update(
        {
            "schemaVersion": CAUSAL_SCHEMA_VERSION,
            "proposalId": proposal_id,
            "sourceKind": source_kind,
            "targetKind": target_kind,
            "text": text,
            "sourceEventIds": event_ids,
            "sourceFactIds": fact_ids,
            "supersedesEpisodeId": supersedes_episode_id,
            "supersedesProposalId": supersedes_proposal_id,
            "validatedAt": _iso(now),
        }
    )
    reason = ""
    if not proposal_id or not text:
        reason = "proposal_identity_or_text_missing"
    elif target_kind not in REFLECTION_TARGET_KINDS:
        reason = "target_kind_not_allowed"
    elif source_kind == "dream" and target_kind in {
        "environment_fact",
        "external_fact",
        "location_fact",
    }:
        reason = "dream_cannot_be_external_fact"
    elif source_kind in {"lived_event", "activity_outcome"} and (
        not event_ids or any(item not in valid_event_ids for item in event_ids)
    ):
        reason = "source_event_missing"
    elif source_kind in {"environment", "authorized_environment"} and (
        not fact_ids or any(item not in valid_fact_ids for item in fact_ids)
    ):
        reason = "source_fact_missing"
    elif target_kind == "memory_reinforcement" and (
        not event_ids or any(item not in valid_event_ids for item in event_ids)
    ):
        reason = "memory_source_missing"
    elif target_kind in {
        "preference",
        "habit",
        "skill",
        "self_narrative",
        "episodic_insert",
        "episodic_supersede",
    } and (
        not event_ids or any(item not in valid_event_ids for item in event_ids)
    ):
        reason = "source_event_missing"
    elif target_kind == "episodic_supersede" and not supersedes_episode_id:
        reason = "superseded_episode_missing"
    elif source_kind not in {
        "lived_event",
        "activity_outcome",
        "environment",
        "authorized_environment",
        "dream",
    }:
        reason = "source_kind_not_allowed"

    result["factEligible"] = bool(
        not reason
        and source_kind != "dream"
        and target_kind in {"environment_fact", "external_fact", "location_fact"}
    )
    result["status"] = "rejected" if reason else "pending"
    result["validationReason"] = reason or "source_boundary_passed"
    return result


def transition_reflection_proposal(
    proposal: Mapping[str, Any],
    *,
    decision: str,
    reviewer_kind: str,
    review_note: str,
    now: datetime,
    successor_proposal_id: str = "",
) -> dict[str, Any]:
    """Apply one auditable lifecycle transition without changing source facts."""

    result = deepcopy(dict(proposal))
    current_status = str(result.get("status") or "").strip().lower()
    if current_status in REFLECTION_TERMINAL_STATUSES:
        return result
    if current_status != "pending":
        raise ValueError("Reflection proposal is not pending review.")
    normalized = str(decision or "").strip().lower()
    if normalized not in {"approve", "reject", "supersede"}:
        raise ValueError("Reflection decision must be approve, reject, or supersede.")
    successor = str(successor_proposal_id or "").strip()[:200]
    if normalized == "supersede" and not successor:
        raise ValueError("Superseding a reflection proposal requires a successor proposal id.")
    result["status"] = {
        "approve": "approved",
        "reject": "rejected",
        "supersede": "superseded",
    }[normalized]
    result["reviewerKind"] = str(reviewer_kind or "operator").strip()[:40] or "operator"
    result["reviewNote"] = str(review_note or "").strip()[:600]
    result["reviewedAt"] = _iso(now)
    if successor:
        result["supersededByProposalId"] = successor
    return result


def build_nightly_reflection_proposals(
    events: Sequence[Mapping[str, Any]],
    *,
    promoted_source_ids: set[str],
    existing_proposal_ids: set[str],
    local_date: str,
    now: datetime,
) -> list[dict[str, Any]]:
    """Build deterministic proposals only from promoted lived events."""

    proposals: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event.get("eventId") or "").strip()
        outcome = event.get("outcome") if isinstance(event.get("outcome"), Mapping) else {}
        if (
            not event_id
            or event_id not in promoted_source_ids
            or str(event.get("kind") or "") != "activity_completed"
            or str(outcome.get("status") or "") != "succeeded"
        ):
            continue
        digest = hashlib.sha256(f"{local_date}:{event_id}".encode()).hexdigest()[:20]
        proposal_id = f"reflection-{digest}"
        if proposal_id in existing_proposal_ids:
            continue
        proposals.append(
            {
                "schemaVersion": CAUSAL_SCHEMA_VERSION,
                "proposalId": proposal_id,
                "sourceKind": "lived_event",
                "targetKind": "memory_reinforcement",
                "text": (
                    "这段真实经历仍值得保留："
                    + str(outcome.get("summary") or event.get("title") or "生活片段").strip()[:600]
                ),
                "sourceEventIds": [event_id],
                "sourceFactIds": [],
                "localDate": local_date,
                "createdAt": _iso(now),
            }
        )
    return proposals


def project_memory_strength(
    receipt: Mapping[str, Any],
    *,
    reinforcements: Sequence[Mapping[str, Any]],
    affect_episodes: Sequence[Mapping[str, Any]],
    open_loops: Sequence[Mapping[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    """Project memory strength without becoming a second episodic store."""

    source_ids = {
        str(item).strip()
        for item in list(receipt.get("sourceEventIds") or [])
        if str(item).strip()
    }
    base = _bounded_int(receipt.get("salienceScore"), 0, 100, 0)
    relevant_reinforcements = [
        item
        for item in reinforcements
        if source_ids.intersection(
            str(source).strip()
            for source in list(item.get("sourceEventIds") or [])
            if str(source).strip()
        )
    ]
    reinforcement_value = min(
        20,
        sum(
            _bounded_int(item.get("reinforcementAmount"), 0, 12, 0)
            for item in relevant_reinforcements
        ),
    )
    importance = min(100, base + reinforcement_value)
    occurred = _parse(receipt.get("occurredAt"))
    age_days = (
        max(0.0, (now.astimezone(timezone.utc) - occurred).total_seconds() / 86_400)
        if occurred is not None
        else 365.0
    )
    recency = max(0, min(100, round(100 - age_days * 4)))
    emotion = max(
        (
            _bounded_int(item.get("intensity"), 0, 100, 0)
            for item in affect_episodes
            if str(item.get("sourceEventId") or "") in source_ids
        ),
        default=0,
    )
    unresolved = 85 if any(
        str(item.get("status") or "") == "open"
        and source_ids.intersection(
            str(source).strip()
            for source in list(item.get("sourceEventIds") or [])
            if str(source).strip()
        )
        for item in open_loops
    ) else 0
    strength = min(
        100,
        round(base + reinforcement_value + recency * 0.05 + emotion * 0.08 + unresolved * 0.06),
    )
    reinforced_at = max(
        (
            str(item.get("reinforcedAt") or item.get("createdAt") or "")
            for item in relevant_reinforcements
            if str(item.get("reinforcedAt") or item.get("createdAt") or "")
        ),
        default="",
    )
    return {
        "baseSalienceScore": base,
        "memoryStrengthScore": max(base, strength),
        "scoreBreakdown": {
            "importance": importance,
            "recency": recency,
            "emotion": emotion,
            "unresolved": unresolved,
            "reinforcement": reinforcement_value,
        },
        "reinforcedAt": reinforced_at,
    }


__all__ = [
    "REFLECTION_TARGET_KINDS",
    "build_nightly_reflection_proposals",
    "project_memory_strength",
    "transition_reflection_proposal",
    "validate_reflection_proposal",
]
