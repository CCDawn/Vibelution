#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Governed Agent / Session lifecycle tools for project operations."""

from __future__ import annotations

import json
from typing import Any

from core.logging import debug as _debug_logger


def _json_dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _json_result(
    *,
    ok: bool,
    status: str,
    message: str = "",
    error: str = "",
    **fields: Any,
) -> str:
    payload: dict[str, Any] = {
        "ok": bool(ok),
        "status": str(status or "").strip() or ("ok" if ok else "error"),
        "error": str(error or "").strip(),
        "message": str(message or "").strip(),
    }
    payload.update({key: value for key, value in fields.items() if value is not None})
    return _json_dump(payload)


def _parse_json_object(raw: Any, *, field_name: str) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except Exception as exc:
        raise ValueError(f"{field_name} must be valid JSON: {type(exc).__name__}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must be a JSON object.")
    return dict(parsed)


def _parse_json_string_list(raw: Any, *, field_name: str) -> list[str]:
    if isinstance(raw, (list, tuple)):
        parsed = list(raw)
    else:
        text = str(raw or "").strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception as exc:
            raise ValueError(f"{field_name} must be valid JSON: {type(exc).__name__}") from exc
    if not isinstance(parsed, list):
        raise ValueError(f"{field_name} must be a JSON array.")
    values: list[str] = []
    for item in parsed:
        normalized = str(item or "").strip()
        if normalized and normalized not in values:
            values.append(normalized)
    return values


def _resolve_llm_bindings(model_id: str, llm_bindings_json: str) -> dict[str, Any]:
    if str(llm_bindings_json or "").strip():
        return _parse_json_object(llm_bindings_json, field_name="llm_bindings_json")
    normalized_model_id = str(model_id or "").strip()
    if not normalized_model_id:
        return {}
    return {"dialogue": {"modelId": normalized_model_id}}


def _current_agent_id(explicit_agent_id: str = "") -> str:
    normalized = str(explicit_agent_id or "").strip()
    if normalized:
        return normalized
    try:
        from core.web.services.agent_directory_service import current_agent_runtime

        runtime = current_agent_runtime()
    except Exception as exc:
        _debug_logger.warning(
            f"[项目操作工具] 获取当前 Agent runtime 失败: {type(exc).__name__}: {exc}"
        )
        runtime = {}
    return str((runtime or {}).get("agentId") or "").strip()


def _current_agent_target(explicit_agent_id: str = "") -> str:
    """Resolve a self-owned target; runtime Agents cannot impersonate another inbox owner."""

    explicit = str(explicit_agent_id or "").strip()
    current = _current_agent_id()
    if current and explicit and explicit != current:
        raise PermissionError("Current Agent can only access its own inbox.")
    return current or explicit


def agent_create_tool(
    display_name: str,
    primary_mode: str = "",
    role_key: str = "",
    prompt_template_id: str = "",
    model_id: str = "",
    llm_bindings_json: str = "",
    persona_profile_json: str = "",
    task_profile_json: str = "",
    tool_policy_json: str = "",
    metadata_json: str = "",
    context_compression_policy_json: str = "",
    avatar_image_path: str = "",
) -> str:
    """Create a governed Agent using the same semantics as POST /api/agents."""

    try:
        from core.web.services.agent_directory_service import AgentDirectoryError
        from core.web.services.agent_operation_service import create_agent_from_catalog_request

        agent = create_agent_from_catalog_request(
            display_name=display_name,
            llm_bindings=_resolve_llm_bindings(model_id, llm_bindings_json),
            primary_mode=primary_mode,
            role_key=role_key,
            prompt_template_id=prompt_template_id,
            context_compression_policy=_parse_json_object(
                context_compression_policy_json,
                field_name="context_compression_policy_json",
            ),
            persona_profile=_parse_json_object(persona_profile_json, field_name="persona_profile_json"),
            task_profile=_parse_json_object(task_profile_json, field_name="task_profile_json"),
            tool_policy=_parse_json_object(tool_policy_json, field_name="tool_policy_json"),
            metadata=_parse_json_object(metadata_json, field_name="metadata_json"),
            avatar_image_path=avatar_image_path,
            source="agent_create_tool",
        )
    except ValueError as exc:
        return _json_result(
            ok=False,
            status="error",
            error="invalid_input",
            message=str(exc),
        )
    except AgentDirectoryError as exc:
        return _json_result(
            ok=False,
            status="error",
            error="validation_error",
            message=str(exc),
        )
    except Exception as exc:
        return _json_result(
            ok=False,
            status="error",
            error=exc.__class__.__name__,
            message=str(exc),
        )

    agent_id = str(agent.get("agentId") or "").strip()
    return _json_result(
        ok=True,
        status="ok",
        message="Agent created.",
        error="",
        agentId=agent_id,
        directSessionId=str(agent.get("directSessionId") or "").strip(),
        agent=agent,
    )


def agent_update_tool(
    agent_id: str,
    updates_json: str,
    expected_updated_at: str = "",
    expected_config_revision: int = -1,
    source_draft_id: str = "",
) -> str:
    """Update non-lifecycle Agent configuration using PATCH-compatible field names."""

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return _json_result(
            ok=False,
            status="error",
            error="agent_id_required",
            message="agent_id is required.",
        )
    try:
        updates = _parse_json_object(updates_json, field_name="updates_json")
    except ValueError as exc:
        return _json_result(ok=False, status="error", error="invalid_input", message=str(exc), agentId=normalized_agent_id)
    try:
        from core.web.services import session_service
        from core.web.services.agent_directory_service import (
            AgentDirectoryError,
            AgentNotFoundError,
            AgentStateConflictError,
        )
        from core.web.services.agent_operation_service import update_agent_from_catalog_request

        agent = update_agent_from_catalog_request(
            normalized_agent_id,
            updates=updates,
            expected_updated_at=expected_updated_at,
            expected_config_revision=(
                int(expected_config_revision)
                if int(expected_config_revision) >= 0
                else None
            ),
            source_draft_id=source_draft_id,
            source="agent_update_tool",
        )
    except AgentNotFoundError as exc:
        return _json_result(ok=False, status="error", error="not_found", message=str(exc), agentId=normalized_agent_id)
    except AgentStateConflictError as exc:
        return _json_result(ok=False, status="blocked", error="conflict", message=str(exc), agentId=normalized_agent_id)
    except session_service.SessionBusyError as exc:
        return _json_result(ok=False, status="blocked", error="busy", message=str(exc), agentId=normalized_agent_id)
    except AgentDirectoryError as exc:
        return _json_result(ok=False, status="error", error="validation_error", message=str(exc), agentId=normalized_agent_id)
    except Exception as exc:
        return _json_result(ok=False, status="error", error=exc.__class__.__name__, message=str(exc), agentId=normalized_agent_id)

    return _json_result(
        ok=True,
        status="ok",
        message="Agent updated.",
        error="",
        agentId=normalized_agent_id,
        agent=agent,
        publishedConfigChange=agent.get("publishedConfigChange"),
    )


def agent_archive_tool(agent_id: str) -> str:
    """Archive one Agent through the authoritative bulk archive lifecycle."""

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return _json_result(
            ok=False,
            status="error",
            error="agent_id_required",
            message="agent_id is required.",
        )
    try:
        from core.web.services.agent_bulk_delete_service import (
            AgentLifecycleBusyError,
            bulk_archive_agents,
        )

        result = bulk_archive_agents([normalized_agent_id])
    except AgentLifecycleBusyError as exc:
        return _json_result(
            ok=False,
            status="blocked",
            error="busy",
            message=str(exc),
            agentId=normalized_agent_id,
        )
    except Exception as exc:
        return _json_result(
            ok=False,
            status="error",
            error=exc.__class__.__name__,
            message=str(exc),
            agentId=normalized_agent_id,
        )

    success_items = list(result.get("success") or [])
    if success_items:
        archived = success_items[0]
        from core.web.services.agent_config_workspace_service import invalidate_agent_config_workspace_cache

        invalidate_agent_config_workspace_cache()
        return _json_result(
            ok=True,
            status="ok",
            message="Agent archived.",
            error="",
            agentId=normalized_agent_id,
            archiveSummary=archived.get("archiveSummary"),
            agent=archived,
        )

    skipped_items = list(result.get("skipped") or [])
    if skipped_items:
        item = skipped_items[0]
        reason = str(item.get("reason") or "blocked").strip()
        status = "blocked" if reason in {"protected", "busy", "not_found"} else "error"
        return _json_result(
            ok=False,
            status=status,
            error=reason or "archive_blocked",
            message=str(item.get("message") or "Agent archive was not allowed."),
            agentId=normalized_agent_id,
        )

    failed_items = list(result.get("failed") or [])
    if failed_items:
        item = failed_items[0]
        reason = str(item.get("reason") or "archive_failed").strip()
        status = "blocked" if reason == "busy" else "error"
        return _json_result(
            ok=False,
            status=status,
            error=reason or "archive_failed",
            message=str(item.get("message") or "Agent archive failed."),
            agentId=normalized_agent_id,
        )

    return _json_result(
        ok=False,
        status="error",
        error="archive_failed",
        message="Agent archive did not complete.",
        agentId=normalized_agent_id,
    )


def agent_reset_tool(
    agent_id: str,
    clear_runtime_state: bool = True,
    reset_direct_session: bool = True,
    direct_session_id: str = "",
    reset_persona_profile: bool = False,
    reset_task_profile: bool = False,
    reset_tool_policy: bool = False,
    reset_memory_policy: bool = False,
    reset_runtime_policy: bool = False,
) -> str:
    """Reset one Agent through reset_agent_instance."""

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return _json_result(
            ok=False,
            status="error",
            error="agent_id_required",
            message="agent_id is required.",
        )
    try:
        from core.web.services.agent_directory_service import (
            AgentDirectoryError,
            AgentNotFoundError,
            reset_agent_instance,
        )

        reset_summary = reset_agent_instance(
            normalized_agent_id,
            clear_runtime_state=bool(clear_runtime_state),
            reset_direct_session=bool(reset_direct_session),
            direct_session_id=direct_session_id,
            reset_persona_profile=bool(reset_persona_profile),
            reset_task_profile=bool(reset_task_profile),
            reset_tool_policy=bool(reset_tool_policy),
            reset_memory_policy=bool(reset_memory_policy),
            reset_runtime_policy=bool(reset_runtime_policy),
        )
    except AgentNotFoundError as exc:
        return _json_result(
            ok=False,
            status="error",
            error="not_found",
            message=str(exc),
            agentId=normalized_agent_id,
        )
    except AgentDirectoryError as exc:
        return _json_result(
            ok=False,
            status="error",
            error="validation_error",
            message=str(exc),
            agentId=normalized_agent_id,
        )
    except Exception as exc:
        return _json_result(
            ok=False,
            status="error",
            error=exc.__class__.__name__,
            message=str(exc),
            agentId=normalized_agent_id,
        )

    from core.web.services.agent_config_workspace_service import invalidate_agent_config_workspace_cache

    invalidate_agent_config_workspace_cache()
    return _json_result(
        ok=True,
        status="ok",
        message="Agent reset completed.",
        error="",
        agentId=normalized_agent_id,
        resetSummary=reset_summary,
    )


def session_create_tool(
    title: str = "",
    agent_id: str = "",
) -> str:
    """Create a root session for an existing Agent; never creates a new Agent."""

    normalized_agent_id = _current_agent_id(agent_id)
    if not normalized_agent_id:
        return _json_result(
            ok=False,
            status="error",
            error="agent_id_required",
            message="agent_id is required when no current Agent runtime is bound.",
        )
    try:
        from core.web.services import session_service
        from core.web.services.agent_directory_service import get_agent

        if not get_agent(normalized_agent_id, include_archived=False):
            return _json_result(
                ok=False,
                status="error",
                error="agent_not_found",
                message=f"Agent not found: {normalized_agent_id}",
                agentId=normalized_agent_id,
            )
        session = session_service.create_chat_session(
            title=str(title or "").strip(),
            agent_id=normalized_agent_id,
            created_by="session_create_tool",
        )
    except Exception as exc:
        return _json_result(
            ok=False,
            status="error",
            error=exc.__class__.__name__,
            message=str(exc),
            agentId=normalized_agent_id,
        )

    session_id = str(session.get("id") or session.get("sessionId") or "").strip()
    return _json_result(
        ok=True,
        status="ok",
        message="Session created.",
        error="",
        agentId=normalized_agent_id,
        sessionId=session_id,
        session=session,
    )


def session_update_tool(
    session_id: str,
    title: str = "",
    agent_id: str = "",
) -> str:
    """Update one Session title and/or bind it to an existing active Agent."""

    normalized_session_id = str(session_id or "").strip()
    normalized_title = str(title or "").strip()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_session_id:
        return _json_result(ok=False, status="error", error="session_id_required", message="session_id is required.")
    if not normalized_title and not normalized_agent_id:
        return _json_result(
            ok=False,
            status="error",
            error="update_required",
            message="title or agent_id is required.",
            sessionId=normalized_session_id,
        )
    try:
        from core.web.services import session_service

        session = session_service.update_chat_session(
            normalized_session_id,
            title=normalized_title or None,
            agent_id=normalized_agent_id or None,
        )
    except session_service.SessionNotFoundError as exc:
        return _json_result(ok=False, status="error", error="not_found", message=str(exc), sessionId=normalized_session_id)
    except session_service.SessionBusyError as exc:
        return _json_result(ok=False, status="blocked", error="busy", message=str(exc), sessionId=normalized_session_id)
    except session_service.SessionValidationError as exc:
        return _json_result(ok=False, status="error", error="validation_error", message=str(exc), sessionId=normalized_session_id)
    except Exception as exc:
        return _json_result(ok=False, status="error", error=exc.__class__.__name__, message=str(exc), sessionId=normalized_session_id)

    return _json_result(
        ok=True,
        status="ok",
        message="Session updated.",
        error="",
        sessionId=normalized_session_id,
        agentId=str(session.get("agentId") or "").strip(),
        session=session,
    )


def session_stop_tool(session_id: str, turn_id: str) -> str:
    """Request stop for the active turn; requires both session_id and turn_id."""

    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_session_id:
        return _json_result(
            ok=False,
            status="error",
            error="session_id_required",
            message="session_id is required.",
        )
    if not normalized_turn_id:
        return _json_result(
            ok=False,
            status="error",
            error="turn_id_required",
            message="turn_id is required.",
            sessionId=normalized_session_id,
        )
    try:
        from core.web.services import session_service

        detail = session_service.request_stop_session_turn(
            normalized_session_id,
            expected_turn_id=normalized_turn_id,
        )
    except session_service.SessionNotFoundError as exc:
        return _json_result(
            ok=False,
            status="error",
            error="not_found",
            message=str(exc),
            sessionId=normalized_session_id,
            turnId=normalized_turn_id,
        )
    except session_service.SessionBusyError as exc:
        return _json_result(
            ok=False,
            status="blocked",
            error="busy",
            message=str(exc),
            sessionId=normalized_session_id,
            turnId=normalized_turn_id,
        )
    except Exception as exc:
        return _json_result(
            ok=False,
            status="error",
            error=exc.__class__.__name__,
            message=str(exc),
            sessionId=normalized_session_id,
            turnId=normalized_turn_id,
        )

    return _json_result(
        ok=True,
        status="ok",
        message="Stop request accepted.",
        error="",
        sessionId=normalized_session_id,
        turnId=normalized_turn_id,
        session=detail,
    )


def session_delete_tool(session_id: str) -> str:
    """Delete one session through delete_chat_session."""

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return _json_result(
            ok=False,
            status="error",
            error="session_id_required",
            message="session_id is required.",
        )
    try:
        from core.web.services import session_service

        result = session_service.delete_chat_session(normalized_session_id)
    except session_service.SessionNotFoundError as exc:
        return _json_result(
            ok=False,
            status="error",
            error="not_found",
            message=str(exc),
            sessionId=normalized_session_id,
        )
    except session_service.SessionBusyError as exc:
        return _json_result(
            ok=False,
            status="blocked",
            error="busy",
            message=str(exc),
            sessionId=normalized_session_id,
        )
    except session_service.SessionValidationError as exc:
        return _json_result(
            ok=False,
            status="error",
            error="validation_error",
            message=str(exc),
            sessionId=normalized_session_id,
        )
    except Exception as exc:
        return _json_result(
            ok=False,
            status="error",
            error=exc.__class__.__name__,
            message=str(exc),
            sessionId=normalized_session_id,
        )

    return _json_result(
        ok=True,
        status="ok",
        message="Session deleted.",
        error="",
        sessionId=normalized_session_id,
        deletedSessionId=str(result.get("deletedSessionId") or normalized_session_id).strip(),
        nextActiveSessionId=str(result.get("nextActiveSessionId") or "").strip(),
        replacementDirectSessionId=str(result.get("replacementDirectSessionId") or "").strip(),
        deleteResult=result,
    )


def agent_inbox_list_tool(
    agent_id: str = "",
    status: str = "pending",
    limit: int = 20,
) -> str:
    """List a bounded Agent inbox through the authoritative directory service."""

    try:
        normalized_agent_id = _current_agent_target(agent_id)
    except PermissionError as exc:
        return _json_result(ok=False, status="blocked", error="permission_denied", message=str(exc), agentId=str(agent_id or "").strip())
    if not normalized_agent_id:
        return _json_result(ok=False, status="error", error="agent_id_required", message="agent_id is required when no current Agent runtime is bound.")
    try:
        from core.web.services.agent_directory_service import get_agent, list_agent_inbox_messages_for_agent

        if not get_agent(normalized_agent_id, include_archived=True):
            return _json_result(ok=False, status="error", error="not_found", message=f"Agent not found: {normalized_agent_id}", agentId=normalized_agent_id)
        normalized_limit = max(1, min(int(limit or 20), 100))
        messages = list_agent_inbox_messages_for_agent(
            normalized_agent_id,
            status=str(status or "").strip(),
            limit=normalized_limit,
        )
    except (TypeError, ValueError) as exc:
        return _json_result(ok=False, status="error", error="invalid_input", message=str(exc), agentId=normalized_agent_id)
    except Exception as exc:
        return _json_result(ok=False, status="error", error=exc.__class__.__name__, message=str(exc), agentId=normalized_agent_id)
    return _json_result(
        ok=True,
        status="ok",
        message="Agent inbox listed.",
        error="",
        agentId=normalized_agent_id,
        messageCount=len(messages),
        messages=messages,
    )


def agent_message_consume_tool(
    message_id: str,
    agent_id: str = "",
    consumed_by_session_id: str = "",
    consumed_by_turn_id: str = "",
) -> str:
    """Consume one Agent inbox message."""

    try:
        normalized_agent_id = _current_agent_target(agent_id)
    except PermissionError as exc:
        return _json_result(ok=False, status="blocked", error="permission_denied", message=str(exc), agentId=str(agent_id or "").strip(), messageId=str(message_id or "").strip())
    normalized_message_id = str(message_id or "").strip()
    if not normalized_agent_id:
        return _json_result(ok=False, status="error", error="agent_id_required", message="agent_id is required when no current Agent runtime is bound.")
    if not normalized_message_id:
        return _json_result(ok=False, status="error", error="message_id_required", message="message_id is required.", agentId=normalized_agent_id)
    try:
        from core.web.services.agent_directory_service import (
            AgentMessageNotFoundError,
            AgentNotFoundError,
            consume_agent_inbox_message,
        )

        message = consume_agent_inbox_message(
            normalized_agent_id,
            normalized_message_id,
            consumed_by_session_id=consumed_by_session_id,
            consumed_by_turn_id=consumed_by_turn_id,
        )
    except (AgentNotFoundError, AgentMessageNotFoundError) as exc:
        return _json_result(ok=False, status="error", error="not_found", message=str(exc), agentId=normalized_agent_id, messageId=normalized_message_id)
    except Exception as exc:
        return _json_result(ok=False, status="error", error=exc.__class__.__name__, message=str(exc), agentId=normalized_agent_id, messageId=normalized_message_id)
    return _json_result(ok=True, status="ok", message="Agent inbox message consumed.", error="", agentId=normalized_agent_id, messageId=normalized_message_id, inboxMessage=message)


def agent_messages_consume_all_tool(
    agent_id: str = "",
    consumed_by_session_id: str = "",
    consumed_by_turn_id: str = "",
) -> str:
    """Consume every pending message in one Agent inbox."""

    try:
        normalized_agent_id = _current_agent_target(agent_id)
    except PermissionError as exc:
        return _json_result(ok=False, status="blocked", error="permission_denied", message=str(exc), agentId=str(agent_id or "").strip())
    if not normalized_agent_id:
        return _json_result(ok=False, status="error", error="agent_id_required", message="agent_id is required when no current Agent runtime is bound.")
    try:
        from core.web.services.agent_directory_service import AgentNotFoundError, consume_all_agent_inbox_messages

        result = consume_all_agent_inbox_messages(
            normalized_agent_id,
            consumed_by_session_id=consumed_by_session_id,
            consumed_by_turn_id=consumed_by_turn_id,
        )
    except AgentNotFoundError as exc:
        return _json_result(ok=False, status="error", error="not_found", message=str(exc), agentId=normalized_agent_id)
    except Exception as exc:
        return _json_result(ok=False, status="error", error=exc.__class__.__name__, message=str(exc), agentId=normalized_agent_id)
    return _json_result(ok=True, status="ok", message="Agent inbox messages consumed.", error="", consumeResult=result, **result)


def knowledge_base_acl_grant_tool(
    knowledge_base_id: str,
    target_agent_id: str,
    permissions_json: str = '["read", "propose"]',
) -> str:
    """Grant explicit KB permissions as the current authorized owner/reviewer Agent."""

    normalized_kb_id = str(knowledge_base_id or "").strip()
    normalized_target_id = str(target_agent_id or "").strip()
    actor_agent_id = _current_agent_id()
    if not normalized_kb_id:
        return _json_result(ok=False, status="error", error="knowledge_base_id_required", message="knowledge_base_id is required.")
    if not normalized_target_id:
        return _json_result(ok=False, status="error", error="target_agent_id_required", message="target_agent_id is required.", knowledgeBaseId=normalized_kb_id)
    if not actor_agent_id:
        return _json_result(ok=False, status="blocked", error="current_agent_required", message="Current Agent runtime is required; actor identity cannot be supplied by arguments.", knowledgeBaseId=normalized_kb_id, targetAgentId=normalized_target_id)
    try:
        permissions = _parse_json_string_list(permissions_json, field_name="permissions_json")
    except ValueError as exc:
        return _json_result(ok=False, status="error", error="invalid_input", message=str(exc), knowledgeBaseId=normalized_kb_id, targetAgentId=normalized_target_id)
    try:
        from core.web.services.team_knowledge_service import (
            TeamKnowledgeError,
            TeamKnowledgeNotFoundError,
            TeamKnowledgePermissionError,
            grant_knowledge_base_access,
        )

        result = grant_knowledge_base_access(
            normalized_kb_id,
            normalized_target_id,
            permissions=permissions,
            actor_agent_id=actor_agent_id,
        )
    except TeamKnowledgePermissionError as exc:
        return _json_result(ok=False, status="blocked", error="permission_denied", message=str(exc), knowledgeBaseId=normalized_kb_id, targetAgentId=normalized_target_id)
    except TeamKnowledgeNotFoundError as exc:
        return _json_result(ok=False, status="error", error="not_found", message=str(exc), knowledgeBaseId=normalized_kb_id, targetAgentId=normalized_target_id)
    except TeamKnowledgeError as exc:
        return _json_result(ok=False, status="error", error="validation_error", message=str(exc), knowledgeBaseId=normalized_kb_id, targetAgentId=normalized_target_id)
    except Exception as exc:
        return _json_result(ok=False, status="error", error=exc.__class__.__name__, message=str(exc), knowledgeBaseId=normalized_kb_id, targetAgentId=normalized_target_id)
    return _json_result(ok=True, status="ok", message="Knowledge base access granted.", error="", knowledgeBaseId=normalized_kb_id, targetAgentId=normalized_target_id, actorAgentId=actor_agent_id, grantResult=result)
