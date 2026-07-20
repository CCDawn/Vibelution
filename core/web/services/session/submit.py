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
from typing import Any


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import session_service

    return session_service


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

    if normalized_mode == "interrupt" and running:
        return s.request_stop_session_turn(conversation_id)

    s._publish_session_detail_snapshot(conversation_id)
    return s.get_session_detail(conversation_id) or detail

def submit_session_message(
    session_id: str,
    content: str,
    content_utf8_base64: str = "",
    mental_model_enabled: bool | None = None,
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
) -> dict:
    """Persist a user message and start a single web chat turn."""

    s = _service()
    submit_started_at = s._perf_counter()
    submit_timing_fields: dict[str, Any] = {}
    lang = s.get_web_language()
    conversation_id = str(session_id or "").strip()
    normalized_client_submission_id = str(client_submission_id or "").strip()
    message = _resolve_user_message_content(content, content_utf8_base64=content_utf8_base64)
    normalized_message_source = str(message_source or "").strip() or "raw"
    recent_image_reference_routing_enabled = normalized_message_source not in {
        "supervised_evolution",
        "self_observation",
    }
    if not conversation_id:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
    s._validate_user_message_not_encoding_replacement(message, lang=lang)
    lock_wait_started_at = s._perf_counter()
    with s._CHAT_STATE_LOCK:
        lock_acquired_at = s._perf_counter()
        submit_timing_fields["chatStateLockWaitMs"] = s._elapsed_ms_between(lock_wait_started_at, lock_acquired_at)
        payload = s.load_chat_state(s.PROJECT_ROOT)
        s._materialize_agent_directory_conversation_locked(payload, conversation_id, source="submit_session_message")
        conversation = s._find_conversation_entry(payload, conversation_id)
        if conversation is None:
            raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
        s._ensure_conversation_workspace_metadata(conversation)
        attachments = s._resolve_session_image_attachments(
            conversation_id,
            attachment_ids or [],
            conversation=conversation,
        )
        session_references = s._resolve_session_references(
            conversation_id,
            references or [],
            conversations=payload.get("conversations") or [],
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
            raise s.SessionBusyError(
                s.text_for(
                    lang,
                    zh="当前会话仍在运行，请等这一轮结束后再继续发送。",
                    en="This session is still running. Wait for the current turn to finish before sending again.",
                )
            )

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
            payload["updated_at"] = conversation.get("updated_at") or s._now_timestamp()
            s.save_chat_state(s.PROJECT_ROOT, payload)
            raise s.SessionBusyError(localized_reason)

        s._ensure_conversation_agent_metadata(conversation)
        agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
        agent = s._resolve_active_agent_for_turn(conversation_id, agent_id, lang=lang)
        skill_command = s.parse_skill_slash_command(message)
        skill_invocation = s._skill_invocation_payload(skill_command) if skill_command is not None else None
        s._reconcile_stale_session_ledger(conversation_id, reason="new_turn_submitted")
        previous_messages = s._session_ledger_visible_messages(conversation_id)
        turn_control = s._create_session_turn_control(conversation_id)
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
        kernel_trace_started_at = s._perf_counter()
        kernel_trace = s._create_direct_session_submit_kernel_trace(
            conversation,
            agent=agent,
            turn_id=turn_control.turn_id,
            message=message,
            source=normalized_message_source,
        )
        submit_timing_fields["kernelTraceMs"] = s._elapsed_ms(kernel_trace_started_at)
        if kernel_trace:
            persisted_message_metadata["kernel"] = kernel_trace
            if str(kernel_trace.get("status") or "").strip() == "recorded":
                for source_key, metadata_key in (
                    ("eventId", "kernelEventId"),
                    ("taskId", "kernelTaskId"),
                    ("workRunId", "kernelWorkRunId"),
                    ("outcomeId", "kernelOutcomeId"),
                ):
                    value = str(kernel_trace.get(source_key) or "").strip()
                    if value:
                        persisted_message_metadata[metadata_key] = value
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
        payload["active_conversation_id"] = conversation_id
        payload["updated_at"] = user_entry["timestamp"]
        s.save_chat_state(s.PROJECT_ROOT, payload)
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
        submit_timing_fields["chatStateLockedMs"] = s._elapsed_ms_between(lock_acquired_at)
    stage_started_at = s._perf_counter()
    s._append_session_conversation_event(
        conversation_id,
        turn_control.turn_id,
        s.EVENT_TURN_STARTED,
        status="running",
        payload={
            "agentId": agent_id,
            "leases": requested_leases,
            "source": normalized_message_source,
        },
        source="submit_session_message",
    )
    submit_timing_fields["turnStartedJournalMs"] = s._elapsed_ms(stage_started_at)
    stage_started_at = s._perf_counter()
    s._append_session_conversation_event(
        conversation_id,
        turn_control.turn_id,
        s.EVENT_USER_MESSAGE,
        status="recorded",
        payload={
            "content": message,
            "attachments": s._normalize_message_attachments(attachments),
            "references": s._normalize_session_references(session_references),
            "metadata": persisted_message_metadata,
            "source": normalized_message_source,
        },
        source="submit_session_message",
    )
    submit_timing_fields["userMessageJournalMs"] = s._elapsed_ms(stage_started_at)
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
        "submit_timing_fields": dict(submit_timing_fields),
        "submit_started_at_monotonic": submit_started_at,
    }
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
        s._set_session_running(conversation_id, False)
        s._clear_session_turn_control(conversation_id)
        s._persist_session_turn_failure(conversation_id, context, exc)
        s._publish_session_detail_snapshot(conversation_id)
        raise
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
    *,
    client_submission_id: str = "",
    attachment_ids: list[str] | None = None,
    references: list[dict[str, Any]] | None = None,
    turn_mode: str = "",
    write_intent: bool | None = None,
) -> dict[str, Any]:
    """Submit a user message and return the smallest accepted-turn payload."""

    s = _service()
    detail = submit_session_message(
        session_id,
        content,
        client_submission_id=client_submission_id,
        content_utf8_base64=content_utf8_base64,
        mental_model_enabled=mental_model_enabled,
        attachment_ids=attachment_ids,
        references=references,
        turn_mode=turn_mode,
        write_intent=write_intent,
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
    *,
    client_submission_id: str = "",
    turn_mode: str = "",
    write_intent: bool | None = None,
) -> dict:
    """Replace the latest user message, truncate later turns, and start a new turn."""

    s = _service()
    lang = s.get_web_language()
    conversation_id = str(session_id or "").strip()
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

    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, conversation_id)
        if conversation is None:
            raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
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
            payload["updated_at"] = conversation.get("updated_at") or s._now_timestamp()
            s.save_chat_state(s.PROJECT_ROOT, payload)
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
        payload["active_conversation_id"] = conversation_id
        payload["updated_at"] = user_entry["timestamp"]
        s.save_chat_state(s.PROJECT_ROOT, payload)
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
        "active_task": active_task,
        "agent_id": agent_id,
        "skill_invocation": skill_invocation,
        "active_skill_contract": active_skill_contract,
        "llm_slot": s.SESSION_LLM_SLOT_DIALOGUE,
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
        s._set_session_running(conversation_id, False)
        s._clear_session_turn_control(conversation_id)
        s._persist_session_turn_failure(conversation_id, context, exc)
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
