"""Project-level Agent communication bus.

The bus is an observation surface plus delivery fan-out. It does not schedule
round-robin meetings; targeted messages are delivered to Agent inboxes.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import agent_directory_service, session_service
from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]

_BUS_LOCK = threading.RLock()
_MENTION_PATTERN = re.compile(r"@([^\s@,，:：;；]+)")
_ALL_MENTIONS = {"全体", "全体成员", "所有人", "所有成员", "all", "everyone"}
_TARGET_SCOPES = {"observe", "agents", "all"}
_INTERRUPT_MODES = {"none", "interrupt_targets"}


class ProjectAgentBusError(ValueError):
    """Raised when a project bus request is invalid."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_project_agent_bus_events(*, limit: int = 80) -> dict[str, Any]:
    """Return recent bus timeline events and the current active Agent count."""

    events = _read_jsonl(_bus_events_path())
    try:
        capped_limit = max(1, min(int(limit or 80), 300))
    except (TypeError, ValueError):
        capped_limit = 80
    return {
        "events": events[-capped_limit:],
        "activeAgentCount": len(_active_agents()),
        "updatedAt": utc_now_iso(),
    }


def send_project_agent_bus_message(
    *,
    content: str,
    target_scope: str = "",
    target_agent_ids: list[str] | None = None,
    interrupt_mode: str = "none",
    wake_target: bool = True,
    created_by: str = "user",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a bus event and optionally deliver it to targeted Agent inboxes."""

    normalized_content = _trim_lines(str(content or ""), max_lines=40).strip()
    if not normalized_content:
        raise ProjectAgentBusError("Project Agent bus message content is required.")
    active_agents = _active_agents()
    explicit_scope = str(target_scope or "").strip().lower()
    if explicit_scope and explicit_scope not in _TARGET_SCOPES:
        raise ProjectAgentBusError(f"Unsupported target scope: {target_scope}")
    normalized_interrupt = str(interrupt_mode or "none").strip().lower() or "none"
    if normalized_interrupt not in _INTERRUPT_MODES:
        raise ProjectAgentBusError(f"Unsupported interrupt mode: {interrupt_mode}")

    resolution = resolve_project_agent_bus_targets(
        normalized_content,
        active_agents=active_agents,
        target_scope=explicit_scope,
        target_agent_ids=target_agent_ids or [],
    )
    event_id = _new_event_id("projectbus")
    now = utc_now_iso()
    event = {
        "eventId": event_id,
        "messageType": resolution["messageType"],
        "targetScope": resolution["targetScope"],
        "targetAgentIds": [agent["agentId"] for agent in resolution["targets"]],
        "targetAgentCodes": [agent.get("agentCode") or "" for agent in resolution["targets"]],
        "targetAgentNames": [agent.get("displayName") or "" for agent in resolution["targets"]],
        "mentionedTokens": resolution["mentionedTokens"],
        "unresolvedMentions": resolution["unresolvedMentions"],
        "content": normalized_content,
        "summary": _trim_lines(normalized_content, max_lines=3),
        "createdBy": str(created_by or "user").strip() or "user",
        "createdAt": now,
        "updatedAt": now,
        "metadata": _safe_metadata(metadata),
        "deliveries": [],
        "interruptions": [],
    }

    if resolution["targets"] and normalized_interrupt == "interrupt_targets":
        event["interruptions"] = [
            _interrupt_target_agent(agent, source_event_id=event_id)
            for agent in resolution["targets"]
        ]

    event["deliveries"] = [
        _deliver_to_agent(
            agent,
            content=normalized_content,
            event_id=event_id,
            message_type=event["messageType"],
            wake_target=bool(wake_target),
        )
        for agent in resolution["targets"]
    ]

    with _BUS_LOCK:
        _append_jsonl(_bus_events_path(), event)
    _record_bus_event("message.sent", event)
    return event


def revoke_project_agent_bus_message(
    event_id: str,
    *,
    revoked_by: str = "user",
    reason: str = "",
    stop_targets: bool = True,
) -> dict[str, Any]:
    normalized_event_id = str(event_id or "").strip()
    if not normalized_event_id:
        raise ProjectAgentBusError("Project Agent bus event id is required.")
    revoked_at = utc_now_iso()
    with _BUS_LOCK:
        events = _read_jsonl(_bus_events_path())
        target_event: dict[str, Any] | None = None
        for event in events:
            if str(event.get("eventId") or "").strip() == normalized_event_id:
                target_event = event
                break
        if target_event is None:
            raise ProjectAgentBusError(f"Project Agent bus event not found: {event_id}")
        if str(target_event.get("status") or "").strip().lower() != "revoked":
            target_event["status"] = "revoked"
            target_event["revokedAt"] = revoked_at
            target_event["revokedBy"] = str(revoked_by or "user").strip() or "user"
            target_event["revokeReason"] = _trim_lines(str(reason or ""), max_lines=2)
            target_event["updatedAt"] = revoked_at
        revocations = _revoke_deliveries(target_event, revoked_by=revoked_by, reason=reason, stop_targets=stop_targets)
        target_event["revocations"] = revocations
        _write_jsonl(_bus_events_path(), events)
    _record_bus_event("message.revoked", target_event)
    return target_event


def resolve_project_agent_bus_targets(
    content: str,
    *,
    active_agents: list[dict[str, Any]] | None = None,
    target_scope: str = "",
    target_agent_ids: list[str] | None = None,
) -> dict[str, Any]:
    agents = list(active_agents if active_agents is not None else _active_agents())
    agent_ids = {str(agent.get("agentId") or "").strip() for agent in agents}
    explicit_ids = [
        str(agent_id or "").strip()
        for agent_id in list(target_agent_ids or [])
        if str(agent_id or "").strip()
    ]
    mentioned_tokens = _extract_mentions(content)
    all_requested = any(_normalize_mention_token(token) in _ALL_MENTIONS for token in mentioned_tokens)
    matched_ids, unresolved = _match_mentions(mentioned_tokens, agents)
    target_ids: list[str] = []
    normalized_scope = str(target_scope or "").strip().lower()

    if normalized_scope == "observe":
        target_ids = []
    elif normalized_scope == "all" or all_requested:
        target_ids = [str(agent.get("agentId") or "").strip() for agent in agents]
        normalized_scope = "all"
    elif explicit_ids:
        target_ids = [agent_id for agent_id in explicit_ids if agent_id in agent_ids]
        unresolved.extend(agent_id for agent_id in explicit_ids if agent_id not in agent_ids)
        normalized_scope = "agents" if target_ids else "observe"
    elif matched_ids:
        target_ids = matched_ids
        normalized_scope = "agents"
    elif mentioned_tokens:
        target_ids = []
        normalized_scope = "agents"
    else:
        target_ids = [str(agent.get("agentId") or "").strip() for agent in agents]
        normalized_scope = "all" if target_ids else "observe"

    target_id_set = set()
    targets: list[dict[str, Any]] = []
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        if agent_id in target_ids and agent_id not in target_id_set:
            target_id_set.add(agent_id)
            targets.append(agent)

    if normalized_scope == "all":
        message_type = "user_guidance"
    elif targets:
        message_type = "user_guidance"
    else:
        message_type = "project_observation"

    return {
        "targetScope": normalized_scope,
        "targets": targets,
        "mentionedTokens": mentioned_tokens,
        "unresolvedMentions": sorted(set(unresolved)),
        "messageType": message_type,
    }


def _revoke_deliveries(
    event: dict[str, Any],
    *,
    revoked_by: str,
    reason: str,
    stop_targets: bool,
) -> list[dict[str, Any]]:
    revocations: list[dict[str, Any]] = []
    for delivery in list(event.get("deliveries") or []):
        if not isinstance(delivery, dict):
            continue
        agent_id = str(delivery.get("targetAgentId") or "").strip()
        message_id = str(delivery.get("inboxMessageId") or delivery.get("wake", {}).get("messageId") or "").strip()
        session_id = str(delivery.get("targetSessionId") or delivery.get("wake", {}).get("targetSessionId") or "").strip()
        revoked = {
            "targetAgentId": agent_id,
            "targetSessionId": session_id,
            "inboxMessageId": message_id,
            "inboxStatus": "skipped",
            "stopStatus": "not_requested" if not stop_targets else "skipped",
            "reason": "",
        }
        delivery["revoked"] = True
        delivery["revokedAt"] = str(event.get("revokedAt") or utc_now_iso())
        if agent_id and message_id:
            try:
                agent_directory_service.revoke_agent_inbox_message(
                    agent_id,
                    message_id,
                    revoked_by=revoked_by,
                    reason=reason or f"Project bus event revoked: {event.get('eventId') or ''}",
                )
                revoked["inboxStatus"] = "revoked"
            except Exception as exc:
                revoked["inboxStatus"] = "failed"
                revoked["reason"] = type(exc).__name__
        if stop_targets and session_id:
            try:
                stop_result = session_service.request_stop_session_turn(session_id)
                revoked["stopStatus"] = str(stop_result.get("status") or stop_result.get("currentPhase") or "requested").strip() or "requested"
            except Exception as exc:
                revoked["stopStatus"] = "failed"
                revoked["reason"] = type(exc).__name__
        revocations.append(revoked)
    return revocations


def _deliver_to_agent(
    agent: dict[str, Any],
    *,
    content: str,
    event_id: str,
    message_type: str,
    wake_target: bool,
) -> dict[str, Any]:
    agent_id = str(agent.get("agentId") or "").strip()
    delivery = {
        "targetAgentId": agent_id,
        "targetAgentCode": str(agent.get("agentCode") or "").strip(),
        "targetAgentName": str(agent.get("displayName") or "").strip(),
        "targetSessionId": str(agent.get("directSessionId") or "").strip(),
        "inboxMessageId": "",
        "status": "skipped",
        "wake": {
            "wakeRequested": bool(wake_target),
            "wakeStatus": "not_requested" if not wake_target else "skipped",
            "messageId": "",
            "targetAgentId": agent_id,
            "targetSessionId": str(agent.get("directSessionId") or "").strip(),
            "turnId": "",
            "reason": "",
        },
        "reason": "",
    }
    try:
        message = agent_directory_service.write_agent_inbox_message(
            agent_id,
            content=content,
            source_room_id="project_agent_bus",
            source_round_id=event_id,
            thread_id="project:agent-bus",
            kind="user_guidance" if message_type == "user_guidance" else "agent_broadcast",
            summary=content,
            prompt_eligible=True,
            created_by="user",
            metadata={"projectBusEventId": event_id, "messageType": message_type},
        )
    except Exception as exc:
        delivery["status"] = "failed"
        delivery["reason"] = type(exc).__name__
        return delivery

    delivery["status"] = "delivered"
    delivery["inboxMessageId"] = str(message.get("messageId") or message.get("eventId") or "").strip()
    delivery["wake"]["messageId"] = delivery["inboxMessageId"]
    if wake_target:
        delivery["wake"] = session_service.wake_agent_for_inbox_message(message)
    return delivery


def _interrupt_target_agent(agent: dict[str, Any], *, source_event_id: str) -> dict[str, Any]:
    agent_id = str(agent.get("agentId") or "").strip()
    session_id = str(agent.get("directSessionId") or "").strip()
    result = {
        "targetAgentId": agent_id,
        "targetAgentCode": str(agent.get("agentCode") or "").strip(),
        "targetAgentName": str(agent.get("displayName") or "").strip(),
        "targetSessionId": session_id,
        "status": "skipped",
        "reason": "",
    }
    if not session_id:
        result["status"] = "skipped_no_direct_session"
        result["reason"] = "target_agent_has_no_direct_session"
        return result
    try:
        before_status = str((session_service.get_session_detail(session_id) or {}).get("status") or "").strip()
        session_service.request_stop_session_turn(session_id)
        after_status = str((session_service.get_session_detail(session_id) or {}).get("status") or "").strip()
    except Exception as exc:
        result["status"] = "failed"
        result["reason"] = type(exc).__name__
        return result
    if before_status == "running" or after_status in {"stopped", "stopping"}:
        result["status"] = "interrupted"
    else:
        result["status"] = "skipped_not_running"
        result["reason"] = before_status or "not_running"
    result["sourceEventId"] = source_event_id
    return result


def _active_agents() -> list[dict[str, Any]]:
    return [
        agent for agent in agent_directory_service.list_agents(include_archived=False)
        if str(agent.get("status") or "active").strip().lower() != "archived"
    ]


def _extract_mentions(content: str) -> list[str]:
    tokens: list[str] = []
    for match in _MENTION_PATTERN.finditer(str(content or "")):
        token = match.group(1).strip()
        if token:
            tokens.append(token)
    return tokens


def _match_mentions(tokens: list[str], agents: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    matched: list[str] = []
    unresolved: list[str] = []
    for token in tokens:
        normalized = _normalize_mention_token(token)
        if normalized in _ALL_MENTIONS:
            continue
        token_matches = [
            str(agent.get("agentId") or "").strip()
            for agent in agents
            if _agent_matches_mention(agent, normalized)
        ]
        if token_matches:
            matched.extend(token_matches)
        else:
            unresolved.append(token)
    deduped: list[str] = []
    seen: set[str] = set()
    for agent_id in matched:
        if agent_id and agent_id not in seen:
            seen.add(agent_id)
            deduped.append(agent_id)
    return deduped, unresolved


def _agent_matches_mention(agent: dict[str, Any], normalized_token: str) -> bool:
    values = [
        agent.get("agentId"),
        agent.get("agentCode"),
        agent.get("displayName"),
        agent.get("roleKey"),
        agent.get("dialogueModelId"),
        agent.get("promptTemplateId"),
    ]
    return any(_normalize_mention_token(value) == normalized_token for value in values)


def _normalize_mention_token(value: Any) -> str:
    return str(value or "").strip().strip(".,，。:：;；!！?？").lower()


def _bus_events_path() -> Path:
    from core.infrastructure import developer_sandbox

    return developer_sandbox.route_workspace_path(
        _project_root(),
        "project_agent_bus",
        "project_agent_bus",
        "events.jsonl",
        intent="state",
        seed=True,
    )


def _project_root() -> Path:
    root = Path(PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _new_event_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _write_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(payload, ensure_ascii=False, sort_keys=True) for payload in payloads]
    path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8", newline="\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _trim_lines(value: str, *, max_lines: int) -> str:
    lines = str(value or "").splitlines()
    return "\n".join(lines[:max(1, max_lines)]).strip()


def _safe_bus_event_token(event_id: Any) -> str:
    token = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(event_id or "").strip()).strip("._-")
    return token[:96] or "event"


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, value in list(metadata.items())[:32]:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[normalized_key] = value
        elif isinstance(value, (list, tuple)):
            safe[normalized_key] = [
                item if isinstance(item, (str, int, float, bool)) or item is None else str(item)
                for item in list(value)[:24]
            ]
        else:
            safe[normalized_key] = str(value)
    return safe


def _record_bus_event(event_name: str, event: dict[str, Any]) -> None:
    try:
        event_id = str(event.get("eventId") or "").strip()
        deliveries = [item for item in list(event.get("deliveries") or []) if isinstance(item, dict)]
        interruptions = [item for item in list(event.get("interruptions") or []) if isinstance(item, dict)]
        target_agent_ids = [
            str(agent_id or "").strip()
            for agent_id in list(event.get("targetAgentIds") or [])
            if str(agent_id or "").strip()
        ]
        inbox_message_ids = [
            str(item.get("inboxMessageId") or "").strip()
            for item in deliveries
            if str(item.get("inboxMessageId") or "").strip()
        ]
        wake_statuses = [
            str((item.get("wake") if isinstance(item.get("wake"), dict) else {}).get("wakeStatus") or "").strip()
            for item in deliveries
        ]
        interrupt_statuses = [
            str(item.get("status") or "").strip()
            for item in interruptions
            if str(item.get("status") or "").strip()
        ]
        delivery_statuses = [
            str(item.get("status") or "").strip()
            for item in deliveries
            if str(item.get("status") or "").strip()
        ]
        record_runtime_scene_event(
            "project_agent_bus",
            "message",
            f"project_agent_bus.{event_name}",
            message=f"project_agent_bus.{event_name}",
            level="info",
            outcome="observed",
            fields={
                "eventId": event_id,
                "messageType": event.get("messageType") or "",
                "targetScope": event.get("targetScope") or "",
                "targetAgentIds": target_agent_ids[:24],
                "inboxMessageIds": inbox_message_ids[:24],
                "targetCount": len(target_agent_ids),
                "deliveryCount": len(deliveries),
                "deliveredCount": sum(1 for status in delivery_statuses if status == "delivered"),
                "deliveryStatuses": delivery_statuses[:24],
                "interruptCount": len(interruptions),
                "interruptedCount": sum(1 for status in interrupt_statuses if status == "interrupted"),
                "interruptStatuses": interrupt_statuses[:24],
                "wakeStatuses": wake_statuses[:24],
                "unresolvedMentionCount": len(event.get("unresolvedMentions") or []),
                "unresolvedMentions": list(event.get("unresolvedMentions") or [])[:24],
            },
            child_log_path=f"agent/project_agent_bus/{_safe_bus_event_token(event_id)}.jsonl",
            child_log_payload={
                "event_id": event_id,
                "message_type": str(event.get("messageType") or "").strip(),
                "target_scope": str(event.get("targetScope") or "").strip(),
                "target_agent_ids": target_agent_ids[:50],
                "mentioned_tokens": list(event.get("mentionedTokens") or [])[:50],
                "unresolved_mentions": list(event.get("unresolvedMentions") or [])[:50],
                "content_summary": _trim_lines(str(event.get("summary") or ""), max_lines=3),
                "deliveries": [
                    {
                        "target_agent_id": str(item.get("targetAgentId") or "").strip(),
                        "target_session_id": str(item.get("targetSessionId") or "").strip(),
                        "inbox_message_id": str(item.get("inboxMessageId") or "").strip(),
                        "status": str(item.get("status") or "").strip(),
                        "reason": str(item.get("reason") or "").strip(),
                        "wake_status": str((item.get("wake") if isinstance(item.get("wake"), dict) else {}).get("wakeStatus") or "").strip(),
                        "wake_reason": str((item.get("wake") if isinstance(item.get("wake"), dict) else {}).get("reason") or "").strip(),
                        "turn_id": str((item.get("wake") if isinstance(item.get("wake"), dict) else {}).get("turnId") or "").strip(),
                    }
                    for item in deliveries[:50]
                ],
                "interruptions": [
                    {
                        "target_agent_id": str(item.get("targetAgentId") or "").strip(),
                        "target_session_id": str(item.get("targetSessionId") or "").strip(),
                        "status": str(item.get("status") or "").strip(),
                        "reason": str(item.get("reason") or "").strip(),
                    }
                    for item in interruptions[:50]
                ],
            },
            lifecycle=True,
        )
    except Exception:
        return
