"""Provider-neutral semantic request types."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .provider_replay_state import ProviderReplayState
from .types import CanonicalToolCall, CanonicalToolResult


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(item) for item in value)
    return value


@dataclass(frozen=True)
class InvocationScope:
    session_id: str
    turn_id: str
    invocation_id: str
    iteration: int
    is_synthetic: bool = False

    def __post_init__(self) -> None:
        if not self.session_id.strip() or not self.turn_id.strip() or not self.invocation_id.strip():
            raise ValueError("invocation scope fields must be non-empty")
        if self.iteration < 0:
            raise ValueError("invocation scope iteration must be non-negative")

    @classmethod
    def for_synthetic(cls, *, invocation_id: str, purpose: str) -> InvocationScope:
        normalized = re.sub(r"[^a-z0-9_-]+", "-", str(purpose or "").strip().lower()).strip("-")
        if not normalized:
            raise ValueError("synthetic invocation scope requires purpose")
        return cls(
            session_id=f"synthetic:{normalized}",
            turn_id=f"synthetic:{normalized}:{invocation_id}",
            invocation_id=invocation_id,
            iteration=0,
            is_synthetic=True,
        )


@dataclass(frozen=True)
class CacheHint:
    mode: str

    def __post_init__(self) -> None:
        if self.mode != "ephemeral":
            raise ValueError("unsupported semantic cache hint")


@dataclass(frozen=True)
class TextPart:
    text: str
    cache_hint: CacheHint | None = None


@dataclass(frozen=True)
class ImagePart:
    uri: str
    media_type: str
    detail: str = ""
    cache_hint: CacheHint | None = None

    def __post_init__(self) -> None:
        if not self.uri.strip() or not self.media_type.strip():
            raise ValueError("semantic image part requires uri and media_type")


@dataclass(frozen=True)
class ToolCallPart:
    call: CanonicalToolCall


@dataclass(frozen=True)
class ToolResultPart:
    result: CanonicalToolResult


@dataclass(frozen=True)
class ReasoningReplayPart:
    replay_item_id: str

    def __post_init__(self) -> None:
        if not self.replay_item_id.strip():
            raise ValueError("reasoning replay part requires replay_item_id")


@dataclass(frozen=True)
class ReasoningTextPart:
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("reasoning text part requires text")


SemanticPart = TextPart | ImagePart | ToolCallPart | ToolResultPart | ReasoningReplayPart | ReasoningTextPart


@dataclass(frozen=True)
class SemanticMessage:
    role: str
    parts: tuple[SemanticPart, ...]

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise ValueError("semantic message requires role")
        object.__setattr__(self, "parts", tuple(self.parts))


class SemanticChainValidationError(ValueError):
    def __init__(self, code: str, message_index: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message_index = message_index


def validate_provider_ready_messages(messages: Sequence[SemanticMessage]) -> None:
    """Fail closed unless tool calls and results form one ordered complete chain."""

    pending_call_ids: list[str] = []
    seen_call_ids: set[str] = set()
    seen_result_ids: set[str] = set()
    for message_index, message in enumerate(messages):
        if pending_call_ids and message.role != "tool":
            raise SemanticChainValidationError(
                "interrupted_tool_chain",
                message_index,
                "unresolved tool calls must be completed before another semantic message",
            )
        if message.role == "tool" and (
            len(message.parts) != 1 or not isinstance(message.parts[0], ToolResultPart)
        ):
            raise SemanticChainValidationError(
                "non_atomic_tool_message",
                message_index,
                "tool messages must contain exactly one tool result",
            )
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                if message.role != "assistant":
                    raise SemanticChainValidationError(
                        "invalid_tool_call_role",
                        message_index,
                        "tool calls must belong to an assistant message",
                    )
                call_id = part.call.call_id.strip()
                if not call_id:
                    raise SemanticChainValidationError(
                        "invalid_tool_call_id",
                        message_index,
                        "tool call requires a non-empty call id",
                    )
                if call_id in seen_call_ids:
                    raise SemanticChainValidationError(
                        "duplicate_tool_call_id",
                        message_index,
                        f"duplicate tool call id `{call_id}`",
                    )
                seen_call_ids.add(call_id)
                pending_call_ids.append(call_id)
            elif isinstance(part, ToolResultPart):
                if message.role != "tool":
                    raise SemanticChainValidationError(
                        "invalid_tool_result_role",
                        message_index,
                        "tool results must belong to a tool message",
                    )
                call_id = part.result.call_id.strip()
                if call_id in seen_result_ids:
                    raise SemanticChainValidationError(
                        "duplicate_tool_result",
                        message_index,
                        f"duplicate tool result for `{call_id}`",
                    )
                if call_id not in seen_call_ids:
                    raise SemanticChainValidationError(
                        "orphan_tool_result",
                        message_index,
                        f"tool result `{call_id}` has no preceding call",
                    )
                if call_id not in pending_call_ids:
                    raise SemanticChainValidationError(
                        "orphan_tool_result",
                        message_index,
                        f"tool result `{call_id}` does not match an unresolved call",
                    )
                pending_call_ids.remove(call_id)
                seen_result_ids.add(call_id)
    if pending_call_ids:
        raise SemanticChainValidationError(
            "unresolved_tool_call",
            max(0, len(messages) - 1),
            f"tool call `{pending_call_ids[0]}` has no matching result",
        )


@dataclass(frozen=True)
class SemanticToolDefinition:
    name: str
    input_schema: Mapping[str, Any]
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("semantic tool definition requires name")
        object.__setattr__(self, "input_schema", _freeze_value(self.input_schema))


@dataclass(frozen=True)
class SemanticGenerationSettings:
    max_output_tokens: int
    stream: bool = False
    temperature: float | None = None
    top_p: float | None = None
    tool_choice: str = "auto"

    def __post_init__(self) -> None:
        if self.max_output_tokens <= 0:
            raise ValueError("semantic generation settings require positive max_output_tokens")


@dataclass(frozen=True)
class SemanticModelRequest:
    scope: InvocationScope
    messages: tuple[SemanticMessage, ...]
    tools: tuple[SemanticToolDefinition, ...]
    settings: SemanticGenerationSettings
    replay_state: ProviderReplayState | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))


__all__ = [
    "CacheHint",
    "ImagePart",
    "InvocationScope",
    "ReasoningReplayPart",
    "ReasoningTextPart",
    "SemanticChainValidationError",
    "SemanticGenerationSettings",
    "SemanticMessage",
    "SemanticModelRequest",
    "SemanticToolDefinition",
    "TextPart",
    "ToolCallPart",
    "ToolResultPart",
    "validate_provider_ready_messages",
]
