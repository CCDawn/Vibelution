# -*- coding: utf-8 -*-
"""LLM 子系统核心类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

if TYPE_CHECKING:
    from .provider_replay_state import ProviderReplayState


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(item) for item in value)
    return value


@dataclass
class LLMCapabilities:
    supports_streaming: bool = True
    supports_tool_calling: bool = True
    supports_parallel_tool_calls: bool = False
    supports_system_messages: bool = True
    supports_json_mode: bool = False
    supports_model_discovery: bool = True
    supports_image_input: bool = False
    supports_prompt_cache: bool = False
    supports_thinking: bool = False
    supports_reasoning_roundtrip: bool = False
    supports_explicit_tool_choice: bool = True
    supports_stream_usage: bool = False
    supports_strict_json_schema: bool = False
    supports_responses_transport: bool = False
    supports_structured_content: bool = False


@dataclass
class UsageStats:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    reasoning_output_tokens: int = 0
    provider_raw_usage: Dict[str, Any] = field(default_factory=dict)
    estimated_cost: float = 0.0
    latency_ms: int = 0


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    raw_arguments: Any = None
    provider_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedModelSpec:
    provider: str
    profile_id: str
    model: str
    transport: str
    contract: str
    context_window: int
    capabilities: LLMCapabilities
    discovery_status: str = "configured"
    max_output_tokens: int = 0
    reasoning_state_field: str = ""
    strict_compatibility: bool = True
    provider_details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagnosticReport:
    ok: bool
    provider: str
    profile_id: str
    model: str
    messages: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    resolved_spec: Optional[ResolvedModelSpec] = None


@dataclass
class StreamChunk:
    type: str
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Optional[UsageStats] = None
    provider_payload: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass(frozen=True)
class CanonicalItemIdentity:
    session_id: str
    turn_id: str
    invocation_id: str
    iteration: int
    item_id: str
    item_revision: int = 0

    def __post_init__(self) -> None:
        if not self.session_id.strip() or not self.invocation_id.strip():
            raise ValueError("canonical identity requires session_id and invocation_id")
        if self.iteration < 0 or self.item_revision < 0:
            raise ValueError("canonical identity counters must be non-negative")


@dataclass(frozen=True)
class CanonicalToolCall:
    identity: CanonicalItemIdentity
    call_id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    provider_item_id: str = ""

    def __post_init__(self) -> None:
        if not self.call_id.strip() or not self.name.strip():
            raise ValueError("canonical tool call requires call_id and name")
        object.__setattr__(self, "arguments", _freeze_value(self.arguments))


@dataclass(frozen=True)
class CanonicalToolResult:
    identity: CanonicalItemIdentity
    call_id: str
    tool_name: str
    output: Any
    status: str = "completed"
    is_error: bool = False

    def __post_init__(self) -> None:
        if not self.call_id.strip():
            raise ValueError("canonical tool result requires call_id")
        object.__setattr__(self, "output", _freeze_value(self.output))


LLM_PROTOCOL_EVENT_KINDS = frozenset(
    {
        "turn_started",
        "reasoning_delta",
        "commentary_delta",
        "interim_text_delta",
        "answer_delta",
        "item_completed",
        "tool_call_started",
        "tool_arguments_delta",
        "tool_call_ready",
        "usage_updated",
        "turn_completed",
        "turn_incomplete",
        "turn_failed",
        "turn_cancelled",
    }
)


@dataclass(frozen=True)
class LLMProtocolEvent:
    kind: str
    sequence: int
    session_id: str
    invocation_id: str
    iteration: int
    turn_id: str = ""
    item_id: str = ""
    response_id: str = ""
    item_revision: int = 0
    call_id: str = ""
    channel: str = ""
    phase: str = ""
    status: str = ""
    text: str = ""
    tool_name: str = ""
    arguments_delta: str = ""
    provisional: bool = False
    terminal: bool = False
    provider_event_type: str = ""
    diagnostic_summary: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in LLM_PROTOCOL_EVENT_KINDS:
            raise ValueError(f"unknown canonical protocol event kind `{self.kind}`")
        if self.sequence < 0:
            raise ValueError("canonical event sequence must be non-negative")
        if not self.session_id.strip() or not self.invocation_id.strip():
            raise ValueError("canonical event requires session_id and invocation_id")
        if len(self.diagnostic_summary) > 32:
            raise ValueError("canonical event diagnostic summary exceeds field limit")
        forbidden = ("raw", "payload", "prompt", "argument", "secret", "api_key", "replay", "opaque")
        for key in self.diagnostic_summary:
            normalized = str(key).strip().lower()
            if any(marker in normalized for marker in forbidden):
                raise ValueError(f"unsafe canonical event diagnostic field `{key}`")
        object.__setattr__(self, "diagnostic_summary", _freeze_value(self.diagnostic_summary))

    @property
    def identity(self) -> CanonicalItemIdentity:
        return CanonicalItemIdentity(
            session_id=self.session_id,
            turn_id=self.turn_id,
            invocation_id=self.invocation_id,
            iteration=self.iteration,
            item_id=self.item_id,
            item_revision=self.item_revision,
        )


TURN_OUTCOME_KINDS = frozenset({"tool_calls", "final_answer", "incomplete", "failed", "cancelled"})


@dataclass(frozen=True)
class TurnOutcome:
    kind: str
    identity: CanonicalItemIdentity
    events: tuple[LLMProtocolEvent, ...] = ()
    tool_calls: tuple[CanonicalToolCall, ...] = ()
    tool_results: tuple[CanonicalToolResult, ...] = ()
    final_text: str = ""
    pending_tool_call_ids: tuple[str, ...] = ()
    terminal_event_seen: bool = False
    error: str = ""
    replay_state: ProviderReplayState | None = None

    def __post_init__(self) -> None:
        if self.kind not in TURN_OUTCOME_KINDS:
            raise ValueError(f"unknown turn outcome kind `{self.kind}`")
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        object.__setattr__(self, "tool_results", tuple(self.tool_results))
        object.__setattr__(self, "pending_tool_call_ids", tuple(self.pending_tool_call_ids))
        if self.kind == "final_answer" and (not self.terminal_event_seen or self.pending_tool_call_ids):
            raise ValueError("final_answer requires a terminal event and no pending tool calls")

    @classmethod
    def final_answer(
        cls,
        *,
        identity: CanonicalItemIdentity,
        text: str,
        events: tuple[LLMProtocolEvent, ...] = (),
        replay_state: ProviderReplayState | None = None,
    ) -> TurnOutcome:
        return cls(
            kind="final_answer",
            identity=identity,
            events=events,
            final_text=text,
            terminal_event_seen=True,
            replay_state=replay_state,
        )


class LLMError(RuntimeError):
    """统一的 LLM 错误类型。"""

    def __init__(
        self,
        category: str,
        message: str,
        *,
        retryable: bool = False,
        provider: str = "",
        model: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.provider = provider
        self.model = model
        self.details = details or {}
