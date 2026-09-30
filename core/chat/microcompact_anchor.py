# -*- coding: utf-8 -*-
"""Hybrid token metering anchor for the micro-compaction trigger gate.

Design borrowed from ZCode ``runtime/methods/compact.ts``
(``buildProviderUsageTokenOverride``; design, not code): the gate anchors on
the latest committed assistant's provider usage instead of a pure local
estimate, and only the messages produced *after* that assistant are estimated
locally. This removes most of the drift of the char-ratio estimator while
keeping the per-turn increment cheap.

Data source is the Vibelution usage ledger (``core/llm/usage_ledger.py``):
the latest row with ``source='provider_usage'`` scoped to the conversation.
The lookup is strictly read-only — the micro-compaction tier never writes the
ledger, so the next assembly rebuilds the same view from the persisted
transcript (projection determinism invariant).

When no anchor applies (no ledger row, ledger unreadable, or the last
committed assistant is not present in the live list) the gate falls back to
the pure local estimate, which is behaviorally identical to the pre-anchor
tier. Every decision carries a ``tokenSource`` audit field:
``estimate`` (pure fallback), ``provider_usage`` (anchor base with an empty
increment), or ``anchor+estimate`` (provider base plus local increment).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

from core.llm.usage_ledger import usage_ledger_path


_EMPTY_AUDIT_KEYS: tuple[str, ...] = (
    "tokenSource",
    "anchorTokens",
    "incrementalTokens",
    "incrementalStartIndex",
    "anchorEventId",
    "anchorRecordedAt",
)


def empty_anchor_audit() -> dict[str, Any]:
    return {
        "tokenSource": "estimate",
        "anchorTokens": 0,
        "incrementalTokens": 0,
        "incrementalStartIndex": -1,
        "anchorEventId": "",
        "anchorRecordedAt": "",
    }


def load_provider_usage_anchor(
    *,
    conversation_id: str = "",
    session_id: str = "",
    project_root: Path | None = None,
) -> dict[str, Any] | None:
    """Return the latest committed provider usage for this conversation.

    Read-only lookup on the usage ledger: ``source='provider_usage'`` rows
    only, ordered ``recorded_at DESC, rowid DESC`` (same recency convention
    as the ledger's own last-valid-row query). ``conversation_id`` is tried
    first and ``session_id`` second, because ledger writers fill the two
    columns from different metadata aliases. Any failure — missing ledger
    file, missing table, locked database — returns ``None`` so the gate can
    fall back to the pure estimate instead of breaking the turn.
    """

    scoped_ids = [
        str(value or "").strip()
        for value in (conversation_id, session_id)
        if str(value or "").strip()
    ]
    if not scoped_ids:
        return None
    try:
        path = usage_ledger_path(project_root)
    except Exception:
        return None
    if not path.exists():
        return None
    connection: sqlite3.Connection | None = None
    try:
        try:
            connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        except sqlite3.Error:
            connection = sqlite3.connect(str(path))
        connection.row_factory = sqlite3.Row
        for scoped_id in scoped_ids:
            row = connection.execute(
                """
                SELECT event_id, recorded_at, input_tokens, output_tokens, total_tokens
                FROM usage_events
                WHERE source='provider_usage'
                  AND (conversation_id=? OR session_id=?)
                ORDER BY recorded_at DESC, rowid DESC
                LIMIT 1
                """,
                (scoped_id, scoped_id),
            ).fetchone()
            if row is not None:
                return {
                    "eventId": str(row["event_id"] or ""),
                    "recordedAt": str(row["recorded_at"] or ""),
                    "inputTokens": _nonnegative_int(row["input_tokens"]),
                    "outputTokens": _nonnegative_int(row["output_tokens"]),
                    "totalTokens": _nonnegative_int(row["total_tokens"]),
                }
        return None
    except Exception:
        return None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def estimate_tokens_with_anchor(
    messages: list[Any] | None,
    *,
    anchor: dict[str, Any] | None,
    incremental_estimate: Callable[[list[Any]], int] | None = None,
    estimate_tokens: Callable[[list[Any]], int] | None = None,
    fallback_tokens: int | None = None,
) -> tuple[int, dict[str, Any]]:
    """Hybrid estimate: provider-usage base + local estimate of the increment.

    The anchor corresponds to the provider call that produced the last
    committed assistant message in ``messages``:

    - ``total_tokens > 0`` (provider context-after-call, the
      ``contextUsageTokens`` analogue): the base already covers the assistant
      output, so the local increment starts strictly after it;
    - otherwise ``input_tokens > 0``: the provider input only covers the
      request that produced the assistant, so the assistant message itself
      stays part of the local increment.

    Returns ``(tokens, audit)``. ``audit["tokenSource"]`` is one of
    ``estimate`` (no applicable anchor — value equals the pure estimate, or
    ``fallback_tokens`` when the caller already computed it),
    ``provider_usage`` (anchor base, empty increment), or
    ``anchor+estimate``. The estimator defaults to the shared
    ``estimate_messages_tokens`` so Chinese/ASCII weights stay on the
    token-manager convention instead of a second estimator.
    """

    audit = empty_anchor_audit()
    source = list(messages or [])
    estimator = incremental_estimate or estimate_tokens or _default_estimate_tokens

    def _pure_estimate() -> tuple[int, dict[str, Any]]:
        if fallback_tokens is not None:
            return max(0, int(fallback_tokens or 0)), audit
        return max(0, int(_safe_int(estimator(source)))), audit

    if not isinstance(anchor, dict):
        return _pure_estimate()
    total_tokens = _safe_int(anchor.get("totalTokens") or anchor.get("total_tokens"))
    input_tokens = _safe_int(anchor.get("inputTokens") or anchor.get("input_tokens"))
    if total_tokens <= 0 and input_tokens <= 0:
        return _pure_estimate()

    last_assistant_index = _last_assistant_index(source)
    if last_assistant_index < 0:
        # The anchored call's assistant message is not part of this view
        # (windowed seed, replayed suffix); the anchor cannot be located, so
        # the hybrid number would silently double-count. Fall back.
        return _pure_estimate()

    if total_tokens > 0:
        base = total_tokens
        start = last_assistant_index + 1
    else:
        base = input_tokens
        start = last_assistant_index

    audit["anchorTokens"] = base
    audit["incrementalStartIndex"] = start
    audit["anchorEventId"] = str(anchor.get("eventId") or "")
    audit["anchorRecordedAt"] = str(anchor.get("recordedAt") or "")
    incremental_messages = source[start:]
    if not incremental_messages:
        audit["tokenSource"] = "provider_usage"
        audit["incrementalTokens"] = 0
        return max(0, base), audit
    incremental = max(0, int(_safe_int(estimator(incremental_messages))))
    audit["tokenSource"] = "anchor+estimate"
    audit["incrementalTokens"] = incremental
    return max(0, base + incremental), audit


def _last_assistant_index(messages: list[Any]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if _message_role(messages[index]) == "assistant":
            return index
    return -1


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        role = message.get("role")
    else:
        role = getattr(message, "type", None) or getattr(message, "role", None)
    normalized = str(role or "").strip().lower()
    if normalized == "ai":
        return "assistant"
    if normalized == "human":
        return "user"
    return normalized


def _default_estimate_tokens(messages: list[Any]) -> int:
    from tools.token_manager import estimate_messages_tokens

    return int(estimate_messages_tokens(messages))


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _nonnegative_int(value: Any) -> int:
    return _safe_int(value)


__all__ = [
    "empty_anchor_audit",
    "estimate_tokens_with_anchor",
    "load_provider_usage_anchor",
]
