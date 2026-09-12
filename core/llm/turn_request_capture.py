# -*- coding: utf-8 -*-
"""In-memory capture of the last provider-bound request of one agent turn.

Composer "next prompt" suggestions fork the last real turn request so the
provider prompt cache is reused instead of paying full input cost again. The
capture keeps references to the exact client, the sanitized messages and the
invocation context that were sent for the turn's final LLM call. Nothing is
persisted, logged or written to the conversation ledger.

The capture scope is opt-in: the session worker opens it around one turn and
registers the collected snapshot afterwards. Outside that scope these helpers
are inert.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

PROMPT_CACHE_INHERITED_COUNT_METADATA_KEY = "promptCacheInheritedMessageCount"

_CAPTURE_SCOPE: ContextVar[dict[str, Any] | None] = ContextVar(
    "vibelution_turn_request_capture",
    default=None,
)


@contextmanager
def turn_request_capture_scope(collector: dict[str, Any]) -> Iterator[None]:
    """Bind one mutable collector to the current turn."""

    token = _CAPTURE_SCOPE.set(collector if isinstance(collector, dict) else None)
    try:
        yield
    finally:
        _CAPTURE_SCOPE.reset(token)


def capture_turn_request(client: Any, messages: list[Any], invocation_context: Any = None) -> None:
    """Store the request identity of the turn's latest LLM call (last call wins)."""

    collector = _CAPTURE_SCOPE.get()
    if collector is None:
        return
    collector["client"] = client
    collector["messages"] = list(messages or [])
    collector["invocationContext"] = invocation_context


def capture_turn_provider_message_count(count: int) -> None:
    """Store the provider-shaped message count of the latest built payload."""

    collector = _CAPTURE_SCOPE.get()
    if collector is None:
        return
    try:
        normalized = max(0, int(count or 0))
    except (TypeError, ValueError):
        normalized = 0
    collector["providerMessageCount"] = normalized


def record_turn_request_outcome(outcome: Any) -> None:
    """Store the canonical outcome summary needed by the suggestion guard."""

    collector = _CAPTURE_SCOPE.get()
    if collector is None:
        return
    usage = None
    for event in reversed(tuple(getattr(outcome, "events", ()) or ())):
        candidate = getattr(event, "usage", None)
        if candidate is not None:
            usage = candidate
            break
    collector["usage"] = usage
    collector["outcomeKind"] = str(getattr(outcome, "kind", "") or "")


__all__ = [
    "PROMPT_CACHE_INHERITED_COUNT_METADATA_KEY",
    "capture_turn_provider_message_count",
    "capture_turn_request",
    "record_turn_request_outcome",
    "turn_request_capture_scope",
]
