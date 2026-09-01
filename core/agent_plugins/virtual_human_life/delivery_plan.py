"""Versioned Companion delivery plans backed by native assistant-only Turns.

Plans keep only identity, ordering, decision and receipt metadata. They never
store assistant text or become a transcript or Session authority.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

DELIVERY_PLAN_VERSION = "companion_delivery.v1"
DIALOGUE_BURST_VERSION = "companion_dialogue_burst.v2"
DIALOGUE_BURST_STATUSES = {
    "queued",
    "awaiting_native_admission",
    "running",
    "awaiting_terminal_receipt",
    "decision_ready",
    "await_user",
    "completed",
    "cancelled",
    "failed",
    "expired",
}
DELIVERY_PLAN_STATUSES = {
    "planned",
    "queued",
    "delivering",
    "delivered",
    "cancelled",
    "failed",
}


def _iso(value: datetime) -> str:
    normalized = (
        value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    )
    return normalized.astimezone(timezone.utc).isoformat()


def _stable_suffix(*parts: object) -> str:
    source = "\x1f".join(str(part or "").strip() for part in parts)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]


def build_companion_delivery_plan(
    *,
    session_id: str,
    generation: int,
    source_entry_id: str,
    source_turn_id: str,
    expression_decision: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Return a stable one-or-two-bubble plan without generating message text."""

    normalized_session_id = str(session_id or "").strip()
    normalized_entry_id = str(source_entry_id or "").strip()
    normalized_turn_id = str(source_turn_id or "").strip()
    normalized_generation = int(generation)
    if not normalized_session_id or not normalized_entry_id or not normalized_turn_id:
        raise ValueError("Companion delivery plan identity is incomplete.")
    if normalized_generation < 1:
        raise ValueError("Companion delivery generation must be positive.")
    suffix = _stable_suffix(
        normalized_session_id,
        normalized_generation,
        normalized_entry_id,
        normalized_turn_id,
    )
    followup_eligible = bool(expression_decision.get("followup"))
    plan_id = f"delivery-plan:{suffix}"
    followup = (
        {
            "bubbleIndex": 2,
            "entryId": f"followup:{suffix}",
            "attemptId": f"followup-attempt:{suffix}",
            "triggerId": f"followup-trigger:{suffix}",
            "deliveryToken": f"followup-{suffix}",
            "idempotencyKey": f"followup:{suffix}",
        }
        if followup_eligible
        else None
    )
    return {
        "contractVersion": DELIVERY_PLAN_VERSION,
        "planId": plan_id,
        "sessionId": normalized_session_id,
        "generation": normalized_generation,
        "sourceEntryId": normalized_entry_id,
        "sourceTurnId": normalized_turn_id,
        "bubbleBudget": 2 if followup is not None else 1,
        "status": "planned",
        "followup": followup,
        "createdAt": _iso(now),
        "updatedAt": _iso(now),
    }


def build_conversation_burst_plan_v2(
    *,
    agent_id: str,
    session_id: str,
    root_entry_id: str,
    root_source_kind: str,
    generation: int,
    binding_revision: int,
    root_turn_id: str,
    now: datetime,
) -> dict[str, Any]:
    """Build a receipt-driven Companion burst without future message text."""

    normalized_agent_id = str(agent_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    normalized_entry_id = str(root_entry_id or "").strip()
    normalized_source_kind = str(root_source_kind or "").strip().lower()
    normalized_turn_id = str(root_turn_id or "").strip()
    normalized_generation = int(generation)
    normalized_revision = int(binding_revision)
    if (
        not normalized_agent_id
        or not normalized_session_id
        or not normalized_entry_id
        or not normalized_turn_id
        or normalized_source_kind not in {"user", "proactive"}
    ):
        raise ValueError("Companion dialogue burst identity is incomplete.")
    if (
        normalized_generation < 0
        or (normalized_source_kind == "user" and normalized_generation < 1)
        or normalized_revision < 1
    ):
        raise ValueError("Companion dialogue burst fence is invalid.")
    suffix = _stable_suffix(
        normalized_agent_id,
        normalized_session_id,
        normalized_entry_id,
        normalized_generation,
    )
    timestamp = _iso(now)
    return {
        "contractVersion": DIALOGUE_BURST_VERSION,
        "planId": f"dialogue-burst:{suffix}",
        "agentId": normalized_agent_id,
        "sessionId": normalized_session_id,
        "rootEntryId": normalized_entry_id,
        "rootSourceKind": normalized_source_kind,
        "generation": normalized_generation,
        "bindingRevision": normalized_revision,
        "status": "awaiting_terminal_receipt",
        "deliveredCount": 0,
        "questionCount": 0,
        "currentBubbleOrdinal": 1,
        "currentEntryId": normalized_entry_id,
        "currentAttemptId": "",
        "currentTriggerId": "",
        "currentDeliveryToken": "",
        "currentIdempotencyKey": "",
        "currentTurnId": normalized_turn_id,
        "decisionDraft": None,
        "decisionDraftStatus": "missing",
        "decisionDraftStopReason": "",
        "decisionToolCallIds": [],
        "nextAct": "",
        "latestAssistantReceiptEventId": "",
        "assistantReceiptEventIds": [],
        "latestDeliveryReceiptId": "",
        "disclosedTopicKeys": [],
        "stopReason": "",
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "expiresAt": _iso(now + timedelta(minutes=5)),
        "version": 1,
    }


def upsert_delivery_plan(
    rows: list[dict[str, Any]],
    plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Idempotently add a plan while rejecting identity drift."""

    normalized = deepcopy(plan)
    plan_id = str(normalized.get("planId") or "").strip()
    if not plan_id:
        raise ValueError("Companion delivery plan id is required.")
    updated = [deepcopy(item) for item in rows]
    for existing in updated:
        if str(existing.get("planId") or "") != plan_id:
            continue
        identity_keys = (
            (
                "contractVersion",
                "agentId",
                "sessionId",
                "rootEntryId",
                "rootSourceKind",
                "generation",
                "bindingRevision",
            )
            if str(normalized.get("contractVersion") or "")
            == DIALOGUE_BURST_VERSION
            else (
                "contractVersion",
                "sessionId",
                "generation",
                "sourceEntryId",
                "sourceTurnId",
                "bubbleBudget",
                "followup",
            )
        )
        if any(existing.get(key) != normalized.get(key) for key in identity_keys):
            raise ValueError("Companion delivery plan id conflicts with another plan.")
        return updated, deepcopy(existing)
    updated.append(normalized)
    return updated, deepcopy(normalized)


def transition_delivery_plan(
    rows: list[dict[str, Any]],
    *,
    plan_id: str,
    status: str,
    now: datetime,
    receipt: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    normalized_plan_id = str(plan_id or "").strip()
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in DELIVERY_PLAN_STATUSES:
        raise ValueError("Unsupported Companion delivery plan status.")
    updated = [deepcopy(item) for item in rows]
    plan = next(
        (
            item
            for item in updated
            if str(item.get("planId") or "") == normalized_plan_id
        ),
        None,
    )
    if plan is None:
        raise ValueError("Companion delivery plan does not exist.")
    terminal = str(plan.get("status") or "") in {"delivered", "cancelled", "failed"}
    if (
        terminal
        and str(plan.get("status") or "") != normalized_status
        and normalized_status != "delivered"
    ):
        return updated, deepcopy(plan)
    plan["status"] = normalized_status
    plan["updatedAt"] = _iso(now)
    if isinstance(receipt, dict):
        plan["receipt"] = deepcopy(receipt)
    return updated, deepcopy(plan)


__all__ = [
    "DELIVERY_PLAN_STATUSES",
    "DELIVERY_PLAN_VERSION",
    "DIALOGUE_BURST_STATUSES",
    "DIALOGUE_BURST_VERSION",
    "build_companion_delivery_plan",
    "build_conversation_burst_plan_v2",
    "transition_delivery_plan",
    "upsert_delivery_plan",
]
