"""LiteLLM-compatible native-provider wire adapters.

These adapters keep the OpenAI Chat Completions *message shape* that LiteLLM
accepts for `anthropic/*` and `gemini/*` model prefixes, while advertising the
correct WireProtocol so protocol_resolver routes no longer hard-fail with
`unsupported_wire_protocol`.

They are not full re-implementations of Anthropic Messages REST or Gemini
generateContent REST; transport still goes through LiteLLM chat.completions.
"""

from __future__ import annotations

from ..protocols import WireProtocol
from .chat_completions import ChatCompletionsWireAdapter


class AnthropicMessagesWireAdapter(ChatCompletionsWireAdapter):
    """Anthropic native wire id + OpenAI-shaped body for LiteLLM anthropic/."""

    adapter_id = "anthropic_messages"
    wire_protocol = WireProtocol.ANTHROPIC_MESSAGES


class GeminiGenerateContentWireAdapter(ChatCompletionsWireAdapter):
    """Gemini native wire id + OpenAI-shaped body for LiteLLM gemini/."""

    adapter_id = "gemini_generate_content"
    wire_protocol = WireProtocol.GEMINI_GENERATE_CONTENT


__all__ = [
    "AnthropicMessagesWireAdapter",
    "GeminiGenerateContentWireAdapter",
]
