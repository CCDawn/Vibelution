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


def get_kernel_task_timeline(task_id: str) -> dict[str, Any]:
    """Return a read-only task timeline projection.

    The timeline is derived from the TaskLedger/index and JSONL streams. It is
    intentionally not persisted as a second source of truth.
    """

    normalized = _required_id(task_id, label="task id")
    with _KERNEL_LOCK:
        store = _store()
        index = store.load_index()
        task = index.get("tasksById", {}).get(normalized)
        if not isinstance(task, dict):
            _record_kernel_timeline_scene_event(
                "kernel.timeline.missing_task",
                task_id=normalized,
                outcome_status="missing",
                level="warning",
            )
            raise KernelNotFoundError(f"Kernel task not found: {task_id}")
        task_payload = dict(task)
        event_id = str(task_payload.get("creatorEventId") or "").strip()
        event = index.get("eventsById", {}).get(event_id)
        event_payload = dict(event) if isinstance(event, dict) else {}
        execution = _task_execution(index, task_payload)
        outcome = _task_outcome(index, task_payload)
        proposals = _outcome_proposals(index, outcome)
        deliveries = list(outcome.get("deliveries") or []) if isinstance(outcome.get("deliveries"), list) else []
        timeline = _build_kernel_task_timeline(
            store,
            task=task_payload,
            event=event_payload,
            execution=execution,
            outcome=outcome,
            deliveries=deliveries,
            proposals=proposals,
        )
        response = {
            "taskId": normalized,
            "task": task_payload,
            "event": event_payload,
            "execution": execution,
            "outcome": outcome,
            "deliveries": deliveries,
            "proposals": proposals,
            "runtimeEvidenceRefs": _kernel_runtime_evidence_refs(
                event=event_payload,
                task=task_payload,
                execution=execution,
                outcome=outcome,
            ),
            "projectionRefs": _kernel_projection_refs(event_payload),
            "timeline": timeline,
            "readModel": {
                "projection": True,
                "factAuthority": False,
                "truthSource": "TaskLedger",
                "generatedAt": utc_now_iso(),
            },
        }
        _record_kernel_timeline_scene_event(
            "kernel.timeline.loaded",
            task_id=normalized,
            event_id=event_id,
            outcome_id=str(outcome.get("outcomeId") or "").strip(),
            timeline_item_count=len(timeline),
            outcome_status=str(outcome.get("status") or task_payload.get("status") or "observed"),
        )
        return response


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


def _build_kernel_task_timeline(
    store: KernelJsonlStore,
    *,
    task: dict[str, Any],
    event: dict[str, Any],
    execution: dict[str, Any],
    outcome: dict[str, Any],
    deliveries: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    sequence = 0

    def add_entry(
        *,
        kind: str,
        status: str,
        at: str,
        summary: str,
        refs: list[dict[str, str]] | None = None,
        fields: dict[str, Any] | None = None,
    ) -> None:
        nonlocal sequence
        sequence += 1
        item = {
            "kind": kind,
            "status": status,
            "at": at,
            "summary": _trim(summary, 300),
            "refs": refs or [],
            "_sequence": sequence,
        }
        if fields:
            item.update(fields)
        entries.append(item)

    event_id = str(event.get("eventId") or task.get("creatorEventId") or "").strip()
    for row in _matching_stream_rows(store, "events", "eventId", event_id, fallback=event):
        status = str(row.get("status") or "observed").strip()
        semantic = row.get("semanticPayload") if isinstance(row.get("semanticPayload"), dict) else {}
        add_entry(
            kind=f"event.{status}",
            status=status,
            at=str(row.get("updatedAt") or row.get("createdAt") or ""),
            summary=f"Kernel event {status}: {str(semantic.get('semanticType') or 'agent.message').strip()}",
            refs=[_timeline_ref("event", "eventId", event_id)],
        )

    task_id = str(task.get("taskId") or "").strip()
    for row in _matching_stream_rows(store, "tasks", "taskId", task_id, fallback=task):
        status = str(row.get("status") or "observed").strip()
        add_entry(
            kind=f"task.{status}",
            status=status,
            at=str(row.get("updatedAt") or row.get("createdAt") or ""),
            summary=f"Task {status}: {str(row.get('goal') or '').strip()}",
            refs=[_timeline_ref("task", "taskId", task_id)],
        )

    work_run_id = str(execution.get("workRunId") or "").strip()
    for row in _matching_stream_rows(store, "executions", "workRunId", work_run_id, fallback=execution):
        status = str(row.get("status") or "observed").strip()
        add_entry(
            kind=f"execution.{status}",
            status=status,
            at=str(row.get("updatedAt") or row.get("createdAt") or row.get("startedAt") or ""),
            summary=f"WorkRun {status}",
            refs=[_timeline_ref("execution", "workRunId", work_run_id), _timeline_ref("task", "taskId", task_id)],
        )

    outcome_id = str(outcome.get("outcomeId") or "").strip()
    for row in _matching_stream_rows(store, "outcomes", "outcomeId", outcome_id, fallback=outcome):
        status = str(row.get("status") or "observed").strip()
        add_entry(
            kind=f"outcome.{status}",
            status=status,
            at=str(row.get("createdAt") or ""),
            summary=str(row.get("resultSummary") or f"Outcome {status}"),
            refs=[
                _timeline_ref("outcome", "outcomeId", outcome_id),
                _timeline_ref("execution", "workRunId", str(row.get("workRunId") or work_run_id).strip()),
                _timeline_ref("task", "taskId", task_id),
            ],
        )

    delivery_at = str(outcome.get("createdAt") or execution.get("endedAt") or execution.get("updatedAt") or "")
    for delivery in deliveries:
        if not isinstance(delivery, dict):
            continue
        status = str(delivery.get("status") or "observed").strip()
        wake = delivery.get("wake") if isinstance(delivery.get("wake"), dict) else {}
        target_agent_id = str(delivery.get("targetAgentId") or "").strip()
        inbox_message_id = str(delivery.get("inboxMessageId") or "").strip()
        wake_status = str(wake.get("wakeStatus") or "").strip()
        add_entry(
            kind=f"delivery.{status}",
            status=status,
            at=delivery_at,
            summary=f"Delivery {status} to {target_agent_id}",
            refs=[
                _timeline_ref("agent", "agentId", target_agent_id),
                _timeline_ref("inbox_message", "messageId", inbox_message_id),
                _timeline_ref("task", "taskId", task_id),
            ],
            fields={
                "targetAgentId": target_agent_id,
                "inboxMessageId": inbox_message_id,
                "wakeStatus": wake_status,
            },
        )

    proposal_rows = []
    proposal_ids = {str(item.get("proposalId") or "").strip() for item in proposals if isinstance(item, dict)}
    for row in store.read_stream("proposals"):
        if str(row.get("proposalId") or "").strip() in proposal_ids:
            proposal_rows.append(row)
    if not proposal_rows:
        proposal_rows = proposals
    for proposal in proposal_rows:
        if not isinstance(proposal, dict):
            continue
        status = str(proposal.get("status") or "observed").strip()
        proposal_id = str(proposal.get("proposalId") or "").strip()
        add_entry(
            kind=f"proposal.{status}",
            status=status,
            at=str(proposal.get("createdAt") or ""),
            summary=str(proposal.get("summary") or proposal.get("proposalType") or f"Proposal {status}"),
            refs=[
                _timeline_ref("proposal", "proposalId", proposal_id),
                _timeline_ref("outcome", "outcomeId", str(proposal.get("sourceOutcomeId") or outcome_id).strip()),
            ],
        )

    entries.sort(key=lambda item: (str(item.get("at") or ""), int(item.get("_sequence") or 0)))
    for item in entries:
        item.pop("_sequence", None)
        item["refs"] = [ref for ref in item.get("refs", []) if ref.get("id")]
    return entries


def _matching_stream_rows(
    store: KernelJsonlStore,
    stream: str,
    id_key: str,
    expected_id: str,
    *,
    fallback: dict[str, Any],
) -> list[dict[str, Any]]:
    expected = str(expected_id or "").strip()
    if not expected:
        return [dict(fallback)] if fallback else []
    rows = [dict(row) for row in store.read_stream(stream) if str(row.get(id_key) or "").strip() == expected]
    if rows:
        return rows
    return [dict(fallback)] if fallback else []


def _timeline_ref(kind: str, id_key: str, value: str) -> dict[str, str]:
    return {"kind": kind, id_key: str(value or "").strip(), "id": str(value or "").strip()}


def _kernel_projection_refs(event: dict[str, Any]) -> list[dict[str, str]]:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    source_surface = str(metadata.get("sourceSurface") or "").strip()
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add_ref(kind: str, value: Any, metadata_key: str) -> None:
        for item in _projection_ref_values(value, default_kind=kind):
            ref_kind = str(item.get("kind") or kind).strip()
            ref_id = str(item.get("id") or "").strip()
            if not ref_kind or not ref_id:
                continue
            dedupe_key = (ref_kind, ref_id, metadata_key)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            refs.append(
                {
                    "kind": ref_kind,
                    "id": ref_id,
                    "sourceSurface": source_surface,
                    "metadataKey": metadata_key,
                }
            )

    add_ref("session", metadata.get("sourceSessionId"), "sourceSessionId")
    add_ref("room", metadata.get("sourceRoomId"), "sourceRoomId")
    add_ref("message", metadata.get("sourceMessageId"), "sourceMessageId")
    add_ref("projection", metadata.get("projectionRef"), "projectionRef")
    return refs


def _projection_ref_values(value: Any, *, default_kind: str) -> list[dict[str, str]]:
    if isinstance(value, dict):
        ref_id = str(value.get("id") or value.get("ref") or value.get("value") or "").strip()
        if not ref_id:
            return []
        return [{"kind": str(value.get("kind") or default_kind).strip(), "id": ref_id}]
    if isinstance(value, (list, tuple)):
        refs: list[dict[str, str]] = []
        for item in value:
            refs.extend(_projection_ref_values(item, default_kind=default_kind))
        return refs
    ref_id = str(value or "").strip()
    if not ref_id:
        return []
    return [{"kind": default_kind, "id": ref_id}]


def _kernel_runtime_evidence_refs(
    *,
    event: dict[str, Any],
    task: dict[str, Any],
    execution: dict[str, Any],
    outcome: dict[str, Any],
) -> list[dict[str, str]]:
    event_status = str(event.get("status") or "").strip()
    outcome_status = str(outcome.get("status") or "").strip()
    if event_status == "rejected":
        event_code = "kernel.event.rejected"
    elif outcome_status:
        event_code = "kernel.event.completed"
    else:
        event_code = "kernel.event.observed"
    return [
        {
            "kind": "runtime_scene_event",
            "component": "agent_kernel",
            "layer": "runtime",
            "eventCode": event_code,
            "eventId": str(event.get("eventId") or task.get("creatorEventId") or "").strip(),
            "taskId": str(task.get("taskId") or "").strip(),
            "workRunId": str(execution.get("workRunId") or "").strip(),
            "outcomeId": str(outcome.get("outcomeId") or "").strip(),
        }
    ]


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


def _record_kernel_timeline_scene_event(
    event_code: str,
    *,
    task_id: str,
    event_id: str = "",
    outcome_id: str = "",
    timeline_item_count: int = 0,
    outcome_status: str = "observed",
    level: str = "info",
) -> None:
    try:
        record_runtime_scene_event(
            "agent_kernel",
            "runtime",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome_status,
            fields={
                "taskId": str(task_id or "").strip(),
                "eventId": str(event_id or "").strip(),
                "outcomeId": str(outcome_id or "").strip(),
                "timelineItemCount": int(timeline_item_count or 0),
            },
            lifecycle=True,
        )
    except Exception:
        return
