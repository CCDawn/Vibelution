# -*- coding: utf-8 -*-
"""Sticky projection locks: keep sent bytes of compressed tool results stable.

DeepSeek-style provider prefix caches match request bytes exactly. The context
assembler re-derives three read-time compression projections from the raw
ledger every turn (large-tool-result replacement, micro-compaction, agent-inbox
bounded truncation), so a tool result that was sent verbatim last turn can come
back as a placeholder (or the reverse) whenever the derivation inputs move
(keep-recent window slide, min-savings rollback after a checkpoint shrinks the
replay, whitelist/limit config changes). Any such flip changes bytes in the
middle of the request and invalidates the whole cached prefix.

This module adds one append-only lock layer on top, without touching the
projection builders themselves:

- Once a tool result has entered an assembled output in a projected form, the
  form is locked. Later assemblies replay the exact same bytes, re-derived
  deterministically from the original ledger content (placeholders and trims
  are pure functions of content + identity + locked limits), even when the
  current derivation rules would no longer project the entry.
- Entries never projected before keep following the current rules, so the
  projected set only grows ("只对新达到条件的条目新增投影"). Growth is
  anchored at the youngest qualifying entry, near the conversation tail, so a
  growth step only re-prefills the recent window, never the whole prefix.
- Already-projected entries never regress to verbatim: rollback, config flips,
  branch rebases, and restarts all replay the locked form.

Persistence is a new out-of-band ledger event (``tool_result_projection_lock``)
appended after an assembly whose projection produced forms with no prior lock.
The ledger stays the single authority: lock events share its lifecycle, its
append-only contract, and its restart semantics; no existing event is ever
rewritten or deleted, and no side-car file exists. The events are
``visible_in_model=False`` out-of-band markers: they never enter model replay,
visible projections, or turn state.

Lock identity is content addressed: ``(toolCallId, sha256(original content))``
with a digest-only fallback for entries without a stable call id. The earliest
record wins; later records for the same key are ignored, which makes the lock
set monotone under duplicate appends.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .turn_journal import (
    TurnJournalEvent,
    append_turn_event,
)


EVENT_TOOL_RESULT_PROJECTION_LOCK = "tool_result_projection_lock"
PROJECTION_LOCK_SCHEMA = "tool_result_projection_lock.v1"

LOCK_MODE_REPLACEMENT = "compression_only"
LOCK_MODE_MICRO_COMPACT = "micro_compact"
LOCK_MODE_AGENT_INBOX = "agent_inbox_truncation"

# Agent-inbox trim kinds that depend on a char limit and therefore need the
# limit locked alongside the form. Failure summaries and stage-task summaries
# are limit-free pure functions of the content and need no lock.
LOCK_AGENT_INBOX_KIND_TOOL = "tool_trim"
LOCK_AGENT_INBOX_KIND_ASSISTANT = "assistant_trim"

_MAX_DECISIONS_PER_EVENT = 256


@dataclass(frozen=True)
class ProjectionLockRecord:
    """One locked projection form for a single tool-result entry."""

    mode: str
    sha256: str
    tool_call_id: str = ""
    tool_name: str = ""
    reference: str = ""
    original_chars: int = 0
    preview_limit: int = 0
    char_limit: int = 0
    kind: str = ""

    def decision_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "toolCallId": self.tool_call_id,
            "toolName": self.tool_name,
            "sha256": self.sha256,
            "reference": self.reference,
            "originalChars": self.original_chars,
            "previewLimit": self.preview_limit,
            "charLimit": self.char_limit,
            "kind": self.kind,
        }


class ProjectionLockIndex:
    """First-wins lookup index over persisted projection lock decisions."""

    __slots__ = ("_by_call", "_by_digest", "_modes")

    def __init__(self) -> None:
        self._by_call: dict[tuple[str, str], ProjectionLockRecord] = {}
        self._by_digest: dict[str, ProjectionLockRecord] = {}
        self._modes: set[str] = set()

    def __bool__(self) -> bool:
        return bool(self._by_call or self._by_digest)

    def has_mode(self, mode: str) -> bool:
        return str(mode or "").strip() in self._modes

    def add(self, record: ProjectionLockRecord) -> None:
        normalized_mode = str(record.mode or "").strip()
        if not normalized_mode or not str(record.sha256 or "").strip():
            return
        digest = str(record.sha256 or "").strip()
        call_id = str(record.tool_call_id or "").strip()
        if call_id:
            key = (call_id, digest)
            if key not in self._by_call:
                self._by_call[key] = record
        elif digest not in self._by_digest:
            # Only id-less records occupy the digest-only slot, so entries with
            # stable call ids can never be shadowed by an unrelated same-size
            # content digest.
            self._by_digest[digest] = record
        self._modes.add(normalized_mode)

    def lookup(
        self,
        *,
        mode: str,
        tool_call_id: str = "",
        sha256: str = "",
    ) -> ProjectionLockRecord | None:
        normalized_mode = str(mode or "").strip()
        digest = str(sha256 or "").strip()
        if not normalized_mode or not digest:
            return None
        call_id = str(tool_call_id or "").strip()
        if call_id:
            record = self._by_call.get((call_id, digest))
            if record is not None and record.mode == normalized_mode:
                return record
        record = self._by_digest.get(digest)
        if record is not None and record.mode == normalized_mode:
            return record
        return None


def content_digest(content: Any) -> str:
    return hashlib.sha256(str(content or "").encode("utf-8", errors="replace")).hexdigest()


def _coerce_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _lock_record_from_decision(decision: dict[str, Any]) -> ProjectionLockRecord | None:
    if not isinstance(decision, dict):
        return None
    mode = str(decision.get("mode") or "").strip()
    sha256 = str(decision.get("sha256") or "").strip()
    if not mode or not sha256:
        return None
    return ProjectionLockRecord(
        mode=mode,
        sha256=sha256,
        tool_call_id=str(decision.get("toolCallId") or "").strip(),
        tool_name=str(decision.get("toolName") or "").strip(),
        reference=str(decision.get("reference") or "").strip(),
        original_chars=_coerce_int(decision.get("originalChars")),
        preview_limit=_coerce_int(decision.get("previewLimit")),
        char_limit=_coerce_int(decision.get("charLimit")),
        kind=str(decision.get("kind") or "").strip(),
    )


def projection_locks_from_ledger_events(
    events: Iterable[TurnJournalEvent] | None,
) -> ProjectionLockIndex:
    """Build the first-wins lock index from a conversation event stream."""

    index = ProjectionLockIndex()
    for event in list(events or []):
        if getattr(event, "event_type", "") != EVENT_TOOL_RESULT_PROJECTION_LOCK:
            continue
        payload = event.payload if isinstance(event.payload, dict) else {}
        for decision in list(payload.get("decisions") or []):
            record = _lock_record_from_decision(decision)
            if record is not None:
                index.add(record)
    return index


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

# In-process duplicate guard: the assembly that just produced a form cannot see
# its own lock event yet (the caller loaded the ledger before assembling), so
# repeated assemblies inside one turn must not append the same decisions again.
_PERSISTED_LOCKS_GUARD = threading.Lock()
_PERSISTED_LOCK_KEYS: dict[tuple[str, str], set[tuple[str, str, str]]] = {}
_PERSISTED_LOCK_KEYS_MAX_SESSIONS = 64


def _remember_persisted_lock_keys(
    session_id: str,
    turn_id: str,
    keys: set[tuple[str, str, str]],
) -> None:
    if not keys:
        return
    with _PERSISTED_LOCKS_GUARD:
        _PERSISTED_LOCK_KEYS[(session_id, turn_id)] = keys
        while len(_PERSISTED_LOCK_KEYS) > _PERSISTED_LOCK_KEYS_MAX_SESSIONS:
            oldest = next(iter(_PERSISTED_LOCK_KEYS))
            _PERSISTED_LOCK_KEYS.pop(oldest, None)


def _known_persisted_lock_keys(session_id: str, turn_id: str) -> set[tuple[str, str, str]]:
    with _PERSISTED_LOCKS_GUARD:
        known = set(_PERSISTED_LOCK_KEYS.get((session_id, turn_id), set()))
    # Keys persisted for other turns of this session may still be invisible to
    # the caller (e.g. ledger_events was not passed); merge every remembered
    # turn of the same session so the dedupe stays conservative.
    with _PERSISTED_LOCKS_GUARD:
        for (known_session, _turn), keys in _PERSISTED_LOCK_KEYS.items():
            if known_session == session_id:
                known |= keys
    return known


def collect_projection_lock_decisions(
    *,
    tool_result_replacement_state: dict[str, Any] | None = None,
    micro_compact_state: dict[str, Any] | None = None,
    history_seed_compaction_state: dict[str, Any] | None = None,
) -> list[ProjectionLockRecord]:
    """Extract lockable projection decisions from one assembly result's states."""

    records: list[ProjectionLockRecord] = []

    replacement_state = tool_result_replacement_state if isinstance(tool_result_replacement_state, dict) else {}
    replacement_char_limit = _coerce_int(replacement_state.get("charLimit"))
    for entry in list(replacement_state.get("replacements") or []):
        if not isinstance(entry, dict):
            continue
        sha256 = str(entry.get("sha256") or "").strip()
        if not sha256:
            continue
        records.append(
            ProjectionLockRecord(
                mode=LOCK_MODE_REPLACEMENT,
                sha256=sha256,
                tool_call_id=str(entry.get("toolCallId") or "").strip(),
                tool_name=str(entry.get("toolName") or "").strip(),
                reference=str(entry.get("reference") or "").strip(),
                original_chars=_coerce_int(entry.get("originalChars")),
                preview_limit=min(800, replacement_char_limit) if replacement_char_limit else 0,
                char_limit=replacement_char_limit,
            )
        )

    micro_state = micro_compact_state if isinstance(micro_compact_state, dict) else {}
    for entry in list(micro_state.get("replacements") or []):
        if not isinstance(entry, dict):
            continue
        sha256 = str(entry.get("sha256") or "").strip()
        if not sha256:
            continue
        records.append(
            ProjectionLockRecord(
                mode=LOCK_MODE_MICRO_COMPACT,
                sha256=sha256,
                tool_call_id=str(entry.get("toolCallId") or "").strip(),
                tool_name=str(entry.get("toolName") or "").strip(),
                reference=str(entry.get("reference") or "").strip(),
                original_chars=_coerce_int(entry.get("originalChars")),
                preview_limit=_micro_compact_preview_limit(micro_state),
            )
        )

    inbox_state = history_seed_compaction_state if isinstance(history_seed_compaction_state, dict) else {}
    for entry in list(inbox_state.get("projectionEntries") or []):
        if not isinstance(entry, dict):
            continue
        sha256 = str(entry.get("sha256") or "").strip()
        kind = str(entry.get("kind") or "").strip()
        if not sha256 or kind not in {LOCK_AGENT_INBOX_KIND_TOOL, LOCK_AGENT_INBOX_KIND_ASSISTANT}:
            continue
        records.append(
            ProjectionLockRecord(
                mode=LOCK_MODE_AGENT_INBOX,
                sha256=sha256,
                tool_call_id=str(entry.get("toolCallId") or "").strip(),
                original_chars=_coerce_int(entry.get("originalChars")),
                char_limit=_coerce_int(entry.get("charLimit")),
                kind=kind,
            )
        )
    return records


def _micro_compact_preview_limit(micro_state: dict[str, Any]) -> int:
    from .microcompact import DEFAULT_PREVIEW_CHAR_LIMIT

    return _coerce_int(micro_state.get("previewCharLimit")) or DEFAULT_PREVIEW_CHAR_LIMIT


def persist_assembly_projection_locks(
    project_root: Path,
    session_id: str,
    *,
    turn_id: str = "",
    ledger_events: Iterable[TurnJournalEvent] | None = None,
    tool_result_replacement_state: dict[str, Any] | None = None,
    micro_compact_state: dict[str, Any] | None = None,
    history_seed_compaction_state: dict[str, Any] | None = None,
) -> TurnJournalEvent | None:
    """Append one lock event for projection forms with no prior lock record.

    Purely additive: existing ledger events are never touched, the append is
    out-of-band (never model-visible), and a failure to persist never changes
    the already-computed assembly result. Returns the appended event or
    ``None`` when there was nothing new to lock.
    """

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    candidates = collect_projection_lock_decisions(
        tool_result_replacement_state=tool_result_replacement_state,
        micro_compact_state=micro_compact_state,
        history_seed_compaction_state=history_seed_compaction_state,
    )
    if not candidates:
        return None
    known_index = projection_locks_from_ledger_events(ledger_events)
    known_keys = _known_persisted_lock_keys(normalized_session_id, str(turn_id or "").strip())
    decisions: list[dict[str, Any]] = []
    new_keys: set[tuple[str, str, str]] = set()
    for record in candidates:
        key = (record.mode, record.tool_call_id, record.sha256)
        if key in new_keys or key in known_keys:
            continue
        if known_index.lookup(
            mode=record.mode,
            tool_call_id=record.tool_call_id,
            sha256=record.sha256,
        ) is not None:
            continue
        new_keys.add(key)
        decisions.append(record.decision_dict())
        if len(decisions) >= _MAX_DECISIONS_PER_EVENT:
            break
    if not decisions:
        return None
    event = append_turn_event(
        Path(project_root),
        normalized_session_id,
        str(turn_id or "").strip() or "projection-lock",
        EVENT_TOOL_RESULT_PROJECTION_LOCK,
        status="locked",
        payload={
            "schema": PROJECTION_LOCK_SCHEMA,
            "decisionCount": len(decisions),
            "decisions": decisions,
        },
        source="projection_stickiness",
        visible_in_model=False,
        projection_kind="projection_lock",
        source_kind="context_projection",
    )
    _remember_persisted_lock_keys(normalized_session_id, str(turn_id or "").strip(), new_keys)
    return event


__all__ = [
    "EVENT_TOOL_RESULT_PROJECTION_LOCK",
    "LOCK_AGENT_INBOX_KIND_ASSISTANT",
    "LOCK_AGENT_INBOX_KIND_TOOL",
    "LOCK_MODE_AGENT_INBOX",
    "LOCK_MODE_MICRO_COMPACT",
    "LOCK_MODE_REPLACEMENT",
    "PROJECTION_LOCK_SCHEMA",
    "ProjectionLockIndex",
    "ProjectionLockRecord",
    "collect_projection_lock_decisions",
    "content_digest",
    "persist_assembly_projection_locks",
    "projection_locks_from_ledger_events",
]
