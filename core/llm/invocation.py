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
