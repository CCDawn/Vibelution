"""Session residual: agent/team/workspace, running state, codex/SC bridges.

Claim scope: agent identity/context, supervised workspace overrides, session
mutable/running state, conversation event append helpers, codex terminal
bridges, and source-collection stage-task metadata still on the facade.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import stat
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


def _service():
    from core.web.services import session_service

    return session_service


def _active_chat_turn_id_for_session(session_id: str) -> str:
    s = _service()
    active = s._WORK_RUN_STORE.load_active_snapshot("chat_turn")
    if not isinstance(active, dict):
        return ""
    if str(active.get("sessionId") or "").strip() != str(session_id or "").strip():
        return ""
    status = str(active.get("status") or active.get("currentPhase") or "").strip().lower()
    if status not in {"queued", "running", "stopping", "paused"}:
        return ""
    return str(active.get("runId") or "").strip()


def _active_skill_contract_from_conversation(conversation: Any) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(conversation, dict):
        return None
    return s.refresh_active_skill_contract_status(
        conversation.get("active_skill_contract") or conversation.get("activeSkillContract")
    )


def _active_skill_contract_from_invocation(
    invocation: Any,
    *,
    turn_id: str = "",
) -> dict[str, Any] | None:
    s = _service()
    contract = s.build_active_skill_contract(
        invocation,
        activated_at=s._now_timestamp(),
        activated_turn_id=turn_id,
        scope="task",
    )
    return contract


def _active_skill_runtime_context_from_contract(contract: Any) -> str:
    s = _service()
    return s.build_active_skill_runtime_context(contract)


def _active_task_context_chars(active_task: Any) -> int:
    s = _service()
    task = s._normalize_session_active_task(active_task)
    if not isinstance(task, dict):
        return 0
    if not s._is_task_tool_backed_active_task(task):
        return 0
    parts = [
        task.get("title"),
        task.get("goal"),
        task.get("latest_summary"),
        task.get("next_action"),
        " ".join(str(item) for item in list(task.get("read_files") or [])[:8]),
        " ".join(str(item) for item in list(task.get("changed_files") or [])[:8]),
    ]
    return len("\n".join(str(item or "") for item in parts if str(item or "").strip()))


def _agent_avatar_path(agent: dict[str, Any], metadata: dict[str, Any] | None = None) -> str:
    s = _service()
    source = metadata if isinstance(metadata, dict) else agent.get("metadata")
    meta = source if isinstance(source, dict) else {}
    raw_path = str(meta.get("avatarImagePath") or "").strip()
    filename = s.agent_directory_service.agent_avatar_filename(raw_path)
    if not filename:
        return ""
    return str(s.agent_directory_service.AGENT_AVATAR_RELATIVE_DIR / filename)


def _agent_context_manifest_segments(
    runtime_context_segments: list[dict[str, Any]] | None,
    *,
    dynamic_runtime_context_included: bool,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    s = _service()
    segments: list[dict[str, Any]] = []
    previews: dict[str, str] = {}
    for index, item in enumerate(list(runtime_context_segments or [])):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        block = str(item.get("block") or "").strip()
        if not key or not block:
            continue
        placement = str(item.get("placement") or "").strip()
        is_static = placement == "cache_prefix"
        is_dynamic = placement == "volatile_turn"
        if not is_static and not is_dynamic:
            continue
        included = bool(is_static or (is_dynamic and dynamic_runtime_context_included))
        segment = s._context_segment(
            key,
            s._agent_context_segment_label(key),
            content=block,
            chars=s._coerce_nonnegative_int(item.get("chars") or len(block)),
            item_count=1,
            status="included" if included else "omitted",
            source="context_engine",
            description=(
                "ContextEngine prompt segment seeded into the stable system prefix."
                if is_static
                else "ContextEngine turn-local prompt segment."
            ),
            kind=s._agent_context_prompt_category(key),
            lifecycle="stable" if is_static else "turn",
            authority=82 if is_static else 58,
            volatility=15 if is_static else 88,
            relevance=76,
            placement="system_prefix" if is_static else "before_current_user",
            cache_policy="cacheable" if is_static else "volatile",
            retention="persist" if is_static else "current_turn_only",
            included_in_model_input=included,
            content_hash=str(item.get("hash") or "").strip(),
        )
        segment["promptCategory"] = s._agent_context_prompt_category(key)
        segment["segmentKind"] = "prompt_source"
        segment["accuracy"] = "manifest"
        segment["order"] = index
        segments.append(segment)
        preview = s._compact_preview_text(block, max_lines=3, max_chars=240)
        if preview:
            previews[key] = preview
    return segments, previews


def _agent_context_prompt_category(key: str) -> str:
    s = _service()
    normalized = str(key or "").strip()
    return s._AGENT_CONTEXT_SEGMENT_CATEGORIES.get(normalized, "agent_context")


def _agent_created_by(agent: dict[str, Any], metadata: dict[str, Any]) -> str:
    s = _service()
    creation_spec = metadata.get("creationSpec") if isinstance(metadata.get("creationSpec"), dict) else {}
    return str(agent.get("createdBy") or creation_spec.get("source") or "").strip()


def _agent_direct_session_collision_owner_sort_key(agent: dict[str, Any]) -> tuple[int, str, str]:
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    previous_direct_session_id = str(metadata.get("previousDirectSessionId") or "").strip()
    return (
        1 if previous_direct_session_id else 0,
        str(agent.get("updatedAt") or agent.get("createdAt") or ""),
        str(agent.get("agentId") or ""),
    )


def _agent_direct_session_collision_repair_sort_key(agent: dict[str, Any]) -> tuple[str, str]:
    s = _service()
    return (
        str(agent.get("updatedAt") or agent.get("createdAt") or ""),
        str(agent.get("agentId") or ""),
    )


def _agent_directory_session_stub_for_id(
    session_id: str,
    *,
    agent_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    agents = list((agent_by_id if agent_by_id is not None else s._agent_lookup_for_conversations()).values())
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        if str(agent.get("status") or "active").strip().lower() == "archived":
            continue
        if str(agent.get("directSessionId") or "").strip() != normalized_session_id:
            continue
        return s._agent_directory_conversation_record(agent, session_id=normalized_session_id)
    return None


def _agent_for_direct_session(session_id: str) -> dict[str, Any] | None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    try:
        agents = s.agent_directory_service.list_agents(include_archived=False)
    except Exception:
        return None
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        if str(agent.get("directSessionId") or "").strip() == normalized_session_id:
            return dict(agent)
    return None


def _agent_message_tool_result_succeeded(payload: dict[str, Any]) -> bool:
    s = _service()
    if not isinstance(payload, dict) or not payload:
        return False
    if not s.infer_tool_business_success(payload):
        return False
    return bool(str(payload.get("targetAgentId") or "").strip())


def _agent_message_tool_sent_to_source(
    tool_calls: list[dict[str, Any]],
    *,
    source_agent_id: str,
) -> bool:
    s = _service()
    normalized_source_agent_id = str(source_agent_id or "").strip()
    if not normalized_source_agent_id:
        return False
    for tool_call in list(tool_calls or []):
        if not isinstance(tool_call, dict):
            continue
        if str(tool_call.get("name") or "").strip() != "agent_message_tool":
            continue
        result_payload = s._parse_agent_message_tool_result(tool_call)
        if not s._agent_message_tool_result_succeeded(result_payload):
            continue
        if str(result_payload.get("targetAgentId") or "").strip() == normalized_source_agent_id:
            return True
    return False


def _agent_needs_ai_search_team_marker(agent: dict[str, Any], metadata: dict[str, Any]) -> bool:
    s = _service()
    role_key = str(agent.get("roleKey") or metadata.get("aiSearchRole") or "").strip()
    return (
        s._agent_created_by(agent, metadata) == "ai_search_team"
        or bool(str(metadata.get("aiSearchRole") or "").strip())
        or role_key.startswith("ai_search_")
    )


def _agent_team_identity(agent: dict[str, Any], metadata: dict[str, Any]) -> dict[str, str]:
    s = _service()
    generic_team_id = str(metadata.get("teamId") or "").strip()
    generic_team_name = str(metadata.get("teamName") or "").strip()
    if generic_team_id:
        return {"teamId": generic_team_id, "teamName": generic_team_name}

    challenge_team_id = str(metadata.get("challengeCupTeamId") or "").strip()
    challenge_team_name = str(metadata.get("challengeCupTeamName") or "").strip()
    knowledge_team_id = str(metadata.get("knowledgeExpansionTeamId") or "").strip()
    knowledge_team_name = str(metadata.get("knowledgeExpansionTeamName") or "").strip()
    role_text = " ".join(
        str(value or "").strip()
        for value in (
            agent.get("roleKey"),
            metadata.get("researchTeamRole"),
            metadata.get("researchTeamRoleKey"),
            metadata.get("challengeCupTeamRole"),
            metadata.get("challengeCupTeamRoleKey"),
            metadata.get("knowledgeExpansionTeamRole"),
            metadata.get("knowledgeExpansionTeamRoleKey"),
        )
        if str(value or "").strip()
    ).lower()

    if knowledge_team_id and ("knowledge" in role_text or not challenge_team_id):
        return {"teamId": knowledge_team_id, "teamName": knowledge_team_name}
    if challenge_team_id:
        return {"teamId": challenge_team_id, "teamName": challenge_team_name}
    if knowledge_team_id:
        return {"teamId": knowledge_team_id, "teamName": knowledge_team_name}
    return {"teamId": "", "teamName": ""}


def _ai_search_team_id_for_repair() -> str:
    s = _service()
    try:
        from . import team_service

        return str(team_service.AI_SEARCH_TEAM_ID or "").strip() or "ai-search-team"
    except Exception:
        return "ai-search-team"


def _append_session_conversation_event(
    session_id: str,
    turn_id: str,
    event_type: str,
    *,
    status: str = "",
    payload: dict[str, Any] | None = None,
    source: str = "session_service",
    visible_in_model: bool = True,
    projection_kind: str = "",
    tool_call_id: str = "",
    correlation_id: str = "",
    source_kind: str = "",
) -> None:
    s = _service()
    s._journal_bridge.append_session_conversation_event(
        session_id,
        turn_id,
        event_type,
        status=status,
        payload=payload,
        source=source,
        visible_in_model=visible_in_model,
        projection_kind=projection_kind,
        tool_call_id=tool_call_id,
        correlation_id=correlation_id,
        source_kind=source_kind,
        project_root=s.PROJECT_ROOT,
    )


def _append_session_runtime_notice(items: Any, notice: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
    return s._normalize_session_runtime_notices([*list(items or []), notice])


def _archived_agent_for_direct_session(session_id: str) -> dict[str, Any] | None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    try:
        agents = s.agent_directory_service.list_agents(include_archived=True)
    except Exception:
        return None
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        if str(agent.get("directSessionId") or "").strip() != normalized_session_id:
            continue
        if str(agent.get("status") or "active").strip().lower() == "archived":
            return agent
    return None


def _assistant_projection_text_key(value: Any) -> str:
    s = _service()
    return "".join(str(value or "").split())


def _build_lightweight_session_detail(conversation: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    summary = s._build_session_summary(conversation, hydrate_agent=False)
    return s._build_session_detail_from_summary(conversation, summary, hydrate_agent=False)


def _chat_contract_blocks_unexecuted_validation(contract: dict[str, Any]) -> bool:
    s = _service()
    if not isinstance(contract, dict):
        return False
    if str(contract.get("outcome") or "").strip().lower() != "blocked":
        return False
    text = "\n".join(
        str(contract.get(key) or "")
        for key in ("blocked_reason", "verification_summary")
        if contract.get(key)
    )
    return "验证尚未执行" in text or "跨平台检查拦截" in text or "[跨平台警告]" in text


def _chat_result_outcome_source(result: dict[str, Any]) -> str:
    s = _service()
    metadata = dict(result.get("metadata") or {}) if isinstance(result.get("metadata"), dict) else {}
    source = str(metadata.get("chat_contract_outcome_source") or result.get("outcome_source") or "").strip().lower()
    if source in {"explicit", "inferred"}:
        return source
    return "explicit" if (result.get("outcome") or result.get("task_outcome")) else ""


def _check_chat_turn_lease_decision(leases: list[str]):
    s = _service()
    active_runs = [
        snapshot
        for snapshot in (
            s.load_evolution_active_run_snapshot("self"),
            s.load_evolution_active_run_snapshot("supervised"),
        )
        if isinstance(snapshot, dict)
    ]
    return s.check_lease_conflicts(
        s.WorkRunLeaseRequest(run_kind="chat_turn", leases=leases),
        active_runs,
    )


def _clear_session_live_output(session_id: str, *, turn_id: str = "") -> None:
    s = _service()
    if s._clear_session_live_output_memory(session_id, turn_id=turn_id):
        s._delete_session_live_output_checkpoint(session_id)


def _clear_session_turn_control(session_id: str, *, turn_id: str = "") -> None:
    s = _service()
    with s._SESSION_TURN_CONTROLS_LOCK:
        current = s._SESSION_TURN_CONTROLS.get(session_id)
        if not turn_id or (current is not None and current.turn_id == turn_id):
            s._SESSION_TURN_CONTROLS.pop(session_id, None)


def _close_previous_running_status_events(events: Any, current_name: str) -> list[dict[str, Any]]:
    s = _service()
    normalized_current_name = str(current_name or "").strip()
    normalized_events: list[dict[str, Any]] = []
    for item in s._normalize_message_feedback_events(events):
        entry = dict(item)
        if (
            str(entry.get("kind") or "").strip() == "status"
            and str(entry.get("name") or "").strip() != normalized_current_name
            and str(entry.get("status") or "").strip().lower() in {"running", "pending"}
        ):
            entry["status"] = "done"
        normalized_events.append(entry)
    return normalized_events


def _codex_cell_default_title(kind: str) -> str:
    s = _service()
    if kind == "reasoning_summary":
        return "Reasoning"
    if kind == "status":
        return "Status"
    if kind == "error_notice":
        return "Failed"
    return "Tool call"


def _codex_cell_kind(kind: str, status: str) -> str:
    s = _service()
    if status == "failed":
        return "error_notice"
    if kind == "thought":
        return "reasoning_summary"
    if kind == "status":
        return "status"
    return "tool_call"


def _codex_cell_tone(status: str) -> str:
    s = _service()
    if status == "failed":
        return "error"
    if status == "degraded":
        return "warning"
    if status in {"running", "pending"}:
        return "running"
    return "neutral"


def _codex_exit_code(source: dict[str, Any]) -> int | float | None:
    s = _service()
    value = s._coerce_tool_number(s._first_present_mapping_value(source, ("exitCode", "exit_code")))
    return value


def _codex_lifecycle_status(value: Any) -> str:
    s = _service()
    normalized = s._normalize_tool_call_status(value, default="done")
    if normalized in {"failed", "error", "blocked", "cancelled", "timeout", "timed_out"}:
        return "failed"
    if normalized in {"degraded", "fallback", "partial", "recovered", "unavailable"}:
        return "degraded"
    if normalized in {"queued", "pending", "submitted"}:
        return "pending"
    if normalized in {"running", "thinking", "tooling", "answering", "in_progress"}:
        return "running"
    return "completed"


def _codex_operation_id(message_id: str, source: dict[str, Any], sequence: int) -> str:
    s = _service()
    raw_id = str(
        source.get("id")
        or source.get("toolCallId")
        or source.get("tool_call_id")
        or source.get("taskId")
        or ""
    ).strip()
    if raw_id:
        return raw_id
    normalized_sequence = s._coerce_nonnegative_int(source.get("sequence") or source.get("_sequence") or sequence)
    if normalized_sequence > 0:
        return f"{message_id}-feedback-{normalized_sequence}"
    name = str(source.get("name") or "operation").strip() or "operation"
    return f"{message_id}-{name}-{sequence}"


def _codex_operation_summary(source: dict[str, Any], *, failed: bool) -> str:
    s = _service()
    if failed:
        return s._trim_tool_detail_text(
            source.get("error") or source.get("summary") or source.get("resultPreview") or "",
            max_chars=1200,
            max_lines=10,
        )
    return s._trim_tool_detail_text(
        source.get("summary") or source.get("resultPreview") or source.get("content") or "",
        max_chars=1200,
        max_lines=10,
    )


def _codex_rollout_event(
    tool_call: dict[str, Any],
    kind: str,
    status: str,
    terminal_operation: dict[str, Any] | None,
) -> dict[str, Any]:
    s = _service()
    result = terminal_operation.get("result") if isinstance(terminal_operation, dict) else {}
    return s._compact_codex_record(
        {
            "id": f"{tool_call.get('rawOperationId')}-{s._codex_rollout_event_suffix(kind)}",
            "kind": kind,
            "operationId": tool_call.get("rawOperationId"),
            "toolCallId": tool_call.get("toolCallId"),
            "terminalOperationId": (terminal_operation or {}).get("operationId"),
            "terminalId": (terminal_operation or {}).get("terminalId"),
            "sequence": tool_call.get("sequence"),
            "timestamp": tool_call.get("timestamp"),
            "status": status,
            "title": tool_call.get("title"),
            "summary": tool_call.get("summary"),
            "runtimeKind": tool_call.get("runtimeKind") or "tool",
            "rawToolName": tool_call.get("rawToolName"),
            "durationSeconds": (terminal_operation or {}).get("durationSeconds"),
            "exitCode": result.get("exitCode") if isinstance(result, dict) else None,
            "timedOut": result.get("timedOut") if isinstance(result, dict) else None,
            "tracePath": (terminal_operation or {}).get("tracePath") or tool_call.get("tracePath"),
            "error": tool_call.get("error") or (result.get("stderr") if isinstance(result, dict) else ""),
            "modelObservationSource": "DirectToolCall" if terminal_operation else None,
        }
    )


def _codex_rollout_event_suffix(kind: str) -> str:
    s = _service()
    return {
        "ToolCallStarted": "tool-call-started",
        "RuntimeStarted": "runtime-started",
        "RuntimeEnded": "runtime-ended",
        "ToolCallEnded": "tool-call-ended",
    }.get(kind, kind)


def _codex_rollout_events_from_lifecycle(
    tool_call: dict[str, Any],
    terminal_operation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    s = _service()
    status = s._codex_lifecycle_status(tool_call.get("status"))
    start_status = "pending" if status == "pending" else "running"
    events = [
        s._codex_rollout_event(tool_call, "ToolCallStarted", start_status, terminal_operation),
        s._codex_rollout_event(tool_call, "RuntimeStarted", start_status, terminal_operation),
    ]
    if status in {"pending", "running"}:
        return events
    events.extend(
        [
            s._codex_rollout_event(tool_call, "RuntimeEnded", status, terminal_operation),
            s._codex_rollout_event(tool_call, "ToolCallEnded", status, terminal_operation),
        ]
    )
    return events


def _codex_runtime_kind(source: dict[str, Any]) -> str:
    s = _service()
    name = str(source.get("name") or source.get("label") or "").strip().lower()
    if str(source.get("terminalSessionId") or "").strip() or name in {
        "cli_tool",
        "exec_command",
        "write_stdin",
        "cli_agent_run_tool",
    }:
        return "terminal"
    return "tool"


def _codex_terminal_operation_kind(source: dict[str, Any]) -> str:
    s = _service()
    name = str(source.get("name") or source.get("label") or "").strip().lower()
    return "WriteStdin" if name == "write_stdin" else "ExecCommand"


def _codex_terminal_request(source: dict[str, Any], summary: str, title: str) -> dict[str, Any]:
    s = _service()
    arguments = source.get("arguments") if isinstance(source.get("arguments"), dict) else {}
    display_command = s._trim_tool_detail_text(
        arguments.get("cmd")
        or arguments.get("command")
        or source.get("resultPreview")
        or summary
        or title,
        max_chars=1200,
        max_lines=4,
    )
    command = arguments.get("command") or arguments.get("cmd")
    if isinstance(command, list):
        command_value = [
            s._trim_tool_detail_text(item, max_chars=240, max_lines=1)
            for item in command[:12]
        ]
    elif display_command:
        command_value = [display_command]
    else:
        command_value = []
    return s._compact_codex_record(
        {
            "displayCommand": display_command,
            "command": command_value,
            "cwd": s._trim_tool_detail_text(arguments.get("cwd") or "", max_chars=420, max_lines=1),
        }
    )


def _codex_terminal_result(source: dict[str, Any], summary: str, status: str) -> dict[str, Any]:
    s = _service()
    result_preview = s._trim_tool_detail_text(
        source.get("formattedOutput") or source.get("resultPreview") or "",
        max_chars=1200,
        max_lines=10,
    )
    error = s._trim_tool_detail_text(source.get("error") or "", max_chars=1200, max_lines=10)
    return s._compact_codex_record(
        {
            "exitCode": s._codex_exit_code(source),
            "stdout": "" if status == "failed" else (result_preview or summary),
            "stderr": error if error else (summary if status == "failed" else ""),
            "formattedOutput": error or result_preview or summary,
            "timedOut": bool(source.get("timedOut")) if "timedOut" in source else None,
        }
    )


def _codex_terminal_session_key(source: dict[str, Any]) -> str:
    s = _service()
    explicit = str(source.get("terminalSessionId") or source.get("terminal_session_id") or "").strip()
    if explicit:
        return explicit
    arguments = source.get("arguments") if isinstance(source.get("arguments"), dict) else {}
    for key in ("session_id", "sessionId", "terminal_id", "terminalId"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return ""


def _coerce_confidence(value: Any) -> float:
    s = _service()
    try:
        return max(0.0, min(float(value or 0.0), 1.0))
    except (TypeError, ValueError):
        return 0.0


def _coerce_nonnegative_int(value: Any) -> int:
    s = _service()
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _coerce_session_detail_before_index(value: Any) -> int:
    s = _service()
    return max(0, s._coerce_nonnegative_int(value))


def _coerce_session_detail_message_limit(value: Any) -> int | None:
    s = _service()
    if value is None or str(value).strip() == "":
        return None
    limit = s._coerce_nonnegative_int(value)
    if limit <= 0:
        return None
    return min(limit, s._SESSION_DETAIL_MESSAGE_WINDOW_MAX_LIMIT)


def _coerce_session_query_limit(value: Any) -> int:
    s = _service()
    limit = s._coerce_nonnegative_int(value)
    if limit <= 0:
        return s._SESSION_QUERY_DEFAULT_LIMIT
    return min(limit, s._SESSION_QUERY_MAX_LIMIT)


def _coerce_tool_number(value: Any) -> int | float | None:
    s = _service()
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value == value and value not in {float("inf"), float("-inf")}:
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = float(value)
        except ValueError:
            return None
        if parsed != parsed or parsed in {float("inf"), float("-inf")}:
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _compact_codex_record(record: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    return {
        key: value
        for key, value in record.items()
        if value is not None and value != "" and value != [] and value != {}
    }


def _context_prompt_category(key: str) -> str:
    s = _service()
    normalized = str(key or "").strip()
    if normalized in s._AGENT_CONTEXT_SEGMENT_CATEGORIES:
        return s._agent_context_prompt_category(normalized)
    return s._CONTEXT_PROMPT_CATEGORIES.get(normalized, normalized or "context")


def _conversation_hidden_from_index(
    raw: dict[str, Any],
    agent: dict[str, Any] | None,
    *,
    hidden_team_member_agent_ids: set[str] | None = None,
) -> bool:
    s = _service()
    classification = s._conversation_index_classification(
        raw,
        agent,
        hidden_team_member_agent_ids=hidden_team_member_agent_ids,
    )
    kind = str(classification.get("kind") or "").strip()
    if kind == s.agent_directory_service.CONVERSATION_INDEX_KIND_INVALID:
        return False
    if kind == s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
        return True
    return bool(raw.get("hidden_from_index") or raw.get("hiddenFromIndex"))


def _conversation_is_read_only(conversation: dict[str, Any]) -> bool:
    s = _service()
    archive_state = conversation.get("archive_state") or conversation.get(
        "archiveState"
    )
    archived = (
        isinstance(archive_state, dict)
        and str(archive_state.get("status") or "").strip().lower() == "archived"
    )
    return bool(
        conversation.get("read_only")
        or conversation.get("readOnly")
        or archived
    )


def _conversation_turn_log_path(session_id: str, turn_id: str, file_name: str) -> str:
    s = _service()
    session_token = s._safe_session_workspace_token(session_id)
    turn_token = s._safe_session_workspace_token(turn_id or "turn")
    file_token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(file_name or "trace_events.jsonl")).strip("._-")
    return f"sessions/{session_token}/turns/{turn_token}/{file_token or 'trace_events.jsonl'}"


def _create_session_turn_control(session_id: str, *, turn_id: str = "") -> Any:
    s = _service()
    with s._SESSION_TURN_CONTROLS_LOCK:
        control = s.SessionTurnControl(
            session_id=session_id,
            turn_id=str(turn_id or "").strip() or f"{session_id}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        )
        s._SESSION_TURN_CONTROLS[session_id] = control
        return control


def _current_session_live_context_composition(session_id: str) -> dict[str, Any] | None:
    s = _service()
    with s._SESSION_LIVE_OUTPUTS_LOCK:
        state = s._SESSION_LIVE_OUTPUTS.get(session_id)
        if state is None:
            return None
        return s._normalize_session_context_composition(state.context_composition)


def _current_session_turn_id(session_id: str) -> str:
    s = _service()
    with s._RUNNING_SESSIONS_LOCK:
        return str(s._SESSION_ACTIVE_TURN_IDS.get(session_id) or "").strip()


def _default_session_dialogue_model_id() -> str:
    s = _service()
    try:
        config = s.get_config()
    except Exception:
        return ""
    try:
        profile = config.llm.get_profile(profile_id=s.DEFAULT_SESSION_AGENT_PROFILE_ID)
        model_id, _entry = config.llm.get_model_library_entry_for_profile(profile)
        if str(model_id or "").strip():
            return str(model_id or "").strip()
    except Exception:
        pass
    model_library = getattr(config.llm, "model_library", {}) or {}
    if isinstance(model_library, dict):
        items = model_library.items()
    else:
        items = []
    for model_id, item in items:
        if not isinstance(item, dict):
            continue
        model = str(item.get("model") or "").strip()
        if model:
            return str(model_id or "").strip()
    return ""


def _elapsed_ms(started_at: float) -> int:
    s = _service()
    return max(0, int(round((s._perf_counter() - started_at) * 1000)))


def _elapsed_ms_between(started_at: Any, ended_at: float | None = None) -> int:
    s = _service()
    try:
        start_value = float(started_at)
    except (TypeError, ValueError):
        return 0
    end_value = s._perf_counter() if ended_at is None else float(ended_at)
    return max(0, int(round((end_value - start_value) * 1000)))


def _empty_codex_tool_lifecycle_projection() -> dict[str, list[dict[str, Any]]]:
    s = _service()
    return {
        "toolCalls": [],
        "terminalOperations": [],
        "terminalSessions": [],
        "modelObservations": [],
    }


def _ensure_session_mutable(
    session_id: str,
    *,
    conversation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise s.SessionNotFoundError("Session not found")
    target = conversation
    if target is None:
        with s._CHAT_STATE_LOCK:
            payload = s.load_chat_state(s.PROJECT_ROOT)
            target = s._find_conversation_entry(payload, normalized_session_id)
    if target is None:
        raise s.SessionNotFoundError(f"Session not found: {normalized_session_id}")
    if s._conversation_is_read_only(target):
        raise s.SessionValidationError(
            s.text_for(
                s.get_web_language(),
                zh="该会话已归档并处于只读状态，不能再修改。",
                en="This session is archived and read-only; it cannot be modified.",
            )
        )
    return target


def _ensure_session_reasoning_effort_initialized(session_id: str) -> str:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    initialized, current = s._initialized_session_reasoning_effort(normalized_session_id)
    if initialized:
        return current
    model = s._session_fixed_model_choice(normalized_session_id)
    agent_id = s._session_agent_id_snapshot(normalized_session_id)
    agent = s.get_agent(agent_id, include_archived=False) if agent_id else None
    if agent is None:
        detail = s.get_session_detail(normalized_session_id, message_limit=0, transcript_scope="none")
        if detail is None:
            raise s.SessionNotFoundError(f"Session not found: {normalized_session_id}")
        fallback_agent_id = str(detail.get("agentId") or "").strip()
        agent = s.get_agent(fallback_agent_id, include_archived=False) if fallback_agent_id else None
    initial = s._initial_session_reasoning_effort(agent, model)
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            raise s.SessionNotFoundError(f"Session not found: {normalized_session_id}")
        if "reasoning_effort" in conversation:
            return s.normalize_reasoning_effort(conversation.get("reasoning_effort"))
        conversation["reasoning_effort"] = initial
        conversation["updated_at"] = s._now_timestamp()
        s.save_chat_state(s.PROJECT_ROOT, payload)
    s._invalidate_session_list_cache()
    return initial


def _ensure_session_workspace(session_id: str) -> Path:
    s = _service()
    token = s._safe_session_workspace_token(session_id)
    sessions_root = s.developer_sandbox.sandboxed_workspace_path(s.PROJECT_ROOT, "sessions").resolve()
    workspace_path = (sessions_root / token).resolve()
    if not workspace_path.is_relative_to(sessions_root):
        raise s.SessionValidationError(f"Invalid session workspace path: {workspace_path}")
    formal_workspace_path = s.developer_sandbox.formal_workspace_path(s.PROJECT_ROOT, "sessions", token)
    if not workspace_path.exists() and formal_workspace_path.exists():
        workspace_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(formal_workspace_path, workspace_path)
    workspace_path.mkdir(parents=True, exist_ok=True)
    for subdir in s._SESSION_WORKSPACE_SUBDIRS:
        (workspace_path / subdir).mkdir(parents=True, exist_ok=True)
    return workspace_path


def _estimate_session_context_tokens(character_count: int, tool_call_count: int) -> int:
    # Conservative mixed Chinese/English approximation plus a small per-message/tool overhead.
    s = _service()
    return max(0, int((max(0, character_count) + 2) // 3) + max(0, tool_call_count) * 12)


def _explicit_chat_result_outcome(result: dict[str, Any]) -> str:
    s = _service()
    metadata = dict(result.get("metadata") or {}) if isinstance(result.get("metadata"), dict) else {}
    source = s._chat_result_outcome_source(result)
    if source == "inferred":
        return str(result.get("task_outcome") or metadata.get("chat_contract_explicit_outcome") or "").strip().lower()
    return str(result.get("outcome") or result.get("task_outcome") or "").strip().lower()


def _extend_codex_tool_lifecycle_projection(
    target: dict[str, list[dict[str, Any]]],
    source: dict[str, list[dict[str, Any]]],
) -> None:
    s = _service()
    for key in ("toolCalls", "terminalOperations", "terminalSessions", "modelObservations"):
        target[key].extend(source.get(key) or [])
    s._merge_codex_terminal_sessions(target)


def _extract_chat_tool_calls(result: Any) -> list[dict[str, Any]]:
    s = _service()
    if not isinstance(result, dict):
        return []
    tool_calls = s._normalize_persisted_tool_calls(result.get("tool_trace") or [])
    if tool_calls:
        return tool_calls
    return s._normalize_persisted_tool_calls(result.get("tool_calls") or result.get("tools") or [])


def _extract_missing_agent_llm_model_id(message: Any) -> str:
    s = _service()
    value = str(message or "").strip()
    marker = "model not found in model library:"
    lowered = value.lower()
    marker_index = lowered.find(marker)
    if marker_index < 0:
        return ""
    return value[marker_index + len(marker):].strip().split()[0].strip("`'\".,;")


def _find_user_message_index_by_api_id(
    conversation_id: str,
    messages: list[dict[str, Any]],
    message_id: str,
) -> int:
    s = _service()
    normalized_target = str(message_id or "").strip()
    if not normalized_target:
        return -1
    for index, item in enumerate(list(messages or []), start=1):
        api_id = str(item.get("id") or f"{conversation_id}-message-{index}").strip()
        if api_id == normalized_target and s._is_real_user_message_entry(item):
            return index - 1
    return -1


def _first_positive_int(*values: Any) -> int:
    s = _service()
    for value in values:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            parsed = 0
        if parsed > 0:
            return parsed
    return 0


def _first_present_mapping_value(source: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    s = _service()
    for key in aliases:
        if key in source and source.get(key) is not None:
            return source.get(key)
    return None


def _get_session_stop_reason(session_id: str) -> str:
    s = _service()
    controller = s._get_session_turn_control(session_id)
    return s._get_turn_control_stop_reason(controller)


def _get_session_turn_control(session_id: str) -> Any | None:
    s = _service()
    with s._SESSION_TURN_CONTROLS_LOCK:
        return s._SESSION_TURN_CONTROLS.get(session_id)


def _get_turn_control_stop_reason(controller: Any | None) -> str:
    s = _service()
    if controller is None:
        return ""
    snapshot = controller.snapshot()
    if not snapshot.get("stopRequested"):
        return ""
    return str(snapshot.get("stopReason") or "").strip()


def _initial_session_reasoning_effort(agent: dict[str, Any] | None, model: dict[str, Any]) -> str:
    s = _service()
    supported = [
        s.normalize_reasoning_effort(value)
        for value in list(model.get("reasoningEffortValues") or [])
    ]
    supported = [value for value in dict.fromkeys(supported) if value]
    agent_default = s.normalize_reasoning_effort(s._session_agent_reasoning_effort(agent))
    model_default = s.normalize_reasoning_effort(model.get("defaultReasoningEffort"))
    return next(
        (value for value in (agent_default, model_default) if value in supported),
        supported[0] if supported else "",
    )


def _initialized_session_reasoning_effort(session_id: str) -> tuple[bool, str]:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not s._ensure_session_conversation_record(
        normalized_session_id,
        source="session.reasoning_effort.snapshot",
    ):
        raise s.SessionNotFoundError(f"Session not found: {normalized_session_id}")
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            raise s.SessionNotFoundError(f"Session not found: {normalized_session_id}")
        if "reasoning_effort" not in conversation:
            return False, ""
        return True, s.normalize_reasoning_effort(conversation.get("reasoning_effort"))


def _invalidate_session_conversation_events_cache(session_id: str = "") -> None:
    s = _service()
    s._journal_bridge.invalidate_session_conversation_events_cache(session_id)


def _invalidate_session_list_cache() -> None:
    """Clear list cache and any direct-session collision repair fingerprint."""
    s = _service()

    s._invalidate_session_list_cache_core()
    with s._DIRECT_SESSION_COLLISION_REPAIR_LOCK:
        s._DIRECT_SESSION_COLLISION_REPAIR_SIGNATURE = None


def _is_continue_request(text: Any) -> bool:
    s = _service()
    normalized = re.sub(r"\s+", "", str(text or "").strip().lower())
    return normalized in {
        "继续",
        "接着",
        "继续做",
        "继续执行",
        "继续推进",
        "接着做",
        "继续上一轮",
        "继续上一个任务",
        "continue",
        "goon",
    }


def _is_effective_user_message(message: Any) -> bool:
    s = _service()
    return (
        s._is_meaningful_task_goal(message)
        and not s._is_contextual_confirmation_message(message)
        and not s._looks_like_agent_inbox_protocol_message(message)
    )


def _is_meaningful_task_goal(text: Any) -> bool:
    s = _service()
    value = s.trim_lines(text or "", max_lines=4)
    compact = re.sub(r"\s+", "", value).strip()
    if not compact:
        return False
    if s._is_continue_request(compact):
        return False
    if compact in {"1", "2", "3", "ok", "好的", "确认", "是", "否", "停止", "stop"}:
        return False
    return len(compact) >= 6


def _is_non_diagnostic_runtime_status_source(source: dict[str, Any]) -> bool:
    s = _service()
    if str(source.get("kind") or "").strip().lower() != "status":
        return False
    status = s._codex_lifecycle_status(source.get("status") or source.get("semanticStatus"))
    if status in {"failed", "degraded"} or s._status_source_has_error_detail(source):
        return False
    return True


def _is_protocol_only_assistant_message(content: Any) -> bool:
    s = _service()
    raw = str(content or "").strip()
    if not raw:
        return True
    if s._sanitize_message_content("assistant", raw):
        return False
    return bool(
        re.search(
            r"<\s*(?:/?state\b|/?invoke\b|/?parameter\b|/?active_components\b|[\w:.-]*tool_call\b|[^>\n]*dsml)",
            raw,
            flags=re.IGNORECASE,
        )
    )


def _is_real_user_message_entry(item: Any) -> bool:
    s = _service()
    if not isinstance(item, dict):
        return False
    if str(item.get("role") or "").strip().lower() != "user":
        return False
    return not (s._is_agent_inbox_message_entry(item) or s._is_system_authored_user_message_entry(item))


def _is_retriable_image_request_prompt(prompt: Any) -> bool:
    s = _service()
    return s._looks_like_image_retry_context(prompt)


def _is_session_busy_for_delete(conversation_id: str, conversation: dict[str, Any]) -> bool:
    s = _service()
    phase = s._conversation_phase(conversation_id, conversation)
    return phase in {"queued", "running", "stopping", "paused"}


def _is_session_running(session_id: str) -> bool:
    s = _service()
    with s._RUNNING_SESSIONS_LOCK:
        return session_id in s._RUNNING_SESSION_IDS


def _is_session_stop_requested(session_id: str) -> bool:
    s = _service()
    controller = s._get_session_turn_control(session_id)
    if controller is None:
        return False
    snapshot = controller.snapshot()
    if snapshot.get("releasedToUser"):
        return False
    return bool(snapshot.get("stopRequested"))


def _is_session_turn_current(session_id: str, turn_id: str) -> bool:
    s = _service()
    if not turn_id:
        return True
    with s._RUNNING_SESSIONS_LOCK:
        return s._SESSION_ACTIVE_TURN_IDS.get(session_id) == turn_id


def _is_system_authored_user_message_entry(item: Any) -> bool:
    s = _service()
    if not isinstance(item, dict):
        return False
    if str(item.get("role") or "").strip().lower() != "user":
        return False
    return s._message_metadata_kind(item) == "hot_restart_resume"


def _is_task_tool_backed_active_task(task: dict[str, Any] | None) -> bool:
    s = _service()
    if not isinstance(task, dict):
        return False
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    source = str(metadata.get("source") or "").strip()
    return source == "task_tool"


def _is_task_tool_name(name: Any) -> bool:
    s = _service()
    return str(name or "").strip() in s._SESSION_TASK_CONTEXT_TOOL_NAMES


def _latest_assistant_message_is_stop(messages: list[dict[str, Any]]) -> bool:
    s = _service()
    latest_messages = list(messages or [])[-1:]
    message = latest_messages[0] if latest_messages else None
    if not isinstance(message, dict):
        return False
    if str(message.get("role") or "").strip().lower() != "assistant":
        return False
    content = str(message.get("content") or "")
    return "本轮已按请求停止" in content or "stopped as requested" in content


def _latest_assistant_summary(messages: list[dict[str, Any]]) -> str:
    s = _service()
    for item in reversed(messages):
        if str(item.get("role") or "").strip().lower() != "assistant":
            continue
        return s._compact_preview_text(item.get("content") or "")
    return ""


def _latest_meaningful_user_message(messages: list[dict[str, Any]]) -> str:
    s = _service()
    for item in reversed(messages):
        if str(item.get("role") or "").strip().lower() != "user":
            continue
        content = s.trim_lines(item.get("content") or "", max_lines=4)
        if s._is_effective_user_message(content):
            return content
    return ""


def _latest_message_timestamp(messages: list[dict[str, Any]]) -> str:
    s = _service()
    for item in reversed(messages):
        timestamp = str(item.get("timestamp") or "").strip()
        if timestamp:
            return timestamp
    return ""


def _latest_real_user_message(messages: list[dict[str, Any]]) -> str:
    s = _service()
    for item in reversed(messages):
        if not s._is_real_user_message_entry(item):
            continue
        return s.trim_lines(item.get("content") or "", max_lines=4)
    return ""


def _latest_user_message(messages: list[dict[str, Any]]) -> str:
    s = _service()
    for item in reversed(messages):
        if not s._is_real_user_message_entry(item):
            continue
        return s.trim_lines(item.get("content") or "", max_lines=4)
    return ""


def _latest_user_message_id(conversation_id: str, messages: list[dict[str, Any]]) -> str:
    s = _service()
    for index in range(len(messages or []) - 1, -1, -1):
        item = messages[index] or {}
        if not s._is_real_user_message_entry(item):
            continue
        return str(item.get("id") or f"{conversation_id}-message-{index + 1}").strip()
    return ""


def _latest_user_message_index(messages: list[dict[str, Any]]) -> int:
    s = _service()
    for index in range(len(messages or []) - 1, -1, -1):
        if s._is_real_user_message_entry(messages[index] or {}):
            return index
    return -1


def _latest_user_message_index_matching_goal(messages: list[dict[str, Any]], goal: Any) -> int:
    s = _service()
    target = s._task_goal_dedupe_key(goal)
    if not target:
        return -1
    for index in range(len(messages or []) - 1, -1, -1):
        item = messages[index]
        if not isinstance(item, dict):
            continue
        if not s._is_real_user_message_entry(item):
            continue
        content = s.trim_lines(item.get("content") or "", max_lines=4)
        if s._task_goal_dedupe_key(content) == target:
            return index
    return -1


def _latest_user_summary(messages: list[dict[str, Any]]) -> str:
    s = _service()
    for item in reversed(messages):
        if not s._is_real_user_message_entry(item):
            continue
        return s._compact_preview_text(item.get("content") or "")
    return ""


def _live_assistant_message_id(session_id: str, turn_id: str = "") -> str:
    s = _service()
    return f"{session_id}-message-live-{s._live_assistant_overlay_turn_id(session_id, turn_id)}"


def _live_assistant_overlay_turn_id(session_id: str, turn_id: str = "") -> str:
    s = _service()
    normalized_turn_id = str(turn_id or "").strip() or s._current_session_turn_id(session_id)
    return normalized_turn_id or "current"


def _load_active_conversation_summary_target(
    *,
    agent_by_id: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    """Normalize only the persisted active conversation for polling fast paths."""
    s = _service()

    with s._CHAT_STATE_LOCK, s.chat_state_transaction(s.PROJECT_ROOT):
        payload = s.load_chat_state(s.PROJECT_ROOT)
        active_id = str(payload.get("active_conversation_id") or s.DEFAULT_CHAT_CONVERSATION_ID).strip()
        raw_target = s._find_conversation_entry(payload, active_id)
        if raw_target is None:
            return active_id, None
        target = s._normalize_conversation(
            raw_target,
            agent_by_id=agent_by_id,
            hidden_team_member_agent_ids=s._agent_directory_stub_hidden_team_member_ids(),
            ensure_workspace=False,
            lightweight=True,
        )
        return active_id, target


def _load_session_conversation_events_cached(session_id: str) -> list[Any]:
    s = _service()
    return s._journal_bridge.load_session_conversation_events_cached(
        session_id,
        project_root=s.PROJECT_ROOT,
    )


def _localize_lease_conflict(reason: str, *, lang: str) -> str:
    s = _service()
    fallback = str(reason or "").strip()
    return s.text_for(
        lang,
        zh=f"当前资源正在被另一条运行占用，请等待它收束后再继续。{fallback}",
        en=f"Another active run holds a conflicting resource lease. Wait for it to finish before continuing. {fallback}",
    ).strip()


def _looks_like_agent_message_delivery_confirmation(text: str) -> bool:
    s = _service()
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if len(normalized) > 240:
        return False
    return bool(
        re.search(
            r"(已(?:将|把).{0,80}(?:发送|发给|转发|投递).{0,80}(?:成功|完成)|消息投递成功|投递成功|发送成功|已发送给)",
            normalized,
        )
    )


def _looks_like_encoding_replacement_message(message: str) -> bool:
    s = _service()
    text = str(message or "").strip()
    if not text:
        return False
    if s._REPLACEMENT_ONLY_TEXT_PATTERN.fullmatch(text):
        return True
    if s._REPLACEMENT_ONLY_PREFIX_PATTERN.match(text):
        return True
    question_count = text.count("?")
    if question_count < 3:
        return False
    non_space_count = sum(1 for char in text if not char.isspace())
    return non_space_count > 0 and question_count / non_space_count >= 0.8


def _looks_like_structured_payload(text: str) -> bool:
    s = _service()
    candidate = str(text or "").strip()
    if not candidate:
        return False
    if not (
        (candidate.startswith("{") and candidate.endswith("}"))
        or (candidate.startswith("[") and candidate.endswith("]"))
    ):
        return False
    try:
        parsed = json.loads(candidate)
    except Exception:
        return False
    return isinstance(parsed, (dict, list))


def _merge_codex_lifecycle_status(left: Any, right: Any) -> str:
    s = _service()
    statuses = {s._codex_lifecycle_status(left), s._codex_lifecycle_status(right)}
    for status in ("running", "pending", "failed", "degraded"):
        if status in statuses:
            return status
    return "completed"


def _merge_codex_terminal_sessions(lifecycle: dict[str, list[dict[str, Any]]]) -> None:
    s = _service()
    sessions_by_id: dict[str, dict[str, Any]] = {}
    for session in lifecycle.get("terminalSessions") or []:
        terminal_id = str(session.get("terminalId") or "").strip()
        if not terminal_id:
            continue
        existing = sessions_by_id.get(terminal_id)
        if existing is None:
            sessions_by_id[terminal_id] = {
                **session,
                "operationIds": list(session.get("operationIds") or []),
            }
            continue
        for operation_id in session.get("operationIds") or []:
            if operation_id not in existing["operationIds"]:
                existing["operationIds"].append(operation_id)
        existing["status"] = s._merge_codex_lifecycle_status(existing.get("status"), session.get("status"))
    lifecycle["terminalSessions"] = list(sessions_by_id.values())


def _merge_project_paths(*groups: list[str], limit: int = 8) -> list[str]:
    s = _service()
    merged: list[str] = []
    for group in groups:
        for raw in list(group or []):
            value = str(raw or "").strip()
            if not value or value in merged:
                continue
            merged.append(value)
    if limit > 0:
        return merged[-limit:]
    return merged


def _message_content_with_attachment_summary(content: Any, attachments: list[dict[str, Any]]) -> str:
    s = _service()
    text = str(content or "").strip()
    normalized = s._normalize_message_attachments(attachments)
    if not normalized:
        return text
    lines = [text] if text else []
    lines.append("")
    lines.append("[图片附件摘要]")
    for index, attachment in enumerate(normalized, start=1):
        filename = str(attachment.get("filename") or attachment.get("artifactId") or f"image-{index}").strip()
        content_type = str(attachment.get("contentType") or "").strip()
        size_bytes = s._coerce_nonnegative_int(attachment.get("sizeBytes") or 0)
        lines.append(f"- {filename} · {content_type or 'image'} · {size_bytes} bytes")
    return "\n".join(lines).strip()


def _message_metadata_kind(item: Any) -> str:
    s = _service()
    if not isinstance(item, dict):
        return ""
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return str(metadata.get("kind") or "").strip()


def _message_turn_id(message: Any) -> str:
    s = _service()
    if not isinstance(message, dict):
        return ""
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    return str(
        metadata.get("turnId")
        or metadata.get("turn_id")
        or message.get("turnId")
        or message.get("turn_id")
        or ""
    ).strip()


def _missing_llm_usage(*, recorded_at: str = "") -> dict[str, Any]:
    s = _service()
    return {
        "source": "missing",
        "inputTokens": 0,
        "outputTokens": 0,
        "totalTokens": 0,
        "cachedInputTokens": 0,
        "cacheReadInputTokens": 0,
        "cacheCreationInputTokens": 0,
        "uncachedInputTokens": 0,
        "cacheHitRate": 0.0,
        "provider": "",
        "model": "",
        "recordedAt": str(recorded_at or "").strip() or s._now_timestamp(),
    }


def _normalize_message_thought(raw: dict[str, Any], *, role: str) -> str:
    s = _service()
    if role != "assistant":
        return ""
    explicit = s._sanitize_thought_text(raw.get("thought") or "")
    if explicit:
        return explicit
    return s._extract_embedded_thought(raw.get("content") or "")


def _normalize_project_path(value: Any, *, existing_only: bool) -> str:
    s = _service()
    paths = s._normalize_project_paths([value], existing_only=existing_only)
    return paths[0] if paths else ""


def _normalize_project_paths(items: Any, *, existing_only: bool) -> list[str]:
    s = _service()
    project_root = s.PROJECT_ROOT.resolve()
    paths: list[str] = []
    for raw in list(items or []):
        value = str(raw or "").strip()
        if not value or value in {".", "./"}:
            continue
        candidate = (project_root / value).resolve()
        try:
            candidate.relative_to(project_root)
        except ValueError:
            continue
        if existing_only:
            if not candidate.exists() or not candidate.is_file():
                continue
        elif candidate.exists() and candidate.is_dir():
            continue
        normalized = candidate.relative_to(project_root).as_posix()
        if normalized not in paths:
            paths.append(normalized)
    return paths


def _normalize_session_detail_transcript_scope(value: Any) -> str:
    s = _service()
    normalized = str(value or "all").strip().lower()
    return normalized if normalized in {"all", "window", "none"} else "all"


def _normalize_session_kind(value: Any) -> str:
    s = _service()
    normalized = str(value or "").strip().lower()
    if normalized in {"child", "supervised"}:
        return normalized
    return "main"


def _normalize_session_query_sort(value: str) -> str:
    s = _service()
    normalized = str(value or "").strip()
    return normalized if normalized in {"updatedAt_desc", "updatedAt_asc", "title_asc", "title_desc"} else "updatedAt_desc"


def _normalize_session_runtime_notice(value: Any, *, index: int = 0) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(value, dict):
        return None
    message = str(value.get("message") or value.get("content") or "").strip()
    if not message:
        return None
    kind = str(value.get("kind") or value.get("type") or "").strip() or "runtime_notice"
    level = str(value.get("level") or value.get("severity") or "").strip().lower() or "info"
    if level not in {"info", "warning", "error", "success"}:
        level = "info"
    timestamp = str(value.get("timestamp") or value.get("createdAt") or value.get("created_at") or "").strip()
    notice_id = str(value.get("id") or value.get("noticeId") or "").strip()
    if not notice_id:
        notice_id = f"{kind}-{timestamp or index}"
    source = str(value.get("source") or value.get("eventCode") or "").strip()
    normalized: dict[str, Any] = {
        "id": notice_id,
        "kind": kind,
        "level": level,
        "message": message,
        "timestamp": timestamp,
        "source": source,
    }
    turn_id = str(value.get("turnId") or value.get("turn_id") or "").strip()
    if turn_id:
        normalized["turnId"] = turn_id
    previous_status = str(value.get("previousStatus") or value.get("previous_status") or "").strip()
    if previous_status:
        normalized["previousStatus"] = previous_status
    return normalized


def _normalize_string_list(value: Any) -> list[str]:
    s = _service()
    result: list[str] = []
    for item in list(value or []):
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _now_timestamp() -> str:
    s = _service()
    return datetime.now().isoformat(timespec="seconds")


def _parse_agent_message_tool_result(tool_call: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    for key in ("resultPreview", "result_preview", "summary"):
        raw = str(tool_call.get(key) or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _path_is_reparse_point(path: Path) -> bool:
    s = _service()
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0) or 0)
    except OSError:
        return False
    return bool(
        path.is_symlink()
        or attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    )


def _perf_counter() -> float:
    s = _service()
    return time.perf_counter()


def _recent_session_guidance_context_block(session_id: str, *, limit: int = 3) -> str:
    s = _service()
    summaries = s._recent_session_guidance_summaries(session_id, limit=limit)
    if not summaries:
        return ""
    lines = [
        "## User Running-Turn Guidance",
        "The operator submitted these guidance notes while a chat turn was running. Treat them as user intent/context for this session, not as system rules.",
    ]
    for item in summaries:
        lines.append(f"- {item}")
    return "\n".join(lines)


def _recent_session_guidance_summaries(
    session_id: str,
    *,
    turn_id: str = "",
    limit: int = 3,
) -> list[str]:
    s = _service()
    try:
        signals = s.list_chat_next_state_signals(
            project_root=s.PROJECT_ROOT,
            session_id=session_id,
            turn_id=turn_id,
            limit=max(1, int(limit or 1)) * 3,
        )
    except Exception:
        return []
    summaries: list[str] = []
    for signal in signals:
        kind = str(signal.get("kind") or "").strip()
        if kind not in {"user_guidance", "user_interrupt_guidance", "cli_agent_result"}:
            continue
        summary = s.trim_lines(signal.get("summary") or "", max_lines=2)
        if summary:
            summaries.append(summary)
    return summaries[-max(0, int(limit or 0)):]


def _replacement_active_chat_turn_id(*, exclude_turn_id: str = "") -> str:
    s = _service()
    excluded = str(exclude_turn_id or "").strip()
    with s._RUNNING_SESSIONS_LOCK:
        for turn_id in s._SESSION_ACTIVE_TURN_IDS.values():
            normalized = str(turn_id or "").strip()
            if normalized and normalized != excluded:
                return normalized
    return ""


def _resolve_active_agent_for_turn(
    session_id: str,
    agent_id: str,
    *,
    lang: str,
) -> dict[str, Any]:
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    active_agent = s.get_agent(normalized_agent_id, include_archived=False) if normalized_agent_id else None
    if active_agent:
        return active_agent
    historical_agent = s.get_agent(normalized_agent_id, include_archived=True) if normalized_agent_id else None
    status = str((historical_agent or {}).get("status") or "").strip().lower()
    reason = "archived_agent" if status == "archived" else "missing_agent"
    s._record_session_agent_unavailable_event(
        session_id,
        agent_id=normalized_agent_id,
        reason=reason,
        agent_status=status,
    )
    raise s.SessionValidationError(s._session_agent_unavailable_message(reason, lang=lang))


def _resolve_chat_source_log_path() -> str:
    s = _service()
    conversation_logger = getattr(s.unified_logger, "conversation", None)
    current_session_file = str(getattr(conversation_logger, "_current_session_file", "") or "").strip()
    if current_session_file:
        path = Path(current_session_file)
        if path.exists():
            return str(path.resolve())
    log_dir = (s.PROJECT_ROOT / "log_info").resolve()
    if not log_dir.exists():
        return ""
    candidates = sorted(
        (path for path in log_dir.glob("conversation_*.jsonl") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return ""
    return str(candidates[0].resolve())


def _resolve_session_user_prompt(
    session_id: str,
    raw_message: Any,
    history_messages: list[dict[str, Any]],
    *,
    existing_task: dict[str, Any] | None = None,
) -> tuple[str, str]:
    s = _service()
    prompt = str(raw_message or "").strip()
    if s._is_continue_request(prompt):
        return prompt, "raw_continue"
    if s._is_contextual_confirmation_message(prompt):
        return prompt, "raw_confirmation"
    if s._is_effective_user_message(prompt):
        return prompt, "raw_meaningful"
    return prompt, "raw_dialogue"


def _result_has_image2_tool_call(result: Any) -> bool:
    s = _service()
    for tool_call in s._extract_chat_tool_calls(result):
        if str(tool_call.get("name") or "").strip() == "image2_generate_tool":
            return True
    return False


def _result_has_task_context_tool(result: Any) -> bool:
    s = _service()
    if not isinstance(result, dict):
        return False
    for tool_call in s._extract_chat_tool_calls(result):
        if s._is_task_tool_name(s._tool_call_name(tool_call)):
            return True
    return False


def _result_tool_names(result: Any) -> set[str]:
    s = _service()
    if not isinstance(result, dict):
        return set()
    tool_trace = result.get("tool_trace") or result.get("tool_calls") or []
    return {
        name
        for item in list(tool_trace or [])
        if (name := s._tool_call_name(item))
    }


def _root_session_id_for_conversations(session_id: str, conversations: list[dict[str, Any]]) -> str:
    s = _service()
    normalized = str(session_id or "").strip()
    for item in list(conversations or []):
        if str(item.get("id") or item.get("conversation_id") or "").strip() != normalized:
            continue
        root_id = str(item.get("rootSessionId") or item.get("root_session_id") or "").strip()
        if root_id:
            return root_id
        parent_id = str(item.get("parentSessionId") or item.get("parent_session_id") or "").strip()
        return parent_id or normalized
    return normalized


def _sandbox_terminal_result_facts(value: Any) -> dict[str, Any]:
    """Extract explicit terminal facts from the new sandbox tool result envelope."""
    s = _service()

    if isinstance(value, dict):
        payload = value
    else:
        try:
            payload = json.loads(str(value or "").lstrip("\ufeff").strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    if not isinstance(payload, dict):
        return {}
    terminal_session_id = str(payload.get("terminalSessionId") or "").strip()
    if not terminal_session_id:
        return {}
    result: dict[str, Any] = {"terminalSessionId": terminal_session_id}
    for key in ("status", "terminalStatus"):
        status = str(payload.get(key) or "").strip()
        if status:
            result["terminalStatus"] = status
            break
    if "sessionOpen" in payload:
        result["sessionOpen"] = bool(payload.get("sessionOpen"))
    formatted_output = s._trim_tool_detail_text(payload.get("formattedOutput") or "", max_chars=1200, max_lines=10)
    if formatted_output:
        result["formattedOutput"] = formatted_output
    for key in ("exitCode", "timedOut", "truncated", "originalLength", "durationMs"):
        if key in payload:
            result[key] = payload[key]
    return result


def _sanitize_message_content(role: str, content: Any) -> str:
    s = _service()
    text = str(content or "").strip()
    if str(role or "").strip().lower() != "assistant":
        return text
    return s.sanitize_assistant_visible_text(text)


def _sanitize_thought_delta_text(text: Any) -> str:
    s = _service()
    return s.sanitize_assistant_thought_delta_text(text)


def _sanitize_thought_text(text: Any) -> str:
    s = _service()
    return s.sanitize_assistant_thought_text(text)


def _select_existing_active_task_for_update(
    stored_active_task: dict[str, Any] | None,
    hint_active_task: dict[str, Any] | None,
    messages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    s = _service()
    if s._is_task_tool_backed_active_task(stored_active_task):
        return stored_active_task
    if s._is_task_tool_backed_active_task(hint_active_task):
        return hint_active_task
    return None


def _session_context_limit(conversation: dict[str, Any] | None = None) -> int:
    s = _service()
    return s._coerce_nonnegative_int(s._session_context_limit_payload(conversation).get("limit") or 0)


def _session_context_limit_payload(conversation: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve the model max context window for a session.

    No silent numeric fallbacks (no 128k/32k invention, no compression-threshold
    masquerading as window). Callers must treat limit<=0 / source=missing as an
    operator-visible error.
    """
    s = _service()
    try:
        cfg = s.get_config()
        model_payload = s._conversation_agent_dialogue_context_window_payload(cfg, conversation)
        model_limit = s._coerce_nonnegative_int(model_payload.get("limit") or 0)
        model_id = str(model_payload.get("modelId") or "").strip()
        agent_id = str(model_payload.get("agentId") or "").strip()
        if model_limit > 0:
            return {
                **model_payload,
                "limit": model_limit,
                "source": "agent_dialogue_model",
                "error": "",
            }
        if not model_id:
            error = (
                "未解析到会话对话模型，无法确定 max 上下文窗口。"
                "请为 Agent 绑定明确的对话模型，并在模型/供应商配置中设置 context_window。"
            )
        else:
            error = (
                f"模型 `{model_id}` 未配置有效的 max 上下文窗口（context_window）。"
                "禁止使用默认兜底值；请在设置中填写，或通过模型发现写入后再试。"
            )
        return {
            "limit": 0,
            "source": "missing",
            "modelId": model_id,
            "agentId": agent_id,
            "error": error,
        }
    except Exception as exc:
        return {
            "limit": 0,
            "source": "missing",
            "modelId": "",
            "agentId": "",
            "error": f"解析 max 上下文窗口失败：{type(exc).__name__}",
        }


def _session_conversation_events_signature(session_id: str) -> tuple[str, int, int, int]:
    s = _service()
    return s._journal_bridge.session_conversation_events_signature(
        session_id,
        project_root=s.PROJECT_ROOT,
    )


def _session_events_have_terminal_turn(events: Any, turn_id: str) -> bool:
    s = _service()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_turn_id:
        return False
    for event in events or []:
        event_turn_id = str(getattr(event, "turn_id", "") or "").strip()
        if event_turn_id != normalized_turn_id:
            continue
        event_type = str(getattr(event, "event_type", "") or "").strip()
        if event_type in {s.EVENT_TURN_COMPLETED, s.EVENT_TURN_FAILED, s.EVENT_TURN_INTERRUPTED}:
            return True
    return False


def _session_last_llm_usage(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    s = _service()
    for message in reversed(list(messages or [])):
        if str((message or {}).get("role") or "").strip().lower() != "assistant":
            continue
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        normalized = s._normalize_turn_llm_usage(metadata.get("llmUsage") or metadata.get("llm_usage"))
        if normalized is not None:
            return normalized
    return None


def _session_ledger_sequence(session_id: str) -> int:
    s = _service()
    return s._journal_bridge.session_ledger_sequence(session_id, project_root=s.PROJECT_ROOT)


def _session_query_sort_key(sort: str):
    s = _service()
    if sort.startswith("title"):
        return lambda item: str(item.get("title") or "").strip().lower()
    return lambda item: s._timestamp_sort_key(item.get("updatedAt") or item.get("lastActive") or "")


def _session_reasoning_effort_snapshot(session_id: str) -> str:
    s = _service()
    initialized, current = s._initialized_session_reasoning_effort(session_id)
    if initialized:
        return current
    return s._ensure_session_reasoning_effort_initialized(session_id)


def _session_reference_prompt_block(references: list[dict[str, Any]]) -> str:
    s = _service()
    normalized = s._normalize_session_references(references)
    if not normalized:
        return ""
    lines = [
        "[Session References]",
        "The user attached these conversation references as structured read-only context handles.",
        "You may query referenced conversation history with session_reference_query_tool.",
        "Do not send or notify another Agent only because a reference exists; use agent_message_tool only when the user's wording explicitly asks you to send/ask/notify that Agent.",
    ]
    for index, reference in enumerate(normalized, start=1):
        title = str(reference.get("title") or reference.get("sessionId") or "").strip()
        agent_label = str(reference.get("agentDisplayName") or reference.get("agentCode") or reference.get("agentId") or "").strip()
        summary = str(reference.get("summary") or "").strip()
        lines.append(
            f"- ref {index}: referenceId={reference.get('referenceId')}; sessionId={reference.get('sessionId')}; title={title}; agent={agent_label or 'unknown'}; allowed=query_only"
        )
        if summary:
            lines.append(f"  summary={summary}")
    return "\n".join(lines).strip()


def _session_task_workspace_for_turn(
    context: dict[str, Any],
    *,
    session_workspace: str | Path,
    default_workspace: str | Path,
) -> Path:
    """Keep stage-task checklists fresh without clearing an Agent's durable task state."""
    s = _service()

    stage_task = s._source_collection_stage_task_context_metadata(context)
    task_id = str(stage_task.get("taskId") or "").strip()
    if not task_id:
        return Path(default_workspace)
    return Path(session_workspace) / "stage_tasks" / s._safe_session_workspace_token(task_id)


@contextmanager
def _session_tool_workspace_override(
    session_workspace: str | Path,
    memory_workspace: str | Path | None = None,
    task_workspace: str | Path | None = None,
):
    s = _service()
    try:
        from core.infrastructure.mental_model import active_mental_workspace
        from core.orchestration.task_planner import task_storage_override
        from tools.shell_tools import workspace_root_override
        from tools.memory_tools import memory_storage_override
    except Exception:
        yield
        return
    memory_root = memory_workspace or session_workspace
    task_root = task_workspace or session_workspace
    with (
        active_mental_workspace(session_workspace),
        workspace_root_override(session_workspace),
        memory_storage_override(memory_root),
        task_storage_override(task_root),
    ):
        yield


def _session_turn_agent_message_item_id(session_id: str, turn_id: str) -> str:
    s = _service()
    return f"{s._session_turn_item_base_id(session_id, turn_id)}-agent-message"


def _session_turn_assistant_markdown_text(cells: list[Any]) -> str:
    s = _service()
    text_parts: list[str] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        if str(cell.get("kind") or "").strip() != "assistant_markdown":
            continue
        text = s._sanitize_message_content("assistant", cell.get("text") or "")
        if text:
            text_parts.append(text)
    return "\n\n".join(text_parts)


def _session_turn_item_base_id(session_id: str, turn_id: str) -> str:
    s = _service()
    normalized_session_id = str(session_id or "").strip() or "session"
    normalized_turn_id = str(turn_id or "").strip() or "current"
    return f"{normalized_session_id}-turn-{normalized_turn_id}"


def _session_turn_item_type_from_codex_cell(cell_kind: str) -> str:
    s = _service()
    if cell_kind == "reasoning_summary":
        return "reasoning"
    if cell_kind == "tool_call":
        return "tool_call"
    if cell_kind == "status":
        return "status"
    if cell_kind == "error_notice":
        return "error"
    if cell_kind == "stream_tail":
        return "status"
    return ""


def _session_turn_prepare_timing_log_fields(timings: dict[str, Any]) -> dict[str, Any]:
    """Keep turn-start telemetry below the runtime-scene field cap.

    ``worker_started`` already has enough identity and runtime fields to hit the
    telemetry field limit. Emit preparation timings in a dedicated event rather
    than silently dropping the measurements that explain pre-LLM latency.
    """
    s = _service()

    keys = (
        "totalPrepareMs",
        "sessionWorkspaceMs",
        "agentDirectorySyncMs",
        "agentLookupMs",
        "promptSnapshotMs",
        "lightweightChatDecisionMs",
        "agentContextBuildMs",
        "workspacePolicyMs",
        "llmKeyEnvSyncMs",
        "agentLlmResolveMs",
        "llmKeyEnvSyncedCount",
        "llmKeyEnvAlreadyPresentCount",
        "llmKeyEnvMissingCount",
    )
    return {
        key: timings[key]
        for key in keys
        if key in timings and isinstance(timings[key], (bool, int, float))
    }


def _session_workspace_relative_path(session_id: str) -> str:
    s = _service()
    return f"workspace/sessions/{s._safe_session_workspace_token(session_id)}"


def _set_or_clear_session_active_task(conversation: dict[str, Any], task: dict[str, Any] | None) -> None:
    s = _service()
    if task is not None:
        conversation["active_task"] = task
        conversation.pop("activeTask", None)
        return
    conversation.pop("active_task", None)
    conversation.pop("activeTask", None)


def _set_session_live_context_composition(
    session_id: str,
    context_composition: Any,
    *,
    turn_id: str = "",
) -> None:
    s = _service()
    s._set_session_live_output(session_id, turn_id=turn_id, context_composition=context_composition)


def _set_session_running(
    session_id: str,
    is_running: bool,
    *,
    turn_id: str = "",
    leases: list[str] | None = None,
) -> None:
    s = _service()
    with s._RUNNING_SESSIONS_LOCK:
        if is_running:
            s._RUNNING_SESSION_IDS.add(session_id)
            if turn_id:
                s._SESSION_ACTIVE_TURN_IDS[session_id] = turn_id
            if leases is not None:
                s._SESSION_ACTIVE_TURN_LEASES[session_id] = list(leases)
        else:
            if not turn_id:
                s._RUNNING_SESSION_IDS.discard(session_id)
                s._SESSION_ACTIVE_TURN_IDS.pop(session_id, None)
                s._SESSION_ACTIVE_TURN_LEASES.pop(session_id, None)
                return
            if s._SESSION_ACTIVE_TURN_IDS.get(session_id) == turn_id:
                s._RUNNING_SESSION_IDS.discard(session_id)
                s._SESSION_ACTIVE_TURN_IDS.pop(session_id, None)
                s._SESSION_ACTIVE_TURN_LEASES.pop(session_id, None)


def _set_session_waiting_live_output(session_id: str, *, turn_id: str = "") -> None:
    s = _service()
    s._set_session_turn_progress_live_output(session_id, "context_prepare", turn_id=turn_id)


def _short_hash(value: Any) -> str:
    s = _service()
    text = str(value or "")
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _skill_invocation_payload(command: Any | None) -> dict[str, Any] | None:
    s = _service()
    if command is None:
        return None
    return {
        "command": command.command,
        "args": command.args,
        **s.skill_descriptor_for_log(command.skill),
        "_skill": command.skill,
    }


def _skill_runtime_context_from_invocation(invocation: Any) -> str:
    s = _service()
    if not isinstance(invocation, dict):
        return ""
    skill = invocation.get("_skill")
    if skill is None:
        return ""
    return s.build_skill_runtime_context(
        skill,
        command=str(invocation.get("command") or ""),
        args=str(invocation.get("args") or ""),
    )


def _source_authority_ref(kind: str, source_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    from core.agent_kernel.source_authority import source_ref

    return source_ref(kind, source_id, metadata)


def _source_collection_stage_task_context_metadata(context: dict[str, Any]) -> dict[str, str]:
    s = _service()
    metadata = context.get("message_metadata") if isinstance(context.get("message_metadata"), dict) else {}
    if str(metadata.get("kind") or "").strip() != s.SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND:
        return {}
    team_id = str(metadata.get("teamId") or "").strip()
    task_id = str(metadata.get("sourceCollectionStageTaskId") or "").strip()
    if not team_id or not task_id:
        return {}
    return {
        "teamId": team_id,
        "runId": str(metadata.get("runId") or "").strip(),
        "stageId": str(metadata.get("stageId") or "").strip(),
        "taskId": task_id,
        "agentId": str(metadata.get("agentId") or "").strip(),
        "agentRole": str(metadata.get("agentRole") or "").strip(),
    }


def _source_collection_stage_task_turn_metadata(messages: list[dict[str, Any]], turn_id: str = "") -> dict[str, str]:
    s = _service()
    normalized_turn_id = str(turn_id or "").strip()
    for message in reversed(list(messages or [])):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if str(metadata.get("kind") or "").strip() != s.SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND:
            continue
        message_turn_id = s._message_turn_id(message)
        if normalized_turn_id and message_turn_id and message_turn_id != normalized_turn_id:
            continue
        team_id = str(metadata.get("teamId") or "").strip()
        task_id = str(metadata.get("sourceCollectionStageTaskId") or "").strip()
        if not team_id or not task_id:
            continue
        return {
            "teamId": team_id,
            "runId": str(metadata.get("runId") or "").strip(),
            "taskId": task_id,
            "stageId": str(metadata.get("stageId") or "").strip(),
            "agentId": str(metadata.get("agentId") or "").strip(),
            "agentRole": str(metadata.get("agentRole") or "").strip(),
            "turnId": message_turn_id,
        }
    return {}


def _status_source_has_error_detail(source: dict[str, Any]) -> bool:
    s = _service()
    return bool(
        str(source.get("error") or "").strip()
        or str(source.get("failureClass") or source.get("failure_class") or "").strip()
        or bool(source.get("timedOut") or source.get("timed_out"))
    )


def _submit_session_cycle_message_projection(
    session_id: str,
    message: dict[str, Any],
    *,
    event: str,
    status: str,
    turn_id: str,
    active_task: dict[str, Any] | None = None,
) -> None:
    s = _service()
    s._SESSION_CYCLE_PROJECTION_EXECUTOR.submit(
        s._run_session_cycle_message_projection,
        str(session_id or "").strip(),
        copy.deepcopy(message),
        event=str(event or "").strip(),
        status=str(status or "").strip(),
        turn_id=str(turn_id or "").strip(),
        active_task=copy.deepcopy(active_task) if isinstance(active_task, dict) else None,
    )


def _supervised_completion_marker_present(text: str) -> bool:
    s = _service()
    normalized = str(text or "")
    return "SUPERVISED_FINAL_STATE:" in normalized or "SUPERVISED_INFEASIBLE_OUTCOME:" in normalized


def _supervised_role_for_runtime_context(context: dict[str, Any], agent_instance: dict[str, Any] | None) -> str:
    s = _service()
    if str(context.get("user_message_source") or "").strip() != "supervised_evolution":
        return ""
    candidates: list[Any] = [
        context.get("message_metadata"),
        context.get("supervised_context"),
        (agent_instance or {}).get("metadata") if isinstance(agent_instance, dict) else {},
    ]
    for payload in candidates:
        if not isinstance(payload, dict):
            continue
        for key in ("supervisedRole", "role", "supervised_role"):
            role = str(payload.get(key) or "").strip()
            if role:
                return role
    return ""


def _supervised_workspace_override_path(context: dict[str, Any]) -> Path | None:
    """Return a per-turn candidate worktree override for supervised hidden sessions."""
    s = _service()

    if str(context.get("user_message_source") or "").strip() != "supervised_evolution":
        return None
    candidates: list[Any] = [
        context.get("message_metadata"),
        context.get("supervised_context"),
    ]
    raw_path = ""
    for payload in candidates:
        if not isinstance(payload, dict):
            continue
        for key in ("workspaceOverride", "workspace_override", "toolWorkspaceOverride", "tool_workspace_override"):
            value = str(payload.get(key) or "").strip()
            if value:
                raw_path = value
                break
        if raw_path:
            break
    if not raw_path:
        return None
    try:
        candidate_path = Path(raw_path).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise s.SessionValidationError(f"Invalid supervised workspace override: {raw_path}") from exc
    if not candidate_path.exists():
        raise s.SessionValidationError(f"Supervised workspace override does not exist: {candidate_path}")
    if not candidate_path.is_dir():
        raise s.SessionValidationError(f"Supervised workspace override is not a directory: {candidate_path}")
    return candidate_path


def _task_goal_dedupe_key(value: Any) -> str:
    s = _service()
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def _thought_duplicates_reply(thought: str, reply: str) -> bool:
    s = _service()
    thought_compact = re.sub(r"\s+", " ", str(thought or "")).strip()
    reply_compact = re.sub(r"\s+", " ", str(reply or "")).strip()
    if not thought_compact or not reply_compact:
        return False
    if thought_compact == reply_compact:
        return True
    if thought_compact in reply_compact or reply_compact in thought_compact:
        shorter = min(len(thought_compact), len(reply_compact))
        longer = max(len(thought_compact), len(reply_compact))
        return shorter >= max(24, int(longer * 0.75))
    return False


def _trim_tool_detail_text(value: Any, *, max_chars: int = 1200, max_lines: int = 12) -> str:
    s = _service()
    text = str(value or "").strip()
    if not text:
        return ""
    if "\n" not in text and "\r" not in text:
        if len(text) > max_chars:
            return text[: max_chars - 1].rstrip() + "…"
        return text
    lines = text.splitlines()
    text = "\n".join(line.rstrip() for line in lines[:max_lines]).strip()
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _truncate_session_ledger_before_message(session_id: str, message: dict[str, Any]) -> None:
    s = _service()
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    event_id = str(metadata.get("eventId") or "").strip()
    if not event_id:
        return
    events = s._load_session_conversation_events_cached(session_id)
    target_index = -1
    target_turn_id = ""
    for index, event in enumerate(events):
        if str(getattr(event, "event_id", "") or "").strip() != event_id:
            continue
        target_index = index
        target_turn_id = str(getattr(event, "turn_id", "") or "").strip()
        break
    if target_index < 0:
        return
    truncate_index = target_index
    if target_turn_id:
        for index, event in enumerate(events):
            if str(getattr(event, "turn_id", "") or "").strip() == target_turn_id:
                truncate_index = index
                break
    s.rewrite_conversation_events(s.PROJECT_ROOT, session_id, events[:truncate_index])
    s._invalidate_session_conversation_events_cache(session_id)


def _validate_user_message_not_encoding_replacement(message: str, *, lang: str) -> None:
    s = _service()
    if not s._looks_like_encoding_replacement_message(message):
        return
    s._record_session_message_encoding_rejected(message)
    raise s.SessionValidationError(
        s.text_for(
            lang,
            zh="消息看起来已在进入后端前发生编码损坏，请刷新页面后重新输入原始中文。",
            en="The message appears to have been corrupted before it reached the backend. Refresh the page and re-enter the original text.",
        )
    )


def active_session_has_write_leases() -> bool:
    s = _service()
    for run in s.list_active_session_work_runs():
        leases = set(s.leases_for_snapshot(run))
        if leases.intersection({s.WORKTREE_WRITE_LEASE, s.MEMORY_WRITE_LEASE}):
            return True
    return False


def has_running_sessions() -> bool:
    """Return whether any web chat session turn is currently active."""
    s = _service()

    with s._RUNNING_SESSIONS_LOCK:
        return bool(s._RUNNING_SESSION_IDS)


def load_session_conversation_events_snapshot(session_id: str) -> list[Any]:
    """Return the current session ledger snapshot through the shared signature cache."""
    s = _service()

    return s._journal_bridge.load_session_conversation_events_snapshot(
        session_id,
        project_root=s.PROJECT_ROOT,
    )
