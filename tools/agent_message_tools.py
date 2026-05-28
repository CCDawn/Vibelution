# -*- coding: utf-8 -*-
"""Agent-to-agent messaging tools."""

from __future__ import annotations

import json
from typing import Any

from core.chat.chat_task_types import trim_lines


def agent_message_tool(
    target_agent: str,
    content: str,
    summary: str = "",
    wake_target: bool = True,
    thread_id: str = "",
    metadata_json: str = "",
) -> str:
    """
    Send a persistent message from the current Agent to another Agent.

    Args:
        target_agent: Target Agent id, stable code such as A002, or unique display name.
        content: Message body for the target Agent.
        summary: Optional short summary.
        wake_target: Whether to wake the target Agent's direct session when it is idle.
        thread_id: Optional conversation thread id.
        metadata_json: Optional JSON object with small structured metadata.

    Returns:
        JSON string with status, message id, target identity, and wake delivery status.
    """

    try:
        from core.web.services import session_service
        from core.web.services.agent_directory_service import (
            current_agent_runtime,
            list_agents,
            write_agent_inbox_message,
        )

        runtime = current_agent_runtime()
        source_agent_id = str(runtime.get("agentId") or "").strip()
        source_session_id = str(runtime.get("sessionId") or "").strip()
        if not source_agent_id:
            return _json_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "error": "agent_runtime_missing",
                    "message": "当前工具需要在已绑定 AgentInstance 的运行时中调用。",
                }
            )

        normalized_target = str(target_agent or "").strip()
        if not normalized_target:
            return _json_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "error": "target_required",
                    "message": "请提供目标 Agent 的 agentId、代号或唯一名称。",
                }
            )

        message_body = trim_lines(str(content or ""), max_lines=20).strip()
        if not message_body:
            return _json_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "error": "content_required",
                    "message": "请提供要发送给目标 Agent 的消息内容。",
                }
            )

        target = _resolve_target_agent(normalized_target, list_agents(include_archived=False))
        if not target.get("ok"):
            return _json_result(target)
        target_agent_payload = target["agent"]
        target_agent_id = str(target_agent_payload.get("agentId") or "").strip()
        if target_agent_id == source_agent_id:
            return _json_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "error": "self_message_blocked",
                    "message": "Agent 私信工具用于发送给其他 Agent，不发送给自己。",
                    "targetAgentId": target_agent_id,
                }
            )

        metadata = _parse_metadata(metadata_json)
        message = write_agent_inbox_message(
            target_agent_id,
            source_agent_id=source_agent_id,
            source_session_id=source_session_id,
            content=message_body,
            summary=summary,
            thread_id=thread_id,
            kind="agent_direct_message",
            created_by="agent_tool",
            metadata=metadata,
        )
        delivery = (
            session_service.wake_agent_for_inbox_message(message)
            if bool(wake_target)
            else {
                "wakeRequested": False,
                "wakeStatus": "not_requested",
                "messageId": message.get("messageId") or message.get("eventId") or "",
                "targetAgentId": message.get("targetAgentId") or "",
                "targetSessionId": message.get("targetSessionId") or "",
                "turnId": "",
                "reason": "",
            }
        )
        _record_agent_message_tool_event(message, delivery)
        return _json_result(
            {
                "ok": True,
                "status": "sent",
                "messageId": message.get("messageId") or "",
                "sourceAgentId": source_agent_id,
                "sourceSessionId": source_session_id,
                "targetAgentId": target_agent_id,
                "targetAgentCode": target_agent_payload.get("agentCode") or "",
                "targetSessionId": target_agent_payload.get("directSessionId") or "",
                "wakeStatus": delivery.get("wakeStatus") or "",
                "delivery": delivery,
            }
        )
    except Exception as exc:
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=2),
            }
        )


def _resolve_target_agent(target: str, agents: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = str(target or "").strip()
    folded = normalized.casefold()
    exact_matches = [
        item for item in agents
        if str(item.get("agentId") or "").strip() == normalized
        or str(item.get("agentCode") or "").strip().casefold() == folded
    ]
    if len(exact_matches) == 1:
        return {"ok": True, "agent": exact_matches[0]}
    if len(exact_matches) > 1:
        return {
            "ok": False,
            "status": "blocked",
            "error": "ambiguous_target",
            "message": "目标 Agent 匹配到多个实例，请改用 agentId。",
        }
    name_matches = [
        item for item in agents
        if str(item.get("displayName") or "").strip().casefold() == folded
    ]
    if len(name_matches) == 1:
        return {"ok": True, "agent": name_matches[0]}
    if len(name_matches) > 1:
        return {
            "ok": False,
            "status": "blocked",
            "error": "ambiguous_target_name",
            "message": "目标名称不唯一，请改用 agentId 或稳定代号。",
        }
    return {
        "ok": False,
        "status": "blocked",
        "error": "target_not_found",
        "message": f"未找到目标 Agent: {normalized}",
    }


def _parse_metadata(metadata_json: str) -> dict[str, Any]:
    raw = str(metadata_json or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw[:500]}
    return payload if isinstance(payload, dict) else {"value": payload}


def _record_agent_message_tool_event(message: dict[str, Any], delivery: dict[str, Any]) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "agent_inbox",
            "tool",
            "agent_inbox.tool_sent",
            message="agent_inbox.tool_sent",
            level="info",
            outcome="sent",
            fields={
                "messageId": str(message.get("messageId") or "").strip(),
                "sourceAgentId": str(message.get("sourceAgentId") or "").strip(),
                "targetAgentId": str(message.get("targetAgentId") or "").strip(),
                "targetSessionId": str(message.get("targetSessionId") or "").strip(),
                "wakeStatus": str(delivery.get("wakeStatus") or "").strip(),
                "turnId": str(delivery.get("turnId") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
