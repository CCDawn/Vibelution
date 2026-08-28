"""Internal proactive Session admission for trusted Agent plugins.

Unlike ``submit_session_message`` this entrypoint never writes a user message.
The trigger is an internal, model-hidden journal fact; the plugin Prompt Pack
supplies the bounded semantic context used by the model turn.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any

from .submit import (
    _normalize_trace_context_carrier,
    _require_positive_context_limit,
    _session_submit_admit_lock,
)

INTERNAL_TURN_TRIGGER_EVENT = "internal_turn_trigger"

logger = logging.getLogger(__name__)

_PROACTIVE_CONTEXTS_LOCK = threading.Lock()
_PROACTIVE_CONTEXTS: dict[str, dict[str, Any]] = {}


def _service():
    from core.web.services import session_service

    return session_service


def submit_session_proactive_turn(
    *,
    session_id: str,
    agent_id: str,
    origin: str,
    source_kind: str,
    plugin_id: str,
    trigger_id: str,
    delivery_token: str,
    binding_revision: int,
    trigger: dict[str, Any] | None = None,
    trace_context_carrier: dict[str, str] | None = None,
) -> dict[str, Any]:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    normalized_agent_id = str(agent_id or "").strip()
    normalized_trigger_id = str(trigger_id or "").strip()
    normalized_delivery_token = str(delivery_token or "").strip()
    if str(origin or "").strip() != "proactive_plugin":
        raise s.SessionValidationError("Internal proactive turns require origin=proactive_plugin.")
    if str(source_kind or "").strip() != "virtual-human-life" or str(plugin_id or "").strip() != "virtual-human-life":
        raise s.SessionValidationError("Unsupported proactive plugin source.")
    if not all(
        [
            normalized_session_id,
            normalized_agent_id,
            normalized_trigger_id,
            normalized_delivery_token,
            int(binding_revision or 0) > 0,
        ]
    ):
        raise s.SessionValidationError("Proactive turn identity is incomplete.")
    from core.web.services.virtual_human_life_service import (
        get_virtual_human_life_service,
    )

    plugin_service = get_virtual_human_life_service()
    if not plugin_service.proactive_turn_is_current(
        agent_id=normalized_agent_id,
        binding_revision=int(binding_revision),
        delivery_token=normalized_delivery_token,
    ):
        raise s.SessionValidationError("The proactive trigger is stale or no longer authorized.")
    trigger_payload = dict(trigger or {})
    turn_id = f"{normalized_session_id}-proactive-{uuid.uuid4().hex[:16]}"
    plugin_metadata = {
        "pluginId": "virtual-human-life",
        "triggerId": normalized_trigger_id,
        "deliveryToken": normalized_delivery_token,
        "bindingRevision": int(binding_revision),
        "sourceKind": "virtual-human-life",
        "trigger": trigger_payload,
    }
    context = {
        "session_id": normalized_session_id,
        "turn_id": turn_id,
        "turn_control": None,
        "origin": "proactive_plugin",
        "user_message": "",
        "raw_user_message": "",
        "user_message_source": "proactive_plugin",
        "attachments": [],
        "session_references": [],
        "history_messages": [],
        "active_task": None,
        "agent_id": normalized_agent_id,
        "agent_snapshot": {},
        "agent_prompt_snapshot": {},
        "leases": [],
        "message_metadata": {"kind": "internal_turn_trigger", **plugin_metadata},
        "client_submission_id": "",
        "supervised_context": {},
        "skill_invocation": None,
        "active_skill_contract": None,
        "llm_slot": s.SESSION_LLM_SLOT_DIALOGUE,
        "trace_context_carrier": _normalize_trace_context_carrier(trace_context_carrier),
        "proactive_plugin": plugin_metadata,
        "allow_internal_auto_continue": False,
        "_proactive_admitted": False,
        "_scheduler_deferred_session_admission": True,
        "_scheduler_priority": 100,
    }
    register_proactive_turn_context(context)
    s._record_session_turn_scheduled_event(context)
    try:
        s._schedule_session_turn(context)
    except Exception:
        cancel_proactive_turn_context(context, reason="schedule_failed")
        if bool(context.get("_proactive_admitted")):
            s._set_session_running(normalized_session_id, False, turn_id=turn_id)
            s._clear_session_turn_control(normalized_session_id, turn_id=turn_id)
        raise
    admitted = s._is_session_turn_current(normalized_session_id, turn_id)
    now = s._now_timestamp()
    return {
        "accepted": True,
        "sessionId": normalized_session_id,
        "turnId": turn_id,
        "status": "running" if admitted else "queued",
        "acceptedAt": now,
        "origin": "proactive_plugin",
        "triggerId": normalized_trigger_id,
        "deliveryToken": normalized_delivery_token,
    }


def admit_session_proactive_turn(context: dict[str, Any]) -> str:
    """Admit one proactive turn only after the scheduler selects it to run.

    Returns ``admitted``, ``defer`` when a user turn won the race, or
    ``cancelled`` when the plugin revision/identity fence is no longer valid.
    """

    s = _service()
    if str(context.get("origin") or "") != "proactive_plugin":
        return "cancelled"
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    agent_id = str(context.get("agent_id") or "").strip()
    metadata = (
        context.get("proactive_plugin")
        if isinstance(context.get("proactive_plugin"), dict)
        else {}
    )
    delivery_token = str(metadata.get("deliveryToken") or "").strip()
    binding_revision = int(metadata.get("bindingRevision") or 0)
    from core.web.services.virtual_human_life_service import (
        get_virtual_human_life_service,
    )

    plugin_service = get_virtual_human_life_service()
    if not plugin_service.proactive_turn_is_current(
        agent_id=agent_id,
        binding_revision=binding_revision,
        delivery_token=delivery_token,
    ):
        cancel_proactive_turn_context(context, reason="binding_revision_fence_before_admission")
        return "cancelled"

    admit_lock = _session_submit_admit_lock(session_id)
    admit_lock.acquire()
    try:
        if not plugin_service.proactive_turn_is_current(
            agent_id=agent_id,
            binding_revision=binding_revision,
            delivery_token=delivery_token,
        ):
            cancel_proactive_turn_context(context, reason="binding_revision_fence_during_admission")
            return "cancelled"
        if s._is_session_running(session_id) and not s._is_session_turn_current(
            session_id,
            turn_id,
        ):
            return "defer"
        s._reconcile_stale_session_ledger(
            session_id,
            reason="proactive_turn_dequeued",
        )
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
        if conversation is None:
            raise s.SessionNotFoundError("Session not found.")
        s._ensure_session_mutable(session_id, conversation=conversation)
        _require_positive_context_limit(s, conversation, s.get_web_language())
        conversation_agent_id = str(
            conversation.get("agent_id") or conversation.get("agentId") or ""
        ).strip()
        if conversation_agent_id != agent_id:
            raise s.SessionValidationError(
                "Proactive turn Agent does not own the target session."
            )
        agent = s._resolve_active_agent_for_turn(
            session_id,
            agent_id,
            lang=s.get_web_language(),
        )
        if str(agent.get("directSessionId") or "").strip() != session_id:
            raise s.SessionValidationError(
                "Proactive turns require the Agent direct session."
            )
        previous_messages = s._session_ledger_visible_messages(session_id)
        turn_control = s._create_session_turn_control(session_id, turn_id=turn_id)
        now = s._now_timestamp()
        conversation.pop("messages", None)
        conversation.pop("last_turn_error", None)
        conversation.pop("lastTurnError", None)
        conversation["last_turn_status"] = "running"
        conversation["updated_at"] = now
        s.save_session_chat_state(s.PROJECT_ROOT, session_id, conversation)
        s._set_session_running(session_id, True, turn_id=turn_id, leases=[])
        s._persist_chat_turn_work_run(
            session_id=session_id,
            turn_id=turn_id,
            status="running",
            agent_id=agent_id,
            leases=[],
            user_message="",
            started_at=now,
            updated_at=now,
        )
        context.update(
            {
                "turn_control": turn_control,
                "history_messages": previous_messages,
                "agent_snapshot": dict(agent),
                "agent_prompt_snapshot": (
                    dict(conversation.get("agentPromptSnapshot") or {})
                    if isinstance(conversation.get("agentPromptSnapshot"), dict)
                    else {}
                ),
                "_proactive_admitted": True,
            }
        )
        # The scheduler executes a shallow copy of the submitted context.  Keep
        # the cancellation registry pointed at that admitted copy so a binding
        # disable or executor-submit failure can close the real Turn owner.
        register_proactive_turn_context(context)
    finally:
        admit_lock.release()

    trigger_payload = (
        dict(metadata.get("trigger") or {})
        if isinstance(metadata.get("trigger"), dict)
        else {}
    )
    s._append_session_conversation_event(
        session_id,
        turn_id,
        s.EVENT_TURN_STARTED,
        status="running",
        payload={
            "agentId": agent_id,
            "leases": [],
            "source": "proactive_plugin",
            "pluginId": "virtual-human-life",
        },
        source="submit_session_proactive_turn",
        visible_in_model=False,
        correlation_id=delivery_token,
        source_kind="virtual-human-life",
    )
    s._append_session_conversation_event(
        session_id,
        turn_id,
        INTERNAL_TURN_TRIGGER_EVENT,
        status="recorded",
        payload={
            "agentId": agent_id,
            "pluginId": "virtual-human-life",
            "triggerId": str(metadata.get("triggerId") or ""),
            "deliveryToken": delivery_token,
            "bindingRevision": binding_revision,
            **trigger_payload,
        },
        source="submit_session_proactive_turn",
        visible_in_model=False,
        correlation_id=delivery_token,
        source_kind="virtual-human-life",
    )
    s._set_session_waiting_live_output(session_id, turn_id=turn_id)
    return "admitted"


def register_proactive_turn_context(context: dict[str, Any]) -> None:
    metadata = context.get("proactive_plugin") if isinstance(context.get("proactive_plugin"), dict) else {}
    delivery_token = str(metadata.get("deliveryToken") or "").strip()
    if not delivery_token:
        return
    with _PROACTIVE_CONTEXTS_LOCK:
        _PROACTIVE_CONTEXTS[delivery_token] = context


def release_proactive_turn_context(context: dict[str, Any]) -> None:
    metadata = context.get("proactive_plugin") if isinstance(context.get("proactive_plugin"), dict) else {}
    delivery_token = str(metadata.get("deliveryToken") or "").strip()
    if not delivery_token:
        return
    with _PROACTIVE_CONTEXTS_LOCK:
        _PROACTIVE_CONTEXTS.pop(delivery_token, None)


def cancel_virtual_human_proactive_turns(agent_id: str, *, reason: str) -> list[str]:
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    with _PROACTIVE_CONTEXTS_LOCK:
        contexts = [
            context
            for context in _PROACTIVE_CONTEXTS.values()
            if str(context.get("agent_id") or "").strip() == normalized_agent_id
        ]
    cancelled: list[str] = []
    for context in contexts:
        session_id = str(context.get("session_id") or "").strip()
        turn_id = str(context.get("turn_id") or "").strip()
        controller = s._get_session_turn_control(session_id)
        if controller is not None and str(controller.turn_id or "").strip() == turn_id:
            controller.request_stop(str(reason or "virtual_human_binding_invalidated"))
        queued = s._cancel_queued_session_turn(session_id, turn_id)
        if queued:
            cancel_proactive_turn_context(context, reason=reason)
            if bool(context.get("_proactive_admitted")):
                s._set_session_running(session_id, False, turn_id=turn_id)
                s._clear_session_turn_control(session_id, turn_id=turn_id)
                s._publish_session_detail_snapshot(session_id)
        cancelled.append(turn_id)
    return cancelled


def cancel_proactive_turn_context(context: dict[str, Any], *, reason: str) -> None:
    s = _service()
    if str(context.get("origin") or "") != "proactive_plugin":
        return
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    metadata = context.get("proactive_plugin") if isinstance(context.get("proactive_plugin"), dict) else {}
    # Session cancellation and the plugin delivery ledger are separate durable
    # surfaces. Reconcile both so a binding/host fence cannot leave a delivering
    # attempt open forever after its in-memory context is released.
    try:
        from core.web.services.virtual_human_life_service import (
            get_virtual_human_life_service,
        )

        get_virtual_human_life_service().cancel_proactive_attempt(
            str(context.get("agent_id") or "").strip(),
            str(metadata.get("deliveryToken") or "").strip(),
            reason=reason,
        )
    except Exception as exc:  # noqa: BLE001 - plugin storage is an optional adapter here
        # Session cancellation remains best-effort even if plugin storage is
        # unavailable; the next startup reconciliation can repair the ledger.
        logger.warning(
            "Failed to reconcile cancelled proactive attempt for agent=%s (%s).",
            str(context.get("agent_id") or "").strip(),
            type(exc).__name__,
        )
    if not bool(context.get("_proactive_admitted")):
        release_proactive_turn_context(context)
        return
    try:
        existing_terminal = any(
            str(getattr(event, "turn_id", "") or "").strip() == turn_id
            and str(getattr(event, "event_type", "") or "")
            in {s.EVENT_TURN_COMPLETED, s.EVENT_TURN_FAILED, s.EVENT_TURN_INTERRUPTED}
            for event in s._load_session_conversation_events_cached(session_id)
        )
        if not existing_terminal:
            s._append_session_conversation_event(
                session_id,
                turn_id,
                s.EVENT_TURN_INTERRUPTED,
                status="cancelled",
                payload={
                    "reason": str(reason or "binding_invalidated")[:160],
                    "pluginId": "virtual-human-life",
                    "triggerId": str(metadata.get("triggerId") or ""),
                    "deliveryToken": str(metadata.get("deliveryToken") or ""),
                },
                source="virtual_human_life_revision_fence",
                visible_in_model=False,
                correlation_id=str(metadata.get("deliveryToken") or ""),
                source_kind="virtual-human-life",
            )
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
        if conversation is not None:
            conversation["last_turn_status"] = "ready"
            conversation["updated_at"] = s._now_timestamp()
            s.save_session_chat_state(s.PROJECT_ROOT, session_id, conversation)
        s._persist_chat_turn_work_run(
            session_id=session_id,
            turn_id=turn_id,
            status="stopped",
            summary="Virtual human proactive turn cancelled by the binding revision fence.",
            finished_at=s._now_timestamp(),
            updated_at=s._now_timestamp(),
        )
        s._clear_session_live_output(session_id, turn_id=turn_id)
    finally:
        # Cancellation is a terminal transition, including failures that occur
        # after admission but before the executor owns the Turn.  Always clear
        # the Session runtime projection so the frontend cannot remain running.
        s._set_session_running(session_id, False, turn_id=turn_id)
        s._clear_session_turn_control(session_id, turn_id=turn_id)
        s._publish_session_detail_snapshot(session_id)
        release_proactive_turn_context(context)


__all__ = [
    "INTERNAL_TURN_TRIGGER_EVENT",
    "admit_session_proactive_turn",
    "cancel_proactive_turn_context",
    "cancel_virtual_human_proactive_turns",
    "register_proactive_turn_context",
    "release_proactive_turn_context",
    "submit_session_proactive_turn",
]
