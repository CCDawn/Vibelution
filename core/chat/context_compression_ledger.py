# -*- coding: utf-8 -*-
"""Ledger-backed context compression checkpoints.

Compression checkpoints are model-context facts. The raw conversation ledger
keeps every event, while model replay can replace an older covered event range
with the checkpoint summary.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from .turn_journal import (
    EVENT_COMPACTION_CHECKPOINT,
    TurnJournalEvent,
    append_turn_event,
    load_turn_events,
)


def build_context_compression_checkpoint_payload(
    *,
    summary: str,
    level: str,
    reason: str,
    before_tokens: int,
    after_tokens: int,
    iteration: int = 0,
    trigger_source: str = "",
    effectiveness_threshold: float = 0.0,
    effectiveness_ratio: float = 0.0,
    effective: bool = True,
    source_message_count: int = 0,
    tool_result_replacement_state: dict[str, Any] | None = None,
    covered_events: Iterable[TurnJournalEvent] | None = None,
) -> dict[str, Any]:
    """Return the durable payload for a compression checkpoint event."""

    summary_text = str(summary or "").strip()
    covered = [event for event in list(covered_events or []) if isinstance(event, TurnJournalEvent)]
    covered_sequences = [int(event.sequence or 0) for event in covered if int(event.sequence or 0) > 0]
    before = max(0, int(before_tokens or 0))
    after = max(0, int(after_tokens or 0))
    replacement_state = (
        dict(tool_result_replacement_state)
        if isinstance(tool_result_replacement_state, dict)
        else {"replacements": []}
    )
    return {
        "summary": summary_text,
        "summaryHash": _short_hash(summary_text),
        "summaryWritten": bool(summary_text),
        "level": str(level or "").strip(),
        "reason": str(reason or "").strip(),
        "triggerSource": str(trigger_source or "").strip(),
        "beforeTokens": before,
        "afterTokens": after,
        "savedTokens": max(0, before - after),
        "iteration": max(0, int(iteration or 0)),
        "effectivenessThreshold": max(0.0, float(effectiveness_threshold or 0.0)),
        "effectivenessRatio": max(0.0, float(effectiveness_ratio or 0.0)),
        "effective": bool(effective),
        "sourceMessageCount": max(0, int(source_message_count or 0)),
        "coveredEventSeqStart": min(covered_sequences) if covered_sequences else 0,
        "coveredEventSeqEnd": max(covered_sequences) if covered_sequences else 0,
        "coveredEventIds": [event.event_id for event in covered if str(event.event_id or "").strip()],
        "coveredEventCount": len(covered),
        "toolResultReplacement": replacement_state,
        "schema": "context_compression_checkpoint.v1",
    }


def append_context_compression_checkpoint(
    project_root: Path,
    session_id: str,
    *,
    turn_id: str = "",
    current_turn_id: str = "",
    summary: str,
    level: str,
    reason: str,
    before_tokens: int,
    after_tokens: int,
    iteration: int = 0,
    trigger_source: str = "",
    effectiveness_threshold: float = 0.0,
    effectiveness_ratio: float = 0.0,
    effective: bool = True,
    source_message_count: int = 0,
    tool_result_replacement_state: dict[str, Any] | None = None,
    source: str = "agent_context_compression",
) -> TurnJournalEvent | None:
    """Append a compression checkpoint that covers only historical events."""

    normalized_session_id = str(session_id or "").strip()
    summary_text = str(summary or "").strip()
    if not normalized_session_id or not summary_text:
        return None
    normalized_current_turn_id = str(current_turn_id or turn_id or "").strip()
    events = load_turn_events(Path(project_root), normalized_session_id)
    coverable = [
        event
        for event in events
        if _is_coverable_by_checkpoint(event, current_turn_id=normalized_current_turn_id)
    ]
    payload = build_context_compression_checkpoint_payload(
        summary=summary_text,
        level=level,
        reason=reason,
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        iteration=iteration,
        trigger_source=trigger_source,
        effectiveness_threshold=effectiveness_threshold,
        effectiveness_ratio=effectiveness_ratio,
        effective=effective,
        source_message_count=source_message_count,
        tool_result_replacement_state=tool_result_replacement_state,
        covered_events=coverable,
    )
    return append_turn_event(
        Path(project_root),
        normalized_session_id,
        str(turn_id or normalized_current_turn_id or "context-compression").strip(),
        EVENT_COMPACTION_CHECKPOINT,
        status="checkpointed",
        payload=payload,
        source=source,
        visible_in_model=True,
        projection_kind="context_compression_checkpoint",
        source_kind="context_compression",
    )


def apply_context_compression_checkpoints(
    events: Iterable[TurnJournalEvent],
    *,
    current_turn_id: str = "",
) -> list[TurnJournalEvent]:
    """Return ledger events with checkpoint-covered historical events omitted."""

    event_list = list(events or [])
    if not event_list:
        return []
    normalized_current_turn_id = str(current_turn_id or "").strip()
    checkpoints = [
        event
        for event in event_list
        if event.event_type == EVENT_COMPACTION_CHECKPOINT
        and (not normalized_current_turn_id or event.turn_id != normalized_current_turn_id)
    ]
    if not checkpoints:
        return event_list
    covered_ids: set[str] = set()
    covered_ranges: list[tuple[int, int]] = []
    checkpoint_ids = {event.event_id for event in checkpoints}
    for checkpoint in checkpoints:
        payload = dict(checkpoint.payload or {})
        for event_id in list(payload.get("coveredEventIds") or []):
            normalized = str(event_id or "").strip()
            if normalized:
                covered_ids.add(normalized)
        start = _positive_int(payload.get("coveredEventSeqStart"))
        end = _positive_int(payload.get("coveredEventSeqEnd"))
        if start and end and end >= start:
            covered_ranges.append((start, end))

    filtered: list[TurnJournalEvent] = []
    for event in event_list:
        if event.event_id in checkpoint_ids:
            filtered.append(event)
            continue
        if normalized_current_turn_id and event.turn_id == normalized_current_turn_id:
            filtered.append(event)
            continue
        if _event_is_covered(event, covered_ids=covered_ids, covered_ranges=covered_ranges):
            continue
        filtered.append(event)
    return filtered


def latest_context_compression_checkpoint(
    events: Iterable[TurnJournalEvent],
) -> TurnJournalEvent | None:
    checkpoints = [
        event
        for event in list(events or [])
        if event.event_type == EVENT_COMPACTION_CHECKPOINT
    ]
    return checkpoints[-1] if checkpoints else None


def context_compression_projection(events: Iterable[TurnJournalEvent]) -> dict[str, Any]:
    event_list = list(events or [])
    checkpoints = [
        event
        for event in event_list
        if event.event_type == EVENT_COMPACTION_CHECKPOINT
    ]
    latest = checkpoints[-1] if checkpoints else None
    payload = dict(latest.payload or {}) if latest is not None else {}
    if payload and latest is not None:
        payload.setdefault("timestamp", str(latest.timestamp or "").strip())
    return {
        "compressionCount": len(checkpoints),
        "lastCompression": payload if payload else {},
        "lastCompressionEventId": latest.event_id if latest is not None else "",
        "lastCompressionSeq": int(latest.sequence or 0) if latest is not None else 0,
        "updatedAt": str(latest.timestamp or "").strip() if latest is not None else "",
    }


def _is_coverable_by_checkpoint(event: TurnJournalEvent, *, current_turn_id: str) -> bool:
    if event.event_type == EVENT_COMPACTION_CHECKPOINT:
        return True
    if current_turn_id and event.turn_id == current_turn_id:
        return False
    return True


def _event_is_covered(
    event: TurnJournalEvent,
    *,
    covered_ids: set[str],
    covered_ranges: list[tuple[int, int]],
) -> bool:
    if event.event_id and event.event_id in covered_ids:
        return True
    sequence = int(event.sequence or 0)
    return bool(sequence and any(start <= sequence <= end for start, end in covered_ranges))


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _short_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()[:16]


__all__ = [
    "append_context_compression_checkpoint",
    "apply_context_compression_checkpoints",
    "build_context_compression_checkpoint_payload",
    "context_compression_projection",
    "latest_context_compression_checkpoint",
]
