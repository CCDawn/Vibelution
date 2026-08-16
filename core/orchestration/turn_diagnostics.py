# -*- coding: utf-8 -*-
"""Turn diagnostics, cache telemetry, stall signal tracking, and LLM retry publication for Agent."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any, Dict, List, Optional
from uuid import uuid4

from core.ui.cli_ui import get_ui
from core.llm.client import current_llm_status_context
from core.llm.invocation import LLMInvocationContext
from core.logging.logger import debug as _debug_logger
from core.orchestration.agent_runtime_bindings import (
    _as_mapping,
    _coerce_text,
    _mapping_get,
    _reset_stall_signal_reported,
    _safe_turn_runtime_metadata,
    _stall_signal_threshold_events,
    _turn_runtime_from_env,
)
from core.orchestration.cache_diagnostics import (
    build_llm_usage_from_observation,
    build_runtime_cache_composition,
    build_runtime_context_composition,
)


def _coerce_nonnegative_int(value: Any, *, default: int = 0) -> int:
    if isinstance(value, bool) or value is None:
        return max(0, int(default or 0))
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return max(0, int(default or 0))


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


def _coerce_message_list(value: Any) -> list:
    value = _maybe_json(value)
    if value is None or isinstance(value, (str, bytes, bytearray, memoryview)):
        return []
    if isinstance(value, Mapping):
        return [dict(value)]
    try:
        return list(value)
    except TypeError:
        return []


def _response_metadata(response: Any) -> Dict[str, Any]:
    if isinstance(response, Mapping):
        return _as_mapping(response.get("response_metadata") or response.get("responseMetadata"))
    return _as_mapping(getattr(response, "response_metadata", None))


def publish_llm_retry_status(
    *,
    attempt: int,
    max_attempts: int,
    category: str = "",
    action: str = "",
    event_bus_getter: Any = None,
) -> None:
    """Surface outer Agent reconnect attempts for live session feedback."""
    cat = _coerce_text(category).strip()
    act = _coerce_text(action).strip()
    if not cat and not act:
        return
    try:
        from core.infrastructure.event_bus import EventNames, get_event_bus

        bus_getter = event_bus_getter or get_event_bus
        bus = bus_getter()
        bus.publish(
            EventNames.LLM_STATUS,
            {
                "status": "retrying",
                "attempt": _coerce_nonnegative_int(attempt),
                "max_attempts": _coerce_nonnegative_int(max_attempts),
                "category": cat,
                "recovery_action": act,
                "source": "agent_outer_reconnect",
            },
            source="SelfEvolvingAgent",
        )
    except Exception:
        return


def record_turn_cache_diagnostics(
    *,
    token_usage: Any,
    response: Any,
    messages: List[Any],
    current_turn: int,
    context_window_limit: int = 0,
    get_ui_fn: Any = None,
    turn_runtime_fn: Any = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Record turn cache diagnostics and return (llm_usage, metadata_update)."""
    response_metadata = _response_metadata(response)
    runtime = _as_mapping((turn_runtime_fn or _turn_runtime_from_env)())
    partition = _coerce_text(
        _mapping_get(runtime, "promptCachePartition", "prompt_cache_partition")
    ).strip()
    runtime_metadata = {
        **_safe_turn_runtime_metadata(runtime),
        **({"promptCachePartition": partition} if partition else {}),
    }
    llm_usage = build_llm_usage_from_observation(
        token_usage,
        response_metadata=response_metadata,
        runtime_metadata=runtime_metadata,
    )
    prompt_cache_partition = _coerce_text(llm_usage.get("promptCachePartition")).strip()
    context_limit = _coerce_nonnegative_int(context_window_limit)
    turn_id = _coerce_text(current_turn).strip()
    context_composition = build_runtime_context_composition(
        _coerce_message_list(messages),
        turn_id=turn_id,
        prompt_cache_partition=prompt_cache_partition,
        context_limit=context_limit,
    )
    ui_getter = get_ui_fn or get_ui
    ui = ui_getter()
    average_cache = {}
    snapshot = getattr(ui, "cache_average_snapshot", None)
    if callable(snapshot):
        try:
            average_cache = snapshot()
        except Exception:
            average_cache = {}
    cache_composition = build_runtime_cache_composition(
        turn_id=turn_id,
        llm_usage=llm_usage,
        context_composition=context_composition,
        average_cache=average_cache,
    )
    metadata_update = {
        "llm_usage": llm_usage,
        "context_composition": context_composition,
        "cache_composition": cache_composition,
    }
    note_cache_diagnostics = getattr(ui, "note_cache_diagnostics", None)
    if callable(note_cache_diagnostics):
        try:
            note_cache_diagnostics(
                llm_usage=llm_usage,
                context_composition=context_composition,
                cache_composition=cache_composition,
            )
        except Exception as exc:
            _debug_logger.warning(
                f"[TOKEN] runtime cache diagnostics persist failed: {type(exc).__name__}: {exc}",
                tag="TOKEN",
            )
    return llm_usage, metadata_update


def build_llm_invocation_context(
    *,
    runtime_binding: Optional[Dict[str, Any]] = None,
    mode_value: str = "",
    orchestrator_kind: str = "",
    pending_supervised_case_id: str = "",
    tool_authorization_fingerprint: str = "",
    ledger_conversation_fingerprint: str = "",
    prompt_purpose: str = "main_reply",
    route_attempt: int = 1,
    turn_runtime_fn: Any = None,
    status_context_fn: Any = None,
) -> LLMInvocationContext:
    runtime = _as_mapping((turn_runtime_fn or _turn_runtime_from_env)())
    status_getter = status_context_fn or current_llm_status_context
    status_context = _as_mapping(status_getter())
    binding = _as_mapping(runtime_binding)
    mode_str = _coerce_text(mode_value).strip()
    orch_kind = _coerce_text(orchestrator_kind).strip()
    surface = "chat_turn" if orch_kind == "chat" or mode_str == "chat" else "agent_turn"
    run_kind = (
        _coerce_text(_mapping_get(runtime, "runKind", "run_kind")).strip()
        or ("chat_turn" if surface == "chat_turn" else mode_str or "agent_turn")
    )
    return LLMInvocationContext(
        surface=surface,
        run_kind=run_kind,
        run_id=_coerce_text(
            _mapping_get(runtime, "runId", "run_id") or pending_supervised_case_id
        ).strip(),
        session_id=_coerce_text(
            _mapping_get(runtime, "sessionId", "session_id")
            or _mapping_get(status_context, "session_id", "sessionId")
            or _mapping_get(binding, "directSessionId", "direct_session_id")
        ).strip(),
        agent_id=_coerce_text(
            _mapping_get(runtime, "agentId", "agent_id") or _mapping_get(binding, "agentId", "agent_id")
        ).strip(),
        llm_slot=_coerce_text(
            _mapping_get(runtime, "llmSlot", "llm_slot")
            or _mapping_get(binding, "llmSlot", "llm_slot")
            or "dialogue"
        ).strip()
        or "dialogue",
        model_id=_coerce_text(
            _mapping_get(runtime, "modelId", "model_id") or os.environ.get("VIBELUTION_AGENT_LLM_MODEL_ID")
        ).strip(),
        cache_scope=_coerce_text(_mapping_get(runtime, "cacheScope", "cache_scope")).strip(),
        cache_partition=_coerce_text(
            _mapping_get(runtime, "promptCachePartition", "prompt_cache_partition")
        ).strip(),
        prompt_purpose=_coerce_text(prompt_purpose).strip() or "main_reply",
        conversation_bound=surface == "chat_turn",
        metadata={
            "agentMode": mode_str,
            "orchestratorKind": orch_kind,
            "invocationId": uuid4().hex,
            "routeAttempt": max(1, _coerce_nonnegative_int(route_attempt, default=1)),
            "toolAuthorizationDecisionFingerprint": _coerce_text(tool_authorization_fingerprint).strip(),
            "ledgerConversationFingerprint": _coerce_text(ledger_conversation_fingerprint).strip(),
            "turnId": _coerce_text(
                _mapping_get(status_context, "turn_id", "turnId")
                or _mapping_get(runtime, "runId", "run_id")
            ).strip(),
        },
    )


def report_round_state_stall_signals(
    round_state: Any,
    reported_signals: Dict[str, bool],
    *,
    debug_logger: Any = None,
) -> Dict[str, bool]:
    """Check round-state stall signals and return the updated reported set.

    Reads `RoundStateController.runtime_telemetry()`. A legacy
    `telemetry_snapshot` attribute is ignored so stall events cannot fire
    against the wrong shape and go silent.
    """
    reported = _as_mapping(reported_signals)
    if round_state is None:
        return reported
    telemetry_fn = getattr(round_state, "runtime_telemetry", None)
    if not callable(telemetry_fn):
        return reported
    telemetry = _as_mapping(telemetry_fn())
    events = _stall_signal_threshold_events(telemetry, reported)
    if events:
        details = ", ".join(
            f"{key}={_coerce_nonnegative_int(telemetry.get(key))}" for key in sorted(events)
        )
        logger = debug_logger if debug_logger is not None else _debug_logger
        logger.warning(f"[循环卡住信号] {details}", tag="STATE")
        reported.update({key: True for key in events})
    return _reset_stall_signal_reported(telemetry, reported)
