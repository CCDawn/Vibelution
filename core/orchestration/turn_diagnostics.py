# -*- coding: utf-8 -*-
"""Turn diagnostics, cache telemetry, stall signal tracking, and LLM retry publication for Agent."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from uuid import uuid4

from core.ui.cli_ui import get_ui
from core.llm.client import current_llm_status_context
from core.llm.invocation import LLMInvocationContext
from core.logging.logger import debug as _debug_logger
from core.orchestration.agent_runtime_bindings import (
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


def publish_llm_retry_status(
    *,
    attempt: int,
    max_attempts: int,
    category: str = "",
    action: str = "",
    event_bus_getter: Any = None,
) -> None:
    """Surface outer Agent reconnect attempts for live session feedback."""
    cat = str(category or "").strip()
    act = str(action or "").strip()
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
                "attempt": max(0, int(attempt or 0)),
                "max_attempts": max(0, int(max_attempts or 0)),
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
    response_metadata = getattr(response, "response_metadata", None)
    if not isinstance(response_metadata, dict):
        response_metadata = {}
    runtime = (turn_runtime_fn or _turn_runtime_from_env)()
    runtime_metadata = {
        **_safe_turn_runtime_metadata(runtime),
        **({
            "promptCachePartition": str(runtime.get("promptCachePartition") or "").strip(),
        } if str(runtime.get("promptCachePartition") or "").strip() else {}),
    }
    llm_usage = build_llm_usage_from_observation(
        token_usage,
        response_metadata=response_metadata,
        runtime_metadata=runtime_metadata,
    )
    prompt_cache_partition = str(llm_usage.get("promptCachePartition") or "").strip()
    context_limit = int(context_window_limit or 0)
    context_composition = build_runtime_context_composition(
        list(messages or []),
        turn_id=str(current_turn or ""),
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
        turn_id=str(current_turn or ""),
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
    prompt_purpose: str = "main_reply",
    route_attempt: int = 1,
    turn_runtime_fn: Any = None,
    status_context_fn: Any = None,
) -> LLMInvocationContext:
    runtime = (turn_runtime_fn or _turn_runtime_from_env)()
    status_getter = status_context_fn or current_llm_status_context
    status_context = status_getter() or {}
    binding = dict(runtime_binding or {})
    mode_str = str(mode_value or "").strip()
    orch_kind = str(orchestrator_kind or "").strip()
    surface = "chat_turn" if orch_kind == "chat" or mode_str == "chat" else "agent_turn"
    run_kind = (
        str(runtime.get("runKind") or "").strip()
        or ("chat_turn" if surface == "chat_turn" else mode_str or "agent_turn")
    )
    return LLMInvocationContext(
        surface=surface,
        run_kind=run_kind,
        run_id=str(runtime.get("runId") or pending_supervised_case_id or "").strip(),
        session_id=str(
            runtime.get("sessionId")
            or status_context.get("session_id")
            or status_context.get("sessionId")
            or binding.get("directSessionId")
            or ""
        ).strip(),
        agent_id=str(runtime.get("agentId") or binding.get("agentId") or "").strip(),
        llm_slot=str(runtime.get("llmSlot") or binding.get("llmSlot") or "dialogue").strip() or "dialogue",
        model_id=str(runtime.get("modelId") or os.environ.get("VIBELUTION_AGENT_LLM_MODEL_ID") or "").strip(),
        cache_scope=str(runtime.get("cacheScope") or "").strip(),
        cache_partition=str(runtime.get("promptCachePartition") or "").strip(),
        prompt_purpose=prompt_purpose,
        conversation_bound=surface == "chat_turn",
        metadata={
            "agentMode": mode_str,
            "orchestratorKind": orch_kind,
            "invocationId": uuid4().hex,
            "routeAttempt": max(1, int(route_attempt)),
            "toolAuthorizationDecisionFingerprint": str(tool_authorization_fingerprint or "").strip(),
            "turnId": str(
                status_context.get("turn_id")
                or status_context.get("turnId")
                or runtime.get("runId")
                or ""
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
    reported = dict(reported_signals or {})
    if round_state is None:
        return reported
    telemetry_fn = getattr(round_state, "runtime_telemetry", None)
    if not callable(telemetry_fn):
        return reported
    telemetry = dict(telemetry_fn() or {})
    events = _stall_signal_threshold_events(telemetry, reported)
    if events:
        details = ", ".join(
            f"{key}={int(telemetry.get(key) or 0)}" for key in sorted(events)
        )
        logger = debug_logger if debug_logger is not None else _debug_logger
        logger.warning(f"[循环卡住信号] {details}", tag="STATE")
        reported.update({key: True for key in events})
    return _reset_stall_signal_reported(telemetry, reported)
