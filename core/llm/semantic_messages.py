"""Provider-neutral semantic request types."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

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
class TextPart:
    text: str


@dataclass(frozen=True)
class ImagePart:
    uri: str
    media_type: str
    detail: str = ""

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


SemanticPart = TextPart | ImagePart | ToolCallPart | ToolResultPart | ReasoningReplayPart


@dataclass(frozen=True)
class SemanticMessage:
    role: str
    parts: tuple[SemanticPart, ...]

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise ValueError("semantic message requires role")
        object.__setattr__(self, "parts", tuple(self.parts))


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
