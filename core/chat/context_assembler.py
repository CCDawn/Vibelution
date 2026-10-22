# -*- coding: utf-8 -*-
"""Cache-friendly conversation context assembly."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable

from .history_ledger import (
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
    HistoryEvent,
    HistoryEventBuilder,
    latest_checkpoint,
)
from .tool_result_replacement import (
    apply_sticky_tool_result_replacements,
    empty_tool_result_replacement_state,
    replace_large_tool_results_for_compression as replace_tool_results_for_compression,
)
from .microcompact import (
    apply_micro_compact_projection,
    apply_sticky_micro_compact_projection,
    empty_micro_compact_state,
)
from .projection_stickiness import (
    LOCK_MODE_AGENT_INBOX,
    LOCK_MODE_MICRO_COMPACT,
    LOCK_MODE_REPLACEMENT,
    LOCK_AGENT_INBOX_KIND_ASSISTANT,
    LOCK_AGENT_INBOX_KIND_TOOL,
    ProjectionLockIndex,
    content_digest,
    projection_locks_from_ledger_events,
)
from .conversation_invariant import (
    ConversationSeedInvariantError,
    canonical_conversation_messages_from_events,
    canonical_replay_input,
    check_conversation_payload_invariant,
    conversation_layer_fingerprint,
    conversation_layer_messages,
)
from .conversation_ledger import (
    ConversationLedgerEvent,
    apply_context_compression_checkpoints,
    conversation_model_messages_from_events,
    fold_active_events,
    latest_context_compression_checkpoint,
)
from .turn_journal import (
    ModelProjectionReplay,
    _ProjectionResumeBail,
    EVENT_ASSISTANT_DELTA_COMMITTED,
    EVENT_ASSISTANT_ITEM_COMMITTED,
    EVENT_ASSISTANT_MESSAGE,
    EVENT_ASSISTANT_PARTIAL,
    EVENT_CLI_SESSION_LIFECYCLE,
    EVENT_CLI_TASK_RESULT,
    EVENT_CLI_TASK_SENT,
    EVENT_TOOL_CALL_STARTED,
    EVENT_TOOL_RESULT,
    EVENT_TOOL_RESULT_PROJECTION_LOCK,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_CONTEXT,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_STARTED,
    EVENT_TURN_STEER,
    EVENT_SUBAGENT_PROGRESS,
    EVENT_USER_MESSAGE,
)
from .conversation_invariant import (
    ConversationSeedInvariantError,
    canonical_conversation_messages_from_events,
    check_conversation_payload_invariant,
    conversation_layer_fingerprint,
)


DEFAULT_RECENT_MESSAGE_LIMIT = 8
AGENT_INBOX_TOOL_RESULT_CHAR_LIMIT = 900
AGENT_INBOX_ASSISTANT_MESSAGE_CHAR_LIMIT = 1_800


@dataclass(frozen=True)
class ContextSegment:
    key: str
    label: str
    source: str
    item_count: int = 0
    chars: int = 0
    cache_policy: str = "dynamic"
    included_in_model_input: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "source": self.source,
            "itemCount": self.item_count,
            "chars": self.chars,
            "cachePolicy": self.cache_policy,
            "includedInModelInput": self.included_in_model_input,
        }


@dataclass(frozen=True)
class ContextAssemblyResult:
    history_messages: list[dict[str, Any]]
    events: list[HistoryEvent]
    included_event_ids: list[str] = field(default_factory=list)
    omitted_event_count: int = 0
    checkpoint_event_id: str = ""
    segments: list[ContextSegment] = field(default_factory=list)
    cacheable_prefix_hash: str = ""
    dynamic_context_hash: str = ""
    tool_result_replacement_state: dict[str, Any] = field(
        default_factory=empty_tool_result_replacement_state
    )
    micro_compact_state: dict[str, Any] = field(default_factory=empty_micro_compact_state)
    history_seed_compaction_state: dict[str, Any] = field(default_factory=dict)

    def to_composition_patch(self) -> dict[str, Any]:
        return {
            "schemaVersion": 2,
            "includedEventIds": list(self.included_event_ids),
            "omittedEventCount": self.omitted_event_count,
            "checkpointEventId": self.checkpoint_event_id,
            "cache": {
                "cacheablePrefixHash": self.cacheable_prefix_hash,
                "dynamicContextHash": self.dynamic_context_hash,
                "cacheableSegmentCount": len(
                    [segment for segment in self.segments if segment.cache_policy == "prefix_candidate"]
                ),
                "volatileSegmentCount": len(
                    [segment for segment in self.segments if segment.cache_policy != "prefix_candidate"]
                ),
            },
            "segments": [segment.to_dict() for segment in self.segments],
            "toolResultReplacement": dict(self.tool_result_replacement_state or {}),
            "microCompact": dict(self.micro_compact_state or {}),
            "historySeedCompaction": dict(self.history_seed_compaction_state or {}),
        }


_MISS = object()
_EMPTY = object()


@dataclass(frozen=True)
class _MemoEntry:
    """One memo slot: the stored input items, the projected value, and any
    stage-specific bookkeeping (turn ids, flags, carried builders)."""

    items: tuple[Any, ...]
    value: Any
    extra: dict[str, Any] = field(default_factory=dict)


class _IdentityListMemo:
    """Identity + append-prefix memo for pure projections over frozen lists.

    Journal loads reuse parsed prefix objects across appends, so two lists
    built from the same journal state share object identities element-wise.
    A plain :meth:`lookup` hits only on an exact element-wise replay (same
    length, every item ``is`` the stored one). Projection stages that can be
    extended incrementally use :meth:`entry` plus :func:`_prefix_append_guard`
    instead: the stored tuple is a shared prefix, and only the appended tail
    is projected. Stored tuples keep every item referenced, which rules out
    id-reuse collisions; any mismatch just misses and recomputes, so this can
    only trade a recompute for a recompute.

    Bounded LRU (entries evict oldest-first past ``max_entries``) and
    thread-safe (one lock around the dict; projections themselves run outside
    it, so racers only ever store equally-correct values).
    """

    def __init__(self, *, max_entries: int = 256) -> None:
        self._entries: dict[tuple[Any, ...], _MemoEntry] = {}
        self._max_entries = max(8, int(max_entries))
        self._lock = threading.Lock()

    def entry(self, scope: tuple[Any, ...]) -> _MemoEntry | None:
        with self._lock:
            entry = self._entries.get(scope)
            if entry is not None:
                # Refresh recency for the LRU eviction below.
                self._entries.pop(scope, None)
                self._entries[scope] = entry
            return entry

    def lookup(self, scope: tuple[Any, ...], items: list[Any]) -> Any:
        entry = self.entry(scope)
        if entry is None:
            return _MISS
        stored = entry.items
        if len(items) != len(stored):
            return _MISS
        for index, kept in enumerate(stored):
            if items[index] is not kept:
                return _MISS
        return entry.value

    def store(
        self,
        scope: tuple[Any, ...],
        items: list[Any],
        value: Any,
        extra: dict[str, Any] | None = None,
    ) -> None:
        entry = _MemoEntry(items=tuple(items), value=value, extra=extra or {})
        with self._lock:
            self._entries[scope] = entry
            while len(self._entries) > self._max_entries:
                oldest = next(iter(self._entries))
                self._entries.pop(oldest, None)


_ASSEMBLY_MEMO = _IdentityListMemo()


# Event types whose arrival never rewrites the projection of earlier events:
# ordinary turn traffic plus out-of-band never-model-visible facts. Anything
# else — fold markers (branch_rebase), compression checkpoints (covered-range
# deletion), compression attempts, resilience/recovery facts, terminal failure
# events, and unknown future types — forces a full recompute.
_PREFIX_APPEND_SAFE_EVENT_TYPES = frozenset(
    {
        EVENT_TURN_STARTED,
        EVENT_USER_MESSAGE,
        EVENT_TURN_CONTEXT,
        EVENT_ASSISTANT_PARTIAL,
        EVENT_ASSISTANT_DELTA_COMMITTED,
        EVENT_ASSISTANT_ITEM_COMMITTED,
        EVENT_ASSISTANT_MESSAGE,
        EVENT_TOOL_CALL_STARTED,
        EVENT_TOOL_RESULT,
        EVENT_TOOL_RESULT_PROJECTION_LOCK,
        EVENT_CLI_TASK_SENT,
        EVENT_CLI_TASK_RESULT,
        EVENT_CLI_SESSION_LIFECYCLE,
        EVENT_TURN_COMPLETED,
        EVENT_TURN_INTERRUPTED,
        EVENT_TURN_STEER,
        EVENT_SUBAGENT_PROGRESS,
    }
)


def _prefix_append_guard(
    stored_items: tuple[Any, ...],
    items: list[Any],
    *,
    known_turn_ids: frozenset[str] | set[str],
    excluded_turn_id: str = "",
) -> tuple[list[Any], list[Any]] | None:
    """Validate an identity-prefix append of safe, unseen-turn events.

    Returns ``(appended_all, visible)`` — the full appended tail and the part
    of it that survives ``excluded_turn_id`` filtering — or ``None`` when the
    list shrank, reordered, contains unsafe event types, or appends events of
    a turn this stage's input already carries (an out-of-order rewrite the
    incremental path must not guess about).
    """

    offset = len(stored_items)
    if len(items) < offset:
        return None
    for index in range(offset):
        if items[index] is not stored_items[index]:
            return None
    appended_all = list(items[offset:])
    visible: list[Any] = []
    for event in appended_all:
        if getattr(event, "event_type", "") not in _PREFIX_APPEND_SAFE_EVENT_TYPES:
            return None
        turn_id = str(getattr(event, "turn_id", "") or "").strip()
        if not turn_id:
            return None
        if excluded_turn_id and turn_id == excluded_turn_id:
            continue
        if turn_id in known_turn_ids:
            return None
        visible.append(event)
    return appended_all, visible


def _event_turn_id(event: Any) -> str:
    return str(getattr(event, "turn_id", "") or "").strip()


def _event_type(event: Any) -> str:
    return str(getattr(event, "event_type", "") or "")


def _input_turn_ids(events: list[Any]) -> frozenset[str]:
    return frozenset(_event_turn_id(event) for event in events if _event_turn_id(event))


def _historical_ledger_events_memoized(
    raw_events: list[ConversationLedgerEvent],
    *,
    current_turn_id: str,
    session_id: str,
) -> list[ConversationLedgerEvent]:
    """Memoized :func:`_historical_ledger_events` (fold + current-turn cut).

    Append-only growth of the raw journal under the safe-type guard folds to
    ``stored_folded + appended`` and the turn cut to
    ``stored_output + visible``; a turn rollover re-admits the previously
    excluded stored-turn block (already folded inside ``folded_full``).
    Anything else recomputes.
    """

    scope = ("historical_ledger_events", session_id)
    normalized_turn_id = str(current_turn_id or "").strip()
    entry = _ASSEMBLY_MEMO.entry(scope)
    if entry is not None:
        # The exclusion window rides on current_turn_id, so the exact replay
        # hit is only valid under the same window.
        if (
            entry.extra["turnId"] == normalized_turn_id
            and len(raw_events) == len(entry.items)
            and all(raw_events[index] is kept for index, kept in enumerate(entry.items))
        ):
            return entry.value
        extra = entry.extra
        guard = _prefix_append_guard(
            entry.items,
            raw_events,
            known_turn_ids=extra["knownTurnIds"],
            excluded_turn_id=normalized_turn_id,
        )
        if guard is not None:
            appended_all, visible = guard
            if extra["turnId"] == normalized_turn_id:
                new_output = [*entry.value, *visible]
            else:
                new_output = [*extra["foldedFull"], *visible]
            new_folded_full = [*extra["foldedFull"], *appended_all]
            new_extra = {
                "turnId": normalized_turn_id,
                "foldedFull": new_folded_full,
                "knownTurnIds": extra["knownTurnIds"]
                | {turn for turn in map(_event_turn_id, appended_all) if turn},
            }
            _ASSEMBLY_MEMO.store(scope, raw_events, new_output, new_extra)
            return new_output
    output = _historical_ledger_events(raw_events, current_turn_id=current_turn_id)
    _ASSEMBLY_MEMO.store(
        scope,
        raw_events,
        output,
        {
            "turnId": normalized_turn_id,
            "foldedFull": fold_active_events(raw_events),
            "knownTurnIds": _input_turn_ids(raw_events),
        },
    )
    return output


def _projection_locks_memoized(
    raw_events: list[ConversationLedgerEvent],
    *,
    session_id: str,
) -> ProjectionLockIndex:
    """Memoized :func:`projection_locks_from_ledger_events`.

    The index is first-wins, so an identity-prefix append can only add new
    records: the cached index is extended in place (keeping object identity
    for downstream sticky-overlay memos) and returned. Any non-append change
    rebuilds from scratch.
    """

    scope = ("projection_locks", session_id)
    entry = _ASSEMBLY_MEMO.entry(scope)
    if entry is not None:
        stored, index, _extra = entry.items, entry.value, entry.extra
        if len(raw_events) >= len(stored) and all(
            raw_events[i] is kept for i, kept in enumerate(stored)
        ):
            appended = raw_events[len(stored):]
            if appended:
                _merge_projection_lock_events(index, appended)
            if len(raw_events) > len(stored):
                _ASSEMBLY_MEMO.store(scope, raw_events, index)
            return index
    index = projection_locks_from_ledger_events(raw_events)
    _ASSEMBLY_MEMO.store(scope, raw_events, index)
    return index


def _merge_projection_lock_events(index: ProjectionLockIndex, events: list[Any]) -> None:
    from .projection_stickiness import _lock_record_from_decision

    for event in events:
        if _event_type(event) != "tool_result_projection_lock":
            continue
        payload = event.payload if isinstance(event.payload, dict) else {}
        for decision in list(payload.get("decisions") or []):
            record = _lock_record_from_decision(decision)
            if record is not None:
                index.add(record)


def _checkpointed_events_memoized(
    ledger_event_list: list[ConversationLedgerEvent],
    *,
    current_turn_id: str,
    session_id: str,
) -> list[ConversationLedgerEvent]:
    """Memoized :func:`apply_context_compression_checkpoints`.

    Checkpoints delete covered earlier events, so any appended checkpoint
    (unsafe type) misses. A safe append only extends: no new covered ranges
    can appear, and an appended event's sequence is always past every stored
    covered range.
    """

    scope = ("context_compression_checkpoints", session_id)
    normalized_turn_id = str(current_turn_id or "").strip()
    entry = _ASSEMBLY_MEMO.entry(scope)
    if entry is not None:
        # Checkpoint application keys on current_turn_id, so the exact replay
        # hit is only valid under the same window.
        if (
            entry.extra.get("turnId") == normalized_turn_id
            and len(ledger_event_list) == len(entry.items)
            and all(ledger_event_list[index] is kept for index, kept in enumerate(entry.items))
        ):
            return entry.value
        extra = entry.extra
        guard = _prefix_append_guard(
            entry.items,
            ledger_event_list,
            known_turn_ids=extra["knownTurnIds"],
            excluded_turn_id=normalized_turn_id,
        )
        if guard is not None:
            appended_all, visible = guard
            new_output = [*entry.value, *visible]
            _ASSEMBLY_MEMO.store(
                scope,
                ledger_event_list,
                new_output,
                {
                    "turnId": normalized_turn_id,
                    "knownTurnIds": extra["knownTurnIds"]
                    | {turn for turn in map(_event_turn_id, appended_all) if turn},
                },
            )
            return new_output
    output = apply_context_compression_checkpoints(
        ledger_event_list,
        current_turn_id=current_turn_id,
    )
    _ASSEMBLY_MEMO.store(
        scope,
        ledger_event_list,
        output,
        {
            "turnId": normalized_turn_id,
            "knownTurnIds": _input_turn_ids(ledger_event_list),
        },
    )
    return output


def _model_messages_memoized(
    ledger_replay_events: list[ConversationLedgerEvent],
    *,
    session_id: str,
) -> list[dict[str, Any]]:
    """Memoized model projection over the checkpointed historical event list.

    Exact element-wise replay of the stored input reuses the cached message
    list (zero replay) — this covers every re-assembly of an unchanged
    journal state, including all mid-turn growth of the *current* turn, which
    the historical window never sees. Appended growth resumes from the stored
    provenance carry (the batch-8 fix-G follow-up): the projection's
    sourceIndex baseline and scan state ride the memo, so a safe append
    replays only the appended turns and must match a cold replay byte for
    byte. Anything the carry cannot prove — rewinds, marker appends, same-turn
    rewrites, cross-turn id collisions — recomputes in full.
    """

    scope = ("conversation_model_messages", session_id)
    entry = _ASSEMBLY_MEMO.entry(scope)
    if entry is not None:
        if len(ledger_replay_events) == len(entry.items) and all(
            ledger_replay_events[index] is kept for index, kept in enumerate(entry.items)
        ):
            return entry.value
        extra = entry.extra
        guard = _prefix_append_guard(
            entry.items,
            ledger_replay_events,
            known_turn_ids=extra["knownTurnIds"],
        )
        if guard is not None:
            appended = guard[0]
            try:
                replay = ModelProjectionReplay(carry=extra["carry"])
                replay.feed(extra["pendingEvents"])
                replay.feed(appended)
                messages = replay.finish()
            except _ProjectionResumeBail:
                messages = None
            if messages is not None:
                _ASSEMBLY_MEMO.store(
                    scope,
                    ledger_replay_events,
                    messages,
                    {
                        "carry": replay.carry,
                        "pendingEvents": replay.pending_events,
                        "knownTurnIds": extra["knownTurnIds"]
                        | {turn for turn in map(_event_turn_id, appended) if turn},
                    },
                )
                return messages
    replay = ModelProjectionReplay()
    replay.feed(ledger_replay_events)
    messages = replay.finish()
    _ASSEMBLY_MEMO.store(
        scope,
        ledger_replay_events,
        messages,
        {
            "carry": replay.carry,
            "pendingEvents": replay.pending_events,
            "knownTurnIds": _input_turn_ids(ledger_replay_events),
        },
    )
    return messages


def _canonical_messages_memoized(
    raw_ledger_event_list: list[ConversationLedgerEvent],
    *,
    current_turn_id: str,
    session_id: str,
) -> list[dict[str, Any]]:
    """Memoized canonical replay (fold + current-turn cut + layer filter).

    The canonical window excludes the in-flight turn inside the projection,
    so journal growth of the *current* turn leaves the value untouched: the
    cached value is reused while only the stored input tuple rolls forward.
    A turn rollover admits the previously excluded block — the replay input
    grows by an identity-checked prefix, and the projection resumes from the
    stored provenance carry over exactly the admitted delta. Any change the
    carry cannot prove byte-equivalent recomputes in full, matching a cold
    assembly byte for byte.
    """

    scope = ("canonical_conversation_messages", session_id)
    normalized_turn_id = str(current_turn_id or "").strip()
    entry = _ASSEMBLY_MEMO.entry(scope)
    if entry is not None and entry.extra["turnId"] == normalized_turn_id:
        guard = _prefix_append_guard(
            entry.items,
            raw_ledger_event_list,
            known_turn_ids=entry.extra["knownTurnIds"],
            excluded_turn_id=normalized_turn_id,
        )
        if guard is not None and not guard[1]:
            # Every appended event belongs to the excluded in-flight turn.
            _ASSEMBLY_MEMO.store(
                scope,
                raw_ledger_event_list,
                entry.value,
                entry.extra,
            )
            return entry.value
    replay_input = canonical_replay_input(
        raw_ledger_event_list,
        current_turn_id=normalized_turn_id,
    )
    messages = None
    used_carry = None
    used_pending: list[ConversationLedgerEvent] = []
    if entry is not None:
        stored_input = entry.extra["replayInput"]
        if len(replay_input) > len(stored_input) and all(
            replay_input[index] is kept for index, kept in enumerate(stored_input)
        ):
            block = replay_input[len(stored_input):]
            try:
                replay = ModelProjectionReplay(carry=entry.extra["carry"])
                replay.feed(entry.extra["pendingEvents"])
                replay.feed(block)
                model_messages = replay.finish()
            except _ProjectionResumeBail:
                model_messages = None
            if model_messages is not None:
                messages = conversation_layer_messages(model_messages)
                used_carry = replay.carry
                used_pending = replay.pending_events
    if messages is None:
        replay = ModelProjectionReplay()
        replay.feed(replay_input)
        model_messages = replay.finish()
        messages = conversation_layer_messages(model_messages)
        used_carry = replay.carry
        used_pending = replay.pending_events
    _ASSEMBLY_MEMO.store(
        scope,
        raw_ledger_event_list,
        messages,
        {
            "turnId": normalized_turn_id,
            "knownTurnIds": _input_turn_ids(raw_ledger_event_list),
            "carry": used_carry,
            "pendingEvents": used_pending if used_carry is not None else [],
            "replayInput": replay_input,
        },
    )
    return messages


def _identity_value_memoized(scope: tuple[Any, ...], items: list[Any], compute) -> Any:
    """Reuse a cached pure value when the input list replays identically."""

    cached = _ASSEMBLY_MEMO.lookup(scope, items)
    if cached is not _MISS:
        return cached
    value = compute()
    _ASSEMBLY_MEMO.store(scope, items, value)
    return value


def _history_events_memoized(
    normalized_messages: list[dict[str, Any]],
    *,
    session_id: str,
) -> list[HistoryEvent]:
    """Memoized :func:`build_history_events` with appended-tail delta.

    The builder's carried tool-call lookup and running message index make the
    projection resumable: a safe identity-prefix append feeds only the new
    messages to a forked builder.
    """

    scope = ("build_history_events", session_id)
    entry = _ASSEMBLY_MEMO.entry(scope)
    if entry is not None:
        stored = entry.items
        offset = len(stored)
        if len(normalized_messages) >= offset and all(
            normalized_messages[index] is kept for index, kept in enumerate(stored)
        ):
            appended = normalized_messages[offset:]
            if not appended:
                _ASSEMBLY_MEMO.store(scope, normalized_messages, entry.value, entry.extra)
                return list(entry.value)
            builder = entry.extra["builder"].fork()
            delta_events = list(builder.feed(appended))
            new_events = [*entry.value, *delta_events]
            _ASSEMBLY_MEMO.store(
                scope,
                normalized_messages,
                new_events,
                {"builder": builder},
            )
            return new_events
    builder = HistoryEventBuilder(session_id=session_id)
    builder.feed(normalized_messages)
    _ASSEMBLY_MEMO.store(scope, normalized_messages, builder.events, {"builder": builder})
    return builder.events


def _clone_overlay_state(state: dict[str, Any]) -> dict[str, Any]:
    """Content copy of an overlay state dict (one level of list entries)."""

    if not isinstance(state, dict):
        return state
    cloned: dict[str, Any] = {}
    for key, value in state.items():
        if isinstance(value, list):
            cloned[key] = [
                dict(entry) if isinstance(entry, dict) else entry for entry in value
            ]
        elif isinstance(value, dict):
            cloned[key] = dict(value)
        else:
            cloned[key] = value
    return cloned


def _sticky_overlay_memoized(
    scope: tuple[Any, ...],
    source_messages: list[Any],
    *,
    overlay,
    projection_locks: ProjectionLockIndex | None,
    session_id: str,
    state: dict[str, Any],
) -> tuple[list[Any], dict[str, Any]]:
    """Memoized sticky overlay with an exact-replay fast path.

    The overlay's per-message projection is cheap, but its *state* accounting
    (restoration counts) is whole-list: a tail-only replay would under-count
    locked forms the raw derivation no longer selects. Unchanged windows
    replay from the cache; any growth takes the full overlay call — identical
    to an unmemoized assembly — so the returned state always matches a cold
    round byte for byte.
    """

    if projection_locks is None:
        return overlay(source_messages, projection_locks=None, session_id=session_id, state=state)
    entry = _ASSEMBLY_MEMO.entry(scope)
    if entry is not None:
        extra = entry.extra
        if extra["locks"] is projection_locks and extra["inState"] == state:
            stored = entry.items
            offset = len(stored)
            if len(source_messages) == offset and all(
                source_messages[index] is kept for index, kept in enumerate(stored)
            ):
                return list(entry.value[0]), _clone_overlay_state(entry.value[1])
    out_list, out_state = overlay(
        source_messages,
        projection_locks=projection_locks,
        session_id=session_id,
        state=state,
    )
    _ASSEMBLY_MEMO.store(
        scope,
        source_messages,
        (out_list, out_state),
        {"locks": projection_locks, "inState": _clone_overlay_state(state)},
    )
    return out_list, out_state


def assemble_conversation_context(
    messages: Iterable[dict[str, Any]] | None,
    *,
    session_id: str = "",
    current_turn_id: str = "",
    recent_message_limit: int | None = DEFAULT_RECENT_MESSAGE_LIMIT,
    retrieved_events: Iterable[HistoryEvent] | None = None,
    ledger_events: Iterable[ConversationLedgerEvent] | None = None,
    replace_large_tool_results_for_compression: bool = False,
    tool_result_replacement_char_limit: int = 12_000,
    micro_compact_old_tool_results: bool = False,
    micro_compact_keep_recent_groups: int = 5,
    micro_compact_min_savings_tokens: int = 256,
    micro_compact_tool_whitelist: Iterable[str] | None = None,
    history_seed_profile: str = "full",
    enforce_conversation_invariant: bool = True,
) -> ContextAssemblyResult:
    """Return the ledger history view used to seed an agent turn.

    ``recent_message_limit=None`` replays the complete post-checkpoint history.
    Callers use it when dropping an uncheckpointed event would lose conversation
    state; explicit numeric limits retain the existing bounded-tail behavior.

    Checkpoint (compression summary) messages always ride at the tail of the
    assembled history so provider prefix caches stay valid across
    re-checkpointing; see ``_split_history_checkpoint_messages``.
    """

    ledger_event_list = _historical_ledger_events_memoized(
        list(ledger_events or []),
        current_turn_id=current_turn_id,
        session_id=session_id,
    )
    raw_ledger_event_list = list(ledger_events or [])
    # Sticky projection locks ride the ledger itself: past assemblies append
    # out-of-band lock events recording which tool results were sent in a
    # projected form. Building the index is a cheap type-filtered scan; for
    # sessions with no lock events yet it stays empty and every overlay below
    # degrades to today's behavior.
    projection_locks = _projection_locks_memoized(raw_ledger_event_list, session_id=session_id)
    ledger_replay_events = _checkpointed_events_memoized(
        ledger_event_list,
        current_turn_id=current_turn_id,
        session_id=session_id,
    )
    # Memo scopes: turn-agnostic projections (model replay, fingerprints,
    # history events) are pure functions of their identity-keyed input lists,
    # so they key on the session only and can be reused whenever the same
    # journal state is assembled again — including under a different turn id.
    # Unchanged lists reuse the cached value object; safe appends extend the
    # cached projection incrementally; anything else recomputes in full. The
    # canonical replay keys on the session too and handles the current-turn
    # exclusion window inside its own delta logic (same-turn appends are
    # invisible to it; a rollover replays the previously excluded block).
    ledger_messages = _model_messages_memoized(ledger_replay_events, session_id=session_id)
    if enforce_conversation_invariant:
        invariant = check_conversation_payload_invariant(ledger_messages)
        if not invariant.ok:
            raise ConversationSeedInvariantError(
                error_type=str(invariant.error_type or "conversation_seed_invariant_failed"),
                message=str(invariant.message or "Ledger history seed failed conversation invariant."),
                details=dict(invariant.details or {}),
            )
        canonical_history = _canonical_messages_memoized(
            raw_ledger_event_list,
            current_turn_id=current_turn_id,
            session_id=session_id,
        )
        memoized_canonical_fingerprint = _identity_value_memoized(
            ("conversation_layer_fingerprint", session_id),
            canonical_history,
            lambda: conversation_layer_fingerprint(canonical_history),
        )
        memoized_model_fingerprint = _identity_value_memoized(
            ("conversation_layer_fingerprint_model", session_id),
            ledger_messages,
            lambda: conversation_layer_fingerprint(ledger_messages),
        )
        if memoized_canonical_fingerprint != memoized_model_fingerprint:
            raise ConversationSeedInvariantError(
                error_type="ledger_history_projection_mismatch",
                message="Ledger history seed projection does not match canonical ConversationLedger replay.",
                details={
                    "expectedFingerprint": memoized_canonical_fingerprint,
                    "actualFingerprint": memoized_model_fingerprint,
                },
            )
    normalized_messages = list(ledger_messages)
    events = _history_events_memoized(normalized_messages, session_id=session_id)
    if recent_message_limit is None:
        recent_start_index = 0
    else:
        bounded_recent_limit = max(1, min(int(recent_message_limit or DEFAULT_RECENT_MESSAGE_LIMIT), 40))
        recent_start_index = _provider_history_tail_start_index(
            normalized_messages,
            message_limit=bounded_recent_limit,
        )
    recent_raw_messages = normalized_messages[recent_start_index:]
    checkpoint = latest_checkpoint(events)
    ledger_checkpoint = latest_context_compression_checkpoint(ledger_replay_events)
    retrieved_list = list(retrieved_events or [])
    retrieved_messages = [_event_seed_message(event) for event in retrieved_list]
    # DeepSeek-style automatic prefix caches match request bytes from the head.
    # A checkpoint summary at the head of the assembled history invalidates the
    # whole cached prefix whenever a new checkpoint lands, so checkpoint
    # messages ride at the conversation tail instead: the assembled prefix
    # stays byte-stable across re-checkpointing and a new checkpoint only
    # appends (ZCode-style compact-boundary at the tail).
    recent_messages, tail_checkpoint_messages = _split_history_checkpoint_messages(recent_raw_messages)
    if checkpoint is not None and 0 <= checkpoint.message_index < recent_start_index:
        rescued_checkpoint_message = normalized_messages[checkpoint.message_index]
        if isinstance(rescued_checkpoint_message, dict):
            tail_checkpoint_messages = [rescued_checkpoint_message, *tail_checkpoint_messages]
    history_messages = [
        message
        for message in [*retrieved_messages, *recent_messages, *tail_checkpoint_messages]
        if message
    ]
    replacement_state = empty_tool_result_replacement_state(char_limit=tool_result_replacement_char_limit)
    if replace_large_tool_results_for_compression:
        # Memoized deterministic replacement pass: the assembled history list
        # is identity-stable across memoized upstream stages, so an unchanged
        # round reuses the cached (list, state) pair. The state is cloned on
        # reuse because the sticky overlay below appends restoration entries
        # to it in place; the cached copy must stay pristine.
        replace_scope = (
            "replace_large_tool_results",
            session_id,
            tool_result_replacement_char_limit,
        )
        replace_entry = _ASSEMBLY_MEMO.entry(replace_scope)
        if (
            replace_entry is not None
            and len(history_messages) == len(replace_entry.items)
            and all(history_messages[i] is kept for i, kept in enumerate(replace_entry.items))
        ):
            history_messages, replacement_state = replace_entry.value
            replacement_state = _clone_overlay_state(replacement_state)
        else:
            pre_replace_messages = history_messages
            history_messages, replacement_state = replace_tool_results_for_compression(
                history_messages,
                char_limit=tool_result_replacement_char_limit,
                session_id=session_id,
            )
            _ASSEMBLY_MEMO.store(
                replace_scope,
                pre_replace_messages,
                (history_messages, replacement_state),
            )
    # Sticky form locks: a tool result that already entered an assembled
    # output in a projected (placeholder) form keeps that exact form even
    # when this round's derivation no longer selects it, so previously sent
    # prefix bytes stay stable for DeepSeek-style exact-match prefix caches.
    # The overlay rebuilds the projection from the original content with the
    # locked parameters, so the replayed bytes match what was sent before.
    # The overlay memo rides on the assembled history list identity plus the
    # lock-index object identity (the lock memo above reuses one object while
    # the ledger only appends), so unchanged windows replay from cache and
    # grown windows only project the appended tail.
    history_messages, replacement_state = _sticky_overlay_memoized(
        ("sticky_tool_result_replacements", session_id, tool_result_replacement_char_limit),
        history_messages,
        overlay=apply_sticky_tool_result_replacements,
        projection_locks=projection_locks if projection_locks.has_mode(LOCK_MODE_REPLACEMENT) else None,
        session_id=session_id,
        state=replacement_state,
    )
    micro_state = empty_micro_compact_state()
    if micro_compact_old_tool_results:
        # Read-time micro-compaction tier: clear old whitelisted tool results
        # into reference+preview placeholders without touching the ledger. The
        # memo scope rides on the assembled history list identity; any ledger
        # change rebuilds the list contents and misses on purpose. A sticky
        # replacement restore rewrites middle items without moving the list
        # ends, so the identity memo cannot see it: skip the memo read for
        # that round (the fresh result is stored back instead). The projection
        # parameters ride in the scope so a parameter change can never reuse a
        # stale projection.
        memo_read_enabled = not replacement_state.get("stickyRestored")
        micro_memo_scope = (
            session_id,
            micro_compact_keep_recent_groups,
            micro_compact_min_savings_tokens,
            tuple(micro_compact_tool_whitelist or ()),
        )
        memoized_micro = _MISS
        if memo_read_enabled:
            memoized_micro = _ASSEMBLY_MEMO.lookup(
                ("micro_compact_projection", *micro_memo_scope),
                history_messages,
            )
        if memoized_micro is _MISS:
            memoized_micro = apply_micro_compact_projection(
                history_messages,
                session_id=session_id,
                keep_recent_groups=micro_compact_keep_recent_groups,
                min_savings_tokens=micro_compact_min_savings_tokens,
                tool_whitelist=micro_compact_tool_whitelist,
            )
            _ASSEMBLY_MEMO.store(
                ("micro_compact_projection", *micro_memo_scope),
                history_messages,
                memoized_micro,
            )
        history_messages, micro_state = memoized_micro
    history_messages, micro_state = _sticky_overlay_memoized(
        (
            "sticky_micro_compact_projection",
            session_id,
        ),
        history_messages,
        overlay=apply_sticky_micro_compact_projection,
        projection_locks=projection_locks if projection_locks.has_mode(LOCK_MODE_MICRO_COMPACT) else None,
        session_id=session_id,
        state=micro_state,
    )
    history_compaction_state = empty_history_seed_compaction_state(profile=history_seed_profile)
    if str(history_seed_profile or "").strip().lower() == "agent_inbox":
        agent_inbox_tool_result_limit = min(
            max(1, int(tool_result_replacement_char_limit or AGENT_INBOX_TOOL_RESULT_CHAR_LIMIT)),
            AGENT_INBOX_TOOL_RESULT_CHAR_LIMIT,
        )
        history_messages, history_compaction_state = compact_agent_inbox_history_seed_messages(
            history_messages,
            tool_result_char_limit=agent_inbox_tool_result_limit,
            assistant_message_char_limit=AGENT_INBOX_ASSISTANT_MESSAGE_CHAR_LIMIT,
            projection_locks=projection_locks if projection_locks.has_mode(LOCK_MODE_AGENT_INBOX) else None,
        )
    # Leading context-seed promotion rebuilds every message dict; memoizing it
    # keeps the post-promotion list identity-stable so the dynamic-context
    # hash below can hit on unchanged rounds instead of re-hashing O(n).
    promote_scope = ("promote_leading_context", session_id)
    promote_entry = _ASSEMBLY_MEMO.entry(promote_scope)
    if (
        promote_entry is not None
        and len(history_messages) == len(promote_entry.items)
        and all(history_messages[i] is kept for i, kept in enumerate(promote_entry.items))
    ):
        history_messages = promote_entry.value
    else:
        pre_promote_messages = history_messages
        history_messages = _promote_leading_context_assistant_messages(history_messages)
        _ASSEMBLY_MEMO.store(promote_scope, pre_promote_messages, history_messages)
    included_event_ids = _included_event_ids(
        events,
        recent_start_index=recent_start_index,
        checkpoint=checkpoint,
        retrieved_events=retrieved_list,
    )
    omitted_event_count = max(0, len(events) - len(set(included_event_ids)))
    segments = [
        ContextSegment(
            key="stable_prefix",
            label="stable prefix",
            source="agent_protocol",
            item_count=1,
            chars=0,
            cache_policy="prefix_candidate",
        ),
        ContextSegment(
            key="history_tail",
            label="history tail",
            source="conversation_ledger",
            item_count=len(recent_messages),
            chars=_message_chars(recent_messages),
            cache_policy="dynamic",
        ),
        ContextSegment(
            key="conversation_ledger",
            label="conversation ledger replay",
            source="conversation_ledger",
            item_count=len(ledger_replay_events),
            chars=_message_chars(ledger_messages),
            cache_policy="dynamic",
        ),
    ]
    if ledger_checkpoint is not None:
        segments.append(
            ContextSegment(
                key="context_compression_checkpoint",
                label="context compression checkpoint",
                source="conversation_ledger",
                item_count=1,
                chars=len(str((ledger_checkpoint.payload or {}).get("summary") or "")),
                cache_policy="dynamic",
            )
        )
    if checkpoint is not None:
        segments.append(
            ContextSegment(
                key="history_checkpoint",
                label="history checkpoint",
                source="conversation_ledger",
                item_count=1,
                chars=len(checkpoint.content),
                cache_policy="dynamic",
            )
        )
    if retrieved_list:
        segments.append(
            ContextSegment(
                key="retrieved_history",
                label="retrieved history",
                source="history_lookup_tools",
                item_count=len(retrieved_list),
                chars=sum(len(event.content) + len(event.summary) for event in retrieved_list),
                cache_policy="dynamic",
            )
        )
    memoized_dynamic_hash = _ASSEMBLY_MEMO.lookup(
        ("dynamic_context_hash", session_id),
        history_messages,
    )
    if memoized_dynamic_hash is _MISS:
        memoized_dynamic_hash = _hash_messages(history_messages)
        _ASSEMBLY_MEMO.store(
            ("dynamic_context_hash", session_id),
            history_messages,
            memoized_dynamic_hash,
        )
    return ContextAssemblyResult(
        history_messages=history_messages,
        events=events,
        included_event_ids=included_event_ids,
        omitted_event_count=omitted_event_count,
        checkpoint_event_id=(
            ledger_checkpoint.event_id
            if ledger_checkpoint is not None
            else checkpoint.event_id
            if checkpoint
            else ""
        ),
        segments=segments,
        cacheable_prefix_hash=_hash_text("agent_protocol:v1"),
        dynamic_context_hash=memoized_dynamic_hash,
        tool_result_replacement_state=replacement_state,
        micro_compact_state=micro_state,
        history_seed_compaction_state=history_compaction_state,
    )


def empty_history_seed_compaction_state(*, profile: str = "full") -> dict[str, Any]:
    return {
        "profile": str(profile or "full").strip() or "full",
        "compactedMessageCount": 0,
        "omittedToolFailureCount": 0,
        "trimmedMessageCount": 0,
        "originalChars": 0,
        "compactedChars": 0,
        "projectionEntries": [],
    }


# Bounded per-entry trim records carried in the agent-inbox compaction state;
# they feed the sticky projection-lock persistence and stay small even for
# long histories.
_MAX_INBOX_PROJECTION_ENTRIES = 128


def compact_agent_inbox_history_seed_messages(
    messages: Iterable[dict[str, Any]],
    *,
    tool_result_char_limit: int = AGENT_INBOX_TOOL_RESULT_CHAR_LIMIT,
    assistant_message_char_limit: int = AGENT_INBOX_ASSISTANT_MESSAGE_CHAR_LIMIT,
    projection_locks: ProjectionLockIndex | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Keep private-message wakeups focused without replaying bulky old evidence."""

    state = empty_history_seed_compaction_state(profile="agent_inbox")
    compacted_messages: list[dict[str, Any]] = []
    locks = projection_locks if isinstance(projection_locks, ProjectionLockIndex) else None
    bounded_tool_limit = max(240, min(int(tool_result_char_limit or AGENT_INBOX_TOOL_RESULT_CHAR_LIMIT), 2_000))
    bounded_assistant_limit = max(480, min(int(assistant_message_char_limit or AGENT_INBOX_ASSISTANT_MESSAGE_CHAR_LIMIT), 4_000))

    def _locked_limit(kind: str, content: str, current_limit: int, tool_call_id: str = "") -> int:
        """Replay a previously sent trim with its locked limit (byte-stable)."""

        if locks is None or not locks.has_mode(LOCK_MODE_AGENT_INBOX):
            return current_limit
        record = locks.lookup(
            mode=LOCK_MODE_AGENT_INBOX,
            tool_call_id=tool_call_id,
            sha256=content_digest(content),
        )
        if record is None or record.kind != kind or record.char_limit <= 0:
            return current_limit
        return record.char_limit

    def _remember_projection_entry(kind: str, *, original: str, char_limit: int, tool_call_id: str = "") -> None:
        if len(state["projectionEntries"]) >= _MAX_INBOX_PROJECTION_ENTRIES:
            return
        state["projectionEntries"].append(
            {
                "kind": kind,
                "toolCallId": tool_call_id,
                "sha256": content_digest(original),
                "charLimit": int(char_limit),
                "originalChars": len(original),
            }
        )

    for raw in list(messages or []):
        if not isinstance(raw, dict):
            continue
        message = dict(raw)
        content = str(message.get("content") or "")
        original_chars = len(content)
        if _looks_like_historical_source_collection_stage_task_message(message):
            compacted_content = _historical_source_collection_stage_task_summary(message)
            if compacted_content != content:
                message["content"] = compacted_content
                state["compactedMessageCount"] += 1
                state["trimmedMessageCount"] += 1
                state["originalChars"] += original_chars
                state["compactedChars"] += len(compacted_content)
            compacted_messages.append(message)
            continue
        role = str(message.get("role") or "").strip().lower()
        if role == "tool" or _looks_like_historical_tool_result(content):
            tool_call_id = _inbox_message_tool_call_id(message)
            effective_tool_limit = _locked_limit(
                LOCK_AGENT_INBOX_KIND_TOOL,
                content,
                bounded_tool_limit,
                tool_call_id=tool_call_id,
            )
            compacted_content, omitted_failure = _compact_historical_tool_result(
                content,
                char_limit=effective_tool_limit,
            )
            if compacted_content != content:
                message["content"] = compacted_content
                state["compactedMessageCount"] += 1
                state["originalChars"] += original_chars
                state["compactedChars"] += len(compacted_content)
                if omitted_failure:
                    state["omittedToolFailureCount"] += 1
                else:
                    # Limit-dependent trims are lockable projection forms;
                    # failure summaries are limit-free and deterministic.
                    _remember_projection_entry(
                        LOCK_AGENT_INBOX_KIND_TOOL,
                        original=content,
                        char_limit=effective_tool_limit,
                        tool_call_id=tool_call_id,
                    )
            compacted_messages.append(message)
            continue
        # Checkpoint summaries are the compressed history itself, not old
        # evidence noise: keep them whole even in the bounded agent-inbox
        # profile (they now sit at the tail as assistant messages instead of
        # being promoted to a leading system role).
        if role == "assistant" and not _is_history_checkpoint_message(message):
            effective_assistant_limit = _locked_limit(
                LOCK_AGENT_INBOX_KIND_ASSISTANT,
                content,
                bounded_assistant_limit,
            )
            if original_chars > effective_assistant_limit:
                compacted_content = _trim_history_text(
                    content,
                    char_limit=effective_assistant_limit,
                    marker="历史 assistant 回复已压缩，仅保留前段摘要；如需全文请查询会话历史。",
                )
                message["content"] = compacted_content
                state["compactedMessageCount"] += 1
                state["trimmedMessageCount"] += 1
                state["originalChars"] += original_chars
                state["compactedChars"] += len(compacted_content)
                _remember_projection_entry(
                    LOCK_AGENT_INBOX_KIND_ASSISTANT,
                    original=content,
                    char_limit=effective_assistant_limit,
                )
        compacted_messages.append(message)
    return compacted_messages, state


def _inbox_message_tool_call_id(message: dict[str, Any]) -> str:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    return str(
        message.get("tool_call_id")
        or message.get("toolCallId")
        or metadata.get("toolCallId")
        or metadata.get("tool_call_id")
        or ""
    ).strip()


def _looks_like_historical_source_collection_stage_task_message(message: dict[str, Any]) -> bool:
    if str(message.get("role") or "").strip().lower() != "user":
        return False
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    kind = str(metadata.get("kind") or "").strip()
    if kind == "source_collection_stage_session_task":
        return True
    if str(metadata.get("sourceCollectionStageTaskId") or metadata.get("source_collection_stage_task_id") or "").strip():
        return True
    return str(message.get("content") or "").lstrip().startswith("## 资料搜集阶段任务：")


def _historical_source_collection_stage_task_summary(message: dict[str, Any]) -> str:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    content = str(message.get("content") or "").strip()
    title = next((line.strip("# ").strip() for line in content.splitlines() if line.strip()), "资料搜集阶段任务")
    task_id = str(metadata.get("sourceCollectionStageTaskId") or metadata.get("source_collection_stage_task_id") or "").strip()
    run_id = str(metadata.get("runId") or metadata.get("run_id") or "").strip()
    stage_id = str(metadata.get("stageId") or metadata.get("stage_id") or "").strip()
    agent_role = str(metadata.get("agentRole") or metadata.get("agent_role") or "").strip()
    facts = [
        f"任务: {title}" if title else "",
        f"stageTaskId: {task_id}" if task_id else "",
        f"runId: {run_id}" if run_id else "",
        f"stageId: {stage_id}" if stage_id else "",
        f"agentRole: {agent_role}" if agent_role else "",
    ]
    return "\n".join(
        part
        for part in [
            "历史阶段任务启动消息已压缩；当前轮请以本轮任务消息和 source_collection_context_tool 返回的上下文为准。",
            *facts,
            "旧任务完整启动提示仍保存在会话历史中。",
        ]
        if part
    )
def _looks_like_historical_tool_result(content: str) -> bool:
    text = str(content or "").lstrip()
    return any(
        text.startswith(marker)
        for marker in ("历史工具调用:", "历史工具结果:", "历史工具证据:")
    )


def _compact_historical_tool_result(content: str, *, char_limit: int) -> tuple[str, bool]:
    text = str(content or "").strip()
    lowered = text.lower()
    status = _historical_tool_result_status(text)
    is_failure = status in {"failed", "error", "blocked", "timeout"} or any(
        marker in lowered
        for marker in (
            "http 403",
            "http 404",
            "请求超时",
            "timeout",
            "[错误]",
            "status: failed",
            "status: error",
            "status: blocked",
        )
    )
    if is_failure:
        return _historical_tool_failure_summary(text, status=status), True
    if len(text) <= char_limit:
        return text, False
    return _trim_history_text(
        text,
        char_limit=char_limit,
        marker="历史工具结果已压缩，原始结果仍保存在会话历史/工具日志中。",
    ), False


# Keep failure-summary marker expected by agent-inbox compaction tests.


def _historical_tool_result_status(content: str) -> str:
    for line in str(content or "").splitlines()[:6]:
        normalized = line.strip()
        if normalized.lower().startswith("status:"):
            return normalized.split(":", 1)[1].strip().lower()
    return ""


def _historical_tool_failure_summary(content: str, *, status: str = "") -> str:
    lines = [line.strip() for line in str(content or "").splitlines() if line.strip()]
    header = lines[0] if lines else "历史工具结果"
    status_line = f"status: {status or 'failed'}"
    detail = ""
    for line in lines[1:]:
        lowered = line.lower()
        if "http 403" in lowered or "http 404" in lowered or "请求超时" in line or "timeout" in lowered or line.startswith("[错误]"):
            detail = line
            break
    if not detail:
        detail = next((line for line in lines[1:] if line.lower().startswith("status:")), "")
    return "\n".join(
        part
        for part in (
            header,
            status_line,
            f"压缩原因: 历史私信上下文不重放失败工具正文，避免旧 403/404/timeout 噪声放大当前模型输入。",
            f"失败摘要: {detail}" if detail else "",
            "详情位置: 会话历史和工具日志仍保留原始结果。",
        )
        if part
    )


def _trim_history_text(content: str, *, char_limit: int, marker: str) -> str:
    text = str(content or "").strip()
    bounded_limit = max(120, int(char_limit or 0))
    if len(text) <= bounded_limit:
        return text
    head_limit = max(80, bounded_limit - len(marker) - 64)
    head = text[:head_limit].rstrip()
    return f"{head}\n\n[{marker} 原始字符数: {len(text)}]"


def _historical_ledger_events(
    events: list[ConversationLedgerEvent],
    *,
    current_turn_id: str = "",
) -> list[ConversationLedgerEvent]:
    # Current-turn branch markers still select the historical path. Resolve
    # them before excluding the in-flight turn, as canonical replay does.
    events = fold_active_events(events)
    normalized_current_turn_id = str(current_turn_id or "").strip()
    if not normalized_current_turn_id:
        return list(events or [])
    return [
        event
        for event in list(events or [])
        if str(getattr(event, "turn_id", "") or "").strip() != normalized_current_turn_id
    ]


def _provider_history_tail_start_index(
    messages: list[dict[str, Any]],
    *,
    message_limit: int,
) -> int:
    """Select a bounded tail without splitting an assistant/tool chain."""

    atoms: list[tuple[int, int]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        call_ids = _provider_message_tool_call_ids(message)
        if call_ids:
            end_index = index + 1
            seen_ids: list[str] = []
            while end_index < len(messages):
                result = messages[end_index]
                if str(result.get("role") or "").strip().lower() != "tool":
                    break
                tool_call_id = str(result.get("tool_call_id") or result.get("toolCallId") or "").strip()
                if tool_call_id not in call_ids or tool_call_id in seen_ids:
                    break
                seen_ids.append(tool_call_id)
                end_index += 1
            if set(seen_ids) == set(call_ids):
                atoms.append((index, end_index))
                index = end_index
                continue
        atoms.append((index, index + 1))
        index += 1

    selected_count = 0
    start_index = len(messages)
    bounded_limit = max(1, int(message_limit or 1))
    for atom_start, atom_end in reversed(atoms):
        atom_size = atom_end - atom_start
        if selected_count + atom_size > bounded_limit:
            break
        start_index = atom_start
        selected_count += atom_size
        if selected_count == bounded_limit:
            break
    return start_index


def _provider_message_tool_call_ids(message: dict[str, Any]) -> list[str]:
    if not isinstance(message, dict) or str(message.get("role") or "").strip().lower() != "assistant":
        return []
    return [
        str(call.get("id") or call.get("tool_call_id") or call.get("toolCallId") or "").strip()
        for call in list(message.get("tool_calls") or message.get("toolCalls") or [])
        if isinstance(call, dict)
        and str(call.get("id") or call.get("tool_call_id") or call.get("toolCallId") or "").strip()
    ]


def _is_context_seed_assistant_message(message: dict[str, Any]) -> bool:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    return str(metadata.get("kind") or "").strip() in {
        "compaction_checkpoint",
        "context_compression_attempt",
        "historical_orphan_tool_result",
        "historical_tool_context",
        "history_checkpoint_seed",
        "retrieved_history_seed",
    }


def _promote_leading_context_assistant_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    promoted: list[dict[str, Any]] = []
    in_leading_context = True
    for raw in list(messages or []):
        if not isinstance(raw, dict):
            continue
        message = dict(raw)
        role = str(message.get("role") or "").strip().lower()
        if in_leading_context and role == "assistant" and _is_context_seed_assistant_message(message):
            metadata = dict(message.get("metadata") or {})
            metadata["promotedFromRole"] = "assistant"
            metadata["promotionReason"] = "provider_safe_history_tail_start"
            message["metadata"] = metadata
            message["role"] = "system"
            promoted.append(message)
            continue
        in_leading_context = False
        promoted.append(message)
    return promoted


CHECKPOINT_MESSAGE_KINDS = frozenset({"checkpoint", "compaction_checkpoint"})


def _is_history_checkpoint_message(message: dict[str, Any]) -> bool:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    return str(metadata.get("kind") or "").strip() in CHECKPOINT_MESSAGE_KINDS


def _split_history_checkpoint_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split replayed checkpoint messages out of the conversation body.

    Automatic prefix caches (DeepSeek-style, 64-token blocks) match request
    bytes from the head.  A checkpoint summary at the head invalidates the
    whole cached prefix each time a new checkpoint lands (full re-prefill);
    keeping checkpoint messages at the conversation tail leaves the assembled
    prefix byte-stable so a new checkpoint only appends fresh bytes.  The
    checkpoint message itself keeps its replayed role/content untouched —
    only its position moves.
    """

    body: list[dict[str, Any]] = []
    checkpoints: list[dict[str, Any]] = []
    for raw in list(messages or []):
        if isinstance(raw, dict) and _is_history_checkpoint_message(raw):
            checkpoints.append(raw)
            continue
        body.append(raw)
    return body, checkpoints


def _event_seed_message(event: HistoryEvent) -> dict[str, Any]:
    label = event.tool_name or event.event_type
    content = event.content or event.summary
    if event.event_type in {EVENT_TOOL_CALL, EVENT_TOOL_RESULT}:
        content = f"历史工具证据：{label}\n状态：{event.status or 'unknown'}\n{content}".strip()
    return {
        "role": "assistant",
        "content": content,
        "metadata": {
            "kind": "retrieved_history_seed",
            "eventId": event.event_id,
            "eventType": event.event_type,
        },
    }


def _included_event_ids(
    events: list[HistoryEvent],
    *,
    recent_start_index: int,
    checkpoint: HistoryEvent | None,
    retrieved_events: Iterable[HistoryEvent] | None,
) -> list[str]:
    included: list[str] = []
    for event in events:
        if event.message_index >= recent_start_index:
            included.append(event.event_id)
    if checkpoint is not None:
        included.append(checkpoint.event_id)
    for event in list(retrieved_events or []):
        included.append(event.event_id)
    return list(dict.fromkeys(included))


def _message_chars(messages: Iterable[dict[str, Any]]) -> int:
    total = 0
    for message in list(messages or []):
        total += len(str(message.get("content") or ""))
        for tool in list(message.get("toolCalls") or message.get("tool_calls") or []):
            if isinstance(tool, dict):
                total += len(str(tool.get("name") or tool.get("toolName") or ""))
                total += len(str(tool.get("result") or tool.get("summary") or tool.get("resultPreview") or tool.get("error") or ""))
    return total


def _hash_messages(messages: Iterable[dict[str, Any]]) -> str:
    parts = []
    for message in list(messages or []):
        parts.append(str(message.get("role") or ""))
        parts.append(str(message.get("content") or ""))
        parts.append(str(message.get("tool_call_id") or message.get("toolCallId") or ""))
        parts.append(str(message.get("metadata") or ""))
        for tool in list(message.get("toolCalls") or message.get("tool_calls") or message.get("tools") or []):
            if isinstance(tool, dict):
                function_block = tool.get("function") if isinstance(tool.get("function"), dict) else {}
                parts.append(str(tool.get("id") or tool.get("tool_call_id") or tool.get("toolCallId") or ""))
                parts.append(str(tool.get("name") or tool.get("toolName") or ""))
                parts.append(str(function_block.get("name") or ""))
                parts.append(str(tool.get("arguments") or tool.get("args") or function_block.get("arguments") or ""))
                parts.append(str(tool.get("status") or tool.get("semanticStatus") or ""))
                parts.append(str(tool.get("result") or tool.get("resultPreview") or tool.get("error") or ""))
    return _hash_text("\n".join(parts))


def _hash_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8", errors="replace")).hexdigest()[:16]


__all__ = [
    "ContextAssemblyResult",
    "ContextSegment",
    "DEFAULT_RECENT_MESSAGE_LIMIT",
    "assemble_conversation_context",
]
