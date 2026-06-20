# -*- coding: utf-8 -*-
"""Agent-to-agent messaging tools."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from core.chat.chat_task_types import trim_lines
from core.logging import debug as _debug_logger


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

    Messages involving explicit research organization Agents are routed through
    the research organization graph policy before any inbox write.

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
        from core.web.services.agent_directory_service import (
            current_agent_runtime,
            get_agent,
            list_agents,
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

        message_body = str(content or "").strip()
        if not message_body:
            return _json_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "error": "content_required",
                    "message": "请提供要发送给目标 Agent 的消息内容。",
                }
            )

        agents = list_agents(include_archived=False)
        target = _resolve_target_agent(normalized_target, agents)
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
        source_agent_payload = get_agent(source_agent_id, include_archived=True) or {}
        research_org_result = _try_send_research_org_message(
            source_agent=source_agent_payload,
            target_agent=target_agent_payload,
            source_agent_id=source_agent_id,
            source_session_id=source_session_id,
            content=message_body,
            summary=summary,
            wake_target=wake_target,
            thread_id=thread_id,
            metadata=metadata,
        )
        if research_org_result is not None:
            return _json_result(research_org_result)

        kernel_result = _send_direct_agent_message_via_kernel(
            source_agent=source_agent_payload,
            target_agent=target_agent_payload,
            source_agent_id=source_agent_id,
            source_session_id=source_session_id,
            target_agent_id=target_agent_id,
            content=message_body,
            summary=summary,
            wake_target=wake_target,
            thread_id=thread_id,
            metadata=metadata,
        )
        kernel_delivery = _first_kernel_delivery(kernel_result, target_agent_id=target_agent_id)
        delivery = _flatten_kernel_delivery(
            kernel_delivery,
            target_agent_id=target_agent_id,
            target_session_id=str(target_agent_payload.get("directSessionId") or "").strip(),
            wake_target=bool(wake_target),
        )
        sent = str(kernel_delivery.get("status") or "").strip() == "delivered"
        message_id = str(delivery.get("messageId") or delivery.get("inboxMessageId") or "").strip()
        tool_message = {
            "messageId": message_id,
            "sourceAgentId": source_agent_id,
            "sourceSessionId": source_session_id,
            "targetAgentId": target_agent_id,
            "targetSessionId": str(delivery.get("targetSessionId") or target_agent_payload.get("directSessionId") or "").strip(),
        }
        kernel_trace = _kernel_trace_fields(kernel_result)
        _record_agent_message_tool_event(
            tool_message,
            delivery,
            route="kernel",
            outcome="sent" if sent else "blocked",
            extra_fields=kernel_trace,
        )
        return _json_result(
            {
                "ok": sent,
                "status": "sent" if sent else "blocked",
                "route": "kernel",
                "messageId": message_id,
                "sourceAgentId": source_agent_id,
                "sourceSessionId": source_session_id,
                "targetAgentId": target_agent_id,
                "targetAgentCode": target_agent_payload.get("agentCode") or "",
                "targetSessionId": target_agent_payload.get("directSessionId") or "",
                "wakeStatus": delivery.get("wakeStatus") or "",
                "reason": delivery.get("reason") or "",
                "delivery": delivery,
                "kernel": kernel_trace,
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
    candidate_labels = _target_agent_lookup_labels(normalized)
    folded_labels = {item.casefold() for item in candidate_labels if item}
    exact_matches = [
        item for item in agents
        if str(item.get("agentId") or "").strip() in candidate_labels
        or str(item.get("agentCode") or "").strip().casefold() in folded_labels
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
        if str(item.get("displayName") or "").strip().casefold() in folded_labels
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


def _target_agent_lookup_labels(target: str) -> list[str]:
    normalized = str(target or "").strip()
    if not normalized:
        return []
    labels: list[str] = [normalized]
    composite_match = re.match(
        r"^\s*(?P<code>A\d{3,})\s*(?:[·•\-\u2013\u2014:：|/]|[\(（])\s*(?P<name>.+?)\s*[\)）]?\s*$",
        normalized,
        flags=re.IGNORECASE,
    )
    if composite_match:
        labels.extend(
            [
                str(composite_match.group("code") or "").strip(),
                str(composite_match.group("name") or "").strip(),
            ]
        )
    paren_match = re.match(r"^\s*(?P<head>.+?)\s*[\(（]\s*(?P<body>.+?)\s*[\)）]\s*$", normalized)
    if paren_match:
        labels.extend(
            [
                str(paren_match.group("head") or "").strip(),
                str(paren_match.group("body") or "").strip(),
            ]
        )

    unique: list[str] = []
    seen: set[str] = set()
    for label in labels:
        clean = str(label or "").strip()
        if not clean:
            continue
        folded = clean.casefold()
        if folded in seen:
            continue
        unique.append(clean)
        seen.add(folded)
    return unique


def _parse_metadata(metadata_json: str) -> dict[str, Any]:
    raw = str(metadata_json or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw[:500]}
    return payload if isinstance(payload, dict) else {"value": payload}


def _send_direct_agent_message_via_kernel(
    *,
    source_agent: dict[str, Any],
    target_agent: dict[str, Any],
    source_agent_id: str,
    source_session_id: str,
    target_agent_id: str,
    content: str,
    summary: str,
    wake_target: bool,
    thread_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    from core.agent_kernel.adapters import submit_agent_message_event

    source_message_id = f"agent-message-tool-{uuid.uuid4().hex}"
    source_agent_code = str(source_agent.get("agentCode") or "").strip()
    target_agent_code = str(target_agent.get("agentCode") or "").strip()
    kernel_metadata = {
        "sourceSurface": "agent_message_tool",
        "sourceSessionId": source_session_id,
        "sourceAgentId": source_agent_id,
        "senderAgentId": source_agent_id,
        "sourceMessageId": source_message_id,
        "agentMessageToolSourceId": source_message_id,
        "inboxKind": "agent_direct_message",
        "messageSummary": trim_lines(str(summary or content or ""), max_lines=4),
        "agentToolMetadataJson": json.dumps(metadata, ensure_ascii=False, sort_keys=True) if metadata else "{}",
    }
    if source_agent_code:
        kernel_metadata["sourceAgentCode"] = source_agent_code
    if target_agent_code:
        kernel_metadata["targetAgentCode"] = target_agent_code
    resolved_thread_id = str(thread_id or f"agent:{source_agent_id}->{target_agent_id}").strip()
    return submit_agent_message_event(
        source="agent_message_tool",
        sender={
            "type": "agent",
            "id": source_agent_id,
            "agentId": source_agent_id,
            "agentCode": source_agent_code,
            "sessionId": source_session_id,
            "displayName": str(source_agent.get("displayName") or "").strip(),
        },
        recipient_agent_ids=[target_agent_id],
        content=content,
        correlation_id=resolved_thread_id,
        wake_target=bool(wake_target),
        metadata=kernel_metadata,
        source_id=source_message_id,
        idempotency_key=f"agent-message-tool:{source_message_id}",
    )


def _first_kernel_delivery(kernel_result: dict[str, Any], *, target_agent_id: str) -> dict[str, Any]:
    outcome = kernel_result.get("outcome") if isinstance(kernel_result.get("outcome"), dict) else {}
    deliveries = outcome.get("deliveries") if isinstance(outcome.get("deliveries"), list) else []
    normalized_target = str(target_agent_id or "").strip()
    for item in deliveries:
        if not isinstance(item, dict):
            continue
        if str(item.get("targetAgentId") or "").strip() == normalized_target:
            return item
    for item in deliveries:
        if isinstance(item, dict):
            return item
    return {
        "targetAgentId": normalized_target,
        "status": "failed",
        "inboxMessageId": "",
        "targetSessionId": "",
        "reason": "kernel_delivery_missing",
        "wake": {
            "wakeRequested": False,
            "wakeStatus": "failed",
            "messageId": "",
            "targetAgentId": normalized_target,
            "targetSessionId": "",
            "turnId": "",
            "reason": "kernel_delivery_missing",
        },
    }


def _flatten_kernel_delivery(
    delivery: dict[str, Any],
    *,
    target_agent_id: str,
    target_session_id: str,
    wake_target: bool,
) -> dict[str, Any]:
    wake = delivery.get("wake") if isinstance(delivery.get("wake"), dict) else {}
    message_id = str(delivery.get("inboxMessageId") or wake.get("messageId") or "").strip()
    resolved_target_session_id = str(delivery.get("targetSessionId") or wake.get("targetSessionId") or target_session_id or "").strip()
    reason = str(delivery.get("reason") or wake.get("reason") or "").strip()
    return {
        "status": str(delivery.get("status") or "").strip(),
        "inboxMessageId": message_id,
        "messageId": message_id,
        "targetAgentId": str(delivery.get("targetAgentId") or target_agent_id or "").strip(),
        "targetSessionId": resolved_target_session_id,
        "wakeRequested": bool(wake.get("wakeRequested", wake_target)),
        "wakeStatus": str(wake.get("wakeStatus") or ("not_requested" if not wake_target else "")).strip(),
        "turnId": str(wake.get("turnId") or "").strip(),
        "reason": reason,
        "kernelDelivery": delivery,
    }


def _kernel_trace_fields(kernel_result: dict[str, Any]) -> dict[str, Any]:
    event = kernel_result.get("event") if isinstance(kernel_result.get("event"), dict) else {}
    task = kernel_result.get("task") if isinstance(kernel_result.get("task"), dict) else {}
    execution = kernel_result.get("execution") if isinstance(kernel_result.get("execution"), dict) else {}
    outcome = kernel_result.get("outcome") if isinstance(kernel_result.get("outcome"), dict) else {}
    adapter = kernel_result.get("adapter") if isinstance(kernel_result.get("adapter"), dict) else {}
    return {
        "eventId": str(event.get("eventId") or adapter.get("eventId") or "").strip(),
        "taskId": str(task.get("taskId") or "").strip(),
        "workRunId": str(execution.get("workRunId") or "").strip(),
        "outcomeId": str(outcome.get("outcomeId") or "").strip(),
        "outcomeStatus": str(outcome.get("status") or "").strip(),
        "adapterVersion": str(adapter.get("adapterVersion") or "").strip(),
        "idempotencyKey": str(event.get("idempotencyKey") or adapter.get("idempotencyKey") or "").strip(),
        "reused": bool(kernel_result.get("reused")),
    }


def _try_send_research_org_message(
    *,
    source_agent: dict[str, Any],
    target_agent: dict[str, Any],
    source_agent_id: str,
    source_session_id: str,
    content: str,
    summary: str,
    wake_target: bool,
    thread_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any] | None:
    if not (_agent_has_research_org_scope(source_agent) or _agent_has_research_org_scope(target_agent)):
        return None

    from core.web.services import research_organization_service

    target_agent_id = str(target_agent.get("agentId") or "").strip()
    organization = research_organization_service.get_research_organization()
    organization_agent_ids = {
        str(node.get("agentId") or "").strip()
        for node in organization.get("agents") or []
        if isinstance(node, dict)
    }
    if source_agent_id not in organization_agent_ids and target_agent_id not in organization_agent_ids:
        return None

    message_type = _metadata_text(metadata, "researchOrgMessageType", "messageType") or "request"
    intent = _metadata_text(metadata, "researchOrgIntent", "intent")
    if not intent:
        return {
            "ok": False,
            "status": "blocked",
            "route": "research_org",
            "error": "research_org_intent_required",
            "reason": "research_org_intent_required",
            "message": (
                "科研组织消息必须在 metadata_json 中提供 researchOrgIntent。"
                "可用示例: research_goal, task_assignment, evidence_request, knowledge_update, "
                "validation_plan, permission_review, organization_design, decision_request, "
                "risk_escalation, status_report, final_report。"
            ),
            "sourceAgentId": source_agent_id,
            "sourceSessionId": source_session_id,
            "targetAgentId": target_agent_id,
            "targetAgentCode": target_agent.get("agentCode") or "",
            "targetSessionId": target_agent.get("directSessionId") or "",
            "wakeStatus": "blocked",
            "delivery": {
                "allowed": False,
                "reason": "research_org_intent_required",
                "inboxMessageId": "",
                "wakeStatus": "blocked",
            },
        }
    delivery_mode = _metadata_text(metadata, "researchOrgDeliveryMode", "deliveryMode") or "private"
    mailbox_only = _metadata_bool(metadata, "researchOrgMailboxOnly", "mailboxOnly")
    result = research_organization_service.send_research_org_message(
        {
            "sourceType": "agent",
            "sourceAgentId": source_agent_id,
            "sourceSessionId": source_session_id,
            "targetAgentId": target_agent_id,
            "messageType": message_type,
            "intent": intent,
            "deliveryMode": delivery_mode,
            "content": content,
            "summary": summary,
            "threadId": thread_id,
            "wakeTarget": bool(wake_target),
            "mailboxOnly": mailbox_only,
            "createdBy": "agent_tool",
        }
    )
    message = result.get("message") if isinstance(result.get("message"), dict) else {}
    deliveries = message.get("deliveries") if isinstance(message.get("deliveries"), list) else []
    delivery = deliveries[0] if deliveries and isinstance(deliveries[0], dict) else {}
    allowed = bool(delivery.get("allowed"))
    inbox_message_id = str(delivery.get("inboxMessageId") or "").strip()
    research_org_message_id = str(message.get("messageId") or "").strip()
    tool_message_id = inbox_message_id or research_org_message_id
    kernel_trace = _research_org_kernel_trace_fields(delivery)
    tool_message = {
        "messageId": tool_message_id,
        "sourceAgentId": source_agent_id,
        "sourceSessionId": source_session_id,
        "targetAgentId": target_agent_id,
        "targetSessionId": str(target_agent.get("directSessionId") or "").strip(),
    }
    _record_agent_message_tool_event(
        tool_message,
        delivery,
        route="research_org",
        outcome="sent" if allowed else "blocked",
        extra_fields={
            "researchOrgMessageId": research_org_message_id,
            "edgeId": str(delivery.get("edgeId") or "").strip(),
            "messageType": str(message.get("messageType") or message_type).strip(),
            "intent": str(message.get("intent") or intent).strip(),
            "deliveryMode": str(message.get("deliveryMode") or delivery_mode).strip(),
            **kernel_trace,
        },
    )
    return {
        "ok": allowed,
        "status": "sent" if allowed else "blocked",
        "route": "research_org",
        "messageId": tool_message_id,
        "researchOrgMessageId": research_org_message_id,
        "sourceAgentId": source_agent_id,
        "sourceSessionId": source_session_id,
        "targetAgentId": target_agent_id,
        "targetAgentCode": target_agent.get("agentCode") or "",
        "targetSessionId": target_agent.get("directSessionId") or "",
        "wakeStatus": delivery.get("wakeStatus") or ("blocked" if not allowed else ""),
        "reason": delivery.get("reason") or "",
        "delivery": delivery,
        "kernel": kernel_trace,
    }


def _agent_has_research_org_scope(agent: dict[str, Any]) -> bool:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    return any(str(metadata.get(key) or "").strip() for key in ("researchOrgRole", "systemRole"))


def _research_org_kernel_trace_fields(delivery: dict[str, Any]) -> dict[str, Any]:
    return {
        "eventId": str(delivery.get("kernelEventId") or "").strip(),
        "taskId": str(delivery.get("kernelTaskId") or "").strip(),
        "workRunId": str(delivery.get("kernelWorkRunId") or "").strip(),
        "outcomeId": str(delivery.get("kernelOutcomeId") or "").strip(),
        "outcomeStatus": str(delivery.get("kernelOutcomeStatus") or "").strip(),
        "adapterVersion": str(delivery.get("kernelAdapterVersion") or "").strip(),
        "reused": bool(delivery.get("kernelReused")),
    }


def _metadata_text(metadata: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if value is None:
            continue
        text = trim_lines(str(value), max_lines=1).strip()
        if text:
            return text
    return ""


def _metadata_bool(metadata: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        if key not in metadata:
            continue
        value = metadata.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "y", "on"}
        return bool(value)
    return False


def _record_agent_message_tool_event(
    message: dict[str, Any],
    delivery: dict[str, Any],
    *,
    route: str,
    outcome: str = "sent",
    extra_fields: dict[str, Any] | None = None,
) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        sent = outcome == "sent"
        fields = {
            "messageId": str(message.get("messageId") or "").strip(),
            "sourceAgentId": str(message.get("sourceAgentId") or "").strip(),
            "targetAgentId": str(message.get("targetAgentId") or "").strip(),
            "targetSessionId": str(message.get("targetSessionId") or "").strip(),
            "wakeStatus": str(delivery.get("wakeStatus") or "").strip(),
            "turnId": str(delivery.get("turnId") or "").strip(),
            "route": route,
            "reason": str(delivery.get("reason") or "").strip(),
        }
        if isinstance(extra_fields, dict):
            fields.update(
                {
                    str(key): value
                    for key, value in extra_fields.items()
                    if str(key or "").strip()
                }
            )
        record_runtime_scene_event(
            "agent_inbox",
            "tool",
            "agent_inbox.tool_sent" if sent else "agent_inbox.tool_blocked",
            message="agent_inbox.tool_sent" if sent else "agent_inbox.tool_blocked",
            level="info" if sent else "warning",
            outcome=outcome,
            fields=fields,
            lifecycle=True,
        )
    except Exception as exc:
        _debug_logger.warning(f"[Agent消息工具] 记录消息投递场景事件失败: {type(exc).__name__}: {exc}")
        return


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
