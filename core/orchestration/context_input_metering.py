"""Read-only context estimates including the fields the provider will receive."""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from core.llm.message_projector import message_to_openai_dict
from tools.token_manager import (
    estimate_messages_tokens,
    estimate_messages_tokens_for_threshold,
)

# Keep auxiliary message objects stable so the existing bounded token-estimate
# cache can reuse unchanged history. Never retain the original message objects.
_AUX_MAX_ENTRIES = 8
_AUX_MAX_CHARS = 2_000_000
_aux_cache: OrderedDict[tuple[str, ...], list[dict[str, str]]] = OrderedDict()
_aux_chars = 0
_aux_lock = threading.Lock()


def _auxiliary_messages(texts: tuple[str, ...]) -> list[dict[str, str]]:
    global _aux_chars
    weight = sum(map(len, texts))
    with _aux_lock:
        cached = _aux_cache.get(texts)
        if cached is not None:
            _aux_cache.move_to_end(texts)
            return cached
        projected = [{"content": text} for text in texts]
        if weight > _AUX_MAX_CHARS:
            return projected
        _aux_cache[texts] = projected
        _aux_chars += weight
        while len(_aux_cache) > _AUX_MAX_ENTRIES or _aux_chars > _AUX_MAX_CHARS:
            previous, _ = _aux_cache.popitem(last=False)
            _aux_chars -= sum(map(len, previous))
        return projected


def estimate_context_input_tokens(
    messages: list[Any],
    *,
    threshold: int | None = None,
    preserve_reasoning_content: bool = False,
    exact_estimator: Callable | None = None,
    threshold_estimator: Callable | None = None,
) -> int:
    """Estimate message content plus normalized call/round-trip metadata.

    This remains an estimate, not the provider tokenizer or tool-schema budget.
    Native tool results already live in message content and are counted once.
    Protocols that strip reasoning must not be charged for that hidden field.
    The auxiliary messages exist only for counting, never for model submission.
    """
    auxiliary = []
    for message in messages:
        wire = message_to_openai_dict(
            message, preserve_structured_content=True,
            preserve_reasoning_content=preserve_reasoning_content,
        )
        fields = {key: wire[key] for key in ("tool_calls", "tool_call_id", "reasoning_content") if wire.get(key)}
        if fields:
            auxiliary.append(json.dumps(fields, ensure_ascii=False))
    metered = [*messages, *_auxiliary_messages(tuple(auxiliary))] if auxiliary else messages
    if threshold is None:
        return (exact_estimator or estimate_messages_tokens)(metered)
    return (threshold_estimator or estimate_messages_tokens_for_threshold)(metered, threshold)
