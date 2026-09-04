# -*- coding: utf-8 -*-
"""Turn message context compression orchestrator for long-running Agent turns."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage

from core.infrastructure.feature_gate import resolve_feature_decision
from core.infrastructure.state import AgentState, get_state_manager
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
) -> Tuple[List[Any], bool, bool, int, int]:
    """Execute message compression.

    Fail-closed contract (versioned compression policy v3): when the compressed
    history breaks the retention chain (new unresolved tool calls / orphan tool
    results) or still exceeds ``context_input_hard_limit``, the original
    messages are returned with ``should_break=True`` and an auditable
    ``agent.context_budget_exhausted`` scene event is recorded; the model is
    never invoked with the over-limit or chain-broken context.

    Returns:
        (compressed_messages, should_break, last_context_compression_applied,
         new_compression_count, new_last_iteration)
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
    session_id = _coerce_text(
        _mapping_get(turn_runtime, "sessionId", "session_id")
        or _mapping_get(runtime_binding, "directSessionId", "direct_session_id")
    ).strip()
    turn_id = _coerce_text(_mapping_get(turn_runtime, "runId", "run_id")).strip()
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
        return messages, False, False, compression_count_this_turn, last_compression_iteration

    # Guard: 速率限制
    if last_compression_iteration > 0:
        if iteration - last_compression_iteration < compression_min_iteration_gap:
            record_preflight(eligible=False, guard_reason="iteration_gap")
            return messages, False, False, compression_count_this_turn, last_compression_iteration

    # Guard: 超过最大压缩次数
    max_comp = _coerce_nonnegative_int(
        getattr(config.context_compression, "max_compressions_per_session", 3),
        default=3,
    )
    if compression_count_this_turn >= max_comp:
        record_preflight(eligible=False, guard_reason="max_compressions")
        return messages, False, False, compression_count_this_turn, last_compression_iteration

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
    use_llm = level in (CompressionLevel.DEEP, CompressionLevel.EMERGENCY)
    messages_for_compression = messages
    tool_result_replacement_state: Dict[str, Any] = {"replacements": []}
    try:
        from core.chat.tool_result_replacement import replace_large_tool_results_for_compression

        tool_session_id = _coerce_text(
            _mapping_get(runtime_binding, "directSessionId", "direct_session_id") or session_id
        ).strip()
        replacement_limit = max(
            4_000,
            _coerce_nonnegative_int(comp_config.summary_max_chars, default=1_000) * 4,
        )
        messages_for_compression, tool_result_replacement_state = replace_large_tool_results_for_compression(
            messages,
            char_limit=replacement_limit,
            session_id=tool_session_id,
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
    compressed, summary = token_compressor.compress(
        messages_for_compression,
        max_chars=comp_config.summary_max_chars,
        reason=combined_reason,
        keep_count=keep_ai_messages,
        preserve_errors=comp_config.preserve_errors,
        use_llm_summary=use_llm,
    )
    replacement_summary = _format_tool_result_replacement_summary(tool_result_replacement_state)
    if replacement_summary:
        summary = f"{summary}\n\n{replacement_summary}".strip() if summary else replacement_summary

    # 日志
    after_tokens = _coerce_nonnegative_int(estimator(compressed))
    token_saved = current_tokens - after_tokens

    # Fail-closed budget/retention gate: a broken retention chain or a
    # post-compression size that still exceeds the hard input limit must stop
    # the turn before any model call (auditable context_budget_exhausted).
    after_pairing = _tool_call_pairing_snapshot(compressed)
    retention_violation = _retention_violation_reason(before_pairing, after_pairing)
    normalized_hard_limit = _coerce_nonnegative_int(context_input_hard_limit)
    over_hard_limit = normalized_hard_limit > 0 and after_tokens > normalized_hard_limit
    if retention_violation or over_hard_limit:
        guard_reason = retention_violation or "post_compression_over_hard_limit"
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
                "afterTokens": after_tokens,
                "contextInputHardLimit": normalized_hard_limit,
                "postCompressionTargetTokens": _coerce_nonnegative_int(post_compression_target_tokens),
                "retentionBefore": {
                    "unresolvedCallCount": before_pairing.get("unresolvedCallCount"),
                    "orphanResultCount": before_pairing.get("orphanResultCount"),
                },
                "retentionAfter": {
                    "unresolvedCallCount": after_pairing.get("unresolvedCallCount"),
                    "orphanResultCount": after_pairing.get("orphanResultCount"),
                },
                "messageCount": len(messages),
            },
        )
        return messages, True, False, compression_count_this_turn, last_compression_iteration
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
                retention_contract=retention_contract,
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
    compression_effective = bool(token_saved > 0 and (effectiveness_threshold <= 0 or effectiveness_ratio >= effectiveness_threshold))
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
        try:
            from core.web.services import agent_directory_service

            current_runtime = agent_directory_service.current_agent_runtime()
            session_id = _coerce_text(
                session_id or _mapping_get(_as_mapping(current_runtime), "sessionId", "session_id")
            ).strip()
            turn_id = _coerce_text(
                turn_id or _mapping_get(_as_mapping(current_runtime), "turnId", "turn_id")
            ).strip()
        except Exception:
            pass
        if session_id and mode_text == AgentMode.CHAT and project_root:
            try:
                from core.chat.conversation_ledger import (
                    append_context_compression_attempt,
                    append_context_compression_checkpoint,
                )

                if compression_effective:
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
                        trigger_source=_context_compression_trigger_source(combined_reason),
                        effectiveness_threshold=effectiveness_threshold,
                        effectiveness_ratio=effectiveness_ratio,
                        effective=True,
                        source_message_count=len(messages),
                        tool_result_replacement_state=tool_result_replacement_state,
                    )
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
                        trigger_source=_context_compression_trigger_source(combined_reason),
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
                        trigger_source=_context_compression_trigger_source(combined_reason),
                        effectiveness_threshold=effectiveness_threshold,
                        effectiveness_ratio=effectiveness_ratio,
                        error_type=type(exc).__name__,
                    )
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
        try:
            if not ledger_checkpoint_written and prompt_manager is not None:
                prompt_manager.update_state_memory(
                    f"[上下文检查点 | iter={iteration} | {level.value}]\n{summary}"
                )
                summary_written = True
        except Exception:
            pass

    try:
        ui.note_context_compression_event(
            level=level.value,
            reason=combined_reason,
            before_tokens=current_tokens,
            after_tokens=after_tokens,
            saved_tokens=token_saved,
            iteration=iteration,
            summary_written=summary_written,
            trigger_source=_context_compression_trigger_source(combined_reason),
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

    # 提前结束判断
    should_break = False
    if level == CompressionLevel.EMERGENCY and mode_text != AgentMode.CHAT:
        should_break = True
        ui.add_log("紧急压缩触发，提前结束当前轮次", "WARN")
    elif iteration > 30:
        should_break = True
        ui.add_log(f"迭代次数过多 ({iteration})，提前结束当前轮次", "WARN")

    return compressed, should_break, last_context_compression_applied, new_count, new_last_iteration
