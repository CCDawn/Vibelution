# -*- coding: utf-8 -*-
"""Durable Session Journal authority for LLM resilience decisions.

LLM resilience decisions — explicit route fallback switches, same-profile
degraded retries, stuck-loop detection, and answer-channel leak handling —
are persisted as ``llm_resilience`` journal events so they survive process
restarts. This module is the single owner for that event: the scene-event
name mapping, the payload schema, the append path, and the read projection
used by the web session turn DTO (``routeFallback``).

Shape follows the run-tree / attempt-as-sibling paradigm (OpenTelemetry
GenAI attempt spans, LangSmith run trees, Restate's durable journal): one
turn carries multiple sibling ``llm_resilience`` events distinguished by
``attempt``, not one aggregated record per turn. The write is synchronous
and same-process at decision time — a callback-style deferred flush drops
events exactly when the process dies (the LiteLLM callback-pipeline
lesson), so the decision and its durable record commit together.

The events are ``visible_in_model=False``, are absent from every
model-visible / audit-only / deferred-fsync set (so they always fsync and
never trip the post-terminal guard), and the bounded latest-preview reader
ignores them outright. Unknown payload ``schema`` versions are tolerated
on read: the fallback projection only matches its own stage name and skips
everything else, so newer writers cannot crash older readers.

Non-journal-backed surfaces (CLI, meeting, team runners) stay
scene-event-only: they never flow through :func:`record_llm_resilience_from_scene_event`
with a journal-backed session, and the journal-existence gate keeps it that
way even if a future funnel starts forwarding scene events.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from .turn_journal import (
    EVENT_LLM_RESILIENCE,
    TurnJournalEvent,
    append_turn_event,
    turn_journal_path,
)


DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]

RESILIENCE_SCHEMA = "llm_resilience.v1"

STAGE_FALLBACK_SWITCH = "fallback_switch"
STAGE_DEGRADED_RETRY = "degraded_retry"
STAGE_STUCK_DETECTED = "stuck_detected"
STAGE_ANSWER_CHANNEL_LEAK = "answer_channel_leak"

# Scene event code -> journal stage. The turn LLM adapter never touches the
# journal directly; the agent runtime binding layer mirrors these scene
# events here (adapter -> hooks.record_scene_event -> this module).
SCENE_EVENT_STAGE_MAP = {
    "llm_route_fallback_switched": STAGE_FALLBACK_SWITCH,
    "llm_route_degraded_retry": STAGE_DEGRADED_RETRY,
    "conversation.turn.stuck_loop_detected": STAGE_STUCK_DETECTED,
    "answer_channel_leak_detected": STAGE_ANSWER_CHANNEL_LEAK,
}

_PROJECTION_SOURCE = "llm_resilience_journal"
_PROJECTION_KIND = "llm_resilience_marker"
_SOURCE_KIND = "llm_resilience"

_BOUNDED_LIST_MAX_ITEMS = 8
_BOUNDED_TEXT_MAX_CHARS = 500


def resilience_stage_for_scene_event(event_code: Any) -> str:
    """Map a scene event code onto its journal stage ("" when unmapped)."""

    return SCENE_EVENT_STAGE_MAP.get(str(event_code or "").strip(), "")


def record_llm_resilience_event(
    project_root: Path | str | None,
    session_id: Any,
    turn_id: Any,
    *,
    stage: str,
    attempt: int = 0,
    fields: Mapping[str, Any] | None = None,
) -> TurnJournalEvent | None:
    """Append one sibling ``llm_resilience`` event for the turn.

    Returns the appended event, or ``None`` when the inputs cannot form a
    bounded, attributable record (no session/turn, unknown stage, or an
    invalid attempt). Never raises on JSON-unfriendly extras: only known,
    coerced fields enter the payload.
    """

    normalized_stage = str(stage or "").strip()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_stage or not normalized_session_id or not normalized_turn_id:
        return None
    source = fields if isinstance(fields, Mapping) else {}
    payload = _resilience_payload(
        normalized_stage,
        attempt=_coerce_nonnegative_int(attempt),
        fields=source,
    )
    return append_turn_event(
        Path(project_root) if project_root is not None else DEFAULT_PROJECT_ROOT,
        normalized_session_id,
        normalized_turn_id,
        EVENT_LLM_RESILIENCE,
        status=normalized_stage,
        payload=payload,
        source=_PROJECTION_SOURCE,
        visible_in_model=False,
        projection_kind=_PROJECTION_KIND,
        source_kind=_SOURCE_KIND,
    )


def record_llm_resilience_from_scene_event(
    event_code: Any,
    *,
    fields: Mapping[str, Any] | None = None,
    project_root: Path | str | None = None,
) -> TurnJournalEvent | None:
    """Mirror one resilience scene event into the Session Journal.

    Binding-layer convenience used by the agent runtime scene-event funnel.
    Gates on a non-empty ``sessionId``/``turnId`` in the event fields and on
    the session already owning a turn journal (the journal exists from
    ``turn_started`` onwards, before any LLM call can fail), so CLI and
    other non-journal surfaces remain scene-event-only. The caller owns
    failure handling; nothing here raises beyond the append itself.
    """

    stage = resilience_stage_for_scene_event(event_code)
    if not stage:
        return None
    source = fields if isinstance(fields, Mapping) else {}
    session_id = _text(source.get("sessionId") or source.get("session_id"))
    turn_id = _text(source.get("turnId") or source.get("turn_id"))
    if not session_id or not turn_id:
        return None
    root = Path(project_root) if project_root is not None else DEFAULT_PROJECT_ROOT
    if not turn_journal_path(root, session_id).exists():
        return None
    return record_llm_resilience_event(
        root,
        session_id,
        turn_id,
        stage=stage,
        attempt=_coerce_nonnegative_int(source.get("attempt")),
        fields=source,
    )


def latest_route_fallback_from_events(
    events: Iterable[Any],
    *,
    turn_id: str = "",
) -> dict[str, str] | None:
    """Project the strict ``{from, to}`` DTO from journaled fallback switches.

    Exact turn matches win. With no turn id, the session's latest recorded
    switch is returned so a completed turn stays visible after the active
    turn id is released. A turn that never switched must not be mislabelled
    with an older turn's entry, so a turn-scoped query with no matching
    event returns ``None``. Events with an unrecognized payload ``schema``
    (future writers) are skipped, never crash the reader.
    """

    normalized_turn_id = str(turn_id or "").strip()
    latest: tuple[tuple[int, str, str], dict[str, str]] | None = None
    for event in events:
        if str(getattr(event, "event_type", "") or "").strip() != EVENT_LLM_RESILIENCE:
            continue
        if normalized_turn_id and str(getattr(event, "turn_id", "") or "").strip() != normalized_turn_id:
            continue
        payload = getattr(event, "payload", None)
        if not isinstance(payload, Mapping):
            continue
        if str(payload.get("stage") or "").strip() != STAGE_FALLBACK_SWITCH:
            continue
        schema = str(payload.get("schema") or "").strip()
        if schema and schema != RESILIENCE_SCHEMA:
            continue
        dto = {
            "from": _text(payload.get("fromProfileId")),
            "to": _text(payload.get("toProfileId")),
        }
        # Same-profile "switches" are not fallbacks (legacy registry
        # normalization rejected them at write time); never project them.
        if not dto["from"] or not dto["to"] or dto["from"] == dto["to"]:
            continue
        key = (
            max(0, _coerce_nonnegative_int(getattr(event, "sequence", 0))),
            _text(getattr(event, "timestamp", "")),
            _text(getattr(event, "event_id", "")),
        )
        if latest is None or key > latest[0]:
            latest = (key, dto)
    return latest[1] if latest is not None else None


def resilience_events_for_turn(
    events: Iterable[Any],
    *,
    turn_id: str = "",
) -> list[TurnJournalEvent]:
    """Return this turn's (or the session's) sibling resilience events."""

    normalized_turn_id = str(turn_id or "").strip()
    matched = [
        event
        for event in events
        if str(getattr(event, "event_type", "") or "").strip() == EVENT_LLM_RESILIENCE
        and (not normalized_turn_id or str(getattr(event, "turn_id", "") or "").strip() == normalized_turn_id)
    ]
    return sorted(
        matched,
        key=lambda item: (
            max(0, _coerce_nonnegative_int(getattr(item, "sequence", 0))),
            _text(getattr(item, "timestamp", "")),
            _text(getattr(item, "event_id", "")),
        ),
    )


def _resilience_payload(stage: str, *, attempt: int, fields: Mapping[str, Any]) -> dict[str, Any]:
    """Build the bounded, schema-versioned payload for one stage."""

    payload: dict[str, Any] = {
        "schema": RESILIENCE_SCHEMA,
        "stage": stage,
        "attempt": attempt,
        "fromProfileId": _fallback_field(fields, "from", "fromProfileId", "from_profile_id"),
        "toProfileId": _fallback_field(fields, "to", "toProfileId", "to_profile_id"),
        "errorCategory": _fallback_field(fields, "errorCategory", "reason", "fromCategory"),
        "action": _text(fields.get("action")),
        "routeId": _fallback_field(fields, "routeId", "fromRouteId"),
    }
    if stage == STAGE_ANSWER_CHANNEL_LEAK:
        payload["leakRecovered"] = _coerce_bool(fields.get("leakRecovered"))
        payload["leakRetried"] = _coerce_bool(fields.get("leakRetried"))
        payload["leakMarkers"] = _bounded_text_list(fields.get("leakMarkers"))
        payload["leakTriggeredBy"] = _bounded_text_list(fields.get("leakTriggeredBy"))
        outcome_kind = _text(fields.get("outcomeKind"))
        if outcome_kind:
            payload["outcomeKind"] = outcome_kind
    if stage == STAGE_STUCK_DETECTED:
        payload["stuckPattern"] = _text(fields.get("stuckPattern"))
        payload["stuckTool"] = _text(fields.get("stuckTool"))
        payload["stuckRepeatCount"] = _coerce_nonnegative_int(fields.get("stuckRepeatCount"))
        payload["stuckEvidence"] = _bounded_text(fields.get("stuckEvidence"))
        reason = _text(fields.get("reason"))
        if reason:
            payload["reason"] = reason
    return payload


def _fallback_field(fields: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = _text(fields.get(name))
        if value:
            return value
    return ""


def _bounded_text_list(value: Any, *, max_items: int = _BOUNDED_LIST_MAX_ITEMS) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    items: list[str] = []
    for entry in value:
        text = _text(entry)
        if text:
            items.append(text)
        if len(items) >= max_items:
            break
    return items


def _bounded_text(value: Any, *, max_chars: int = _BOUNDED_TEXT_MAX_CHARS) -> str:
    return _text(value)[:max_chars]


def _coerce_nonnegative_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _text(value: Any) -> str:
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    return str(value or "").strip()


__all__ = [
    "DEFAULT_PROJECT_ROOT",
    "EVENT_LLM_RESILIENCE",
    "RESILIENCE_SCHEMA",
    "SCENE_EVENT_STAGE_MAP",
    "STAGE_ANSWER_CHANNEL_LEAK",
    "STAGE_DEGRADED_RETRY",
    "STAGE_FALLBACK_SWITCH",
    "STAGE_STUCK_DETECTED",
    "latest_route_fallback_from_events",
    "record_llm_resilience_event",
    "record_llm_resilience_from_scene_event",
    "resilience_events_for_turn",
    "resilience_stage_for_scene_event",
]
