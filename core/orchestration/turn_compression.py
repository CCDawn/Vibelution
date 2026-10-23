# -*- coding: utf-8 -*-
"""Turn message context compression orchestrator for long-running Agent turns."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, ToolMessage

from core.infrastructure.feature_gate import resolve_feature_decision
from core.infrastructure.runtime_input import build_runtime_notice_message
from core.infrastructure.state import AgentState, get_state_manager
from core.orchestration import llm_summary_breaker
from core.orchestration.agent_modes import AgentMode
from core.orchestration.agent_runtime_bindings import (
    _as_mapping,
    _coerce_text,
    _context_compression_trigger_source,
    _format_tool_result_replacement_summary,
    _mapping_get,
    _record_agent_scene_event,
    _turn_runtime_from_env,
)
from core.ui.cli_ui import get_ui
from tools.compression_strategy import CompressionLevel, get_compression_strategy
from tools.token_manager import estimate_messages_tokens


# Zero-diagnosis guard: an unconfigured (<= 0) context input hard limit used to
# silently disable the budget gate -- evaluate_context_budget_preflight kept
# guardReason empty and agent.context_budget_exhausted never fired. The guard
# is still non-blocking in that case (there is no limit to fail closed on),
# but it is now explicit in results and diagnostics.
BUDGET_LIMIT_UNCONFIGURED_GUARD_REASON = "budget_limit_unconfigured"

# Non-chat emergency compression is NOT budget fail-closed. The caller used
# to receive it through the same ``should_break`` channel as the retention/hard-limit
# fail-closed contract, which mislabeled them as
# ``context_budget_exhausted``. It gets a dedicated ``stop_reason`` string so
# the caller can report the real cause. ``should_break`` stays
# reserved for the fail-closed contract documented on
# ``compress_turn_messages``.
STOP_REASON_CONTEXT_BUDGET_EXHAUSTED = "context_budget_exhausted"
# Kept for caller diagnostics compatibility; compression no longer emits it.
STOP_REASON_ITERATION_LIMIT = "iteration_limit_reached"
STOP_REASON_EMERGENCY_COMPRESSION = "emergency_compression"


def _cooperative_yield() -> None:
    """GIL courtesy between serial estimator sweeps (compressionGateMs).

    The budget-window gate re-estimates one full candidate per history group;
    on a ~186k-token history that keeps one core busy for seconds without a
    yield and starves the interactive turn's small CPU segments (same
    precedent as the hypothesis_first_chain sweep wall-clock budget).
    ``sleep(0)`` returns immediately when no other thread is ready, so the
    scheduling-only cost is negligible: every estimate and its order are
    unchanged.
    """

    time.sleep(0)


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
        nested = value.get("messages")
        if nested is None:
            nested = value.get("items")
        if nested is None:
            nested = value.get("history")
        if nested is not None:
            return _coerce_message_list(nested)
        if any(key in value for key in ("role", "content", "type", "kind")):
            return [dict(value)]
        return []
    try:
        return list(value)
    except TypeError:
        return []


def build_token_budget_window(
    messages: Any,
    *,
    hard_limit: int,
    estimator: Any,
    keep_history: bool = True,
) -> Tuple[List[Any], int, bool]:
    """Keep required context and the newest complete history groups that fit.

    System/runtime messages include the summary and policy prefix; the newest
    user message is the current request. Neither may be retired to make room.
    Tool calls and their results are selected together, in original order.
    The caller may meter a subsequent notice through ``estimator`` as well.
    """

    items = _coerce_message_list(messages)
    budget = _coerce_nonnegative_int(hard_limit)
    if not items or budget <= 0:
        return [], 0, False
    required = {
        index for index, message in enumerate(items)
        if _pairing_role(message) in {"system", "developer", "runtime", "runtime_context"}
    }
    latest_user = next(
        (index for index in range(len(items) - 1, -1, -1)
         if _pairing_role(items[index]) in {"user", "human"}),
        None,
    )
    if latest_user is not None:
        required.add(latest_user)
    groups: list[list[int]] = []
    call_groups: dict[str, list[int]] = {}
    for index, message in enumerate(items):
        if index in required:
            continue
        role = _pairing_role(message)
        result_id = _pairing_tool_result_id(message)
        if role == "tool":
            group = call_groups.get(result_id)
            if group is not None:
                group.append(index)
            # An orphan result must never survive on its own.
            continue
        group = [index]
        groups.append(group)
        for call_id in _pairing_tool_call_ids(message):
            call_groups[call_id] = group
    kept_indices = set(required)
    kept = [message for index, message in enumerate(items) if index in kept_indices]
    if _coerce_nonnegative_int(estimator(kept)) > budget:
        return [], 0, False
    if not keep_history:
        return kept, _coerce_nonnegative_int(estimator(kept)), bool(kept)
    for group in reversed(groups):
        # One full estimator sweep per group: hand the GIL back between
        # groups so a long compression preflight cannot monopolize a core.
        _cooperative_yield()
        candidate_indices = kept_indices.union(group)
        candidate = [message for index, message in enumerate(items) if index in candidate_indices]
        if _coerce_nonnegative_int(estimator(candidate)) > budget:
            break
        kept_indices = candidate_indices
        kept = candidate
    if not kept:
        return [], 0, False
    return kept, _coerce_nonnegative_int(estimator(kept)), True


def build_context_compression_notice(before_tokens: int, after_tokens: int) -> Any:
    """One notice shared by the compressor's budget and the eventual send."""
    return build_runtime_notice_message(
        f"由于上下文超过最大承受能力，现在强制进行了一次压缩"
        f"（{before_tokens} → {after_tokens} tokens）。"
    )


# --- Context retention contract (versioned compression policy v3) -----------


def _pairing_role(message: Any) -> str:
    role = str(getattr(message, "type", "") or "").strip().lower()
    if not role and isinstance(message, Mapping):
        role = str(message.get("role") or "").strip().lower()
    if not role:
        role = type(message).__name__.strip().lower()
    return role


def _pairing_tool_call_ids(message: Any) -> list[str]:
    raw = getattr(message, "tool_calls", None)
    if raw is None and isinstance(message, Mapping):
        raw = message.get("tool_calls")
    ids: list[str] = []
    for item in list(raw or []):
        if isinstance(item, Mapping):
            call_id = str(item.get("id") or "").strip()
        else:
            call_id = str(getattr(item, "id", "") or "").strip()
        if call_id:
            ids.append(call_id)
    return ids


def _pairing_tool_result_id(message: Any) -> str:
    call_id = getattr(message, "tool_call_id", None)
    if call_id is None and isinstance(message, Mapping):
        call_id = message.get("tool_call_id")
    return str(call_id or "").strip()


def _tool_call_pairing_snapshot(messages: Any) -> Dict[str, Any]:
    """Snapshot assistant tool-call / tool-result pairing for retention checks.

    Compression may retire old pairs wholesale (they enter the summary), but it
    must never create a new unresolved call or a new orphan tool result — that
    would fail the strict provider payload validator at send time.
    """

    pending: list[str] = []
    orphan_results = 0
    assistant_tool_calls = 0
    tool_results = 0
    for message in list(messages or []):
        role = _pairing_role(message)
        if role in {"ai", "assistant"}:
            call_ids = _pairing_tool_call_ids(message)
            assistant_tool_calls += len(call_ids)
            pending.extend(call_ids)
            continue
        result_id = _pairing_tool_result_id(message)
        if role == "tool" or (result_id and role not in {"system", "user", "human"}):
            tool_results += 1
            if result_id and result_id in pending:
                pending.remove(result_id)
            elif result_id:
                orphan_results += 1
    return {
        "unresolvedCallIds": list(pending),
        "unresolvedCallCount": len(pending),
        "orphanResultCount": orphan_results,
        "assistantToolCallCount": assistant_tool_calls,
        "toolResultCount": tool_results,
    }


def _retention_violation_reason(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    before_unresolved = set(before.get("unresolvedCallIds") or [])
    after_unresolved = set(after.get("unresolvedCallIds") or [])
    if after_unresolved - before_unresolved:
        return "retention_missing"
    if int(after.get("orphanResultCount") or 0) > int(before.get("orphanResultCount") or 0):
        return "retention_missing"
    return ""


ABORTED_TOOL_RESULT_CONTENT = "aborted"


def _pairing_tool_call_names(message: Any) -> Dict[str, str]:
    raw = getattr(message, "tool_calls", None)
    if raw is None and isinstance(message, Mapping):
        raw = message.get("tool_calls")
    names: Dict[str, str] = {}
    for item in list(raw or []):
        if isinstance(item, Mapping):
            call_id = str(item.get("id") or "").strip()
            function = item.get("function")
            function_name = function.get("name") if isinstance(function, Mapping) else None
            name = str(item.get("name") or function_name or "").strip()
        else:
            call_id = str(getattr(item, "id", "") or "").strip()
            name = str(getattr(item, "name", "") or "").strip()
        if call_id:
            names[call_id] = name
    return names


def _aborted_tool_result_message(call_id: str, tool_name: str, *, as_mapping: bool) -> Any:
    name = tool_name or "unknown_tool"
    if as_mapping:
        return {
            "role": "tool",
            "content": ABORTED_TOOL_RESULT_CONTENT,
            "tool_call_id": call_id,
            "metadata": {
                "kind": "interrupted_tool_result",
                "status": "aborted",
                "toolName": name,
            },
        }
    return ToolMessage(
        content=ABORTED_TOOL_RESULT_CONTENT,
        tool_call_id=call_id,
        name=name,
    )


def normalize_tool_call_pairing(messages: Any) -> Tuple[list, Dict[str, int]]:
    """Repair assistant tool-call / tool-result pairing before the provider call.

    Codex parity (``codex-rs/core/src/context_manager/normalize.rs``): every
    assistant tool call gets exactly one result — unanswered calls receive a
    synthesized ``aborted`` output — and orphan tool results without a matching
    call are removed. Compression output may lose one side of a pair when a
    summary or an error-preserving cut retires it; normalizing keeps the chain
    a valid provider payload without silently dropping the call contract.
    """

    materialized = _coerce_message_list(messages)
    normalized: List[Any] = []
    pending: List[Tuple[str, str, bool]] = []
    dropped_orphan_results = 0
    synthesized_aborted_results = 0
    changed = False

    def flush_pending() -> None:
        nonlocal changed, synthesized_aborted_results
        while pending:
            call_id, tool_name, as_mapping = pending.pop(0)
            normalized.append(
                _aborted_tool_result_message(call_id, tool_name, as_mapping=as_mapping)
            )
            synthesized_aborted_results += 1
            changed = True

    for message in materialized:
        role = _pairing_role(message)
        if role in {"ai", "assistant"}:
            flush_pending()
            normalized.append(message)
            names = _pairing_tool_call_names(message)
            as_mapping = isinstance(message, Mapping)
            for call_id in _pairing_tool_call_ids(message):
                pending.append((call_id, names.get(call_id, ""), as_mapping))
            continue
        result_id = _pairing_tool_result_id(message)
        if role == "tool" or (result_id and role not in {"system", "user", "human"}):
            matched = False
            if result_id:
                for index, (call_id, _name, _as_mapping) in enumerate(pending):
                    if call_id == result_id:
                        normalized.append(message)
                        del pending[index]
                        matched = True
                        break
            if not matched:
                dropped_orphan_results += 1
                changed = True
            continue
        flush_pending()
        normalized.append(message)
    flush_pending()
    if changed or not isinstance(messages, list):
        repaired_messages = normalized
    else:
        # Untouched chains keep their list identity so callers can detect
        # "compression changed nothing" without a deep comparison.
        repaired_messages = messages
    return repaired_messages, {
        "droppedOrphanResults": dropped_orphan_results,
        "synthesizedAbortedResults": synthesized_aborted_results,
    }


def build_retention_contract_summary_header(
    *,
    retention_contract: Any,
    iteration: int,
    compression_generation: int,
    before_tokens: int,
    after_tokens: int,
    context_input_hard_limit: int,
    pairing: Mapping[str, Any],
) -> str:
    """Bounded, structured retention header prefixed onto every compression summary."""

    contract = _as_mapping(retention_contract)
    scope_pairs: list[str] = []
    for key in (
        "researchProjectId",
        "projectId",
        "workflowId",
        "runId",
        "stageTaskId",
        "sessionId",
        "agentId",
        "roleKey",
    ):
        snake_key = "".join("_" + char.lower() if char.isupper() else char for char in key)
        value = _coerce_text(_mapping_get(contract, key, snake_key)).strip()
        if value:
            scope_pairs.append(f"{key}={value}")
    unresolved = ",".join(list(pairing.get("unresolvedCallIds") or [])[:12]) or "none"
    scope_text = " ".join(scope_pairs) if scope_pairs else "scope=unavailable"
    return (
        "[上下文保留合同] "
        f"{scope_text}"
        f" | compressionGeneration={max(0, int(compression_generation or 0))}"
        f" | iteration={max(0, int(iteration or 0))}"
        f" | unresolvedToolCallIds={unresolved}"
        f" | budget: before={max(0, int(before_tokens or 0))}"
        f" after={max(0, int(after_tokens or 0))}"
        f" hardLimit={max(0, int(context_input_hard_limit or 0))}"
    )


def apply_retention_contract_summary(summary: str, header: str) -> str:
    header_text = _coerce_text(header).strip()
    if not header_text:
        return summary
    return f"{header_text}\n{summary}".strip() if _coerce_text(summary).strip() else header_text


def evaluate_context_budget_preflight(
    *,
    estimated_tokens: int,
    context_input_hard_limit: int,
) -> Dict[str, Any]:
    """Pre-model-call hard input-limit gate (fail-closed, auditable).

    An unconfigured limit (``<= 0``) never reports ``exhausted`` (there is no
    limit to enforce, matching the historical contract), but it now says so:
    ``guardReason`` carries ``budget_limit_unconfigured`` instead of an empty
    string so budget decisions are never silent.
    """

    hard_limit = _coerce_nonnegative_int(context_input_hard_limit)
    estimated = _coerce_nonnegative_int(estimated_tokens)
    exhausted = hard_limit > 0 and estimated > hard_limit
    if exhausted:
        guard_reason = "input_over_hard_limit"
    elif hard_limit > 0:
        guard_reason = ""
    else:
        guard_reason = BUDGET_LIMIT_UNCONFIGURED_GUARD_REASON
    return {
        "exhausted": exhausted,
        "guardReason": guard_reason,
        "estimatedTokens": estimated,
        "hardLimit": hard_limit,
    }


def compress_turn_messages(
    *,
    messages: List[Any],
    iteration: int,
    reason: str = "",
    token_compressor: Any,
    config: Any,
    effective_max_token_limit: int,
    threshold_tokens: int,
    runtime_agent_binding: Optional[Dict[str, Any]] = None,
    project_root: str = "",
    mode: Any = AgentMode.CHAT,
    last_compression_iteration: int = 0,
    compression_min_iteration_gap: int = 3,
    compression_count_this_turn: int = 0,
    compression_strategy: Any = None,
    prompt_manager: Any = None,
    turn_runtime_fn: Any = None,
    estimate_tokens_fn: Any = None,
    get_ui_fn: Any = None,
    get_state_manager_fn: Any = None,
    scene_recorder_fn: Any = None,
    context_input_hard_limit: int = 0,
    post_compression_target_tokens: int = 0,
    retention_contract: Optional[Mapping[str, Any]] = None,
    trigger_source: str = "",
) -> Tuple[List[Any], bool, bool, int, int, str]:
    """Execute message compression.

    Fail-closed contract (versioned compression policy v3): when the compressed
    history breaks the retention chain (new unresolved tool calls / orphan tool
    results) or still exceeds ``context_input_hard_limit``, the original
    messages are returned with ``should_break=True`` and an auditable
    ``agent.context_budget_exhausted`` scene event is recorded; the model is
    never invoked with the over-limit or chain-broken context.

    ``should_break`` is reserved for that fail-closed contract alone. Emergency
    compression in non-chat modes returns ``should_break=False`` plus a
    dedicated ``stop_reason`` so the caller reports the real cause. Iteration
    limits belong to the main loop's configured RoundStateController;
    successful compression does not impose another iteration limit.

    Returns:
        (compressed_messages, should_break, last_context_compression_applied,
         new_compression_count, new_last_iteration, stop_reason)
    """
    ui_getter = get_ui_fn or get_ui
    ui = ui_getter()
    estimator = estimate_tokens_fn or estimate_messages_tokens
    messages = _coerce_message_list(messages)
    iteration = _coerce_nonnegative_int(iteration)
    last_compression_iteration = _coerce_nonnegative_int(last_compression_iteration)
    compression_min_iteration_gap = _coerce_nonnegative_int(
        compression_min_iteration_gap, default=3
    )
    compression_count_this_turn = _coerce_nonnegative_int(compression_count_this_turn)
    threshold_tokens = _coerce_nonnegative_int(threshold_tokens)
    reason = _coerce_text(reason)
    mode_text = _coerce_text(getattr(mode, "value", mode)).strip().lower()
    current_tokens = _coerce_nonnegative_int(estimator(messages))
    budget = max(1, _coerce_nonnegative_int(effective_max_token_limit, default=1))
    runtime_binding = _as_mapping(runtime_agent_binding)
    runtime_getter = turn_runtime_fn or _turn_runtime_from_env
    turn_runtime = _as_mapping(runtime_getter())
    from core.web.services import agent_directory_service

    # In-process chat turns bind their identity through the runtime ContextVar,
    # not process environment variables. Resolve it before the Agent's default
    # session so every compression artifact belongs to the turn being run.
    current_runtime = _as_mapping(agent_directory_service.current_agent_runtime())
    session_id = _coerce_text(
        _mapping_get(turn_runtime, "sessionId", "session_id")
        or _mapping_get(current_runtime, "sessionId", "session_id")
        or _mapping_get(runtime_binding, "directSessionId", "direct_session_id")
    ).strip()
    turn_id = _coerce_text(
        _mapping_get(turn_runtime, "runId", "run_id")
        or _mapping_get(current_runtime, "turnId", "turn_id")
    ).strip()
    recorder = scene_recorder_fn or _record_agent_scene_event
    agent_id = _coerce_text(_mapping_get(runtime_binding, "agentId", "agent_id")).strip()

    def record_preflight(*, eligible: bool, guard_reason: str = "") -> None:
        recorder(
            "runtime",
            "agent.context_compression.preflight",
            message="Agent context compression preflight evaluated.",
            outcome="eligible" if eligible else "skipped",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "turnId": turn_id,
                "iteration": iteration,
                "estimatedTokens": current_tokens,
                "effectiveLimit": budget,
                "thresholdTokens": threshold_tokens,
                "messageCount": len(messages),
                "eligible": eligible,
                "guardReason": guard_reason,
            },
        )

    # Guard: 压缩未启用
    if token_compressor is None or not resolve_feature_decision(
        "context_compression",
        config=config,
    ).effective_enabled:
        record_preflight(eligible=False, guard_reason="disabled")
        return messages, False, False, compression_count_this_turn, last_compression_iteration, ""

    # Guard: 速率限制
    if last_compression_iteration > 0:
        if iteration - last_compression_iteration < compression_min_iteration_gap:
            record_preflight(eligible=False, guard_reason="iteration_gap")
            return messages, False, False, compression_count_this_turn, last_compression_iteration, ""

    # Guard: 超过最大压缩次数
    max_comp = _coerce_nonnegative_int(
        getattr(config.context_compression, "max_compressions_per_session", 3),
        default=3,
    )
    if compression_count_this_turn >= max_comp:
        record_preflight(eligible=False, guard_reason="max_compressions")
        return messages, False, False, compression_count_this_turn, last_compression_iteration, ""

    record_preflight(eligible=True)

    # 确定压缩级别
    strategy = compression_strategy or get_compression_strategy()
    level = strategy.determine_level_with_iteration(
        current_tokens, budget, iteration, compression_count_this_turn
    )

    # 获取级别配置
    comp_config = strategy.get_config(level, current_tokens, budget)

    # 执行压缩
    combined_reason = reason or f"Level: {level.value}"
    resolved_trigger_source = (
        _coerce_text(trigger_source).strip()
        or _context_compression_trigger_source(combined_reason)
    )
    use_llm = level in (CompressionLevel.DEEP, CompressionLevel.EMERGENCY)

    # LLM summary failure breaker: repeated consecutive LLM summary failures
    # degrade *automatic* full compression to the rule-based summary, audibly
    # (see core/orchestration/llm_summary_breaker.py). Manual / provider-limit
    # compression requests are never intercepted -- their LLM attempts can
    # still succeed, which resets the counter and releases the breaker.
    # Micro-compaction makes no LLM call and is unaffected.
    breaker_threshold = _coerce_nonnegative_int(
        getattr(
            config.context_compression,
            "llm_summary_failure_breaker_threshold",
            llm_summary_breaker.DEFAULT_LLM_SUMMARY_FAILURE_BREAKER_THRESHOLD,
        ),
        default=llm_summary_breaker.DEFAULT_LLM_SUMMARY_FAILURE_BREAKER_THRESHOLD,
    )
    if use_llm and llm_summary_breaker.is_open(session_id, agent_id):
        breaker_failures = llm_summary_breaker.consecutive_failures(session_id, agent_id)
        if resolved_trigger_source == "auto":
            recorder(
                "runtime",
                "agent.context_compression.llm_summary_degraded",
                message=(
                    "Automatic full compression degraded to the rule-based summary: "
                    "LLM summary breaker is open."
                ),
                level="warning",
                outcome="degraded",
                fields={
                    "agentId": agent_id,
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "iteration": iteration,
                    "triggerSource": resolved_trigger_source,
                    "guardReason": llm_summary_breaker.BREAKER_GUARD_REASON,
                    "consecutiveFailures": breaker_failures,
                    "threshold": breaker_threshold,
                    "fallbackType": "rule_based_breaker_open",
                },
            )
            try:
                ui.add_log(
                    f"[压缩] LLM 摘要连败熔断生效，本次自动压缩改用规则摘要"
                    f"（连败 {breaker_failures} 次，成功一次后自动恢复）",
                    "WARN",
                )
            except Exception:
                pass
            use_llm = False
        # manual / provider_limit: fall through with the LLM attempt intact.
    messages_for_compression = messages
    tool_result_replacement_state: Dict[str, Any] = {"replacements": []}
    try:
        from core.chat.tool_result_replacement import replace_large_tool_results_for_compression

        replacement_limit = max(
            4_000,
            _coerce_nonnegative_int(comp_config.summary_max_chars, default=1_000) * 4,
        )
        messages_for_compression, tool_result_replacement_state = replace_large_tool_results_for_compression(
            messages,
            char_limit=replacement_limit,
            session_id=session_id,
        )
    except Exception:
        messages_for_compression = messages
        tool_result_replacement_state = {"replacements": []}

    ai_message_count = sum(
        1
        for message in messages_for_compression
        if isinstance(message, AIMessage) or getattr(message, "type", "") == "ai"
    )
    keep_ai_messages = min(
        max(0, _coerce_nonnegative_int(comp_config.keep_ai_messages)),
        max(0, ai_message_count - 1),
    )
    # Retention baseline: compression must never create a new unresolved call
    # or a new orphan tool result (strict provider validator stays fail-closed).
    before_pairing = _tool_call_pairing_snapshot(messages_for_compression)
    summary_reporter = None
    if use_llm:
        summary_reporter = llm_summary_breaker.SummaryBreakerReporter(
            session_id=session_id,
            agent_id=agent_id,
            turn_id=turn_id,
            iteration=iteration,
            threshold=breaker_threshold,
            trigger_source=resolved_trigger_source,
            recorder=recorder,
        )
    compression_output = token_compressor.compress(
        messages_for_compression,
        max_chars=comp_config.summary_max_chars,
        reason=combined_reason,
        keep_count=keep_ai_messages,
        preserve_errors=comp_config.preserve_errors,
        use_llm_summary=use_llm,
        llm_summary_reporter=summary_reporter,
    )
    compressed, summary = compression_output[0], compression_output[1]
    # The exact set of messages the summary folded (None for compressors that
    # predate the field): the ledger checkpoint needs it to cover only the
    # events that really entered the summary.
    summarized_messages = getattr(compression_output, "summarized_messages", None)
    def fail_closed(
        guard_reason: str,
        retention_after: Mapping[str, Any],
        after_tokens_value: int,
    ) -> Tuple[List[Any], bool, bool, int, int]:
        recorder(
            "runtime",
            "agent.context_budget_exhausted",
            message="Context compression could not satisfy the retention contract or hard input limit; model call blocked.",
            level="error",
            outcome="blocked",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "turnId": turn_id,
                "iteration": iteration,
                "guardReason": guard_reason,
                "estimatedTokens": current_tokens,
                "afterTokens": after_tokens_value,
                "contextInputHardLimit": normalized_hard_limit,
                "postCompressionTargetTokens": _coerce_nonnegative_int(post_compression_target_tokens),
                "retentionBefore": {
                    "unresolvedCallCount": before_pairing.get("unresolvedCallCount"),
                    "orphanResultCount": before_pairing.get("orphanResultCount"),
                },
                "retentionAfter": {
                    "unresolvedCallCount": retention_after.get("unresolvedCallCount"),
                    "orphanResultCount": retention_after.get("orphanResultCount"),
                },
                "messageCount": len(messages),
            },
        )
        return (
            messages,
            True,
            False,
            compression_count_this_turn,
            last_compression_iteration,
            STOP_REASON_CONTEXT_BUDGET_EXHAUSTED,
        )

    normalized_hard_limit = _coerce_nonnegative_int(context_input_hard_limit)
    refusal_reason = getattr(compression_output, "retention_refusal_reason", "")
    if refusal_reason:
        return fail_closed(str(refusal_reason), before_pairing, current_tokens)
    replacement_summary = _format_tool_result_replacement_summary(tool_result_replacement_state)
    if replacement_summary:
        summary = f"{summary}\n\n{replacement_summary}".strip() if summary else replacement_summary

    # Retention gate, check-first: judge the RAW compressed output before any
    # repair. normalize_tool_call_pairing is an explicit post-gate repair step
    # for damage that already existed in the input; running the gate on its
    # output made the check structurally unreachable (normalization zeroes
    # unresolved calls and drops orphan results by construction), so a
    # compression cut that broke the tool chain was silently repaired instead
    # of failing closed.
    raw_after_pairing = _tool_call_pairing_snapshot(compressed)
    raw_retention_violation = _retention_violation_reason(before_pairing, raw_after_pairing)
    if raw_retention_violation:
        return fail_closed(
            raw_retention_violation,
            raw_after_pairing,
            _coerce_nonnegative_int(estimator(compressed)),
        )

    # Provider-chain normalization (codex parity): synthesize aborted results
    # for unresolved calls and drop orphan tool results. It runs only after the
    # retention gate above passed, as an explicit repair for damage that
    # already existed in the input; a compression cut that newly breaks the
    # pair contract was already rejected instead of being silently repaired.
    # The repair stays auditable in the runtime scene.
    compressed, pairing_repair = normalize_tool_call_pairing(compressed)
    if pairing_repair["droppedOrphanResults"] or pairing_repair["synthesizedAbortedResults"]:
        recorder(
            "runtime",
            "agent.context_compression.tool_chain_normalized",
            message="Compressed history tool call/result pairing was normalized before the retention gate.",
            outcome="repaired",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "turnId": turn_id,
                "iteration": iteration,
                "droppedOrphanResults": pairing_repair["droppedOrphanResults"],
                "synthesizedAbortedResults": pairing_repair["synthesizedAbortedResults"],
                "messageCount": len(compressed),
            },
        )
        try:
            ui.add_log(
                "[压缩] 工具链配对修复："
                f"孤儿结果 -{pairing_repair['droppedOrphanResults']} / "
                f"合成 aborted +{pairing_repair['synthesizedAbortedResults']}",
                "WARN",
            )
        except Exception:
            pass

    # Recover from uncompressed journal facts before measuring the resulting
    # payload, so restored checklist data cannot bypass the hard input budget.
    if mode_text == AgentMode.CHAT and project_root and session_id and turn_id:
        from core.chat.todo_checklist import restore_todo_context_from_journal

        compressed = restore_todo_context_from_journal(
            compressed, project_root=project_root, session_id=session_id, turn_id=turn_id,
        )

    # 日志
    after_tokens = _coerce_nonnegative_int(estimator(compressed))
    token_saved = current_tokens - after_tokens

    # Fail-closed budget/retention gate: a broken retention chain or a
    # post-compression size that still exceeds the hard input limit must stop
    # the turn before any model call (auditable context_budget_exhausted).
    # The retention half re-checks the final payload defensively (the check
    # above already judged the raw output; normalization only removes
    # unresolved calls / orphan results), the hard-limit half is new here.
    after_pairing = _tool_call_pairing_snapshot(compressed)
    retention_violation = _retention_violation_reason(before_pairing, after_pairing)

    def estimate_send_payload(candidate: list) -> int:
        candidate_tokens = _coerce_nonnegative_int(estimator(candidate))
        if current_tokens > candidate_tokens:
            return _coerce_nonnegative_int(estimator([
                *candidate, build_context_compression_notice(current_tokens, candidate_tokens),
            ]))
        return candidate_tokens

    send_tokens = estimate_send_payload(compressed)
    budget_window_applied = False
    budget_window_event: Dict[str, Any] | None = None
    over_hard_limit = normalized_hard_limit > 0 and send_tokens > normalized_hard_limit
    window_limit = min((
        value for value in (
            normalized_hard_limit,
            _coerce_nonnegative_int(post_compression_target_tokens),
            max(1, threshold_tokens - 1) if threshold_tokens > 0 else 0,
        ) if value > 0
    ), default=0)
    if normalized_hard_limit > 0 and send_tokens > window_limit and not retention_violation:
        # Install a window below the next compression trigger when possible,
        # including the notice the caller appends. The ledger receives both
        # source and retained boundaries so this replacement survives replay.
        budget_window, budget_tokens, budget_applied = build_token_budget_window(
            compressed,
            hard_limit=window_limit,
            estimator=estimate_send_payload,
        )
        target_unreachable = not budget_applied and window_limit < normalized_hard_limit
        if target_unreachable:
            # The target is soft: never discard required context just to hit it.
            # Continue only if that complete context plus notice meets the hard gate.
            budget_window, budget_tokens, budget_applied = build_token_budget_window(
                compressed, hard_limit=normalized_hard_limit, estimator=estimate_send_payload,
                keep_history=False,
            )
        if budget_applied:
            budget_pairing = _tool_call_pairing_snapshot(budget_window)
            budget_violation = _retention_violation_reason(before_pairing, budget_pairing)
            if not budget_violation:
                if not summary and len(budget_window) < len(compressed):
                    # Without a checkpoint summary this cut would live only in
                    # memory and silently disappear on the next ledger replay.
                    return fail_closed("budget_window_requires_summary", budget_pairing, budget_tokens)
                budget_window_applied = len(budget_window) < len(compressed)
                if budget_window_applied:
                    budget_window_event = dict(
                        message=(
                            "Summarized history and its notice exceeded the compression target; "
                            "installed a token-budget window."
                        ),
                        outcome="applied",
                        fields={
                            "agentId": agent_id,
                            "sessionId": session_id,
                            "turnId": turn_id,
                            "iteration": iteration,
                            "beforeTokens": current_tokens,
                            "summarizedTokens": after_tokens,
                            "windowTokens": _coerce_nonnegative_int(estimator(budget_window)),
                            "sendTokens": budget_tokens,
                            "targetTokens": window_limit,
                            "targetUnreachable": target_unreachable,
                            "retiredMessageCount": len(compressed) - len(budget_window),
                            "contextInputHardLimit": normalized_hard_limit,
                            "messageCount": len(budget_window),
                        },
                    )
                compressed = budget_window
                after_tokens = _coerce_nonnegative_int(estimator(compressed))
                after_pairing = budget_pairing
                token_saved = current_tokens - after_tokens
                over_hard_limit = False
                if target_unreachable:
                    recorder(
                        "runtime", "agent.context_compression.target_unreachable",
                        message="Required context and notice fit the hard limit but exceed the compression target.",
                        outcome="continued",
                        fields={"targetTokens": window_limit, "sendTokens": budget_tokens,
                                "contextInputHardLimit": normalized_hard_limit},
                    )
    if retention_violation or over_hard_limit:
        guard_reason = retention_violation or "post_compression_over_hard_limit"
        return fail_closed(guard_reason, after_pairing, after_tokens)
    if normalized_hard_limit <= 0:
        # Zero-diagnosis guard: without a hard limit the budget gate cannot
        # fail closed, which used to be fully silent. The turn still proceeds
        # (unchanged behavior), but the unconfigured guard is now audible.
        recorder(
            "runtime",
            "agent.context_budget_unconfigured",
            message="Context input hard limit is unconfigured; the context budget gate cannot fail closed.",
            level="warning",
            outcome="monitored",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "turnId": turn_id,
                "iteration": iteration,
                "guardReason": BUDGET_LIMIT_UNCONFIGURED_GUARD_REASON,
                "estimatedTokens": current_tokens,
                "afterTokens": after_tokens,
                "contextInputHardLimit": 0,
                "messageCount": len(messages),
            },
        )

    # Prefix the bounded retention contract header onto the summary so scope,
    # compression generation and the tool calls that were summarized away
    # (still unresolved at compression time) stay auditable.
    if summary:
        summary = apply_retention_contract_summary(
            summary,
            build_retention_contract_summary_header(
                retention_contract={**_as_mapping(retention_contract), "sessionId": session_id},
                iteration=iteration,
                compression_generation=compression_count_this_turn + 1,
                before_tokens=current_tokens,
                after_tokens=after_tokens,
                context_input_hard_limit=_coerce_nonnegative_int(context_input_hard_limit),
                pairing=before_pairing,
            ),
        )
    over_target = (
        _coerce_nonnegative_int(post_compression_target_tokens) > 0
        and after_tokens > _coerce_nonnegative_int(post_compression_target_tokens)
    )
    if over_target:
        try:
            ui.add_log(
                f"[压缩] 超出压缩目标 {after_tokens} > {post_compression_target_tokens} tokens（未超硬上限）",
                "WARN",
            )
        except Exception:
            pass

    last_context_compression_applied = token_saved > 0
    if not summary and token_saved <= 0:
        recorder(
            "runtime",
            "agent.context_compression.skipped",
            message="Context compression had no safely compressible history.",
            outcome="skipped",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "turnId": turn_id,
                "iteration": iteration,
                "estimatedTokens": current_tokens,
                "effectiveLimit": budget,
                "thresholdTokens": threshold_tokens,
                "messageCount": len(messages),
                "guardReason": "no_compressible_history",
            },
        )
    try:
        effectiveness_threshold = float(
            getattr(config.context_compression, "effectiveness_threshold", 0.0) or 0.0
        )
    except Exception:
        effectiveness_threshold = 0.0
    effectiveness_ratio = (max(0, token_saved) / current_tokens) if current_tokens > 0 else 0.0
    # A budget window is an actual context replacement. Persist it even when
    # savings are below the advisory threshold, or replay resurrects its cuts.
    compression_effective = bool(
        budget_window_applied
        or (token_saved > 0 and (effectiveness_threshold <= 0 or effectiveness_ratio >= effectiveness_threshold))
    )
    ui.add_log(
        f"[压缩] {level.value.upper()} | {token_saved:+d} tokens "
        f"({current_tokens} -> {after_tokens}) | {combined_reason[:60]}",
        "INFO",
    )
    if not compression_effective:
        ui.add_log(
            f"[压缩] 收益不足 | saved={effectiveness_ratio:.1%} "
            f"threshold={effectiveness_threshold:.1%}",
            "WARN",
        )

    # 写入 COMPRESS_SUMMARY.md
    summary_written = False
    ledger_checkpoint_written = False
    if summary:
        if session_id and mode_text == AgentMode.CHAT and project_root:
            replacement_checkpoint_written = False
            try:
                from core.chat.conversation_ledger import (
                    append_context_compression_attempt,
                    append_context_compression_checkpoint,
                )

                if compression_effective:
                    checkpoint_kwargs: Dict[str, Any] = {
                        "source_messages": messages_for_compression,
                        "retained_messages": compressed,
                    }
                    if summarized_messages is not None:
                        # Exact covered domain: only the events whose messages
                        # really entered the summary. Kept-window / error-
                        # preserved events must stay replayable.
                        checkpoint_kwargs["summarized_messages"] = summarized_messages
                    event = append_context_compression_checkpoint(
                        Path(project_root),
                        session_id,
                        turn_id=turn_id or "context-compression",
                        current_turn_id=turn_id,
                        summary=summary,
                        level=level.value,
                        reason=combined_reason,
                        before_tokens=current_tokens,
                        after_tokens=after_tokens,
                        iteration=iteration,
                        trigger_source=resolved_trigger_source,
                        effectiveness_threshold=effectiveness_threshold,
                        effectiveness_ratio=effectiveness_ratio,
                        effective=True,
                        source_message_count=len(messages),
                        tool_result_replacement_state=tool_result_replacement_state,
                        **checkpoint_kwargs,
                    )
                    if budget_window_applied and event is None:
                        raise RuntimeError("Context replacement checkpoint was not written.")
                    replacement_checkpoint_written = event is not None
                else:
                    event = append_context_compression_attempt(
                        Path(project_root),
                        session_id,
                        turn_id=turn_id or "context-compression-attempt",
                        status="skipped_low_savings",
                        summary=summary,
                        level=level.value,
                        reason=combined_reason,
                        before_tokens=current_tokens,
                        after_tokens=after_tokens,
                        trigger_source=resolved_trigger_source,
                        effectiveness_threshold=effectiveness_threshold,
                        effectiveness_ratio=effectiveness_ratio,
                    )
                ledger_checkpoint_written = event is not None
                summary_written = ledger_checkpoint_written
            except Exception as exc:
                recorder(
                    "runtime",
                    "agent.context_compression_checkpoint_failed",
                    message="Failed to append context compression checkpoint to conversation ledger.",
                    level="warning",
                    outcome="failed",
                    fields={
                        "sessionId": session_id,
                        "turnId": turn_id,
                        "errorType": type(exc).__name__,
                        "reason": _coerce_text(combined_reason)[:160],
                        "beforeTokens": current_tokens,
                        "afterTokens": after_tokens,
                        "stage": "checkpoint",
                    },
                )
                try:
                    from core.chat.conversation_ledger import append_context_compression_attempt

                    event = append_context_compression_attempt(
                        Path(project_root),
                        session_id,
                        turn_id=turn_id or "context-compression-attempt",
                        status="failed_preserved",
                        summary="",
                        level=level.value,
                        reason=combined_reason,
                        before_tokens=current_tokens,
                        after_tokens=current_tokens,
                        trigger_source=resolved_trigger_source,
                        effectiveness_threshold=effectiveness_threshold,
                        effectiveness_ratio=effectiveness_ratio,
                        error_type=type(exc).__name__,
                    )
                    if not budget_window_applied:
                        ledger_checkpoint_written = event is not None
                        summary_written = ledger_checkpoint_written
                except Exception as fallback_exc:
                    recorder(
                        "runtime",
                        "session.context_compression.ledger_failed",
                        message="Failed to append context compression ledger fallback attempt.",
                        level="warning",
                        outcome="failed",
                        fields={
                            "sessionId": session_id,
                            "turnId": turn_id,
                            "errorType": type(fallback_exc).__name__,
                            "checkpointErrorType": type(exc).__name__,
                            "reason": _coerce_text(combined_reason)[:160],
                            "beforeTokens": current_tokens,
                            "afterTokens": after_tokens,
                            "stage": "attempt_fallback",
                        },
                    )
            if budget_window_applied and not replacement_checkpoint_written:
                return fail_closed("budget_window_checkpoint_not_written", after_pairing, after_tokens)
        try:
            if not ledger_checkpoint_written and prompt_manager is not None:
                prompt_manager.update_state_memory(
                    f"[上下文检查点 | iter={iteration} | {level.value}]\n{summary}"
                )
                summary_written = True
        except Exception:
            pass

    if budget_window_event is not None:
        recorder("runtime", "agent.context_compression.token_budget_applied", **budget_window_event)

    try:
        ui.note_context_compression_event(
            level=level.value,
            reason=combined_reason,
            before_tokens=current_tokens,
            after_tokens=after_tokens,
            saved_tokens=token_saved,
            iteration=iteration,
            summary_written=summary_written,
            trigger_source=resolved_trigger_source,
        )
    except Exception:
        pass

    # 更新状态
    try:
        state_mgr_getter = get_state_manager_fn or get_state_manager
        state_mgr_getter().set_state(
            AgentState.COMPRESSING,
            action=f"压缩 {level.value} (iter={iteration})",
        )
    except Exception:
        pass

    new_count = compression_count_this_turn + 1
    new_last_iteration = iteration

    # 仅非对话模式的紧急压缩在这里收轮；迭代上限由主循环统一控制。
    # should_break 只保留给 retention/hard-limit 契约。
    should_break = False
    stop_reason = ""
    if level == CompressionLevel.EMERGENCY and mode_text != AgentMode.CHAT:
        stop_reason = STOP_REASON_EMERGENCY_COMPRESSION
        ui.add_log("紧急压缩完成，非对话模式按防御策略收束本轮", "WARN")

    return (
        compressed,
        should_break,
        last_context_compression_applied,
        new_count,
        new_last_iteration,
        stop_reason,
    )
