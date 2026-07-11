# -*- coding: utf-8 -*-
"""Unified helper functions for protocol-aware LLM calls."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import nullcontext
from typing import Any

from .invocation_context import LLMInvocationContext, prompt_purpose_cache_partition
from .payload_builder import current_prompt_cache_partition, prompt_cache_partition_scope


def _developer_sandbox_module():
    from core.infrastructure import developer_sandbox

    return developer_sandbox


def _context_with_effective_partition(context: LLMInvocationContext) -> LLMInvocationContext:
    explicit_partition = str(context.cache_partition or "").strip()
    base_partition = explicit_partition or str(current_prompt_cache_partition() or "").strip()
    effective_partition = (
        explicit_partition
        if explicit_partition
        else prompt_purpose_cache_partition(base_partition, context.prompt_purpose)
    )
    effective_partition = _developer_sandbox_module().sandbox_prompt_cache_partition(
        effective_partition,
        surface=str(context.surface or "runtime"),
    )
    return context.with_cache_partition(effective_partition)


def _merged_metadata(context: LLMInvocationContext, client: Any, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(metadata or {})
    merged.update(context.to_metadata(client=client))
    return _developer_sandbox_module().enrich_debug_fields(merged)


def invocation_scope_from_metadata(metadata: Any = None):
    """Build a stable canonical scope from invocation metadata.

    Conversation-bound calls keep their explicit session identity. Auxiliary
    calls use the controlled synthetic namespace required by wire adapters.
    """
    from uuid import uuid4

    from .semantic_messages import InvocationScope

    values = dict(metadata or {})
    run_id = str(values.get("llmRunId") or "").strip()
    invocation_id = str(values.get("invocationId") or run_id or uuid4().hex).strip()
    session_id = str(values.get("sessionId") or "").strip()
    if session_id:
        turn_id = str(values.get("turnId") or run_id or f"{session_id}:turn").strip()
        raw_iteration = values.get("iteration", 0)
        try:
            iteration = max(0, int(raw_iteration))
        except (TypeError, ValueError):
            iteration = 0
        return InvocationScope(
            session_id=session_id,
            turn_id=turn_id,
            invocation_id=invocation_id,
            iteration=iteration,
        )

    purpose = str(
        values.get("promptPurpose")
        or values.get("llmRunKind")
        or values.get("llmInvocationSurface")
        or "llm"
    ).strip()
    return InvocationScope.for_synthetic(invocation_id=invocation_id, purpose=purpose)


def invoke_llm(
    client: Any,
    messages: list[Any],
    *,
    context: LLMInvocationContext,
    tools: list[Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """Invoke a client with normalized metadata and prompt-cache partitioning."""

    effective_context = _context_with_effective_partition(context)
    effective_metadata = _merged_metadata(effective_context, client, metadata)
    partition = str(effective_context.cache_partition or "").strip()
    scope = prompt_cache_partition_scope(partition) if partition else nullcontext()
    with scope:
        return client.invoke(messages, tools=tools, metadata=effective_metadata)


def stream_llm(
    client: Any,
    messages: list[Any],
    *,
    context: LLMInvocationContext,
    tools: list[Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Stream from a client with normalized metadata and prompt-cache partitioning."""

    effective_context = _context_with_effective_partition(context)
    effective_metadata = _merged_metadata(effective_context, client, metadata)
    partition = str(effective_context.cache_partition or "").strip()
    scope = prompt_cache_partition_scope(partition) if partition else nullcontext()
    with scope:
        yield from client.stream(messages, tools=tools, metadata=effective_metadata)


__all__ = ["invoke_llm", "stream_llm"]
