"""Session ops / update / transcript / repair helpers.

Claim scope: update session metadata/title/reasoning effort, list prewarm,
chat message builders, codex transcript helpers, terminal error items,
stale-running repair, tool-governance pending, SC continuation prompts,
and related residual session operations.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import copy
import hashlib
import re
from typing import Any, Mapping

# Local default for signature evaluation (facade remains SSOT via s.SESSION_LLM_SLOT_DIALOGUE).
SESSION_LLM_SLOT_DIALOGUE = "dialogue"


def _service():
    from core.web.services import session_service

    return session_service


def _build_chat_turn_records_from_messages(messages: list[dict[str, Any]]) -> list[Any]:
    s = _service()
    turns: list[Any] = []
    pending_user_message = ""
    for item in list(messages or []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = s._sanitize_message_content(role, item.get("content") or "")
        if not content:
            continue
        if role == "user":
            pending_user_message = content
            continue
        if role != "assistant" or not pending_user_message:
            continue
        tool_calls = [
            str(tool_call.get("name") if isinstance(tool_call, dict) else tool_call or "").strip()
            for tool_call in s.normalize_chat_tool_calls(item.get("tool_calls") or item.get("toolCalls") or item.get("tools") or [])
        ]
        tool_calls = [tool_name for tool_name in tool_calls if tool_name]
        turns.append(
            s.ChatTurnRecord(
                turn_number=len(turns) + 1,
                user_message=pending_user_message,
                assistant_message=content,
                tool_calls=tool_calls,
                tool_call_count=len(tool_calls),
                had_delegation=False,
                had_explicit_conclusion=s.has_conclusion_signal(content),
                had_next_action=s.has_next_action_signal(content),
                metadata={"mode": "chat", "source": "web_session"},
            )
        )
        pending_user_message = ""
    return turns


def _build_contextual_confirmation_prompt(
    confirmation: str,
    goal: str,
    *,
    existing_task: dict[str, Any] | None = None,
) -> str:
    s = _service()
    compact_confirmation = s.trim_lines(confirmation or "", max_lines=1)
    compact_goal = s.trim_lines(goal or "", max_lines=2)
    if not compact_confirmation or not compact_goal:
        return compact_goal or compact_confirmation
    lines = [
        f"用户确认：{compact_confirmation}",
        f"请基于已确认的当前目标继续执行：{compact_goal}",
    ]
    if isinstance(existing_task, dict):
        latest_summary = s.trim_lines(existing_task.get("latest_summary") or "", max_lines=2)
        next_action = s.trim_lines(existing_task.get("next_action") or "", max_lines=2)
        if latest_summary:
            lines.append(f"最近进展：{latest_summary}")
        if next_action:
            lines.append(f"下一步：{next_action}")
    lines.append("不要把这个确认短句当成新的任务标题，也不要只重复回答目标本身。")
    return "\n".join(lines)


def _build_resume_goal_from_conversation_context(
    messages: list[dict[str, Any]],
    *,
    active_task: dict[str, Any],
) -> str:
    s = _service()
    effective_goals = s._latest_effective_user_messages(messages, limit=3)
    context_lines: list[str] = []
    for item in list(messages or [])[-8:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        if role == "user" and s._is_system_authored_user_message_entry(item):
            continue
        content = s.trim_lines(s._sanitize_message_content(role, item.get("content") or ""), max_lines=4)
        if not content:
            continue
        if role == "user" and not (s._is_effective_user_message(content) or s._is_contextual_confirmation_message(content)):
            continue
        if role == "assistant" and s._looks_like_runtime_failure_notice(content):
            content = "上一轮被运行保护暂停，未完成真实用户目标。"
        context_lines.append(f"{'用户' if role == 'user' else 'Agent'}：{content}")
    read_files = []
    if isinstance(active_task, dict):
        read_files = [
            str(item).strip()
            for item in list(active_task.get("read_files") or active_task.get("readFiles") or [])[:5]
            if str(item).strip()
        ]
    if not effective_goals and not context_lines and not read_files:
        return ""
    lines = [
        "继续完成当前会话中尚未完成的真实用户目标。",
        "不要把“继续”“确认”“好的开始修改”这类控制/确认短句当作任务目标。",
    ]
    if effective_goals:
        lines.append("最近有效用户请求：")
        lines.extend(f"- {goal}" for goal in effective_goals)
    if context_lines:
        lines.append("最近对话上下文：")
        lines.extend(context_lines[-6:])
    if read_files:
        lines.append("当前已读文件：" + "、".join(read_files))
    lines.append("请先恢复真实任务语境，再基于已有证据继续推进并输出可见结果。")
    return "\n".join(lines)


def _build_terminal_error_turn_item(
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    content: Any,
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    s = _service()
    normalized_metadata = dict(metadata or {})
    normalized_turn_id = str(
        turn_id
        or normalized_metadata.get("turnId")
        or normalized_metadata.get("turn_id")
        or ""
    ).strip()
    item_id = f"{s._session_turn_item_base_id(session_id, normalized_turn_id)}-error"
    diagnostic_summary = {
        key: normalized_metadata[key]
        for key in (
            "reasonCode",
            "reasonSummary",
            "reasonDetail",
            "httpStatus",
            "providerErrorType",
            "provider",
            "model",
            "chainStage",
            "eventCode",
            "traceId",
            "protocol",
            "retryable",
        )
        if normalized_metadata.get(key) not in (None, "")
    }
    return {
        "version": 2,
        "id": f"{item_id}:0",
        "type": "error",
        "sessionId": str(session_id or "").strip(),
        "turnId": normalized_turn_id,
        "itemId": item_id,
        "revision": 0,
        "sequence": 1,
        "kind": "error",
        "phase": "turn_failed",
        "status": "failed",
        "provisional": False,
        "terminal": True,
        "messageId": str(message_id or "").strip(),
        "source": "session_turn_error",
        "text": str(content or "").strip(),
        "diagnosticSummary": diagnostic_summary,
        "metadata": {"turnId": normalized_turn_id},
    }


def _chat_turn_result_status(result_status: str, result: Any, *, stop_requested: bool) -> str:
    s = _service()
    if stop_requested:
        return "stopped_by_user"
    normalized = str(result_status or "").strip().lower()
    if isinstance(result, dict):
        contract = s.build_chat_coding_result_contract(result)
        outcome = str(contract.get("outcome") or result.get("outcome") or result.get("task_outcome") or "").strip().lower()
        explicit_outcome = s._explicit_chat_result_outcome(result)
        visible = s._visible_reply_candidate(result)
        if normalized == "completed" and s._chat_contract_blocks_unexecuted_validation(contract):
            return "needs_continue"
        if normalized == "completed" and explicit_outcome != "progress" and visible:
            return "completed"
        tool_count = s._coerce_nonnegative_int(result.get("tool_call_count") or 0)
        tool_trace = list(result.get("tool_trace") or result.get("tool_calls") or [])
        if normalized == "completed" and not visible and (tool_count > 0 or tool_trace):
            return "needs_continue"
        if outcome == "progress":
            return "needs_continue"
    if normalized == "completed":
        return "completed"
    if normalized in {
        "needs_continue",
        "paused_limit",
        "stopped_by_user",
        "force_stopping",
        "stop_failed",
        "failed_provider",
        "failed_runtime",
        "superseded",
    }:
        return normalized
    if normalized in {"failed", "timeout", "error"}:
        return "failed_runtime"
    return normalized or "completed"


def _codex_transcript_cell_from_operation_source(
    message_id: str,
    source: dict[str, Any],
    ordinal: int,
) -> tuple[dict[str, Any] | None, dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    s = _service()
    operation_id = str(source.get("_operationId") or "").strip()
    status = s._codex_lifecycle_status(source.get("status") or source.get("semanticStatus"))
    kind = str(source.get("kind") or "tool").strip().lower()
    if kind == "assistant_text":
        text = s._sanitize_message_content("assistant", source.get("content") or source.get("text") or "")
        if not text:
            return None, s._empty_codex_tool_lifecycle_projection(), []
        return (
            s._compact_codex_record(
                {
                    "id": f"{message_id}-{operation_id}",
                    "kind": "assistant_markdown",
                    "messageId": message_id,
                    "status": status,
                    "tone": s._codex_cell_tone(status),
                    "phase": "commentary",
                    "text": text,
                    "sourceItemId": operation_id,
                }
            ),
            s._empty_codex_tool_lifecycle_projection(),
            [],
        )
    title = str(source.get("name") or source.get("label") or "").strip()
    summary = s._codex_operation_summary(source, failed=status == "failed")
    cell_kind = s._codex_cell_kind(kind, status)
    cell = s._compact_codex_record(
        {
            "id": f"{message_id}-{operation_id}",
            "kind": cell_kind,
            "messageId": message_id,
            "status": status,
            "tone": s._codex_cell_tone(status),
            "title": title or s._codex_cell_default_title(cell_kind),
            "summary": summary,
            "operationIds": [operation_id] if operation_id else [],
            "sourceItemId": operation_id,
        }
    )
    if kind != "tool":
        return cell, s._empty_codex_tool_lifecycle_projection(), []
    lifecycle = s._codex_tool_lifecycle_projection_from_source(source, operation_id, ordinal, status, title, summary)
    rollout_events = s._codex_rollout_events_from_lifecycle(
        lifecycle["toolCalls"][0],
        lifecycle["terminalOperations"][0] if lifecycle["terminalOperations"] else None,
    ) if lifecycle["toolCalls"] else []
    if rollout_events:
        cell["rolloutTraceEvents"] = rollout_events
    if any(lifecycle.values()):
        cell["toolLifecycleModel"] = lifecycle
    return cell, lifecycle, rollout_events


def _codex_transcript_operation_sources(
    message_id: str,
    feedback_events: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    s = _service()
    sources: list[dict[str, Any]] = []
    for event in feedback_events:
        source = dict(event)
        if s._is_non_diagnostic_runtime_status_source(source):
            continue
        source["_operationId"] = s._codex_operation_id(message_id, source, len(sources) + 1)
        source["_sourceKind"] = "feedback"
        sources.append(source)
    if sources:
        return sources
    for index, tool_call in enumerate(tool_calls, start=1):
        source = dict(tool_call)
        source.setdefault("kind", "tool")
        source["_operationId"] = s._codex_operation_id(message_id, source, index)
        source["_sourceKind"] = "toolCall"
        source["_sequence"] = index
        sources.append(source)
    return sources


def _is_contextual_confirmation_message(text: Any) -> bool:
    s = _service()
    compact = re.sub(r"\s+", "", str(text or "")).strip().lower()
    if not compact:
        return False
    semantic_compact = re.sub(r"[，,。.!！?？、；;：:]+", "", compact)
    exact_values = {
        "确认",
        "同意",
        "可以",
        "好的",
        "好",
        "是的",
        "对的",
        "好的开始修改",
        "好开始修改",
        "开始修改",
        "好的开始修复",
        "开始修复",
        "好的开始实现",
        "开始实现",
        "好的开始执行",
        "开始执行",
        "确认开始",
        "同意开始",
        "可以开始",
        "好的继续",
        "好继续",
        "现在好了你再试一下",
        "现在应该真的可以了你再试试",
        "好了应该恢复了你再试试",
        "好的现在修好了你继续",
        "修好了你继续",
    }
    if semantic_compact in exact_values:
        return True
    if "再试" in semantic_compact and any(
        marker in semantic_compact for marker in ("好了", "修好了", "恢复", "可以了", "应该")
    ):
        return True
    if semantic_compact.endswith("你继续") and any(
        marker in semantic_compact for marker in ("好了", "修好了", "恢复", "可以了")
    ):
        return True
    return bool(
        re.fullmatch(
            r"(好的|好|确认|同意|可以|是的|对的)?(按这个|按计划|就这样)?(开始|继续)(修改|修复|实现|执行|处理|推进)",
            semantic_compact,
        )
    )


def _is_session_turn_terminal(result: Any) -> bool:
    s = _service()
    if not isinstance(result, dict):
        return True
    if bool(result.get("stop_requested")):
        return True

    status = str(result.get("status") or "").strip().lower()
    contract = s.build_chat_coding_result_contract(result)
    outcome = str(contract.get("outcome") or "").strip().lower()
    visible = s._visible_reply_candidate(result)
    tool_count = int(result.get("tool_call_count") or 0)
    tool_trace = list(result.get("tool_trace") or [])

    if status in {"failed", "timeout", "stopped"}:
        return True
    explicit_outcome = s._explicit_chat_result_outcome(result)

    if (
        status == "completed"
        and explicit_outcome != "progress"
        and visible
        and (s.has_conclusion_signal(visible) or s.has_next_action_signal(visible))
    ):
        return True
    if explicit_outcome == "progress":
        return False
    if not visible and s._raw_visible_payload_is_control_marker_only(result) and outcome in {"done", "blocked", "needs_input"}:
        return True
    if not visible and (tool_count > 0 or tool_trace):
        return False
    if outcome in {"done", "blocked", "needs_input"}:
        return True
    if not visible:
        return False
    return True


def _latest_unfinished_task_goal(session_id: str) -> str:
    s = _service()
    goal, _source = s._latest_unfinished_task_goal_with_source(session_id)
    return goal


def _latest_unfinished_task_goal_with_source(session_id: str) -> tuple[str, str]:
    s = _service()
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, session_id)
        if conversation is None:
            return "", ""
        active_task = s._normalize_session_active_task(
            conversation.get("active_task") or conversation.get("activeTask")
        )
    messages = s._session_ledger_visible_messages(session_id)
    if not s._is_task_tool_backed_active_task(active_task):
        return "", ""
    status = str(active_task.get("status") or "").strip().lower()
    if status in {"done", "idle"}:
        return "", ""
    goal = s.trim_lines(active_task.get("goal") or active_task.get("title") or "", max_lines=2)
    if s._is_effective_user_message(goal):
        history_goal, history_goal_index = s._latest_effective_user_message_with_index(messages)
        if s._should_prefer_history_goal_over_active_task(
            active_task,
            messages,
            existing_goal=goal,
            history_goal=history_goal,
            history_goal_index=history_goal_index,
        ):
            context_goal = s._build_resume_goal_from_conversation_context(messages, active_task=active_task)
            if context_goal:
                return context_goal, "conversation_context_newer_user_goal"
            return history_goal, "history_newer_user_goal"
        return goal, "active_task"
    if s._is_continue_request(goal) or not s._is_meaningful_task_goal(goal):
        history_goal = s._latest_meaningful_user_message(messages)
        if history_goal:
            return history_goal, "history"
    context_goal = s._build_resume_goal_from_conversation_context(messages, active_task=active_task)
    if context_goal:
        return context_goal, "conversation_context"
    history_goal = s._latest_meaningful_user_message(messages)
    if history_goal:
        return history_goal, "history"
    return "", ""


def _load_conversation_detail_target(
    session_id: str,
    *,
    payload: dict[str, Any] | None = None,
    repair: bool = True,
    agent_by_id: dict[str, dict[str, Any]] | None = None,
    lightweight: bool = False,
) -> dict[str, Any] | None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    payload = payload if isinstance(payload, dict) else s.load_chat_state(s.PROJECT_ROOT)
    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        return None
    agent_by_id = agent_by_id if agent_by_id is not None else s._agent_lookup_for_conversations()
    hidden_team_member_agent_ids = s._agent_directory_stub_hidden_team_member_ids()
    changed = False
    if repair:
        changed = s._repair_child_root_agent_direct_session_bindings(payload, agent_by_id=agent_by_id) or changed
    for raw in conversations:
        if not isinstance(raw, dict):
            continue
        raw_session_id = str(raw.get("conversation_id") or s.DEFAULT_CHAT_CONVERSATION_ID).strip()
        if raw_session_id != normalized_session_id:
            continue
        if repair:
            changed = s._repair_stale_running_conversation(raw) or changed
            changed = s._ensure_conversation_agent_metadata(raw, agent_by_id=agent_by_id) or changed
            changed = s._ensure_conversation_workspace_metadata(raw) or changed
        conversation = s._normalize_conversation(
            raw,
            agent_by_id=agent_by_id,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
            ensure_workspace=repair,
            lightweight=lightweight,
        )
        if changed:
            payload["updated_at"] = s._now_timestamp()
            s.save_chat_state(s.PROJECT_ROOT, payload)
        return conversation
    return None


def _make_chat_message(
    role: str,
    content: str,
    tool_calls: list[Any] | None = None,
    *,
    thought: str = "",
    mental_snapshot: dict[str, Any] | None = None,
    feedback_events: list[Any] | None = None,
    metadata: dict[str, Any] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    message: dict[str, Any] = {
        "role": str(role or "").strip().lower(),
        "content": s._ensure_assistant_visible_text(content) if str(role or "").strip().lower() == "assistant" else str(content or "").strip(),
        "timestamp": s._now_timestamp(),
    }
    cleaned_thought = s._sanitize_thought_text(thought)
    if cleaned_thought:
        message["thought"] = cleaned_thought
    normalized_snapshot = s._normalize_mental_snapshot(mental_snapshot)
    if normalized_snapshot is not None:
        message["mental_snapshot"] = normalized_snapshot
    normalized_tool_calls = s._normalize_persisted_tool_calls(tool_calls or [])
    if normalized_tool_calls:
        message["tool_calls"] = normalized_tool_calls
    normalized_feedback_events = s._normalize_persisted_feedback_events(feedback_events or [])
    if normalized_feedback_events:
        message["feedback_events"] = normalized_feedback_events
    normalized_attachments = s._normalize_message_attachments(attachments or [])
    if normalized_attachments:
        message["attachments"] = normalized_attachments
    normalized_references = s._normalize_session_references(references or [])
    if normalized_references:
        message["references"] = normalized_references
    if isinstance(metadata, dict) and metadata:
        message["metadata"] = dict(metadata)
        if message["role"] == "assistant" and str(metadata.get("kind") or "").strip() == "turn_error":
            message["content"] = s._complete_turn_error_visible_content(message.get("content") or "", metadata)
    return message


def _make_local_runtime_error_chat_message(turn_error: dict[str, Any], *, turn_id: str = "") -> dict[str, Any]:
    s = _service()
    timestamp = str(turn_error.get("timestamp") or s._now_timestamp()).strip()
    error_type = str(turn_error.get("error_type") or turn_error.get("errorType") or "runtime_error").strip()
    reason_summary = str(turn_error.get("reason_summary") or turn_error.get("reasonSummary") or "").strip()
    reason_detail = str(turn_error.get("reason_detail") or turn_error.get("reasonDetail") or "").strip()
    visible_message = str(turn_error.get("message") or "").strip()
    message = s._make_chat_message(
        "assistant",
        visible_message,
        metadata={
            "kind": "turn_error",
            "errorType": error_type,
            "turnId": str(turn_error.get("turn_id") or turn_error.get("turnId") or turn_id or "").strip(),
            "recoverable": bool(turn_error.get("recoverable")),
            "providerFailure": False,
            "reasonCode": str(turn_error.get("reason_code") or turn_error.get("reasonCode") or "").strip(),
            "reasonSummary": reason_summary,
            "reasonDetail": reason_detail,
            "httpStatus": s._coerce_nonnegative_int(turn_error.get("http_status") or turn_error.get("httpStatus")) or None,
            "provider": str(turn_error.get("provider") or "").strip(),
            "providerHost": str(turn_error.get("provider_host") or turn_error.get("providerHost") or "").strip(),
            "providerErrorType": str(turn_error.get("provider_error_type") or turn_error.get("providerErrorType") or "").strip(),
            "providerErrorMessage": str(turn_error.get("provider_error_message") or turn_error.get("providerErrorMessage") or "").strip(),
            "model": str(turn_error.get("model") or "").strip(),
            "chainStage": str(turn_error.get("chain_stage") or turn_error.get("chainStage") or "").strip(),
            "eventCode": str(turn_error.get("event_code") or turn_error.get("eventCode") or "").strip(),
            "traceId": str(turn_error.get("trace_id") or turn_error.get("traceId") or "").strip(),
            "protocol": str(turn_error.get("protocol") or "").strip(),
        },
    )
    message["timestamp"] = timestamp
    return message


def _pending_tool_governance_requests_for_session(agent_id: str, *, limit: int = 3) -> list[dict[str, Any]]:
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return []
    try:
        from core.web.services import agent_tool_governance_service

        requests = agent_tool_governance_service.list_tool_governance_requests(
            agent_id=normalized_agent_id,
            status="pending_review",
            limit=limit,
        )
    except Exception as exc:
        s._debug_logger.warning(
            f"Failed to list pending tool governance requests for session detail. agent={normalized_agent_id}, limit={limit}, error={type(exc).__name__}: {exc}",
            tag="AGENT_TOOL_GOVERNANCE",
        )
        return []
    result: list[dict[str, Any]] = []
    for item in requests:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "eventId": str(item.get("eventId") or "").strip(),
                "requestId": str(item.get("requestId") or item.get("eventId") or "").strip(),
                "kind": str(item.get("kind") or "tool_governance_request").strip(),
                "status": str(item.get("status") or "pending_review").strip(),
                "grantScope": str(item.get("grantScope") or "persistent").strip(),
                "sourceSessionId": str(item.get("sourceSessionId") or "").strip(),
                "sourceTurnId": str(item.get("sourceTurnId") or "").strip(),
                "targetAgentId": str(item.get("targetAgentId") or "").strip(),
                "targetAgentCode": str(item.get("targetAgentCode") or "").strip(),
                "targetAgentName": str(item.get("targetAgentName") or "").strip(),
                "proposedByAgentId": str(item.get("proposedByAgentId") or "").strip(),
                "proposedByAgentCode": str(item.get("proposedByAgentCode") or "").strip(),
                "proposedByAgentName": str(item.get("proposedByAgentName") or "").strip(),
                "policyDelta": item.get("policyDelta") if isinstance(item.get("policyDelta"), dict) else {},
                "reason": str(item.get("reason") or "").strip(),
                "authority": item.get("authority") if isinstance(item.get("authority"), dict) else {},
                "riskLevel": str(item.get("riskLevel") or "low").strip(),
                "riskTags": list(item.get("riskTags") or []),
                "requiresApproval": bool(item.get("requiresApproval", True)),
                "approvalReason": str(item.get("approvalReason") or "").strip(),
                "createdAt": str(item.get("createdAt") or "").strip(),
                "resolvedAt": str(item.get("resolvedAt") or "").strip(),
                "resolvedBy": str(item.get("resolvedBy") or "").strip(),
                "resolutionNote": str(item.get("resolutionNote") or "").strip(),
                "appliedToolPolicyId": str(item.get("appliedToolPolicyId") or "").strip(),
                "temporaryGrant": item.get("temporaryGrant") if isinstance(item.get("temporaryGrant"), dict) else {},
                "after": item.get("after") if isinstance(item.get("after"), dict) else {},
            }
        )
    return result


def _remove_replacement_direct_session_after_failed_agent_reset(
    session_id: str,
    *,
    agent_id: str,
    fallback_active_session_id: str,
) -> None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            return
        remaining = []
        changed = False
        for item in conversations:
            if not isinstance(item, dict):
                continue
            if str(item.get("conversation_id") or "").strip() == normalized_session_id:
                changed = True
                continue
            remaining.append(item)
        if not changed:
            return
        fallback_id = str(fallback_active_session_id or "").strip()
        existing_ids = {
            str(item.get("conversation_id") or "").strip()
            for item in remaining
            if isinstance(item, dict)
        }
        if fallback_id and fallback_id in existing_ids:
            payload["active_conversation_id"] = fallback_id
        elif payload.get("active_conversation_id") == normalized_session_id:
            payload["active_conversation_id"] = next(iter(existing_ids), "")
        payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
        payload["updated_at"] = s._now_timestamp()
        payload["conversations"] = remaining
        s.save_chat_state(s.PROJECT_ROOT, payload)
    s._invalidate_session_list_cache()
    s._record_session_delete_event(
        "agent_reset_replacement_rolled_back",
        session_id=normalized_session_id,
        outcome="rolled_back",
        fields={"agentId": str(agent_id or "").strip(), "fallbackActiveSessionId": str(fallback_active_session_id or "").strip()},
    )


def _repair_child_root_agent_direct_session_bindings(
    payload: dict[str, Any],
    *,
    agent_by_id: dict[str, dict[str, Any]],
) -> bool:
    s = _service()
    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        return False
    changed = False
    for conversation in conversations:
        if not isinstance(conversation, dict):
            continue
        conversation_id = str(conversation.get("conversation_id") or "").strip()
        if not conversation_id or s._raw_conversation_session_kind(conversation) == "child":
            continue
        agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
        if not agent_id:
            continue
        agent = s._agent_from_lookup(agent_by_id, agent_id)
        if not agent:
            continue
        direct_session_id = str(agent.get("directSessionId") or "").strip()
        if not direct_session_id or direct_session_id not in s._raw_conversation_child_session_ids(conversation):
            continue
        title = str(conversation.get("title") or s.DEFAULT_CHAT_CONVERSATION_TITLE).strip() or s.DEFAULT_CHAT_CONVERSATION_TITLE
        session_workspace = str(conversation.get("workspace_path") or s._session_workspace_relative_path(conversation_id))
        repaired_agent = s.ensure_agent_for_session(
            conversation_id,
            display_name=title,
            llm_bindings=s.agent_directory_service.normalize_agent_llm_bindings(agent.get("llmBindings")),
            primary_mode=str(agent.get("primaryMode") or s.agent_directory_service.DEFAULT_AGENT_PRIMARY_MODE).strip()
            or s.agent_directory_service.DEFAULT_AGENT_PRIMARY_MODE,
            role_key=str(agent.get("roleKey") or "").strip(),
            prompt_template_id=str(agent.get("promptTemplateId") or "").strip(),
            existing_agent_id=agent_id,
            session_workspace_path=session_workspace,
        )
        agent_by_id[agent_id] = s._conversation_agent_from_state(repaired_agent)
        s._record_session_agent_child_direct_binding_repaired_event(
            conversation_id,
            agent_id=agent_id,
            previous_direct_session_id=direct_session_id,
        )
        changed = True
    return changed


def _repair_stale_running_conversation(conversation: dict[str, Any]) -> bool:
    s = _service()
    conversation_id = str(conversation.get("conversation_id") or "").strip()
    persisted_status = str(conversation.get("last_turn_status") or "").strip().lower()
    if persisted_status not in {"queued", "running", "stopping"}:
        return False
    if conversation_id and s._is_session_running(conversation_id):
        return False
    recovered_at = s._now_timestamp()
    summary = s.text_for(
        s.get_web_language(),
        zh="上一轮运行已被中断，当前会话已恢复为可继续状态。",
        en="The previous turn was interrupted. This session is ready to continue.",
    )
    if conversation.get("messages") and not s._ledger_visible_messages_for_session(conversation_id):
        conversation["legacy_messages_preserved"] = True
    conversation["runtime_notices"] = s._append_session_runtime_notice(
        conversation.get("runtime_notices") or conversation.get("runtimeNotices") or [],
        {
            "kind": "turn_recovered",
            "level": "warning",
            "message": summary,
            "timestamp": recovered_at,
            "source": "conversation.turn_recovered",
            "turnId": s._active_chat_turn_work_run_id_for_session(conversation_id),
            "previousStatus": persisted_status,
        },
    )
    conversation["last_turn_status"] = "ready"
    conversation["updated_at"] = recovered_at
    s._release_stale_chat_turn_work_run(
        session_id=conversation_id,
        finished_at=recovered_at,
        summary=summary,
    )
    return True


def _repair_stale_running_conversations(payload: dict[str, Any]) -> dict[str, Any]:
    """Clear persisted running state when no in-memory worker owns it."""
    s = _service()

    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        return payload

    changed = False
    for conversation in conversations:
        if not isinstance(conversation, dict):
            continue
        changed |= s._repair_stale_running_conversation(conversation)
    if changed:
        payload["updated_at"] = s._now_timestamp()
        s.save_chat_state(s.PROJECT_ROOT, payload)
    return payload


def _session_fixed_model_choice(session_id: str) -> dict[str, Any]:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    agent_id = s._session_agent_id_snapshot(normalized_session_id)
    agent = s.get_agent(agent_id, include_archived=False) if agent_id else None
    fallback_detail: dict[str, Any] | None = None
    if agent is None:
        fallback_detail = s.get_session_detail(normalized_session_id, message_limit=0, transcript_scope="none")
        if fallback_detail is None:
            raise s.SessionNotFoundError(f"Session not found: {normalized_session_id}")
        fallback_agent_id = str(fallback_detail.get("agentId") or "").strip()
        agent = s.get_agent(fallback_agent_id, include_archived=False) if fallback_agent_id else None
    model_ref = str(
        s.agent_dialogue_model_id(agent)
        or (fallback_detail or {}).get("dialogueModelId")
        or ""
    ).strip()
    if not model_ref:
        raise s.SessionValidationError("当前会话的 Agent 尚未绑定对话模型。")
    selected = next(
        (
            choice
            for choice in s._session_llm_model_choices()
            if model_ref
            in {
                str(choice.get("modelRef") or "").strip(),
                str(choice.get("modelId") or "").strip(),
            }
        ),
        None,
    )
    if selected is None:
        raise s.SessionValidationError(f"当前 Agent 绑定的模型不在模型库中：{model_ref}。")
    result = copy.deepcopy(selected)
    result["modelRef"] = str(result.get("modelRef") or result.get("modelId") or model_ref).strip()
    return result


def _session_prompt_cache_partition(
    *,
    session_id: str,
    agent_id: str = "",
    llm_slot: str = SESSION_LLM_SLOT_DIALOGUE,
    llm_model_id: str = "",
    model_id: str = "",
    prompt_template_id: str = "",
    prompt_snapshot_hash: str = "",
) -> str:
    """Build a short stable provider cache shard for the ordinary chat flow."""
    s = _service()

    normalized_model = str(llm_model_id or model_id or "").strip()
    normalized_agent_id = str(agent_id or "").strip()
    normalized_slot = str(llm_slot or s.SESSION_LLM_SLOT_DIALOGUE).strip() or s.SESSION_LLM_SLOT_DIALOGUE
    normalized_template = str(prompt_template_id or "").strip()
    normalized_snapshot_hash = str(prompt_snapshot_hash or "").strip()
    if normalized_agent_id:
        raw_parts = [
            s.SESSION_PROMPT_CACHE_SCOPE_AGENT_STATIC,
            normalized_agent_id,
            normalized_slot,
            normalized_model,
            normalized_template,
            normalized_snapshot_hash,
        ]
        raw = "|".join(raw_parts)
        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
        return s.developer_sandbox.sandbox_prompt_cache_partition(f"chat-agent-static-{digest}", surface="chat", project_root=s.PROJECT_ROOT)

    raw_parts = [
        s.SESSION_PROMPT_CACHE_SCOPE_SESSION_FALLBACK,
        str(session_id or "").strip(),
        normalized_slot,
        normalized_model,
    ]
    raw = "|".join(raw_parts)
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
    return s.developer_sandbox.sandbox_prompt_cache_partition(f"chat-session-{digest}", surface="chat", project_root=s.PROJECT_ROOT)


def _session_query_matches(
    item: dict[str, Any],
    *,
    query: str,
    agent_id: str,
    session_kind: str,
    state: str,
) -> bool:
    s = _service()
    if agent_id and str(item.get("agentId") or "").strip() != agent_id:
        return False
    if session_kind and str(item.get("sessionKind") or "").strip().lower() != session_kind:
        return False
    if state:
        values = {
            str(item.get("status") or "").strip().lower(),
            str(item.get("currentPhase") or "").strip().lower(),
            str(item.get("childStatus") or "").strip().lower(),
        }
        if state not in values:
            return False
    if not query:
        return True
    haystack = " ".join(
        str(item.get(key) or "")
        for key in (
            "id",
            "title",
            "taskTitle",
            "taskSummary",
            "agentId",
            "agentCode",
            "agentDisplayName",
            "dialogueModelId",
            "sessionKind",
            "status",
            "currentPhase",
        )
    ).lower()
    return query in haystack


def _session_turn_item_from_codex_cell(
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    cell: dict[str, Any],
    index: int,
    source: str,
) -> dict[str, Any] | None:
    s = _service()
    cell_kind = str(cell.get("kind") or "").strip()
    if cell_kind == "assistant_markdown":
        return None
    item_type = s._session_turn_item_type_from_codex_cell(cell_kind)
    if not item_type:
        return None
    cell_id = str(cell.get("id") or "").strip()
    suffix = cell_id or f"{item_type}-{index}"
    return s._compact_codex_record(
        {
            "id": f"{s._session_turn_item_base_id(session_id, turn_id)}-{item_type}-{s._short_hash(suffix) or index}",
            "type": item_type,
            "status": str(cell.get("status") or "completed").strip() or "completed",
            "turnId": turn_id,
            "messageId": message_id,
            "source": source,
            "sourceCellId": cell_id,
            "sourceCellKind": cell_kind,
            "title": str(cell.get("title") or "").strip(),
            "summary": str(cell.get("summary") or "").strip(),
            "text": str(cell.get("text") or "").strip(),
            "sourceItemId": str(cell.get("sourceItemId") or "").strip(),
            "operationIds": list(cell.get("operationIds") or []),
        }
    )


def _source_collection_stage_task_continuation_metadata(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Carry a stage-task contract across a bounded chain of explicit continue turns."""
    s = _service()

    for message in reversed(list(messages or [])):
        if not isinstance(message, dict) or str(message.get("role") or "").strip().lower() != "user":
            continue
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if str(metadata.get("kind") or "").strip() == s.SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND:
            team_id = str(metadata.get("teamId") or "").strip()
            task_id = str(metadata.get("sourceCollectionStageTaskId") or "").strip()
            if team_id and task_id:
                return {
                    key: copy.deepcopy(metadata[key])
                    for key in s._SOURCE_COLLECTION_STAGE_TASK_CONTINUATION_METADATA_KEYS
                    if key in metadata
                }
            return {}
        if s._is_continue_request(message.get("content")):
            continue
        return {}
    return {}


def _source_collection_stage_task_continuation_prompt(metadata: dict[str, Any]) -> str:
    s = _service()
    if not isinstance(metadata, dict) or metadata.get("sourceCollectionStageContinuation") is not True:
        return ""
    if str(metadata.get("kind") or "").strip() != s.SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND:
        return ""
    team_id = str(metadata.get("teamId") or "").strip()
    run_id = str(metadata.get("runId") or "").strip()
    stage_id = str(metadata.get("stageId") or "").strip()
    task_id = str(metadata.get("sourceCollectionStageTaskId") or "").strip()
    if not team_id or not task_id:
        return ""
    required_tools = s._source_collection_stage_task_required_tool_names({"message_metadata": metadata})
    lines = [
        "用户请求继续当前资料搜集阶段任务。请沿用现有 checklist 和已完成进度，不要新建或切换任务。",
        f"- team_id: {team_id}",
        f"- run_id: {run_id}",
        f"- stage_id: {stage_id}",
        f"- task_id: {task_id}",
    ]
    if required_tools:
        lines.append(f"- required_tools: {', '.join(required_tools)}")
    source_context_mode = str(metadata.get("sourceContextMode") or "").strip().lower()
    extraction_evidence_continuation = (
        stage_id == "extraction"
        and source_context_mode in {"evidence", "retry_evidence"}
    )
    lines.extend(
        [
            "本阶段 checklist 已由后端绑定；直接沿用阶段上下文，只补尚未完成的分页或指定缺口，不要调用通用 task_list_tool、task_create_tool 或 task_update_tool 复制清单。",
            (
                "证据补全时可使用 web_fetch_tool，但仅抓取上下文已给出的 sourceUrl 或 DOI；"
                "不要扩展检索方向、搜索新候选或抓取 file:///localhost。每页先补证并分批回写，再读取下一页；"
                "单条抓取失败才标记 needs_more_info，并继续处理其他候选。"
                if extraction_evidence_continuation
                else "续跑阶段不要调用 web_fetch_tool、research_knowledge_query_tool 或通用记忆搜索；现有证据不足的候选直接标记 needs_more_info。"
            ),
            "优先分批调用 source_collection_stage_writeback_tool 产生可累计结果，再更新 checklist；以服务端 coverageSummary 和 completionGate 为准。",
        ]
    )
    return "\n".join(lines)


def _supersede_active_session_turn_for_edit(session_id: str, *, lang: str) -> str:
    s = _service()
    controller = s._get_session_turn_control(session_id)
    if controller is None:
        controller = s._restore_missing_session_turn_control(session_id)
    turn_id = str(getattr(controller, "turn_id", "") or "").strip()
    if not turn_id:
        return ""
    reason = s.text_for(
        lang,
        zh="用户编辑并重新提交了最新消息，当前轮已被新输入取代。",
        en="The user edited and resubmitted the latest message, superseding the active turn.",
    )
    controller.request_stop(reason)
    s._cancel_queued_session_turn(session_id, turn_id)
    s._persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=turn_id,
        status="superseded",
        summary=reason,
        finished_at=s._now_timestamp(),
        updated_at=s._now_timestamp(),
    )
    s._set_session_running(session_id, False, turn_id=turn_id)
    s._clear_session_turn_control(session_id, turn_id=turn_id)
    s._clear_session_live_output(session_id, turn_id=turn_id)
    s._record_chat_next_state_signal(
        session_id=session_id,
        turn_id=turn_id,
        source="user",
        kind="user_edit_supersedes_turn",
        polarity="neutral",
        mode="directive",
        related_event_code="conversation.message_edited_resubmitted",
        summary=reason,
        metadata={"supersededTurnId": turn_id},
    )
    s._record_session_turn_lifecycle_event(
        session_id,
        "superseded_by_edit_resubmit",
        turn_id=turn_id,
        outcome="superseded",
        fields={
            "reason": "edit_resubmit",
        },
    )
    return turn_id


def _terminal_error_turn_item(items: Any) -> dict[str, Any] | None:
    s = _service()
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        if (
            str(item.get("type") or item.get("kind") or "").strip() == "error"
            and item.get("terminal") is True
            and item.get("provisional") is not True
        ):
            return item
    return None


def append_session_assistant_artifact_message(
    session_id: str,
    content: str,
    *,
    metadata: dict[str, Any] | None = None,
    tool_calls: list[Any] | None = None,
) -> dict[str, Any]:
    """Append an assistant artifact message and notify session subscribers."""
    s = _service()

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise s.SessionValidationError("Session id is required for artifact messages.")
    status = str((metadata or {}).get("status") or "observed").strip() or "observed"
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            raise s.SessionNotFoundError(f"Session not found: {normalized_session_id}")
        assistant_entry = s._make_chat_message(
            "assistant",
            content,
            tool_calls or [],
            metadata=metadata,
        )
        conversation.pop("messages", None)
        conversation["updated_at"] = assistant_entry["timestamp"]
        payload["updated_at"] = assistant_entry["timestamp"]
        s.save_chat_state(s.PROJECT_ROOT, payload)
    turn_id = str((metadata or {}).get("turnId") or (metadata or {}).get("turn_id") or f"artifact:{assistant_entry['timestamp']}").strip()
    s._append_session_conversation_event(
        normalized_session_id,
        turn_id,
        s.EVENT_ASSISTANT_MESSAGE,
        status=status,
        payload={
            "content": content,
            "toolCalls": s._normalize_message_tool_calls(tool_calls or []),
            "metadata": metadata or {},
        },
        source="s.append_session_assistant_artifact_message",
    )

    s._record_session_cycle_message(
        normalized_session_id,
        assistant_entry,
        event="assistant_artifact",
        status=status,
    )
    s._publish_session_detail_snapshot(normalized_session_id)
    normalized = s._normalize_messages(normalized_session_id, [assistant_entry])
    return normalized[0] if normalized else assistant_entry


def prewarm_session_list_cache(*, reason: str = "startup") -> dict[str, Any]:
    """Build the lightweight session list cache before the first user query."""
    s = _service()

    global _SESSION_LIST_PREWARM_INFLIGHT
    normalized_reason = s.trim_lines(reason, max_lines=1) or "startup"
    started_at = s._perf_counter()
    with s._SESSION_LIST_PREWARM_LOCK:
        if s._SESSION_LIST_PREWARM_INFLIGHT:
            return {
                "status": "skipped",
                "reason": normalized_reason,
                "skipReason": "inflight",
                "durationMs": s._elapsed_ms(started_at),
            }
        s._SESSION_LIST_PREWARM_INFLIGHT = True

    try:
        sessions = s.list_sessions()
        duration_ms = s._elapsed_ms(started_at)
        result = {
            "status": "completed",
            "reason": normalized_reason,
            "sessionCount": len(sessions),
            "durationMs": duration_ms,
        }
        s._record_session_list_prewarm_event(
            status="completed",
            reason=normalized_reason,
            elapsed_ms=duration_ms,
            session_count=len(sessions),
        )
        return result
    except Exception as exc:
        duration_ms = s._elapsed_ms(started_at)
        s._record_session_list_prewarm_event(
            status="failed",
            reason=normalized_reason,
            elapsed_ms=duration_ms,
            error_type=type(exc).__name__,
            error_message=s.trim_lines(str(exc), max_lines=2),
        )
        return {
            "status": "failed",
            "reason": normalized_reason,
            "durationMs": duration_ms,
            "errorType": type(exc).__name__,
        }
    finally:
        with s._SESSION_LIST_PREWARM_LOCK:
            s._SESSION_LIST_PREWARM_INFLIGHT = False


def update_chat_session(
    session_id: str,
    *,
    title: str | None = None,
    agent_id: str | None = None,
) -> dict:
    """Persist user-facing chat session settings."""
    s = _service()

    lang = s.get_web_language()
    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))

    normalized_title: str | None = None
    if title is not None:
        normalized_title = s.trim_lines(title or "", max_lines=1).strip()
        if not normalized_title:
            raise s.SessionValidationError(s.text_for(lang, zh="请输入会话名称。", en="Enter a session name."))
        if len(normalized_title) > 120:
            normalized_title = normalized_title[:120].rstrip()

    normalized_agent_id: str | None = None
    selected_agent: dict[str, Any] | None = None
    if agent_id is not None:
        normalized_agent_id = str(agent_id or "").strip()
        if not normalized_agent_id:
            raise s.SessionValidationError(s.text_for(lang, zh="请选择会话 Agent。", en="Choose a session Agent."))
        selected_agent = s.get_agent(normalized_agent_id, include_archived=False)
        if not selected_agent:
            raise s.SessionValidationError(s.text_for(lang, zh=f"未找到会话 Agent：{normalized_agent_id}", en=f"Session Agent not found: {normalized_agent_id}"))

    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, conversation_id)
        if conversation is None:
            raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
        s._ensure_session_mutable(conversation_id, conversation=conversation)
        changed = False
        changed = s._ensure_conversation_workspace_metadata(conversation) or changed
        changed = s._ensure_conversation_agent_metadata(conversation) or changed

        if normalized_title is not None and conversation.get("title") != normalized_title:
            conversation["title"] = normalized_title
            changed = True
        if selected_agent is not None and normalized_agent_id is not None:
            s._bind_conversation_to_agent_instance(
                conversation,
                selected_agent,
                session_id=conversation_id,
                source="agent_id",
            )
            changed = True
        changed = s._ensure_conversation_agent_metadata(conversation) or changed
        if changed:
            payload["updated_at"] = s._now_timestamp()
            s.save_chat_state(s.PROJECT_ROOT, payload)

    if changed:
        s._invalidate_session_list_cache()
        s._publish_session_detail_snapshot(conversation_id)
    return s.get_session_detail(conversation_id) or {}


def update_chat_session_title(session_id: str, title: str) -> dict:
    """Persist a user-facing chat session title."""
    s = _service()

    lang = s.get_web_language()
    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))

    normalized_title = s.trim_lines(title or "", max_lines=1).strip()
    if not normalized_title:
        raise s.SessionValidationError(s.text_for(lang, zh="请输入会话名称。", en="Enter a session name."))
    if len(normalized_title) > 120:
        normalized_title = normalized_title[:120].rstrip()

    changed = False
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, conversation_id)
        if conversation is None:
            raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
        s._ensure_session_mutable(conversation_id, conversation=conversation)

        session_kind = str(conversation.get("session_kind") or conversation.get("sessionKind") or "main").strip().lower()
        agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
        if session_kind == "child":
            if str(conversation.get("task_title") or conversation.get("taskTitle") or "").strip() != normalized_title:
                conversation["task_title"] = normalized_title
                conversation["taskTitle"] = normalized_title
                conversation["title"] = normalized_title
                conversation["updated_at"] = s._now_timestamp()
                payload["updated_at"] = str(conversation.get("updated_at") or s._now_timestamp())
                s.save_chat_state(s.PROJECT_ROOT, payload)
                changed = True
        elif agent_id:
            if str(conversation.get("title") or "").strip() != normalized_title:
                conversation["title"] = normalized_title
                conversation["updated_at"] = s._now_timestamp()
                payload["updated_at"] = str(conversation.get("updated_at") or s._now_timestamp())
                s.save_chat_state(s.PROJECT_ROOT, payload)
                changed = True
        elif str(conversation.get("title") or "").strip() != normalized_title:
            conversation["title"] = normalized_title
            conversation["updated_at"] = s._now_timestamp()
            payload["updated_at"] = str(conversation.get("updated_at") or s._now_timestamp())
            s.save_chat_state(s.PROJECT_ROOT, payload)
            changed = True

    target = s._load_conversation_detail_target(
        conversation_id,
        repair=False,
    )
    detail = s._build_lightweight_session_detail(target) if target is not None else {}
    if changed:
        s._invalidate_session_list_cache()
        if detail:
            s._publish_session_detail_snapshot(conversation_id, detail=detail)
        else:
            s._publish_session_detail_snapshot(conversation_id)
        try:
            s.record_runtime_scene_event(
                "conversation",
                "title",
                "conversation.title.updated",
                level="info",
                outcome="updated",
                message="Session title updated without changing the owning Agent responsibility.",
                fields={
                    "sessionId": conversation_id,
                    "agentId": agent_id,
                    "sessionKind": session_kind,
                    "agentIdentityChanged": False,
                    "source": "session_record",
                },
                lifecycle=True,
            )
        except Exception as exc:
            s._debug_logger.warning(
                f"runtime scene session title log skipped: {type(exc).__name__}: {exc}",
                tag="LOGS",
            )
    return detail


def update_session_reasoning_effort(
    session_id: str,
    *,
    reasoning_effort: str,
) -> dict[str, Any]:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    selected = s._session_fixed_model_choice(normalized_session_id)
    supported_efforts = {
        s.normalize_reasoning_effort(value)
        for value in list(selected.get("reasoningEffortValues") or [])
        if s.normalize_reasoning_effort(value)
    }
    normalized_effort = s.normalize_reasoning_effort(reasoning_effort)
    if normalized_effort not in supported_efforts:
        raise s.SessionValidationError(
            f"模型 {selected.get('label') or selected.get('modelId')} 不支持推理强度 {normalized_effort or '-'}。"
        )
    with s._CHAT_STATE_LOCK:
        if s._is_session_running(normalized_session_id):
            raise s.SessionBusyError("会话运行中，不能切换推理强度。")
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            raise s.SessionNotFoundError(f"Session not found: {normalized_session_id}")
        s._ensure_session_mutable(
            normalized_session_id,
            conversation=conversation,
        )
        conversation["reasoning_effort"] = normalized_effort
        conversation["updated_at"] = s._now_timestamp()
        s.save_chat_state(s.PROJECT_ROOT, payload)
    s._invalidate_session_list_cache()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "reasoning_effort",
            "conversation.reasoning_effort.updated",
            level="info",
            outcome="updated",
            message="Session reasoning effort updated without changing the Agent model binding.",
            fields={
                "sessionId": normalized_session_id,
                "modelRef": str(selected.get("modelRef") or selected.get("modelId") or "").strip(),
                "reasoningEffortRequested": normalized_effort,
                "reasoningEffortAdapter": str(selected.get("reasoningAdapter") or "none").strip(),
                "source": "session_record",
            },
            lifecycle=True,
        )
    except Exception as exc:
        s._debug_logger.warning(
            f"runtime scene reasoning effort log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )
    return s.get_session_llm_options(normalized_session_id)
