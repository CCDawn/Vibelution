# -*- coding: utf-8 -*-
"""Shared LLM invocation context and dialogue-chain metadata."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from typing import Any, Mapping


_SAFE_PART_RE = re.compile(r"[^a-zA-Z0-9_.:-]+")
_MAIN_PURPOSES = {"", "main", "main_reply", "dialogue", "conversation"}


def _clean(value: Any, *, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _short_hash(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _safe_fragment(value: Any, *, fallback: str = "") -> str:
    text = _SAFE_PART_RE.sub("-", _clean(value, fallback=fallback)).strip("-:._")
    return text or fallback


def dialogue_chain_mode_for_protocol(protocol: Any, *, transport: str = "", contract: str = "") -> str:
    """Map a model protocol to the reusable dialogue-chain mode it should use."""

    value = str(getattr(protocol, "value", protocol) or "").strip().lower()
    if value in {"openai_responses", "relay_responses"}:
        return "responses_agent"
    if value in {
        "anthropic_thinking",
        "deepseek_reasoning",
        "qwen_thinking_no_prefill",
        "llamacpp_qwen_thinking",
    }:
        return "reasoning_chat"
    if value in {"basic_chat_no_tools", "llamacpp_basic"}:
        return "basic_chat"
    if value in {
        "openai_chat_tools",
        "anthropic_chat",
        "qwen_openai_compat",
        "xiaomi_mimo_multimodal_openai_compat",
        "xiaomi_mimo_token_plan_openai_compat",
        "minimax_chat",
    }:
        return "tool_chat"

    normalized_transport = str(transport or "").strip().lower()
    normalized_contract = str(contract or "").strip().lower()
    if normalized_transport == "responses":
        return "responses_agent"
    if normalized_contract == "basic_chat":
        return "basic_chat"
    if normalized_contract == "reasoning_chat":
        return "reasoning_chat"
    return "tool_chat"


def prompt_purpose_cache_partition(base_partition: str, prompt_purpose: str) -> str:
    """Derive a purpose-specific partition without changing the base conversation shard."""

    base = _clean(base_partition)
    if not base:
        return ""
    purpose = _safe_fragment(prompt_purpose).lower()
    if purpose in _MAIN_PURPOSES:
        return base
    candidate = f"{base}:{purpose}"
    if len(candidate) <= 120:
        return candidate
    digest = _short_hash(candidate)
    keep = max(1, 120 - len(digest) - 1)
    return f"{candidate[:keep].rstrip(':._-')}:{digest}"


@dataclass(frozen=True)
class LLMInvocationContext:
    """Stable metadata for one logical LLM call.

    The context describes the product surface and prompt purpose. Provider
    protocol adaptation still lives in ``core.llm`` payload/protocol modules.
    """

    surface: str
    run_kind: str = ""
    run_id: str = ""
    session_id: str = ""
    agent_id: str = ""
    llm_slot: str = "dialogue"
    model_id: str = ""
    cache_scope: str = ""
    cache_partition: str = ""
    prompt_purpose: str = "main_reply"
    conversation_bound: bool = False
    dialogue_chain_mode: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def with_cache_partition(self, cache_partition: str) -> "LLMInvocationContext":
        return replace(self, cache_partition=_clean(cache_partition))

    def with_client_protocol(self, client: Any) -> "LLMInvocationContext":
        if self.dialogue_chain_mode:
            return self
        route = getattr(client, "protocol_route", None)
        profile = getattr(client, "profile", None)
        mode = dialogue_chain_mode_for_protocol(
            getattr(route, "protocol", ""),
            transport=getattr(getattr(route, "policy", None), "transport", "")
            or getattr(profile, "transport", ""),
            contract=getattr(profile, "contract", ""),
        )
        return replace(self, dialogue_chain_mode=mode)

    def to_metadata(self, *, client: Any = None) -> dict[str, Any]:
        context = self.with_client_protocol(client) if client is not None else self
        route = getattr(client, "protocol_route", None) if client is not None else None
        partition = _clean(context.cache_partition)
        metadata = {key: value for key, value in dict(context.metadata or {}).items() if value not in (None, "")}
        metadata.update({
            "llmInvocationSurface": _clean(context.surface, fallback="unknown"),
            "llmRunKind": _clean(context.run_kind),
            "llmRunId": _clean(context.run_id),
            "sessionId": _clean(context.session_id),
            "agentId": _clean(context.agent_id),
            "llmSlot": _clean(context.llm_slot, fallback="dialogue"),
            "llmModelId": _clean(context.model_id),
            "promptPurpose": _clean(context.prompt_purpose, fallback="main_reply"),
            "conversationBound": bool(context.conversation_bound),
            "dialogueChainMode": _clean(context.dialogue_chain_mode, fallback="tool_chat"),
            "promptCacheScope": _clean(context.cache_scope),
            "promptCachePartition": partition,
            "promptCachePartitionHash": _short_hash(partition),
            "promptCachePartitionChars": len(partition),
        })
        if route is not None:
            metadata.update(
                {
                    "selectedProtocol": str(getattr(getattr(route, "protocol", None), "value", "") or ""),
                    "protocolSource": _clean(getattr(route, "source", "")),
                }
            )
        return {key: value for key, value in metadata.items() if value not in (None, "")}


__all__ = [
    "LLMInvocationContext",
    "dialogue_chain_mode_for_protocol",
    "prompt_purpose_cache_partition",
]
