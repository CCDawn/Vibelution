# -*- coding: utf-8 -*-
"""Ledger-backed context compression checkpoints.

Compression checkpoints are model-context facts. The raw conversation ledger
keeps every event, while model replay can replace an older covered event range
with the checkpoint summary.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Iterable

from .turn_journal import (
    EVENT_COMPACTION_CHECKPOINT,
    EVENT_COMPRESSION_ATTEMPT,
    EVENT_CLI_TASK_RESULT,
    EVENT_TOOL_CALL_STARTED,
    EVENT_TOOL_RESULT,
    TurnJournalEvent,
    _event_tool_correlation_key,
    append_turn_event,
    fold_active_events,
    load_turn_events,
    model_messages_from_events,
)


def _scope_helpers():
    """Lazy-import the workflow scope authority to keep legacy chat imports light."""

    from core.research.workflow.checkpoint_store import (
        ScopeBindingMismatch,
        canonical_discussion_scope,
        discussion_scope_hash,
        scope_without_agent_id,
    )

    return (
        ScopeBindingMismatch,
        canonical_discussion_scope,
        discussion_scope_hash,
        scope_without_agent_id,
    )


def _normalized_compression_scope(
    scope: Any,
    *,
    scope_hash: str = "",
    child_session_scope: Any = None,
    required: bool = False,
) -> tuple[dict[str, Any] | None, str, bool]:
    """Normalize compression scope and reject a cross-scope child binding."""

    if scope is None and child_session_scope is not None:
        scope = child_session_scope
    if scope is None:
        if required:
            ScopeBindingMismatch, _, _, _ = _scope_helpers()
            raise ScopeBindingMismatch(
                "formal challenge compression checkpoint is missing discussion scope",
                field="scope",
            )
        return None, "", False
    ScopeBindingMismatch, canonical_scope, hash_for, without_agent = _scope_helpers()
    try:
        normalized = canonical_scope(scope, require_hash=False)
        if child_session_scope is not None:
            normalized_child = without_agent(child_session_scope)
            if normalized_child["scopeHash"] != normalized["scopeHash"]:
                raise ScopeBindingMismatch(
                    "compression checkpoint child session scope does not match discussion scope",
                    field="childSessionScope",
                    expected_scope_hash=normalized["scopeHash"],
                    observed_scope_hash=normalized_child["scopeHash"],
                )
        expected_hash = str(
            hash_for({key: value for key, value in normalized.items() if key != "scopeHash"})
        ).lower()
        supplied_hash = str(scope_hash or "").strip().lower()
        if supplied_hash and supplied_hash != expected_hash:
            raise ScopeBindingMismatch(
                "compression checkpoint scopeHash does not match its scope",
                field="scopeHash",
                expected_scope_hash=expected_hash,
                observed_scope_hash=supplied_hash,
            )
        normalized["scopeHash"] = expected_hash
        return normalized, expected_hash, True
    except ScopeBindingMismatch:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise ScopeBindingMismatch(
            f"invalid compression checkpoint scope: {exc}", field="scope"
        ) from exc


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
    include_sequence_range: bool = True,
    scope: Mapping[str, Any] | None = None,
    scope_hash: str = "",
    child_session_id: str = "",
    child_session_scope: Mapping[str, Any] | None = None,
    scope_binding_required: bool = False,
) -> dict[str, Any]:
    """Return the durable payload for a compression checkpoint event.

    ``include_sequence_range=False`` keeps only the explicit
    ``coveredEventIds``: a sparse covered set (kept-window events sit between
    folded ones) must never publish a min/max sequence range, or the replay
    would cover the un-summarized events inside the range as well.
    """

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
    normalized_scope, normalized_scope_hash, has_scope = _normalized_compression_scope(
        scope,
        scope_hash=scope_hash,
        child_session_scope=child_session_scope,
        required=scope_binding_required,
    )
    payload: dict[str, Any] = {
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
        "coveredEventSeqStart": (
            min(covered_sequences) if covered_sequences and include_sequence_range else 0
        ),
        "coveredEventSeqEnd": (
            max(covered_sequences) if covered_sequences and include_sequence_range else 0
        ),
        "coveredEventIds": [event.event_id for event in covered if str(event.event_id or "").strip()],
        "coveredEventCount": len(covered),
        "toolResultReplacement": replacement_state,
        "schema": "context_compression_checkpoint.v1",
    }
    if has_scope and normalized_scope is not None:
        payload["scope"] = {
            key: value for key, value in normalized_scope.items() if key != "scopeHash"
        }
        payload["scopeHash"] = normalized_scope_hash
        payload["childSessionId"] = str(child_session_id or "").strip()
        payload["scopeBindingRequired"] = True
    return payload


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
    summarized_messages: Iterable[Any] | None = None,
    source_messages: Iterable[Any] | None = None,
    retained_messages: Iterable[Any] | None = None,
    source: str = "agent_context_compression",
    scope: Mapping[str, Any] | None = None,
    scope_hash: str = "",
    child_session_id: str = "",
    child_session_scope: Mapping[str, Any] | None = None,
    scope_binding_required: bool = False,
) -> TurnJournalEvent | None:
    """Append a compression checkpoint without rewriting the transcript.

    ``summarized_messages`` is the set of messages the summary actually folded
    (the compression output's ``summarized_messages``). When provided, the
    checkpoint covers exactly the historical events projecting to those
    messages — kept-window and error-preserved events must stay uncovered, or
    the next replay silently drops history that never entered the summary.
    ``source_messages`` and ``retained_messages`` describe an explicit context
    replacement. They let replay retire only proven source events missing from
    the actual kept window, including completed work from the in-flight turn.
    Budget-retired events are recorded separately from summarized events. No
    provider messages or system prompts are stored in the checkpoint.
    Callers without that boundary retain the legacy historical-only behavior.
    """

    normalized_session_id = str(session_id or "").strip()
    summary_text = str(summary or "").strip()
    if not normalized_session_id or not summary_text:
        return None
    # A formal checkpoint is tied to the physical Child Session that supplied
    # its covered range.  ``session_id`` is the durable fallback identity; a
    # caller may also pass an explicit childSessionId for cross-checking.
    normalized_child_session_id = str(child_session_id or normalized_session_id).strip()
    if child_session_id and normalized_child_session_id != normalized_session_id:
        ScopeBindingMismatch, _, _, _ = _scope_helpers()
        raise ScopeBindingMismatch(
            "compression checkpoint childSessionId does not match ledger session",
            field="childSessionId",
        )
    _, _, has_scope = _normalized_compression_scope(
        scope,
        scope_hash=scope_hash,
        child_session_scope=child_session_scope,
        required=scope_binding_required,
    )
    normalized_current_turn_id = str(current_turn_id or turn_id or "").strip()
    events = load_turn_events(Path(project_root), normalized_session_id)
    replacement = source_messages is not None and retained_messages is not None
    coverable = [
        event
        for event in events
        if replacement or _is_coverable_by_checkpoint(event, current_turn_id=normalized_current_turn_id)
    ]
    retired_events: list[TurnJournalEvent] = []
    if replacement:
        source_events = _summarized_checkpoint_events(coverable, source_messages, exact_boundary=True)
        source_ids = {event.event_id for event in source_events}
        # Protect the kept window before assigning covered/retired events.
        # Ambiguous identical messages without identity remain replayable.
        retained_ids = {
            event.event_id
            for event in _summarized_checkpoint_events(
                coverable, retained_messages, exact_boundary=True, protect_ambiguous=True,
            )
        }
        covered_events = [
            event for event in _summarized_checkpoint_events(coverable, summarized_messages or [], exact_boundary=True)
            if event.event_id in source_ids and event.event_id not in retained_ids
        ]
        covered_ids = {event.event_id for event in covered_events}
        retired_events = [
            event for event in source_events
            if event.event_id not in covered_ids and event.event_id not in retained_ids
        ]
        include_sequence_range = False
    elif summarized_messages is None:
        covered_events = coverable
        include_sequence_range = True
    else:
        covered_events = _summarized_checkpoint_events(coverable, summarized_messages)
        # A sparse folded set (kept-window events in between) must not publish
        # a sequence range: replay treats the whole range as covered.
        include_sequence_range = _sequences_contiguous(covered_events)
    _assert_covered_events_scope(covered_events, scope=scope, required=scope_binding_required)
    _assert_covered_events_scope(retired_events, scope=scope, required=scope_binding_required)
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
        covered_events=covered_events,
        include_sequence_range=include_sequence_range,
        scope=scope,
        scope_hash=scope_hash,
        child_session_id=normalized_child_session_id if has_scope else "",
        child_session_scope=child_session_scope,
        scope_binding_required=scope_binding_required,
    )
    if replacement:
        payload.update({
            "retentionMode": "replacement",
            "retiredEventIds": [event.event_id for event in retired_events],
            "retiredEventCount": len(retired_events),
        })
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


def _assert_covered_events_scope(
    events: Iterable[TurnJournalEvent],
    *,
    scope: Mapping[str, Any] | None,
    required: bool,
) -> None:
    """Reject an explicitly tagged event from another Discussion Scope.

    Existing legacy ledger events do not carry scope metadata and remain
    readable.  Formal Child Session writers may tag events; once tagged, a
    checkpoint cannot cover a sibling candidate's event even if it happens to
    share a physical storage root.
    """

    if scope is None:
        return
    _, canonical_scope, _, _ = _scope_helpers()
    expected = canonical_scope(scope, require_hash=False)
    expected_hash = str(expected["scopeHash"])
    for index, event in enumerate(events):
        payload = dict(event.payload or {})
        tagged = payload.get("discussionScope") or payload.get("scope")
        if not isinstance(tagged, Mapping):
            continue
        observed = canonical_scope(tagged, require_hash=False)
        if str(observed["scopeHash"]) != expected_hash:
            ScopeBindingMismatch, _, _, _ = _scope_helpers()
            raise ScopeBindingMismatch(
                "compression checkpoint covers an event from another scope",
                field=f"coveredEvents[{index}].scope",
                expected_scope_hash=expected_hash,
                observed_scope_hash=str(observed["scopeHash"]),
            )


def append_context_compression_attempt(
    project_root: Path,
    session_id: str,
    *,
    turn_id: str = "",
    status: str,
    summary: str = "",
    level: str = "",
    reason: str = "",
    before_tokens: int = 0,
    after_tokens: int = 0,
    trigger_source: str = "",
    effectiveness_threshold: float = 0.0,
    effectiveness_ratio: float = 0.0,
    error_type: str = "",
    source: str = "agent_context_compression",
    scope: Mapping[str, Any] | None = None,
    scope_hash: str = "",
    child_session_id: str = "",
    child_session_scope: Mapping[str, Any] | None = None,
    scope_binding_required: bool = False,
) -> TurnJournalEvent | None:
    """Append a non-covering compression attempt marker."""

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    normalized_child_session_id = str(child_session_id or normalized_session_id).strip()
    if child_session_id and normalized_child_session_id != normalized_session_id:
        ScopeBindingMismatch, _, _, _ = _scope_helpers()
        raise ScopeBindingMismatch(
            "compression attempt childSessionId does not match ledger session",
            field="childSessionId",
        )
    normalized_scope, normalized_scope_hash, has_scope = _normalized_compression_scope(
        scope,
        scope_hash=scope_hash,
        child_session_scope=child_session_scope,
        required=scope_binding_required,
    )
    normalized_status = str(status or "").strip() or "skipped_low_savings"
    summary_text = str(summary or "").strip()
    before = max(0, int(before_tokens or 0))
    after = max(0, int(after_tokens or 0))
    payload = {
        "summary": summary_text,
        "summaryHash": _short_hash(summary_text),
        "summaryWritten": bool(summary_text),
        "level": str(level or "").strip(),
        "reason": str(reason or "").strip(),
        "triggerSource": str(trigger_source or "").strip(),
        "beforeTokens": before,
        "afterTokens": after,
        "savedTokens": max(0, before - after),
        "effectivenessThreshold": max(0.0, float(effectiveness_threshold or 0.0)),
        "effectivenessRatio": max(0.0, float(effectiveness_ratio or 0.0)),
        "effective": False,
        "markerStatus": normalized_status,
        "errorType": str(error_type or "").strip(),
        "schema": "context_compression_attempt.v1",
    }
    if has_scope and normalized_scope is not None:
        payload["scope"] = {
            key: value for key, value in normalized_scope.items() if key != "scopeHash"
        }
        payload["scopeHash"] = normalized_scope_hash
        payload["childSessionId"] = normalized_child_session_id
        payload["scopeBindingRequired"] = True
    return append_turn_event(
        Path(project_root),
        normalized_session_id,
        str(turn_id or "context-compression-attempt").strip(),
        EVENT_COMPRESSION_ATTEMPT,
        status=normalized_status,
        payload=payload,
        source=source,
        visible_in_model=False,
        projection_kind="context_compression_marker",
        source_kind="context_compression",
    )


def apply_context_compression_checkpoints(
    events: Iterable[TurnJournalEvent],
    *,
    current_turn_id: str = "",
    expected_scope: Mapping[str, Any] | None = None,
) -> list[TurnJournalEvent]:
    """Apply checkpoints from the active branch to its historical events."""

    # A checkpoint on a superseded branch must not cover active history.
    # Folding after compression is too late: the stale checkpoint may already
    # have removed the events needed to reconstruct the selected branch.
    event_list = fold_active_events(events)
    if not event_list:
        return []
    normalized_current_turn_id = str(current_turn_id or "").strip()
    checkpoints = [
        event
        for event in event_list
        if event.event_type == EVENT_COMPACTION_CHECKPOINT
        and (not normalized_current_turn_id or event.turn_id != normalized_current_turn_id)
    ]
    if expected_scope is not None:
        _, canonical_scope, _, _ = _scope_helpers()
        expected = canonical_scope(expected_scope, require_hash=False)
        expected_hash = str(expected["scopeHash"])
        for index, checkpoint in enumerate(checkpoints):
            payload = dict(checkpoint.payload or {})
            checkpoint_scope = payload.get("scope") or payload.get("discussionScope")
            if not isinstance(checkpoint_scope, Mapping):
                ScopeBindingMismatch, _, _, _ = _scope_helpers()
                raise ScopeBindingMismatch(
                    "formal compression checkpoint scope is missing",
                    field=f"checkpoints[{index}].scope",
                )
            observed = canonical_scope(checkpoint_scope, require_hash=False)
            if str(observed["scopeHash"]) != expected_hash:
                ScopeBindingMismatch, _, _, _ = _scope_helpers()
                raise ScopeBindingMismatch(
                    "compression checkpoint scope does not match current Child Session",
                    field=f"checkpoints[{index}].scope",
                    expected_scope_hash=expected_hash,
                    observed_scope_hash=str(observed["scopeHash"]),
                )
    if not checkpoints:
        return event_list
    covered_ids: set[str] = set()
    covered_ranges: list[tuple[int, int]] = []
    for checkpoint in checkpoints:
        payload = dict(checkpoint.payload or {})
        for event_id in [*list(payload.get("coveredEventIds") or []), *list(payload.get("retiredEventIds") or [])]:
            normalized = str(event_id or "").strip()
            if normalized:
                covered_ids.add(normalized)
        start = _positive_int(payload.get("coveredEventSeqStart"))
        end = _positive_int(payload.get("coveredEventSeqEnd"))
        if start and end and end >= start:
            covered_ranges.append((start, end))

    # Older checkpoints only name the projected result event. Its suppressed
    # start records must stay suppressed after that result is folded away.
    covered_ids = _completed_tool_lifecycle_ids(
        event_list,
        {
            event.event_id for event in event_list
            if _event_is_covered(event, covered_ids=covered_ids, covered_ranges=covered_ranges)
        },
    )

    filtered: list[TurnJournalEvent] = []
    for event in event_list:
        if normalized_current_turn_id and event.turn_id == normalized_current_turn_id:
            filtered.append(event)
            continue
        if _event_is_covered(event, covered_ids=covered_ids, covered_ranges=covered_ranges):
            continue
        filtered.append(event)
    from .compaction_fact_recovery import recover_legacy_checkpoint_facts

    return recover_legacy_checkpoint_facts(event_list, filtered)


def _completed_tool_lifecycle_ids(
    events: Iterable[TurnJournalEvent], covered_ids: set[str],
) -> set[str]:
    """Include starts suppressed by a covered, unambiguously resolved result.

    A call id is local to a Session/turn. Name-only correlation is not enough
    to discard history, and an uncovered result sharing the identity protects
    its starts. Later unresolved uses of an id also remain replayable.
    """
    event_list = fold_active_events(events)
    covered_through: dict[tuple[str, str, str], int] = {}
    retained_keys: set[tuple[str, str, str]] = set()

    def key_for(event: TurnJournalEvent) -> tuple[str, str, str] | None:
        correlation = _event_tool_correlation_key(event)
        if not event.session_id or not event.turn_id or not correlation.startswith("id:"):
            return None
        return event.session_id, event.turn_id, correlation

    for event in event_list:
        if not event.visible_in_model or event.event_type not in {EVENT_TOOL_RESULT, EVENT_CLI_TASK_RESULT}:
            continue
        key = key_for(event)
        if key is None:
            continue
        if event.event_id in covered_ids:
            covered_through[key] = max(covered_through.get(key, 0), event.sequence)
        else:
            retained_keys.add(key)

    expanded = set(covered_ids)
    for event in event_list:
        if event.event_type != EVENT_TOOL_CALL_STARTED:
            continue
        key = key_for(event)
        if key in covered_through and key not in retained_keys and event.sequence <= covered_through[key]:
            expanded.add(event.event_id)
    return expanded


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


def _summarized_checkpoint_events(
    events: Iterable[TurnJournalEvent],
    summarized_messages: Iterable[Any],
    *,
    exact_boundary: bool = False,
    protect_ambiguous: bool = False,
) -> list[TurnJournalEvent]:
    """Return the events whose projected model messages were folded into a summary.

    The checkpoint's covered set must equal the summary's actual input domain.
    Projecting the candidate events with the same model replay the seed uses
    keeps the mapping anchored on ``metadata.eventId``; messages whose content
    was rewritten downstream (redaction, tool-result replacement, truncation)
    simply fail to match and stay uncovered — under-covering only costs a
    duplicated replay, while over-covering loses history.
    """

    candidates = list(summarized_messages or [])
    event_list = [event for event in list(events or []) if isinstance(event, TurnJournalEvent)]
    if not candidates or not event_list:
        return []
    try:
        projected = model_messages_from_events(event_list)
    except Exception:
        return []
    event_by_id = {
        str(event.event_id or "").strip(): event
        for event in event_list
        if str(event.event_id or "").strip()
    }
    # Consume-on-match keeps the alignment monotonic: two history messages
    # with identical content cannot both claim one folded candidate, so a
    # kept-window twin can never be marked covered through its folded twin.
    unconsumed = list(range(len(candidates)))
    matched_ids: set[str] = set()
    if exact_boundary:
        # Without a durable event/tool identity, only an unambiguous complete
        # content match proves a replacement boundary. In particular, SHORT
        # must never claim SHORT WITH MORE CONTEXT or an identical older twin.
        proven_positions: list[int] = []
        for position in unconsumed:
            candidate = candidates[position]
            if _candidate_has_checkpoint_identity(candidate):
                proven_positions.append(position)
                continue
            possible_ids = {
                str(message.get("metadata", {}).get("eventId") or "")
                for message in projected
                if isinstance(message, Mapping)
                and _projects_to_summary_input(message, candidate, exact_content=True)
            } - {""}
            if len(possible_ids) == 1:
                proven_positions.append(position)
            elif protect_ambiguous:
                # Retaining too much is safe; treating an ambiguous kept
                # message as absent would silently retire a live request.
                matched_ids.update(possible_ids)
        unconsumed = proven_positions
    for message in projected:
        if not isinstance(message, Mapping):
            continue
        metadata = message.get("metadata")
        event_id = (
            str(metadata.get("eventId") or "").strip() if isinstance(metadata, Mapping) else ""
        )
        if not event_id or event_id not in event_by_id:
            continue
        for position in list(unconsumed):
            if _projects_to_summary_input(message, candidates[position], exact_content=exact_boundary):
                unconsumed.remove(position)
                matched_ids.add(event_id)
                break
    matched_ids = _completed_tool_lifecycle_ids(event_list, matched_ids)
    return [event for event in event_list if str(event.event_id or "").strip() in matched_ids]


def _candidate_has_checkpoint_identity(candidate: Any) -> bool:
    metadata = (
        candidate.get("metadata") if isinstance(candidate, Mapping)
        else getattr(candidate, "additional_kwargs", None)
    )
    return bool(
        (isinstance(metadata, Mapping) and metadata.get("eventId"))
        or _candidate_tool_call_id(candidate)
        or _candidate_tool_call_ids(candidate)
    )


def _projects_to_summary_input(
    projected: Mapping[str, Any], candidate: Any, *, exact_content: bool = False,
) -> bool:
    """Best-effort identity match between a projected event message and the
    in-memory message compression folded."""

    metadata = projected.get("metadata")
    candidate_metadata = (
        candidate.get("metadata") if isinstance(candidate, Mapping)
        else getattr(candidate, "additional_kwargs", None)
    )
    projected_id = str(metadata.get("eventId") or "") if isinstance(metadata, Mapping) else ""
    candidate_id = str(candidate_metadata.get("eventId") or "") if isinstance(candidate_metadata, Mapping) else ""
    if projected_id and candidate_id:
        return projected_id == candidate_id
    projected_role = str(projected.get("role") or "").strip().lower()
    # History assembly promotes checkpoint summaries to runtime/system notices.
    # A later checkpoint must replace that earlier summary rather than append
    # another copy on every turn.
    if (
        isinstance(metadata, Mapping)
        and metadata.get("kind") == EVENT_COMPACTION_CHECKPOINT
        and _candidate_message_role(candidate) in {"system", "runtime", "runtime_context"}
    ):
        if exact_content:
            from core.infrastructure.runtime_input import build_runtime_notice_message

            summary_text = str(projected.get("content") or "").strip()
            candidate_text = str(_candidate_content_text(candidate) or "").strip()
            return candidate_text in {
                summary_text,
                f"历史摘要:\n{summary_text}",
                build_runtime_notice_message(f"历史摘要:\n{summary_text}").content,
            }
        return _content_overlaps(projected.get("content"), candidate)
    if projected_role != _candidate_message_role(candidate):
        return False
    if projected_role == "tool":
        projected_call_id = str(projected.get("tool_call_id") or "").strip()
        candidate_call_id = _candidate_tool_call_id(candidate)
        if projected_call_id and candidate_call_id:
            return projected_call_id == candidate_call_id
    else:
        projected_calls = _projected_tool_call_ids(projected)
        candidate_calls = _candidate_tool_call_ids(candidate)
        if projected_calls and candidate_calls:
            if not set(projected_calls) & set(candidate_calls):
                return False
            # Tool-call ids are a strong identity anchor; content may have
            # been legitimately rewritten downstream (redaction/replacement).
            return True
    if exact_content:
        projected_content = projected.get("content")
        candidate_content = _candidate_content_text(candidate)
        if isinstance(projected_content, str) and isinstance(candidate_content, str):
            projected_text, candidate_text = projected_content.strip(), candidate_content.strip()
            if projected_text == candidate_text:
                return True
            if projected_role == "user":
                from core.infrastructure.runtime_input import build_chat_user_message

                return candidate_text == build_chat_user_message(projected_text)["content"]
            return False
        return projected_content == candidate_content
    return _content_overlaps(projected.get("content"), candidate)


def _candidate_message_role(candidate: Any) -> str:
    if isinstance(candidate, Mapping):
        role = str(candidate.get("role") or "").strip().lower()
    else:
        role = str(getattr(candidate, "type", "") or getattr(candidate, "role", "") or "").strip().lower()
    return {"human": "user", "ai": "assistant"}.get(role, role)


def _projected_tool_call_ids(projected: Mapping[str, Any]) -> list[str]:
    raw = projected.get("tool_calls") or projected.get("toolCalls") or []
    ids: list[str] = []
    for item in list(raw or []):
        if isinstance(item, Mapping):
            call_id = str(item.get("id") or "").strip()
        else:
            call_id = str(getattr(item, "id", "") or "").strip()
        if call_id:
            ids.append(call_id)
    return ids


def _candidate_tool_call_ids(candidate: Any) -> list[str]:
    if isinstance(candidate, Mapping):
        raw = candidate.get("tool_calls") or candidate.get("toolCalls") or []
    else:
        raw = getattr(candidate, "tool_calls", None) or []
    ids: list[str] = []
    for item in list(raw or []):
        if isinstance(item, Mapping):
            call_id = str(item.get("id") or "").strip()
        else:
            call_id = str(getattr(item, "id", "") or "").strip()
        if call_id:
            ids.append(call_id)
    return ids


def _candidate_tool_call_id(candidate: Any) -> str:
    if isinstance(candidate, Mapping):
        value = candidate.get("tool_call_id") or candidate.get("toolCallId")
    else:
        value = getattr(candidate, "tool_call_id", None)
    return str(value or "").strip()


def _candidate_content_text(candidate: Any) -> Any:
    if isinstance(candidate, Mapping):
        return candidate.get("content")
    return getattr(candidate, "content", None)


def _content_overlaps(projected_content: Any, candidate: Any) -> bool:
    projected_text = _overlap_text(projected_content)
    candidate_text = _overlap_text(_candidate_content_text(candidate))
    if not projected_text or not candidate_text:
        return False
    return projected_text == candidate_text or projected_text in candidate_text or candidate_text in projected_text


def _overlap_text(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("text") or value.get("content") or ""
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item or ""))
        value = "".join(parts)
    return " ".join(str(value or "").split())


def _sequences_contiguous(events: Iterable[TurnJournalEvent]) -> bool:
    sequences = sorted(
        int(event.sequence or 0)
        for event in list(events or [])
        if int(event.sequence or 0) > 0
    )
    return all(next_seq - current_seq == 1 for current_seq, next_seq in zip(sequences, sequences[1:]))


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
    "append_context_compression_attempt",
    "apply_context_compression_checkpoints",
    "build_context_compression_checkpoint_payload",
    "context_compression_projection",
    "latest_context_compression_checkpoint",
]
