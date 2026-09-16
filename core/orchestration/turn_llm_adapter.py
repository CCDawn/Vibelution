# -*- coding: utf-8 -*-
"""Agent LLM attempt loop. Invocation, recovery, and routing stay in core.llm."""

from __future__ import annotations

import hashlib
import json
import time
import traceback
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from core.infrastructure.llm_utils import MAX_CONSECUTIVE_FAILURES
from core.llm import LLMError
from core.llm.recovery import DEGRADED_RETRY_ACTIONS, degraded_retry_overrides
from core.llm.route_fallback_registry import record_route_fallback
from core.llm.turn_request_capture import (
    capture_turn_request,
    record_turn_request_outcome,
)
from core.orchestration.agent_runtime_bindings import (
    _llm_effective_route_id,
    _llm_route_trace_fields,
    _safe_llm_error_diagnostic_details,
)

# Explicit fallback switching triggers only when the primary route's transport
# retry budget is exhausted on a gateway-level recoverable failure (the same
# error classes LiteLLM's general ``fallbacks`` bucket covers). Permanent
# categories (auth/parameter/capability) never switch, and the fallback target
# itself is never switched again (single hop, no chained fallbacks).
_FALLBACK_SWITCH_CATEGORIES = frozenset({"network_error", "timeout", "server_error", "rate_limit"})


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _maybe_json(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _as_mapping(value: Any) -> Dict[str, Any]:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _mapping_get(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return None


def _object_field(value: Any, *names: str) -> Any:
    mapped = _as_mapping(value)
    if mapped:
        for name in names:
            if name in mapped:
                return mapped.get(name)
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _coerce_message_list(value: Any) -> list:
    value = _maybe_json(value)
    if value is None or isinstance(value, (str, bytes, bytearray, memoryview)):
        return []
    if isinstance(value, Mapping):
        nested = value.get("messages")
        if nested is None:
            nested = value.get("items")
        if nested is None:
            nested = value.get("history")
        if nested is not None:
            return _coerce_message_list(nested)
        return [dict(value)] if value else []
    try:
        return list(value)
    except TypeError:
        return []


def _coerce_positive_int(value: Any, *, default: int = 1) -> int:
    if isinstance(value, bool):
        return 0
    if value is None:
        parsed = 0
    else:
        if isinstance(value, (bytes, bytearray, memoryview)):
            value = bytes(value).decode("utf-8", errors="replace")
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 0
    if parsed > 0:
        return parsed
    if isinstance(default, bool) or default is None:
        return 1
    try:
        fallback = int(default)
    except (TypeError, ValueError):
        fallback = 1
    return fallback if fallback > 0 else 1


def _llm_error_details(error: BaseException) -> Dict[str, Any]:
    raw = getattr(error, "details", None) if isinstance(error, LLMError) else None
    return _as_mapping(raw)


def _invocation_metadata(invocation_context: Any) -> Dict[str, Any]:
    if invocation_context is None:
        return {}
    return _as_mapping(_object_field(invocation_context, "metadata"))


GetUiFn = Callable[[], Any]
CancelContextFn = Callable[..., Any]
RaiseIfStopFn = Callable[[], None]
StopReasonFn = Callable[[], str]
GetLlmFn = Callable[..., Any]
ShouldStreamFn = Callable[..., bool]
BuildContextFn = Callable[..., Any]
InvokeOutcomeFn = Callable[..., Any]
StreamOutcomeFn = Callable[..., Any]
CanonicalizeFn = Callable[..., Any]
PlanRecoveryFn = Callable[..., Any]
RecordSceneFn = Callable[..., Any]
RecordSuccessFn = Callable[..., Any]
RequestCompressionFn = Callable[..., Any]


@dataclass(frozen=True)
class AgentLlmTurnHooks:
    get_ui: GetUiFn
    llm_cancel_context: CancelContextFn
    raise_if_stop: RaiseIfStopFn
    current_stop_reason: StopReasonFn
    get_llm_for_mode: GetLlmFn
    should_stream: ShouldStreamFn
    build_invocation_context: BuildContextFn
    invoke_outcome: InvokeOutcomeFn
    run_streaming_outcome: StreamOutcomeFn
    canonicalize: CanonicalizeFn
    plan_recovery: PlanRecoveryFn
    record_scene_event: RecordSceneFn
    record_route_success: RecordSuccessFn
    request_compression: RequestCompressionFn
    debug_logger: Any
    error_logger: Any
    config: Any
    force_disable_tools: bool
    stop_error_cls: type
    base_llm: Any = None
    structured_output_contract: Any = None


@dataclass
class AgentLlmAttemptResult:
    payload: Any = None
    last_error_category: Optional[str] = None
    last_error_retryable: bool = False
    last_recovery_action: Optional[str] = None
    last_error_message: str = ""
    last_error_details: Dict[str, Any] = field(default_factory=dict)
    last_failure_attempts: int = 0
    last_failure_max_attempts: int = MAX_CONSECUTIVE_FAILURES
    route_fallback: Dict[str, str] = field(default_factory=dict)
    # Degradation actions dispatched this turn (attempt-level capability
    # reductions from core/llm/recovery.py). In-memory telemetry only; a
    # successful degraded retry still closes the turn as a normal success.
    degraded_actions: list[str] = field(default_factory=list)


def _resolve_explicit_fallback_profile_id(client: Any) -> str:
    """Read the operator-declared fallback profile off the failed route client.

    Empty (the default) means the operator declared nothing for this route, so
    the adapter keeps today's fail-fast behaviour.
    """
    profile = getattr(client, "profile", None)
    target = str(getattr(profile, "fallback", "") or "").strip()
    current = str(getattr(client, "profile_id", "") or "").strip()
    if not target or target == current:
        return ""
    return target


def sanitize_llm_turn_messages(messages: list) -> list:
    """Keep tool/AI identity and structured system cache-control blocks intact."""
    clean_messages = []
    for msg in _coerce_message_list(messages):
        if isinstance(msg, AIMessage):
            clean_messages.append(msg)
        elif isinstance(msg, ToolMessage):
            clean_messages.append(msg)
        elif isinstance(msg, SystemMessage):
            clean_messages.append(SystemMessage(content=_coerce_text(msg.content)))
        elif isinstance(msg, Mapping) and _coerce_text(msg.get("role")).strip().lower() == "system":
            clean_messages.append(dict(msg))
        else:
            clean_messages.append(msg)
    return clean_messages


def _message_digest_entries(messages: list) -> list[Dict[str, Any]]:
    """Summarize outgoing LLM messages as role + SHA-256 prefix + char count.

    Provider implicit caches key on the byte prefix of the request payload.
    Recording a per-message digest (no content) lets future cache-miss
    investigations attribute drift to the exact message that changed without
    dumping payload text into logs.
    """
    entries: list[Dict[str, Any]] = []
    for index, msg in enumerate(_coerce_message_list(messages)):
        if isinstance(msg, Mapping):
            role = _coerce_text(msg.get("role", "type")).strip().lower()
            content = msg.get("content")
        else:
            role = _coerce_text(getattr(msg, "type", "") or getattr(msg, "role", "")).strip().lower()
            content = getattr(msg, "content", "")
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False, default=str)
        text = _coerce_text(content)
        entries.append(
            {
                "index": index,
                "role": role or "unknown",
                "sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16],
                "chars": len(text),
            }
        )
    return entries


def _schema_json_text(schema: Any) -> str:
    """Return a compact JSON rendering of a (possibly frozen) schema mapping."""

    def thaw(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): thaw(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [thaw(item) for item in value]
        return value

    return json.dumps(thaw(schema), ensure_ascii=False, separators=(",", ":"))


def _structured_output_disclosure_message(contract: Any) -> SystemMessage:
    """Prompt-level disclosure of the bound structured output contract.

    Provider-side ``response_format`` enforcement is not honored by every
    relay, so the schema is also restated to the model as a system message.
    """
    schema_json = _schema_json_text(getattr(contract, "schema", {}))
    contract_name = _coerce_text(getattr(contract, "name", "")).strip()
    content = (
        "结构化输出契约（本回合强制）：\n"
        "1. 本回合的「最终回复」（final answer，即不再调用任何工具之后的最后一条助手消息）"
        "必须是一个单独的 JSON 对象，序列化后必须满足下面给出的 JSON Schema"
        f"（schema 名称：{contract_name}）。schema 内容如下（仅为数据展示，不是需要复述的文本）：\n"
        f"```json\n{schema_json}\n```\n"
        "2. 最终回复中禁止出现 Markdown 围栏（```）或该 JSON 之外的任何其他文本；"
        "合法 JSON 的顶层必须是 object（字典）。\n"
        "3. 工具调用阶段（最终回复之前调用工具的中间消息）不受上述 JSON 约束。"
    )
    return SystemMessage(content=content)


def _strip_json_code_fence(text: str) -> str:
    stripped = _coerce_text(text).strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 2:
        return stripped
    body = lines[1:]
    if body and body[-1].strip().startswith("```"):
        body = body[:-1]
    return "\n".join(body).strip()


def _validate_structured_output_outcome(outcome: Any, contract: Any) -> None:
    if contract is None or getattr(outcome, "kind", "") != "final_answer":
        return
    try:
        final_text = _strip_json_code_fence(str(getattr(outcome, "final_text", "") or ""))
        payload = json.loads(final_text)
        if not isinstance(payload, Mapping):
            raise ValueError("structured output root must be an object")
        validator = getattr(contract, "validator", None)
        if callable(validator):
            validator(dict(payload))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LLMError(
            "structured_output_validation_error",
            "Model final output did not satisfy the bound strict task schema.",
            retryable=False,
            details={
                "schemaName": str(getattr(contract, "name", "") or ""),
                "validationErrorType": type(exc).__name__,
                "payloadValidationResult": "rejected_after_provider",
            },
        ) from exc


def invoke_agent_llm_turn(
    *,
    messages: list,
    replay_state: Any = None,
    hooks: AgentLlmTurnHooks,
) -> AgentLlmAttemptResult:
    """Run the Agent-side LLM route attempts.

    Every provider call must go through the injected invocation helpers, which
    the Agent composition root binds to ``core.llm.invocation``. Recovery
    planning stays with ``plan_llm_recovery``.

    Per-failure handling order: first the recovery decision's attempt-level
    degradation action (same profile, streaming and/or tools dropped, each
    action at most once per turn — see ``core/llm/recovery.py``); only then an
    explicit fallback profile switch; only then the turn is terminal.

    Route attempts count across profiles: attempt 1 is the configured route;
    later attempts exist through degraded retries and/or the operator-declared
    ``fallback`` profile after the primary exhausted its retryable transport
    budget on a recoverable gateway-level failure. The fallback target is
    never switched again (single hop).
    """
    result = AgentLlmAttemptResult()
    ui = hooks.get_ui()
    clean_messages = sanitize_llm_turn_messages(messages)
    if hooks.structured_output_contract is not None:
        clean_messages = clean_messages + [
            _structured_output_disclosure_message(hooks.structured_output_contract)
        ]
    # Per-message digests cover every caller of this seam (session turns and
    # meeting rounds alike), so provider-cache drift can be attributed to the
    # exact message that changed. Digest only; no payload text is logged.
    hooks.record_scene_event(
        "llm_route",
        "llm_request_messages_digest",
        message="Outgoing LLM payload per-message SHA-256 digests recorded for cache attribution.",
        fields={"messageDigests": _message_digest_entries(clean_messages)},
        level="debug",
    )

    with ui.thinking("?? 思考中..."), hooks.llm_cancel_context(hooks.current_stop_reason):
        route_attempt = 1
        pending_fallback_profile_id = ""
        switched_fallback: Dict[str, str] = {}
        invocation_context = None
        trace_fields: Dict[str, Any] = {}
        llm_for_turn = None
        degraded_actions_used: set[str] = set()
        # One-shot capability overrides for the next attempt only; consumed at
        # the top of each iteration so a later failure (e.g. after a fallback
        # switch) is judged on its own merits.
        pending_disable_streaming = False
        pending_disable_tools = False
        while True:
            # Consume the pending one-shot degradation overrides: they apply to
            # exactly this attempt, then expire.
            attempt_disable_streaming = pending_disable_streaming
            attempt_disable_tools = pending_disable_tools
            pending_disable_streaming = False
            pending_disable_tools = False
            try:
                hooks.raise_if_stop()
                llm_for_turn = hooks.get_llm_for_mode(
                    disable_tools=(
                        _coerce_bool(hooks.force_disable_tools, False) or attempt_disable_tools
                    ),
                    profile_id=pending_fallback_profile_id or None,
                )
                route_id = _llm_effective_route_id(llm_for_turn)
                invocation_context = hooks.build_invocation_context(
                    prompt_purpose="main_reply",
                    route_attempt=route_attempt,
                )
                capture_turn_request(llm_for_turn, clean_messages, invocation_context)
                route_started_at = time.monotonic()
                trace_fields = _llm_route_trace_fields(
                    invocation_context,
                    llm_for_turn,
                    route_attempt=route_attempt,
                    route_id=route_id,
                )
                hooks.record_scene_event(
                    "llm_route",
                    "llm_route_attempt_started",
                    message="LLM effective route attempt started.",
                    fields=trace_fields,
                )
                # A degraded attempt is pinned to the non-streaming path even
                # if the operator's streaming preference would allow it.
                if (
                    not attempt_disable_streaming
                    and hooks.should_stream(llm_for_turn)
                    and hasattr(llm_for_turn, "stream")
                ):
                    def on_protocol_event(event: Any) -> None:
                        hooks.raise_if_stop()
                        if event.kind == "reasoning_delta" and event.text:
                            ui.stream_thought(event.text, done=False)
                        elif event.kind in {"commentary_delta", "answer_delta"} and event.text:
                            stream_response = getattr(ui, "stream_response", None)
                            if callable(stream_response):
                                stream_response(event.text, done=False)

                    stream_kwargs = {
                        "context": invocation_context,
                        "on_event": on_protocol_event,
                        "replay_state": replay_state,
                    }
                    if hooks.structured_output_contract is not None:
                        stream_kwargs["output_schema"] = hooks.structured_output_contract
                    generation_started_at = time.monotonic()
                    outcome = hooks.run_streaming_outcome(
                        llm_for_turn,
                        clean_messages,
                        **stream_kwargs,
                    )
                    generation_elapsed_ms = int((time.monotonic() - generation_started_at) * 1000)
                    outcome = hooks.canonicalize(outcome)
                    record_turn_request_outcome(outcome)
                    _validate_structured_output_outcome(
                        outcome,
                        hooks.structured_output_contract,
                    )
                    if outcome.kind in {"tool_calls", "final_answer"}:
                        hooks.record_route_success(
                            trace_fields=trace_fields,
                            duration_ms=int((time.monotonic() - route_started_at) * 1000),
                            streamed=True,
                        )
                    result.payload = (outcome, llm_for_turn.project_outcome_message(outcome, latency_ms=generation_elapsed_ms))
                    result.route_fallback = dict(switched_fallback)
                    return result
                hooks.raise_if_stop()
                invoke_kwargs = {
                    "context": invocation_context,
                    "replay_state": replay_state,
                }
                if hooks.structured_output_contract is not None:
                    invoke_kwargs["output_schema"] = hooks.structured_output_contract
                generation_started_at = time.monotonic()
                outcome = hooks.invoke_outcome(
                    llm_for_turn,
                    clean_messages,
                    **invoke_kwargs,
                )
                generation_elapsed_ms = int((time.monotonic() - generation_started_at) * 1000)
                outcome = hooks.canonicalize(outcome)
                record_turn_request_outcome(outcome)
                _validate_structured_output_outcome(
                    outcome,
                    hooks.structured_output_contract,
                )
                if outcome.kind in {"tool_calls", "final_answer"}:
                    hooks.record_route_success(
                        trace_fields=trace_fields,
                        duration_ms=int((time.monotonic() - route_started_at) * 1000),
                        streamed=False,
                    )
                result.payload = (outcome, llm_for_turn.project_outcome_message(outcome, latency_ms=generation_elapsed_ms))
                result.route_fallback = dict(switched_fallback)
                return result
            except hooks.stop_error_cls:
                raise
            except KeyboardInterrupt:
                raise
            except Exception as e:
                llm_error_details = _llm_error_details(e)
                safe_projection_details = _safe_llm_error_diagnostic_details(llm_error_details)
                reported_attempt = _coerce_positive_int(
                    _mapping_get(llm_error_details, "attempt", "attemptIndex"),
                    default=1,
                )
                reported_max_attempts = _coerce_positive_int(
                    _mapping_get(llm_error_details, "max_attempts", "maxAttempts"),
                    default=reported_attempt,
                )
                recovery = hooks.plan_recovery(
                    e,
                    attempt=reported_attempt,
                    max_attempts=reported_max_attempts,
                )
                category = _coerce_text(recovery.category).strip()
                is_retryable = _coerce_bool(recovery.retryable, False)
                user_msg = _coerce_text(recovery.user_message)
                stop_reason = (
                    hooks.current_stop_reason()
                    or _coerce_text(
                        _mapping_get(llm_error_details, "stop_reason", "stopReason")
                    ).strip()
                )
                if category == "cancelled" and stop_reason:
                    hooks.record_scene_event(
                        "llm_route",
                        "llm_route_cancelled",
                        message="LLM route cancelled by the active turn stop request.",
                        fields={
                            **trace_fields,
                            "routeAttempt": route_attempt,
                            "routeId": _llm_effective_route_id(llm_for_turn),
                            "reasonCode": "turn_stop_requested",
                        },
                        level="info",
                        outcome="cancelled",
                    )
                    raise hooks.stop_error_cls(stop_reason)
                try:
                    streaming_enabled_for_failed_attempt = bool(
                        (not attempt_disable_streaming)
                        and hooks.should_stream(llm_for_turn)
                        and hasattr(llm_for_turn, "stream")
                    )
                except Exception:
                    streaming_enabled_for_failed_attempt = False
                provider_stream_retry_exhausted = _coerce_bool(
                    _mapping_get(
                        llm_error_details, "retry_budget_exhausted", "retryBudgetExhausted"
                    ),
                    False,
                ) or (
                    reported_attempt > 0 and reported_attempt >= reported_max_attempts
                )
                result.last_error_category = category
                result.last_error_retryable = is_retryable
                result.last_recovery_action = recovery.action
                result.last_error_message = f"{category}: {user_msg}".strip(": ")
                result.last_failure_attempts = reported_attempt
                result.last_failure_max_attempts = reported_max_attempts
                exception_type = type(e).__name__
                exception_message = str(e)
                llm_error_traceback = traceback.format_exc()
                error_details = {
                    **safe_projection_details,
                    "exception_type": exception_type,
                    "exception_message": exception_message[:4000],
                    "retryable": is_retryable,
                    "recovery_action": recovery.action,
                    "stop_current_turn": _coerce_bool(recovery.stop_current_turn, False),
                    "request_context_compression": _coerce_bool(
                        recovery.request_context_compression, False
                    ),
                    "provider_stream_retry_exhausted": provider_stream_retry_exhausted,
                    "attempt": reported_attempt,
                    "max_attempts": reported_max_attempts,
                    "route_attempt": route_attempt,
                    "route_id": _llm_effective_route_id(llm_for_turn),
                    "invocation_id": _coerce_text(
                        _mapping_get(
                            _invocation_metadata(invocation_context),
                            "invocationId",
                            "invocation_id",
                        )
                    ),
                    "model": getattr(getattr(hooks.config, "llm", None), "model_name", ""),
                    "provider": getattr(getattr(hooks.config, "llm", None), "provider", ""),
                    "api_base": getattr(getattr(hooks.config, "llm", None), "api_base", ""),
                    "api_timeout": getattr(getattr(hooks.config, "llm", None), "api_timeout", None),
                    "streaming_enabled": streaming_enabled_for_failed_attempt,
                    "message_count": len(clean_messages),
                }
                if attempt_disable_streaming or attempt_disable_tools:
                    error_details["degraded_retry"] = {
                        "disable_streaming": attempt_disable_streaming,
                        "disable_tools": attempt_disable_tools,
                    }
                if switched_fallback:
                    error_details["route_fallback"] = dict(switched_fallback)
                try:
                    from tools.token_manager import estimate_messages_tokens

                    error_details["estimated_input_tokens"] = max(
                        0, int(estimate_messages_tokens(clean_messages) or 0)
                    )
                except Exception:
                    error_details["estimated_input_tokens"] = 0
                result.last_error_details = dict(error_details)

                hooks.debug_logger.error(
                    f"LLM 路由调用失败 [{route_attempt}] "
                    f"{category}: {user_msg} | action={recovery.action} | "
                    f"{exception_type}: {exception_message[:300]}",
                    tag="LLM",
                )
                hooks.error_logger.log_error(
                    "llm_error",
                    f"{category}: {user_msg}",
                    traceback=llm_error_traceback,
                    details=error_details,
                )
                failed_route = llm_for_turn
                failed_route_id = _llm_effective_route_id(failed_route)
                failed_profile_id = _coerce_text(getattr(failed_route, "profile_id", "")).strip()
                failed_invocation_id = _coerce_text(
                    _mapping_get(
                        _invocation_metadata(invocation_context),
                        "invocationId",
                        "invocation_id",
                    )
                )
                hooks.record_scene_event(
                    "llm_route",
                    "llm_route_attempt_exhausted",
                    message="LLM effective route attempt exhausted.",
                    fields={
                        **trace_fields,
                        "routeAttempt": route_attempt,
                        "routeId": failed_route_id,
                        "invocationId": failed_invocation_id,
                        "profileId": failed_profile_id,
                        "transportAttempt": reported_attempt,
                        "maxTransportAttempts": reported_max_attempts,
                        "errorCategory": category,
                        "retryable": is_retryable,
                        **safe_projection_details,
                    },
                    level="warning" if is_retryable else "error",
                    outcome="failed",
                )

                if _coerce_bool(recovery.request_context_compression, False):
                    hooks.record_scene_event(
                        "llm_route",
                        "llm_turn_terminal",
                        message="LLM turn stopped for context compression.",
                        fields={
                            **trace_fields,
                            "routeAttempts": route_attempt,
                            "routeId": failed_route_id,
                            "errorCategory": category,
                            "reasonCode": "context_compression_required",
                        },
                        level="warning",
                        outcome="failed",
                    )
                    hooks.request_compression(
                        f"LLM provider reported context limit: {category}",
                        source="provider_limit",
                    )
                    return result

                # Attempt-level capability degradation, driven by the action
                # vocabulary in core/llm/recovery.py (single source of truth —
                # no category mapping is re-declared here). Ordered BEFORE the
                # explicit fallback switch: a same-profile degraded retry keeps
                # the provider prompt-cache prefix and the tool/AI message
                # context that a profile switch would discard, and the degrade
                # categories (empty_content_error / tool_protocol_error /
                # protocol_error) are disjoint from the gateway-level
                # _FALLBACK_SWITCH_CATEGORIES, so this ordering never competes
                # within a single failure — a degraded retry that later fails
                # on a transport category still reaches the fallback branch
                # below in its own iteration. Each action fires at most once
                # per turn (no degradation loops), and the skipped case where
                # the degraded shape would equal the failed shape (already
                # non-streaming and already tool-less) falls through instead
                # of burning a no-op request.
                degraded_action = _coerce_text(recovery.action).strip()
                if (
                    degraded_action in DEGRADED_RETRY_ACTIONS
                    and degraded_action not in degraded_actions_used
                ):
                    degrade_streaming, degrade_tools = degraded_retry_overrides(degraded_action)
                    force_tools_off = _coerce_bool(hooks.force_disable_tools, False)
                    streaming_would_change = degrade_streaming and streaming_enabled_for_failed_attempt
                    tools_would_change = degrade_tools and not (
                        force_tools_off or attempt_disable_tools
                    )
                    if streaming_would_change or tools_would_change:
                        degraded_actions_used.add(degraded_action)
                        result.degraded_actions.append(degraded_action)
                        pending_disable_streaming = degrade_streaming
                        pending_disable_tools = degrade_tools
                        hooks.record_scene_event(
                            "llm_route",
                            "llm_route_degraded_retry",
                            message=(
                                "LLM route failed with a degradation-eligible "
                                f"category; retrying once on the same profile "
                                f"with action `{degraded_action}`."
                            ),
                            fields={
                                **trace_fields,
                                "routeAttempt": route_attempt,
                                "attempt": route_attempt + 1,
                                "routeId": failed_route_id,
                                "profileId": failed_profile_id,
                                "action": degraded_action,
                                "fromCategory": category,
                                "errorCategory": category,
                                "retryable": is_retryable,
                                "streamingDisabled": degrade_streaming,
                                "toolsDisabled": degrade_tools,
                            },
                            level="warning",
                            outcome="degraded",
                        )
                        route_attempt += 1
                        continue

                # Explicit fallback switch: only on the primary route (single
                # hop), only for recoverable gateway-level categories, and only
                # once the route's own transport retry budget is exhausted.
                fallback_profile_id = (
                    "" if pending_fallback_profile_id else _resolve_explicit_fallback_profile_id(failed_route)
                )
                if (
                    fallback_profile_id
                    and is_retryable
                    and provider_stream_retry_exhausted
                    and category in _FALLBACK_SWITCH_CATEGORIES
                ):
                    invocation_metadata = _invocation_metadata(invocation_context)
                    hooks.record_scene_event(
                        "llm_route",
                        "llm_route_fallback_switched",
                        message=(
                            "Primary LLM route exhausted its retry budget on a "
                            "recoverable failure; switching once to the declared "
                            f"fallback profile `{fallback_profile_id}`."
                        ),
                        fields={
                            **trace_fields,
                            "routeAttempt": route_attempt,
                            "routeId": failed_route_id,
                            "from": failed_profile_id,
                            "to": fallback_profile_id,
                            "fromRouteId": failed_route_id,
                            "reason": category,
                            "attempt": route_attempt,
                            "transportAttempt": reported_attempt,
                            "maxTransportAttempts": reported_max_attempts,
                            "errorCategory": category,
                            "retryable": is_retryable,
                        },
                        level="warning",
                        outcome="switched",
                    )
                    fallback_session_id = _coerce_text(
                        _mapping_get(invocation_metadata, "sessionId", "session_id")
                    )
                    fallback_turn_id = _coerce_text(
                        _mapping_get(invocation_metadata, "turnId", "turn_id")
                    )
                    if fallback_session_id:
                        record_route_fallback(
                            fallback_session_id,
                            fallback_turn_id,
                            from_profile_id=failed_profile_id,
                            to_profile_id=fallback_profile_id,
                            reason=category,
                        )
                    switched_fallback = {"from": failed_profile_id, "to": fallback_profile_id}
                    result.route_fallback = dict(switched_fallback)
                    pending_fallback_profile_id = fallback_profile_id
                    route_attempt += 1
                    continue

                terminal_fields = {
                    **trace_fields,
                    "routeAttempts": route_attempt,
                    "routeId": failed_route_id,
                    "errorCategory": category,
                    "reasonCode": "route_failed",
                }
                if switched_fallback:
                    terminal_fields["routeFallback"] = dict(switched_fallback)
                hooks.record_scene_event(
                    "llm_route",
                    "llm_turn_terminal",
                    message="LLM turn exhausted all permitted routes.",
                    fields={**terminal_fields, **safe_projection_details},
                    level="error",
                    outcome="failed",
                )
                return result
