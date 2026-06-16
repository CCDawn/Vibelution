# -*- coding: utf-8 -*-
"""Model protocol policies for LLM payload routing.

Provider adapters describe how to reach an upstream service. Protocol policies
describe the model/request contract that must be satisfied before the payload is
sent to that service.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict


class ModelProtocol(StrEnum):
    BASIC_CHAT_NO_TOOLS = "basic_chat_no_tools"
    OPENAI_CHAT_TOOLS = "openai_chat_tools"
    OPENAI_RESPONSES = "openai_responses"
    ANTHROPIC_CHAT = "anthropic_chat"
    ANTHROPIC_THINKING = "anthropic_thinking"
    DEEPSEEK_REASONING = "deepseek_reasoning"
    XIAOMI_MIMO_MULTIMODAL_OPENAI_COMPAT = "xiaomi_mimo_multimodal_openai_compat"
    XIAOMI_MIMO_TOKEN_PLAN_OPENAI_COMPAT = "xiaomi_mimo_token_plan_openai_compat"
    QWEN_OPENAI_COMPAT = "qwen_openai_compat"
    QWEN_THINKING_NO_PREFILL = "qwen_thinking_no_prefill"
    LLAMACPP_BASIC = "llamacpp_basic"
    LLAMACPP_QWEN_THINKING = "llamacpp_qwen_thinking"
    MINIMAX_CHAT = "minimax_chat"
    RELAY_RESPONSES = "relay_responses"


@dataclass(frozen=True)
class CompatPolicy:
    requires_string_content: bool = False
    strict_message_keys: bool = False
    allow_assistant_prefill: bool = True
    reasoning_roundtrip: bool = False
    thinking_format: str = ""
    tool_choice_mode: str = "auto"
    stream_usage_options: bool = False

    @classmethod
    def from_raw(cls, raw: Any) -> "CompatPolicy":
        if not isinstance(raw, dict):
            return cls()
        default = cls()
        return cls(
            requires_string_content=bool(raw.get("requiresStringContent", raw.get("requires_string_content", default.requires_string_content))),
            strict_message_keys=bool(raw.get("strictMessageKeys", raw.get("strict_message_keys", default.strict_message_keys))),
            allow_assistant_prefill=bool(raw.get("allowAssistantPrefill", raw.get("allow_assistant_prefill", default.allow_assistant_prefill))),
            reasoning_roundtrip=bool(raw.get("reasoningRoundtrip", raw.get("reasoning_roundtrip", default.reasoning_roundtrip))),
            thinking_format=str(raw.get("thinkingFormat", raw.get("thinking_format", default.thinking_format)) or "").strip().lower(),
            tool_choice_mode=str(raw.get("toolChoiceMode", raw.get("tool_choice_mode", default.tool_choice_mode)) or "auto").strip().lower(),
            stream_usage_options=bool(raw.get("streamUsageOptions", raw.get("stream_usage_options", default.stream_usage_options))),
        )

    def merged(self, override: "CompatPolicy", *, override_fields: set[str] | None = None) -> "CompatPolicy":
        explicit = override_fields or set()
        return CompatPolicy(
            requires_string_content=override.requires_string_content if "requires_string_content" in explicit else self.requires_string_content,
            strict_message_keys=override.strict_message_keys if "strict_message_keys" in explicit else self.strict_message_keys,
            allow_assistant_prefill=override.allow_assistant_prefill if "allow_assistant_prefill" in explicit else self.allow_assistant_prefill,
            reasoning_roundtrip=override.reasoning_roundtrip if "reasoning_roundtrip" in explicit else self.reasoning_roundtrip,
            thinking_format=override.thinking_format or self.thinking_format,
            tool_choice_mode=override.tool_choice_mode if "tool_choice_mode" in explicit else self.tool_choice_mode,
            stream_usage_options=override.stream_usage_options if "stream_usage_options" in explicit else self.stream_usage_options,
        )

    def to_log_dict(self) -> Dict[str, Any]:
        return {
            "requiresStringContent": self.requires_string_content,
            "strictMessageKeys": self.strict_message_keys,
            "allowAssistantPrefill": self.allow_assistant_prefill,
            "reasoningRoundtrip": self.reasoning_roundtrip,
            "thinkingFormat": self.thinking_format,
            "toolChoiceMode": self.tool_choice_mode,
            "streamUsageOptions": self.stream_usage_options,
        }


def compat_override_fields(raw: Any) -> set[str]:
    if not isinstance(raw, dict):
        return set()
    mapping = {
        "requiresStringContent": "requires_string_content",
        "requires_string_content": "requires_string_content",
        "strictMessageKeys": "strict_message_keys",
        "strict_message_keys": "strict_message_keys",
        "allowAssistantPrefill": "allow_assistant_prefill",
        "allow_assistant_prefill": "allow_assistant_prefill",
        "reasoningRoundtrip": "reasoning_roundtrip",
        "reasoning_roundtrip": "reasoning_roundtrip",
        "thinkingFormat": "thinking_format",
        "thinking_format": "thinking_format",
        "toolChoiceMode": "tool_choice_mode",
        "tool_choice_mode": "tool_choice_mode",
        "streamUsageOptions": "stream_usage_options",
        "stream_usage_options": "stream_usage_options",
    }
    return {mapping[key] for key in raw if key in mapping}


@dataclass(frozen=True)
class ProtocolPolicy:
    protocol: ModelProtocol
    transport: str
    allow_tools: bool
    allow_parallel_tools: bool
    allow_explicit_tool_choice: bool
    allow_stream_usage_options: bool
    allow_multiple_system_messages: bool
    allow_assistant_prefill: bool
    allow_reasoning_roundtrip: bool
    thinking_param_shape: str
    system_message_policy: str
    final_message_policy: str
    content_shape_policy: str
    reasoning_extract_policy: str
    tool_schema_policy: str

    @property
    def compat_defaults(self) -> CompatPolicy:
        return CompatPolicy(
            requires_string_content=self.content_shape_policy == "string_only",
            strict_message_keys=self.tool_schema_policy == "minimal",
            allow_assistant_prefill=self.allow_assistant_prefill,
            reasoning_roundtrip=self.allow_reasoning_roundtrip,
            thinking_format=self.thinking_param_shape if self.thinking_param_shape not in {"", "none"} else "",
            tool_choice_mode="auto" if self.allow_explicit_tool_choice else "omit",
            stream_usage_options=self.allow_stream_usage_options,
        )


def _policy(
    protocol: ModelProtocol,
    *,
    transport: str = "chat_completions",
    allow_tools: bool = True,
    allow_parallel_tools: bool = False,
    allow_explicit_tool_choice: bool = True,
    allow_stream_usage_options: bool = False,
    allow_multiple_system_messages: bool = True,
    allow_assistant_prefill: bool = True,
    allow_reasoning_roundtrip: bool = False,
    thinking_param_shape: str = "none",
    system_message_policy: str = "preserve",
    final_message_policy: str = "any",
    content_shape_policy: str = "preserve",
    reasoning_extract_policy: str = "generic",
    tool_schema_policy: str = "default",
) -> ProtocolPolicy:
    return ProtocolPolicy(
        protocol=protocol,
        transport=transport,
        allow_tools=allow_tools,
        allow_parallel_tools=allow_parallel_tools,
        allow_explicit_tool_choice=allow_explicit_tool_choice,
        allow_stream_usage_options=allow_stream_usage_options,
        allow_multiple_system_messages=allow_multiple_system_messages,
        allow_assistant_prefill=allow_assistant_prefill,
        allow_reasoning_roundtrip=allow_reasoning_roundtrip,
        thinking_param_shape=thinking_param_shape,
        system_message_policy=system_message_policy,
        final_message_policy=final_message_policy,
        content_shape_policy=content_shape_policy,
        reasoning_extract_policy=reasoning_extract_policy,
        tool_schema_policy=tool_schema_policy,
    )


PROTOCOL_POLICIES: Dict[ModelProtocol, ProtocolPolicy] = {
    ModelProtocol.BASIC_CHAT_NO_TOOLS: _policy(
        ModelProtocol.BASIC_CHAT_NO_TOOLS,
        allow_tools=False,
        allow_explicit_tool_choice=False,
        content_shape_policy="string_only",
        system_message_policy="first_only_rest_user",
        tool_schema_policy="minimal",
    ),
    ModelProtocol.OPENAI_CHAT_TOOLS: _policy(ModelProtocol.OPENAI_CHAT_TOOLS, allow_stream_usage_options=True),
    ModelProtocol.OPENAI_RESPONSES: _policy(
        ModelProtocol.OPENAI_RESPONSES,
        transport="responses",
        content_shape_policy="responses_blocks",
        allow_stream_usage_options=True,
    ),
    ModelProtocol.ANTHROPIC_CHAT: _policy(ModelProtocol.ANTHROPIC_CHAT, content_shape_policy="preserve"),
    ModelProtocol.ANTHROPIC_THINKING: _policy(
        ModelProtocol.ANTHROPIC_THINKING,
        thinking_param_shape="anthropic",
        content_shape_policy="preserve",
        reasoning_extract_policy="anthropic",
    ),
    ModelProtocol.DEEPSEEK_REASONING: _policy(
        ModelProtocol.DEEPSEEK_REASONING,
        allow_explicit_tool_choice=False,
        allow_reasoning_roundtrip=True,
        reasoning_extract_policy="deepseek",
    ),
    ModelProtocol.XIAOMI_MIMO_MULTIMODAL_OPENAI_COMPAT: _policy(
        ModelProtocol.XIAOMI_MIMO_MULTIMODAL_OPENAI_COMPAT,
        allow_stream_usage_options=True,
    ),
    ModelProtocol.XIAOMI_MIMO_TOKEN_PLAN_OPENAI_COMPAT: _policy(
        ModelProtocol.XIAOMI_MIMO_TOKEN_PLAN_OPENAI_COMPAT,
        allow_stream_usage_options=True,
    ),
    ModelProtocol.QWEN_OPENAI_COMPAT: _policy(
        ModelProtocol.QWEN_OPENAI_COMPAT,
        allow_stream_usage_options=True,
        system_message_policy="first_only_rest_user",
    ),
    ModelProtocol.QWEN_THINKING_NO_PREFILL: _policy(
        ModelProtocol.QWEN_THINKING_NO_PREFILL,
        allow_stream_usage_options=True,
        allow_assistant_prefill=False,
        thinking_param_shape="qwen",
        system_message_policy="first_only_rest_user",
        final_message_policy="no_assistant_prefill",
        reasoning_extract_policy="think_tag",
    ),
    ModelProtocol.LLAMACPP_BASIC: _policy(
        ModelProtocol.LLAMACPP_BASIC,
        allow_explicit_tool_choice=False,
        allow_stream_usage_options=False,
        system_message_policy="first_only_rest_user",
        content_shape_policy="string_only",
        tool_schema_policy="minimal",
    ),
    ModelProtocol.LLAMACPP_QWEN_THINKING: _policy(
        ModelProtocol.LLAMACPP_QWEN_THINKING,
        allow_explicit_tool_choice=False,
        allow_stream_usage_options=False,
        allow_assistant_prefill=False,
        allow_reasoning_roundtrip=False,
        thinking_param_shape="qwen",
        system_message_policy="first_only_rest_user",
        final_message_policy="no_assistant_prefill",
        content_shape_policy="string_only",
        reasoning_extract_policy="think_tag",
        tool_schema_policy="minimal",
    ),
    ModelProtocol.MINIMAX_CHAT: _policy(
        ModelProtocol.MINIMAX_CHAT,
        system_message_policy="first_only_rest_user",
    ),
    ModelProtocol.RELAY_RESPONSES: _policy(
        ModelProtocol.RELAY_RESPONSES,
        transport="responses",
        content_shape_policy="responses_blocks",
        allow_stream_usage_options=True,
    ),
}


def get_protocol_policy(protocol: ModelProtocol | str) -> ProtocolPolicy:
    normalized = ModelProtocol(str(protocol or ModelProtocol.BASIC_CHAT_NO_TOOLS))
    return PROTOCOL_POLICIES[normalized]


__all__ = [
    "CompatPolicy",
    "ModelProtocol",
    "ProtocolPolicy",
    "PROTOCOL_POLICIES",
    "get_protocol_policy",
]
