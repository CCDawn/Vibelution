"""Session submit entrypoints (Chat message / guidance / edit-resubmit).

Claim scope: user-turn acceptance path only — validate input, open turn,
write initial journal markers, publish first snapshot, schedule worker.
Do not put turn worker loop, stream capture, or team workflow here.

Bodies late-bind ``session_service`` for private helpers so import cycles are
avoided and the public facade can re-export these symbols unchanged.
"""

from __future__ import annotations

import base64
import binascii
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from .admission import (
    DevelopmentSubmissionAdmissionConfigurationError,
    get_development_submission_admission_runtime,
)


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import session_service

    return session_service


def _normalize_trace_context_carrier(value: object) -> dict[str, str]:
    from core.logging.trace_context import TraceContext, get_current_trace_context

    context = TraceContext.from_carrier(value)
    if context is None:
        context = get_current_trace_context()
    return context.to_carrier() if context is not None else {}


def _challenge_deadline_at_ms_for_submit(message_metadata: Mapping[str, Any] | None) -> int | None:
    """Copy an active workflow deadline into the executor-bound context only."""

    metadata = message_metadata if isinstance(message_metadata, Mapping) else {}
    if not (
        str(metadata.get("workflowRunId") or "").strip()
        and str(metadata.get("nodeRunId") or "").strip()
    ):
        return None
    try:
        from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
            current_challenge_task_deadline_at_ms,
        )

        deadline_at_ms = current_challenge_task_deadline_at_ms()
    except (ImportError, AttributeError):
        return None
    if isinstance(deadline_at_ms, int) and not isinstance(deadline_at_ms, bool) and deadline_at_ms > 0:
        return deadline_at_ms
    return None


_SESSION_SUBMIT_ADMIT_LOCKS_GUARD = threading.Lock()
_SESSION_SUBMIT_ADMIT_LOCKS: dict[str, threading.Lock] = {}


def _session_submit_admit_lock(session_id: str) -> threading.Lock:
    """Serialize admit for one session without blocking other sessions."""

    normalized = str(session_id or "").strip()
    with _SESSION_SUBMIT_ADMIT_LOCKS_GUARD:
        lock = _SESSION_SUBMIT_ADMIT_LOCKS.get(normalized)
        if lock is None:
            lock = threading.Lock()
            _SESSION_SUBMIT_ADMIT_LOCKS[normalized] = lock
        return lock


@contextmanager
def _release_acquired_lock(lock: threading.Lock) -> Iterator[threading.Lock]:
    try:
        yield lock
    finally:
        lock.release()


def _session_still_running_error(service: Any, lang: str) -> Any:
    return service.SessionBusyError(
        service.text_for(
            lang,
            zh="当前会话仍在运行，请等这一轮结束后再继续发送。",
            en="This session is still running. Wait for the current turn to finish before sending again.",
        )
    )


def _session_reference_conversation_rows(
    service: Any,
    conversation_id: str,
    conversation: dict[str, Any],
    references: Any,
) -> list[dict[str, Any]]:
    """Load only the current session and referenced session runtime rows."""

    rows = [conversation]
    seen = {str(conversation_id or "").strip()}
    for reference in service._normalize_session_references(references):
        target_id = str(reference.get("sessionId") or "").strip()
        if not target_id or target_id in seen:
            continue
        target = service.load_session_chat_state(service.PROJECT_ROOT, target_id)
        if target is None:
            continue
        rows.append(target)
        seen.add(target_id)
    return rows


def _require_positive_context_limit(service: Any, conversation: dict[str, Any], lang: str) -> dict[str, Any]:
    context_limit_payload = service._session_context_limit_payload(conversation)
    if int(context_limit_payload.get("limit") or 0) <= 0:
        detail = str(context_limit_payload.get("error") or "").strip()
        if not detail:
            detail = service.text_for(
                lang,
                zh="未配置模型 max 上下文窗口（禁止默认兜底）。请在设置中为对话模型填写 context_window，或先运行模型发现。",
                en="Model max context window is not configured (silent defaults are disabled). Set context_window for the dialogue model in settings, or run model discovery first.",
            )
        raise service.SessionValidationError(detail)
    return context_limit_payload


def _append_initial_session_journal_markers(
    *,
    session_id: str,
    turn_id: str,
    client_submission_id: str,
    agent: dict[str, Any],
    conversation: dict[str, Any],
    source: str,
    leases: list[str],
    user_payload: dict[str, Any],
) -> dict[str, Any]:
    """Append/recover one journal-backed user submission.

    SQLite is only consulted when an explicit development data root is set.
    Its receipt prevents duplicate journal writes for a retried browser
    submission; it never stores message text, reasoning, tools, or results.
    """

    s = _service()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    normalized_submission_id = str(client_submission_id or "").strip()

    def matching_events(event_type: str) -> list[Any]:
        if not normalized_submission_id:
            return []
        return [
            event
            for event in s._load_session_conversation_events_cached(normalized_session_id)
            if str(getattr(event, "correlation_id", "") or "").strip()
            == normalized_submission_id
            and str(getattr(event, "event_type", "") or "") == event_type
        ]

    def lookup(record: dict[str, Any]) -> dict[str, Any] | None:
        if not normalized_submission_id:
            return None
        events = matching_events(s.EVENT_USER_MESSAGE)
        if not events:
            return None
        event = events[-1]
        return {
            "journalSequence": int(getattr(event, "sequence", 0) or 0),
            "journalEventId": str(getattr(event, "event_id", "") or "").strip(),
        }

    def append(record: dict[str, Any]) -> dict[str, Any]:
        record_turn_id = str(record.get("turnId") or normalized_turn_id).strip()
        timings: dict[str, float] = {}
        if not matching_events(s.EVENT_TURN_STARTED):
            turn_started_at = s._perf_counter()
            s._append_session_conversation_event(
                normalized_session_id,
                record_turn_id,
                s.EVENT_TURN_STARTED,
                status="running",
                payload={
                    "agentId": str(record.get("agentId") or agent.get("agentId") or "").strip(),
                    "leases": list(leases),
                    "source": source,
                },
                source="submit_session_message",
                visible_in_model=False,
                correlation_id=normalized_submission_id,
            )
            timings["turnStartedJournalMs"] = s._elapsed_ms(turn_started_at)
        existing_user_events = matching_events(s.EVENT_USER_MESSAGE)
        if existing_user_events:
            user_event = existing_user_events[-1]
        else:
            user_message_started_at = s._perf_counter()
            user_event = s._append_session_conversation_event(
                normalized_session_id,
                record_turn_id,
                s.EVENT_USER_MESSAGE,
                status="recorded",
                payload=dict(user_payload),
                source="submit_session_message",
                correlation_id=normalized_submission_id,
            )
            timings["userMessageJournalMs"] = s._elapsed_ms(user_message_started_at)
        return {
            "journalSequence": int(getattr(user_event, "sequence", 0) or 0),
            "journalEventId": str(getattr(user_event, "event_id", "") or "").strip(),
            **timings,
        }

    runtime = get_development_submission_admission_runtime(s.PROJECT_ROOT)
    if runtime is None or not normalized_submission_id:
        receipt = append(
            {
                "sessionId": normalized_session_id,
                "turnId": normalized_turn_id,
                "agentId": str(agent.get("agentId") or agent.get("agent_id") or "").strip(),
            }
        )
        return {
            **receipt,
            "turnId": normalized_turn_id,
            "admissionDisposition": "disabled",
        }

    admission = runtime.admit(
        session_id=normalized_session_id,
        agent=agent,
        conversation=conversation,
        client_submission_id=normalized_submission_id,
        turn_id=normalized_turn_id,
        journal_lookup=lookup,
        journal_append=append,
    )
    return {
        "journalSequence": int(admission.get("journalSequence") or 0),
        "journalEventId": str(admission.get("journalEventId") or "").strip(),
        "turnId": str(admission.get("turnId") or "").strip(),
        "admissionDisposition": str(admission.get("journalDisposition") or ""),
    }


def submit_session_guidance(session_id: str, content: str, *, mode: str = "safe") -> dict:
    """Record operator guidance for a running turn, optionally interrupting it."""

    s = _service()
    lang = s.get_web_language()
    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))

    detail = s.get_session_detail(conversation_id)
    if detail is None:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))

    guidance_text = str(content or "").strip()
    if not guidance_text:
        raise s.SessionValidationError(s.text_for(lang, zh="引导内容不能为空。", en="Guidance content cannot be empty."))

    normalized_mode = str(mode or "").strip().lower().replace("-", "_")
    if normalized_mode not in {"safe", "interrupt"}:
        raise s.SessionValidationError(s.text_for(lang, zh="引导模式无效。", en="Invalid guidance mode."))

    with s._CHAT_STATE_LOCK:
        s._ensure_session_mutable(conversation_id)
        controller = s._get_session_turn_control(conversation_id)
        active_turn_id = ""
        if controller is not None:
            active_turn_id = str(controller.turn_id or "").strip()
        if not active_turn_id:
            for run in s.list_active_session_work_runs():
                if str(run.get("sessionId") or "").strip() == conversation_id:
                    active_turn_id = str(run.get("runId") or "").strip()
                    break

        running = s._is_session_running(conversation_id)
        signal = s._record_chat_next_state_signal(
            session_id=conversation_id,
            turn_id=active_turn_id,
            source="user",
            kind="user_interrupt_guidance" if normalized_mode == "interrupt" else "user_guidance",
            polarity="neutral",
            mode="directive",
            related_event_code=(
                "conversation.user_interrupt_guidance_submitted"
                if normalized_mode == "interrupt"
                else "conversation.user_guidance_submitted"
            ),
            summary=guidance_text,
            metadata={
                "guidanceMode": normalized_mode,
                "guidanceLength": len(guidance_text),
                "sessionRunning": running,
                "willRequestStop": normalized_mode == "interrupt" and running,
            },
        )
        s._record_session_guidance_event(
            conversation_id,
            mode=normalized_mode,
            turn_id=active_turn_id,
            signal_id=str((signal or {}).get("signalId") or ""),
            guidance_length=len(guidance_text),
            running=running,
        )

    guidance_kind = "user_interrupt_guidance" if normalized_mode == "interrupt" else "user_guidance"
    if active_turn_id:
        s._append_session_conversation_event(
            conversation_id,
            active_turn_id,
            s.EVENT_USER_MESSAGE,
            status="recorded",
            payload={
                "content": guidance_text,
                "attachments": [],
                "references": [],
                "metadata": {
                    "kind": guidance_kind,
                    "source": "steer",
                    "guidanceMode": normalized_mode,
                    "turnId": active_turn_id,
                },
                "source": "steer",
            },
            source="submit_session_guidance",
            visible_in_model=True,
        )

    if normalized_mode == "interrupt" and running:
        return s.request_stop_session_turn(conversation_id)

    s._publish_session_detail_snapshot(conversation_id)
    return s.get_session_detail(conversation_id) or detail

def submit_session_message(
    session_id: str,
    content: str,
    content_utf8_base64: str = "",
    mental_model_enabled: bool | None = None,
    runtime_status_enabled: bool | None = None,
    turn_status_tail: dict[str, Any] | None = None,
    *,
    client_submission_id: str = "",
    attachment_ids: list[str] | None = None,
    references: list[dict[str, Any]] | None = None,
    turn_mode: str = "",
    write_intent: bool | None = None,
    message_metadata: dict[str, Any] | None = None,
    message_source: str = "raw",
    include_started_turn_id: bool = False,
    lightweight_response: bool = False,
    trace_context_carrier: Mapping[str, Any] | None = None,
) -> dict:
    """Persist a user message and start a single web chat turn."""

    s = _service()
    submit_started_at = s._perf_counter()
    submit_timing_fields: dict[str, Any] = {}
    normalized_trace_context_carrier = _normalize_trace_context_carrier(trace_context_carrier)
    deferred_kernel_trace: dict[str, Any] | None = None
    lang = s.get_web_language()
    conversation_id = str(session_id or "").strip()
    normalized_client_submission_id = str(client_submission_id or "").strip()
    development_admission_runtime = None
    existing_development_admission: dict[str, Any] | None = None
    if normalized_client_submission_id:
        try:
            development_admission_runtime = get_development_submission_admission_runtime(
                s.PROJECT_ROOT
            )
        except DevelopmentSubmissionAdmissionConfigurationError as exc:
            raise s.SessionValidationError(str(exc)) from exc
        if development_admission_runtime is not None:
            existing_development_admission = development_admission_runtime.existing(
                session_id=conversation_id,
                client_submission_id=normalized_client_submission_id,
            )
            if str((existing_development_admission or {}).get("state") or "") in {
                "journaled",
                "projected",
            }:
                return _accepted_session_turn_payload(
                    conversation_id,
                    str(existing_development_admission.get("turnId") or "").strip(),
                    status="running",
                    client_submission_id=normalized_client_submission_id,
                )
    message = _resolve_user_message_content(content, content_utf8_base64=content_utf8_base64)
    normalized_message_source = str(message_source or "").strip() or "raw"
    recent_image_reference_routing_enabled = normalized_message_source not in {
        "supervised_evolution",
        "self_observation",
    }
    if not conversation_id:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
    s._validate_user_message_not_encoding_replacement(message, lang=lang)
    if s._is_session_running(conversation_id):
        raise _session_still_running_error(s, lang)

    # Ledger I/O is per-session. Holding _CHAT_STATE_LOCK across it serializes
    # every other session's 202 accept (measured 6-way wait ~20s).
    admit_lock = _session_submit_admit_lock(conversation_id)
    admit_lock.acquire()
    prepared_agent: dict[str, Any] | None = None
    prepared_agent_id = ""
    prepared_context_limit_ok = False
    try:
        if s._is_session_running(conversation_id):
            raise _session_still_running_error(s, lang)
        ledger_started_at = s._perf_counter()
        s._reconcile_stale_session_ledger(conversation_id, reason="new_turn_submitted")
        previous_messages = s._session_ledger_visible_messages(conversation_id)
        submit_timing_fields["ledgerReconcileMs"] = s._elapsed_ms(ledger_started_at)
        prepare_started_at = s._perf_counter()
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, conversation_id)
        if conversation is None:
            current_active = str(s.load_active_conversation_id(s.PROJECT_ROOT) or "").strip()
            if s._ensure_agent_directory_conversation_materialized(
                conversation_id,
                source="submit_session_message",
                activate=not current_active,
            ):
                conversation = s.load_session_chat_state(s.PROJECT_ROOT, conversation_id)
        if conversation is not None:
            s._ensure_session_mutable(
                conversation_id,
                conversation=conversation,
            )
            _require_positive_context_limit(s, conversation, lang)
            prepared_context_limit_ok = True
            prepared_agent_id = str(
                conversation.get("agent_id") or conversation.get("agentId") or ""
            ).strip()
            if prepared_agent_id:
                prepared_agent = s._resolve_active_agent_for_turn(
                    conversation_id,
                    prepared_agent_id,
                    lang=lang,
                )
        submit_timing_fields["submitPrepareMs"] = s._elapsed_ms(prepare_started_at)
    except BaseException:
        admit_lock.release()
        raise

    persist_started_at = s._perf_counter()
    submit_timing_fields["chatStateLockWaitMs"] = 0
    try:
        if conversation is None:
            raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
        # Fail closed: never run a turn with an invented context window.
        if not prepared_context_limit_ok:
            _require_positive_context_limit(s, conversation, lang)
        s._ensure_session_mutable(
            conversation_id,
            conversation=conversation,
        )
        s._ensure_conversation_workspace_metadata(conversation)
        attachments = s._resolve_session_image_attachments(
            conversation_id,
            attachment_ids or [],
            conversation=conversation,
        )
        session_references = s._resolve_session_references(
            conversation_id,
            references or [],
            conversations=_session_reference_conversation_rows(
                s,
                conversation_id,
                conversation,
                references or [],
            ),
            lang=lang,
        )
        active_task = s._normalize_session_active_task(conversation.get("active_task") or conversation.get("activeTask"))
        if not s._is_task_tool_backed_active_task(active_task):
            active_task = None
        explicit_recent_image_reference = (
            s._has_recent_image_attachment_reference(message)
            if recent_image_reference_routing_enabled
            else False
        )
        contextual_recent_image_request = (
            {}
            if not recent_image_reference_routing_enabled or attachments or explicit_recent_image_reference
            else s._image_context_request_for_retry(
                message,
                conversation=conversation,
            )
        )
        contextual_recent_image_prompt = str(contextual_recent_image_request.get("prompt") or "").strip()
        contextual_recent_image_artifact_ids = [
            str(item or "").strip()
            for item in list(contextual_recent_image_request.get("artifactIds") or [])
            if str(item or "").strip()
        ]
        recent_image_reference_prompt = message if explicit_recent_image_reference else contextual_recent_image_prompt
        recent_image_reference_requested = not attachments and bool(recent_image_reference_prompt)
        recent_image_reference_missing = False
        if recent_image_reference_requested:
            if contextual_recent_image_artifact_ids:
                attachments = s._resolve_session_image_attachments(
                    conversation_id,
                    contextual_recent_image_artifact_ids,
                    conversation=conversation,
                )
                recent_image_reference_missing = not bool(attachments)
            elif explicit_recent_image_reference:
                recent_attachment = s._find_recent_user_image_attachment(conversation)
                if recent_attachment:
                    attachments = s._resolve_session_image_attachments(
                        conversation_id,
                        [str(recent_attachment.get("artifactId") or "").strip()],
                        conversation=conversation,
                    )
                else:
                    recent_image_reference_missing = True
            else:
                recent_image_reference_missing = True
        if not message and not attachments and not session_references:
            raise s.SessionValidationError(
                s.text_for(lang, zh="请输入本轮消息、添加图片或引用会话后再发送。", en="Enter a message, attach an image, or reference a session before sending.")
            )

        if s._is_session_running(conversation_id):
            raise _session_still_running_error(s, lang)

        if normalized_message_source == "supervised_evolution":
            requested_leases = [s.SUPERVISED_EVALUATION_CHAT_LEASE]
        else:
            requested_leases = s.infer_chat_turn_leases(
                {
                    "content": message,
                    "mode": turn_mode,
                    "writeIntent": write_intent,
                    "activeTask": active_task,
                }
            )
        lease_decision = s._check_chat_turn_lease_decision(requested_leases)
        if not lease_decision.allowed:
            localized_reason = s._localize_lease_conflict(lease_decision.reason, lang=lang)
            s._persist_session_preflight_rejection(
                conversation,
                message=message,
                reason=localized_reason,
                error_type="resource_lease_conflict",
                http_status=409,
                source="conversation.turn.lease_conflict",
                requested_leases=requested_leases,
                lease_conflicts=lease_decision.conflicts,
                lang=lang,
            )
            s.save_session_chat_state(s.PROJECT_ROOT, conversation_id, conversation)
            raise s.SessionBusyError(localized_reason)

        if prepared_agent is None:
            s._ensure_conversation_agent_metadata(conversation)
            agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
            agent = s._resolve_active_agent_for_turn(conversation_id, agent_id, lang=lang)
        else:
            agent_id = str(
                conversation.get("agent_id") or conversation.get("agentId") or prepared_agent_id
            ).strip() or prepared_agent_id
            agent = prepared_agent
        skill_command = s.parse_skill_slash_command(message)
        skill_invocation = s._skill_invocation_payload(skill_command) if skill_command is not None else None
        reserved_turn_id = str(
            (existing_development_admission or {}).get("turnId") or ""
        ).strip()
        turn_control = s._create_session_turn_control(
            conversation_id,
            turn_id=reserved_turn_id,
        )
        active_skill_contract = (
            s._active_skill_contract_from_invocation(skill_invocation, turn_id=turn_control.turn_id)
            if skill_invocation
            else s._active_skill_contract_from_conversation(conversation)
        )
        persisted_message_metadata = dict(message_metadata or {}) if isinstance(message_metadata, dict) else {}
        if s._is_continue_request(message) and not str(persisted_message_metadata.get("kind") or "").strip():
            inherited_stage_task_metadata = s._source_collection_stage_task_continuation_metadata(previous_messages)
            if inherited_stage_task_metadata:
                persisted_message_metadata = {
                    **inherited_stage_task_metadata,
                    **persisted_message_metadata,
                    "sourceCollectionStageContinuation": True,
                }
        if normalized_client_submission_id:
            persisted_message_metadata["clientSubmissionId"] = normalized_client_submission_id
        persisted_message_metadata.setdefault("turnId", turn_control.turn_id)
        # Kernel bridge is audit/traceOnly: never hold CHAT_STATE_LOCK or block
        # Prefer: respond-async accept on its latency (measured cold path ~5s).
        deferred_kernel_trace = {
            "conversationId": conversation_id,
            "agent": dict(agent) if isinstance(agent, dict) else {},
            "turnId": turn_control.turn_id,
            "message": message,
            "source": normalized_message_source,
        }
        conversation_snapshot_for_kernel = {
            "id": conversation_id,
            "conversation_id": conversation_id,
            "agent_id": agent_id,
            "agentId": agent_id,
        }
        deferred_kernel_trace["conversation"] = conversation_snapshot_for_kernel
        if session_references:
            persisted_message_metadata["sessionReferences"] = session_references
        if skill_invocation:
            persisted_message_metadata["slashSkillCommand"] = {
                "command": skill_invocation.get("command", ""),
                "skillName": skill_invocation.get("skillName", ""),
                "skillHash": skill_invocation.get("skillHash", ""),
            }
            if active_skill_contract is not None:
                conversation["active_skill_contract"] = active_skill_contract
        user_entry = s._make_chat_message(
            "user",
            message,
            metadata=persisted_message_metadata,
            attachments=attachments,
            references=session_references,
        )
        if recent_image_reference_requested:
            user_entry.setdefault("metadata", {})
            user_entry["metadata"]["resolvedRecentImageReference"] = {
                "status": "missing" if recent_image_reference_missing else "resolved",
                "source": "explicit" if explicit_recent_image_reference else "contextual_retry",
                "prompt": s.trim_lines(recent_image_reference_prompt, max_lines=3),
                "artifactIds": [
                    str(item.get("artifactId") or "").strip()
                    for item in s._normalize_message_attachments(attachments)
                    if str(item.get("artifactId") or "").strip()
                ],
            }
        persisted_message_metadata = {
            **persisted_message_metadata,
            **(user_entry.get("metadata") if isinstance(user_entry.get("metadata"), dict) else {}),
        }
        conversation.pop("messages", None)
        conversation.pop("last_turn_error", None)
        conversation.pop("lastTurnError", None)
        conversation["last_turn_status"] = "running"
        conversation["updated_at"] = user_entry["timestamp"]
        s.save_session_chat_state(s.PROJECT_ROOT, conversation_id, conversation)
        s._set_session_running(conversation_id, True, turn_id=turn_control.turn_id, leases=requested_leases)
        s._persist_chat_turn_work_run(
            session_id=conversation_id,
            turn_id=turn_control.turn_id,
            status="running",
            agent_id=agent_id,
            leases=requested_leases,
            user_message=message,
            started_at=user_entry["timestamp"],
            updated_at=user_entry["timestamp"],
        )
        submit_timing_fields["chatStateLockedMs"] = s._elapsed_ms_between(persist_started_at)
    finally:
        admit_lock.release()
    from . import directory_bridge

    directory_bridge.sync_conversation_record(
        conversation,
        last_preview=message,
        status="running",
        wait=False,
    )
    stage_started_at = s._perf_counter()
    journal_receipt = _append_initial_session_journal_markers(
        session_id=conversation_id,
        turn_id=turn_control.turn_id,
        client_submission_id=normalized_client_submission_id,
        agent=dict(agent) if isinstance(agent, dict) else {"agentId": agent_id},
        conversation=dict(conversation) if isinstance(conversation, dict) else {},
        source=normalized_message_source,
        leases=requested_leases,
        user_payload={
            "content": message,
            "attachments": s._normalize_message_attachments(attachments),
            "references": s._normalize_session_references(session_references),
            "metadata": persisted_message_metadata,
            "source": normalized_message_source,
        },
    )
    admitted_turn_id = str(journal_receipt.get("turnId") or "").strip()
    if admitted_turn_id and admitted_turn_id != turn_control.turn_id:
        raise RuntimeError("Submission admission turn identity changed during journal append.")
    submit_timing_fields["initialJournalMarkersMs"] = s._elapsed_ms(stage_started_at)
    submit_timing_fields.setdefault("turnStartedJournalMs", 0)
    submit_timing_fields.setdefault("userMessageJournalMs", 0)
    for journal_timing_field in ("turnStartedJournalMs", "userMessageJournalMs"):
        if journal_timing_field in journal_receipt:
            submit_timing_fields[journal_timing_field] = journal_receipt[journal_timing_field]
    submit_timing_fields["sessionAdmissionDisposition"] = str(
        journal_receipt.get("admissionDisposition") or "disabled"
    )
    live_publish_started_at = s._perf_counter()
    s._set_session_waiting_live_output(conversation_id, turn_id=turn_control.turn_id)
    submit_timing_fields["initialLiveDeltaPublishMs"] = s._elapsed_ms(live_publish_started_at)
    submit_timing_fields["initialLivePublishMode"] = "assistant_delta"
    stage_started_at = s._perf_counter()
    s._submit_session_cycle_message_projection(
        conversation_id,
        user_entry,
        event="user_message",
        status="running",
        turn_id=turn_control.turn_id,
    )
    submit_timing_fields["cycleMessageDispatchMs"] = s._elapsed_ms(stage_started_at)
    submit_timing_fields["cycleMessageProjectionMode"] = "background_ordered"
    stage_started_at = s._perf_counter()
    s._record_session_turn_started_event(
        conversation_id,
        turn_id=turn_control.turn_id,
        leases=requested_leases,
        user_message=message,
        raw_user_message=message,
        user_message_source=normalized_message_source,
        attachments=attachments,
        trace_context_carrier=normalized_trace_context_carrier,
    )
    submit_timing_fields["turnStartedSceneLogMs"] = s._elapsed_ms(stage_started_at)
    if session_references:
        s._record_session_turn_lifecycle_event(
            conversation_id,
            "session_references_attached",
            turn_id=turn_control.turn_id,
            outcome="recorded",
            fields={
                "referenceCount": len(session_references),
                "targetSessionIds": [str(item.get("sessionId") or "").strip() for item in session_references],
                "queryAllowed": True,
                "sendRequiresExplicitUserIntent": True,
            },
        )
    if recent_image_reference_missing and normalized_message_source != "agent_inbox":
        visible = s._recent_image_attachment_missing_message(lang)
        s._finish_image_attachment_preflight_turn(
            conversation_id,
            turn_control.turn_id,
            {
                "status": "completed",
                "summary": visible,
                "raw_output": visible,
                "outcome": "needs_input",
                "metadata": {
                    "imageAttachmentPreflight": "missing_recent_image",
                },
            },
            decision="blocked",
            reason="missing_recent_image",
            agent_id=agent_id,
            attachments=[],
            leases=requested_leases,
            raw_user_message=message,
            fields={
                "recentImageReference": True,
                "resolvedRecentImageReference": False,
            },
            outcome="needs_input",
        )
        detail = s.get_session_detail(conversation_id) or {}
        if include_started_turn_id:
            detail["startedTurnId"] = turn_control.turn_id
        return detail
    if attachments and normalized_message_source != "agent_inbox":
        image_capability = s._resolve_image_attachment_capability(agent_instance=agent)
        image_capability_log_fields = {
            "supportsImageInput": image_capability.get("supports_image_input"),
            "llmSlot": s.SESSION_LLM_SLOT_DIALOGUE,
            "llmModelId": str(image_capability.get("model_id") or "").strip(),
            "dialogueModelId": s.agent_dialogue_model_id(agent),
            "visionModelId": s.agent_llm_model_id(agent, s.SESSION_LLM_SLOT_VISION),
            "modelName": image_capability.get("model_name") or "",
            "recentImageReference": bool(recent_image_reference_requested),
            "resolvedRecentImageReference": bool(recent_image_reference_requested and not recent_image_reference_missing),
            "recentImageReferenceSource": "explicit" if explicit_recent_image_reference else "contextual_retry" if recent_image_reference_requested else "",
        }
        if image_capability["supports_image_input"] is False:
            visible = s._image_input_unsupported_message(
                lang,
                model_name=str(image_capability.get("model_name") or "").strip(),
            )
            s._finish_image_attachment_preflight_turn(
                conversation_id,
                turn_control.turn_id,
                {
                    "status": "failed_runtime",
                    "summary": visible,
                    "raw_output": visible,
                    "error": visible,
                    "outcome": "blocked",
                    "metadata": {
                        "imageAttachmentPreflight": "unsupported_image_input",
                        "supportsImageInput": False,
                    },
                },
                decision="blocked",
                reason="unsupported_image_input",
                agent_id=agent_id,
                attachments=attachments,
                leases=requested_leases,
                raw_user_message=message,
                fields=image_capability_log_fields,
                outcome="blocked",
                level="warning",
            )
            detail = s.get_session_detail(conversation_id) or {}
            if include_started_turn_id:
                detail["startedTurnId"] = turn_control.turn_id
            return detail
        s._record_image_attachment_capability_event(
            conversation_id,
            turn_id=turn_control.turn_id,
            decision="forwarded",
            reason="supported" if image_capability["supports_image_input"] is True else "unknown_fail_open",
            outcome="scheduled",
            agent_id=agent_id,
            attachments=attachments,
            fields=image_capability_log_fields,
        )

    prompt_resolve_started_at = s._perf_counter()
    if normalized_message_source == "agent_inbox":
        effective_user_message, user_message_source = message, normalized_message_source
    elif attachments:
        effective_user_message = recent_image_reference_prompt or message
        user_message_source = "raw_with_attachments" if message else "attachments_only"
    elif normalized_message_source == "supervised_evolution":
        effective_user_message, user_message_source = message, normalized_message_source
    else:
        effective_user_message, user_message_source = s._resolve_session_user_prompt(
            conversation_id,
            message,
            previous_messages,
            existing_task=active_task,
        )
        if effective_user_message == message and normalized_message_source != "raw":
            user_message_source = normalized_message_source
    stage_task_continuation_prompt = s._source_collection_stage_task_continuation_prompt(persisted_message_metadata)
    if stage_task_continuation_prompt:
        effective_user_message = stage_task_continuation_prompt
        user_message_source = "source_collection_stage_task_continue"
    reference_prompt_block = s._session_reference_prompt_block(session_references)
    if reference_prompt_block:
        effective_user_message = "\n\n".join(part for part in [effective_user_message or message, reference_prompt_block] if part).strip()
        if not user_message_source or user_message_source == "raw":
            user_message_source = "raw_with_session_references" if message else "session_references_only"
    if effective_user_message != message:
        s._record_session_user_message_filtered_event(
            conversation_id,
            turn_id=turn_control.turn_id,
            reason="non_meaningful_user_message",
            message=message,
            source=user_message_source,
        )
    submit_timing_fields["userPromptResolveMs"] = s._elapsed_ms(prompt_resolve_started_at)
    if s._is_continue_request(message):
        s._record_chat_next_state_signal(
            session_id=conversation_id,
            turn_id=turn_control.turn_id,
            source="user",
            kind="user_continues",
            polarity="neutral",
            mode="directive",
            related_event_code="conversation.user_continue_requested",
            summary=s.text_for(
                lang,
                zh="用户请求继续上一轮未完成任务。",
                en="The user requested continuation of the unfinished task.",
            ),
            metadata={
                "userMessageSource": user_message_source,
                "effectivePromptLength": len(effective_user_message),
            },
        )

    context = {
        "session_id": conversation_id,
        "turn_id": turn_control.turn_id,
        "turn_control": turn_control,
        "user_message": effective_user_message,
        "raw_user_message": message,
        "user_message_source": user_message_source,
        "attachments": attachments,
        "session_references": session_references,
        "history_messages": previous_messages,
        "mental_model_enabled": mental_model_enabled,
        "runtime_status_enabled": runtime_status_enabled,
        "turn_status_tail": dict(turn_status_tail) if isinstance(turn_status_tail, dict) else None,
        "active_task": active_task,
        "agent_id": agent_id,
        "agent_snapshot": dict(agent) if isinstance(agent, dict) else {},
        "agent_prompt_snapshot": dict(conversation.get("agentPromptSnapshot") or {})
        if isinstance(conversation.get("agentPromptSnapshot"), dict)
        else {},
        "leases": requested_leases,
        "message_metadata": dict(persisted_message_metadata),
        "client_submission_id": normalized_client_submission_id,
        "supervised_context": dict(conversation.get("supervised_context") or {})
        if isinstance(conversation.get("supervised_context"), dict)
        else {},
        "skill_invocation": skill_invocation,
        "active_skill_contract": active_skill_contract,
        "llm_slot": s.SESSION_LLM_SLOT_DIALOGUE,
        "trace_context_carrier": dict(normalized_trace_context_carrier),
        "submit_timing_fields": dict(submit_timing_fields),
        "submit_started_at_monotonic": submit_started_at,
    }
    # ContextVars do not cross SESSION_EXECUTOR threads.  Carry the Ledger
    # deadline only as an ephemeral scheduler field for workflow-scoped
    # Challenge turns; it must never enter message metadata, the turn journal,
    # or chat state. Continuation metadata intentionally has no ``kind``.
    deadline_at_ms = _challenge_deadline_at_ms_for_submit(persisted_message_metadata)
    if deadline_at_ms is not None:
        context["_challenge_task_deadline_at_ms"] = deadline_at_ms
    stage_started_at = s._perf_counter()
    s._record_session_turn_scheduled_event(context)
    submit_timing_fields["scheduledSceneLogMs"] = s._elapsed_ms(stage_started_at)
    try:
        schedule_started_at = s._perf_counter()
        s._schedule_session_turn(context)
        submit_timing_fields["scheduleSubmitMs"] = s._elapsed_ms(schedule_started_at)
    except Exception as exc:
        s._persist_chat_turn_work_run(
            session_id=conversation_id,
            turn_id=turn_control.turn_id,
            status="failed",
            leases=requested_leases,
            user_message=message,
            summary=f"{type(exc).__name__}: {exc}",
        )
        # Persist while this turn is still current: both clearing the turn
        # control and flagging the session not-running drop the active-turn
        # identity the runtime-state commit gate requires.
        s._persist_session_turn_failure(conversation_id, context, exc)
        s._set_session_running(conversation_id, False)
        s._clear_session_turn_control(conversation_id)
        s._publish_session_detail_snapshot(conversation_id)
        raise
    # Defer kernel audit after schedule so accept latency is not gated by Kernel I/O.
    kernel_enqueue_started_at = s._perf_counter()
    if deferred_kernel_trace is not None:
        s._enqueue_direct_session_submit_kernel_trace(
            conversation=deferred_kernel_trace.get("conversation") or {},
            agent=deferred_kernel_trace.get("agent") or {},
            turn_id=str(deferred_kernel_trace.get("turnId") or ""),
            message=str(deferred_kernel_trace.get("message") or ""),
            source=str(deferred_kernel_trace.get("source") or ""),
        )
    submit_timing_fields["kernelTraceMs"] = 0
    submit_timing_fields["kernelTraceDeferred"] = True
    submit_timing_fields["kernelTraceEnqueueMs"] = s._elapsed_ms(kernel_enqueue_started_at)
    s._record_session_turn_accepted_event(context, submit_timing_fields)
    if lightweight_response:
        return _accepted_session_turn_payload(
            conversation_id,
            turn_control.turn_id,
            status="running",
            client_submission_id=normalized_client_submission_id,
        )
    detail = s.get_session_detail(conversation_id) or {}
    if include_started_turn_id:
        detail["startedTurnId"] = turn_control.turn_id
    return detail

def _accepted_session_turn_payload(
    session_id: str,
    turn_id: str,
    *,
    status: str = "running",
    client_submission_id: str = "",
) -> dict[str, Any]:
    s = _service()
    payload = {
        "accepted": True,
        "sessionId": str(session_id or "").strip(),
        "turnId": str(turn_id or "").strip(),
        "status": str(status or "running").strip() or "running",
        "acceptedAt": s._now_timestamp(),
    }
    normalized_client_submission_id = str(client_submission_id or "").strip()
    if normalized_client_submission_id:
        payload["clientSubmissionId"] = normalized_client_submission_id
    return payload

def submit_session_message_lightweight(
    session_id: str,
    content: str,
    content_utf8_base64: str = "",
    mental_model_enabled: bool | None = None,
    runtime_status_enabled: bool | None = None,
    turn_status_tail: dict[str, Any] | None = None,
    *,
    client_submission_id: str = "",
    attachment_ids: list[str] | None = None,
    references: list[dict[str, Any]] | None = None,
    turn_mode: str = "",
    write_intent: bool | None = None,
    trace_context_carrier: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit a user message and return the smallest accepted-turn payload."""

    detail = submit_session_message(
        session_id,
        content,
        client_submission_id=client_submission_id,
        content_utf8_base64=content_utf8_base64,
        mental_model_enabled=mental_model_enabled,
        runtime_status_enabled=runtime_status_enabled,
        turn_status_tail=turn_status_tail,
        attachment_ids=attachment_ids,
        references=references,
        turn_mode=turn_mode,
        write_intent=write_intent,
        trace_context_carrier=trace_context_carrier,
        include_started_turn_id=True,
        lightweight_response=True,
    )
    return detail

def edit_and_resubmit_session_message(
    session_id: str,
    message_id: str,
    content: str,
    content_utf8_base64: str = "",
    mental_model_enabled: bool | None = None,
    runtime_status_enabled: bool | None = None,
    turn_status_tail: dict[str, Any] | None = None,
    *,
    client_submission_id: str = "",
    turn_mode: str = "",
    write_intent: bool | None = None,
    trace_context_carrier: Mapping[str, Any] | None = None,
) -> dict:
    """Replace the latest user message, truncate later turns, and start a new turn."""

    s = _service()
    lang = s.get_web_language()
    conversation_id = str(session_id or "").strip()
    normalized_trace_context_carrier = _normalize_trace_context_carrier(trace_context_carrier)
    target_message_id = str(message_id or "").strip()
    normalized_client_submission_id = str(client_submission_id or "").strip()
    message = _resolve_user_message_content(content, content_utf8_base64=content_utf8_base64)
    if not conversation_id:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
    if not target_message_id:
        raise s.SessionValidationError(s.text_for(lang, zh="请选择要重新编辑的消息。", en="Choose a message to edit."))
    if not message:
        raise s.SessionValidationError(
            s.text_for(lang, zh="请输入重新发送的消息。", en="Enter the edited message before sending.")
        )
    s._validate_user_message_not_encoding_replacement(message, lang=lang)

    admit_lock = _session_submit_admit_lock(conversation_id)
    admit_lock.acquire()
    try:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, conversation_id)
        if conversation is None:
            raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
        s._ensure_session_mutable(
            conversation_id,
            conversation=conversation,
        )
        s._ensure_conversation_workspace_metadata(conversation)

        previous_messages = s._session_ledger_visible_messages(conversation_id)
        skill_command = s.parse_skill_slash_command(message)
        skill_invocation = s._skill_invocation_payload(skill_command) if skill_command is not None else None
        target_index = s._find_user_message_index_by_api_id(conversation_id, previous_messages, target_message_id)
        if target_index < 0:
            raise s.SessionValidationError(
                s.text_for(lang, zh="只能重新编辑历史用户消息。", en="Only historical user messages can be edited and resent.")
            )
        latest_user_index = s._latest_user_message_index(previous_messages)
        if target_index != latest_user_index:
            latest_message_id = ""
            if latest_user_index >= 0:
                latest_message_id = str(previous_messages[latest_user_index].get("id") or "").strip()
            s._record_session_message_edit_resubmit_rejected_event(
                conversation_id,
                target_message_id=target_message_id,
                reason="not_latest_user_message",
                latest_message_id=latest_message_id,
                target_preview=previous_messages[target_index].get("content") or "",
            )
            raise s.SessionValidationError(
                s.text_for(lang, zh="只能重新编辑最新一条用户消息。", en="Only the latest user message can be edited and resent.")
            )

        active_task = s._normalize_session_active_task(conversation.get("active_task") or conversation.get("activeTask"))
        if not s._is_task_tool_backed_active_task(active_task):
            active_task = None
        requested_leases = s.infer_chat_turn_leases(
            {
                "content": message,
                "mode": turn_mode,
                "writeIntent": write_intent,
                "activeTask": active_task,
            }
        )
        lease_decision = s._check_chat_turn_lease_decision(requested_leases)
        if not lease_decision.allowed:
            localized_reason = s._localize_lease_conflict(lease_decision.reason, lang=lang)
            s._persist_session_preflight_rejection(
                conversation,
                message=message,
                reason=localized_reason,
                error_type="resource_lease_conflict",
                http_status=409,
                source="conversation.turn.lease_conflict",
                requested_leases=requested_leases,
                lease_conflicts=lease_decision.conflicts,
                lang=lang,
            )
            s.save_session_chat_state(s.PROJECT_ROOT, conversation_id, conversation)
            raise s.SessionBusyError(localized_reason)

        s._ensure_conversation_agent_metadata(conversation)
        agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
        s._resolve_active_agent_for_turn(conversation_id, agent_id, lang=lang)
        original_entry = dict(previous_messages[target_index])
        history_before_target = previous_messages[:target_index]
        s._truncate_session_ledger_before_message(conversation_id, original_entry)
        original_metadata = original_entry.get("metadata") if isinstance(original_entry.get("metadata"), dict) else {}
        original_was_slash_skill = isinstance(original_metadata.get("slashSkillCommand"), dict)
        superseded_turn_id = ""
        if s._is_session_running(conversation_id):
            superseded_turn_id = s._supersede_active_session_turn_for_edit(conversation_id, lang=lang)
        turn_control = s._create_session_turn_control(conversation_id)
        active_skill_contract = (
            s._active_skill_contract_from_invocation(skill_invocation, turn_id=turn_control.turn_id)
            if skill_invocation
            else s._active_skill_contract_from_conversation(conversation)
        )
        user_metadata = {}
        if normalized_client_submission_id:
            user_metadata["clientSubmissionId"] = normalized_client_submission_id
        if skill_invocation:
            user_metadata["slashSkillCommand"] = {
                "command": skill_invocation.get("command", ""),
                "skillName": skill_invocation.get("skillName", ""),
                "skillHash": skill_invocation.get("skillHash", ""),
            }
            if active_skill_contract is not None:
                conversation["active_skill_contract"] = active_skill_contract
        elif original_was_slash_skill:
            active_skill_contract = None
            conversation.pop("active_skill_contract", None)
            conversation.pop("activeSkillContract", None)
        user_metadata.setdefault("turnId", turn_control.turn_id)
        user_entry = s._make_chat_message("user", message, metadata=user_metadata)
        conversation.pop("messages", None)
        conversation.pop("last_turn_error", None)
        conversation.pop("lastTurnError", None)
        conversation["last_turn_status"] = "running"
        conversation["updated_at"] = user_entry["timestamp"]
        s.save_session_chat_state(s.PROJECT_ROOT, conversation_id, conversation)
        s._set_session_running(conversation_id, True, turn_id=turn_control.turn_id, leases=requested_leases)
        s._persist_chat_turn_work_run(
            session_id=conversation_id,
            turn_id=turn_control.turn_id,
            status="running",
            agent_id=agent_id,
            leases=requested_leases,
            user_message=message,
            started_at=user_entry["timestamp"],
            updated_at=user_entry["timestamp"],
        )
    finally:
        admit_lock.release()
    s._append_session_conversation_event(
        conversation_id,
        turn_control.turn_id,
        s.EVENT_USER_MESSAGE,
        status="recorded",
        payload={
            "content": message,
            "source": "edited_user_message",
            "metadata": user_entry.get("metadata") if isinstance(user_entry.get("metadata"), dict) else user_metadata,
        },
        source="edit_and_resubmit_session_message",
    )

    s._set_session_waiting_live_output(conversation_id, turn_id=turn_control.turn_id)
    s._record_session_message_edit_resubmit_event(
        conversation_id,
        target_message_id=target_message_id,
        turn_id=turn_control.turn_id,
        truncated_count=max(0, len(previous_messages) - target_index - 1),
        original_content=original_entry.get("content") or "",
        edited_content=message,
    )
    s._record_chat_next_state_signal(
        session_id=conversation_id,
        turn_id=turn_control.turn_id,
        source="user",
        kind="assistant_output_edited",
        polarity="neutral",
        mode="directive",
        related_event_code="conversation.message_edited_resubmitted",
        summary=s.text_for(
            lang,
            zh="用户编辑最新消息并重新提交，后续 assistant 输出被截断重跑。",
            en="The user edited the latest message and resubmitted, truncating later assistant output.",
        ),
        metadata={
            "messageId": target_message_id,
            "truncatedMessageCount": max(0, len(previous_messages) - target_index - 1),
            "originalLength": len(str(original_entry.get("content") or "")),
            "editedLength": len(message),
            "supersededTurnId": superseded_turn_id,
        },
    )
    s._record_session_cycle_message(
        conversation_id,
        user_entry,
        event="user_message_edited_resubmitted",
        status="running",
    )
    s._record_session_turn_started_event(
        conversation_id,
        turn_id=turn_control.turn_id,
        leases=requested_leases,
        user_message=message,
        raw_user_message=message,
        user_message_source="raw",
        trace_context_carrier=normalized_trace_context_carrier,
    )
    s._publish_session_detail_snapshot(conversation_id)

    effective_user_message, user_message_source = s._resolve_session_user_prompt(
        conversation_id,
        message,
        history_before_target,
        existing_task=active_task,
    )
    if effective_user_message != message:
        s._record_session_user_message_filtered_event(
            conversation_id,
            turn_id=turn_control.turn_id,
            reason="non_meaningful_user_message",
            message=message,
            source=user_message_source,
        )

    context = {
        "session_id": conversation_id,
        "turn_id": turn_control.turn_id,
        "turn_control": turn_control,
        "user_message": effective_user_message,
        "raw_user_message": message,
        "user_message_source": user_message_source,
        "history_messages": history_before_target,
        "mental_model_enabled": mental_model_enabled,
        "runtime_status_enabled": runtime_status_enabled,
        "turn_status_tail": dict(turn_status_tail) if isinstance(turn_status_tail, dict) else None,
        "active_task": active_task,
        "agent_id": agent_id,
        "skill_invocation": skill_invocation,
        "active_skill_contract": active_skill_contract,
        "llm_slot": s.SESSION_LLM_SLOT_DIALOGUE,
        "trace_context_carrier": dict(normalized_trace_context_carrier),
    }
    s._record_session_turn_scheduled_event(context)
    try:
        s._schedule_session_turn(context)
    except Exception as exc:
        s._persist_chat_turn_work_run(
            session_id=conversation_id,
            turn_id=turn_control.turn_id,
            status="failed",
            leases=requested_leases,
            user_message=message,
            summary=f"{type(exc).__name__}: {exc}",
        )
        # Persist while this turn is still current: both clearing the turn
        # control and flagging the session not-running drop the active-turn
        # identity the runtime-state commit gate requires.
        s._persist_session_turn_failure(conversation_id, context, exc)
        s._set_session_running(conversation_id, False)
        s._clear_session_turn_control(conversation_id)
        s._publish_session_detail_snapshot(conversation_id)
        raise
    return s.get_session_detail(conversation_id) or {}

def _resolve_user_message_content(content: str, *, content_utf8_base64: str = "") -> str:
    encoded = str(content_utf8_base64 or "").strip()
    if not encoded:
        return str(content or "").strip()
    try:
        raw = base64.b64decode(encoded, validate=True)
        decoded = raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return str(content or "").strip()
    return decoded.strip()
