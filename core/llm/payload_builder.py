# -*- coding: utf-8 -*-
"""Build provider payloads from internal messages and protocol routes."""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List

from config import AppConfig, LLMProfile, ProviderConfig
from core.chat.model_messages import ProviderMessageChain

from .adapters import ProviderAdapter
from .protocol_resolver import ResolvedProtocolRoute
from .payload_validator import assert_payload_valid
from .schema import sanitize_tool_schema
from .streaming import extract_text_content
from .types import LLMCapabilities, LLMError
from .wire.types import BuiltPayload as WireBuiltPayload


@dataclass
class PayloadPolicyActions:
    system_messages_converted: int = 0
    string_content_messages: int = 0
    reasoning_content_stripped: int = 0
    empty_assistant_prefill_removed: int = 0
    qwen_thinking_parameter: str = ""
    minimal_tool_schema: bool = False
    prompt_cache_provider_strategy: str = "disabled"
    qwen_prompt_cache_markers_added: int = 0
    anthropic_prompt_cache_markers_added: int = 0
    anthropic_top_level_cache_control: bool = False
    provider_tool_chain_repaired: int = 0

    def to_log_dict(self) -> Dict[str, Any]:
        return {
            "payloadPolicySystemMessagesConverted": self.system_messages_converted,
            "payloadPolicyStringContentMessages": self.string_content_messages,
            "payloadPolicyReasoningContentStripped": self.reasoning_content_stripped,
            "payloadPolicyEmptyAssistantPrefillRemoved": self.empty_assistant_prefill_removed,
            "payloadPolicyQwenThinkingParameter": self.qwen_thinking_parameter,
            "payloadPolicyMinimalToolSchema": self.minimal_tool_schema,
            "promptCacheProviderStrategy": self.prompt_cache_provider_strategy,
            "payloadPolicyQwenPromptCacheMarkersAdded": self.qwen_prompt_cache_markers_added,
            "payloadPolicyAnthropicPromptCacheMarkersAdded": self.anthropic_prompt_cache_markers_added,
            "payloadPolicyAnthropicTopLevelCacheControl": self.anthropic_top_level_cache_control,
            "payloadPolicyProviderToolChainRepaired": self.provider_tool_chain_repaired,
        }


@dataclass(frozen=True)
class PayloadBuildInput:
    messages: List[Any]
    tools: List[Any]
    profile: LLMProfile
    provider: ProviderConfig
    adapter: ProviderAdapter
    route: ResolvedProtocolRoute
    capabilities: LLMCapabilities
    stream: bool
    api_key: str
    profile_id: str
    config: AppConfig
    # Per-call ephemeral clamp for short structured outputs (review JSON etc.).
    # None keeps ``profile.max_output_tokens``. Positive int only; the
    # invocation budget preflight stays authoritative on top of this.
    max_output_tokens_override: int | None = None


def _effective_max_output_tokens(build_input: PayloadBuildInput) -> Any:
    override = getattr(build_input, "max_output_tokens_override", None)
    if isinstance(override, bool) or not isinstance(override, int) or override <= 0:
        return build_input.profile.max_output_tokens
    return override


@dataclass(frozen=True)
class BuiltPayload:
    payload: Dict[str, Any]
    route: ResolvedProtocolRoute
    summary: Dict[str, Any]
    warnings: tuple[str, ...] = field(default_factory=tuple)

_PROMPT_CACHE_KEY_SAFE_RE = re.compile(r"[^a-zA-Z0-9_.:-]+")

# 由上层（chat handler、agent loop、supervised run 等）在拥有 session/conversation
# 上下文时设置，让 prompt_cache_key 在不同会话之间天然分片，避免共享 shard 互相
# 挤压稳定前缀。未设置时退回到 agent+profile+model 维度，与历史行为兼容。
_prompt_cache_partition: ContextVar[str] = ContextVar("vibelution_prompt_cache_partition", default="")


def _provider_timeout(profile: LLMProfile) -> Any:
    timeout = getattr(profile, "timeout", None)
    connect_timeout = getattr(profile, "connect_timeout", None)
    if timeout in (None, "") or connect_timeout in (None, ""):
        return timeout
    try:
        timeout_seconds = float(timeout)
        connect_timeout_seconds = float(connect_timeout)
    except (TypeError, ValueError):
        return timeout
    if timeout_seconds <= 0 or connect_timeout_seconds <= 0:
        return timeout
    try:
        import httpx
    except Exception:
        return timeout
    return httpx.Timeout(timeout=timeout_seconds, connect=connect_timeout_seconds)


def set_prompt_cache_partition(value: str):
    """直接设置当前上下文的 prompt cache 分片标识，返回 Token 供 reset。"""
    return _prompt_cache_partition.set(str(value or "").strip())


def reset_prompt_cache_partition(token) -> None:
    """重置 prompt cache 分片标识到 set_prompt_cache_partition 返回的快照。"""
    _prompt_cache_partition.reset(token)


def current_prompt_cache_partition() -> str:
    """Return the current prompt-cache partition bound by the caller context."""

    return str(_prompt_cache_partition.get() or "").strip()


@contextlib.contextmanager
def prompt_cache_partition_scope(value: str) -> Iterator[None]:
    """ContextManager 包装；适合 `with prompt_cache_partition_scope(conversation_id):` 模式。"""
    token = set_prompt_cache_partition(value)
    try:
        yield
    finally:
        reset_prompt_cache_partition(token)


def _default_prompt_cache_key(build_input: PayloadBuildInput) -> str:
    provider_kind = str(getattr(build_input.provider, "kind", "") or "provider").strip().lower()
    profile_id = str(build_input.profile_id or "profile").strip().lower()
    model = str(getattr(build_input.profile, "model", "") or "model").strip().lower()
    route_protocol = str(getattr(getattr(build_input.route, "protocol", None), "value", "") or "").strip().lower()
    route_transport = str(getattr(getattr(build_input.route, "policy", None), "transport", "") or "").strip().lower()
    agent_name = str(getattr(getattr(build_input.config, "agent", None), "name", "") or "").strip().lower()
    partition = str(_prompt_cache_partition.get() or "").strip().lower()
    raw = "|".join([provider_kind, profile_id, model, route_protocol, route_transport, agent_name, partition])
    digest = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]
    suffix_parts = [provider_kind, profile_id]
    if agent_name:
        suffix_parts.append(agent_name)
    if partition:
        suffix_parts.append(partition)
    label_prefix = _PROMPT_CACHE_KEY_SAFE_RE.sub("-", "vibelution:" + ":".join(suffix_parts)).strip("-")
    digest_suffix = f":{digest}"
    max_length = 80
    if len(label_prefix) + len(digest_suffix) <= max_length:
        return f"{label_prefix}{digest_suffix}" or f"vibelution:{digest}"
    keep = max_length - len(digest_suffix)
    truncated_prefix = label_prefix[:keep].rstrip(":-_.")
    if not truncated_prefix:
        return f"vibelution:{digest}"
    return f"{truncated_prefix}{digest_suffix}"


def _prompt_cache_provider_strategy(build_input: PayloadBuildInput, prompt_cache_mode: str) -> str:
    mode = str(prompt_cache_mode or "").strip().lower()
    if mode in {"", "disabled", "unsupported"}:
        return mode or "disabled"
    provider_kind = str(getattr(build_input.provider, "kind", "") or "").strip().lower()
    provider_api = str(getattr(build_input.provider, "api", "") or "").strip().lower().replace("_", "-")
    compat_mode = str(getattr(build_input.provider, "compat_mode", "") or "").strip().lower().replace("-", "_")
    model = str(getattr(build_input.profile, "model", "") or "").strip().lower()
    route_protocol = str(getattr(getattr(build_input.route, "protocol", None), "value", "") or "").strip().lower()
    route_transport = str(getattr(getattr(build_input.route, "policy", None), "transport", "") or "").strip().lower()
    host = str(getattr(build_input.provider, "base_url", "") or "").strip().lower()
    is_qwen = "qwen" in model or route_protocol.startswith("qwen_") or "dashscope.aliyuncs.com" in host
    is_deepseek = provider_kind == "deepseek" or "api.deepseek.com" in host or model.startswith("deepseek")
    if mode == "explicit_cache_control":
        if is_qwen:
            return "qwen_explicit_cache_control"
        if provider_kind == "anthropic" or route_protocol.startswith("anthropic_"):
            return "anthropic_explicit_cache_control"
        return "explicit_cache_control"
    if mode == "automatic":
        # DeepSeek Context Caching is server-side prefix match only — do not inject
        # OpenAI prompt_cache_key / retention fields (they are ignored or unsupported).
        if is_deepseek:
            return "deepseek_automatic"
        # Anthropic: official automatic caching uses top-level cache_control (not OpenAI keys).
        if provider_kind == "anthropic" or route_protocol.startswith("anthropic_"):
            return "anthropic_automatic_top_level"
        if provider_kind in {"openai", "relay"} or provider_api in {"openai-responses", "responses"} or route_transport == "responses":
            return "openai_automatic_key"
        if is_qwen:
            return "qwen_automatic_key"
        if provider_kind in {"openai_compatible", "relay", "xiaomi", "aliyun", "siliconflow", "google"} or compat_mode in {"openai", "openai_compatible"}:
            return "openai_compatible_automatic_key"
        return "automatic_key"
    return mode


def _requires_extended_prompt_cache_retention(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[-1]
    return normalized == "gpt-5.5" or normalized.startswith("gpt-5.5-")


def _default_prompt_cache_retention(strategy: str, *, model: str = "") -> str:
    normalized = str(strategy or "").strip().lower()
    if _requires_extended_prompt_cache_retention(model):
        return "24h"
    if normalized in {
        "openai_automatic_key",
        "openai_compatible_automatic_key",
        "automatic_key",
    }:
        return "in_memory"
    return ""


def _message_content_shape(content: Any) -> Dict[str, Any]:
    if isinstance(content, str):
        return {"kind": "text", "chars": len(content), "blocks": 0, "images": 0}
    if isinstance(content, list):
        block_types: list[str] = []
        text_chars = 0
        image_blocks = 0
        for block in content:
            if isinstance(block, dict):
                block_type = str(block.get("type") or "").strip().lower() or "object"
                block_types.append(block_type)
                text_chars += len(str(block.get("text") or block.get("content") or ""))
                if block_type in {"image_url", "input_image"} or block.get("image_url") or block.get("imageUrl"):
                    image_blocks += 1
            else:
                block_types.append(type(block).__name__)
                text_chars += len(str(block or ""))
        return {
            "kind": "blocks",
            "chars": text_chars,
            "blocks": len(content),
            "blockTypes": block_types[:8],
            "images": image_blocks,
        }
    if content is None:
        return {"kind": "empty", "chars": 0, "blocks": 0, "images": 0}
    return {"kind": type(content).__name__, "chars": len(str(content or "")), "blocks": 0, "images": 0}


def _tool_pairing_snapshot(messages: List[Dict[str, Any]]) -> Dict[str, int]:
    pending: list[str] = []
    paired = 0
    orphan = 0
    missing = 0
    assistant_tool_calls = 0
    tool_results = 0
    for message in list(messages or []):
        role = str(message.get("role") or "").strip().lower()
        if role == "assistant":
            if pending:
                missing += len(pending)
                pending = []
            raw_calls = message.get("tool_calls")
            if isinstance(raw_calls, list):
                for index, item in enumerate(raw_calls):
                    if not isinstance(item, dict):
                        continue
                    tool_call_id = str(item.get("id") or "").strip() or f"tool_{index}"
                    pending.append(tool_call_id)
                    assistant_tool_calls += 1
            continue
        if role == "tool":
            tool_results += 1
            tool_call_id = str(message.get("tool_call_id") or "").strip()
            if tool_call_id and tool_call_id in pending:
                pending.remove(tool_call_id)
                paired += 1
            else:
                orphan += 1
            continue
        if pending:
            missing += len(pending)
            pending = []
    if pending:
        missing += len(pending)
    return {
        "payloadMessageAssistantToolCallCount": assistant_tool_calls,
        "payloadMessageToolResultCount": tool_results,
        "payloadMessagePairedToolResultCount": paired,
        "payloadMessageOrphanToolResultCount": orphan,
        "payloadMessageMissingToolResultCount": missing,
    }


def _responses_tool_pairing_snapshot(items: List[Dict[str, Any]]) -> Dict[str, int]:
    pending: list[str] = []
    paired = 0
    orphan = 0
    missing = 0
    duplicate_calls = 0
    function_calls = 0
    function_outputs = 0
    seen_calls: set[str] = set()
    for item in list(items or []):
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "function_call":
            call_id = str(item.get("call_id") or "").strip()
            if call_id:
                if call_id in seen_calls:
                    duplicate_calls += 1
                seen_calls.add(call_id)
                pending.append(call_id)
            function_calls += 1
            continue
        if item_type == "function_call_output":
            function_outputs += 1
            call_id = str(item.get("call_id") or "").strip()
            if call_id and call_id in pending:
                pending.remove(call_id)
                paired += 1
            else:
                orphan += 1
            continue
        if pending:
            missing += len(pending)
            pending = []
    if pending:
        missing += len(pending)
    return {
        "payloadResponsesFunctionCallCount": function_calls,
        "payloadResponsesFunctionCallOutputCount": function_outputs,
        "payloadResponsesPairedFunctionOutputCount": paired,
        "payloadResponsesOrphanFunctionOutputCount": orphan,
        "payloadResponsesMissingFunctionOutputCount": missing,
        "payloadResponsesDuplicateFunctionCallCount": duplicate_calls,
    }


def _payload_message_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    messages = payload.get("messages")
    message_list = [item for item in messages if isinstance(item, dict)] if isinstance(messages, list) else []
    input_items: list[dict[str, Any]] = []
    if not message_list and isinstance(payload.get("input"), list):
        input_items = [item for item in payload.get("input", []) if isinstance(item, dict)]
        message_list = input_items
    roles = [str(item.get("role") or "").strip().lower() or "unknown" for item in message_list]
    response_item_types = [
        str(item.get("type") or item.get("role") or "unknown").strip().lower() or "unknown"
        for item in input_items
    ]
    shape_items: list[dict[str, Any]] = []
    has_image = False
    for index, message in enumerate(message_list):
        content_shape = _message_content_shape(message.get("content"))
        has_image = has_image or int(content_shape.get("images") or 0) > 0
        shape_items.append(
            {
                "index": index,
                "role": roles[index],
                "contentKind": str(content_shape.get("kind") or ""),
                "contentChars": int(content_shape.get("chars") or 0),
                "contentBlocks": int(content_shape.get("blocks") or 0),
                "imageBlocks": int(content_shape.get("images") or 0),
                "toolCallCount": len(message.get("tool_calls") or []) if isinstance(message.get("tool_calls"), list) else 0,
                "hasToolResultId": bool(str(message.get("tool_call_id") or "").strip()),
            }
        )
    signature_source = json.dumps(shape_items, ensure_ascii=False, sort_keys=True)
    return {
        "payloadMessageShapeHash": hashlib.sha256(signature_source.encode("utf-8", errors="replace")).hexdigest()[:16],
        "payloadMessageRoleSequence": roles,
        "payloadMessageShapeTail": shape_items[-8:],
        "payloadMessageHasImage": has_image,
        "payloadResponsesItemTypeSequence": response_item_types,
        "payloadResponsesItemTypeTail": response_item_types[-8:],
        **_tool_pairing_snapshot(message_list),
        **_responses_tool_pairing_snapshot(input_items),
    }


def _responses_content_blocks(
    content: Any,
    convert_content_blocks_for_transport,
    *,
    role: str = "user",
) -> list[dict[str, Any]]:
    text_block_type = "output_text" if role == "assistant" else "input_text"
    if isinstance(content, list):
        converted = convert_content_blocks_for_transport(content, transport="responses")
        blocks = [dict(item) for item in converted if isinstance(item, dict)] if isinstance(converted, list) else []
        if role == "assistant":
            for block in blocks:
                if str(block.get("type") or "").strip().lower() == "input_text":
                    block["type"] = "output_text"
        return blocks
    text = str(content or "").strip()
    if text:
        return [{"type": text_block_type, "text": text}]
    return []


def _responses_input_from_messages(
    messages: List[Dict[str, Any]],
    *,
    convert_content_blocks_for_transport,
) -> List[Dict[str, Any]]:
    input_items: List[Dict[str, Any]] = []
    for message in list(messages or []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip().lower() or "user"
        if role == "tool":
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(message.get("tool_call_id") or "").strip(),
                    "output": extract_text_content(message.get("content")),
                }
            )
            continue
        content = _responses_content_blocks(
            message.get("content"),
            convert_content_blocks_for_transport,
            role=role,
        )
        if role == "assistant":
            if content:
                input_items.append({"role": role, "content": content})
            for call in list(message.get("tool_calls") or []):
                if not isinstance(call, dict):
                    continue
                function = call.get("function") if isinstance(call.get("function"), dict) else {}
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": str(call.get("id") or call.get("call_id") or "").strip(),
                        "name": str(function.get("name") or call.get("name") or "").strip(),
                        "arguments": (
                            function.get("arguments")
                            if isinstance(function.get("arguments"), str)
                            else json.dumps(function.get("arguments") or {}, ensure_ascii=False)
                        ),
                    }
                )
            continue
        input_items.append({"role": role, "content": content})
    return input_items


def _apply_system_message_policy(
    messages: List[Dict[str, Any]],
    route: ResolvedProtocolRoute,
    actions: PayloadPolicyActions,
) -> List[Dict[str, Any]]:
    if route.policy.system_message_policy != "first_only_rest_user":
        return [dict(item) for item in messages]
    normalized: List[Dict[str, Any]] = []
    seen_system = False
    for item in messages:
        message = dict(item)
        if str(message.get("role") or "").strip().lower() == "system":
            if seen_system:
                message["role"] = "user"
                actions.system_messages_converted += 1
            else:
                seen_system = True
        normalized.append(message)
    return normalized


def _outgoing_reasoning_content_count(messages: List[Any]) -> int:
    count = 0
    for message in messages:
        reasoning: Any = None
        if isinstance(message, dict):
            reasoning = message.get("reasoning_content")
            if reasoning in (None, "") and isinstance(message.get("additional_kwargs"), dict):
                reasoning = message["additional_kwargs"].get("reasoning_content")
        else:
            additional_kwargs = getattr(message, "additional_kwargs", None)
            if isinstance(additional_kwargs, dict):
                reasoning = additional_kwargs.get("reasoning_content")
        if str(extract_text_content(reasoning) or "").strip():
            count += 1
    return count


def _apply_content_shape_policy(
    messages: List[Dict[str, Any]],
    route: ResolvedProtocolRoute,
    actions: PayloadPolicyActions,
    *,
    has_image_content: bool,
    preserve_cache_control: bool,
) -> List[Dict[str, Any]]:
    if route.policy.content_shape_policy != "string_only" and not route.compat.requires_string_content:
        return [dict(item) for item in messages]
    if has_image_content or preserve_cache_control:
        return [dict(item) for item in messages]
    normalized: List[Dict[str, Any]] = []
    for item in messages:
        message = dict(item)
        content = message.get("content")
        if not isinstance(content, str):
            actions.string_content_messages += 1
        message["content"] = extract_text_content(content)
        normalized.append(message)
    return normalized


def _apply_reasoning_roundtrip_policy(
    messages: List[Dict[str, Any]],
    route: ResolvedProtocolRoute,
    actions: PayloadPolicyActions,
) -> List[Dict[str, Any]]:
    if route.compat.reasoning_roundtrip and route.policy.allow_reasoning_roundtrip:
        return [dict(item) for item in messages]
    normalized: List[Dict[str, Any]] = []
    for item in messages:
        message = dict(item)
        if "reasoning_content" in message:
            actions.reasoning_content_stripped += 1
            message.pop("reasoning_content", None)
        normalized.append(message)
    return normalized


def _apply_final_message_policy(
    messages: List[Dict[str, Any]],
    route: ResolvedProtocolRoute,
    actions: PayloadPolicyActions,
) -> List[Dict[str, Any]]:
    if route.policy.final_message_policy != "no_assistant_prefill":
        return [dict(item) for item in messages]
    if not messages:
        return []
    normalized = [dict(item) for item in messages]
    last = normalized[-1]
    if str(last.get("role") or "").strip().lower() != "assistant":
        return normalized
    if last.get("tool_calls"):
        return normalized
    if str(extract_text_content(last.get("content")) or "").strip():
        return normalized
    if last.get("reasoning_content"):
        return normalized
    normalized.pop()
    actions.empty_assistant_prefill_removed += 1
    return normalized


def _apply_message_protocol_policy(
    messages: List[Dict[str, Any]],
    route: ResolvedProtocolRoute,
    actions: PayloadPolicyActions,
    *,
    has_image_content: bool,
    preserve_cache_control: bool,
) -> List[Dict[str, Any]]:
    normalized = _apply_system_message_policy(messages, route, actions)
    normalized = _apply_content_shape_policy(
        normalized,
        route,
        actions,
        has_image_content=has_image_content,
        preserve_cache_control=preserve_cache_control,
    )
    normalized = _apply_reasoning_roundtrip_policy(normalized, route, actions)
    normalized = _apply_final_message_policy(normalized, route, actions)
    return normalized


def _schema_for_tool_policy(
    tool_schema: Dict[str, Any],
    route: ResolvedProtocolRoute,
    actions: PayloadPolicyActions,
) -> Dict[str, Any]:
    if route.policy.tool_schema_policy == "minimal" or route.compat.strict_message_keys:
        actions.minimal_tool_schema = True
        return sanitize_tool_schema(tool_schema)
    return tool_schema


def _payload_thinking_parameters(
    profile: LLMProfile,
    provider: ProviderConfig,
    route: ResolvedProtocolRoute,
    actions: PayloadPolicyActions,
) -> Dict[str, Any]:
    thinking_type = str(getattr(profile, "thinking_type", "") or "").strip().lower()
    if route.policy.thinking_param_shape != "qwen":
        return {}
    if thinking_type == "disabled":
        actions.qwen_thinking_parameter = "disabled"
        enabled = False
        return _qwen_thinking_payload(enabled, provider=provider, route=route)
    if thinking_type:
        actions.qwen_thinking_parameter = "enabled"
        enabled = True
        return _qwen_thinking_payload(enabled, provider=provider, route=route)
    return {}


def _qwen_thinking_payload(
    enabled: bool,
    *,
    provider: ProviderConfig,
    route: ResolvedProtocolRoute,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"enable_thinking": enabled}
    provider_kind = str(getattr(provider, "kind", "") or "").strip().lower()
    protocol = str(getattr(route.protocol, "value", route.protocol) or "").strip().lower()
    if provider_kind == "local" and protocol == "qwen_thinking_no_prefill":
        payload["extra_body"] = {"chat_template_kwargs": {"enable_thinking": enabled}}
    return payload


def _merge_extra_body(payload: Dict[str, Any], extra_body: Any) -> None:
    if not isinstance(extra_body, dict) or not extra_body:
        return
    existing = payload.get("extra_body")
    if not isinstance(existing, dict):
        payload["extra_body"] = dict(extra_body)
        return
    merged = dict(existing)
    for key, value in extra_body.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    payload["extra_body"] = merged


def _content_cache_marker_count(content: Any) -> int:
    if not isinstance(content, list):
        return 0
    return sum(
        1
        for block in content
        if isinstance(block, dict) and bool(block.get("cache_control"))
    )


def _strip_cache_control_from_content_copy(content: Any) -> Any:
    if not isinstance(content, list):
        return content
    normalized: list[Any] = []
    for block in content:
        if isinstance(block, dict):
            copied = dict(block)
            copied.pop("cache_control", None)
            normalized.append(copied)
        else:
            normalized.append(block)
    return normalized


def _strip_cache_control_from_messages_copy(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for message in messages:
        copied = dict(message)
        copied["content"] = _strip_cache_control_from_content_copy(copied.get("content"))
        normalized.append(copied)
    return normalized


def _message_cache_marker_count(message: Dict[str, Any]) -> int:
    return _content_cache_marker_count(message.get("content"))


def _content_has_image_block(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "").strip().lower()
        if block_type in {"image_url", "input_image"}:
            return True
        if block.get("image_url") or block.get("imageUrl"):
            return True
    return False


def _append_cache_control_to_content(content: Any) -> Any:
    if isinstance(content, str):
        text = content.strip()
        if not text:
            return content
        return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]
    if not isinstance(content, list):
        return content
    normalized = [dict(block) if isinstance(block, dict) else block for block in content]
    for index in range(len(normalized) - 1, -1, -1):
        block = normalized[index]
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "text").strip().lower() not in {"", "text", "input_text"}:
            continue
        if not str(block.get("text") or block.get("content") or "").strip():
            continue
        if not block.get("cache_control"):
            block["cache_control"] = {"type": "ephemeral"}
        normalized[index] = block
        return normalized
    return content


def _message_accepts_qwen_prompt_cache_marker(message: Dict[str, Any]) -> bool:
    role = str(message.get("role") or "").strip().lower()
    if role not in {"user", "assistant"}:
        return False
    content = message.get("content")
    if _content_has_image_block(content) or _content_cache_marker_count(content):
        return False
    return _append_cache_control_to_content(content) is not content


def _select_qwen_prompt_cache_marker_index(messages: List[Dict[str, Any]]) -> int:
    if not messages:
        return -1
    current_user_index = -1
    for index in range(len(messages) - 1, -1, -1):
        if str(messages[index].get("role") or "").strip().lower() == "user":
            current_user_index = index
            break
    history_end = len(messages) - 1
    if current_user_index == len(messages) - 1:
        history_end = current_user_index - 1
    for index in range(history_end, -1, -1):
        if _message_accepts_qwen_prompt_cache_marker(messages[index]):
            return index
    if current_user_index >= 0 and _message_accepts_qwen_prompt_cache_marker(messages[current_user_index]):
        return current_user_index
    return -1


def _apply_qwen_explicit_prompt_cache_markers(
    messages: List[Dict[str, Any]],
    actions: PayloadPolicyActions,
    *,
    marker_limit: int = 4,
) -> List[Dict[str, Any]]:
    if actions.prompt_cache_provider_strategy != "qwen_explicit_cache_control":
        return [dict(item) for item in messages]
    normalized = [dict(item) for item in messages]
    marker_count = sum(_message_cache_marker_count(item) for item in normalized)
    if marker_count >= marker_limit:
        return normalized
    index = _select_qwen_prompt_cache_marker_index(normalized)
    if index < 0:
        return normalized
    message = normalized[index]
    content = message.get("content")
    updated_content = _append_cache_control_to_content(content)
    if updated_content is content:
        return normalized
    message["content"] = updated_content
    normalized[index] = message
    actions.qwen_prompt_cache_markers_added += 1
    return normalized


def _message_accepts_anthropic_prompt_cache_marker(message: Dict[str, Any]) -> bool:
    """Anthropic allows cache_control on system/user/assistant text blocks (and tools)."""
    role = str(message.get("role") or "").strip().lower()
    if role not in {"system", "user", "assistant"}:
        return False
    content = message.get("content")
    if _content_has_image_block(content) or _content_cache_marker_count(content):
        return False
    return _append_cache_control_to_content(content) is not content


def _apply_anthropic_explicit_prompt_cache_markers(
    messages: List[Dict[str, Any]],
    actions: PayloadPolicyActions,
    *,
    marker_limit: int = 4,
) -> List[Dict[str, Any]]:
    """Place ephemeral cache_control breakpoints per Anthropic prompt-caching docs.

    Prefers the first system message (stable instructions), then the last
    cacheable history text block before the current user turn.
    """
    if actions.prompt_cache_provider_strategy != "anthropic_explicit_cache_control":
        return [dict(item) for item in messages]
    normalized = [dict(item) for item in messages]
    marker_count = sum(_message_cache_marker_count(item) for item in normalized)
    if marker_count >= marker_limit:
        return normalized

    indices: list[int] = []
    for index, message in enumerate(normalized):
        if str(message.get("role") or "").strip().lower() == "system" and _message_accepts_anthropic_prompt_cache_marker(message):
            indices.append(index)
            break
    # Also mark last stable history text (before final user) so multi-turn can grow.
    current_user_index = -1
    for index in range(len(normalized) - 1, -1, -1):
        if str(normalized[index].get("role") or "").strip().lower() == "user":
            current_user_index = index
            break
    history_end = current_user_index - 1 if current_user_index >= 0 else len(normalized) - 1
    for index in range(history_end, -1, -1):
        if index in indices:
            continue
        if _message_accepts_anthropic_prompt_cache_marker(normalized[index]):
            indices.append(index)
            break

    for index in indices:
        if actions.anthropic_prompt_cache_markers_added + marker_count >= marker_limit:
            break
        message = normalized[index]
        content = message.get("content")
        updated_content = _append_cache_control_to_content(content)
        if updated_content is content:
            continue
        message["content"] = updated_content
        normalized[index] = message
        actions.anthropic_prompt_cache_markers_added += 1
    return normalized


def _apply_explicit_prompt_cache_markers(
    messages: List[Dict[str, Any]],
    actions: PayloadPolicyActions,
    *,
    marker_limit: int = 4,
) -> List[Dict[str, Any]]:
    strategy = str(actions.prompt_cache_provider_strategy or "").strip().lower()
    if strategy == "qwen_explicit_cache_control":
        return _apply_qwen_explicit_prompt_cache_markers(messages, actions, marker_limit=marker_limit)
    if strategy == "anthropic_explicit_cache_control":
        return _apply_anthropic_explicit_prompt_cache_markers(messages, actions, marker_limit=marker_limit)
    return [dict(item) for item in messages]


def build_llm_payload(
    build_input: PayloadBuildInput,
    *,
    messages_have_prompt_cache_control,
    strip_cache_control_from_messages,
    message_to_openai_dict,
    content_blocks_have_image,
    convert_content_blocks_for_transport,
    tool_to_schema,
) -> BuiltPayload:
    messages = list(build_input.messages or [])
    selected_tools = list(build_input.tools or [])
    profile = build_input.profile
    adapter = build_input.adapter
    route = build_input.route
    policy_actions = PayloadPolicyActions()
    prompt_cache_mode = str(
        getattr(getattr(profile, "prompt_cache", None), "mode", "") or "disabled"
    ).strip().lower()
    policy_actions.prompt_cache_provider_strategy = _prompt_cache_provider_strategy(
        build_input,
        prompt_cache_mode,
    )
    has_prompt_cache_control = messages_have_prompt_cache_control(messages)
    if has_prompt_cache_control and prompt_cache_mode == "unsupported":
        raise LLMError(
            "prompt_cache_unsupported",
            (
                "当前模型配置声明不支持 prompt cache；"
                f"profile `{build_input.profile_id}` provider `{build_input.provider.kind}` "
                f"transport `{getattr(profile, 'transport', '') or 'chat_completions'}` "
                f"model `{profile.model}`。请在模型配置中设置 prompt_cache.mode，"
                "或关闭系统提示词缓存强制要求。"
            ),
            retryable=False,
            provider=str(build_input.provider.kind or ""),
            model=str(profile.model or ""),
            details={
                "profile_id": build_input.profile_id,
                "provider_kind": str(build_input.provider.kind or ""),
                "transport": str(getattr(profile, "transport", "") or "chat_completions"),
                "model": str(profile.model or ""),
                "prompt_cache_mode": prompt_cache_mode,
            },
        )

    has_image_content = any(
        isinstance(item, dict) and content_blocks_have_image(item.get("content"))
        for item in messages
    )
    if has_image_content and build_input.capabilities.supports_image_input is False:
        raise LLMError(
            "capability_error",
            (
                f"profile `{build_input.profile_id}` 不支持 image input；"
                f"provider `{build_input.provider.kind}` model `{profile.model}` "
                f"protocol `{route.protocol.value}`。请切换到支持图像理解的模型，"
                "或移除本轮图片输入。"
            ),
            retryable=False,
            provider=str(build_input.provider.kind or ""),
            model=str(profile.model or ""),
            details={
                "profile_id": build_input.profile_id,
                "provider_kind": str(build_input.provider.kind or ""),
                "transport": str(getattr(profile, "transport", "") or "chat_completions"),
                "model": str(profile.model or ""),
                "protocol": route.protocol.value,
                "capability": "image_input",
                "supports_image_input": False,
                "payloadValidationResult": "blocked_before_provider",
            },
        )
    preserve_cache_control = has_prompt_cache_control and prompt_cache_mode == "explicit_cache_control"
    preserve_structured_content = (
        adapter.preserves_structured_content
        or has_image_content
        or has_prompt_cache_control
    )
    preserve_reasoning_content = bool(route.compat.reasoning_roundtrip)
    if not preserve_reasoning_content:
        policy_actions.reasoning_content_stripped = _outgoing_reasoning_content_count(messages)
    normalized_messages = [
        message_to_openai_dict(
            item,
            preserve_structured_content=preserve_structured_content,
            preserve_reasoning_content=preserve_reasoning_content,
        )
        for item in messages
    ]
    provider_chain = ProviderMessageChain.from_messages(normalized_messages)
    normalized_messages = provider_chain.to_provider_payload()
    if provider_chain.repaired:
        policy_actions.provider_tool_chain_repaired += 1
    if has_prompt_cache_control and not preserve_cache_control:
        normalized_messages = strip_cache_control_from_messages(normalized_messages)
    transport = str(getattr(profile, "transport", "") or "").strip().lower()
    if has_image_content and transport != "responses":
        for item in normalized_messages:
            item["content"] = convert_content_blocks_for_transport(item.get("content"), transport=transport)
    normalized_messages = _apply_message_protocol_policy(
        normalized_messages,
        route,
        policy_actions,
        has_image_content=has_image_content,
        preserve_cache_control=preserve_cache_control,
    )
    if preserve_cache_control and not has_image_content:
        normalized_messages = _apply_explicit_prompt_cache_markers(
            normalized_messages,
            policy_actions,
        )

    if transport == "responses":
        payload = {
            "model": adapter.litellm_model_name(),
            "input": _responses_input_from_messages(
                adapter.messages(normalized_messages),
                convert_content_blocks_for_transport=convert_content_blocks_for_transport,
            ),
            "max_output_tokens": _effective_max_output_tokens(build_input),
            "timeout": _provider_timeout(profile),
            "stream": build_input.stream,
            "api_key": build_input.api_key,
            "base_url": build_input.provider.base_url,
        }
    else:
        payload = {
            "model": adapter.litellm_model_name(),
            "messages": adapter.messages(normalized_messages),
            "max_tokens": _effective_max_output_tokens(build_input),
            "timeout": _provider_timeout(profile),
            "stream": build_input.stream,
            "api_key": build_input.api_key,
            "base_url": build_input.provider.base_url,
        }
    payload.update(adapter.payload_sampling_parameters())
    payload.update(adapter.payload_thinking_parameters())
    thinking_payload = _payload_thinking_parameters(profile, build_input.provider, route, policy_actions)
    thinking_extra_body = thinking_payload.pop("extra_body", None)
    payload.update(thinking_payload)
    _merge_extra_body(payload, thinking_extra_body)

    prompt_cache = getattr(profile, "prompt_cache", None)
    cache_strategy = policy_actions.prompt_cache_provider_strategy
    if prompt_cache_mode == "automatic" and cache_strategy == "anthropic_automatic_top_level":
        # Anthropic official automatic caching: top-level cache_control on the request.
        payload["cache_control"] = {"type": "ephemeral"}
        policy_actions.anthropic_top_level_cache_control = True
    elif prompt_cache_mode == "automatic" and cache_strategy not in {
        "deepseek_automatic",
        "anthropic_automatic_top_level",
        "disabled",
        "unsupported",
        "",
    }:
        prompt_cache_key = str(getattr(prompt_cache, "key", "") or "").strip()
        prompt_cache_retention = str(getattr(prompt_cache, "retention", "") or "").strip()
        if not prompt_cache_key:
            prompt_cache_key = _default_prompt_cache_key(build_input)
        if not prompt_cache_retention:
            prompt_cache_retention = _default_prompt_cache_retention(
                cache_strategy,
                model=str(getattr(profile, "model", "") or ""),
            )
        if prompt_cache_key:
            payload["prompt_cache_key"] = prompt_cache_key
        if prompt_cache_retention:
            payload["prompt_cache_retention"] = prompt_cache_retention
    if build_input.stream and adapter.supports_stream_usage_options() and route.compat.stream_usage_options:
        payload["stream_options"] = {"include_usage": True}
    headers = build_input.provider.extra_headers or {}
    if headers:
        payload["extra_headers"] = headers
    if selected_tools:
        if not build_input.capabilities.supports_tool_calling or not route.policy.allow_tools:
            raise LLMError("capability_error", f"profile `{build_input.profile_id}` 不支持 tool calling", retryable=False)
        payload["tools"] = [
            _schema_for_tool_policy(adapter.sanitize_tool_schema(tool_to_schema(tool)), route, policy_actions)
            for tool in selected_tools
        ]
        if adapter.supports_explicit_tool_choice() and route.policy.allow_explicit_tool_choice and route.compat.tool_choice_mode != "omit":
            payload["tool_choice"] = "auto"

    payload_snapshot = _payload_message_snapshot(payload)
    try:
        summary = assert_payload_valid(payload, route)
    except LLMError as exc:
        details = dict(exc.details or {})
        details.update(policy_actions.to_log_dict())
        details.update(payload_snapshot)
        raise LLMError(
            exc.category,
            str(exc),
            retryable=exc.retryable,
            provider=exc.provider,
            model=exc.model,
            details=details,
        ) from exc
    summary.update(policy_actions.to_log_dict())
    summary.update(payload_snapshot)
    return BuiltPayload(payload=payload, route=route, summary=summary, warnings=route.warnings)


def compose_runtime_wire_payload(
    build_input: PayloadBuildInput,
    *,
    wire_payload: WireBuiltPayload,
    has_prompt_cache_control: bool = False,
) -> BuiltPayload:
    """Attach runtime-owned transport fields without rewriting protocol content."""

    profile = build_input.profile
    route = build_input.route
    adapter = build_input.adapter
    actions = PayloadPolicyActions()
    if route.policy.system_message_policy == "first_only_rest_user":
        system_count = sum(
            1
            for message in build_input.messages
            if str(
                (message.get("role") if isinstance(message, dict) else getattr(message, "type", ""))
                or ""
            ).strip().lower() in {"system"}
        )
        actions.system_messages_converted = max(0, system_count - 1)
    if not route.compat.reasoning_roundtrip:
        actions.reasoning_content_stripped = _outgoing_reasoning_content_count(build_input.messages)
    if not route.policy.allow_assistant_prefill:
        actions.empty_assistant_prefill_removed = sum(
            1
            for message in build_input.messages
            if str(
                (message.get("role") if isinstance(message, dict) else getattr(message, "type", ""))
                or ""
            ).strip().lower() in {"assistant", "ai"}
            and not extract_text_content(
                message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
            ).strip()
        )
    if build_input.tools and (
        route.policy.tool_schema_policy == "minimal"
        or route.compat.strict_message_keys
    ):
        actions.minimal_tool_schema = True
    prompt_cache_mode = str(
        getattr(getattr(profile, "prompt_cache", None), "mode", "") or "disabled"
    ).strip().lower()
    actions.prompt_cache_provider_strategy = _prompt_cache_provider_strategy(
        build_input,
        prompt_cache_mode,
    )
    if has_prompt_cache_control and prompt_cache_mode == "unsupported":
        raise LLMError(
            "prompt_cache_unsupported",
            f"profile `{build_input.profile_id}` does not support explicit prompt cache control",
            retryable=False,
            provider=str(build_input.provider.kind or ""),
            model=str(profile.model or ""),
            details={
                "profile_id": build_input.profile_id,
                "provider_kind": str(build_input.provider.kind or ""),
                "prompt_cache_mode": prompt_cache_mode,
                "payloadValidationResult": "blocked_before_provider",
            },
        )

    payload = dict(wire_payload.body)
    payload_messages = payload.get("messages")
    if isinstance(payload_messages, list) and all(
        isinstance(item, dict) for item in payload_messages
    ):
        normalized_messages = [dict(item) for item in payload_messages]
        if prompt_cache_mode == "disabled":
            normalized_messages = _strip_cache_control_from_messages_copy(normalized_messages)
        elif prompt_cache_mode == "explicit_cache_control":
            normalized_messages = _apply_explicit_prompt_cache_markers(
                normalized_messages,
                actions,
                marker_limit=4,
            )
        payload["messages"] = normalized_messages
    payload["model"] = (
        route.effective_model
        if str(getattr(route, "adapter_id", "") or "") == "anthropic_messages_native"
        else adapter.litellm_model_name()
    )
    payload["timeout"] = _provider_timeout(profile)
    payload["api_key"] = build_input.api_key
    payload["base_url"] = wire_payload.endpoint or route.runtime_endpoint
    payload.update(adapter.payload_sampling_parameters())
    payload.update(adapter.payload_thinking_parameters())
    thinking_payload = _payload_thinking_parameters(profile, build_input.provider, route, actions)
    thinking_extra_body = thinking_payload.pop("extra_body", None)
    payload.update(thinking_payload)
    _merge_extra_body(payload, thinking_extra_body)

    prompt_cache = getattr(profile, "prompt_cache", None)
    cache_strategy = actions.prompt_cache_provider_strategy
    if prompt_cache_mode == "automatic" and cache_strategy == "anthropic_automatic_top_level":
        payload["cache_control"] = {"type": "ephemeral"}
        actions.anthropic_top_level_cache_control = True
    elif prompt_cache_mode == "automatic" and cache_strategy not in {
        "deepseek_automatic",
        "anthropic_automatic_top_level",
        "disabled",
        "unsupported",
        "",
    }:
        prompt_cache_key = str(getattr(prompt_cache, "key", "") or "").strip()
        prompt_cache_retention = str(getattr(prompt_cache, "retention", "") or "").strip()
        if not prompt_cache_key:
            prompt_cache_key = _default_prompt_cache_key(build_input)
        if not prompt_cache_retention:
            prompt_cache_retention = _default_prompt_cache_retention(
                cache_strategy,
                model=str(getattr(profile, "model", "") or ""),
            )
        if prompt_cache_key:
            payload["prompt_cache_key"] = prompt_cache_key
        if prompt_cache_retention:
            payload["prompt_cache_retention"] = prompt_cache_retention
    if build_input.stream and adapter.supports_stream_usage_options() and route.compat.stream_usage_options:
        payload["stream_options"] = {"include_usage": True}
    headers = dict(wire_payload.headers)
    headers.update(build_input.provider.extra_headers or {})
    if headers:
        payload["extra_headers"] = headers

    try:
        validation_summary = assert_payload_valid(payload, route)
    except LLMError as exc:
        details = dict(exc.details or {})
        details.update(actions.to_log_dict())
        details.update(_payload_message_snapshot(payload))
        raise LLMError(
            exc.category,
            str(exc),
            retryable=exc.retryable,
            provider=exc.provider,
            model=exc.model,
            details=details,
        ) from exc
    summary = route.log_summary()
    summary.update(validation_summary)
    summary.update(actions.to_log_dict())
    summary.update(_payload_message_snapshot(payload))
    return BuiltPayload(payload=payload, route=route, summary=summary, warnings=route.warnings)


__all__ = [
    "BuiltPayload",
    "PayloadBuildInput",
    "build_llm_payload",
    "compose_runtime_wire_payload",
    "current_prompt_cache_partition",
    "prompt_cache_partition_scope",
    "reset_prompt_cache_partition",
    "set_prompt_cache_partition",
]
