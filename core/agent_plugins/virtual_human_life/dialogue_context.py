"""Companion-only receipt and prompt projection for one native Session turn.

This module stores only bounded routing metadata. It never stores user content,
owns a transcript, submits a turn, or changes native Session admission.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .interaction_expression import (
    build_companion_expression_decision,
    classify_companion_user_intent,
)
from .storage import VirtualHumanLifeStore

_INTERACTION_CONTEXT_PATH = "conversation/interaction_context.json"
_LOCAL_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def _iso(value: datetime) -> str:
    normalized = (
        value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    )
    return normalized.astimezone(timezone.utc).isoformat()


def _timestamp(value: object) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _is_future_plan(
    item: Mapping[str, Any],
    *,
    schedule_date: str,
    local_date: str,
    local_now: datetime,
) -> bool:
    if str(item.get("status") or "planned") != "planned":
        return False
    starts_at = _timestamp(item.get("startAt"))
    return (
        schedule_date != local_date
        or starts_at is None
        or starts_at >= local_now.astimezone(timezone.utc)
    )


def record_interaction_receipt(
    store: VirtualHumanLifeStore,
    agent_id: str,
    *,
    entry: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Persist bounded arrival intent without user content or a second transcript."""

    payload = store.read_json(agent_id, _INTERACTION_CONTEXT_PATH) or {
        "schemaVersion": 1,
        "sessions": {},
    }
    sessions = payload.get("sessions")
    if not isinstance(sessions, dict):
        sessions = {}
    session_id = str(entry.get("sessionId") or "").strip()
    previous = sessions.get(session_id)
    previous_ordinal = (
        int(previous.get("turnOrdinal") or 0) if isinstance(previous, Mapping) else 0
    )
    turn_ordinal = (
        previous_ordinal
        if isinstance(previous, Mapping)
        and str(previous.get("entryId") or "") == str(entry.get("entryId") or "")
        else previous_ordinal + 1
    )
    command = entry.get("command") if isinstance(entry.get("command"), Mapping) else {}
    context = {
        "entryId": str(entry.get("entryId") or "").strip(),
        "sessionId": session_id,
        "sourceKind": str(entry.get("sourceKind") or "user"),
        "arrivalSequence": int(entry.get("arrivalSequence") or 0),
        "turnOrdinal": turn_ordinal,
        "generation": int(entry.get("generation") or 0),
        "userIntent": classify_companion_user_intent(command.get("content")),
        "turnId": "",
        "updatedAt": _iso(now),
    }
    sessions[session_id] = context
    store.write_json(
        agent_id,
        _INTERACTION_CONTEXT_PATH,
        {"schemaVersion": 1, "sessions": sessions},
    )
    return deepcopy(context)


def bind_interaction_receipt_turn(
    store: VirtualHumanLifeStore,
    agent_id: str,
    *,
    session_id: str,
    entry_id: str,
    turn_id: str,
    now: datetime,
) -> None:
    payload = store.read_json(agent_id, _INTERACTION_CONTEXT_PATH) or {}
    sessions = payload.get("sessions")
    if not isinstance(sessions, dict):
        return
    context = sessions.get(session_id)
    if not isinstance(context, dict) or str(context.get("entryId") or "") != entry_id:
        return
    context["turnId"] = str(turn_id or "").strip()
    context["updatedAt"] = _iso(now)
    store.write_json(agent_id, _INTERACTION_CONTEXT_PATH, payload)


def interaction_context_for_turn(
    store: VirtualHumanLifeStore,
    agent_id: str,
    *,
    session_id: str,
    run_id: str,
) -> dict[str, Any]:
    payload = store.read_json(agent_id, _INTERACTION_CONTEXT_PATH) or {}
    sessions = payload.get("sessions")
    if not isinstance(sessions, Mapping):
        return {}
    context = sessions.get(str(session_id or "").strip())
    if not isinstance(context, Mapping):
        return {}
    recorded_turn_id = str(context.get("turnId") or "").strip()
    normalized_run_id = str(run_id or "").strip()
    if normalized_run_id and recorded_turn_id and normalized_run_id != recorded_turn_id:
        return {}
    return {
        "entryId": str(context.get("entryId") or "")[:200],
        "sourceKind": str(context.get("sourceKind") or "user")[:40],
        "arrivalSequence": int(context.get("arrivalSequence") or 0),
        "turnOrdinal": int(context.get("turnOrdinal") or 0),
        "generation": int(context.get("generation") or 0),
        "userIntent": str(context.get("userIntent") or "small_talk")[:40],
        "turnId": recorded_turn_id,
    }


def project_companion_dialogue_context(
    store: VirtualHumanLifeStore,
    agent_id: str,
    *,
    binding: Mapping[str, Any],
    state: Mapping[str, Any],
    causal: Mapping[str, Any],
    today_schedule: Mapping[str, Any],
    tomorrow_schedule: Mapping[str, Any],
    local_now: datetime,
    session_id: str,
    run_id: str,
    proactive: bool,
) -> dict[str, Any]:
    """Project truthful time, experience, plan, and expression data for a turn."""

    local_date = local_now.date().isoformat()
    interaction_context = interaction_context_for_turn(
        store,
        agent_id,
        session_id=session_id,
        run_id=run_id,
    )
    current_activity = next(
        (
            {
                "activityId": str(item.get("activityId") or ""),
                "title": str(item.get("title") or "")[:160],
                "status": str(item.get("status") or "active"),
                "startAt": str(item.get("startAt") or ""),
                "endAt": str(item.get("endAt") or ""),
            }
            for item in list(today_schedule.get("activities") or [])
            if isinstance(item, Mapping)
            and (
                str(item.get("activityId") or "")
                == str(state.get("currentActivityId") or "")
                or str(item.get("status") or "") == "active"
            )
        ),
        None,
    )
    completed_experiences = [
        {
            "eventId": str(item.get("eventId") or ""),
            "title": str(item.get("title") or "")[:160],
            "occurredAt": str(item.get("occurredAt") or ""),
            "outcomeSummary": str((item.get("outcome") or {}).get("summary") or "")[
                :240
            ],
            "factStatus": "completed",
        }
        for item in store.read_jsonl(agent_id, f"events/{local_date}.jsonl")
        if isinstance(item, Mapping)
        and str(item.get("kind") or "") == "activity_completed"
        and isinstance(item.get("outcome"), Mapping)
        and str((item.get("outcome") or {}).get("status") or "") == "succeeded"
    ][-8:]
    future_plans = [
        {
            "activityId": str(item.get("activityId") or ""),
            "title": str(item.get("title") or "")[:160],
            "localDate": schedule_date,
            "startAt": str(item.get("startAt") or ""),
            "endAt": str(item.get("endAt") or ""),
            "factStatus": "planned_not_occurred",
        }
        for schedule_date, schedule in (
            (local_date, today_schedule),
            (str(tomorrow_schedule.get("localDate") or ""), tomorrow_schedule),
        )
        for item in list(schedule.get("activities") or [])
        if isinstance(item, Mapping)
        and _is_future_plan(
            item,
            schedule_date=schedule_date,
            local_date=local_date,
            local_now=local_now,
        )
    ][:12]
    user_relationship = next(
        (
            item
            for item in list(causal.get("relationships") or [])
            if isinstance(item, Mapping) and str(item.get("targetId") or "") == "user"
        ),
        {},
    )
    affect_projection = (
        deepcopy(causal.get("affect"))
        if isinstance(causal.get("affect"), Mapping)
        else {}
    )
    active_episode_ids = {
        str(item or "")
        for item in list(affect_projection.get("activeEpisodeIds") or [])
        if str(item or "")
    }
    affect_projection["activeEpisodes"] = [
        {
            "episodeId": str(item.get("episodeId") or ""),
            "targetId": str(item.get("targetId") or "self")[:160],
        }
        for item in store.read_jsonl(agent_id, "affect/episodes.jsonl")
        if isinstance(item, Mapping)
        and str(item.get("episodeId") or "") in active_episode_ids
    ][:8]
    expression_decision = build_companion_expression_decision(
        relationship=user_relationship,
        affect=affect_projection,
        energy=state.get("energy"),
        user_intent=(
            "proactive"
            if proactive
            else str(interaction_context.get("userIntent") or "small_talk")
        ),
        turn_ordinal=interaction_context.get("turnOrdinal"),
    )
    return {
        "timeContext": {
            "localDate": local_date,
            "localWeekday": _LOCAL_WEEKDAYS[local_now.weekday()],
            "localTime": local_now.strftime("%H:%M"),
            "timezone": str(binding.get("timezone") or "Asia/Shanghai"),
        },
        "currentActivity": current_activity,
        "completedExperiences": completed_experiences,
        "futurePlans": future_plans,
        "interactionContext": interaction_context,
        "expressionDecision": expression_decision,
    }


__all__ = [
    "bind_interaction_receipt_turn",
    "interaction_context_for_turn",
    "project_companion_dialogue_context",
    "record_interaction_receipt",
]
