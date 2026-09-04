# -*- coding: utf-8 -*-
"""统一 LLM client。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections import deque
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import quote, urlparse

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, SystemMessage, ToolMessage

from config import AppConfig, get_config
from config.llm_security import is_llm_local_network_base_url
from config.models import (
    DEFAULT_LLM_ROUTE_CONCURRENCY,
    DEFAULT_LLM_ROUTE_GATE_WAIT_SECONDS,
    DEFAULT_LLM_STREAM_TOTAL_DEADLINE_SECONDS,
)
from core.context.volatility import is_volatile_context_text

from .adapters import get_provider_adapter
from .discovery import discover_model
from .errors import classify_exception
from .message_projector import message_to_openai_dict as project_message_to_openai_dict
from .payload_builder import PayloadBuildInput, compose_runtime_wire_payload
from .payload_trace import build_llm_payload_trace
from .payload_validator import payload_protocol_summary
from .protocol_resolver import ProtocolResolutionError, resolve_model_protocol
from .protocols import ModelProtocol, WireProtocol
from .reasoning_extractor import extract_reasoning_text, strip_think_tag_reasoning
from .responses_websocket import (
    RESPONSES_WEBSOCKET_TRANSPORT_KEY,
    ResponsesWebSocketBackend,
)
from .schema import sanitize_tool_schema
from .stream_http_timing import (
    capture_stream_http_timings,
    classify_raw_stream_event,
    current_stream_http_timings,
)
from .streaming import ResponsesStreamNormalizer, extract_message_tool_calls, extract_text_content
from .semantic_messages import SemanticGenerationSettings, SemanticOutputSchema
from .semantic_projector import SemanticProjectionError, SemanticProjectionInput, project_semantic_request
from .types import LLMCapabilities, LLMError, LLMOutputTruncatedError, LLMProtocolEvent, LLMRouteGateTimeoutError, LLMStreamTotalDeadlineError, StreamChunk, ToolCall, TurnOutcome, UsageStats
from .usage import read_usage_int as _read_provider_usage_int
from .usage import cache_usage_observation_from_payload, usage_stats_from_payload, usage_to_dict
from .wire.registry import build_default_wire_adapter_registry
from .wire.chat_completions import STREAM_EXHAUSTED_WITHOUT_FINISH_REASON
from .wire.chat_completions import OUTPUT_LENGTH_TRUNCATED, TOOL_ARGUMENTS_UNPARSABLE
from .wire.responses import STREAM_EXHAUSTED_WITHOUT_TERMINAL


_LITELLM_LOCAL_MODEL_COST_MAP_ENV = "LITELLM_LOCAL_MODEL_COST_MAP"


def _configure_litellm_import_environment() -> None:
    """Keep LiteLLM import off the provider request network path by default."""

    os.environ.setdefault(_LITELLM_LOCAL_MODEL_COST_MAP_ENV, "True")


_configure_litellm_import_environment()

_LLM_STATUS_CONTEXT: ContextVar[Dict[str, str]] = ContextVar(
    "vibelution_llm_status_context",
    default={},
)
_LLM_CANCEL_CHECKER_CONTEXT: ContextVar[Callable[[], str] | None] = ContextVar(
    "vibelution_llm_cancel_checker",
    default=None,
)
_LLM_CHAT_PROVIDER_ABORT_CONTEXT: ContextVar[bool] = ContextVar(
    "vibelution_llm_chat_provider_abort_enabled",
    default=False,
)
_LLM_ROUTE_CONCURRENCY_LIMIT: int | None = None
_LLM_ROUTE_CONCURRENCY_LOCK = threading.Lock()
_LLM_ROUTE_CONCURRENCY_GATES: Dict[str, threading.BoundedSemaphore] = {}

# --- LLM 流式调用活性治理（route gate 有界等待 + 流总时长硬上限）---
# 两者都是惰性逐请求解析：in-process override（测试/嵌入方）优先，其次 env
# （钳制到安全范围），最后是打包默认值。导入时不读 env，与
# `_resolve_llm_route_concurrency_limit` 的懒解析惯例一致。
# 默认值（含「不小于挑战 per-call fence 800s」的约束说明）统一登记在
# config/models.py；这里只保留 env 名与安全钳制范围。
_LLM_ROUTE_GATE_WAIT_ENV = "VIBELUTION_LLM_ROUTE_GATE_WAIT_SECONDS"
_LLM_ROUTE_GATE_WAIT_DEFAULT_SECONDS = DEFAULT_LLM_ROUTE_GATE_WAIT_SECONDS
_LLM_ROUTE_GATE_WAIT_MIN_SECONDS = 1.0
_LLM_ROUTE_GATE_WAIT_MAX_SECONDS = 600.0
_LLM_ROUTE_GATE_WAIT_LIMIT: float | None = None

_LLM_STREAM_TOTAL_DEADLINE_ENV = "VIBELUTION_LLM_STREAM_TOTAL_DEADLINE_SECONDS"
_LLM_STREAM_TOTAL_DEADLINE_DEFAULT_SECONDS = DEFAULT_LLM_STREAM_TOTAL_DEADLINE_SECONDS
_LLM_STREAM_TOTAL_DEADLINE_MIN_SECONDS = 60.0
_LLM_STREAM_TOTAL_DEADLINE_MAX_SECONDS = 3600.0
_LLM_STREAM_TOTAL_DEADLINE_LIMIT: float | None = None

# 看 watchdog「真断连」用的 turn-scoped 取消态与在途流 closer 登记。key 是
# 规范化的 turn 身份（chat_room 讲者调用是 "chat-room:{round}:{participant}"）。
_LLM_TURN_CANCEL_STATES: Dict[str, tuple[str, float]] = {}
_LLM_TURN_CANCEL_STATES_LOCK = threading.Lock()
_LLM_TURN_CANCEL_STATE_TTL_SECONDS = 3600.0
_LLM_ACTIVE_STREAM_CLOSE_HOOKS: Dict[str, set] = {}
_LLM_ACTIVE_STREAM_CLOSE_HOOKS_LOCK = threading.Lock()


def _clamp_env_seconds(
    raw: Any,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value != value or value in (float("inf"), float("-inf")):
        return default
    return max(minimum, min(maximum, value))


def _llm_route_gate_wait_seconds() -> float:
    """Bounded wait budget for the per-route concurrency gate."""

    override = _LLM_ROUTE_GATE_WAIT_LIMIT
    if isinstance(override, (int, float)) and not isinstance(override, bool) and override > 0:
        return float(override)
    return _clamp_env_seconds(
        os.environ.get(_LLM_ROUTE_GATE_WAIT_ENV),
        default=_LLM_ROUTE_GATE_WAIT_DEFAULT_SECONDS,
        minimum=_LLM_ROUTE_GATE_WAIT_MIN_SECONDS,
        maximum=_LLM_ROUTE_GATE_WAIT_MAX_SECONDS,
    )


def _llm_stream_total_deadline_seconds() -> float:
    """Hard wall-clock ceiling for one streaming attempt."""

    override = _LLM_STREAM_TOTAL_DEADLINE_LIMIT
    if isinstance(override, (int, float)) and not isinstance(override, bool) and override > 0:
        return float(override)
    return _clamp_env_seconds(
        os.environ.get(_LLM_STREAM_TOTAL_DEADLINE_ENV),
        default=_LLM_STREAM_TOTAL_DEADLINE_DEFAULT_SECONDS,
        minimum=_LLM_STREAM_TOTAL_DEADLINE_MIN_SECONDS,
        maximum=_LLM_STREAM_TOTAL_DEADLINE_MAX_SECONDS,
    )


def _stream_force_close_targets(stream: Any) -> list:
    """Collect the objects whose ``close`` can unwind a blocked stream read.

    Covers plain iterators (``close``), OpenAI SDK ``Stream`` (``response``
    httpx response, ``response_cm``) and litellm wrappers (``_response``).
    Every close is best-effort: a blocked socket read raises and unwinds,
    which is exactly the goal.
    """

    targets = []
    seen_ids = set()

    def _push(candidate: Any) -> Any:
        if candidate is None or id(candidate) in seen_ids:
            return None
        seen_ids.add(id(candidate))
        targets.append(candidate)
        return candidate

    cursor = _push(stream)
    for _ in range(3):
        if cursor is None:
            break
        cursor = _push(getattr(cursor, "response", None) or getattr(cursor, "_response", None))
    _push(getattr(stream, "response_cm", None))
    return targets


def force_close_llm_stream(stream: Any) -> None:
    """Best-effort force close of an in-flight provider stream."""

    for target in _stream_force_close_targets(stream):
        close = getattr(target, "close", None)
        if not callable(close):
            continue
        try:
            close()
        except Exception:
            continue


def _register_llm_stream_close_hook(turn_key: str, hook: Callable[[], None]) -> None:
    normalized = str(turn_key or "").strip()
    if not normalized:
        return
    with _LLM_ACTIVE_STREAM_CLOSE_HOOKS_LOCK:
        _LLM_ACTIVE_STREAM_CLOSE_HOOKS.setdefault(normalized, set()).add(hook)


def _unregister_llm_stream_close_hook(turn_key: str, hook: Callable[[], None]) -> None:
    normalized = str(turn_key or "").strip()
    if not normalized:
        return
    with _LLM_ACTIVE_STREAM_CLOSE_HOOKS_LOCK:
        hooks = _LLM_ACTIVE_STREAM_CLOSE_HOOKS.get(normalized)
        if hooks is not None:
            hooks.discard(hook)
            if not hooks:
                _LLM_ACTIVE_STREAM_CLOSE_HOOKS.pop(normalized, None)


def request_llm_stream_close_for_turn(turn_key: str) -> int:
    """Force-close every in-flight provider stream registered for a turn.

    Returns the number of close attempts. Best-effort by design: hooks are
    idempotent and swallow close failures so a watchdog caller can never be
    blocked by a dying connection.
    """

    normalized = str(turn_key or "").strip()
    if not normalized:
        return 0
    with _LLM_ACTIVE_STREAM_CLOSE_HOOKS_LOCK:
        hooks = set(_LLM_ACTIVE_STREAM_CLOSE_HOOKS.get(normalized) or ())
    attempts = 0
    for hook in hooks:
        attempts += 1
        try:
            hook()
        except Exception:
            continue
    return attempts


def cancel_llm_turn_scope(turn_key: str, reason: str) -> int:
    """Mark a turn scope cancelled and force-close its in-flight streams.

    This is the chat-room speaker watchdog path: the abandoned runner thread
    observes the reason through ``_raise_if_llm_cancelled`` (so its retry loop
    stops), and its blocked provider stream is force-closed so the route
    concurrency slot is returned promptly. Ordinary turns never set this
    state, so their cancellation semantics are unchanged.
    """

    normalized = str(turn_key or "").strip()
    normalized_reason = str(reason or "").strip() or "turn scope cancelled by watchdog"
    if not normalized:
        return 0
    now = time.time()
    with _LLM_TURN_CANCEL_STATES_LOCK:
        stale = [
            key
            for key, (_, marked_at) in _LLM_TURN_CANCEL_STATES.items()
            if now - marked_at > _LLM_TURN_CANCEL_STATE_TTL_SECONDS
        ]
        for key in stale:
            _LLM_TURN_CANCEL_STATES.pop(key, None)
        _LLM_TURN_CANCEL_STATES[normalized] = (normalized_reason, now)
    return request_llm_stream_close_for_turn(normalized)


def clear_llm_turn_scope_cancel(turn_key: str) -> None:
    """Clear a turn-scoped cancellation so a fresh turn with the same identity
    (chat-room fence retry) is not insta-cancelled by a stale watchdog flag."""

    normalized = str(turn_key or "").strip()
    if not normalized:
        return
    with _LLM_TURN_CANCEL_STATES_LOCK:
        _LLM_TURN_CANCEL_STATES.pop(normalized, None)
_LLM_BACKEND_ATTEMPT_CONTEXT: ContextVar[tuple[int, int]] = ContextVar(
    "vibelution_llm_backend_attempt",
    default=(1, 0),
)
_MODEL_INVOCATION_RECEIPT_CONTEXT: ContextVar[Mapping[str, Any] | None] = (
    ContextVar("vibelution_model_invocation_receipt_context", default=None)
)
_MODEL_INVOCATION_RECEIPT_OUTCOME_KINDS = frozenset(
    {"candidate", "review", "revision", "plan", "final_output", "source_evidence"}
)
_NO_PROXY_LOCK = threading.Lock()
_NO_PROXY_ENV_NAMES = ("NO_PROXY", "no_proxy")
_PROXY_ENV_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_PROXY_ENV_CONDITION = threading.Condition(threading.RLock())
_PROXY_ENV_STATE = {"readers": 0, "writer": False}
PROMPT_CACHE_OPPORTUNITY_PREFIX_CHARS = 4096
# Controlled per-call output clamp channel: callers (e.g. the structured
# review chain) may pass this metadata key with a positive int so the payload
# carries a smaller ``max_tokens``/``max_output_tokens`` than the profile
# default, without mutating operator config or the shared profile.  Invalid
# values are ignored and the profile default stays authoritative; the
# invocation budget preflight still clamps on top of the result.
MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY = "llmMaxOutputTokensOverride"
_CANONICAL_WIRE_ADAPTERS = build_default_wire_adapter_registry()
_PROVIDER_ABORT_UNAVAILABLE_EVENT_CODE = "llm.provider_abort_unavailable"
# Bounded residual-risk diagnostics: emit at most one scene event per
# (transport, purpose, reason) per process so repeated watcher-skip paths
# cannot flood the scene log on long Challenge sessions.
_PROVIDER_ABORT_UNAVAILABLE_EMIT_LOCK = threading.Lock()
_PROVIDER_ABORT_UNAVAILABLE_EMITTED: set[tuple[str, str, str]] = set()


def _max_output_tokens_override_from_metadata(
    metadata: Optional[Mapping[str, Any]],
) -> int | None:
    """Resolve the controlled per-call output clamp from invocation metadata."""

    if not isinstance(metadata, Mapping):
        return None
    value = metadata.get(MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


@contextmanager
def model_invocation_receipt_context_scope(
    context: Mapping[str, Any] | None,
) -> Iterator[None]:
    """Bind a server-resolved question invocation scope to nested LLM calls."""

    normalized = dict(context) if isinstance(context, Mapping) else None
    token = _MODEL_INVOCATION_RECEIPT_CONTEXT.set(normalized)
    try:
        yield
    finally:
        _MODEL_INVOCATION_RECEIPT_CONTEXT.reset(token)


def _receipt_output_hash(outcome: TurnOutcome) -> str:
    """Hash the canonical JSON answer when the model returned one.

    Challenge output registration uses the same ``audit.output_sha256`` zeroing
    rule. Plain text replies still receive a deterministic content digest; the
    owning adapter may replace it with its canonical artifact hash before
    promotion.
    """

    text = str(getattr(outcome, "final_text", "") or "")
    candidate = text.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]).strip()
        if candidate.lower().startswith("json\n"):
            candidate = candidate[5:].lstrip()
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, dict):
        audit = parsed.setdefault("audit", {})
        if isinstance(audit, dict):
            audit["output_sha256"] = "0" * 64
        material = json.dumps(
            parsed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    else:
        material = text.encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _canonical_receipt_response_summary(outcome: TurnOutcome) -> dict[str, Any]:
    """Return a bounded response summary from the canonical turn outcome.

    Streaming provider events are transport details and may contain sensitive or
    very large payloads.  The canonical outcome already owns the durable answer
    facts, so receipt construction only needs a bounded text excerpt and safe
    outcome counts.  The full canonical answer remains addressable by the
    separately recorded output digest/evidence locator.
    """

    return {
        "kind": str(getattr(outcome, "kind", "") or "").strip(),
        "finalText": str(getattr(outcome, "final_text", "") or "")[:1024],
        "toolCallCount": len(tuple(getattr(outcome, "tool_calls", ()) or ())),
        "pendingToolCallCount": len(
            tuple(getattr(outcome, "pending_tool_call_ids", ()) or ())
        ),
        "terminalEventSeen": bool(getattr(outcome, "terminal_event_seen", False)),
    }


def _canonical_receipt_request_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Hash the real conversation while exposing only bounded shape metadata."""

    conversation = _payload_conversation_items(dict(payload)) or []
    material = json.dumps(
        conversation,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda value: (
            f"<{type(value).__module__}.{type(value).__qualname__}>"
        ),
    ).encode("utf-8")
    return {
        "conversationSha256": hashlib.sha256(material).hexdigest(),
        "messageCount": len(conversation),
        "payloadShape": _safe_payload_shape_summary(dict(payload)),
    }


def _is_retryable_stream_exhaustion(outcome: TurnOutcome, *, allow_chat: bool = False) -> bool:
    if outcome.kind != "incomplete":
        return False
    if outcome.error == STREAM_EXHAUSTED_WITHOUT_TERMINAL:
        return True
    # Truncated tool-call arguments are always provider-stream corruption:
    # resending the same request is the only safe recovery.
    if outcome.error == TOOL_ARGUMENTS_UNPARSABLE:
        return True
    return allow_chat and outcome.error == STREAM_EXHAUSTED_WITHOUT_FINISH_REASON


def _raise_if_output_truncated(outcome: TurnOutcome, *, provider: str, model: str, phase: str) -> None:
    """Convert a provider length-truncation terminal into an explicit error.

    ``finish_reason == "length"`` (marker ``OUTPUT_LENGTH_TRUNCATED``) means
    the model hit the output-token ceiling mid-generation. Raising at the
    outcome-assembly point — before any downstream consumer sees the outcome —
    keeps truncated prose from being persisted as a complete answer and stops a
    truncated structured (json_schema) payload from paying a full-price
    ContractValidationError re-burn downstream; it surfaces instead as
    ``LLMOutputTruncatedError`` (chat_room errorType = class name).
    Not retryable: resending the same request reproduces the same ceiling.

    TODO(retry-hook): a one-shot *downgraded retry* for truncated structured
    purposes (lower thinking effort / smaller ceiling, see
    ``_purpose_max_output_tokens`` in team_workflow llm_review_runners) would
    attach at this call site. Deliberately not implemented here.
    """

    if outcome.kind == "incomplete" and str(outcome.error or "") == OUTPUT_LENGTH_TRUNCATED:
        raise LLMOutputTruncatedError(
            provider=provider,
            model=model,
            details={"phase": phase, "terminal_reason": outcome.error},
        )


def _safe_semantic_projection_snapshot(messages: List[Any]) -> Dict[str, Any]:
    shape_tail: list[dict[str, Any]] = []
    assistant_tool_calls = 0
    tool_results = 0
    for message in list(messages or []):
        role = str(
            (message.get("role") if isinstance(message, dict) else getattr(message, "type", ""))
            or ""
        ).strip().lower()
        role = {"ai": "assistant", "human": "user"}.get(role, role)
        tool_calls = (
            message.get("tool_calls") if isinstance(message, dict) else getattr(message, "tool_calls", None)
        ) or []
        assistant_tool_calls += len(tool_calls) if role == "assistant" else 0
        tool_results += 1 if role == "tool" else 0
        shape_tail.append({"role": role, "toolCallCount": len(tool_calls)})
    bounded_tail = shape_tail[-8:]
    shape_hash = hashlib.sha256(
        json.dumps(bounded_tail, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "payloadMessageAssistantToolCallCount": assistant_tool_calls,
        "payloadMessageToolResultCount": tool_results,
        "payloadMessageShapeHash": shape_hash,
        "payloadMessageShapeTail": bounded_tail,
    }


def _normalize_semantic_messages_with_adapter(messages: List[Any], adapter: Any) -> List[Any]:
    role_envelopes: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        raw_role = message.get("role") if isinstance(message, dict) else getattr(message, "type", "")
        role = {"ai": "assistant", "human": "user"}.get(
            str(raw_role or "").strip().lower(),
            str(raw_role or "").strip().lower(),
        )
        role_envelopes.append({"role": role, "messageIndex": index})
    normalized_roles = adapter.messages(role_envelopes)
    normalized_messages: list[Any] = []
    for index, message in enumerate(messages):
        original_role = str(role_envelopes[index].get("role") or "").strip().lower()
        normalized_role = str(normalized_roles[index].get("role") or original_role).strip().lower()
        if normalized_role == original_role:
            normalized_messages.append(message)
            continue
        if isinstance(message, dict):
            converted = dict(message)
            converted["role"] = normalized_role
        else:
            converted = {
                "role": normalized_role,
                "content": getattr(message, "content", ""),
            }
        normalized_messages.append(converted)
    return normalized_messages


class LLMCancelledError(Exception):
    """Raised when an active turn requests cancellation before more LLM work."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason or "LLM call cancelled.")
        self.reason = str(reason or "").strip()


def _find_ui_tool_calls_message_index(messages: List[Any]) -> int:
    for index, message in enumerate(list(messages or [])):
        if isinstance(message, dict) and "toolCalls" in message:
            return index
    return -1


_RESPONSE_CALL_ID_SUFFIX_PATTERN = re.compile(r"-resp-\d+$")


def _next_response_tool_call_id(original_id: str, known_ids: set) -> str:
    """Return the next free ``<base>-resp-<n>`` id for a replayed call id.

    GLM-style providers replay an id they can already see in the request
    chain when a turn is nudged to continue. The replayed id is renamed
    before it enters the journal or the next request so the chain never
    carries two calls claiming one id. A prior ``-resp-<n>`` suffix is
    stripped from the base first, so suffixes never stack.
    """

    base = _RESPONSE_CALL_ID_SUFFIX_PATTERN.sub("", original_id) or original_id
    counter = 1
    while True:
        candidate = f"{base}-resp-{counter}"
        if candidate not in known_ids:
            return candidate
        counter += 1


def _dedupe_outcome_tool_calls_against_chain(
    outcome: Any,
    messages: List[Any],
) -> Any:
    """Rename outcome tool call ids that collide with the request chain.

    Runs on the canonical ``TurnOutcome`` right after decode, before the
    outcome reaches the agent loop, the journal, or the next request build.
    Only in-memory canonical objects are replaced (copy-on-write); a renamed
    call keeps its provider item identity so receipts stay traceable, while
    ``pending_tool_call_ids`` and any already-decoded ``tool_results`` follow
    the rename so pairing stays intact. When nothing collides the outcome is
    returned unchanged.
    """

    if outcome is None or not getattr(outcome, "tool_calls", None):
        return outcome
    from core.chat.model_messages import collect_chain_tool_call_ids

    known_ids = set(collect_chain_tool_call_ids(messages))
    known_ids.update(str(result.call_id or "") for result in (outcome.tool_results or ()))
    rename_queues: Dict[str, "deque[str]"] = {}
    rename_pairs: List[Tuple[str, str]] = []
    renamed_calls = []
    for call in outcome.tool_calls:
        call_id = str(call.call_id or "").strip()
        if not call_id or call_id not in known_ids:
            known_ids.add(call_id)
            renamed_calls.append(call)
            continue
        new_id = _next_response_tool_call_id(call_id, known_ids)
        known_ids.add(new_id)
        rename_pairs.append((call_id, new_id))
        rename_queues.setdefault(call_id, deque()).append(new_id)
        renamed_calls.append(replace(call, call_id=new_id))
    if not rename_pairs:
        return outcome

    def _renamed_ids(sequence: Any) -> List[str]:
        queues = {old_id: deque(new_ids) for old_id, new_ids in rename_queues.items()}
        mapped: List[str] = []
        for call_id in sequence:
            call_id = str(call_id or "")
            queue = queues.get(call_id)
            mapped.append(queue.popleft() if queue else call_id)
        return mapped

    renamed_results = tuple(
        replace(result, call_id=_renamed_ids([str(result.call_id)])[0])
        if str(result.call_id) in rename_queues
        else result
        for result in (outcome.tool_results or ())
    )
    return replace(
        outcome,
        tool_calls=tuple(renamed_calls),
        tool_results=renamed_results,
        pending_tool_call_ids=tuple(_renamed_ids(outcome.pending_tool_call_ids or ())),
    )


def _current_llm_cancel_reason() -> str:
    checker = _LLM_CANCEL_CHECKER_CONTEXT.get(None)
    if callable(checker):
        try:
            reason = str(checker() or "").strip()
        except Exception:
            reason = ""
        if reason:
            return reason
    # Turn-scoped cancellation (speaker watchdog abandon): only visible when
    # a watchdog actually marked this turn identity, so ordinary turns keep
    # their exact prior semantics.
    status_context = _LLM_STATUS_CONTEXT.get({}) or {}
    turn_key = str(
        status_context.get("turnId")
        or status_context.get("turn_id")
        or ""
    ).strip()
    if turn_key and _LLM_TURN_CANCEL_STATES:
        with _LLM_TURN_CANCEL_STATES_LOCK:
            entry = _LLM_TURN_CANCEL_STATES.get(turn_key)
        if entry is not None:
            return str(entry[0] or "").strip()
    return ""


def _raise_if_llm_cancelled() -> None:
    reason = _current_llm_cancel_reason()
    if reason:
        raise LLMCancelledError(reason)


def _sleep_with_llm_cancel_check(wait_seconds: float) -> None:
    deadline = time.time() + max(0.0, float(wait_seconds or 0.0))
    while True:
        _raise_if_llm_cancelled()
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        time.sleep(min(0.1, remaining))


def _llm_route_concurrency_key(provider: Any, profile: Any, *, profile_id: str) -> str:
    provider_kind = str(getattr(provider, "kind", "") or "").strip().lower() or "unknown"
    base_url = str(getattr(provider, "base_url", "") or "").strip().lower()
    model = str(getattr(profile, "model", "") or "").strip().lower() or "unknown"
    return "|".join((provider_kind, base_url, model, str(profile_id or "").strip()))


def _llm_route_concurrency_gate(route_key: str, *, limit: int) -> threading.BoundedSemaphore:
    with _LLM_ROUTE_CONCURRENCY_LOCK:
        gate = _LLM_ROUTE_CONCURRENCY_GATES.get(route_key)
        if gate is None:
            gate = threading.BoundedSemaphore(limit)
            _LLM_ROUTE_CONCURRENCY_GATES[route_key] = gate
        return gate


def _resolve_llm_route_concurrency_limit(config: Any = None) -> int:
    """Resolve the per-route concurrency limit lazily per request.

    ``_LLM_ROUTE_CONCURRENCY_LIMIT`` stays as an in-process override channel
    (tests monkeypatch it); otherwise the limit comes from the caller's
    ``[llm]`` config (``route_concurrency``), and missing/invalid values fall
    back to the packaged default. Nothing is read at import time, and the
    per-route gate keying is unchanged: existing gates keep their semaphore.
    """

    override = _LLM_ROUTE_CONCURRENCY_LIMIT
    if isinstance(override, int) and not isinstance(override, bool) and override >= 1:
        return override
    value = getattr(getattr(config, "llm", None), "route_concurrency", None)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    return DEFAULT_LLM_ROUTE_CONCURRENCY


@contextmanager
def _reserve_llm_route_slot(
    route_key: str,
    *,
    limit: int,
    role: str,
    profile_id: str,
    provider: str,
    model: str,
    phase: str,
    message_count: int,
    tool_count: int,
):
    gate = _llm_route_concurrency_gate(route_key, limit=limit)
    wait_started = time.time()
    gate_wait_budget = _llm_route_gate_wait_seconds()
    gate_wait_started_monotonic = time.monotonic()
    acquired_immediately = gate.acquire(blocking=False)
    if not acquired_immediately:
        _record_llm_scene_event(
            "concurrency",
            "llm.concurrency.waiting",
            message="LLM route concurrency gate is waiting for a free slot.",
            outcome="waiting",
            fields={
                "role": role,
                "profileId": profile_id,
                "provider": provider,
                "model": model,
                "phase": phase,
                "routeKeyHash": _short_hash(route_key),
                "limit": limit,
                "messageCount": message_count,
                "toolCount": tool_count,
            },
            lifecycle=False,
        )
        while True:
            acquired = gate.acquire(timeout=0.1)
            if acquired:
                break
            _raise_if_llm_cancelled()
            # 有界等待：上限由 VIBELUTION_LLM_ROUTE_GATE_WAIT_SECONDS 控制
            #（默认 120s，钳制 1-600s）。之前这里是无上限自旋，被遗弃的
            # 讲者线程只要还持有槽位就能让同路由后续调用全部永久排队。
            remaining = gate_wait_budget - (time.monotonic() - gate_wait_started_monotonic)
            if remaining <= 0:
                raise LLMRouteGateTimeoutError(
                    wait_seconds=gate_wait_budget,
                    route_key_hash=_short_hash(route_key),
                )
    wait_ms = int((time.time() - wait_started) * 1000)
    _publish_llm_status_event(
        "concurrency_acquired",
        profileId=profile_id,
        provider=provider,
        model=model,
        phase=phase,
        waitMs=wait_ms,
    )
    if wait_ms > 0:
        _record_llm_scene_event(
            "concurrency",
            "llm.concurrency.acquired",
            message="LLM route concurrency slot acquired.",
            outcome="acquired",
            fields={
                "role": role,
                "profileId": profile_id,
                "provider": provider,
                "model": model,
                "phase": phase,
                "routeKeyHash": _short_hash(route_key),
                "limit": limit,
                "waitMs": wait_ms,
                "messageCount": message_count,
                "toolCount": tool_count,
            },
            lifecycle=False,
        )
    try:
        yield wait_ms
    finally:
        gate.release()
        _publish_llm_status_event(
            "concurrency_released",
            profileId=profile_id,
            provider=provider,
            model=model,
            phase=phase,
        )


@contextmanager
def llm_status_context(**fields: str):
    """Attach safe session breadcrumbs to LLM status events in this call context."""

    normalized = {
        str(key): str(value or "").strip()
        for key, value in fields.items()
        if str(value or "").strip()
    }
    token = _LLM_STATUS_CONTEXT.set(normalized)
    try:
        yield
    finally:
        _LLM_STATUS_CONTEXT.reset(token)


def current_llm_status_context() -> Dict[str, str]:
    """Return a copy of the active conversation identity breadcrumbs."""

    return dict(_LLM_STATUS_CONTEXT.get({}) or {})


def _record_llm_scene_event(
    phase: str,
    event_code: str,
    *,
    message: str = "",
    level: str = "info",
    outcome: str = "observed",
    fields: Dict[str, Any] | None = None,
    lifecycle: bool = False,
) -> None:
    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "llm",
            phase,
            event_code,
            message=message or event_code,
            level=level,
            outcome=outcome,
            fields=fields or {},
            lifecycle=lifecycle,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics must never fail LLM invoke
        from core.logging import debug as _debug_logger

        _debug_logger.warning(
            f"runtime scene event record failed (llm/{phase}/{event_code}): "
            f"{type(exc).__name__}: {exc}",
            tag="SCENE",
        )


def _record_stream_http_headers_event(timings: Any, *, identity: Dict[str, Any]) -> None:
    _record_llm_scene_event(
        "stream",
        "llm.stream.http_headers",
        message="LLM stream received HTTP response headers.",
        outcome="observed",
        fields={**identity, **timings.headers_scene_fields()},
        lifecycle=False,
    )


def _record_stream_http_timing_summary(timings: Any, *, identity: Dict[str, Any]) -> None:
    if timings is None or getattr(timings, "summary_emitted", False):
        return
    timings.summary_emitted = True
    _record_llm_scene_event(
        "stream",
        "llm.stream.http_timing",
        message="LLM stream HTTP timing summary.",
        outcome="observed",
        fields={**identity, **timings.summary_scene_fields()},
        lifecycle=False,
    )


@contextmanager
def llm_cancel_context(
    checker: Callable[[], str] | None,
    *,
    enable_chat_provider_abort: bool = False,
):
    token = _LLM_CANCEL_CHECKER_CONTEXT.set(checker if callable(checker) else None)
    abort_token = _LLM_CHAT_PROVIDER_ABORT_CONTEXT.set(bool(enable_chat_provider_abort))
    try:
        yield
    finally:
        _LLM_CHAT_PROVIDER_ABORT_CONTEXT.reset(abort_token)
        _LLM_CANCEL_CHECKER_CONTEXT.reset(token)


def _chat_provider_abort_enabled(checker: Callable[[], str] | None) -> bool:
    """Return whether this caller explicitly permits Chat HTTP cancellation.

    Responses cancellation predates the Challenge deadline path and continues
    to follow the ordinary stop checker. Chat Completions cancellation is the
    new capability and remains opt-in so normal Agent turns keep their prior
    provider behavior.
    """

    return callable(checker) and _LLM_CHAT_PROVIDER_ABORT_CONTEXT.get()


def _publish_llm_status_event(status: str, **fields: Any) -> None:
    """Publish a small LLM status breadcrumb for live session surfaces."""
    context = dict(_LLM_STATUS_CONTEXT.get({}) or {})
    payload = {
        "status": str(status or "").strip(),
        **context,
        **{key: value for key, value in fields.items() if value is not None},
    }
    try:
        from core.infrastructure.event_bus import EventNames, get_event_bus

        get_event_bus().publish(EventNames.LLM_STATUS, payload, source="LLMClient")
    except Exception:
        return


def _trace_metadata_with_context(
    event_metadata: Dict[str, Any],
    explicit_metadata: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Trace identity precedence: explicit metadata > status context > synthetic scope.

    ``event_metadata`` already folds invocation-scope ids; when the scope is
    synthetic (no explicit session identity), active ``llm_status_context``
    breadcrumbs must win so the trace shows the real conversation identity.
    """

    context = dict(_LLM_STATUS_CONTEXT.get({}) or {})
    merged = {**context, **event_metadata}
    explicit = dict(explicit_metadata or {})
    for camel, snake in (("sessionId", "session_id"), ("turnId", "turn_id")):
        explicit_value = str(explicit.get(camel) or explicit.get(snake) or "").strip()
        if explicit_value:
            merged[camel] = explicit_value
            continue
        context_value = str(context.get(camel) or context.get(snake) or "").strip()
        if context_value:
            merged[camel] = context_value
    return merged


def _retry_policy_max_attempts(profile: Any, *, role: str = "") -> int:
    if str(role or "").strip().lower() == "compression":
        return 1
    retry_policy = getattr(profile, "retry_policy", None)
    try:
        return max(1, min(5, int(getattr(retry_policy, "max_attempts", 5) or 5)))
    except Exception:
        return 5


_RETRY_BACKOFF_CONNECTION_CAP_SECONDS = 3.0


def _retry_policy_backoff_seconds(profile: Any, attempt: int, *, category: str = "") -> float:
    retry_policy = getattr(profile, "retry_policy", None)
    try:
        base = float(getattr(retry_policy, "backoff_base_seconds", 2.0) or 2.0)
    except Exception:
        base = 2.0
    base = max(0.1, base)
    normalized_category = str(category or "").strip().lower()
    if normalized_category in {"network_error", "timeout", "server_error"}:
        return min(base * (2 ** max(0, attempt - 1)), _RETRY_BACKOFF_CONNECTION_CAP_SECONDS)
    return base * (2 ** max(0, attempt - 1))


def _llm_retry_event_fields(
    *,
    role: str,
    profile_id: str,
    provider: str,
    model: str,
    message_count: int,
    tool_count: int,
    metadata: Optional[Dict[str, Any]],
    attempt: int,
    max_attempts: int,
    llm_error: LLMError,
) -> Dict[str, Any]:
    safe_metadata = metadata or {}
    role_fields = {}
    if isinstance(safe_metadata, dict):
        for key in (
            "sessionId",
            "turnId",
            "invocationId",
            "iteration",
            "invocationContextPresent",
            "conversationBound",
            "llmSlot",
            "promptPurpose",
            "llmInvocationSurface",
            "llmRunKind",
            "routeAttempt",
            "dialogueChainMode",
            "previousResponseIdPresent",
            "continuationMode",
            "responseInputItemCount",
            "functionCallOutputCount",
            "llmPayloadTraceId",
            "retryRequestMode",
            "messageRoles",
            "messageRoleCounts",
            "protocol",
            "selectedProtocol",
            "protocolSource",
            "protocolWarnings",
            "reasoningRoundtripEnabled",
            "thinkingFormat",
            "toolChoiceMode",
            "strictMessageKeys",
            "requiresStringContent",
            "allowAssistantPrefill",
            "payloadValidationResult",
            "payloadValidationErrorType",
            "payloadPolicySystemMessagesConverted",
            "payloadPolicyStringContentMessages",
            "payloadPolicyReasoningContentStripped",
            "payloadPolicyEmptyAssistantPrefillRemoved",
            "payloadPolicyQwenThinkingParameter",
            "payloadPolicyMinimalToolSchema",
            "modelLibraryId",
            "capabilitySource",
            "declaredCapabilityFields",
        ):
            if key in safe_metadata:
                role_fields[key] = safe_metadata[key]
    return {
        "role": role,
        "profileId": profile_id,
        "provider": provider,
        "model": model,
        "messageCount": message_count,
        "toolCount": tool_count,
        **role_fields,
        "metadata": safe_metadata,
        "attempt": attempt,
        "maxAttempts": max_attempts,
        "errorType": llm_error.category,
        "retryable": llm_error.retryable,
        "error": str(llm_error),
    }


def _safe_message_role_summary(messages: List[Any]) -> Dict[str, Any]:
    roles: List[str] = []
    counts: Dict[str, int] = {}
    for message in list(messages or []):
        if isinstance(message, SystemMessage):
            role = "system"
        elif isinstance(message, ToolMessage):
            role = "tool"
        elif isinstance(message, AIMessage):
            role = "assistant"
        elif isinstance(message, dict):
            role = str(message.get("role") or "user").strip().lower() or "user"
        elif isinstance(message, BaseMessage):
            role = str(getattr(message, "type", "") or "user").strip().lower() or "user"
        else:
            role = "user"
        roles.append(role)
        counts[role] = counts.get(role, 0) + 1
    return {
        "messageRoles": roles,
        "messageRoleCounts": counts,
    }


def _is_strict_blank_input(
    messages: List[Any],
    metadata: Optional[Dict[str, Any]],
) -> bool:
    if not isinstance(metadata, dict):
        return False
    if metadata.get("strictPromptPayload") is not True:
        return False
    if str(metadata.get("inputMode") or "").strip().lower() != "blank":
        return False
    if len(messages) not in {1, 2}:
        return False

    def is_plain_empty_user(message: Any) -> bool:
        return (
            isinstance(message, dict)
            and set(message).issubset({"role", "content"})
            and str(message.get("role") or "").strip().lower() == "user"
            and message.get("content") == ""
        )

    if len(messages) == 1:
        return is_plain_empty_user(messages[0])

    continuation = messages[0]
    if not isinstance(continuation, dict):
        return False
    if not set(continuation).issubset({"role", "content"}):
        return False
    if str(continuation.get("role") or "").strip().lower() != "assistant":
        return False
    if not isinstance(continuation.get("content"), str):
        return False
    if not continuation["content"].strip():
        return False
    return is_plain_empty_user(messages[1])


def _strict_blank_responses_messages(
    messages: List[Any],
    metadata: Optional[Dict[str, Any]],
) -> list[dict[str, Any]] | None:
    if len(messages) != 1 or not _is_strict_blank_input(messages, metadata):
        return None
    return [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": ""}],
        }
    ]


def _strict_blank_chat_completions_messages(
    messages: List[Any],
    metadata: Optional[Dict[str, Any]],
) -> list[dict[str, Any]] | None:
    if not _is_strict_blank_input(messages, metadata):
        return None
    normalized = [
        (
            {
                "role": "assistant",
                "content": messages[0]["content"],
            }
            if len(messages) == 2
            else {
                "role": "user",
                "content": [{"type": "text", "text": ""}],
            }
        )
    ]
    if len(messages) == 2:
        normalized.append(
            {
                "role": "user",
                "content": [{"type": "text", "text": ""}],
            }
        )
    return normalized


def _payload_conversation_items(payload: Dict[str, Any]) -> List[Any]:
    for key in ("messages", "input"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _scope_reasoning_replay_anchors(messages: List[Any], replay_state: Any) -> List[Any]:
    active_ids = {
        str(getattr(item, "item_id", "") or "").strip()
        for item in tuple(getattr(replay_state, "opaque_items", ()) or ())
        if str(getattr(item, "item_id", "") or "").strip()
    }
    scoped: List[Any] = []
    for message in list(messages or []):
        if isinstance(message, AIMessage):
            additional_kwargs = dict(getattr(message, "additional_kwargs", None) or {})
            replay_item_id = str(additional_kwargs.get("reasoning_replay_item_id") or "").strip()
            if replay_item_id and replay_item_id not in active_ids:
                additional_kwargs.pop("reasoning_replay_item_id", None)
            replay_item_ids = additional_kwargs.get("reasoning_replay_item_ids")
            if isinstance(replay_item_ids, (list, tuple)):
                scoped_ids = [str(item_id).strip() for item_id in replay_item_ids if str(item_id).strip() in active_ids]
                if scoped_ids:
                    additional_kwargs["reasoning_replay_item_ids"] = scoped_ids
                else:
                    additional_kwargs.pop("reasoning_replay_item_ids", None)
            message = message.model_copy(update={"additional_kwargs": additional_kwargs})
        elif isinstance(message, dict):
            message = dict(message)
            replay_item_id = str(message.get("reasoning_replay_item_id") or "").strip()
            if replay_item_id and replay_item_id not in active_ids:
                message.pop("reasoning_replay_item_id", None)
            replay_item_ids = message.get("reasoning_replay_item_ids")
            if isinstance(replay_item_ids, (list, tuple)):
                scoped_ids = [str(item_id).strip() for item_id in replay_item_ids if str(item_id).strip() in active_ids]
                if scoped_ids:
                    message["reasoning_replay_item_ids"] = scoped_ids
                else:
                    message.pop("reasoning_replay_item_ids", None)
            additional_kwargs = message.get("additional_kwargs")
            if isinstance(additional_kwargs, dict):
                additional_kwargs = dict(additional_kwargs)
                nested_item_id = str(additional_kwargs.get("reasoning_replay_item_id") or "").strip()
                if nested_item_id and nested_item_id not in active_ids:
                    additional_kwargs.pop("reasoning_replay_item_id", None)
                nested_item_ids = additional_kwargs.get("reasoning_replay_item_ids")
                if isinstance(nested_item_ids, (list, tuple)):
                    scoped_ids = [str(item_id).strip() for item_id in nested_item_ids if str(item_id).strip() in active_ids]
                    if scoped_ids:
                        additional_kwargs["reasoning_replay_item_ids"] = scoped_ids
                    else:
                        additional_kwargs.pop("reasoning_replay_item_ids", None)
                message["additional_kwargs"] = additional_kwargs
        scoped.append(message)
    return scoped


def _message_role_and_content(message: Any) -> tuple[str, Any]:
    def normalize_role(value: str) -> str:
        role = str(value or "user").strip().lower() or "user"
        return "user" if role == "human" else role

    if isinstance(message, SystemMessage):
        return "system", getattr(message, "content", None)
    if isinstance(message, ToolMessage):
        return "tool", getattr(message, "content", None)
    if isinstance(message, AIMessage):
        return "assistant", getattr(message, "content", None)
    if isinstance(message, dict):
        return normalize_role(str(message.get("role") or "user")), message.get("content")
    if isinstance(message, BaseMessage):
        return normalize_role(str(getattr(message, "type", "") or "user")), getattr(message, "content", None)
    return "user", str(message or "")


def _is_volatile_context_content(text: str) -> bool:
    return is_volatile_context_text(text)


def _safe_message_order_cache_summary(messages: List[Any]) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    digest_entries: List[Dict[str, Any]] = []
    first_volatile_index = -1
    last_user_index = -1
    stable_history_chars_before_volatile = 0
    volatile_chars_before_history = 0
    seen_history = False
    for index, message in enumerate(list(messages or [])):
        role, content = _message_role_and_content(message)
        text = extract_text_content(content)
        chars = len(text)
        volatile = _is_volatile_context_content(text)
        if role == "user":
            last_user_index = index
        is_history = role in {"user", "assistant", "tool"} and not volatile
        if index > 0 and is_history:
            seen_history = True
        if index > 0 and first_volatile_index < 0 and is_history:
            stable_history_chars_before_volatile += chars
        if volatile and not seen_history:
            volatile_chars_before_history += chars
        if volatile and first_volatile_index < 0:
            first_volatile_index = index
        entries.append(
            {
                "index": index,
                "role": role,
                "chars": chars,
                "volatileContext": volatile,
            }
        )
        digest_entries.append({"role": role, "content": content})
    if first_volatile_index >= 0:
        stable_prefix_boundary = first_volatile_index
        stable_prefix_end_reason = "before_volatile_context"
    elif last_user_index >= 0:
        stable_prefix_boundary = last_user_index
        stable_prefix_end_reason = "before_current_user"
    else:
        stable_prefix_boundary = len(digest_entries)
        stable_prefix_end_reason = "end_of_messages"
    stable_prefix_entries = digest_entries[: max(0, stable_prefix_boundary)]
    stable_prefix_chars = sum(_text_length(item.get("content")) for item in stable_prefix_entries)
    return {
        "messageOrderProfile": entries[:48],
        "promptCacheOrderDiagnostics": {
            "firstVolatileContextIndex": first_volatile_index,
            "lastUserIndex": last_user_index,
            "stableHistoryBeforeVolatileChars": stable_history_chars_before_volatile,
            "volatileContextBeforeHistoryChars": volatile_chars_before_history,
            "volatileContextBeforeHistory": bool(volatile_chars_before_history > 0),
            "stableCachePrefixMessageCount": len(stable_prefix_entries),
            "stableCachePrefixChars": stable_prefix_chars,
            "stableCachePrefixHash": _short_hash(stable_prefix_entries),
            "stableCachePrefixEndReason": stable_prefix_end_reason,
        },
    }


def _safe_capability_source_summary(resolved_spec: Any) -> Dict[str, Any]:
    details = getattr(resolved_spec, "provider_details", None)
    if not isinstance(details, dict):
        return {}
    summary: Dict[str, Any] = {}
    model_library_id = str(details.get("model_library_id") or "").strip()
    capability_source = str(details.get("capability_source") or "").strip()
    declared_fields = details.get("declared_capability_fields")
    if model_library_id:
        summary["modelLibraryId"] = model_library_id
    if capability_source:
        summary["capabilitySource"] = capability_source
    if isinstance(declared_fields, list):
        summary["declaredCapabilityFields"] = [
            str(item)
            for item in declared_fields
            if str(item or "").strip()
        ]
    return summary


def _short_hash(value: Any) -> str:
    try:
        if isinstance(value, str):
            raw = value
        else:
            raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        raw = str(value)
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _text_length(value: Any) -> int:
    return len(extract_text_content(value))


def _content_blocks_have_cache_control(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for block in value:
        if isinstance(block, dict) and block.get("cache_control"):
            return True
    return False


def _messages_have_prompt_cache_control(messages: List[Any]) -> bool:
    for message in list(messages or []):
        content: Any = None
        if isinstance(message, dict):
            content = message.get("content")
        elif isinstance(message, BaseMessage):
            content = getattr(message, "content", None)
        if _content_blocks_have_cache_control(content):
            return True
    return False


def _first_system_content_from_messages(messages: List[Any]) -> Any:
    for message in list(messages or []):
        role = ""
        content: Any = None
        if isinstance(message, SystemMessage):
            role = "system"
            content = getattr(message, "content", None)
        elif isinstance(message, dict):
            role = str(message.get("role") or "user").strip().lower() or "user"
            content = message.get("content")
        elif isinstance(message, BaseMessage):
            role = str(getattr(message, "type", "") or "user").strip().lower() or "user"
            content = getattr(message, "content", None)
        if role == "system":
            return content
    return None


def _cache_control_text_shape(content: Any) -> Dict[str, Any]:
    blocks = content if isinstance(content, list) else []
    cacheable_parts: List[str] = []
    dynamic_parts: List[str] = []
    cache_control_blocks = 0
    if blocks:
        for block in blocks:
            if not isinstance(block, dict):
                text = extract_text_content(block)
                if text:
                    dynamic_parts.append(text)
                continue
            text = extract_text_content(block.get("text") if "text" in block else block)
            if block.get("cache_control"):
                cache_control_blocks += 1
                if text:
                    cacheable_parts.append(text)
            elif text:
                dynamic_parts.append(text)
    elif content is not None:
        dynamic_parts.append(extract_text_content(content))

    cacheable_text = "\n\n".join(cacheable_parts)
    dynamic_text = "\n\n".join(dynamic_parts)
    first_system_text_chars = _text_length(content)
    cacheable_chars = len(cacheable_text)
    return {
        "firstSystemTextChars": first_system_text_chars,
        "firstSystemBlockCount": len(blocks),
        "firstSystemCacheControlBlockCount": cache_control_blocks,
        "firstSystemCacheableTextChars": cacheable_chars,
        "firstSystemDynamicTextChars": len(dynamic_text),
        "firstSystemCacheableTextRatio": round(cacheable_chars / first_system_text_chars, 4)
        if first_system_text_chars > 0
        else 0.0,
        "firstSystemCacheableHash": _short_hash(cacheable_text),
        "firstSystemDynamicHash": _short_hash(dynamic_text),
    }


def _safe_prompt_cache_design_summary(messages: List[Any], *, prompt_cache_mode: str) -> Dict[str, Any]:
    first_system_content = _first_system_content_from_messages(messages)
    shape = _cache_control_text_shape(first_system_content)
    mode = str(prompt_cache_mode or "").strip().lower()
    cacheable_chars = int(shape.get("firstSystemCacheableTextChars") or 0)
    first_system_cache_control_blocks = int(shape.get("firstSystemCacheControlBlockCount") or 0)
    first_system_dynamic_chars = int(shape.get("firstSystemDynamicTextChars") or 0)
    disabled_mode = mode in {"", "disabled"}
    cacheable_prefix_without_enabled_mode = (
        disabled_mode
        and bool(_messages_have_prompt_cache_control(messages))
        and cacheable_chars >= PROMPT_CACHE_OPPORTUNITY_PREFIX_CHARS
    )
    has_history_after_first_system = False
    for index, message in enumerate(list(messages or [])):
        if index <= 0:
            continue
        role, content = _message_role_and_content(message)
        text = extract_text_content(content)
        if role in {"user", "assistant", "tool"} and not _is_volatile_context_content(text):
            has_history_after_first_system = True
            break
    cacheable_prefix_break_reason = ""
    cacheable_prefix_ends_at = ""
    if first_system_cache_control_blocks > 0:
        if first_system_dynamic_chars > 0:
            cacheable_prefix_ends_at = "first_system_cache_control_block"
            cacheable_prefix_break_reason = (
                "dynamic_system_suffix_before_history"
                if has_history_after_first_system
                else "dynamic_system_suffix_in_first_system"
            )
        else:
            cacheable_prefix_ends_at = "first_system_message"
    return {
        "promptCacheDesign": {
            "mode": mode,
            "hasCacheControl": bool(_messages_have_prompt_cache_control(messages)),
            "cacheablePrefixWithoutEnabledMode": cacheable_prefix_without_enabled_mode,
            "cacheablePrefixOpportunityThresholdChars": PROMPT_CACHE_OPPORTUNITY_PREFIX_CHARS,
            "cacheablePrefixOpportunityReason": (
                "prompt_cache_mode_disabled"
                if cacheable_prefix_without_enabled_mode
                else ""
            ),
            "cacheablePrefixBreakReason": cacheable_prefix_break_reason,
            "cacheablePrefixEndsAt": cacheable_prefix_ends_at,
            "dynamicSystemSuffixOutsideCachePrefix": bool(first_system_dynamic_chars > 0),
            **shape,
        }
    }


def _safe_prompt_cache_payload_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    cache_key_field = ""
    cache_key = ""
    for field in ("prompt_cache_key", "promptCacheKey"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            cache_key_field = field
            cache_key = value.strip()
            break
    retention = payload.get("prompt_cache_retention") or payload.get("promptCacheRetention") or ""
    messages = _payload_conversation_items(payload)
    cache_control_blocks = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("cache_control"):
                cache_control_blocks += 1
    message_chunk_hashes = [
        _short_hash(messages[index : index + 16])
        for index in range(0, len(messages), 16)
    ]
    tool_schemas = payload.get("tools")
    if not isinstance(tool_schemas, list):
        tool_schemas = []
    return {
        "promptCacheMessageHash": _short_hash(messages),
        "promptCacheMessageChunkHashes": ",".join(message_chunk_hashes),
        "promptCacheToolSchemaHash": _short_hash(tool_schemas),
        "promptCachePayload": {
            "keyField": cache_key_field,
            "keyHash": _short_hash(cache_key),
            "keyChars": len(cache_key),
            "retention": str(retention or "").strip(),
            "cacheControlBlockCount": cache_control_blocks,
        }
    }


def _usage_cache_observation_fields(usage: UsageStats) -> Dict[str, Any]:
    input_tokens = max(0, int(getattr(usage, "input_tokens", 0) or 0))
    cache_read_tokens = max(0, int(getattr(usage, "cached_input_tokens", 0) or 0))
    cache_creation_tokens = max(0, int(getattr(usage, "cache_creation_input_tokens", 0) or 0))
    if input_tokens:
        cache_read_tokens = min(cache_read_tokens, input_tokens)
        cache_creation_tokens = min(cache_creation_tokens, input_tokens)
    cache_usage_observed, cache_usage_missing_reason = cache_usage_observation_from_payload(
        getattr(usage, "provider_raw_usage", {})
    )
    uncached_tokens = max(0, input_tokens - cache_read_tokens) if cache_usage_observed else 0
    return {
        "cachedInputTokens": cache_read_tokens,
        "cacheReadInputTokens": cache_read_tokens,
        "cacheCreationInputTokens": cache_creation_tokens,
        "uncachedInputTokens": uncached_tokens,
        "cacheHitRate": round(cache_read_tokens / input_tokens, 4)
        if cache_usage_observed and input_tokens > 0
        else 0.0,
        "cacheUsageObserved": cache_usage_observed,
        "cacheUsageMissingReason": cache_usage_missing_reason,
    }


def _usage_observation_metadata(usage: UsageStats) -> Dict[str, Any]:
    cache_fields = _usage_cache_observation_fields(usage)
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_output_tokens": usage.reasoning_output_tokens,
        "total_tokens": usage.total_tokens,
        "cached_input_tokens": cache_fields["cacheReadInputTokens"],
        "cache_read_input_tokens": cache_fields["cacheReadInputTokens"],
        "cache_creation_input_tokens": cache_fields["cacheCreationInputTokens"],
        "uncached_input_tokens": cache_fields["uncachedInputTokens"],
        "cache_hit_rate": cache_fields["cacheHitRate"],
        "cache_usage_observed": cache_fields["cacheUsageObserved"],
        "cache_usage_missing_reason": cache_fields["cacheUsageMissingReason"],
    }


def _usage_missing_reason(usage: UsageStats) -> str:
    if not isinstance(getattr(usage, "provider_raw_usage", None), dict) or not usage.provider_raw_usage:
        return "provider_usage_missing"
    observed = (
        int(getattr(usage, "input_tokens", 0) or 0) > 0
        or int(getattr(usage, "output_tokens", 0) or 0) > 0
        or int(getattr(usage, "total_tokens", 0) or 0) > 0
        or int(getattr(usage, "cached_input_tokens", 0) or 0) > 0
        or int(getattr(usage, "cache_creation_input_tokens", 0) or 0) > 0
    )
    if observed:
        return ""
    return "provider_usage_without_token_counts"


def record_usage_event(event: Any) -> Any:
    from .usage_ledger import record_usage_event as write_usage_event

    return write_usage_event(event, timeout_seconds=0.05)


def _usage_ledger_event(**kwargs: Any) -> Any:
    from .usage_ledger import UsageLedgerEvent

    return UsageLedgerEvent(**kwargs)


def _estimate_messages_for_usage(messages: List[Any]) -> int:
    try:
        from tools.token_manager import estimate_messages_tokens

        return max(0, int(estimate_messages_tokens(messages) or 0))
    except Exception:
        return 0


def _estimate_text_for_usage(text: Any) -> int:
    content = extract_text_content(text)
    if not content:
        return 0
    try:
        from tools.token_manager import estimate_tokens_precise

        return max(0, int(estimate_tokens_precise(content) or 0))
    except Exception:
        return max(1, len(content) // 4)


def _usage_scope_kind(metadata: Dict[str, Any]) -> str:
    mode = str(metadata.get("mode") or metadata.get("runKind") or "").strip().lower()
    if str(metadata.get("teamId") or metadata.get("team_id") or "").strip():
        return "team_workflow"
    if "evolution" in mode:
        return "evolution"
    if str(metadata.get("sessionId") or metadata.get("session_id") or "").strip():
        return "chat_session"
    if str(metadata.get("agentId") or metadata.get("agent_id") or "").strip():
        return "agent_round"
    return "unknown"


def _usage_metadata_value(metadata: Dict[str, Any], camel_key: str, snake_key: str) -> str:
    return str(metadata.get(camel_key) or metadata.get(snake_key) or "").strip()


def _record_usage_ledger_event(
    *,
    usage: UsageStats,
    metadata: Optional[Dict[str, Any]],
    provider: str,
    model: str,
    profile_id: str,
    transport: str,
    context_window: int = 0,
    estimated_input_tokens: int = 0,
    estimated_output_tokens: int = 0,
) -> None:
    meta = metadata if isinstance(metadata, dict) else {}
    provider_usage = getattr(usage, "provider_raw_usage", {}) if usage is not None else {}
    provider_usage_keys = sorted(str(key) for key in provider_usage.keys()) if isinstance(provider_usage, dict) else []
    input_tokens = max(0, int(getattr(usage, "input_tokens", 0) or 0))
    output_tokens = max(0, int(getattr(usage, "output_tokens", 0) or 0))
    total_tokens = max(0, int(getattr(usage, "total_tokens", 0) or 0))
    if estimated_input_tokens or estimated_output_tokens:
        source = "estimated"
        input_tokens = max(input_tokens, max(0, int(estimated_input_tokens or 0)))
        output_tokens = max(output_tokens, max(0, int(estimated_output_tokens or 0)))
        total_tokens = input_tokens + output_tokens
    elif provider_usage and (input_tokens or output_tokens or total_tokens):
        source = "provider_usage"
    else:
        source = "missing"
        total_tokens = total_tokens or input_tokens + output_tokens
    cached_input_tokens = max(0, int(getattr(usage, "cached_input_tokens", 0) or 0))
    cache_creation_tokens = max(0, int(getattr(usage, "cache_creation_input_tokens", 0) or 0))
    if input_tokens:
        cached_input_tokens = min(cached_input_tokens, input_tokens)
        cache_creation_tokens = min(cache_creation_tokens, input_tokens)
    cache_usage_observed, cache_usage_missing_reason = cache_usage_observation_from_payload(
        provider_usage
    )
    event = _usage_ledger_event(
        source=source,
        scope_kind=_usage_scope_kind(meta),
        session_id=_usage_metadata_value(meta, "sessionId", "session_id"),
        conversation_id=_usage_metadata_value(meta, "conversationId", "conversation_id"),
        turn_id=_usage_metadata_value(meta, "turnId", "turn_id"),
        agent_id=_usage_metadata_value(meta, "agentId", "agent_id"),
        team_id=_usage_metadata_value(meta, "teamId", "team_id"),
        provider=str(provider or "").strip(),
        model=str(model or "").strip(),
        profile_id=str(profile_id or "").strip(),
        transport=str(transport or "").strip(),
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_read_input_tokens=cached_input_tokens,
        cache_creation_input_tokens=cache_creation_tokens,
        uncached_input_tokens=(
            max(0, input_tokens - cached_input_tokens)
            if cache_usage_observed
            else 0
        ),
        output_tokens=output_tokens,
        reasoning_output_tokens=max(0, int(getattr(usage, "reasoning_output_tokens", 0) or 0)),
        total_tokens=total_tokens or input_tokens + output_tokens,
        context_window=max(0, int(context_window or 0)),
        latency_ms=max(0, int(getattr(usage, "latency_ms", 0) or 0)),
        runtime_scene_id=_usage_metadata_value(meta, "runtimeSceneId", "runtime_scene_id"),
        provider_usage_keys=provider_usage_keys,
        cache_usage_observed=cache_usage_observed,
        cache_usage_missing_reason=cache_usage_missing_reason,
    )
    try:
        record_usage_event(event)
    except Exception as exc:
        from .usage_ledger import usage_ledger_stats

        _record_llm_scene_event(
            "usage",
            "llm.usage_ledger.write_failed",
            message="LLM usage ledger write failed.",
            level="warning",
            outcome="failed",
            fields={
                "errorType": type(exc).__name__,
                "profileId": str(profile_id or "").strip(),
                "provider": str(provider or "").strip(),
                "model": str(model or "").strip(),
                "ledgerStats": usage_ledger_stats(),
            },
            lifecycle=False,
        )


def _strip_cache_control_from_content(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    stripped: List[Any] = []
    for block in value:
        if isinstance(block, dict) and "cache_control" in block:
            cleaned = dict(block)
            cleaned.pop("cache_control", None)
            stripped.append(cleaned)
        else:
            stripped.append(block)
    return stripped


def _strip_cache_control_from_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned_messages: List[Dict[str, Any]] = []
    for message in list(messages or []):
        if not isinstance(message, dict):
            cleaned_messages.append(message)
            continue
        cleaned = dict(message)
        cleaned["content"] = _strip_cache_control_from_content(cleaned.get("content"))
        cleaned_messages.append(cleaned)
    return cleaned_messages


def _safe_payload_shape_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    messages = _payload_conversation_items(payload)
    role_text_chars: Dict[str, int] = {}
    system_text_chars = 0
    non_system_text_chars = 0
    image_block_count = 0
    structured_content_message_count = 0
    first_system_content: Any = None

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip().lower() or "user"
        content = message.get("content")
        text_chars = _text_length(content)
        role_text_chars[role] = role_text_chars.get(role, 0) + text_chars
        if role == "system":
            system_text_chars += text_chars
            if first_system_content is None:
                first_system_content = content
        else:
            non_system_text_chars += text_chars
        if isinstance(content, list):
            structured_content_message_count += 1
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = str(block.get("type") or "").strip().lower()
                if block_type in {"image_url", "input_image"} or block.get("image_url") or block.get("imageUrl"):
                    image_block_count += 1

    first_system_shape = _cache_control_text_shape(first_system_content)

    tools = payload.get("tools") if isinstance(payload.get("tools"), list) else []
    tool_names: List[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        name = str(function.get("name") or tool.get("name") or "").strip()
        if name:
            tool_names.append(name)

    return {
        "payloadShape": {
            "messageTextCharsByRole": role_text_chars,
            "systemTextChars": system_text_chars,
            "nonSystemTextChars": non_system_text_chars,
            "structuredContentMessageCount": structured_content_message_count,
            "imageBlockCount": image_block_count,
            "firstSystemHash": _short_hash(first_system_content),
            **first_system_shape,
            "toolSchemaHash": _short_hash(tools) if tools else "",
            "toolNameHash": _short_hash(sorted(tool_names)) if tool_names else "",
        }
    }


def _safe_payload_route_summary(payload: Dict[str, Any], profile: Any, provider: Any) -> Dict[str, Any]:
    host = ""
    try:
        host = urlparse(str(getattr(provider, "base_url", "") or payload.get("base_url") or "")).hostname or ""
    except Exception:
        host = ""
    return {
        "runtimeRoute": str(payload.get("model") or ""),
        "transport": str(getattr(profile, "transport", "") or ""),
        "contract": str(getattr(profile, "contract", "") or ""),
        "baseUrlHost": host,
        "stream": bool(payload.get("stream")),
        "maxTokens": payload.get("max_tokens") if "max_tokens" in payload else payload.get("max_output_tokens"),
        "timeout": _safe_timeout_summary(payload.get("timeout")),
    }


def _safe_responses_continuation_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not _payload_uses_responses(payload):
        return {}
    websocket_options = payload.get(RESPONSES_WEBSOCKET_TRANSPORT_KEY)
    websocket_options = websocket_options if isinstance(websocket_options, dict) else {}
    previous_response_id_present = bool(
        str(
            websocket_options.get("previous_response_id")
            or payload.get("previous_response_id")
            or ""
        ).strip()
    )
    response_input = (
        websocket_options.get("input")
        if previous_response_id_present and isinstance(websocket_options.get("input"), list)
        else payload.get("input")
    )
    response_items = response_input if isinstance(response_input, list) else []
    response_input_item_count = len(response_items) if response_items else int(response_input not in (None, "", []))
    function_call_output_count = sum(
        1
        for item in response_items
        if isinstance(item, dict)
        and str(item.get("type") or "").strip().lower() == "function_call_output"
    )
    has_stateless_replay = any(
        isinstance(item, dict)
        and (
            str(item.get("role") or "").strip().lower() == "assistant"
            or str(item.get("type") or "").strip().lower()
            in {"function_call", "function_call_output", "reasoning"}
        )
        for item in response_items
    )
    continuation_mode = (
        "stateful_previous_response_id"
        if previous_response_id_present
        else "stateless_replay"
        if has_stateless_replay
        else "initial"
    )
    return {
        "previousResponseIdPresent": previous_response_id_present,
        "continuationMode": continuation_mode,
        "responseInputItemCount": response_input_item_count,
        "functionCallOutputCount": function_call_output_count,
    }


def _safe_timeout_summary(timeout: Any) -> Any:
    if timeout is None or isinstance(timeout, (bool, int, float, str)):
        return timeout
    fields = {
        key: getattr(timeout, key, None)
        for key in ("connect", "read", "write", "pool")
        if getattr(timeout, key, None) is not None
    }
    if fields:
        return fields
    return str(timeout)


def _safe_payload_thinking_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    thinking = payload.get("thinking")
    reasoning = payload.get("reasoning")
    reasoning_summary = {
        "reasoningEffortRequested": isinstance(reasoning, dict) and bool(str(reasoning.get("effort") or "").strip()),
        "reasoningEffort": str(reasoning.get("effort") or "").strip() if isinstance(reasoning, dict) else "",
    }
    if not isinstance(thinking, dict):
        return {
            "thinkingRequested": False,
            "thinkingType": "",
            "thinkingDisplay": "",
            **reasoning_summary,
        }
    return {
        "thinkingRequested": True,
        "thinkingType": str(thinking.get("type") or "").strip(),
        "thinkingDisplay": str(thinking.get("display") or "").strip(),
        **reasoning_summary,
    }


def _read_usage_int(container: Any, *keys: str) -> int:
    return _read_provider_usage_int(container, *keys)


def _usage_to_dict(usage: Any) -> Dict[str, Any]:
    return usage_to_dict(usage)


def _with_retry_details(llm_error: LLMError, *, attempt: int, max_attempts: int) -> LLMError:
    details = dict(getattr(llm_error, "details", {}) or {})
    details.update(
        {
            "attempt": int(attempt),
            "max_attempts": int(max_attempts),
            "retry_budget_exhausted": int(attempt) >= int(max_attempts),
        }
    )
    llm_error.details = details
    return llm_error


def _looks_like_stream_usage_options_rejection(exc: Exception, llm_error: LLMError) -> bool:
    if llm_error.category not in {"provider_protocol_error", "capability_error", "empty_content_error"}:
        return False
    text = f"{type(exc).__name__} {exc} {llm_error}".lower()
    return "stream_options" in text or "stream options" in text or "include_usage" in text


def _llm_cancelled_error(reason: str) -> LLMError:
    return LLMError(
        "cancelled",
        reason or "当前 LLM 调用已按停止请求取消。",
        retryable=False,
        details={"stop_reason": reason or ""},
    )


def _ensure_no_proxy_for_local_base_url(base_url: Any) -> None:
    """Ensure local/private-LAN model endpoints bypass process proxy settings."""

    raw_base_url = str(base_url or "").strip()
    if not raw_base_url or not is_llm_local_network_base_url(raw_base_url):
        return
    host = (urlparse(raw_base_url).hostname or "").strip().lower().rstrip(".")
    if not host:
        return
    with _NO_PROXY_LOCK:
        for env_name in _NO_PROXY_ENV_NAMES:
            current = os.environ.get(env_name, "")
            parts = [part.strip() for part in current.split(",") if part.strip()]
            normalized = {part.lower().rstrip(".") for part in parts}
            if host in normalized:
                continue
            os.environ[env_name] = ",".join([*parts, host]) if parts else host


@contextmanager
def _llm_provider_proxy_env(config: Any, base_url: Any) -> Iterator[None]:
    """Bound provider proxy env to project config for the duration of one LLM call."""

    network_config = getattr(config, "network", None)
    proxy_enabled = bool(getattr(network_config, "proxy_enabled", False))
    proxy_url = str(getattr(network_config, "proxy_url", "") or "").strip()
    raw_base_url = str(base_url or "").strip()
    if is_llm_local_network_base_url(raw_base_url):
        _ensure_no_proxy_for_local_base_url(raw_base_url)
        yield
        return
    desired_proxy = proxy_url if proxy_enabled and proxy_url else None
    mode = "read"
    previous: Dict[str, str | None] = {}
    with _PROXY_ENV_CONDITION:
        while _PROXY_ENV_STATE["writer"]:
            _PROXY_ENV_CONDITION.wait()
        env_matches = all(os.environ.get(env_name) == desired_proxy for env_name in _PROXY_ENV_NAMES)
        if env_matches:
            _PROXY_ENV_STATE["readers"] += 1
        else:
            mode = "write"
            while _PROXY_ENV_STATE["writer"] or int(_PROXY_ENV_STATE["readers"]) > 0:
                _PROXY_ENV_CONDITION.wait()
            _PROXY_ENV_STATE["writer"] = True
            previous = {env_name: os.environ.get(env_name) for env_name in _PROXY_ENV_NAMES}
            if desired_proxy:
                for env_name in _PROXY_ENV_NAMES:
                    os.environ[env_name] = desired_proxy
            else:
                for env_name in _PROXY_ENV_NAMES:
                    os.environ.pop(env_name, None)
    try:
        yield
    finally:
        with _PROXY_ENV_CONDITION:
            if mode == "write":
                for env_name, value in previous.items():
                    if value is None:
                        os.environ.pop(env_name, None)
                    else:
                        os.environ[env_name] = value
                _PROXY_ENV_STATE["writer"] = False
            else:
                _PROXY_ENV_STATE["readers"] = max(0, int(_PROXY_ENV_STATE["readers"]) - 1)
            _PROXY_ENV_CONDITION.notify_all()


def _default_completion_backend(payload: Dict[str, Any]) -> Any:
    _raise_if_llm_cancelled()
    try:
        from litellm import completion
    except Exception as exc:  # pragma: no cover
        raise LLMError(
            "configuration_error",
            "LiteLLM 未安装，无法执行模型调用；请安装 litellm",
            retryable=False,
        ) from exc
    _ensure_no_proxy_for_local_base_url(payload.get("base_url"))
    request_payload = dict(payload)
    if request_payload.get("base_url"):
        request_payload["base_url"] = _litellm_chat_completions_api_base(request_payload["base_url"])
    return completion(**request_payload)


def _litellm_chat_completions_api_base(value: Any) -> str:
    """Translate a final Chat Completions endpoint to LiteLLM's service-root contract."""

    endpoint = str(value or "").strip().rstrip("/")
    if endpoint.lower().endswith("/chat/completions"):
        return endpoint[: -len("/chat/completions")]
    return endpoint


def _litellm_responses_api_base(value: Any) -> str:
    """Translate the internal final Responses endpoint to LiteLLM's service-root contract."""

    endpoint = str(value or "").strip().rstrip("/")
    if endpoint.lower().endswith("/responses"):
        return endpoint[: -len("/responses")]
    return endpoint


def _default_responses_backend(payload: Dict[str, Any]) -> Any:
    _raise_if_llm_cancelled()
    try:
        from litellm import responses
    except Exception as exc:  # pragma: no cover
        raise LLMError(
            "configuration_error",
            "LiteLLM 未安装或不支持 Responses API，无法执行模型调用；请安装支持 responses 的 litellm",
            retryable=False,
        ) from exc
    _ensure_no_proxy_for_local_base_url(payload.get("base_url"))
    request_payload = dict(payload)
    request_payload.pop(RESPONSES_WEBSOCKET_TRANSPORT_KEY, None)
    if request_payload.get("base_url") and not request_payload.get("api_base"):
        request_payload["api_base"] = _litellm_responses_api_base(request_payload["base_url"])
    request_payload.pop("base_url", None)
    return responses(**request_payload)


def _default_anthropic_native_backend(payload: Dict[str, Any]) -> Any:
    """Call an explicit Anthropic Messages endpoint without LiteLLM shape conversion."""

    _raise_if_llm_cancelled()
    try:
        import httpx
    except Exception as exc:  # pragma: no cover
        raise LLMError(
            "configuration_error",
            "httpx 未安装，无法执行 Anthropic Messages native 请求",
            retryable=False,
        ) from exc
    request_payload = dict(payload)
    endpoint = str(request_payload.pop("base_url", "") or "").strip()
    api_key = str(request_payload.pop("api_key", "") or "").strip()
    timeout = request_payload.pop("timeout", None)
    ssl_verify = request_payload.pop("ssl_verify", True)
    extra_headers = request_payload.pop("extra_headers", {})
    if not endpoint or not api_key:
        raise LLMError(
            "configuration_error",
            "Anthropic Messages native route requires endpoint and credential",
            retryable=False,
        )
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    if isinstance(extra_headers, dict):
        headers.update({str(key): str(value) for key, value in extra_headers.items()})

    def check_response(response: Any) -> None:
        if int(getattr(response, "status_code", 0) or 0) < 400:
            return
        status = int(response.status_code)
        category = {
            400: "invalid_request_error",
            401: "authentication_error",
            403: "permission_error",
            404: "not_found_error",
            429: "rate_limit_error",
            529: "overloaded_error",
        }.get(status, "provider_error")
        raise LLMError(
            category,
            f"Anthropic Messages request failed with HTTP {status}",
            retryable=status == 429 or status >= 500,
            provider="anthropic",
            details={"statusCode": status, "errorSource": "anthropic_messages_native"},
        )

    if not bool(request_payload.get("stream")):
        with httpx.Client(timeout=timeout, verify=ssl_verify, follow_redirects=False) as client:
            response = client.post(endpoint, headers=headers, json=request_payload)
            check_response(response)
            return response.json()

    def iter_sse():
        with httpx.Client(timeout=timeout, verify=ssl_verify, follow_redirects=False) as client:
            with client.stream("POST", endpoint, headers=headers, json=request_payload) as response:
                check_response(response)
                for line in response.iter_lines():
                    _raise_if_llm_cancelled()
                    normalized = str(line or "").strip()
                    if not normalized.startswith("data:"):
                        continue
                    data = normalized.removeprefix("data:").strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise LLMError(
                            "protocol_error",
                            "Anthropic Messages SSE contains invalid JSON",
                            retryable=False,
                            provider="anthropic",
                            details={"errorSource": "anthropic_messages_native"},
                        ) from exc
                    if isinstance(event, dict):
                        yield event

    return iter_sse()


_default_responses_backend._vibelution_default_responses_backend = True


def _cancellable_client_cache_key(payload: Dict[str, Any]) -> tuple:
    """Identity of a cached cancellable client: baked credentials and transport options.

    Cancellable clients carry ``api_key``/``base_url`` (openai SDK) plus
    transport options, so slots must never be reused across credentials,
    endpoints or timeouts; otherwise one provider's credential would be sent
    to another provider. The base_url uses the same LiteLLM service-root shift
    as the corresponding backend so equivalent endpoints share one entry.
    """

    if _payload_uses_responses(payload):
        base_url = _litellm_responses_api_base(payload.get("base_url"))
    else:
        base_url = _litellm_chat_completions_api_base(payload.get("base_url"))
    return (
        str(payload.get("api_key") or ""),
        str(base_url or ""),
        repr(payload.get("timeout")),
        repr(payload.get("ssl_verify")),
    )


def _new_cancellable_responses_http_handler(payload: Dict[str, Any]) -> Any:
    """Create one reusable LiteLLM HTTP client whose active request can be aborted.

    LiteLLM 1.96.0's ``responses()`` native handler
    (``BaseLLMHTTPHandler.response_api_handler``) expects ``client=`` to be a
    litellm ``HTTPHandler`` and calls ``.post()`` on it directly; an openai SDK
    client fails the ``isinstance`` check there and would be silently ignored,
    losing the in-flight abort semantics. Unlike the Chat Completions path it
    never reads ``client.api_key``, so the credential-free HTTPHandler is the
    installed contract here.
    """

    from litellm import HTTPHandler

    timeout = payload.get("timeout")
    ssl_verify = payload.get("ssl_verify")
    return HTTPHandler(timeout=timeout, ssl_verify=ssl_verify)


def _new_cancellable_completion_http_handler(payload: Dict[str, Any]) -> Any:
    """Create an interruptible Chat Completions client as an openai SDK client.

    LiteLLM 1.96.0's ``completion()`` contract for ``client=`` is an
    ``openai.OpenAI``/``openai.AsyncOpenAI`` instance: the OpenAI handler uses
    the passed client as-is and reads ``client.api_key`` in ``pre_call``
    (``litellm/llms/openai/openai.py``), so an httpx-level ``HTTPHandler``
    crashes with ``'HTTPHandler' object has no attribute 'api_key'``. The
    attach happens before ``_default_completion_backend`` shifts the final
    endpoint to LiteLLM's service root, so the same shift is repeated here.
    ``close()`` closes the underlying httpx client, preserving the in-flight
    TCP-level abort semantics the watcher relies on.
    """

    try:
        import httpx
        import openai
    except Exception as exc:  # pragma: no cover
        raise LLMError(
            "configuration_error",
            "openai/httpx 未安装，无法创建可中断的 Chat Completions 客户端",
            retryable=False,
        ) from exc

    timeout = payload.get("timeout")
    ssl_verify = payload.get("ssl_verify")
    if ssl_verify is None:
        ssl_verify = True
    return openai.OpenAI(
        api_key=payload.get("api_key"),
        base_url=_litellm_chat_completions_api_base(payload.get("base_url")),
        http_client=httpx.Client(timeout=timeout, verify=ssl_verify),
        max_retries=0,
    )


class _CancellableProviderStream:
    """Finalize a cancellable provider request when its iterator ends or is closed."""

    def __init__(self, iterator: Any, finish: Callable[[], None]) -> None:
        self._iterator = iter(iterator)
        self._finish = finish

    def __iter__(self) -> "_CancellableProviderStream":
        return self

    def __next__(self) -> Any:
        try:
            return next(self._iterator)
        except StopIteration as exc:
            self._finish()
            reason = _current_llm_cancel_reason()
            if reason:
                raise LLMCancelledError(reason) from exc
            raise
        except Exception as exc:
            self._finish()
            reason = _current_llm_cancel_reason()
            if reason:
                raise LLMCancelledError(reason) from exc
            raise

    def close(self) -> None:
        try:
            close = getattr(self._iterator, "close", None)
            if callable(close):
                close()
        finally:
            self._finish()


def _payload_uses_responses(payload: Dict[str, Any]) -> bool:
    return "input" in payload and "messages" not in payload


def _normalize_tool_calls(tool_calls: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for index, raw_tool in enumerate(tool_calls or []):
        if isinstance(raw_tool, dict):
            function = raw_tool.get("function") if isinstance(raw_tool.get("function"), dict) else None
            if function is not None:
                normalized.append(
                    {
                        "id": str(raw_tool.get("id") or f"tool_{index}"),
                        "type": str(raw_tool.get("type") or "function"),
                        "function": {
                            "name": str(function.get("name") or ""),
                            "arguments": (
                                function.get("arguments")
                                if isinstance(function.get("arguments"), str)
                                else json.dumps(function.get("arguments") or {}, ensure_ascii=False)
                            ),
                        },
                    }
                )
                continue
            normalized.append(
                {
                    "id": str(raw_tool.get("id") or f"tool_{index}"),
                    "type": "function",
                    "function": {
                        "name": str(raw_tool.get("name") or ""),
                        "arguments": json.dumps(raw_tool.get("args") or {}, ensure_ascii=False),
                    },
                }
            )
            continue
        normalized.append(
            {
                "id": f"tool_{index}",
                "type": "function",
                "function": {"name": "", "arguments": "{}"},
            }
        )
    return normalized


def _message_to_openai_dict(
    message: Any,
    *,
    preserve_structured_content: bool = False,
    preserve_reasoning_content: bool = False,
) -> Dict[str, Any]:
    return project_message_to_openai_dict(
        message,
        preserve_structured_content=preserve_structured_content,
        preserve_reasoning_content=preserve_reasoning_content,
    )


def _content_blocks_have_image(value: Any) -> bool:
    for block in list(value or []):
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "").strip().lower()
        if block_type in {"image_url", "input_image"}:
            return True
        if isinstance(block.get("image_url"), dict) or block.get("image_url") or block.get("imageUrl"):
            return True
    return False


def _convert_content_blocks_for_transport(content: Any, *, transport: str) -> Any:
    if not isinstance(content, list):
        return content
    normalized_transport = str(transport or "").strip().lower()
    if normalized_transport != "responses":
        return content
    converted: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            text = str(block or "").strip()
            if text:
                converted.append({"type": "input_text", "text": text})
            continue
        block_type = str(block.get("type") or "").strip().lower()
        if block_type in {"text", "input_text"}:
            converted.append({"type": "input_text", "text": str(block.get("text") or "").strip()})
            continue
        if block_type in {"image_url", "input_image"} or block.get("image_url") or block.get("imageUrl"):
            image_url = block.get("image_url")
            if isinstance(image_url, dict):
                image_url = image_url.get("url")
            image_url = image_url or block.get("imageUrl") or block.get("image_url")
            if image_url:
                converted.append({"type": "input_image", "image_url": str(image_url).strip()})
            continue
        converted.append(dict(block))
    return converted


def _tool_to_schema(tool: Any) -> Dict[str, Any]:
    if isinstance(tool, dict) and tool.get("type") == "function":
        return tool
    schema = getattr(tool, "args_schema", None)
    parameters = {"type": "object", "properties": {}, "required": []}
    if schema is not None and hasattr(schema, "model_json_schema"):
        parameters = schema.model_json_schema()
    return {
        "type": "function",
        "function": {
            "name": str(getattr(tool, "name", "")),
            "description": str(getattr(tool, "description", "")),
            "parameters": parameters,
        },
    }


class LLMClient:
    """项目统一 LLM client。"""

    def __init__(
        self,
        *,
        config: Optional[AppConfig] = None,
        role: str = "primary",
        profile_id: Optional[str] = None,
        bound_tools: Optional[List[Any]] = None,
        backend: Any = None,
        responses_backend: Any = None,
        anthropic_backend: Any = None,
    ) -> None:
        self.config = config or get_config()
        self.role = role
        self.profile_id = profile_id or self.config.llm.get_role_profile_id(role)
        self.profile = self.config.llm.get_profile(self.profile_id)
        self.provider = self.config.llm.get_provider(self.profile.provider_id)
        self.bound_tools = list(bound_tools or [])
        self._backend = backend or _default_completion_backend
        self._responses_backend = responses_backend or backend or _default_responses_backend
        self._anthropic_backend = anthropic_backend or backend or _default_anthropic_native_backend
        self._cancellable_responses_http_handler: Any = None
        self._cancellable_responses_http_handler_key: Any = None
        self._cancellable_responses_http_handler_lock = threading.Lock()
        self._cancellable_responses_stream_lock = threading.Lock()
        self._cancellable_responses_request_lock = self._cancellable_responses_stream_lock
        self._cancellable_completion_http_handler: Any = None
        self._cancellable_completion_http_handler_key: Any = None
        self._cancellable_completion_http_handler_lock = threading.Lock()
        self._cancellable_completion_stream_lock = threading.Lock()
        self._cancellable_completion_request_lock = self._cancellable_completion_stream_lock
        self.adapter = get_provider_adapter(self.provider, self.profile)
        self._resolved_spec = discover_model(self.config, self.profile_id)
        _model_id, model_entry = self.config.llm.get_model_library_entry_for_profile(self.profile)
        try:
            self.protocol_route = resolve_model_protocol(
                self.profile,
                self.provider,
                model_entry=model_entry if isinstance(model_entry, dict) else None,
            )
        except ProtocolResolutionError as exc:
            _record_llm_scene_event(
                "protocol",
                "llm.protocol.blocked",
                outcome="blocked",
                fields={
                    "providerId": exc.provider_id,
                    "modelRef": exc.model_ref,
                    "errorType": exc.code,
                },
            )
            raise LLMError(
                "provider_protocol_error",
                str(exc),
                retryable=False,
                provider=self.provider.provider_id,
                model=self.profile.model,
            ) from exc
        _record_llm_scene_event(
            "protocol",
            "llm.protocol.resolved",
            outcome="succeeded",
            fields=self.protocol_route.log_summary(),
        )
        self._responses_websocket_backend: ResponsesWebSocketBackend | None = None
        if (
            self._responses_backend is _default_responses_backend
            and bool(getattr(self.protocol_route.compat, "responses_websocket", False))
        ):
            self._responses_websocket_backend = ResponsesWebSocketBackend(
                self._responses_backend,
                state_sink=self._record_responses_websocket_state,
            )
        self._last_payload_protocol_summary: Dict[str, Any] = {}

    def _record_responses_websocket_state(self, state: str, fields: Dict[str, Any]) -> None:
        outcomes = {
            "connected": "succeeded",
            "reused": "observed",
            "fallback": "fallback",
            "disconnected": "failed",
            "recovered": "recovered",
        }
        levels = {"fallback": "warning", "disconnected": "warning"}
        _record_llm_scene_event(
            "transport",
            f"llm.responses_websocket.{state}",
            message=f"Responses WebSocket transport {state}.",
            level=levels.get(state, "info"),
            outcome=outcomes.get(state, "observed"),
            fields={
                "providerId": self.provider.provider_id,
                "providerKind": self.provider.kind,
                "model": self.profile.model,
                "profileId": self.profile_id,
                **fields,
            },
            lifecycle=False,
        )
        status_names = {
            "disconnected": "transport_degraded",
            "fallback": "transport_fallback",
            "recovered": "transport_recovered",
        }
        status_name = status_names.get(state)
        if status_name:
            _publish_llm_status_event(
                status_name,
                providerId=self.provider.provider_id,
                providerKind=self.provider.kind,
                model=self.profile.model,
                profileId=self.profile_id,
                transport="websocket",
                category="provider_transport_unavailable",
                **fields,
            )

    def _get_or_create_cancellable_client(
        self,
        attr: str,
        factory: Callable[[Dict[str, Any]], Any],
        payload: Dict[str, Any],
    ) -> Any:
        """Return the slot's cached cancellable client, rebuilding on drift.

        Cancellable clients bake in credentials/endpoints, so the slot is keyed
        by ``_cancellable_client_cache_key`` (api_key, shifted base_url,
        timeout, ssl_verify). A cache hit reuses the instance; any other state
        closes the stale instance first so credentials never leak across
        providers or profiles. The caller must hold the slot lock.
        """

        key_attr = f"{attr}_key"
        cache_key = _cancellable_client_cache_key(payload)
        handler = getattr(self, attr, None)
        if handler is not None and getattr(self, key_attr, None) == cache_key:
            return handler
        if handler is not None:
            try:
                handler.close()
            except Exception:
                pass
        handler = factory(payload)
        setattr(self, attr, handler)
        setattr(self, key_attr, cache_key)
        return handler

    def _record_provider_abort_unavailable_once(
        self,
        transport: str,
        *,
        reason: str,
        backend: Any,
    ) -> None:
        """Record residual cancel risk once per transport+purpose+reason.

        Non-default backends and the native Anthropic Messages adapter cannot
        host the hard provider-abort watcher; the call still proceeds with
        cooperative stop-checker cancellation only.  The Challenge deadline
        contract requires the precise residual risk to stay visible, so this
        emits one bounded scene event per transport+purpose+reason and never
        refuses the call.
        """

        purpose = str(getattr(self, "role", "") or "").strip() or "primary"
        key = (str(transport), purpose, str(reason))
        with _PROVIDER_ABORT_UNAVAILABLE_EMIT_LOCK:
            if key in _PROVIDER_ABORT_UNAVAILABLE_EMITTED:
                return
            _PROVIDER_ABORT_UNAVAILABLE_EMITTED.add(key)
        try:
            backend_id = str(
                getattr(backend, "__name__", "") or type(backend).__name__ or "unknown"
            )
        except Exception:  # noqa: BLE001 - diagnostics must never fail the call
            backend_id = "unknown"
        # Partially-constructed clients (unit tests, teardown paths) may lack
        # identity attributes; diagnostics degrade to empty strings instead of
        # breaking the provider call.
        provider = getattr(self, "provider", None)
        profile = getattr(self, "profile", None)
        _record_llm_scene_event(
            "transport",
            _PROVIDER_ABORT_UNAVAILABLE_EVENT_CODE,
            message=(
                "Provider abort watcher unavailable; cancellation stays "
                "cooperative-only for this transport."
            ),
            level="warning",
            outcome="degraded",
            fields={
                "transport": transport,
                "reason": reason,
                "purpose": purpose,
                "adapterId": str(
                    getattr(self.protocol_route, "adapter_id", "") or ""
                ),
                "backendId": backend_id,
                "profileId": str(getattr(self, "profile_id", "") or ""),
                "providerId": str(getattr(provider, "provider_id", "") or ""),
                "model": str(getattr(profile, "model", "") or ""),
            },
            lifecycle=False,
        )

    def _prepare_cancellable_responses_stream(
        self,
        payload: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Callable[[], None]]:
        checker = _LLM_CANCEL_CHECKER_CONTEXT.get(None)
        default_responses_backend = bool(
            getattr(
                self._responses_backend,
                "_vibelution_default_responses_backend",
                False,
            )
        )
        if (
            callable(checker)
            and _payload_uses_responses(payload)
            and not default_responses_backend
        ):
            self._record_provider_abort_unavailable_once(
                "responses_stream",
                reason="backend_not_default",
                backend=self._responses_backend,
            )
        if not (
            callable(checker)
            and _payload_uses_responses(payload)
            and default_responses_backend
        ):
            return payload, lambda: None

        while not self._cancellable_responses_stream_lock.acquire(timeout=0.05):
            try:
                reason = str(checker() or "").strip()
            except Exception:
                reason = ""
            if reason:
                raise LLMCancelledError(reason)
        try:
            with self._cancellable_responses_http_handler_lock:
                handler = self._get_or_create_cancellable_client(
                    "_cancellable_responses_http_handler",
                    _new_cancellable_responses_http_handler,
                    payload,
                )
        except Exception:
            self._cancellable_responses_stream_lock.release()
            raise

        request_payload = dict(payload)
        request_payload["client"] = handler
        watcher_finished = threading.Event()
        cleanup_lock = threading.Lock()
        cleaned_up = False

        def watch_for_cancellation() -> None:
            while not watcher_finished.wait(0.05):
                try:
                    reason = str(checker() or "").strip()
                except Exception:
                    reason = ""
                if not reason:
                    continue
                try:
                    handler.close()
                except Exception:
                    pass
                with self._cancellable_responses_http_handler_lock:
                    if self._cancellable_responses_http_handler is handler:
                        self._cancellable_responses_http_handler = None
                        self._cancellable_responses_http_handler_key = None
                return

        watcher = threading.Thread(
            target=watch_for_cancellation,
            name="vibelution-llm-cancel-watch",
            daemon=True,
        )
        try:
            watcher.start()
        except Exception:
            self._cancellable_responses_stream_lock.release()
            raise

        def finish() -> None:
            nonlocal cleaned_up
            with cleanup_lock:
                if cleaned_up:
                    return
                cleaned_up = True
            watcher_finished.set()
            watcher.join(timeout=0.2)
            if watcher.is_alive():
                # A provider client's ``close`` may itself block. Do not
                # release the request slot while the old watcher still owns a
                # handler that a later request could reuse.
                with self._cancellable_responses_http_handler_lock:
                    if self._cancellable_responses_http_handler is handler:
                        self._cancellable_responses_http_handler = None
            self._cancellable_responses_stream_lock.release()

        return request_payload, finish

    def _prepare_cancellable_chat_stream(
        self,
        payload: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Callable[[], None]]:
        """Attach a cancellable client only to the default Chat backend."""

        checker = _LLM_CANCEL_CHECKER_CONTEXT.get(None)
        abort_enabled = _chat_provider_abort_enabled(checker)
        native_adapter = self.protocol_route.adapter_id == "anthropic_messages_native"
        if abort_enabled and (
            self._backend is not _default_completion_backend or native_adapter
        ):
            self._record_provider_abort_unavailable_once(
                "chat_stream",
                reason="native_anthropic_adapter"
                if native_adapter
                else "backend_not_default",
                backend=self._backend,
            )
        if (
            not abort_enabled
            or self._backend is not _default_completion_backend
            or native_adapter
        ):
            return payload, lambda: None

        while not self._cancellable_completion_stream_lock.acquire(timeout=0.05):
            try:
                reason = str(checker() or "").strip()
            except Exception:
                reason = ""
            if reason:
                raise LLMCancelledError(reason)
        try:
            with self._cancellable_completion_http_handler_lock:
                handler = self._get_or_create_cancellable_client(
                    "_cancellable_completion_http_handler",
                    _new_cancellable_completion_http_handler,
                    payload,
                )
        except Exception:
            self._cancellable_completion_stream_lock.release()
            raise

        request_payload = dict(payload)
        request_payload["client"] = handler
        watcher_finished = threading.Event()
        cleanup_lock = threading.Lock()
        cleaned_up = False

        def watch_for_cancellation() -> None:
            while not watcher_finished.wait(0.05):
                try:
                    reason = str(checker() or "").strip()
                except Exception:
                    reason = ""
                if not reason:
                    continue
                try:
                    handler.close()
                except Exception:
                    pass
                with self._cancellable_completion_http_handler_lock:
                    if self._cancellable_completion_http_handler is handler:
                        self._cancellable_completion_http_handler = None
                        self._cancellable_completion_http_handler_key = None
                return

        watcher = threading.Thread(
            target=watch_for_cancellation,
            name="vibelution-llm-cancel-watch",
            daemon=True,
        )
        try:
            watcher.start()
        except Exception:
            self._cancellable_completion_stream_lock.release()
            raise

        def finish() -> None:
            nonlocal cleaned_up
            with cleanup_lock:
                if cleaned_up:
                    return
                cleaned_up = True
            watcher_finished.set()
            watcher.join(timeout=0.2)
            if watcher.is_alive():
                with self._cancellable_completion_http_handler_lock:
                    if self._cancellable_completion_http_handler is handler:
                        self._cancellable_completion_http_handler = None
            self._cancellable_completion_stream_lock.release()

        return request_payload, finish

    def _prepare_cancellable_non_stream_request(
        self,
        payload: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Callable[[], None]]:
        """Prepare cancellation for default non-stream Chat/Responses calls."""

        checker = _LLM_CANCEL_CHECKER_CONTEXT.get(None)
        if _payload_uses_responses(payload):
            backend = self._responses_backend
            default_responses_backend = bool(
                getattr(backend, "_vibelution_default_responses_backend", False)
            )
            if callable(checker) and not default_responses_backend:
                self._record_provider_abort_unavailable_once(
                    "non_stream_responses",
                    reason="backend_not_default",
                    backend=backend,
                )
            enabled = callable(checker) and default_responses_backend
            handler_attr = "_cancellable_responses_http_handler"
            handler_lock = self._cancellable_responses_http_handler_lock
            request_lock = self._cancellable_responses_request_lock
            factory = _new_cancellable_responses_http_handler
        elif "messages" in payload:
            abort_enabled = _chat_provider_abort_enabled(checker)
            native_adapter = self.protocol_route.adapter_id == "anthropic_messages_native"
            if abort_enabled and (
                self._backend is not _default_completion_backend or native_adapter
            ):
                self._record_provider_abort_unavailable_once(
                    "non_stream_chat",
                    reason="native_anthropic_adapter"
                    if native_adapter
                    else "backend_not_default",
                    backend=self._backend,
                )
            enabled = (
                abort_enabled
                and self._backend is _default_completion_backend
                and not native_adapter
            )
            handler_attr = "_cancellable_completion_http_handler"
            handler_lock = self._cancellable_completion_http_handler_lock
            request_lock = self._cancellable_completion_request_lock
            factory = _new_cancellable_completion_http_handler
        else:
            enabled = False
            handler_attr = ""
            handler_lock = None
            request_lock = None
            factory = None
        if not enabled or handler_lock is None or request_lock is None or factory is None:
            return payload, lambda: None
        while not request_lock.acquire(timeout=0.05):
            try:
                reason = str(checker() or "").strip()
            except Exception:
                reason = ""
            if reason:
                raise LLMCancelledError(reason)
        with handler_lock:
            try:
                handler = self._get_or_create_cancellable_client(handler_attr, factory, payload)
            except Exception:
                request_lock.release()
                raise
        request_payload = dict(payload)
        request_payload["client"] = handler
        watcher_finished = threading.Event()
        cleanup_lock = threading.Lock()
        cleaned_up = False

        def watch_for_cancellation() -> None:
            while not watcher_finished.wait(0.05):
                try:
                    reason = str(checker() or "").strip()
                except Exception:
                    reason = ""
                if not reason:
                    continue
                try:
                    handler.close()
                except Exception:
                    pass
                with handler_lock:
                    if getattr(self, handler_attr) is handler:
                        setattr(self, handler_attr, None)
                        setattr(self, f"{handler_attr}_key", None)
                return

        watcher = threading.Thread(
            target=watch_for_cancellation,
            name="vibelution-llm-cancel-watch",
            daemon=True,
        )
        try:
            watcher.start()
        except Exception:
            request_lock.release()
            raise

        def finish() -> None:
            nonlocal cleaned_up
            with cleanup_lock:
                if cleaned_up:
                    return
                cleaned_up = True
            watcher_finished.set()
            watcher.join(timeout=0.2)
            if watcher.is_alive():
                with handler_lock:
                    if getattr(self, handler_attr) is handler:
                        setattr(self, handler_attr, None)
            request_lock.release()

        return request_payload, finish

    def _open_provider_stream(self, payload: Dict[str, Any]) -> Any:
        if _payload_uses_responses(payload):
            request_payload, finish_cancel_watch = self._prepare_cancellable_responses_stream(payload)
        elif "messages" in payload:
            request_payload, finish_cancel_watch = self._prepare_cancellable_chat_stream(payload)
        else:
            request_payload, finish_cancel_watch = payload, lambda: None
        backend = self._backend_for_payload(request_payload)
        if request_payload is payload:
            return backend(payload)
        try:
            iterator = backend(request_payload)
            return _CancellableProviderStream(iterator, finish_cancel_watch)
        except Exception as exc:
            finish_cancel_watch()
            reason = _current_llm_cancel_reason()
            if reason:
                raise LLMCancelledError(reason) from exc
            raise

    @property
    def capabilities(self) -> LLMCapabilities:
        return self._resolved_spec.capabilities

    @property
    def resolved_spec(self):
        return self._resolved_spec

    def _required_wire_adapter(self):
        try:
            return _CANONICAL_WIRE_ADAPTERS.require(self.protocol_route)
        except LookupError as exc:
            route = self.protocol_route
            raise LLMError(
                "unsupported_wire_protocol",
                str(exc),
                retryable=False,
                provider=self.provider.kind,
                model=self.profile.model,
                details={
                    "profileId": self.profile_id,
                    "providerKind": self.provider.kind,
                    "modelId": route.model_id,
                    "wireProtocol": route.wire_protocol.value,
                    "adapterId": route.adapter_id,
                    "routeSource": route.wire_source,
                    "payloadValidationResult": "blocked_before_provider",
                },
            ) from exc

    def _project_semantic_request_or_raise(self, projection_input: SemanticProjectionInput):
        try:
            return project_semantic_request(projection_input)
        except SemanticProjectionError as exc:
            details = _safe_semantic_projection_snapshot(list(projection_input.messages))
            details.update(
                {
                    "messageIndex": exc.message_index,
                    "payloadValidationErrorType": exc.code,
                    "payloadValidationResult": "blocked_before_provider",
                }
            )
            raise LLMError(
                "payload_protocol_error",
                str(exc),
                retryable=False,
                provider=self.provider.kind,
                model=self.profile.model,
                details=details,
            ) from exc

    def bind_tools(self, tools: List[Any], *, binding_name: str = "default") -> "LLMClient":
        return LLMClient(
            config=self.config,
            role=self.role,
            profile_id=self.profile_id,
            bound_tools=list(tools or []),
            backend=self._backend,
            responses_backend=self._responses_backend,
        )

    def _build_payload(
        self,
        messages: List[Any],
        *,
        tools: Optional[List[Any]] = None,
        stream: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        invocation_scope: Any = None,
        replay_state: Any = None,
        output_schema: SemanticOutputSchema | None = None,
    ) -> Dict[str, Any]:
        wire_adapter = self._required_wire_adapter()
        max_output_tokens_override = _max_output_tokens_override_from_metadata(metadata)
        if output_schema is not None and not self.capabilities.supports_strict_json_schema:
            raise LLMError(
                "capability_error",
                f"profile `{self.profile_id}` does not support strict JSON Schema output",
                retryable=False,
                provider=self.provider.kind,
                model=self.profile.model,
                details={
                    "capability": "strict_json_schema",
                    "payloadValidationResult": "blocked_before_provider",
                },
            )
        selected_tools = list(self.bound_tools)
        if tools is not None:
            selected_tools = list(tools or [])
        from core.chat.conversation_invariant import check_conversation_payload_invariant
        from core.chat.model_messages import ProviderMessageChain

        ui_tool_calls_index = _find_ui_tool_calls_message_index(list(messages or []))
        if ui_tool_calls_index >= 0:
            raise LLMError(
                "payload_protocol_error",
                "UI field `toolCalls` is not allowed in model input. Build model context from ConversationLedger ModelProjection first.",
                retryable=False,
                provider=self.provider.kind,
                model=self.profile.model,
                details={
                    "messageIndex": ui_tool_calls_index,
                    "requiredSource": "conversation_ledger_model_projection",
                    "forbiddenField": "toolCalls",
                },
            )
        projection_messages = list(messages or [])
        provider_chain = ProviderMessageChain.from_messages(projection_messages)
        provider_messages = provider_chain.to_provider_payload()
        invariant = check_conversation_payload_invariant(
            provider_messages,
            expected_fingerprint=str(
                (metadata or {}).get("ledgerConversationFingerprint") or ""
            ).strip(),
        )
        if not invariant.ok:
            raise LLMError(
                "payload_protocol_error",
                invariant.message,
                retryable=False,
                provider=self.provider.kind,
                model=self.profile.model,
                details={
                    "requiredSource": "conversation_ledger_model_projection",
                    "payloadValidationResult": "blocked_before_provider",
                    "payloadValidationErrorType": invariant.error_type,
                    **invariant.details,
                },
            )
        if self.protocol_route.wire_protocol == WireProtocol.RESPONSES:
            strict_blank_messages = _strict_blank_responses_messages(
                projection_messages,
                metadata,
            )
            if strict_blank_messages is not None:
                provider_messages = strict_blank_messages
        replay_items = tuple(getattr(replay_state, "opaque_items", ()) or ())
        provider_message_roles = list(
            _safe_message_role_summary(provider_messages).get("messageRoles") or []
        )
        replay_has_response_id = bool(
            str(getattr(replay_state, "response_id", "") or "").strip()
        )
        replay_response_id_usable = bool(
            replay_has_response_id
            and (
                self.protocol_route.compat.responses_continuation
                or self.protocol_route.compat.responses_websocket
            )
        )
        if (
            replay_items
            and provider_message_roles
            and provider_message_roles[-1] == "user"
            and "assistant" not in provider_message_roles
        ):
            replay_summary = (
                replay_state.safe_summary()
                if hasattr(replay_state, "safe_summary")
                else {}
            )
            continuation_mode = (
                "stateful_previous_response_id_replay_items_dropped"
                if replay_response_id_usable
                else "unsupported_previous_response_id_replay_dropped"
                if replay_has_response_id
                else "stateless_replay_dropped"
            )
            _record_llm_scene_event(
                "projection",
                "llm.replay_state.degraded",
                message="Unanchored opaque replay items were discarded before semantic projection.",
                level="warning",
                outcome="degraded",
                fields={
                    "profileId": self.profile_id,
                    "provider": self.provider.kind,
                    "model": self.profile.model,
                    "protocol": self.protocol_route.protocol.value,
                    "reason": "missing_assistant_anchor",
                    "continuationMode": continuation_mode,
                    "replayItemCount": int(replay_summary.get("itemCount") or len(replay_items)),
                    "replayByteSize": int(replay_summary.get("byteSize") or 0),
                    "hasResponseId": replay_has_response_id,
                    "previousResponseIdUsable": replay_response_id_usable,
                    "messageCount": len(provider_messages),
                    "finalMessageRole": provider_message_roles[-1],
                },
                lifecycle=False,
            )
            replay_state = (
                replay_state.without_opaque_items()
                if replay_response_id_usable
                else None
            )
        if replay_state is not None:
            provider_messages = _scope_reasoning_replay_anchors(provider_messages, replay_state)
        provider_tool_chain_repaired = sum(
            1
            for message in provider_messages
            if isinstance(message, dict)
            and isinstance(message.get("metadata"), dict)
            and message["metadata"].get("repairedProviderToolChain") is True
        )
        has_image_content = any(
            isinstance(message, dict) and _content_blocks_have_image(message.get("content"))
            for message in provider_messages
        )
        if has_image_content and self.capabilities.supports_image_input is False:
            raise LLMError(
                "capability_error",
                (
                    f"profile `{self.profile_id}` 不支持 image input；"
                    f"provider `{self.provider.kind}` model `{self.profile.model}` "
                    f"protocol `{self.protocol_route.protocol.value}`。请切换到支持图像理解的模型，"
                    "或移除本轮图片输入。"
                ),
                retryable=False,
                provider=str(self.provider.kind or ""),
                model=str(self.profile.model or ""),
                details={
                    "profile_id": self.profile_id,
                    "provider_kind": str(self.provider.kind or ""),
                    "transport": str(getattr(self.profile, "transport", "") or "chat_completions"),
                    "model": str(self.profile.model or ""),
                    "protocol": self.protocol_route.protocol.value,
                    "capability": "image_input",
                    "supports_image_input": False,
                    "payloadValidationResult": "blocked_before_provider",
                },
            )
        if self.protocol_route.wire_protocol != WireProtocol.RESPONSES:
            provider_messages = _normalize_semantic_messages_with_adapter(
                provider_messages,
                self.adapter,
            )
        if self.protocol_route.wire_protocol in {
            WireProtocol.CHAT_COMPLETIONS,
            WireProtocol.ANTHROPIC_MESSAGES,
            WireProtocol.GEMINI_GENERATE_CONTENT,
        }:
            strict_blank_messages = _strict_blank_chat_completions_messages(
                projection_messages,
                metadata,
            )
            if strict_blank_messages is not None:
                provider_messages = strict_blank_messages
        build_input = PayloadBuildInput(
            messages=provider_messages,
            tools=selected_tools,
            profile=self.profile,
            provider=self.provider,
            adapter=self.adapter,
            route=self.protocol_route,
            capabilities=self.capabilities,
            stream=stream,
            api_key=self.config.get_api_key_for_profile(profile_id=self.profile_id),
            profile_id=self.profile_id,
            config=self.config,
            max_output_tokens_override=max_output_tokens_override,
        )
        # Chat-shaped wires (incl. LiteLLM-backed anthropic/gemini) share encode path.
        if self.protocol_route.wire_protocol in {
            WireProtocol.RESPONSES,
            WireProtocol.CHAT_COMPLETIONS,
            WireProtocol.ANTHROPIC_MESSAGES,
            WireProtocol.GEMINI_GENERATE_CONTENT,
        }:
            from .invocation import invocation_scope_from_metadata

            if selected_tools and (
                not self.capabilities.supports_tool_calling
                or not self.protocol_route.policy.allow_tools
            ):
                raise LLMError(
                    "capability_error",
                    f"profile `{self.profile_id}` 不支持 tool calling",
                    retryable=False,
                )
            semantic_request = self._project_semantic_request_or_raise(
                SemanticProjectionInput(
                    messages=tuple(provider_messages),
                    tools=tuple(selected_tools),
                    scope=invocation_scope or invocation_scope_from_metadata(metadata),
                    settings=SemanticGenerationSettings(
                        max_output_tokens=(
                            max_output_tokens_override
                            if max_output_tokens_override is not None
                            else self.profile.max_output_tokens
                        ),
                        stream=stream,
                        tool_choice=(
                            "auto"
                            if self.capabilities.supports_explicit_tool_choice
                            and self.protocol_route.policy.allow_explicit_tool_choice
                            and self.protocol_route.compat.tool_choice_mode != "omit"
                            else "omit"
                        ),
                    ),
                    tool_to_schema=lambda tool: (
                        sanitize_tool_schema(self.adapter.sanitize_tool_schema(_tool_to_schema(tool)))
                        if self.protocol_route.policy.tool_schema_policy == "minimal"
                        or self.protocol_route.compat.strict_message_keys
                        else self.adapter.sanitize_tool_schema(_tool_to_schema(tool))
                    ),
                    system_message_policy=self.protocol_route.policy.system_message_policy,
                    allow_assistant_prefill=self.protocol_route.policy.allow_assistant_prefill,
                    reasoning_roundtrip=self.protocol_route.compat.reasoning_roundtrip,
                    replay_state=replay_state,
                    output_schema=output_schema,
                )
            )
            wire_payload = wire_adapter.encode_request(semantic_request, route=self.protocol_route)
            built = compose_runtime_wire_payload(
                build_input,
                wire_payload=wire_payload,
                has_prompt_cache_control=_messages_have_prompt_cache_control(provider_messages),
            )
        else:
            raise AssertionError("registered wire adapter uses unsupported protocol")
        final_payload = self._apply_invocation_budget_preflight(
            built.payload,
            metadata=metadata,
            invocation_scope=invocation_scope,
        )
        self._last_payload_protocol_summary = dict(
            built.summary or payload_protocol_summary(final_payload, self.protocol_route)
        )
        final_output_limit = final_payload.get(
            "max_output_tokens", final_payload.get("max_tokens")
        )
        if isinstance(final_output_limit, int) and not isinstance(
            final_output_limit, bool
        ):
            self._last_payload_protocol_summary["maxTokens"] = final_output_limit
            if final_output_limit < max(
                0, int(getattr(self.profile, "max_output_tokens", 0) or 0)
            ):
                self._last_payload_protocol_summary["budgetOutputClamped"] = True
        if output_schema is not None:
            self._last_payload_protocol_summary.update(
                {
                    "structuredOutput": True,
                    "outputSchemaName": output_schema.name,
                    "outputSchemaSha256": output_schema.schema_sha256,
                    "outputSchemaStrict": True,
                }
            )
        if provider_tool_chain_repaired:
            self._last_payload_protocol_summary["payloadPolicyProviderToolChainRepaired"] = max(
                provider_tool_chain_repaired,
                int(self._last_payload_protocol_summary.get("payloadPolicyProviderToolChainRepaired") or 0),
            )
        return final_payload

    def _usage_from_response(self, response: Any, latency_ms: int) -> UsageStats:
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")
        return usage_stats_from_payload(usage, latency_ms=latency_ms)

    def _choice_message(self, response: Any) -> Dict[str, Any]:
        if isinstance(response, dict):
            choices = response.get("choices") or []
            return (choices[0] or {}).get("message") or {}
        choices = getattr(response, "choices", None) or []
        if not choices:
            return {}
        choice = choices[0]
        message = getattr(choice, "message", None)
        if message is None and isinstance(choice, dict):
            message = choice.get("message")
        if hasattr(message, "model_dump"):
            return message.model_dump()
        if isinstance(message, dict):
            return message
        if message is not None:
            return {
                "role": getattr(message, "role", "assistant"),
                "content": getattr(message, "content", ""),
                "tool_calls": getattr(message, "tool_calls", []),
            }
        return {}

    def _responses_message(self, response: Any) -> Dict[str, Any]:
        text = self._responses_text(response)
        return {"role": "assistant", "content": text, "tool_calls": []}

    def _responses_text(self, response: Any) -> str:
        if isinstance(response, dict):
            output_text = response.get("output_text")
            if isinstance(output_text, str):
                return output_text
            return self._responses_text_from_output(response.get("output"))
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str):
            return output_text
        return self._responses_text_from_output(getattr(response, "output", None))

    def _responses_text_from_output(self, output: Any) -> str:
        parts: List[str] = []
        for item in list(output or []):
            item_dict = self._provider_object_to_dict(item)
            if not isinstance(item_dict, dict):
                continue
            if isinstance(item_dict.get("text"), str):
                parts.append(item_dict.get("text") or "")
            content = item_dict.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                block_dict = self._provider_object_to_dict(block)
                if not isinstance(block_dict, dict):
                    continue
                text = block_dict.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)

    @staticmethod
    def _provider_object_to_dict(value: Any) -> Dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            dumped = value.model_dump()
            return dumped if isinstance(dumped, dict) else None
        if value is not None and hasattr(value, "__dict__"):
            return dict(getattr(value, "__dict__", {}) or {})
        return None

    def _decode_canonical_response(
        self,
        response: Any,
        metadata: Optional[Dict[str, Any]],
        invocation_scope: Any = None,
    ) -> Optional[TurnOutcome]:
        from .invocation import invocation_scope_from_metadata

        adapter = self._required_wire_adapter()
        return adapter.decode_response(
            response,
            route=self.protocol_route,
            scope=invocation_scope or invocation_scope_from_metadata(metadata),
        )

    @staticmethod
    def _canonical_compatibility_text(outcome: TurnOutcome) -> str:
        if outcome.final_text:
            return outcome.final_text
        completed_by_item: Dict[str, Any] = {}
        for event in outcome.events:
            if event.kind == "item_completed" and event.phase == "commentary" and event.text:
                completed_by_item[event.item_id or str(event.sequence)] = event
        completed_text = "".join(event.text for event in completed_by_item.values())
        if completed_text:
            return completed_text
        return "".join(
            event.text
            for event in outcome.events
            if event.kind in {"interim_text_delta", "commentary_delta"} and event.text
        )

    @staticmethod
    def _canonical_compatibility_tool_calls(outcome: TurnOutcome) -> List[Dict[str, Any]]:
        return [
            {"id": call.call_id, "name": call.name, "args": dict(call.arguments)}
            for call in outcome.tool_calls
        ]

    @staticmethod
    def _canonical_compatibility_reasoning(outcome: TurnOutcome) -> str:
        order: List[str] = []
        text_by_item: Dict[str, str] = {}
        for event in outcome.events:
            if event.kind != "reasoning_delta" or not event.text:
                continue
            item_key = event.item_id or f"reasoning:{event.sequence}"
            current = text_by_item.get(item_key, "")
            incoming = event.text
            if item_key not in text_by_item:
                order.append(item_key)
                text_by_item[item_key] = incoming
            elif incoming == current or current.endswith(incoming):
                continue
            elif incoming.startswith(current):
                text_by_item[item_key] = incoming
            else:
                text_by_item[item_key] = current + incoming
        return "".join(text_by_item[item_key] for item_key in order)

    def _record_canonical_outcome(self, outcome: TurnOutcome, *, phase: str) -> None:
        replay_summary = (
            outcome.replay_state.safe_summary()
            if outcome.replay_state is not None and hasattr(outcome.replay_state, "safe_summary")
            else {}
        )
        _record_llm_scene_event(
            phase,
            "llm.canonical_outcome.finalized",
            message="Canonical LLM outcome finalized.",
            outcome="succeeded" if outcome.kind not in {"failed", "cancelled"} else outcome.kind,
            fields={
                "profileId": self.profile_id,
                "provider": self.provider.kind,
                "model": self.profile.model,
                "invocationId": outcome.identity.invocation_id,
                "iteration": outcome.identity.iteration,
                "outcomeKind": outcome.kind,
                "terminalReason": str(outcome.error or "") if outcome.kind == "incomplete" else "",
                "terminalEventSeen": bool(outcome.terminal_event_seen),
                "toolCallCount": len(outcome.tool_calls),
                "pendingToolCallCount": len(outcome.pending_tool_call_ids),
                "hasReplayState": outcome.replay_state is not None,
                "replayItemCount": int(replay_summary.get("itemCount") or 0),
                "replayByteSize": int(replay_summary.get("byteSize") or 0),
                "replayHasResponseId": bool(replay_summary.get("hasResponseId")),
            },
            lifecycle=False,
        )

    def _receipt_context(
        self,
        metadata: Optional[Dict[str, Any]],
        invocation_scope: Any,
    ) -> dict[str, Any] | None:
        """Read an explicit question-stage binding without inferring lineage."""

        # Receipt authority is scoped by the server worker. Persisted or
        # client-provided message metadata is transport data, not lineage
        # authority and must never be allowed to mint a formal receipt.
        raw = _MODEL_INVOCATION_RECEIPT_CONTEXT.get()
        if not isinstance(raw, Mapping):
            return None
        binding_payload = raw.get("questionStageBinding") or raw.get("binding")
        if hasattr(binding_payload, "to_dict"):
            binding_payload = binding_payload.to_dict()
        binding: Any
        if isinstance(binding_payload, Mapping):
            try:
                from core.research.workflow.contracts.question_stage_binding import (
                    QuestionStageBinding,
                )

                stage_binding = QuestionStageBinding.from_dict(binding_payload)
            except (TypeError, ValueError, KeyError):
                return None
            outcome_kinds = tuple(
                dict.fromkeys(
                    str(item or "").strip().lower()
                    for item in list(raw.get("outcomeKinds") or [])
                    if str(item or "").strip()
                )
            ) or (stage_binding.question_stage,)
            if any(
                item not in _MODEL_INVOCATION_RECEIPT_OUTCOME_KINDS
                for item in outcome_kinds
            ):
                return None
            binding = {
                "questionId": stage_binding.question_id,
                "questionRunId": stage_binding.question_run_id,
                "workflowRunId": stage_binding.workflow_run_id,
                "workflowId": stage_binding.workflow_id,
                "workflowVersionId": stage_binding.workflow_version_id,
                "formalNodeId": stage_binding.formal_node_id,
                "formalNodeRunId": stage_binding.formal_node_run_id,
                "formalNodeAttempt": stage_binding.formal_node_attempt,
                "sessionId": stage_binding.session_id,
                "taskId": stage_binding.task_id,
                "turnId": stage_binding.turn_id,
                "questionStage": stage_binding.question_stage,
                "outcomeKinds": list(outcome_kinds),
                "mappingPolicyId": stage_binding.mapping_policy_id,
            }
        else:
            binding = dict(raw.get("questionInvocationBinding") or {})
            required = (
                "questionId",
                "workflowRunId",
                "formalNodeId",
                "formalNodeRunId",
                "sessionId",
                "taskId",
                "turnId",
            )
            if any(not str(binding.get(key) or "").strip() for key in required):
                return None
            outcome_kinds = tuple(
                dict.fromkeys(
                    str(item or "").strip().lower()
                    for item in list(binding.get("outcomeKinds") or [])
                    if str(item or "").strip()
                )
            )
            if not outcome_kinds or any(
                item not in _MODEL_INVOCATION_RECEIPT_OUTCOME_KINDS
                for item in outcome_kinds
            ):
                return None
            binding["outcomeKinds"] = list(outcome_kinds)
            binding.setdefault("questionRunId", binding["workflowRunId"])
            binding.setdefault("formalNodeAttempt", 1)
            binding.setdefault("mappingPolicyId", "challenge-question-invocation-binding-v1")
        if (
            str(getattr(invocation_scope, "session_id", "") or "").strip()
            != str(binding.get("sessionId") or "").strip()
            or str(getattr(invocation_scope, "turn_id", "") or "").strip()
            != str(binding.get("turnId") or "").strip()
        ):
            return None

        authority = str(raw.get("receiptRunAuthority") or "").strip().lower()
        receipt_run_id = str(raw.get("receiptRunId") or "").strip()
        if authority == "question_run":
            expected_run_id = str(binding.get("questionRunId") or "").strip()
        elif authority == "workflow_run":
            expected_run_id = str(binding.get("workflowRunId") or "").strip()
        elif authority == "source_run":
            expected_run_id = str(raw.get("sourceRunId") or "").strip()
        else:
            return None
        if not receipt_run_id or receipt_run_id != expected_run_id:
            return None

        expected_route = raw.get("expectedModelRoute")
        if not isinstance(expected_route, Mapping):
            return None
        expected_provider = str(expected_route.get("providerId") or "").strip()
        expected_model = str(expected_route.get("modelId") or "").strip()
        expected_model_ref = str(expected_route.get("modelRef") or "").strip()
        if (
            not expected_provider
            or not expected_model
            or expected_model_ref.partition("/")[0].lower()
            != expected_provider.lower()
        ):
            return None

        policy_sha256 = str(raw.get("modelPolicySha256") or "").strip().lower()
        if (
            len(policy_sha256) != 64
            or any(char not in "0123456789abcdef" for char in policy_sha256)
        ):
            return None
        return {
            "raw": dict(raw),
            "binding": binding,
            "receiptRunId": receipt_run_id,
            "modelPolicySha256": policy_sha256,
            "expectedProviderId": expected_provider,
            "expectedModelId": expected_model,
            "expectedModelRef": expected_model_ref,
        }

    def _apply_invocation_budget_preflight(
        self,
        payload: Dict[str, Any],
        *,
        metadata: Optional[Dict[str, Any]],
        invocation_scope: Any,
    ) -> Dict[str, Any]:
        """Apply an ephemeral server-owned budget clamp before provider I/O."""

        raw = _MODEL_INVOCATION_RECEIPT_CONTEXT.get()
        callback = (
            raw.get("invocationBudgetPreflight")
            if isinstance(raw, Mapping)
            else None
        )
        if not callable(callback):
            return payload
        context = self._receipt_context(metadata, invocation_scope)
        if context is None:
            raise LLMError(
                "budget_authority_error",
                "Challenge invocation budget binding is invalid.",
                retryable=False,
                provider=self.provider.kind,
                model=self.profile.model,
                details={"payloadValidationResult": "blocked_before_provider"},
            )
        output_key = (
            "max_output_tokens" if "max_output_tokens" in payload else "max_tokens"
        )
        profile_limit = max(0, int(payload.get(output_key) or 0))
        estimated_input = _estimate_messages_for_usage(
            payload.get("messages") or payload.get("input") or []
        )
        schema_payload = {
            key: payload.get(key)
            for key in ("tools", "response_format", "text")
            if payload.get(key) not in (None, [], {})
        }
        if schema_payload:
            estimated_input += _estimate_text_for_usage(
                json.dumps(
                    schema_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
            )
        try:
            decision = callback(
                estimated_input_tokens=estimated_input,
                max_output_tokens=profile_limit,
            )
        except Exception as exc:
            raise LLMError(
                "budget_authority_error",
                "Challenge invocation budget authority is unavailable.",
                retryable=False,
                provider=self.provider.kind,
                model=self.profile.model,
                details={"payloadValidationResult": "blocked_before_provider"},
            ) from exc
        if not isinstance(decision, Mapping):
            raise LLMError(
                "budget_authority_error",
                "Challenge invocation budget decision is invalid.",
                retryable=False,
                provider=self.provider.kind,
                model=self.profile.model,
                details={"payloadValidationResult": "blocked_before_provider"},
            )
        allowed_output = max(0, int(decision.get("maxOutputTokens") or 0))
        remaining = max(0, int(decision.get("remainingTokens") or 0))
        if allowed_output <= 0:
            # Machine-readable rejection detail: which side failed (input
            # overrun vs output floor) and how much output space the floor
            # requires, mirroring quota-style 429/403 payloads.
            reason = str(decision.get("reason") or "").strip() or (
                "insufficient_budget"
            )
            required_min_output = decision.get("requiredMinOutput")
            details = {
                "payloadValidationResult": "blocked_before_provider",
                "remainingTokens": remaining,
                "estimatedInputTokens": estimated_input,
                "reason": reason,
            }
            if (
                isinstance(required_min_output, int)
                and not isinstance(required_min_output, bool)
                and required_min_output > 0
            ):
                details["requiredMinOutput"] = required_min_output
            raise LLMError(
                "budget_exhausted",
                "Challenge invocation token budget is exhausted.",
                retryable=False,
                provider=self.provider.kind,
                model=self.profile.model,
                details=details,
            )
        clamped = dict(payload)
        clamped[output_key] = min(profile_limit, allowed_output)
        return clamped

    def _attach_model_invocation_receipt(
        self,
        outcome: TurnOutcome,
        *,
        metadata: Optional[Dict[str, Any]],
        invocation_scope: Any,
        request_content: Any,
        response_content: Any,
        started_at_ms: int,
        finished_at_ms: int,
        attempt: int,
        retry_count: int,
        token_usage: Mapping[str, int] | None = None,
    ) -> TurnOutcome:
        """Attach a bounded receipt only when the caller supplied full binding."""

        context = self._receipt_context(metadata, invocation_scope)
        if context is None:
            return outcome
        binding = context["binding"]
        raw = context["raw"]
        # The persisted request summary is redacted to bounded shape metadata
        # and the wire payload carries a litellm routing name, so neither is
        # the resolved model identity; this client's resolved profile is.
        actual_model = str(getattr(self.profile, "model", "") or "").strip()
        expected_provider = context["expectedProviderId"]
        expected_model = context["expectedModelId"]
        expected_model_ref = context["expectedModelRef"]
        actual_provider = str(self.provider.provider_id or "").strip()
        if (
            not actual_model
            or
            actual_provider.casefold() != expected_provider.casefold()
            or actual_model.casefold() != expected_model.casefold()
            or expected_model_ref.partition("/")[0].casefold()
            != expected_provider.casefold()
        ):
            return outcome
        requested_model = expected_model
        from core.research.workflow.contracts.model_invocation_receipt import (
            ModelInvocationReceipt,
            ModelInvocationStatus,
        )

        status = (
            ModelInvocationStatus.RETRIED
            if retry_count > 0
            else ModelInvocationStatus.SUCCEEDED
        )
        try:
            provider_attempt = max(1, int(attempt))
            invocation_id = str(
                getattr(invocation_scope, "invocation_id", "") or ""
            ).strip()
            if not invocation_id:
                return outcome
            iteration = max(
                0, int(getattr(invocation_scope, "iteration", 0) or 0)
            )
            usage = token_usage or (
                raw.get("tokenUsage") if isinstance(raw.get("tokenUsage"), Mapping) else {}
            )
            normalized_token_usage = {
                key: max(0, int(value or 0))
                for key, value in {
                    "inputTokens": usage.get("inputTokens", 0),
                    "outputTokens": usage.get("outputTokens", 0),
                    "totalTokens": usage.get("totalTokens", 0),
                    "cachedInputTokens": usage.get("cachedInputTokens", 0),
                    "reasoningTokens": usage.get(
                        "reasoningTokens",
                        usage.get("reasoningOutputTokens", 0),
                    ),
                }.items()
            }
            evidence_locator = (
                dict(raw.get("evidenceLocator"))
                if isinstance(raw.get("evidenceLocator"), Mapping)
                else {}
            )
            evidence_locator.update(
                {
                    "kind": str(
                        evidence_locator.get("kind")
                        or "challenge_model_invocation_receipt_registry"
                    ),
                    "outputRef": (
                        f"challenge-receipt://{quote(binding['questionId'], safe='')}"
                        f"/{quote(context['receiptRunId'], safe='')}"
                        f"/{quote(binding['taskId'], safe='')}"
                        f"/{quote(binding['turnId'], safe='')}"
                    ),
                    "outputSha256": str(
                        evidence_locator.get("outputSha256")
                        or raw.get("outputSha256")
                        or _receipt_output_hash(outcome)
                    ).strip().lower(),
                    "sessionId": binding["sessionId"],
                    "taskId": binding["taskId"],
                    "turnId": binding["turnId"],
                    "formalNodeId": binding["formalNodeId"],
                    "formalNodeRunId": binding["formalNodeRunId"],
                    "modelPolicySha256": context["modelPolicySha256"],
                    "invocationId": invocation_id,
                    "iteration": iteration,
                    "attempt": provider_attempt,
                }
            )
            safe_metadata = {
                "captureSource": "llm_provider_boundary",
                "questionStage": str(binding.get("questionStage") or ""),
                "outcomeKinds": list(binding.get("outcomeKinds") or []),
                "mappingPolicyId": binding["mappingPolicyId"],
                "workflowId": binding["workflowId"],
                "workflowVersionId": binding["workflowVersionId"],
                "formalNodeAttempt": int(binding["formalNodeAttempt"]),
                "llmPayloadTraceId": str(
                    (metadata or {}).get("llmPayloadTraceId") or ""
                ).strip(),
            }
            receipt = ModelInvocationReceipt.from_invocation(
                receipt_id=str(
                    raw.get("receiptId")
                    or (
                        "model-receipt-"
                        f"{invocation_id}-"
                        f"{iteration}-attempt-{provider_attempt}"
                    )
                ).strip(),
                run_id=context["receiptRunId"],
                node_run_id=binding["formalNodeRunId"],
                scope={
                    "questionId": binding["questionId"],
                    "runId": context["receiptRunId"],
                    "taskId": binding["taskId"],
                    "turnId": binding["turnId"],
                    "stageId": str(binding.get("questionStage") or binding["formalNodeId"]),
                    "questionStage": str(binding.get("questionStage") or ""),
                    "modelPolicySha256": context["modelPolicySha256"],
                    "workflowRunId": binding["workflowRunId"],
                    "workflowId": binding["workflowId"],
                    "workflowVersionId": binding["workflowVersionId"],
                    "formalNodeId": binding["formalNodeId"],
                    "formalNodeRunId": binding["formalNodeRunId"],
                    "formalNodeAttempt": str(binding["formalNodeAttempt"]),
                    "sessionId": binding["sessionId"],
                    "attempt": str(provider_attempt),
                },
                provider=actual_provider,
                model=actual_model,
                requested_model=requested_model,
                status=status,
                request_content=request_content,
                response_content=response_content,
                started_at_ms=max(0, int(started_at_ms)),
                finished_at_ms=max(max(0, int(started_at_ms)), int(finished_at_ms)),
                attempt=provider_attempt,
                retry_count=max(0, int(retry_count)),
                token_usage=normalized_token_usage,
                cost=(
                    {"estimatedCost": float(raw.get("estimatedCost") or 0.0)}
                    if raw.get("estimatedCost") not in (None, "")
                    else {}
                ),
                metadata=safe_metadata,
                evidence_locator=evidence_locator,
            )
        except (TypeError, ValueError, KeyError, OverflowError):
            # Receipt capture must never turn a successful provider response
            # into an unbound or partially persisted official record.
            return outcome
        return replace(outcome, model_invocation_receipt=receipt.to_dict())

    def invoke_outcome(
        self,
        messages: List[Any],
        *,
        tools: Optional[List[Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        replay_state: Any = None,
        output_schema: SemanticOutputSchema | None = None,
    ) -> TurnOutcome:
        from .invocation import invocation_scope_from_metadata

        start = time.time()
        invocation_scope = invocation_scope_from_metadata(metadata)
        payload = self._build_payload(
            messages,
            tools=tools,
            stream=False,
            metadata=metadata,
            invocation_scope=invocation_scope,
            replay_state=replay_state,
            output_schema=output_schema,
        )
        provider_conversation_items = _payload_conversation_items(payload) or messages
        message_role_summary = _safe_message_role_summary(provider_conversation_items)
        message_order_summary = _safe_message_order_cache_summary(provider_conversation_items)
        route_summary = _safe_payload_route_summary(payload, self.profile, self.provider)
        responses_continuation_summary = _safe_responses_continuation_summary(payload)
        payload_shape_summary = _safe_payload_shape_summary(payload)
        prompt_cache_design_summary = _safe_prompt_cache_design_summary(
            messages,
            prompt_cache_mode=str(getattr(getattr(self.profile, "prompt_cache", None), "mode", "") or "disabled"),
        )
        prompt_cache_payload_summary = _safe_prompt_cache_payload_summary(payload)
        thinking_summary = _safe_payload_thinking_summary(payload)
        protocol_summary = dict(self._last_payload_protocol_summary or payload_protocol_summary(payload, self.protocol_route))
        capability_source_summary = _safe_capability_source_summary(self._resolved_spec)
        effective_tools = tools if tools is not None else self.bound_tools
        tool_count = len(effective_tools or [])
        event_metadata = {
            "sessionId": invocation_scope.session_id,
            "turnId": invocation_scope.turn_id,
            "invocationId": invocation_scope.invocation_id,
            "iteration": invocation_scope.iteration,
            "invocationContextPresent": bool(metadata),
            **(metadata or {}),
            **message_role_summary,
            **message_order_summary,
            **route_summary,
            **responses_continuation_summary,
            **payload_shape_summary,
            **prompt_cache_design_summary,
            **prompt_cache_payload_summary,
            **thinking_summary,
            **protocol_summary,
            **capability_source_summary,
        }
        trace_metadata = _trace_metadata_with_context(event_metadata, metadata)
        llm_payload_trace = build_llm_payload_trace(
            phase="invoke",
            stream=False,
            role=self.role,
            profile_id=self.profile_id,
            provider=self.provider.kind,
            model=self.profile.model,
            message_count=len(messages or []),
            tool_count=tool_count,
            metadata=trace_metadata,
            summaries=[
                message_role_summary,
                message_order_summary,
                route_summary,
                responses_continuation_summary,
                payload_shape_summary,
                prompt_cache_design_summary,
                prompt_cache_payload_summary,
                thinking_summary,
                protocol_summary,
                capability_source_summary,
            ],
        )
        _publish_llm_status_event(
            "payload_trace",
            traceId=llm_payload_trace.get("traceId"),
            llmPayloadTrace=llm_payload_trace,
        )
        event_metadata = {
            **event_metadata,
            "llmPayloadTraceId": llm_payload_trace.get("traceId", ""),
            "retryRequestMode": "same_wire_payload",
        }
        backend_started_at_ms = int(time.time() * 1000)
        response = self._invoke_backend_with_retry(
            payload,
            phase="invoke",
            event_code="llm.invoke.failed",
            message_count=len(messages or []),
            tool_count=tool_count,
            metadata=event_metadata,
        )
        backend_finished_at_ms = int(time.time() * 1000)
        backend_attempt, backend_retry_count = _LLM_BACKEND_ATTEMPT_CONTEXT.get()
        turn_outcome = self._decode_canonical_response(
            response,
            metadata,
            invocation_scope=invocation_scope,
        )
        turn_outcome = _dedupe_outcome_tool_calls_against_chain(turn_outcome, messages)
        latency_ms = int((time.time() - start) * 1000)
        message = self._responses_message(response) if _payload_uses_responses(payload) else self._choice_message(response)
        tool_calls = extract_message_tool_calls(message)
        usage = self._usage_from_response(response, latency_ms)
        reasoning = extract_reasoning_text(message, extract_text_content)
        reasoning_content = reasoning.text
        cache_observation_fields = _usage_cache_observation_fields(usage)
        estimated_input_tokens = 0
        estimated_output_tokens = 0
        if not (usage.input_tokens or usage.output_tokens or usage.total_tokens):
            estimated_input_tokens = _estimate_messages_for_usage(messages)
            estimated_output_tokens = _estimate_text_for_usage(message.get("content") or "")
        _record_usage_ledger_event(
            usage=usage,
            metadata=metadata,
            provider=self.provider.kind,
            model=self.profile.model,
            profile_id=self.profile_id,
            transport=str(protocol_summary.get("transport") or ""),
            context_window=max(0, int(getattr(self._resolved_spec, "context_window", 0) or 0)),
            estimated_input_tokens=estimated_input_tokens,
            estimated_output_tokens=estimated_output_tokens,
        )
        _record_llm_scene_event(
            "invoke",
            "llm.invoke.succeeded",
            message="LLM invoke succeeded.",
            outcome="succeeded",
            fields={
                "role": self.role,
                "profileId": self.profile_id,
                "provider": self.provider.kind,
                "model": self.profile.model,
                "messageCount": len(messages or []),
                "toolCount": tool_count,
                "toolCallCount": len(tool_calls),
                **route_summary,
                **message_role_summary,
                **message_order_summary,
                **payload_shape_summary,
                **prompt_cache_design_summary,
                **prompt_cache_payload_summary,
                **thinking_summary,
                **protocol_summary,
                **capability_source_summary,
                "llmPayloadTraceId": llm_payload_trace.get("traceId", ""),
                "inputTokens": usage.input_tokens,
                "outputTokens": usage.output_tokens,
                "reasoningOutputTokens": usage.reasoning_output_tokens,
                "totalTokens": usage.total_tokens,
                **cache_observation_fields,
                "reasoningSource": reasoning.source,
                "reasoningChars": len(reasoning_content),
                "reasoningObserved": bool(reasoning_content.strip()),
                "latencyMs": latency_ms,
                "metadata": metadata or {},
            },
            lifecycle=False,
        )
        if turn_outcome is None:
            raise LLMError(
                "protocol_error",
                "wire adapter did not produce canonical TurnOutcome",
                retryable=False,
                provider=self.provider.kind,
                model=self.profile.model,
            )
        turn_outcome = self._attach_model_invocation_receipt(
            turn_outcome,
            metadata=metadata,
            invocation_scope=invocation_scope,
            request_content=_canonical_receipt_request_summary(payload),
            response_content=_canonical_receipt_response_summary(turn_outcome),
            started_at_ms=backend_started_at_ms,
            finished_at_ms=backend_finished_at_ms,
            attempt=backend_attempt,
            retry_count=backend_retry_count,
            token_usage={
                "inputTokens": usage.input_tokens,
                "outputTokens": usage.output_tokens,
                "totalTokens": usage.total_tokens,
                "cachedInputTokens": usage.cached_input_tokens,
                "reasoningTokens": usage.reasoning_output_tokens,
            },
        )
        self._record_canonical_outcome(turn_outcome, phase="invoke")
        _raise_if_output_truncated(
            turn_outcome,
            provider=self.provider.kind,
            model=self.profile.model,
            phase="invoke",
        )
        return turn_outcome

    def project_outcome_message(
        self,
        outcome: TurnOutcome,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        include_outcome: bool = False,
    ) -> AIMessage:
        """Project canonical facts into a one-way LangChain compatibility message."""
        additional_kwargs: Dict[str, Any] = {}
        reasoning_content = self._canonical_compatibility_reasoning(outcome)
        if reasoning_content:
            additional_kwargs["reasoning_content"] = reasoning_content
        replay_items = tuple(
            getattr(getattr(outcome, "replay_state", None), "opaque_items", ()) or ()
        )
        replay_item_ids = [
            str(getattr(replay_item, "item_id", "") or "").strip()
            for replay_item in replay_items
            if str(getattr(replay_item, "item_id", "") or "").strip()
        ]
        if len(replay_item_ids) == 1:
            additional_kwargs["reasoning_replay_item_id"] = replay_item_ids[0]
        elif replay_item_ids:
            additional_kwargs["reasoning_replay_item_ids"] = replay_item_ids
        if include_outcome:
            additional_kwargs["turn_outcome"] = outcome
        response_metadata = self._response_metadata(metadata)
        response_metadata["capabilities"] = self.capabilities.__dict__
        usage_event = next(
            (event for event in reversed(outcome.events) if event.kind == "usage_updated"),
            None,
        )
        if usage_event is not None:
            usage_summary = dict(usage_event.diagnostic_summary)
            input_tokens = int(usage_summary.get("inputTokens") or 0)
            cached_input_tokens = int(usage_summary.get("cachedInputTokens") or 0)
            cache_usage_observed = bool(usage_summary.get("cacheUsageObserved"))
            usage_observation = {
                "input_tokens": input_tokens,
                "output_tokens": int(usage_summary.get("outputTokens") or 0),
                "reasoning_output_tokens": int(usage_summary.get("reasoningOutputTokens") or 0),
                "total_tokens": int(usage_summary.get("totalTokens") or 0),
                "cached_input_tokens": cached_input_tokens,
                "cache_read_input_tokens": int(usage_summary.get("cacheReadInputTokens") or 0),
                "cache_creation_input_tokens": int(usage_summary.get("cacheCreationInputTokens") or 0),
                "uncached_input_tokens": int(
                    (usage_summary.get("uncachedInputTokens") or 0)
                    if cache_usage_observed
                    else 0
                ),
                "cache_hit_rate": float(
                    (usage_summary.get("cacheHitRate") or 0.0)
                    if cache_usage_observed
                    else 0.0
                ),
                "cache_usage_observed": cache_usage_observed,
                "cache_usage_missing_reason": str(
                    usage_summary.get("cacheUsageMissingReason") or ""
                ),
            }
            response_metadata["usage_observation"] = usage_observation
            response_metadata["usage"] = {
                "input_tokens": usage_observation["input_tokens"],
                "output_tokens": usage_observation["output_tokens"],
                "total_tokens": usage_observation["total_tokens"],
            }
        return AIMessage(
            content=self._canonical_compatibility_text(outcome),
            tool_calls=self._canonical_compatibility_tool_calls(outcome),
            response_metadata=response_metadata,
            additional_kwargs=additional_kwargs,
        )

    def invoke(
        self,
        messages: List[Any],
        *,
        tools: Optional[List[Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        replay_state: Any = None,
        output_schema: SemanticOutputSchema | None = None,
    ) -> AIMessage:
        outcome = self.invoke_outcome(
            messages,
            tools=tools,
            metadata=metadata,
            replay_state=replay_state,
            output_schema=output_schema,
        )
        return self.project_outcome_message(outcome, metadata=metadata, include_outcome=True)

    def _response_metadata(self, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "role": self.role,
            "profile_id": self.profile_id,
            "provider": self.provider.kind,
            "model": self.profile.model,
            "llm_protocol": dict(self._last_payload_protocol_summary or self.protocol_route.log_summary()),
            "llm_capability_source": _safe_capability_source_summary(self._resolved_spec),
            "metadata": metadata or {},
        }

    def effective_route_identity(self) -> tuple[str, ...]:
        wire_protocol = str(
            getattr(getattr(self.protocol_route, "wire_protocol", None), "value", "")
            or getattr(self.protocol_route, "protocol", "")
            or ""
        ).strip()
        return (
            str(getattr(self.profile, "provider_id", "") or "").strip(),
            str(getattr(self.provider, "kind", "") or "").strip(),
            str(getattr(self.provider, "base_url", "") or "").strip().rstrip("/").lower(),
            str(self.profile_id or "").strip(),
            str(getattr(self.profile, "model", "") or "").strip(),
            wire_protocol,
            str(getattr(self.protocol_route, "adapter_id", "") or "").strip(),
        )

    def effective_route_id(self) -> str:
        material = "\x1f".join(self.effective_route_identity()).encode("utf-8")
        return hashlib.sha256(material).hexdigest()[:16]

    def _invoke_payload_once(self, payload: Dict[str, Any]) -> Any:
        _raise_if_llm_cancelled()
        request_payload, finish_cancel_watch = self._prepare_cancellable_non_stream_request(payload)
        try:
            with _llm_provider_proxy_env(self.config, request_payload.get("base_url")):
                response = self._backend_for_payload(request_payload)(request_payload)
            _raise_if_llm_cancelled()
            return response
        except LLMCancelledError:
            raise
        except Exception as exc:
            reason = _current_llm_cancel_reason()
            if reason:
                raise LLMCancelledError(reason) from exc
            raise
        finally:
            finish_cancel_watch()

    def _backend_for_payload(self, payload: Dict[str, Any]):
        if self.protocol_route.adapter_id == "anthropic_messages_native":
            return self._anthropic_backend
        if _payload_uses_responses(payload) and self._responses_websocket_backend is not None:
            return self._responses_websocket_backend
        return self._responses_backend if _payload_uses_responses(payload) else self._backend

    def _invoke_backend_with_retry(
        self,
        payload: Dict[str, Any],
        *,
        phase: str,
        event_code: str,
        message_count: int,
        tool_count: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        max_attempts = _retry_policy_max_attempts(self.profile, role=self.role)
        last_error: LLMError | None = None
        route_key = _llm_route_concurrency_key(self.provider, self.profile, profile_id=self.profile_id)
        for attempt in range(1, max_attempts + 1):
            try:
                _LLM_BACKEND_ATTEMPT_CONTEXT.set((attempt, max(0, attempt - 1)))
                _raise_if_llm_cancelled()
                with _reserve_llm_route_slot(
                    route_key,
                    limit=_resolve_llm_route_concurrency_limit(self.config),
                    role=self.role,
                    profile_id=self.profile_id,
                    provider=self.provider.kind,
                    model=self.profile.model,
                    phase=phase,
                    message_count=message_count,
                    tool_count=tool_count,
                ):
                    _raise_if_llm_cancelled()
                    request_payload, finish_cancel_watch = self._prepare_cancellable_non_stream_request(payload)
                    try:
                        with _llm_provider_proxy_env(self.config, request_payload.get("base_url")):
                            response = self._backend_for_payload(request_payload)(request_payload)
                        _raise_if_llm_cancelled()
                        _LLM_BACKEND_ATTEMPT_CONTEXT.set((attempt, max(0, attempt - 1)))
                        return response
                    except LLMCancelledError:
                        raise
                    except Exception as exc:
                        reason = _current_llm_cancel_reason()
                        if reason:
                            raise LLMCancelledError(reason) from exc
                        raise
                    finally:
                        finish_cancel_watch()
            except LLMCancelledError as exc:
                raise _llm_cancelled_error(exc.reason) from exc
            except Exception as exc:
                llm_error = classify_exception(exc)
                llm_error = _with_retry_details(llm_error, attempt=attempt, max_attempts=max_attempts)
                last_error = llm_error
                error_category = llm_error.category
                fields = _llm_retry_event_fields(
                    role=self.role,
                    profile_id=self.profile_id,
                    provider=self.provider.kind,
                    model=self.profile.model,
                    message_count=message_count,
                    tool_count=tool_count,
                    metadata=metadata,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    llm_error=llm_error,
                )
                if not llm_error.retryable or attempt >= max_attempts:
                    _record_llm_scene_event(
                        phase,
                        event_code,
                        message=f"LLM {phase} failed{' before iterator' if phase == 'stream' else ''}: {error_category}",
                        level="error",
                        outcome="failed",
                        fields=fields,
                        lifecycle=True,
                    )
                    raise llm_error from exc
                wait_seconds = _retry_policy_backoff_seconds(
                    self.profile,
                    attempt,
                    category=llm_error.category,
                )
                _record_llm_scene_event(
                    phase,
                    f"{event_code}.retrying",
                    message=f"LLM {phase} retrying after {error_category}.",
                    level="warning",
                    outcome="retrying",
                    fields={**fields, "nextAttempt": attempt + 1, "waitSeconds": wait_seconds},
                    lifecycle=True,
                )
                try:
                    _sleep_with_llm_cancel_check(wait_seconds)
                except LLMCancelledError as cancel_exc:
                    raise _llm_cancelled_error(cancel_exc.reason) from cancel_exc
        if last_error is not None:
            raise last_error
        raise LLMError("provider_protocol_error", "LLM backend failed before returning a response.", retryable=False)

    def _record_llm_retry_or_failure(
        self,
        *,
        phase: str,
        event_code: str,
        message: str,
        message_count: int,
        tool_count: int,
        metadata: Optional[Dict[str, Any]],
        attempt: int,
        max_attempts: int,
        llm_error: LLMError,
    ) -> bool:
        fields = _llm_retry_event_fields(
            role=self.role,
            profile_id=self.profile_id,
            provider=self.provider.kind,
            model=self.profile.model,
            message_count=message_count,
            tool_count=tool_count,
            metadata=metadata,
            attempt=attempt,
            max_attempts=max_attempts,
            llm_error=llm_error,
        )
        if not llm_error.retryable or attempt >= max_attempts:
            _record_llm_scene_event(
                phase,
                event_code,
                message=f"{message}: {llm_error.category}",
                level="error",
                outcome="failed",
                fields=fields,
                lifecycle=True,
            )
            _publish_llm_status_event(
                "failed",
                attempt=attempt,
                max_attempts=max_attempts,
                category=llm_error.category,
                retryable=llm_error.retryable,
            )
            return False
        wait_seconds = _retry_policy_backoff_seconds(
            self.profile,
            attempt,
            category=llm_error.category,
        )
        _record_llm_scene_event(
            phase,
            f"{event_code}.retrying",
            message=f"LLM {phase} retrying after {llm_error.category}.",
            level="warning",
            outcome="retrying",
            fields={**fields, "nextAttempt": attempt + 1, "waitSeconds": wait_seconds},
            lifecycle=True,
        )
        _publish_llm_status_event(
            "retrying",
            attempt=attempt,
            max_attempts=max_attempts,
            category=llm_error.category,
            next_attempt=attempt + 1,
            wait_seconds=wait_seconds,
        )
        try:
            _sleep_with_llm_cancel_check(wait_seconds)
        except LLMCancelledError as cancel_exc:
            raise _llm_cancelled_error(cancel_exc.reason) from cancel_exc
        return True

    def _stream_attempt(
        self,
        payload: Dict[str, Any],
        *,
        message_count: int,
        tool_count: int,
        metadata: Optional[Dict[str, Any]] = None,
        invocation_scope: Any = None,
        protocol_event_sink: Optional[Callable[[LLMProtocolEvent], None]] = None,
        scene_identity: Optional[Dict[str, Any]] = None,
        request_messages: Optional[List[Any]] = None,
        stream_deadline_at: float | None = None,
        receipt_builder: Optional[
            Callable[[TurnOutcome, UsageStats | None], TurnOutcome]
        ] = None,
    ) -> Tuple[Iterator[StreamChunk], Callable[[], bool], Callable[[], Optional[TurnOutcome]]]:
        _raise_if_llm_cancelled()
        emitted = False
        turn_outcome: TurnOutcome | None = None

        # 独立的 total-deadline watcher：永远挂载，不受
        # enable_chat_provider_abort 门控。现有的 opt-in 取消 closer
        #（_prepare_cancellable_chat_stream）语义保持不变，两者叠加。
        # Timer 到点强制 close 底层 stream/response，让阻塞在 socket read
        # 上的线程以异常解卷并在 finally 归还路由槽位。
        deadline_fired = threading.Event()
        deadline_timer_holder: list[threading.Timer] = []
        stream_iterator_holder: list[Any] = []
        turn_key = str(dict(scene_identity or {}).get("turnId") or "").strip()

        def _force_close_stream_on_deadline() -> None:
            deadline_fired.set()
            force_close_llm_stream(stream_iterator_holder[0] if stream_iterator_holder else None)

        def _arm_stream_deadline_guard() -> None:
            if stream_deadline_at is None or deadline_timer_holder:
                return
            remaining = max(0.0, stream_deadline_at - time.monotonic())
            timer = threading.Timer(remaining, _force_close_stream_on_deadline)
            timer.daemon = True
            try:
                timer.start()
            except Exception:
                return
            deadline_timer_holder.append(timer)

        def _teardown_stream_deadline_guard() -> None:
            while deadline_timer_holder:
                timer = deadline_timer_holder.pop()
                timer.cancel()
            if turn_key:
                _unregister_llm_stream_close_hook(turn_key, _force_close_stream_on_deadline)

        def _raise_if_stream_deadline_exceeded() -> None:
            if stream_deadline_at is None:
                return
            if time.monotonic() >= stream_deadline_at:
                raise LLMStreamTotalDeadlineError(
                    deadline_seconds=_llm_stream_total_deadline_seconds(),
                    provider=self.provider.kind,
                    model=self.profile.model,
                )

        def events() -> Iterator[StreamChunk]:
            nonlocal emitted, turn_outcome
            iterator: Any = None
            normalized_iterator: Any = None
            pending_reasoning: list[StreamChunk] = []

            def flush_pending_reasoning() -> Iterator[StreamChunk]:
                nonlocal emitted
                buffered = tuple(pending_reasoning)
                pending_reasoning.clear()
                for chunk in buffered:
                    emitted = True
                    yield chunk

            with _llm_provider_proxy_env(self.config, payload.get("base_url")):
                iterator = self._open_provider_stream(payload)
                stream_iterator_holder.append(iterator)
                _arm_stream_deadline_guard()
                _raise_if_stream_deadline_exceeded()
                if turn_key:
                    _register_llm_stream_close_hook(turn_key, _force_close_stream_on_deadline)
                wire_adapter = self._required_wire_adapter()
                if wire_adapter is None:
                    raise AssertionError("required wire adapter returned None")
                else:
                    from .invocation import invocation_scope_from_metadata

                    provider_usage: UsageStats | None = None

                    def observed_wire_events() -> Iterator[Any]:
                        nonlocal provider_usage
                        for raw_event in iterator:
                            raw_dict = self._provider_object_to_dict(raw_event) or {}
                            http_timings = current_stream_http_timings()
                            if http_timings is not None and http_timings.first_raw_event_ms is None:
                                event_kind = classify_raw_stream_event(raw_dict)
                                http_timings.mark_first_raw_event(event_kind)
                                _record_llm_scene_event(
                                    "stream",
                                    "llm.stream.first_raw_event",
                                    message="LLM stream received its first provider wire event.",
                                    outcome="observed",
                                    fields={
                                        **dict(scene_identity or {}),
                                        "elapsedMs": http_timings.first_raw_event_ms,
                                        "eventKind": event_kind,
                                        "httpHeadersMs": http_timings.http_headers_ms,
                                        "requestBodySentMs": http_timings.request_body_sent_ms,
                                        "connectMs": http_timings.connect_ms,
                                    },
                                    lifecycle=False,
                                )
                            response_dict = self._provider_object_to_dict(raw_dict.get("response")) or {}
                            raw_usage = raw_dict.get("usage") or response_dict.get("usage")
                            if raw_usage is not None:
                                provider_usage = usage_stats_from_payload(raw_usage)
                            yield raw_event

                    normalized_iterator = wire_adapter.decode_stream(
                        observed_wire_events(),
                        route=self.protocol_route,
                        scope=(invocation_scope or invocation_scope_from_metadata(metadata)),
                    )
                try:
                    if wire_adapter is None:
                        raise AssertionError("required wire adapter returned None")
                    else:
                        text_items_seen: set[str] = set()
                        canonical_usage: UsageStats | None = None
                        for event in normalized_iterator:
                            _raise_if_llm_cancelled()
                            _raise_if_stream_deadline_exceeded()
                            if protocol_event_sink is not None:
                                protocol_event_sink(event)
                            projected: StreamChunk | None = None
                            item_key = event.item_id or f"sequence:{event.sequence}"
                            if event.kind in {"interim_text_delta", "commentary_delta", "answer_delta"}:
                                text_items_seen.add(item_key)
                                projected = StreamChunk(type="text_delta", text=event.text)
                            elif event.kind == "item_completed" and event.text and item_key not in text_items_seen:
                                text_items_seen.add(item_key)
                                projected = StreamChunk(type="text_delta", text=event.text)
                            elif event.kind == "reasoning_delta":
                                reasoning_source = str(
                                    event.diagnostic_summary.get("reasoningSource") or "canonical"
                                ).strip()
                                projected = StreamChunk(
                                    type="reasoning_delta",
                                    text=event.text,
                                    provider_payload={"reasoning_source": reasoning_source},
                                )
                            elif event.kind == "usage_updated":
                                usage_summary = dict(event.diagnostic_summary)
                                canonical_usage = usage_stats_from_payload(
                                    {
                                        "input_tokens": int(usage_summary.get("inputTokens") or 0),
                                        "output_tokens": int(usage_summary.get("outputTokens") or 0),
                                        "reasoning_output_tokens": int(
                                            usage_summary.get("reasoningOutputTokens") or 0
                                        ),
                                        "total_tokens": int(usage_summary.get("totalTokens") or 0),
                                        "cached_input_tokens": int(
                                            usage_summary.get("cachedInputTokens") or 0
                                        ),
                                        "cache_creation_input_tokens": int(
                                            usage_summary.get("cacheCreationInputTokens") or 0
                                        ),
                                    }
                                )
                            if projected is not None and projected.type == "reasoning_delta":
                                pending_reasoning.append(projected)
                            elif projected is not None:
                                yield from flush_pending_reasoning()
                                emitted = True
                                yield projected
                            _raise_if_llm_cancelled()
                        turn_outcome = normalized_iterator.outcome
                        turn_outcome = _dedupe_outcome_tool_calls_against_chain(
                            turn_outcome,
                            list(request_messages or []),
                        )
                        if receipt_builder is not None:
                            turn_outcome = receipt_builder(
                                turn_outcome, provider_usage or canonical_usage
                            )
                        if turn_outcome.tool_calls:
                            yield from flush_pending_reasoning()
                            emitted = True
                            yield StreamChunk(
                                type="tool_call_final",
                                tool_calls=[
                                    ToolCall(
                                        id=call.call_id,
                                        name=call.name,
                                        arguments=dict(call.arguments),
                                        raw_arguments=json.dumps(dict(call.arguments), ensure_ascii=False),
                                    )
                                    for call in turn_outcome.tool_calls
                                ],
                            )
                        allow_chat_retry = self.protocol_route.protocol == ModelProtocol.DEEPSEEK_REASONING
                        suppress_transient_done = _is_retryable_stream_exhaustion(
                            turn_outcome,
                            allow_chat=allow_chat_retry,
                        ) and (turn_outcome.error == STREAM_EXHAUSTED_WITHOUT_TERMINAL or not emitted)
                        if not suppress_transient_done:
                            yield from flush_pending_reasoning()
                            emitted = True
                            yield StreamChunk(
                                type="done",
                                usage=provider_usage or canonical_usage,
                                provider_payload={"turn_outcome": turn_outcome},
                            )
                except LLMCancelledError:
                    close = getattr(normalized_iterator, "close", None)
                    if callable(close):
                        close()
                    close = getattr(iterator, "close", None)
                    if callable(close):
                        close()
                    raise

        def timed_events() -> Iterator[StreamChunk]:
            identity = dict(scene_identity or {})
            origin_host = urlparse(str(payload.get("base_url") or "")).hostname or ""

            def on_http_headers(http_timings: Any) -> None:
                _record_stream_http_headers_event(http_timings, identity=identity)

            with capture_stream_http_timings(
                on_http_headers=on_http_headers,
                origin_host=origin_host,
            ) as timings:
                try:
                    yield from events()
                except Exception as exc:
                    # total-deadline timer 强制关闭底层连接后，阻塞的读会以
                    # 任意连接类异常解卷；把它归一为 timeout/retryable，
                    # 走现有的可重试错误路径。真正的取消/LLMError 保持原样。
                    if (
                        deadline_fired.is_set()
                        and not isinstance(exc, (LLMError, LLMCancelledError))
                    ):
                        raise LLMStreamTotalDeadlineError(
                            deadline_seconds=_llm_stream_total_deadline_seconds(),
                            provider=self.provider.kind,
                            model=self.profile.model,
                        ) from exc
                    raise
                finally:
                    _teardown_stream_deadline_guard()
                    _record_stream_http_timing_summary(timings, identity=identity)

        return timed_events(), lambda: emitted, lambda: turn_outcome

    def stream_events(
        self,
        messages: List[Any],
        *,
        tools: Optional[List[Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        replay_state: Any = None,
        protocol_event_sink: Optional[Callable[[LLMProtocolEvent], None]] = None,
        output_schema: SemanticOutputSchema | None = None,
    ) -> Iterator[StreamChunk]:
        """Yield normalized stream events independent of LangChain chunks."""
        from .invocation import invocation_scope_from_metadata

        payload_prepare_started = time.perf_counter()
        invocation_scope = invocation_scope_from_metadata(metadata)
        payload_build_started = time.perf_counter()
        payload = self._build_payload(
            messages,
            tools=tools,
            stream=True,
            metadata=metadata,
            invocation_scope=invocation_scope,
            replay_state=replay_state,
            output_schema=output_schema,
        )
        payload_build_ms = max(0, int((time.perf_counter() - payload_build_started) * 1000))
        payload_summary_started = time.perf_counter()
        message_count = len(messages or [])
        effective_tools = tools if tools is not None else self.bound_tools
        tool_count = len(effective_tools or [])
        provider_conversation_items = _payload_conversation_items(payload) or messages
        message_role_summary = _safe_message_role_summary(provider_conversation_items)
        message_order_summary = _safe_message_order_cache_summary(provider_conversation_items)
        route_summary = _safe_payload_route_summary(payload, self.profile, self.provider)
        responses_continuation_summary = _safe_responses_continuation_summary(payload)
        payload_shape_summary = _safe_payload_shape_summary(payload)
        prompt_cache_design_summary = _safe_prompt_cache_design_summary(
            messages,
            prompt_cache_mode=str(getattr(getattr(self.profile, "prompt_cache", None), "mode", "") or "disabled"),
        )
        prompt_cache_payload_summary = _safe_prompt_cache_payload_summary(payload)
        thinking_summary = _safe_payload_thinking_summary(payload)
        protocol_summary = dict(self._last_payload_protocol_summary or payload_protocol_summary(payload, self.protocol_route))
        capability_source_summary = _safe_capability_source_summary(self._resolved_spec)
        event_metadata = {
            "sessionId": invocation_scope.session_id,
            "turnId": invocation_scope.turn_id,
            "invocationId": invocation_scope.invocation_id,
            "iteration": invocation_scope.iteration,
            "invocationContextPresent": bool(metadata),
            **(metadata or {}),
            **message_role_summary,
            **message_order_summary,
            **route_summary,
            **responses_continuation_summary,
            **payload_shape_summary,
            **prompt_cache_design_summary,
            **prompt_cache_payload_summary,
            **thinking_summary,
            **protocol_summary,
            **capability_source_summary,
        }
        trace_metadata = _trace_metadata_with_context(event_metadata, metadata)
        llm_payload_trace = build_llm_payload_trace(
            phase="stream",
            stream=True,
            role=self.role,
            profile_id=self.profile_id,
            provider=self.provider.kind,
            model=self.profile.model,
            message_count=message_count,
            tool_count=tool_count,
            metadata=trace_metadata,
            summaries=[
                message_role_summary,
                message_order_summary,
                route_summary,
                responses_continuation_summary,
                payload_shape_summary,
                prompt_cache_design_summary,
                prompt_cache_payload_summary,
                thinking_summary,
                protocol_summary,
                capability_source_summary,
            ],
        )
        _publish_llm_status_event(
            "payload_trace",
            traceId=llm_payload_trace.get("traceId"),
            llmPayloadTrace=llm_payload_trace,
        )
        event_metadata = {
            **event_metadata,
            "llmPayloadTraceId": llm_payload_trace.get("traceId", ""),
            "retryRequestMode": "same_wire_payload",
        }
        payload_summary_ms = max(0, int((time.perf_counter() - payload_summary_started) * 1000))
        payload_prepare_ms = max(0, int((time.perf_counter() - payload_prepare_started) * 1000))
        max_attempts = _retry_policy_max_attempts(self.profile, role=self.role)
        last_error: LLMError | None = None
        stream_usage_options_downgraded = False
        route_key = _llm_route_concurrency_key(self.provider, self.profile, profile_id=self.profile_id)
        for attempt in range(1, max_attempts + 1):
            try:
                _raise_if_llm_cancelled()
            except LLMCancelledError as exc:
                raise _llm_cancelled_error(exc.reason) from exc
            start = time.time()
            # 流式总时长硬上限按单次 attempt 计：litellm 重试循环的每次重试
            # 都在这里重新起算，不跨 attempt 泄漏。
            stream_total_deadline_seconds = _llm_stream_total_deadline_seconds()
            stream_deadline_at = time.monotonic() + stream_total_deadline_seconds
            emitted = False
            chunk_count = 0
            text_delta_count = 0
            reasoning_delta_count = 0
            reasoning_chars = 0
            reasoning_sources: set[str] = set()
            tool_call_count = 0
            first_chunk_ms: int | None = None
            first_text_delta_ms: int | None = None
            first_reasoning_delta_ms: int | None = None
            previous_chunk_at: float | None = None
            max_inter_chunk_ms = 0
            total_inter_chunk_ms = 0
            inter_chunk_count = 0
            usage_observation = UsageStats()
            generated_text_parts: list[str] = []
            try:
                _record_llm_scene_event(
                    "stream",
                    "llm.stream.started",
                    message="LLM stream started.",
                    outcome="running",
                    fields={
                        "role": self.role,
                        "profileId": self.profile_id,
                        "provider": self.provider.kind,
                        "model": self.profile.model,
                        "messageCount": message_count,
                        "toolCount": tool_count,
                        "payloadBuildMs": payload_build_ms,
                        "payloadSummaryMs": payload_summary_ms,
                        "payloadPrepareMs": payload_prepare_ms,
                        **responses_continuation_summary,
                        **event_metadata,
                        "llmPayloadTraceId": llm_payload_trace.get("traceId", ""),
                        "attempt": attempt,
                        "maxAttempts": max_attempts,
                    },
                    lifecycle=False,
                )
                with _reserve_llm_route_slot(
                    route_key,
                    limit=_resolve_llm_route_concurrency_limit(self.config),
                    role=self.role,
                    profile_id=self.profile_id,
                    provider=self.provider.kind,
                    model=self.profile.model,
                    phase="stream",
                    message_count=message_count,
                    tool_count=tool_count,
                ):
                    _raise_if_llm_cancelled()
                    events, emitted_fn, outcome_fn = self._stream_attempt(
                        payload,
                        message_count=message_count,
                        tool_count=tool_count,
                        metadata=metadata,
                        invocation_scope=invocation_scope,
                        protocol_event_sink=protocol_event_sink,
                        stream_deadline_at=stream_deadline_at,
                        scene_identity={
                            "role": self.role,
                            "profileId": self.profile_id,
                            "provider": self.provider.kind,
                            "model": self.profile.model,
                            "sessionId": event_metadata.get("sessionId", ""),
                            "turnId": event_metadata.get("turnId", ""),
                            "invocationId": event_metadata.get("invocationId", ""),
                            "attempt": attempt,
                        },
                        request_messages=list(messages or []),
                        receipt_builder=lambda outcome, usage: self._attach_model_invocation_receipt(
                            outcome,
                            metadata=metadata,
                            invocation_scope=invocation_scope,
                            request_content=_canonical_receipt_request_summary(payload),
                            response_content=_canonical_receipt_response_summary(outcome),
                            started_at_ms=int(start * 1000),
                            finished_at_ms=int(time.time() * 1000),
                            attempt=attempt,
                            retry_count=max(0, attempt - 1),
                            token_usage={
                                "inputTokens": int(getattr(usage, "input_tokens", 0) or 0),
                                "outputTokens": int(getattr(usage, "output_tokens", 0) or 0),
                                "totalTokens": int(getattr(usage, "total_tokens", 0) or 0),
                                "cachedInputTokens": int(
                                    getattr(usage, "cached_input_tokens", 0) or 0
                                ),
                                "reasoningTokens": int(
                                    getattr(usage, "reasoning_output_tokens", 0) or 0
                                ),
                            },
                        ),
                    )
                    for event in events:
                        _raise_if_llm_cancelled()
                        if time.monotonic() >= stream_deadline_at:
                            raise LLMStreamTotalDeadlineError(
                                deadline_seconds=stream_total_deadline_seconds,
                                provider=self.provider.kind,
                                model=self.profile.model,
                            )
                        now = time.time()
                        elapsed_ms = int((now - start) * 1000)
                        if first_chunk_ms is None:
                            first_chunk_ms = elapsed_ms
                            http_timings = current_stream_http_timings()
                            if http_timings is not None:
                                http_timings.mark_first_projected_chunk()
                            _record_llm_scene_event(
                                "stream",
                                "llm.stream.first_chunk",
                                message="LLM stream produced its first protocol chunk.",
                                outcome="observed",
                                fields={
                                    "role": self.role,
                                    "profileId": self.profile_id,
                                    "provider": self.provider.kind,
                                    "model": self.profile.model,
                                    "sessionId": event_metadata.get("sessionId", ""),
                                    "turnId": event_metadata.get("turnId", ""),
                                    "invocationId": event_metadata.get("invocationId", ""),
                                    "routeAttempt": event_metadata.get("routeAttempt", 0),
                                    "elapsedMs": elapsed_ms,
                                    "chunkType": event.type,
                                    "attempt": attempt,
                                    **(
                                        http_timings.first_chunk_scene_fields()
                                        if http_timings is not None
                                        else {}
                                    ),
                                },
                                lifecycle=False,
                            )
                        if previous_chunk_at is not None:
                            inter_chunk_ms = int((now - previous_chunk_at) * 1000)
                            max_inter_chunk_ms = max(max_inter_chunk_ms, inter_chunk_ms)
                            total_inter_chunk_ms += inter_chunk_ms
                            inter_chunk_count += 1
                        previous_chunk_at = now
                        emitted = emitted_fn()
                        chunk_count += 1
                        if event.type == "text_delta":
                            text_delta_count += 1
                            generated_text_parts.append(event.text or "")
                            if first_text_delta_ms is None and (event.text or ""):
                                first_text_delta_ms = elapsed_ms
                                _record_llm_scene_event(
                                    "stream",
                                    "llm.stream.first_content_delta",
                                    message="LLM stream produced its first visible content delta.",
                                    outcome="observed",
                                    fields={
                                        "role": self.role,
                                        "profileId": self.profile_id,
                                        "provider": self.provider.kind,
                                        "model": self.profile.model,
                                        "sessionId": event_metadata.get("sessionId", ""),
                                        "turnId": event_metadata.get("turnId", ""),
                                        "invocationId": event_metadata.get("invocationId", ""),
                                        "routeAttempt": event_metadata.get("routeAttempt", 0),
                                        "elapsedMs": elapsed_ms,
                                        "contentChars": len(event.text or ""),
                                        "attempt": attempt,
                                    },
                                    lifecycle=False,
                                )
                        elif event.type == "reasoning_delta":
                            reasoning_delta_count += 1
                            if first_reasoning_delta_ms is None and (event.text or ""):
                                first_reasoning_delta_ms = elapsed_ms
                                _record_llm_scene_event(
                                    "stream",
                                    "llm.stream.first_reasoning_delta",
                                    message="LLM stream produced its first reasoning delta.",
                                    outcome="observed",
                                    fields={
                                        "role": self.role,
                                        "profileId": self.profile_id,
                                        "provider": self.provider.kind,
                                        "model": self.profile.model,
                                        "sessionId": event_metadata.get("sessionId", ""),
                                        "turnId": event_metadata.get("turnId", ""),
                                        "invocationId": event_metadata.get("invocationId", ""),
                                        "routeAttempt": event_metadata.get("routeAttempt", 0),
                                        "elapsedMs": elapsed_ms,
                                        "reasoningChars": len(event.text or ""),
                                        "attempt": attempt,
                                    },
                                    lifecycle=False,
                                )
                            reasoning_chars += len(event.text or "")
                            if isinstance(event.provider_payload, dict):
                                source = str(event.provider_payload.get("reasoning_source") or "").strip()
                                if source:
                                    reasoning_sources.add(source)
                        elif event.type == "tool_call_final":
                            tool_call_count += len(event.tool_calls or [])
                        elif event.type == "done" and event.usage is not None:
                            usage_observation = event.usage
                        yield event
                        _raise_if_llm_cancelled()
                usage_observation.latency_ms = int((time.time() - start) * 1000)
                estimated_input_tokens = 0
                estimated_output_tokens = 0
                if not (
                    usage_observation.input_tokens
                    or usage_observation.output_tokens
                    or usage_observation.total_tokens
                ):
                    estimated_input_tokens = _estimate_messages_for_usage(messages)
                    estimated_output_tokens = _estimate_text_for_usage("".join(generated_text_parts))
                _record_usage_ledger_event(
                    usage=usage_observation,
                    metadata=metadata,
                    provider=self.provider.kind,
                    model=self.profile.model,
                    profile_id=self.profile_id,
                    transport=str(event_metadata.get("transport") or ""),
                    context_window=max(0, int(getattr(self._resolved_spec, "context_window", 0) or 0)),
                    estimated_input_tokens=estimated_input_tokens,
                    estimated_output_tokens=estimated_output_tokens,
                )
                usage_observed = (
                    bool(usage_observation.provider_raw_usage)
                    and (
                        usage_observation.input_tokens > 0
                        or usage_observation.output_tokens > 0
                        or usage_observation.total_tokens > 0
                        or usage_observation.cached_input_tokens > 0
                        or usage_observation.cache_creation_input_tokens > 0
                    )
                )
                cache_observation_fields = _usage_cache_observation_fields(usage_observation)
                usage_missing_reason = "" if usage_observed else _usage_missing_reason(usage_observation)
                _record_llm_scene_event(
                    "stream",
                    "llm.stream.succeeded",
                    message="LLM stream succeeded.",
                    outcome="succeeded",
                    fields={
                        "role": self.role,
                        "profileId": self.profile_id,
                        "provider": self.provider.kind,
                        "model": self.profile.model,
                        "usageObserved": usage_observed,
                        "usageMissingReason": usage_missing_reason,
                        "inputTokens": usage_observation.input_tokens,
                        "outputTokens": usage_observation.output_tokens,
                        "reasoningOutputTokens": usage_observation.reasoning_output_tokens,
                        "totalTokens": usage_observation.total_tokens,
                        **cache_observation_fields,
                        **{
                            key: event_metadata[key]
                            for key in ("turnId", "sessionId", "invocationId")
                            if event_metadata.get(key)
                        },
                        **responses_continuation_summary,
                        "latencyMs": usage_observation.latency_ms,
                        "messageCount": message_count,
                        "toolCount": tool_count,
                        **event_metadata,
                        "llmPayloadTraceId": llm_payload_trace.get("traceId", ""),
                        "chunkCount": chunk_count,
                        "textDeltaCount": text_delta_count,
                        "reasoningDeltaCount": reasoning_delta_count,
                        "reasoningChars": reasoning_chars,
                        "reasoningSources": sorted(reasoning_sources),
                        "reasoningObserved": reasoning_chars > 0,
                        "firstChunkMs": first_chunk_ms,
                        "firstTextDeltaMs": first_text_delta_ms,
                        "firstReasoningDeltaMs": first_reasoning_delta_ms,
                        "maxInterChunkMs": max_inter_chunk_ms,
                        "avgInterChunkMs": int(total_inter_chunk_ms / inter_chunk_count)
                        if inter_chunk_count > 0
                        else 0,
                        "interChunkCount": inter_chunk_count,
                        "toolCallCount": tool_call_count,
                    },
                    lifecycle=False,
                )
                canonical_outcome = outcome_fn()
                if canonical_outcome is None:
                    raise LLMError(
                        "protocol_error",
                        "wire stream adapter did not produce canonical TurnOutcome",
                        retryable=False,
                        provider=self.provider.kind,
                        model=self.profile.model,
                    )
                self._record_canonical_outcome(canonical_outcome, phase="stream")
                _raise_if_output_truncated(
                    canonical_outcome,
                    provider=self.provider.kind,
                    model=self.profile.model,
                    phase="stream",
                )
                chat_partial_output = bool(emitted) and canonical_outcome.error in {
                    STREAM_EXHAUSTED_WITHOUT_FINISH_REASON,
                    TOOL_ARGUMENTS_UNPARSABLE,
                }
                allow_chat_retry = self.protocol_route.protocol == ModelProtocol.DEEPSEEK_REASONING
                if _is_retryable_stream_exhaustion(
                    canonical_outcome,
                    allow_chat=allow_chat_retry,
                ) and not chat_partial_output:
                    raise LLMError(
                        "server_error",
                        "LLM stream ended before a complete canonical terminal event.",
                        retryable=True,
                        provider=self.provider.kind,
                        model=self.profile.model,
                        details={"terminal_reason": canonical_outcome.error},
                    )
                if attempt > 1 and canonical_outcome.kind in {"final_answer", "tool_calls"}:
                    _publish_llm_status_event(
                        "retry_recovered",
                        attempt=attempt,
                        max_attempts=max_attempts,
                        category=str(getattr(last_error, "category", "") or ""),
                    )
                return canonical_outcome
            except LLMCancelledError as exc:
                llm_error = _llm_cancelled_error(exc.reason)
                _record_llm_scene_event(
                    "stream",
                    "llm.stream.cancelled",
                    message="LLM stream cancelled by turn stop request.",
                    level="warning",
                    outcome="cancelled",
                    fields=_llm_retry_event_fields(
                        role=self.role,
                        profile_id=self.profile_id,
                        provider=self.provider.kind,
                        model=self.profile.model,
                        message_count=message_count,
                        tool_count=tool_count,
                        metadata=event_metadata,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        llm_error=llm_error,
                    ),
                    lifecycle=True,
                )
                _publish_llm_status_event(
                    "cancelled",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    category=llm_error.category,
                    retryable=False,
                )
                raise llm_error from exc
            except Exception as exc:
                llm_error = classify_exception(exc)
                llm_error = _with_retry_details(llm_error, attempt=attempt, max_attempts=max_attempts)
                last_error = llm_error
                if emitted:
                    _record_llm_scene_event(
                        "stream",
                        "llm.stream.failed",
                        message=f"LLM stream failed: {llm_error.category}",
                        level="error",
                        outcome="failed",
                        fields=_llm_retry_event_fields(
                            role=self.role,
                            profile_id=self.profile_id,
                            provider=self.provider.kind,
                            model=self.profile.model,
                            message_count=message_count,
                            tool_count=tool_count,
                            metadata=event_metadata,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            llm_error=llm_error,
                        ),
                        lifecycle=True,
                    )
                    raise llm_error from exc
                if (
                    not stream_usage_options_downgraded
                    and payload.get("stream_options")
                    and _looks_like_stream_usage_options_rejection(exc, llm_error)
                ):
                    payload = dict(payload)
                    payload.pop("stream_options", None)
                    route_summary = _safe_payload_route_summary(payload, self.profile, self.provider)
                    responses_continuation_summary = _safe_responses_continuation_summary(payload)
                    payload_shape_summary = _safe_payload_shape_summary(payload)
                    event_metadata = {
                        "sessionId": invocation_scope.session_id,
                        "turnId": invocation_scope.turn_id,
                        "invocationId": invocation_scope.invocation_id,
                        "iteration": invocation_scope.iteration,
                        "invocationContextPresent": bool(metadata),
                        **(metadata or {}),
                        **message_role_summary,
                        **route_summary,
                        **responses_continuation_summary,
                        **payload_shape_summary,
                        **prompt_cache_design_summary,
                        **_safe_prompt_cache_payload_summary(payload),
                        **_safe_payload_thinking_summary(payload),
                        **protocol_summary,
                        **capability_source_summary,
                        "llmPayloadTraceId": llm_payload_trace.get("traceId", ""),
                        "retryRequestMode": "wire_payload_without_stream_usage_options",
                        "streamUsageOptionsDowngraded": True,
                    }
                    stream_usage_options_downgraded = True
                    _record_llm_scene_event(
                        "stream",
                        "llm.stream.usage_options_downgraded",
                        message="LLM stream usage options were rejected; retrying without stream_options.",
                        level="warning",
                        outcome="retrying",
                        fields=_llm_retry_event_fields(
                            role=self.role,
                            profile_id=self.profile_id,
                            provider=self.provider.kind,
                            model=self.profile.model,
                            message_count=message_count,
                            tool_count=tool_count,
                            metadata=event_metadata,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            llm_error=llm_error,
                        ),
                        lifecycle=True,
                    )
                    continue
                should_retry = self._record_llm_retry_or_failure(
                    phase="stream",
                    event_code="llm.stream.failed",
                    message="LLM stream failed before iterator",
                    message_count=message_count,
                    tool_count=tool_count,
                    metadata=event_metadata,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    llm_error=llm_error,
                )
                if not should_retry:
                    raise llm_error from exc

    def stream(
        self,
        messages: List[Any],
        *,
        tools: Optional[List[Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        output_schema: SemanticOutputSchema | None = None,
    ) -> Iterator[AIMessageChunk]:
        for event in self.stream_events(
            messages,
            tools=tools,
            metadata=metadata,
            output_schema=output_schema,
        ):
            response_metadata = self._response_metadata(metadata)
            if event.type == "done":
                turn_outcome = (event.provider_payload or {}).get("turn_outcome")
                if event.usage is not None or turn_outcome is not None:
                    done_metadata = dict(response_metadata)
                    additional_kwargs = {}
                    if event.usage is not None:
                        done_metadata["usage"] = event.usage.provider_raw_usage
                        done_metadata["usage_observation"] = _usage_observation_metadata(event.usage)
                    if turn_outcome is not None:
                        additional_kwargs["turn_outcome"] = turn_outcome
                    yield AIMessageChunk(
                        content="",
                        additional_kwargs=additional_kwargs,
                        response_metadata=done_metadata,
                    )
                continue
            if event.type == "text_delta":
                yield AIMessageChunk(content=event.text, response_metadata=response_metadata)
            elif event.type == "reasoning_delta":
                yield AIMessageChunk(
                    content="",
                    additional_kwargs={"reasoning_content_delta": event.text},
                    response_metadata=response_metadata,
                )
            elif event.type == "tool_call_final" and event.tool_calls:
                yield AIMessageChunk(
                    content="",
                    tool_calls=[
                        {"id": call.id, "name": call.name, "args": call.arguments}
                        for call in event.tool_calls
                    ],
                    response_metadata=response_metadata,
                )


def get_llm_client(role: Optional[str] = None, profile_id: Optional[str] = None, *, config: Optional[AppConfig] = None) -> LLMClient:
    return LLMClient(config=config or get_config(), role=role or "primary", profile_id=profile_id)


def list_profiles(config: Optional[AppConfig] = None) -> List[str]:
    return sorted((config or get_config()).llm.profiles.keys())
