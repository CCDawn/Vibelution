# -*- coding: utf-8 -*-
"""Turn message context compression orchestrator for long-running Agent turns."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage

from core.infrastructure.feature_gate import resolve_feature_decision
from core.infrastructure.state import AgentState, get_state_manager
from core.orchestration.agent_modes import AgentMode
from core.orchestration.agent_runtime_bindings import (
    _context_compression_trigger_source,
    _format_tool_result_replacement_summary,
    _record_agent_scene_event,
    _turn_runtime_from_env,
)
from core.ui.cli_ui import get_ui
from tools.compression_strategy import CompressionLevel, get_compression_strategy
from tools.token_manager import estimate_messages_tokens


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
) -> Tuple[List[Any], bool, bool, int, int]:
    """Execute message compression.

    Returns:
        (compressed_messages, should_break, last_context_compression_applied,
         new_compression_count, new_last_iteration)
    """
    ui_getter = get_ui_fn or get_ui
    ui = ui_getter()
    estimator = estimate_tokens_fn or estimate_messages_tokens
    current_tokens = estimator(messages)
    budget = max(1, int(effective_max_token_limit))
    runtime_binding = dict(runtime_agent_binding or {})
    runtime_getter = turn_runtime_fn or _turn_runtime_from_env
    turn_runtime = runtime_getter()
    session_id = str(
        turn_runtime.get("sessionId")
        or runtime_binding.get("directSessionId")
        or ""
    ).strip()
    turn_id = str(turn_runtime.get("runId") or "").strip()
    recorder = scene_recorder_fn or _record_agent_scene_event

    def record_preflight(*, eligible: bool, guard_reason: str = "") -> None:
        recorder(
            "runtime",
            "agent.context_compression.preflight",
            message="Agent context compression preflight evaluated.",
            outcome="eligible" if eligible else "skipped",
            fields={
                "agentId": str(runtime_binding.get("agentId") or "").strip(),
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
    max_comp = getattr(config.context_compression, "max_compressions_per_session", 3)
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

        tool_session_id = str(runtime_binding.get("directSessionId") or session_id or "").strip()
        replacement_limit = max(4_000, int(comp_config.summary_max_chars or 1_000) * 4)
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
        max(0, int(comp_config.keep_ai_messages or 0)),
        max(0, ai_message_count - 1),
    )
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
    after_tokens = estimator(compressed)
    token_saved = current_tokens - after_tokens
    last_context_compression_applied = token_saved > 0
    if not summary and token_saved <= 0:
        recorder(
            "runtime",
            "agent.context_compression.skipped",
            message="Context compression had no safely compressible history.",
            outcome="skipped",
            fields={
                "agentId": str(runtime_binding.get("agentId") or "").strip(),
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
            session_id = str(session_id or current_runtime.get("sessionId") or "").strip()
            turn_id = str(turn_id or current_runtime.get("turnId") or "").strip()
        except Exception:
            pass
        if session_id and mode == AgentMode.CHAT and project_root:
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
                    fields={
                        "sessionId": session_id,
                        "turnId": turn_id,
                        "errorType": type(exc).__name__,
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
                except Exception:
                    pass
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
    if level == CompressionLevel.EMERGENCY and mode != AgentMode.CHAT:
        should_break = True
        ui.add_log("紧急压缩触发，提前结束当前轮次", "WARN")
    elif iteration > 30:
        should_break = True
        ui.add_log(f"迭代次数过多 ({iteration})，提前结束当前轮次", "WARN")

    return compressed, should_break, last_context_compression_applied, new_count, new_last_iteration
