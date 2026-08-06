"""Invoke a project directory Agent as a synchronous sub-agent tool.

Host agents (Codex / Claude Code / Cursor / CLI) call this service through the
MCP stdio server or CLI. Execution reuses the existing chat session hot path:
create session → submit message → wait for turn completion → return summary.

v1 is single-round delegation (one tool call = one agent turn).
"""

from __future__ import annotations

import time
from typing import Any, Callable

from core.web.services import agent_directory_service, session_service
from core.web.services.session import tool_approvals as tool_approvals_service


DEFAULT_TIMEOUT_SECONDS = 600.0
MIN_TIMEOUT_SECONDS = 5.0
MAX_TIMEOUT_SECONDS = 1800.0
DEFAULT_POLL_SECONDS = 0.75
# Tighter than full workbench user default when callers omit mode.
DEFAULT_PERMISSION_MODE = "auto_review"
_VALID_PERMISSION_MODES = frozenset({"auto_review", "full_access", "request_approval"})
_TERMINAL_PHASES = frozenset(
    {
        "idle",
        "ready",
        "completed",
        "failed",
        "error",
        "interrupted",
        "stopped",
        "cancelled",
    }
)
_BUSY_PHASES = frozenset({"running", "queued", "stopping", "busy", "working"})


class ProjectAgentToolError(ValueError):
    """Invalid tool arguments or unrecoverable invoke failure."""


def list_project_agents_for_tool(
    *,
    include_archived: bool = False,
    list_agents_fn: Callable[..., list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Return a compact Agent catalog for host tool discovery."""

    list_fn = list_agents_fn or agent_directory_service.list_agents
    agents = list_fn(include_archived=include_archived, detail="summary")
    items: list[dict[str, Any]] = []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agentId") or agent.get("id") or "").strip()
        if not agent_id:
            continue
        items.append(
            {
                "agentId": agent_id,
                "agentCode": str(agent.get("agentCode") or "").strip(),
                "displayName": str(
                    agent.get("displayName") or agent.get("name") or agent_id
                ).strip(),
                "status": str(agent.get("status") or "active").strip() or "active",
                "role": str(agent.get("role") or agent.get("roleKey") or "").strip(),
                "permissionPreset": str(
                    agent.get("permissionPreset") or agent.get("permission_preset") or ""
                ).strip(),
            }
        )
    items.sort(key=lambda item: (item.get("displayName") or item["agentId"]).lower())
    return {
        "status": "ok",
        "count": len(items),
        "agents": items,
    }


def run_project_agent_tool(
    *,
    agent_id: str = "",
    agent_code: str = "",
    task: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    permission_mode: str = DEFAULT_PERMISSION_MODE,
    title: str = "",
    auto_resolve_approvals: bool = True,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    create_session_fn: Callable[..., dict[str, Any]] | None = None,
    submit_message_fn: Callable[..., dict[str, Any]] | None = None,
    get_detail_fn: Callable[..., dict[str, Any] | None] | None = None,
    get_agent_fn: Callable[..., dict[str, Any] | None] | None = None,
    list_agents_fn: Callable[..., list[dict[str, Any]]] | None = None,
    list_approvals_fn: Callable[..., list[dict[str, Any]]] | None = None,
    resolve_approval_fn: Callable[..., dict[str, Any]] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    monotonic_fn: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Synchronously run one task against a project Agent and return a summary.

    ``permission_mode`` defaults to ``auto_review`` (tighter than ``full_access``).
    When ``auto_resolve_approvals`` is true, pending tool approvals are accepted so
    the call can finish without a UI (required for headless host agents).
    """

    normalized_task = str(task or "").strip()
    if not normalized_task:
        raise ProjectAgentToolError("task is required")

    timeout = _clamp_timeout(timeout_seconds)
    mode = str(permission_mode or DEFAULT_PERMISSION_MODE).strip().lower() or DEFAULT_PERMISSION_MODE
    if mode not in _VALID_PERMISSION_MODES:
        raise ProjectAgentToolError(
            f"unsupported permission_mode: {permission_mode}; "
            f"use one of {', '.join(sorted(_VALID_PERMISSION_MODES))}"
        )

    get_agent = get_agent_fn or agent_directory_service.get_agent
    list_agents = list_agents_fn or agent_directory_service.list_agents
    agent = _resolve_agent(
        agent_id=agent_id,
        agent_code=agent_code,
        get_agent_fn=get_agent,
        list_agents_fn=list_agents,
    )
    resolved_agent_id = str(agent.get("agentId") or agent.get("id") or "").strip()
    agent_name = str(agent.get("displayName") or agent.get("agentCode") or resolved_agent_id).strip()

    create_session = create_session_fn or session_service.create_chat_session
    submit_message = submit_message_fn or session_service.submit_session_message
    get_detail = get_detail_fn or session_service.get_session_detail
    list_approvals = list_approvals_fn or tool_approvals_service.list_tool_approval_requests
    resolve_approval = resolve_approval_fn or (
        lambda session_id, request_id, decision: tool_approvals_service.resolve_tool_approval_request(
            session_id,
            request_id,
            decision=decision,
        )
    )
    sleep = sleep_fn or time.sleep
    monotonic = monotonic_fn or time.monotonic

    session_title = str(title or "").strip() or f"[tool] {agent_name}"
    session = create_session(
        agent_id=resolved_agent_id,
        title=session_title[:160],
        created_by="external_tool",
        lightweight=True,
    )
    session_id = str(
        session.get("sessionId")
        or session.get("conversationId")
        or session.get("id")
        or ""
    ).strip()
    if not session_id:
        raise ProjectAgentToolError("create_chat_session returned no sessionId")

    submit_result = submit_message(
        session_id,
        normalized_task,
        message_source="external_project_agent_tool",
        message_metadata={
            "source": "project_agent_tool",
            "permissionMode": mode,
            "autoResolveApprovals": bool(auto_resolve_approvals),
        },
        lightweight_response=True,
        include_started_turn_id=True,
    )
    turn_id = str(
        submit_result.get("turnId")
        or submit_result.get("startedTurnId")
        or submit_result.get("activeTurnId")
        or ""
    ).strip()

    deadline = monotonic() + timeout
    last_detail: dict[str, Any] | None = None
    approval_auto_count = 0
    while monotonic() < deadline:
        if auto_resolve_approvals:
            approval_auto_count += _auto_accept_pending_approvals(
                session_id,
                list_approvals_fn=list_approvals,
                resolve_approval_fn=resolve_approval,
            )
        detail = get_detail(session_id, message_limit=40, include_secondary=False)
        if isinstance(detail, dict):
            last_detail = detail
            phase = _session_phase(detail)
            if phase in _BUSY_PHASES:
                sleep(max(0.1, float(poll_seconds)))
                continue
            if phase in _TERMINAL_PHASES or not phase:
                # Allow one more short wait if a turn just started and phase lags.
                if turn_id and not _turn_looks_settled(detail, turn_id):
                    sleep(max(0.1, float(poll_seconds)))
                    continue
                return _build_success_result(
                    agent=agent,
                    session_id=session_id,
                    turn_id=turn_id,
                    task=normalized_task,
                    permission_mode=mode,
                    detail=detail,
                    approval_auto_count=approval_auto_count,
                )
        sleep(max(0.1, float(poll_seconds)))

    return {
        "status": "error",
        "code": "TIMEOUT",
        "message": f"project agent did not finish within {timeout:.0f}s",
        "agentId": resolved_agent_id,
        "agentName": agent_name,
        "sessionId": session_id,
        "turnId": turn_id,
        "permissionMode": mode,
        "task": normalized_task,
        "approvalAutoAccepted": approval_auto_count,
        "partialReply": _extract_latest_assistant_text(last_detail or {}),
        "sessionStatus": _session_phase(last_detail or {}),
    }


def _resolve_agent(
    *,
    agent_id: str,
    agent_code: str,
    get_agent_fn: Callable[..., dict[str, Any] | None],
    list_agents_fn: Callable[..., list[dict[str, Any]]],
) -> dict[str, Any]:
    normalized_id = str(agent_id or "").strip()
    normalized_code = str(agent_code or "").strip()
    if not normalized_id and not normalized_code:
        raise ProjectAgentToolError("agent_id or agent_code is required")

    if normalized_id:
        agent = get_agent_fn(normalized_id, include_archived=False)
        if agent:
            return agent
        # Some stores accept code in the same lookup path.
        agent = get_agent_fn(normalized_id, include_archived=False)
        if agent:
            return agent

    if normalized_code or normalized_id:
        needle = (normalized_code or normalized_id).lower()
        for item in list_agents_fn(include_archived=False, detail="summary"):
            if not isinstance(item, dict):
                continue
            code = str(item.get("agentCode") or "").strip().lower()
            name = str(item.get("displayName") or item.get("name") or "").strip().lower()
            item_id = str(item.get("agentId") or item.get("id") or "").strip()
            if needle in {code, name, item_id.lower()}:
                full = get_agent_fn(item_id, include_archived=False) if item_id else item
                if full:
                    return full
                return item

    raise ProjectAgentToolError(
        f"agent not found: agent_id={agent_id!r} agent_code={agent_code!r}"
    )


def _clamp_timeout(value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    return max(MIN_TIMEOUT_SECONDS, min(timeout, MAX_TIMEOUT_SECONDS))


def _session_phase(detail: dict[str, Any]) -> str:
    for key in ("status", "currentPhase", "phase", "childStatus"):
        phase = str(detail.get(key) or "").strip().lower()
        if phase:
            return phase
    return ""


def _turn_looks_settled(detail: dict[str, Any], turn_id: str) -> bool:
    active = str(detail.get("activeTurnId") or detail.get("active_turn_id") or "").strip()
    if active and active == turn_id:
        return False
    if active and active != turn_id:
        return True
    # No active turn reported → treat as settled once we have any assistant reply.
    return bool(_extract_latest_assistant_text(detail))


def _auto_accept_pending_approvals(
    session_id: str,
    *,
    list_approvals_fn: Callable[..., list[dict[str, Any]]],
    resolve_approval_fn: Callable[..., dict[str, Any]],
) -> int:
    accepted = 0
    try:
        pending = list_approvals_fn(session_id, status="pending")
    except TypeError:
        pending = list_approvals_fn(session_id)
    except Exception:
        return 0
    for item in pending or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "").strip().lower() not in {"", "pending"}:
            continue
        request_id = str(item.get("requestId") or item.get("id") or "").strip()
        if not request_id:
            continue
        try:
            resolve_approval_fn(session_id, request_id, "accept")
            accepted += 1
        except Exception:
            continue
    return accepted


def _extract_latest_assistant_text(detail: dict[str, Any]) -> str:
    messages = detail.get("messages") or detail.get("timelineMessages") or []
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or message.get("speaker") or "").strip().lower()
        if role not in {"assistant", "agent", "system_assistant"}:
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str) and block.strip():
                    parts.append(block.strip())
                elif isinstance(block, dict):
                    text = str(block.get("text") or block.get("content") or "").strip()
                    if text:
                        parts.append(text)
            if parts:
                return "\n".join(parts).strip()
    # Fallback: last reply fields on detail
    for key in ("lastAssistantMessage", "assistantReply", "reply"):
        text = str(detail.get(key) or "").strip()
        if text:
            return text
    return ""


def _build_success_result(
    *,
    agent: dict[str, Any],
    session_id: str,
    turn_id: str,
    task: str,
    permission_mode: str,
    detail: dict[str, Any],
    approval_auto_count: int,
) -> dict[str, Any]:
    agent_id = str(agent.get("agentId") or agent.get("id") or "").strip()
    agent_name = str(agent.get("displayName") or agent.get("agentCode") or agent_id).strip()
    reply = _extract_latest_assistant_text(detail)
    phase = _session_phase(detail)
    status = "ok" if reply else "ok_empty"
    return {
        "status": status,
        "code": "COMPLETED" if reply else "COMPLETED_EMPTY_REPLY",
        "agentId": agent_id,
        "agentCode": str(agent.get("agentCode") or "").strip(),
        "agentName": agent_name,
        "sessionId": session_id,
        "turnId": turn_id,
        "permissionMode": permission_mode,
        "task": task,
        "reply": reply,
        "sessionStatus": phase,
        "approvalAutoAccepted": approval_auto_count,
        "messageCount": len(detail.get("messages") or [])
        if isinstance(detail.get("messages"), list)
        else 0,
    }
