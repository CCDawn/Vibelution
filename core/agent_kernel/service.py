"""Agent Kernel MVP runtime loop.

The MVP deliberately keeps the runtime path small:
Event -> Task -> Execution -> Outcome, with proposal creation as an async side
workflow stub. Sessions, rooms, and conversations remain projections.
"""

from __future__ import annotations

import hashlib
import re
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.web.services import agent_directory_service, session_service
from core.web.services.runtime_scene_service import record_runtime_scene_event

from .store import KernelJsonlStore, utc_now_iso


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_KERNEL_LOCK = threading.RLock()
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_TERMINAL_TASK_STATUSES = {"succeeded", "failed", "cancelled", "blocked"}


class KernelError(ValueError):
    """Base class for kernel request errors."""


class KernelValidationError(KernelError):
    """Raised when an input event cannot enter the runtime loop."""

    def __init__(self, message: str, *, event: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.event = event or {}


class KernelNotFoundError(KernelError):
    """Raised when a kernel object is missing."""


def handle_kernel_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept one input event and run the minimal kernel loop."""

    if not isinstance(payload, dict):
        raise KernelValidationError("Kernel event payload must be an object.")
    with _KERNEL_LOCK:
        store = _store()
        index = store.load_index()
        event = _normalize_event(payload)
        if not event["recipients"]:
            event["status"] = "rejected"
            event["failureReason"] = "missing_recipient"
            _persist_event(store, index, event)
            _record_kernel_scene_event("kernel.event.rejected", event, outcome_status="rejected", level="warning")
            raise KernelValidationError("Kernel event recipients are required.", event=event)

        existing_task_id = str(index.get("taskIdsByIdempotencyKey", {}).get(event["idempotencyKey"]) or "").strip()
        if existing_task_id:
            existing_task = dict(index.get("tasksById", {}).get(existing_task_id) or {})
            duplicate_event = {**event, "status": "duplicate", "taskId": existing_task_id}
            _persist_event(store, index, duplicate_event)
            outcome = _task_outcome(index, existing_task)
            return {
                "reused": True,
                "event": duplicate_event,
                "task": existing_task,
                "execution": _task_execution(index, existing_task),
                "outcome": outcome,
                "proposals": _outcome_proposals(index, outcome),
            }

        _persist_event(store, index, event)
        task = _create_task(event)
        _persist_task_transition(store, index, task, "queued")
        _persist_task_transition(store, index, task, "running")
        execution = _create_execution(task, event)
        _persist_execution_transition(store, index, execution, "created")
        _persist_execution_transition(store, index, execution, "running")

        deliveries = _deliver_event_to_recipients(event, task)
        failed_deliveries = [item for item in deliveries if str(item.get("status") or "") != "delivered"]
        if failed_deliveries:
            outcome_status = "blocked"
            result_summary = f"Kernel event delivered partially; {len(failed_deliveries)} recipient(s) blocked."
            final_task_status = "blocked"
            final_execution_status = "blocked"
        else:
            outcome_status = "succeeded"
            result_summary = f"Kernel event delivered to {len(deliveries)} recipient(s)."
            final_task_status = "succeeded"
            final_execution_status = "succeeded"

        _persist_execution_transition(store, index, execution, final_execution_status, deliveries=deliveries)
        outcome = _create_outcome(task, execution, event, status=outcome_status, result_summary=result_summary, deliveries=deliveries)
        _persist_outcome(store, index, outcome)
        task["workRunId"] = execution["workRunId"]
        task["outcomeId"] = outcome["outcomeId"]
        _persist_task_transition(store, index, task, final_task_status)
        proposals = _create_proposal_stubs_from_outcome(store, index, event, outcome)
        _record_kernel_scene_event(
            "kernel.event.completed",
            event,
            task=task,
            outcome_payload=outcome,
            outcome_status=outcome_status,
        )
        return {
            "reused": False,
            "event": event,
            "task": dict(index["tasksById"][task["taskId"]]),
            "execution": dict(index["executionsById"][execution["workRunId"]]),
            "outcome": outcome,
            "proposals": proposals,
        }


def get_kernel_event(event_id: str) -> dict[str, Any]:
    normalized = _required_id(event_id, label="event id")
    event = _store().load_index().get("eventsById", {}).get(normalized)
    if not isinstance(event, dict):
        raise KernelNotFoundError(f"Kernel event not found: {event_id}")
    return dict(event)


def get_kernel_task(task_id: str) -> dict[str, Any]:
    normalized = _required_id(task_id, label="task id")
    task = _store().load_index().get("tasksById", {}).get(normalized)
    if not isinstance(task, dict):
        raise KernelNotFoundError(f"Kernel task not found: {task_id}")
    return dict(task)


def list_kernel_tasks(*, status: str = "", limit: int = 50) -> dict[str, Any]:
    index = _store().load_index()
    normalized_status = str(status or "").strip().lower()
    try:
        bounded_limit = max(1, min(int(limit or 50), 300))
    except (TypeError, ValueError):
        bounded_limit = 50
    task_ids = list(index.get("recentTaskIds") or [])
    tasks = [
        dict(index.get("tasksById", {}).get(task_id) or {})
        for task_id in task_ids
        if isinstance(index.get("tasksById", {}).get(task_id), dict)
    ]
    if normalized_status:
        tasks = [task for task in tasks if str(task.get("status") or "").strip().lower() == normalized_status]
    return {
        "tasks": tasks[-bounded_limit:],
        "limit": bounded_limit,
        "status": normalized_status,
        "updatedAt": str(index.get("updatedAt") or ""),
    }


def list_agent_inbox(agent_id: str, *, status: str = "pending", limit: int = 20) -> dict[str, Any]:
    normalized_agent_id = _required_id(agent_id, label="agent id")
    _ensure_agent_directory_root()
    if not agent_directory_service.get_agent(normalized_agent_id):
        raise KernelNotFoundError(f"Agent not found: {agent_id}")
    messages = agent_directory_service.list_agent_inbox_messages_for_agent(
        normalized_agent_id,
        status=status,
        limit=max(1, min(int(limit or 20), 100)),
    )
    return {
        "agentId": normalized_agent_id,
        "status": str(status or "").strip().lower(),
        "messages": messages,
        "pendingCount": agent_directory_service.count_agent_inbox_messages_for_agent(normalized_agent_id, status="pending"),
        "updatedAt": utc_now_iso(),
    }


def ack_agent_inbox_message(
    agent_id: str,
    event_id: str,
    *,
    consumed_by_session_id: str = "",
    consumed_by_turn_id: str = "",
) -> dict[str, Any]:
    _ensure_agent_directory_root()
    try:
        message = agent_directory_service.consume_agent_inbox_message(
            _required_id(agent_id, label="agent id"),
            _required_id(event_id, label="inbox event id"),
            consumed_by_session_id=consumed_by_session_id,
            consumed_by_turn_id=consumed_by_turn_id,
        )
    except agent_directory_service.AgentNotFoundError as exc:
        raise KernelNotFoundError(str(exc)) from exc
    except agent_directory_service.AgentMessageNotFoundError as exc:
        raise KernelNotFoundError(str(exc)) from exc
    return {
        "acked": True,
        "agentId": str(message.get("targetAgentId") or agent_id).strip(),
        "eventId": str(message.get("messageId") or message.get("eventId") or event_id).strip(),
        "message": message,
    }


def _store() -> KernelJsonlStore:
    return KernelJsonlStore(_kernel_root())


def _kernel_root() -> Path:
    return developer_sandbox.route_workspace_path(
        PROJECT_ROOT,
        "agent_kernel",
        "agent_kernel",
        intent="state",
        seed=True,
    )


def _normalize_event(payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    semantic_payload = _semantic_payload(payload)
    event_id = _safe_external_id(payload.get("eventId") or payload.get("id"), prefix="event")
    if not event_id:
        event_id = _new_id("event")
    recipients = _recipient_agent_ids(payload)
    sender = payload.get("sender") if isinstance(payload.get("sender"), dict) else {}
    sender_type = str(sender.get("type") or "").strip().lower()
    sender_id_as_agent = sender.get("id") if sender_type == "agent" else ""
    sender_agent_id = str(payload.get("senderAgentId") or sender.get("agentId") or sender_id_as_agent or "").strip()
    idempotency_key = str(payload.get("idempotencyKey") or "").strip()
    if not idempotency_key:
        idempotency_key = _default_idempotency_key(sender_agent_id=sender_agent_id, recipients=recipients, semantic_payload=semantic_payload)
    return {
        "eventId": event_id,
        "sender": _safe_metadata(sender),
        "senderAgentId": sender_agent_id,
        "recipients": recipients,
        "status": "accepted",
        "correlationId": str(payload.get("correlationId") or event_id).strip(),
        "causationId": str(payload.get("causationId") or "").strip(),
        "idempotencyKey": idempotency_key,
        "semanticPayload": semantic_payload,
        "deliveryPolicy": {
            "wakeTarget": _event_wake_target(payload, semantic_payload),
        },
        "createdAt": now,
        "updatedAt": now,
        "metadata": _safe_metadata(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
    }


def _semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    embedded = payload.get("semanticPayload") if isinstance(payload.get("semanticPayload"), dict) else {}
    semantic_type = str(payload.get("semanticType") or embedded.get("semanticType") or "agent.message").strip() or "agent.message"
    raw_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else embedded.get("payload")
    if not isinstance(raw_payload, dict):
        raw_payload = {}
    if "content" in payload and "content" not in raw_payload:
        raw_payload = {**raw_payload, "content": str(payload.get("content") or "")}
    return {
        "semanticType": semantic_type,
        "payload": _safe_metadata(raw_payload, max_items=64),
    }


def _event_wake_target(payload: dict[str, Any], semantic_payload: dict[str, Any]) -> bool:
    raw_value = payload.get("wakeTarget")
    if raw_value is not None:
        return bool(raw_value)
    semantic_body = semantic_payload.get("payload") if isinstance(semantic_payload.get("payload"), dict) else {}
    raw_semantic_value = semantic_body.get("wakeTarget")
    if raw_semantic_value is not None:
        return bool(raw_semantic_value)
    return True


def _recipient_agent_ids(payload: dict[str, Any]) -> list[str]:
    raw_values: list[Any] = []
    for key in ("recipients", "recipientAgentIds", "targetAgentIds", "assignedAgentIds"):
        value = payload.get(key)
        if isinstance(value, list):
            raw_values.extend(value)
    if payload.get("recipientAgentId"):
        raw_values.append(payload.get("recipientAgentId"))
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        if isinstance(item, dict):
            raw = item.get("agentId") or item.get("id")
        else:
            raw = item
        agent_id = str(raw or "").strip()
        if agent_id and agent_id not in seen:
            seen.add(agent_id)
            result.append(agent_id)
    return result


def _persist_event(store: KernelJsonlStore, index: dict[str, Any], event: dict[str, Any]) -> None:
    event["updatedAt"] = utc_now_iso()
    store.append("events", event)
    index.setdefault("eventsById", {})[event["eventId"]] = deepcopy(event)
    index["recentEventIds"] = _bounded_recent([event["eventId"], *list(index.get("recentEventIds") or [])])
    store.save_index(index)


def _create_task(event: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    task_id = _new_id("task")
    semantic = event.get("semanticPayload") if isinstance(event.get("semanticPayload"), dict) else {}
    payload = semantic.get("payload") if isinstance(semantic.get("payload"), dict) else {}
    goal = str(payload.get("goal") or payload.get("content") or semantic.get("semanticType") or "Kernel event").strip()
    return {
        "taskId": task_id,
        "creatorEventId": event["eventId"],
        "idempotencyKey": event["idempotencyKey"],
        "goal": _trim(goal, 500),
        "assignedAgentIds": list(event.get("recipients") or []),
        "status": "queued",
        "workRunId": "",
        "outcomeId": "",
        "evidenceRefs": [{"kind": "event", "eventId": event["eventId"]}],
        "createdAt": now,
        "updatedAt": now,
    }


def _persist_task_transition(store: KernelJsonlStore, index: dict[str, Any], task: dict[str, Any], status: str) -> None:
    current = dict(index.get("tasksById", {}).get(task["taskId"]) or task)
    if str(current.get("status") or "") in _TERMINAL_TASK_STATUSES and status not in _TERMINAL_TASK_STATUSES:
        raise KernelValidationError("Terminal kernel task cannot return to a running state.")
    current.update(task)
    current["status"] = status
    current["updatedAt"] = utc_now_iso()
    store.append("tasks", current)
    index.setdefault("tasksById", {})[current["taskId"]] = deepcopy(current)
    index.setdefault("taskIdsByIdempotencyKey", {})[current["idempotencyKey"]] = current["taskId"]
    index["recentTaskIds"] = _bounded_recent([current["taskId"], *list(index.get("recentTaskIds") or [])])
    store.save_index(index)


def _create_execution(task: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "workRunId": _new_id("workrun"),
        "taskId": task["taskId"],
        "agentId": ",".join(task.get("assignedAgentIds") or []),
        "status": "created",
        "startedAt": now,
        "endedAt": "",
        "evidenceRefs": [{"kind": "event", "eventId": event["eventId"]}],
        "deliveryRefs": [],
        "createdAt": now,
        "updatedAt": now,
    }


def _persist_execution_transition(
    store: KernelJsonlStore,
    index: dict[str, Any],
    execution: dict[str, Any],
    status: str,
    *,
    deliveries: list[dict[str, Any]] | None = None,
) -> None:
    current = dict(index.get("executionsById", {}).get(execution["workRunId"]) or execution)
    current.update(execution)
    current["status"] = status
    current["updatedAt"] = utc_now_iso()
    if status in {"succeeded", "failed", "cancelled", "blocked"}:
        current["endedAt"] = current["updatedAt"]
    if deliveries is not None:
        current["deliveryRefs"] = [
            {
                "targetAgentId": str(item.get("targetAgentId") or "").strip(),
                "inboxMessageId": str(item.get("inboxMessageId") or "").strip(),
                "status": str(item.get("status") or "").strip(),
                "wakeStatus": str((item.get("wake") if isinstance(item.get("wake"), dict) else {}).get("wakeStatus") or "").strip(),
            }
            for item in deliveries
        ]
    store.append("executions", current)
    index.setdefault("executionsById", {})[current["workRunId"]] = deepcopy(current)
    store.save_index(index)


def _deliver_event_to_recipients(event: dict[str, Any], task: dict[str, Any]) -> list[dict[str, Any]]:
    _ensure_agent_directory_root()
    _ensure_session_root()
    semantic = event.get("semanticPayload") if isinstance(event.get("semanticPayload"), dict) else {}
    payload = semantic.get("payload") if isinstance(semantic.get("payload"), dict) else {}
    content = str(payload.get("content") or payload.get("message") or task.get("goal") or "").strip()
    if not content:
        content = str(semantic.get("semanticType") or "Kernel message").strip()
    delivery_policy = event.get("deliveryPolicy") if isinstance(event.get("deliveryPolicy"), dict) else {}
    wake_target = bool(delivery_policy.get("wakeTarget", True))
    deliveries: list[dict[str, Any]] = []
    for agent_id in list(event.get("recipients") or []):
        target_agent_id = str(agent_id or "").strip()
        delivery = {
            "targetAgentId": target_agent_id,
            "status": "pending",
            "inboxMessageId": "",
            "targetSessionId": "",
            "reason": "",
            "wake": {
                "wakeRequested": wake_target,
                "wakeStatus": "not_requested" if not wake_target else "skipped",
                "messageId": "",
                "targetAgentId": target_agent_id,
                "targetSessionId": "",
                "turnId": "",
                "reason": "",
            },
        }
        try:
            message = agent_directory_service.write_agent_inbox_message(
                agent_id,
                content=content,
                source_agent_id=str(event.get("senderAgentId") or "").strip(),
                source_round_id=event["eventId"],
                thread_id=str(event.get("correlationId") or event["eventId"]),
                kind="kernel_event",
                summary=content,
                prompt_eligible=True,
                created_by="kernel",
                metadata={
                    "kernelEventId": event["eventId"],
                    "kernelTaskId": task["taskId"],
                    "semanticType": str(semantic.get("semanticType") or ""),
                },
            )
            delivery.update(
                {
                    "status": "delivered",
                    "inboxMessageId": str(message.get("messageId") or message.get("eventId") or "").strip(),
                    "targetSessionId": str(message.get("targetSessionId") or "").strip(),
                }
            )
            delivery["wake"]["messageId"] = delivery["inboxMessageId"]
            delivery["wake"]["targetSessionId"] = delivery["targetSessionId"]
            if wake_target:
                try:
                    delivery["wake"] = session_service.wake_agent_for_inbox_message(message)
                except Exception as wake_exc:
                    delivery["wake"] = {
                        "wakeRequested": True,
                        "wakeStatus": "failed",
                        "messageId": delivery["inboxMessageId"],
                        "targetAgentId": target_agent_id,
                        "targetSessionId": delivery["targetSessionId"],
                        "turnId": "",
                        "reason": f"{type(wake_exc).__name__}: {_trim(str(wake_exc), 240)}",
                    }
        except Exception as exc:
            delivery["status"] = "failed"
            delivery["reason"] = f"{type(exc).__name__}: {_trim(str(exc), 240)}"
        deliveries.append(delivery)
    return deliveries


def _create_outcome(
    task: dict[str, Any],
    execution: dict[str, Any],
    event: dict[str, Any],
    *,
    status: str,
    result_summary: str,
    deliveries: list[dict[str, Any]],
) -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "outcomeId": _new_id("outcome"),
        "taskId": task["taskId"],
        "workRunId": execution["workRunId"],
        "agentId": str(execution.get("agentId") or "").strip(),
        "status": status,
        "visibleReply": "",
        "resultSummary": result_summary,
        "proposalRefs": [],
        "evidenceRefs": [
            {"kind": "event", "eventId": event["eventId"]},
            {"kind": "execution", "workRunId": execution["workRunId"]},
        ],
        "deliveries": deliveries,
        "createdAt": now,
    }


def _persist_outcome(store: KernelJsonlStore, index: dict[str, Any], outcome: dict[str, Any]) -> None:
    store.append("outcomes", outcome)
    index.setdefault("outcomesById", {})[outcome["outcomeId"]] = deepcopy(outcome)
    store.save_index(index)


def _create_proposal_stubs_from_outcome(
    store: KernelJsonlStore,
    index: dict[str, Any],
    event: dict[str, Any],
    outcome: dict[str, Any],
) -> list[dict[str, Any]]:
    semantic = event.get("semanticPayload") if isinstance(event.get("semanticPayload"), dict) else {}
    payload = semantic.get("payload") if isinstance(semantic.get("payload"), dict) else {}
    proposal_type = str(payload.get("proposalType") or "").strip()
    proposal_payload = payload.get("proposal") if isinstance(payload.get("proposal"), dict) else {}
    if not proposal_type and proposal_payload:
        proposal_type = str(proposal_payload.get("type") or "kernel_proposal").strip()
    if not proposal_type:
        return []
    proposal = {
        "proposalId": _new_id("proposal"),
        "sourceOutcomeId": outcome["outcomeId"],
        "proposalType": proposal_type,
        "status": "queued",
        "summary": _trim(str(payload.get("proposalSummary") or proposal_payload.get("summary") or outcome["resultSummary"]), 500),
        "createdAt": utc_now_iso(),
        "metadata": _safe_metadata(proposal_payload),
    }
    store.append("proposals", proposal)
    index.setdefault("proposalsById", {})[proposal["proposalId"]] = deepcopy(proposal)
    refs = list(index.setdefault("proposalIdsByOutcomeId", {}).get(outcome["outcomeId"]) or [])
    refs.append(proposal["proposalId"])
    index["proposalIdsByOutcomeId"][outcome["outcomeId"]] = refs
    stored_outcome = dict(index.get("outcomesById", {}).get(outcome["outcomeId"]) or outcome)
    stored_outcome["proposalRefs"] = refs
    outcome["proposalRefs"] = refs
    index["outcomesById"][outcome["outcomeId"]] = stored_outcome
    store.save_index(index)
    return [proposal]


def _task_outcome(index: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    outcome_id = str(task.get("outcomeId") or "").strip()
    if not outcome_id:
        return {}
    outcome = index.get("outcomesById", {}).get(outcome_id)
    return dict(outcome) if isinstance(outcome, dict) else {}


def _task_execution(index: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    work_run_id = str(task.get("workRunId") or "").strip()
    if not work_run_id:
        return {}
    execution = index.get("executionsById", {}).get(work_run_id)
    return dict(execution) if isinstance(execution, dict) else {}


def _outcome_proposals(index: dict[str, Any], outcome: dict[str, Any]) -> list[dict[str, Any]]:
    outcome_id = str(outcome.get("outcomeId") or "").strip()
    if not outcome_id:
        return []
    proposal_ids = list(index.get("proposalIdsByOutcomeId", {}).get(outcome_id) or [])
    proposals = []
    for proposal_id in proposal_ids:
        proposal = index.get("proposalsById", {}).get(proposal_id)
        if isinstance(proposal, dict):
            proposals.append(dict(proposal))
    return proposals


def _safe_external_id(value: Any, *, prefix: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    cleaned = _SAFE_ID_RE.sub("-", raw).strip("._-")
    if not cleaned:
        return ""
    if cleaned != raw or len(cleaned) > 120:
        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:12]
        return f"{prefix}-{cleaned[:72].strip('._-') or 'id'}-{digest}"
    return cleaned


def _ensure_agent_directory_root() -> None:
    if getattr(agent_directory_service, "PROJECT_ROOT", PROJECT_ROOT) != PROJECT_ROOT:
        agent_directory_service.PROJECT_ROOT = PROJECT_ROOT


def _ensure_session_root() -> None:
    if getattr(session_service, "PROJECT_ROOT", PROJECT_ROOT) != PROJECT_ROOT:
        session_service.PROJECT_ROOT = PROJECT_ROOT


def _new_id(prefix: str) -> str:
    seed = f"{prefix}\0{utc_now_iso()}\0{id(object())}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    timestamp = re.sub(r"[^0-9]", "", utc_now_iso())[:20]
    return f"{prefix}-{timestamp}-{digest}"


def _default_idempotency_key(*, sender_agent_id: str, recipients: list[str], semantic_payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        repr(
            {
                "senderAgentId": sender_agent_id,
                "recipients": recipients,
                "semanticPayload": semantic_payload,
            }
        ).encode("utf-8", errors="replace")
    ).hexdigest()[:24]
    return f"kernel-{digest}"


def _required_id(value: Any, *, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise KernelValidationError(f"Kernel {label} is required.")
    return normalized


def _safe_metadata(metadata: Any, *, max_items: int = 32) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, value in list(metadata.items())[:max_items]:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[normalized_key] = value
        elif isinstance(value, dict):
            safe[normalized_key] = _safe_metadata(value, max_items=16)
        elif isinstance(value, (list, tuple)):
            safe[normalized_key] = [
                item if isinstance(item, (str, int, float, bool)) or item is None else str(item)
                for item in list(value)[:24]
            ]
        else:
            safe[normalized_key] = str(value)
    return safe


def _bounded_recent(values: list[str], *, limit: int = 300) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _trim(value: str, limit: int) -> str:
    text = str(value or "").strip()
    return text[: max(1, limit)]


def _record_kernel_scene_event(
    event_code: str,
    event: dict[str, Any],
    *,
    task: dict[str, Any] | None = None,
    outcome_payload: dict[str, Any] | None = None,
    outcome_status: str | None = None,
    level: str = "info",
) -> None:
    try:
        record_runtime_scene_event(
            "agent_kernel",
            "runtime",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome_status or str(event.get("status") or "observed"),
            fields={
                "eventId": str(event.get("eventId") or "").strip(),
                "taskId": str((task or {}).get("taskId") or event.get("taskId") or "").strip(),
                "outcomeId": str((outcome_payload or {}).get("outcomeId") or "").strip(),
                "semanticType": str((event.get("semanticPayload") or {}).get("semanticType") or "").strip()
                if isinstance(event.get("semanticPayload"), dict)
                else "",
                "recipientCount": len(event.get("recipients") or []),
                "status": str(event.get("status") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return
