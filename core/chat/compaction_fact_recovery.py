"""Recover lost legacy summary facts from their original journal sources.

This is a deterministic read projection. It neither rewrites checkpoints nor
creates a second transcript, and cannot derive user facts from model/tool text.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace

from tools.compression_summary_retention import (
    compose_retained_summary, explicit_user_facts, retained_user_facts,
)

from .turn_journal import EVENT_COMPACTION_CHECKPOINT, EVENT_USER_MESSAGE, TurnJournalEvent

MAX_RECOVERED_FACT_CHARS = 8_000
_CONSTRAINT = re.compile(
    r"约束|必须|不要|不得|禁止|不允许|只能|仅(?:限|允许|回答|输出|使用)|只(?:回答|输出|使用|读)|"
    r"只作为(?:历史)?素材|仅供参考|仅作(?:历史)?素材|"
    r"(?<![\w-])(?:must|never|only)(?![\w-])|\bdo\s+not\b", re.IGNORECASE,
)


def recoverable_user_statements(text: str) -> list[str]:
    """Keep explicit memory requests and constraints as quoted historical data."""
    direct, fenced, keep_value, memory_intro = [], False, False, False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(">") and not memory_intro:
            continue
        if stripped.startswith("```"):
            if not fenced:
                keep_value = memory_intro
            if keep_value:
                direct.append(line)
            fenced = not fenced
            if not fenced:
                memory_intro = False
            continue
        if fenced:
            if keep_value:
                direct.append(line)
            continue
        direct.append(line)
        if stripped:
            memory_intro = bool(explicit_user_facts(line) or _CONSTRAINT.search(line)) and stripped.endswith((":", "："))
    text = "\n".join(direct)
    statements = explicit_user_facts(text)
    statements.extend(explicit_user_facts(text, pattern=_CONSTRAINT))
    return list(dict.fromkeys(statements))


def _ordinary_source(event: TurnJournalEvent) -> bool:
    payload = event.payload or {}
    # Formal research/Child Session scopes retain their existing separate
    # contract. Never backfill an unscoped chat from a tagged sibling source.
    return not any(payload.get(key) for key in ("scope", "discussionScope", "scopeHash", "scopeBindingRequired"))


def _sources(checkpoint, by_id, events):
    pending, visited, sources = [checkpoint], set(), {}
    while pending:
        current = pending.pop()
        if current.event_id in visited:
            continue
        visited.add(current.event_id)
        payload = current.payload or {}
        ids = set()
        for key in ("coveredEventIds", "retiredEventIds"):
            values = payload.get(key)
            if isinstance(values, (list, tuple)):
                ids.update(value for value in values if isinstance(value, str) and value)
        try:
            start, end = int(payload.get("coveredEventSeqStart") or 0), int(payload.get("coveredEventSeqEnd") or 0)
        except (TypeError, ValueError):
            start = end = 0
        if start > 0 and end >= start:
            ids.update(e.event_id for e in events if start <= e.sequence <= end)
        for event_id in ids:
            event = by_id.get(event_id)
            if (event is None or event.session_id != checkpoint.session_id or not event.visible_in_model
                    or not (0 < event.sequence < current.sequence) or not _ordinary_source(event)):
                continue
            if event.event_type == EVENT_COMPACTION_CHECKPOINT:
                pending.append(event)
            elif event.event_type == EVENT_USER_MESSAGE and event.provider_role in {"", "user"}:
                sources[event.event_id] = event
    return sorted(sources.values(), key=lambda e: e.sequence)


def recover_legacy_checkpoint_facts(events: list[TurnJournalEvent], filtered: list[TurnJournalEvent]) -> list[TurnJournalEvent]:
    """Backfill surviving checkpoints using only active, covered user sources.

    If exact facts exceed the bounded supplement, retain the original user
    events for the normal input-budget guard instead of publishing partial facts.
    """
    by_id = {e.event_id: e for e in events}
    replacements, retained = {}, {e.event_id for e in filtered}
    for checkpoint in filtered:
        if checkpoint.event_type != EVENT_COMPACTION_CHECKPOINT or not _ordinary_source(checkpoint):
            continue
        original = str(checkpoint.payload.get("summary") or "").strip()
        if not original:
            continue
        sources = _sources(checkpoint, by_id, events)
        facts, source_ids = [], []
        for source in sources:
            content = source.payload.get("content")
            if not isinstance(content, str):
                continue
            recovered = recoverable_user_statements(content)
            if recovered:
                facts.extend(recovered)
                source_ids.append(source.event_id)
        facts = list(dict.fromkeys(facts))
        if not facts or retained_user_facts([], [original]) == facts:
            continue
        # Candidate text cannot supply the protected block: its contents are
        # escaped by compose_retained_summary. Only source-derived facts can.
        supplement = compose_retained_summary([], [], "", MAX_RECOVERED_FACT_CHARS, preserved_user_statements=facts)
        if supplement is None:
            retained.update(source_ids)
            continue
        summary = compose_retained_summary([], [], original, len(original) + MAX_RECOVERED_FACT_CHARS + 2, preserved_user_statements=facts)
        assert summary is not None
        payload = {**checkpoint.payload, "summary": summary,
                   "summaryHash": hashlib.sha256(summary.encode("utf-8")).hexdigest()[:16],
                   "compactionFactRecovery": {"schema": "covered_user_facts.v1", "sourceEventIds": source_ids, "factCount": len(facts)}}
        replacements[checkpoint.event_id] = replace(checkpoint, payload=payload)
    return [replacements.get(e.event_id, e) for e in events if e.event_id in retained]
