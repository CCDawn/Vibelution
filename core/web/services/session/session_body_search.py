"""Bounded message-body search over per-session workspace journals.

Message bodies are not stored in the SQLite control plane: the durable
transcript stays in each session workspace (``logs/conversation.jsonl``, with
``turn_journal.jsonl`` as the journal authority).  Body hits for session
search are therefore derived at query time by a bounded scan of those files
and returned as ``searchSnippets`` on the matching summaries.

Bounds: at most ``MAX_BODY_SEARCH_SESSIONS`` sessions are scanned per query,
at most ``MAX_SCAN_BYTES_PER_FILE`` bytes per file (tail window — recent
messages matter most), and at most ``MAX_SEARCH_SNIPPETS`` deduplicated
snippets per session.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
import json

MAX_SEARCH_SNIPPETS = 4
_SNIPPET_PREFIX_RADIUS = 48
_SNIPPET_SUFFIX_RADIUS = 112
_SNIPPET_MAX_CHARS = 200
MAX_SCAN_BYTES_PER_FILE = 2 * 1024 * 1024
MAX_BODY_SEARCH_SESSIONS = 400

_JOURNAL_CANDIDATE_FILES = (
    "logs/conversation.jsonl",
    "turn_journal.jsonl",
)

# Flattened field paths that carry user/assistant-visible text in journal
# records.  Kept deliberately narrow so snippets never surface trace or
# prompt-assembly payloads.
_TEXT_FIELD_PATHS: tuple[tuple[str, ...], ...] = (
    ("content",),
    ("thought",),
    ("payload", "content"),
    ("payload", "text"),
    ("text",),
)


def normalize_snippet_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()[:_SNIPPET_MAX_CHARS]


def build_search_snippets(text: str, query: str) -> list[str]:
    """Return up to four match-centered snippets from one searchable text."""

    normalized_query = str(query or "").strip().lower()
    source = str(text or "")
    if not normalized_query or not source.strip():
        return []
    lowered = source.lower()
    snippets: list[str] = []
    snippet_ranges: list[tuple[int, int]] = []
    search_start = 0
    while len(snippets) < MAX_SEARCH_SNIPPETS and search_start <= len(lowered):
        match_index = lowered.find(normalized_query, search_start)
        if match_index < 0:
            break
        start = max(0, match_index - _SNIPPET_PREFIX_RADIUS)
        end = min(
            len(source),
            match_index + len(normalized_query) + _SNIPPET_SUFFIX_RADIUS,
        )
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(source) else ""
        snippet = normalize_snippet_text(
            f"{prefix}{source[start:end]}{suffix}",
        )
        overlaps = any(
            min(existing_end, end) - max(existing_start, start) > 0
            for existing_start, existing_end in snippet_ranges
        )
        if snippet and not overlaps:
            snippets.append(snippet)
            snippet_ranges.append((start, end))
        search_start = match_index + len(normalized_query)
    return snippets


def searchable_text_from_journal_record(record: Any) -> str:
    """Extract bounded user-visible text from one journal JSON record."""

    if not isinstance(record, dict):
        return ""
    parts: list[str] = []
    for path in _TEXT_FIELD_PATHS:
        value: Any = record
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
            if value is None:
                break
        if isinstance(value, str) and value.strip():
            parts.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    parts.append(item)
                elif isinstance(item, dict):
                    nested = item.get("text") or item.get("content")
                    if isinstance(nested, str) and nested.strip():
                        parts.append(nested)
    return "\n".join(parts)


def _scan_journal_file(path: Path, query: str) -> list[str]:
    try:
        if not path.is_file():
            return []
        file_size = path.stat().st_size
        if file_size <= 0:
            return []
        with path.open("rb") as handle:
            if file_size > MAX_SCAN_BYTES_PER_FILE:
                handle.seek(file_size - MAX_SCAN_BYTES_PER_FILE)
            raw = handle.read(MAX_SCAN_BYTES_PER_FILE)
        text = raw.decode("utf-8", errors="replace")
        if text.startswith("\ufeff"):
            text = text[1:]
        lines = text.splitlines()
        if file_size > MAX_SCAN_BYTES_PER_FILE and lines:
            # Drop the partial first line left by the tail window seek.
            lines = lines[1:]
        haystack_parts: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                continue
            extracted = searchable_text_from_journal_record(record)
            if extracted:
                haystack_parts.append(extracted)
        return build_search_snippets("\n".join(haystack_parts), query)
    except OSError:
        return []


def search_session_bodies(
    *,
    query: str,
    session_ids: Sequence[str],
    workspace_resolver: Callable[[str], Path | None],
) -> dict[str, list[str]]:
    """Scan candidate session journals and return ``sessionId -> snippets``.

    Only sessions without a title/preview hit need a body scan; callers pass
    the candidate ids.  A session matches when any journal record text
    contains the query; snippets are match-centered windows.
    """

    normalized_query = str(query or "").strip()
    if not normalized_query:
        return {}
    matches: dict[str, list[str]] = {}
    scanned = 0
    for raw_session_id in session_ids:
        session_id = str(raw_session_id or "").strip()
        if not session_id or session_id in matches:
            continue
        if scanned >= MAX_BODY_SEARCH_SESSIONS:
            break
        workspace = workspace_resolver(session_id)
        if workspace is None:
            continue
        scanned += 1
        snippets: list[str] = []
        for relative in _JOURNAL_CANDIDATE_FILES:
            snippets.extend(_scan_journal_file(workspace / relative, normalized_query))
            if len(snippets) >= MAX_SEARCH_SNIPPETS:
                break
        if snippets:
            matches[session_id] = snippets[:MAX_SEARCH_SNIPPETS]
    return matches
