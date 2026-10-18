"""Agent-scoped native episodic memory recall for one Companion turn.

The selector only ranks and truncates memories that the caller already read
from the character's own native Agent episodic memory through the existing
receipt-based projection. It never creates a second profile or vector store,
never reads another Agent's memory, and never fabricates sourceless content.
Recall failures must degrade to an empty list; the dialogue continues.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .companion_preferences import PREFERENCE_ENVELOPE_PREFIX

RECALL_SUMMARY_MAX_CHARS = 240
RECALL_MESSAGE_MAX_CHARS = 500
RECALL_TEXT_MAX_CHARS = 400
RECALL_MAX_PER_TURN = 3
RECALL_MIN_PER_TURN = 1

# Intents that mean the user just corrected the character's understanding;
# recency then outranks plain topical relevance so a fresh correction is not
# buried under stale memories of the same topic.
_CORRECTION_LIKE_INTENTS = frozenset({"correction", "misunderstanding"})
_LATIN_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{1,}")


def _message_tokens(value: str) -> set[str]:
    text = str(value or "")[:RECALL_MESSAGE_MAX_CHARS]
    tokens = set(_LATIN_TOKEN.findall(text.lower()))
    compact = re.sub(r"\s+", "", text)
    tokens.update(
        compact[index : index + 2] for index in range(max(0, len(compact) - 1))
    )
    return {token for token in tokens if len(token) >= 2}


def _relevance(message_tokens: set[str], text: str) -> int:
    if not message_tokens:
        return 0
    body = str(text or "")[:RECALL_TEXT_MAX_CHARS]
    body_tokens = set(_LATIN_TOKEN.findall(body.lower()))
    compact = re.sub(r"\s+", "", body)
    body_tokens.update(
        compact[index : index + 2] for index in range(max(0, len(compact) - 1))
    )
    return len(message_tokens & body_tokens)


def _naive_utc(value: object) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return datetime.min
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.min
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def select_dialogue_memory_recalls(
    memories: Iterable[Mapping[str, Any]],
    *,
    current_message: str,
    user_intent: str = "",
    now: datetime,
    agent_id: str = "",
    limit: int = RECALL_MAX_PER_TURN,
) -> list[dict[str, Any]]:
    """Return 0-3 current, sourced, non-sensitive memory summaries for the turn.

    Ranking combines topical relevance with the current message, promotion
    confirmation, salience and freshness; superseded or corrected memories are
    dropped because the caller's projection already marks them
    ``excludedFromRecall`` (only the confirmed current version survives). A
    correction-like intent flips the ranking so the newest memory wins. The
    injected clock is only a contract touch point, never recall evidence.
    """

    bounded_limit = max(RECALL_MIN_PER_TURN, min(RECALL_MAX_PER_TURN, int(limit or 3)))
    message_tokens = _message_tokens(current_message)
    correction_turn = str(user_intent or "").strip().lower() in _CORRECTION_LIKE_INTENTS
    candidates: list[tuple[tuple[int, int, int], dict[str, Any]]] = []
    for row in memories:
        if not isinstance(row, Mapping):
            continue
        row_agent = str(row.get("agentId") or "").strip()
        if agent_id and row_agent and row_agent != str(agent_id).strip():
            continue
        if bool(row.get("excludedFromRecall")) or bool(row.get("sensitive")):
            continue
        episode_id = str(row.get("episodeId") or "").strip()
        text = str(row.get("text") or "").strip()
        if not episode_id or not text:
            continue
        if text.startswith(PREFERENCE_ENVELOPE_PREFIX):
            # Reviewed preferences already reach the turn through their own
            # bounded projection; never re-inject their envelopes as recall.
            continue
        score = _relevance(message_tokens, text)
        if score <= 0:
            continue
        salience = int(row.get("salienceScore") or 0)
        ordinal_day = _naive_utc(
            row.get("occurredAt") or row.get("promotedAt")
        ).toordinal()
        rank = (
            (ordinal_day, score, salience)
            if correction_turn
            else (score, salience, ordinal_day)
        )
        candidates.append(
            (
                rank,
                {
                    "sourceKey": f"memory:{episode_id}",
                    "episodeId": episode_id,
                    "summary": text[:RECALL_SUMMARY_MAX_CHARS],
                    "occurredAt": str(row.get("occurredAt") or ""),
                    "sourceKind": str(row.get("sourceKind") or "unknown"),
                    "salienceScore": salience,
                    "relevanceScore": score,
                },
            )
        )
    _ = bool(now)
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [deepcopy(payload) for _, payload in candidates[:bounded_limit]]


def dialogue_followup_matches(message: object, text: object) -> bool:
    """Deterministically detect that the user asked about ``text`` again.

    A bounded token/bigram overlap stands in for semantic matching without a
    second vector store; it only re-enables disclosure topics, never blocks
    anything, so a false negative is merely conservative.
    """

    score = _relevance(_message_tokens(str(message or "")), str(text or ""))
    return score >= 2


__all__ = [
    "RECALL_MAX_PER_TURN",
    "RECALL_SUMMARY_MAX_CHARS",
    "dialogue_followup_matches",
    "select_dialogue_memory_recalls",
]
