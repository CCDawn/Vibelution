"""Session list/detail DTO projection helpers.

Claim scope: list_sessions / get_session_detail and the summary/detail/cache
composition builders that shape API payloads.

SSE publish lives in ``publish.py``. Hot-path submit/worker/persist stay in
their own packs. Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


_SESSION_SUMMARY_MESSAGE_SCAN_LIMIT = 12
_SESSION_SUMMARY_EVENT_SCAN_LIMIT = 64


def _service():
    from core.web.services import session_service

    return session_service


def list_sessions(
    *,
    include_hidden_internal: bool = False,
    repair_collisions: bool = True,
) -> list[dict]:
    """Return summarized sessions sourced from persisted chat state."""
    s = _service()

    started_at = s._perf_counter()
    s._sync_agent_directory_project_root()
    signature = (s._session_list_source_signature(), bool(include_hidden_internal))
    if repair_collisions and s._repair_agent_direct_session_collisions(source_signature=signature):
        signature = (s._session_list_source_signature(), bool(include_hidden_internal))
    cached, should_build, waited_for_inflight = s._begin_session_list_cache_build(
        now=started_at,
        signature=signature,
        allow_stale_matching_signature=True,
    )
    if cached is not None:
        sessions, cache_age_ms, conversation_count, agent_count = cached
        s._record_session_list_loaded_event(
            session_count=len(sessions),
            conversation_count=conversation_count,
            agent_count=agent_count,
            elapsed_ms=s._elapsed_ms(started_at),
            cache_hit=True,
            cache_age_ms=cache_age_ms,
            cache_ttl_ms=int(round(s._SESSION_LIST_CACHE_TTL_SECONDS * 1000)),
            waited_for_inflight=waited_for_inflight,
        )
        return sessions
    if not should_build:
        return []

    try:
        agent_by_id = s._agent_lookup_for_conversations()
        hidden_team_member_agent_ids = s._agent_directory_stub_hidden_team_member_ids()
        load_phase_timings: dict[str, int] = {}
        active_id, conversations = s._load_conversations(
            repair=False,
            agent_by_id=agent_by_id,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
            lightweight=True,
            phase_timings=load_phase_timings,
        )
        summary_projection_started_at = s._perf_counter()
        conversations = s._append_agent_directory_conversations(
            conversations,
            agent_by_id=agent_by_id,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
        )
        sessions = []
        hidden_summaries = []
        for item in conversations:
            summary = s._build_session_summary(item, hydrate_agent=False)
            hidden_internal = not include_hidden_internal and s._empty_direct_agent_session_hidden_from_index(
                item,
                hidden_team_member_agent_ids,
            )
            if include_hidden_internal:
                sessions.append(summary)
            elif s._session_agent_visible_in_indexes(summary) and not hidden_internal:
                sessions.append(summary)
            else:
                hidden_summaries.append(summary)
        s._record_session_agent_missing_index_batch_event(hidden_summaries, source="list_sessions")
        sessions.sort(
            key=lambda item: (
                0 if item["id"] == active_id else 1,
                -s._timestamp_sort_key(item.get("updatedAt") or item.get("lastActive") or ""),
            )
        )
        summary_projection_ms = s._elapsed_ms(summary_projection_started_at)
        s._finish_session_list_cache_build(
            signature=signature,
            sessions=sessions,
            started_at=started_at,
            conversation_count=len(conversations),
            agent_count=len(agent_by_id),
        )
        s._record_session_list_loaded_event(
            session_count=len(sessions),
            conversation_count=len(conversations),
            agent_count=len(agent_by_id),
            elapsed_ms=s._elapsed_ms(started_at),
            cache_hit=False,
            cache_age_ms=0,
            cache_ttl_ms=int(round(s._SESSION_LIST_CACHE_TTL_SECONDS * 1000)),
            waited_for_inflight=waited_for_inflight,
            chat_state_wait_ms=load_phase_timings.get("chatStateWaitMs"),
            chat_state_read_ms=load_phase_timings.get("chatStateReadMs"),
            conversation_normalize_ms=load_phase_timings.get("conversationNormalizeMs"),
            summary_projection_ms=summary_projection_ms,
        )
        return sessions
    except Exception:
        s._finish_session_list_cache_build(signature=signature, started_at=started_at)
        raise


def get_session_detail(
    session_id: str,
    *,
    message_limit: Any = None,
    before_message_index: Any = None,
    transcript_scope: Any = "all",
) -> dict | None:
    """Return a session detail payload by persisted conversation id."""
    s = _service()

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    window_requested = s._session_detail_window_requested(
        message_limit=message_limit,
        before_message_index=before_message_index,
        transcript_scope=transcript_scope,
    )

    s._ensure_agent_directory_conversation_materialized(normalized_session_id, source="s.get_session_detail")
    agent_by_id = s._agent_lookup_for_conversations()
    payload = s.load_chat_state(s.PROJECT_ROOT)
    if s._find_conversation_entry(payload, normalized_session_id) is None:
        fallback = s._agent_directory_session_stub_for_id(normalized_session_id, agent_by_id=agent_by_id)
        if fallback is None:
            return None
        return s._build_session_detail(
            fallback,
            message_limit=message_limit,
            before_message_index=before_message_index,
            transcript_scope=transcript_scope,
        )

    with s._RUNNING_SESSIONS_LOCK:
        active_turn_id = str(s._SESSION_ACTIVE_TURN_IDS.get(normalized_session_id) or "").strip()
        session_running = normalized_session_id in s._RUNNING_SESSION_IDS
    s._reconcile_stale_session_ledger(
        normalized_session_id,
        active_turn_id=active_turn_id if session_running else "",
        reason="detail_loaded_after_restart",
    )
    payload = s.load_chat_state(s.PROJECT_ROOT)
    target = s._load_conversation_detail_target(
        normalized_session_id,
        payload=payload,
        repair=True,
        agent_by_id=agent_by_id,
        lightweight=window_requested,
    )
    if target is not None:
        return s._build_session_detail(
            target,
            message_limit=message_limit,
            before_message_index=before_message_index,
            transcript_scope=transcript_scope,
        )
    return None


def get_active_session_detail() -> dict | None:
    """Return the current active conversation detail when available."""
    s = _service()

    active_id, conversations = s._load_conversations()
    if not conversations:
        return None
    target_id = active_id or conversations[0]["id"]
    for item in conversations:
        if item["id"] == target_id:
            return s._build_session_detail(item)
    return s._build_session_detail(conversations[0])


def get_active_session_summary() -> dict | None:
    """Return the current active conversation summary for shell-level polling."""
    s = _service()

    agent_by_id = s._agent_lookup_for_conversations()
    active_id, target = s._load_active_conversation_summary_target(agent_by_id=agent_by_id)
    if target is None:
        active_id, conversations = s._load_conversations(
            repair=False,
            agent_by_id=agent_by_id,
            lightweight=True,
        )
        conversations = s._append_agent_directory_conversations(conversations, agent_by_id=agent_by_id)
        if not conversations:
            return None
        target_id = str(active_id or "").strip()
        target = next(
            (
                item
                for item in conversations
                if isinstance(item, dict) and str(item.get("id") or "").strip() == target_id
            ),
            None,
        )
        if target is None:
            target = next((item for item in conversations if isinstance(item, dict)), None)
    if target is None:
        return None
    target = s._with_direct_session_agent_for_summary(target, agent_by_id=agent_by_id)
    return s._build_session_summary(target, hydrate_agent=False)


def _build_session_detail(
    conversation: dict[str, Any],
    *,
    message_limit: Any = None,
    before_message_index: Any = None,
    transcript_scope: Any = "all",
) -> dict[str, Any]:
    s = _service()
    summary = s._build_session_summary(conversation)
    return s._build_session_detail_from_summary(
        conversation,
        summary,
        hydrate_agent=True,
        message_limit=message_limit,
        before_message_index=before_message_index,
        transcript_scope=transcript_scope,
    )


def _build_session_detail_from_summary(
    conversation: dict[str, Any],
    summary: dict[str, Any],
    *,
    hydrate_agent: bool,
    message_limit: Any = None,
    before_message_index: Any = None,
    transcript_scope: Any = "all",
) -> dict[str, Any]:
    s = _service()
    turn_control = s._get_session_turn_control(conversation["id"])
    turn_snapshot = turn_control.snapshot() if turn_control is not None else {
        "stopRequested": False,
        "stopRequestedAt": "",
        "stopReason": "",
    }
    active_task = s._normalize_session_active_task(
        conversation.get("active_task") or conversation.get("activeTask")
    )
    if not s._is_task_tool_backed_active_task(active_task):
        active_task = None
    live_work_run = s._active_chat_turn_work_run_for_session(conversation["id"])
    active_task = s._active_task_with_live_work_run(active_task, live_work_run)
    changed_files = list(active_task.get("changed_files") or []) if active_task else []
    read_files = list(active_task.get("read_files") or []) if active_task else []
    preview_tabs = list(active_task.get("preview_tabs") or []) if active_task else []
    default_file_context = str(active_task.get("default_file_context") or "").strip() if active_task else ""
    active_preview_path = (
        str(active_task.get("active_preview_path") or "").strip() if active_task else ""
    ) or "agent"
    message_window: dict[str, Any] | None = None
    stat_messages: list[dict[str, Any]] | None = None
    if s._session_detail_window_requested(
        message_limit=message_limit,
        before_message_index=before_message_index,
        transcript_scope=transcript_scope,
    ):
        detail_messages, message_window, stat_messages = s._session_detail_messages_with_window(
            conversation["id"],
            message_limit=message_limit,
            before_message_index=before_message_index,
            transcript_scope=transcript_scope,
            fallback_items=conversation.get("messages") or [],
        )
    else:
        detail_messages = s._messages_with_live_output(
            conversation["id"],
            normalized_messages=(
                conversation.get("messages")
                if bool(conversation.get("_messagesNormalized"))
                else None
            ),
        )
    if not detail_messages:
        detail_messages = s._normalize_messages(conversation["id"], conversation.get("messages") or [])
    usage_messages = stat_messages or detail_messages
    context_usage = s._build_session_context_usage(conversation, usage_messages)
    llm_usage = s._session_last_llm_usage(usage_messages)
    stored_last_cache_composition = s._normalize_session_cache_composition(
        conversation.get("lastCacheComposition") or conversation.get("last_cache_composition")
    )
    if (
        llm_usage is None
        and stored_last_cache_composition is not None
        and str(stored_last_cache_composition.get("source") or "").strip() == "not_called"
    ):
        llm_usage = s._normalize_turn_llm_usage(
            {
                "source": "not_called",
                "recordedAt": str(stored_last_cache_composition.get("updatedAt") or "").strip(),
            }
        )
    cache_usage = s._build_session_cache_usage(llm_usage, usage_messages)
    live_context_composition = s._current_session_live_context_composition(conversation["id"])
    last_context_composition = live_context_composition or s._normalize_session_context_composition(
        conversation.get("lastContextComposition") or conversation.get("last_context_composition")
    )
    last_llm_payload_trace = s._current_session_live_llm_payload_trace(conversation["id"]) or s._normalize_session_llm_payload_trace(
        conversation.get("lastLlmPayloadTrace") or conversation.get("last_llm_payload_trace")
    )
    last_cache_composition = (
        s._build_session_cache_composition(
            str(live_context_composition.get("turnId") or "").strip(),
            llm_usage,
            context_composition=last_context_composition,
            average_cache=cache_usage,
        )
        if live_context_composition is not None
        else s._session_last_cache_composition(
            conversation,
            llm_usage=llm_usage,
            context_composition=last_context_composition,
            average_cache=cache_usage,
            normalized_last_cache_composition=stored_last_cache_composition,
        )
    )
    agent_available = s._session_agent_is_available(summary)
    available_agent_id = summary.get("agentId") or "" if agent_available else ""
    available_agent = s._session_detail_agent_snapshot(
        conversation,
        available_agent_id,
        hydrate_agent=hydrate_agent,
    )
    detail = {
        **summary,
        "ledgerSeq": s._session_ledger_sequence(conversation["id"]),
        "activeTask": s._active_task_to_api(active_task),
        "defaultFileContext": default_file_context,
        "previewTabs": preview_tabs,
        "activePreviewPath": active_preview_path,
        "changedFiles": changed_files,
        "readFiles": read_files,
        "messages": detail_messages,
        "runtimeNotices": s._visible_session_runtime_notices(
            s._normalize_session_runtime_notices(
                conversation.get("runtime_notices") or conversation.get("runtimeNotices") or []
            ),
            detail_messages,
        ),
        "contextUsage": context_usage,
        "cacheUsage": cache_usage,
        "llmUsage": llm_usage,
        "lastContextComposition": last_context_composition,
        "lastLlmPayloadTrace": last_llm_payload_trace,
        "agentPromptSnapshot": summary.get("agentPromptSnapshot") if isinstance(summary.get("agentPromptSnapshot"), dict) else {},
        "lastPromptAssembly": summary.get("lastPromptAssembly")
        if isinstance(summary.get("lastPromptAssembly"), dict)
        else {},
        "activeSkillContract": s.normalize_active_skill_contract(
            conversation.get("activeSkillContract") or conversation.get("active_skill_contract")
        ),
        "lastCacheComposition": last_cache_composition,
        "handoffContext": s._normalize_child_handoff_context(conversation.get("handoffContext") or conversation.get("handoff_context")),
        "lastTurnError": s._session_turn_error_to_api(conversation.get("lastTurnError")),
        "nextStateSignals": s._recent_chat_next_state_signal_summaries(conversation["id"], limit=5) if hydrate_agent else [],
        "groupContextEvents": s.list_group_context_events_for_agent(available_agent_id, limit=8)
        if available_agent_id and hydrate_agent
        else [],
        "agentInboxMessages": s.list_agent_inbox_messages_for_agent(available_agent_id, limit=8, status="pending")
        if available_agent_id and hydrate_agent
        else [],
        "pendingToolGovernanceRequests": s._pending_tool_governance_requests_for_session(available_agent_id)
        if available_agent_id and hydrate_agent
        else [],
        "toolPolicy": (available_agent or {}).get("toolPolicy") if available_agent_id else None,
        "memoryPolicy": (available_agent or {}).get("memoryPolicy") if available_agent_id else None,
        "activeTurnId": s._current_session_turn_id(conversation["id"])
        or (
            str(turn_snapshot.get("turnId") or "").strip()
            if not bool(turn_snapshot.get("releasedToUser"))
            else ""
        ),
        "stopRequested": bool(turn_snapshot["stopRequested"]) and not bool(turn_snapshot.get("releasedToUser")),
        "stopRequestedAt": ""
        if bool(turn_snapshot.get("releasedToUser"))
        else str(turn_snapshot["stopRequestedAt"] or "").strip(),
        "stopReason": ""
        if bool(turn_snapshot.get("releasedToUser"))
        else str(turn_snapshot["stopReason"] or "").strip(),
    }
    if message_window is not None:
        detail["messageWindow"] = message_window
    return detail


def _build_session_summary(conversation: dict[str, Any], *, hydrate_agent: bool = True) -> dict[str, Any]:
    s = _service()
    status = s._conversation_phase(conversation["id"], conversation)
    summary_messages = list(conversation.get("messages") or [])
    if bool(conversation.get("_messagesNormalized")) or bool(conversation.get("_messagesPreview")):
        normalized_summary_messages = summary_messages
    elif summary_messages:
        normalized_summary_messages = s._normalize_messages(conversation["id"], summary_messages)
    else:
        normalized_summary_messages = s._normalize_messages(
            conversation["id"],
            s._ledger_visible_messages_for_session(conversation["id"]),
        )
    summary = s._latest_message_summary(normalized_summary_messages)
    updated_at = str(conversation.get("updatedAt") or "").strip()
    agent_id = str(conversation.get("agentId") or "").strip()
    cached_agent = conversation.get("_agent")
    agent = cached_agent if isinstance(cached_agent, dict) else (s.get_agent(agent_id) if agent_id and hydrate_agent else None)
    agent_lookup_checked = bool(conversation.get("_agentLookupChecked"))
    agent_workspace_path = str((agent or {}).get("workspacePath") or "").strip()
    agent_code = str((agent or {}).get("agentCode") or "").strip()
    agent_avatar_image_path = str((agent or {}).get("avatarImagePath") or "").strip()
    agent_avatar_image_url = str((agent or {}).get("avatarImageUrl") or "").strip()
    agent_primary_mode = str((agent or {}).get("primaryMode") or "").strip()
    agent_role_key = str((agent or {}).get("roleKey") or "").strip()
    agent_prompt_template_id = str((agent or {}).get("promptTemplateId") or "").strip()
    dialogue_model_id = s.agent_dialogue_model_id(agent) if agent else ""
    agent_inbox_pending_count = s._agent_inbox_pending_count_for_summary(agent)
    agent_primary_direct_session_id = str((agent or {}).get("directSessionId") or "").strip()
    agent_direct_session_mismatch = bool(
        agent_id
        and agent_primary_direct_session_id
        and agent_primary_direct_session_id != conversation["id"]
    )
    agent_status = s._session_agent_status_payload(
        agent_id,
        agent,
        hydrate_agent=hydrate_agent,
        agent_lookup_checked=agent_lookup_checked,
        persisted_status_code=str(conversation.get("agentStatusCode") or "").strip(),
    )
    if not agent_status["agentMissing"] and bool(conversation.get("agentMissing")) and not isinstance(agent, dict):
        agent_status = {
            "agentMissing": True,
            "agentStatusCode": str(conversation.get("agentStatusCode") or "missing_agent").strip() or "missing_agent",
            "agentStatusMessage": s.text_for(
                s.get_web_language(),
                zh="缺少有效 Agent：当前会话引用的 Agent 已不存在或不可用。",
                en="Missing valid Agent: this session references an Agent that no longer exists or is unavailable.",
            ),
        }
    agent_missing_id = str(conversation.get("agentMissingId") or "").strip()
    agent_direct_session_mismatch = bool(conversation.get("agentDirectSessionMismatch"))
    agent_primary_direct_session_id = str(conversation.get("agentPrimaryDirectSessionId") or "").strip()
    agent_display_name = str((agent or {}).get("displayName") or "").strip()
    if agent_status["agentMissing"] and not agent_display_name:
        agent_display_name = s.text_for(s.get_web_language(), zh="缺少有效 Agent", en="Missing Agent")
    raw_title = str(conversation["title"]).strip()
    session_kind = str(conversation.get("sessionKind") or "main").strip() or "main"
    task_title = str(conversation.get("taskTitle") or raw_title).strip() or raw_title
    display_agent_name = agent_display_name or raw_title
    if session_kind == "child":
        display_title = task_title
    elif not s._is_default_empty_session_title(task_title):
        display_title = task_title
    elif agent_id:
        display_title = display_agent_name
    else:
        display_title = task_title
    session_id = str(conversation["id"]).strip()
    session_source_ref = s._source_authority_ref("session", session_id)
    session_projection_edit = s._projection_edit_contract("session", session_id)
    agent_source_ref = s._source_authority_ref("agent", agent_id) if agent_id else None
    return {
        "id": session_id,
        "title": display_title,
        "agentId": agent_id,
        "agentCode": agent_code,
        "agentDisplayName": display_agent_name,
        "agentAvatarImagePath": agent_avatar_image_path,
        "agentAvatarImageUrl": agent_avatar_image_url,
        "agentPrimaryMode": agent_primary_mode,
        "agentRoleKey": agent_role_key,
        "agentPromptTemplateId": agent_prompt_template_id,
        "agentPromptSnapshot": s._public_agent_prompt_snapshot(conversation.get("agentPromptSnapshot")),
        "lastPromptAssembly": s._public_prompt_assembly_manifest(
            conversation.get("last_prompt_assembly") or conversation.get("lastPromptAssembly")
        ),
        "experimentBinding": _public_experiment_binding(
            conversation.get("experimentBinding") or conversation.get("experiment_binding")
        ),
        "agentInboxPendingCount": agent_inbox_pending_count,
        "agentMissingId": agent_missing_id,
        "agentDirectSessionMismatch": agent_direct_session_mismatch,
        "agentPrimaryDirectSessionId": agent_primary_direct_session_id,
        "sessionRole": str(conversation.get("session_role") or conversation.get("sessionRole") or "").strip(),
        "dialogueModelId": dialogue_model_id,
        "reasoningEffort": s.normalize_reasoning_effort(conversation.get("reasoningEffort")),
        "workspacePath": str(conversation.get("workspacePath") or s._session_workspace_relative_path(conversation["id"])),
        "agentWorkspacePath": agent_workspace_path,
        **agent_status,
        "status": status,
        "taskSummary": summary,
        "lastActive": updated_at,
        "updatedAt": updated_at,
        "currentPhase": status,
        "sessionKind": session_kind,
        "hiddenFromIndex": bool(conversation.get("hiddenFromIndex") or conversation.get("hidden_from_index")),
        "readOnly": bool(conversation.get("readOnly") or conversation.get("read_only")),
        "archiveState": dict(conversation.get("archiveState") or {})
        if isinstance(conversation.get("archiveState"), dict)
        else {},
        "conversationIndexVisibility": str(conversation.get("conversationIndexVisibility") or "").strip(),
        "conversationIndexKind": str(conversation.get("conversationIndexKind") or "").strip(),
        "conversationIndexErrors": list(conversation.get("conversationIndexErrors") or []),
        "teamId": str(conversation.get("teamId") or "").strip(),
        "teamName": str(conversation.get("teamName") or "").strip(),
        "parentSessionId": str(conversation.get("parentSessionId") or "").strip(),
        "rootSessionId": str(conversation.get("rootSessionId") or conversation["id"]).strip() or conversation["id"],
        "childSessionIds": list(conversation.get("childSessionIds") or []),
        "activeChildSessionId": str(conversation.get("activeChildSessionId") or "").strip(),
        "childStatus": str(conversation.get("childStatus") or status).strip() or status,
        "taskTitle": task_title,
        "resultCard": s._normalize_child_result_card(conversation.get("resultCard")),
        "sourceRef": session_source_ref,
        "projectionEdit": session_projection_edit,
        "agentSourceRef": agent_source_ref,
    }


def _public_experiment_binding(value: Any) -> dict[str, Any] | None:
    """Project only the allowlisted experiment identity; never expose storage data."""
    if not isinstance(value, dict):
        return None
    research_project_id = str(value.get("researchProjectId") or "").strip()[:160]
    agent_id = str(value.get("agentId") or "").strip()[:160]
    if not research_project_id or not agent_id:
        return None
    try:
        attempt = max(1, int(value.get("attempt") or 1))
    except (TypeError, ValueError):
        attempt = 1
    return {
        "teamId": str(value.get("teamId") or "").strip()[:160],
        "researchProjectId": research_project_id,
        "experimentName": str(value.get("experimentName") or "").strip()[:160],
        "agentId": agent_id,
        "roleKey": str(value.get("roleKey") or "").strip()[:80],
        "roleLabel": str(value.get("roleLabel") or "").strip()[:80],
        "attempt": attempt,
        "retryOfSessionId": str(value.get("retryOfSessionId") or "").strip()[:160],
        "createdFromTaskId": str(value.get("createdFromTaskId") or "").strip()[:160],
        "createdAt": str(value.get("createdAt") or "").strip()[:120],
    }


def _normalize_conversation(
    raw: Any,
    *,
    agent_by_id: dict[str, dict[str, Any]] | None = None,
    hidden_team_member_agent_ids: set[str] | None = None,
    ensure_workspace: bool = True,
    lightweight: bool = False,
) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(raw, dict):
        return None
    conversation_id = str(raw.get("conversation_id") or s.DEFAULT_CHAT_CONVERSATION_ID).strip()
    if not conversation_id:
        return None
    workspace_path = s._session_workspace_relative_path(conversation_id)
    if ensure_workspace:
        s._ensure_session_workspace(conversation_id)
    title = str(raw.get("title") or s.DEFAULT_CHAT_CONVERSATION_TITLE).strip() or s.DEFAULT_CHAT_CONVERSATION_TITLE
    agent_id = str(raw.get("agent_id") or raw.get("agentId") or "").strip()
    agent = s._agent_from_lookup(agent_by_id, agent_id) if agent_id else None
    agent_lookup_checked = agent_by_id is not None
    missing_agent_id = str(raw.get("agent_missing_id") or raw.get("agentMissingId") or "").strip()
    agent_missing = bool(raw.get("agentMissing"))
    agent_status_code = str(raw.get("agentStatusCode") or "").strip()
    agent_direct_session_mismatch = bool(raw.get("agentDirectSessionMismatch"))
    agent_primary_direct_session_id = str(raw.get("agentPrimaryDirectSessionId") or "").strip()
    if agent_status_code != "deleted_agent" and agent is None:
        recovered_agent = s._recover_active_direct_session_agent(
            conversation_id,
            agent_by_id=agent_by_id,
            preferred_agent_id=agent_id or missing_agent_id,
        )
        if recovered_agent is not None:
            agent = recovered_agent
            agent_id = str(recovered_agent.get("agentId") or "").strip()
            missing_agent_id = ""
            agent_missing = False
            agent_status_code = ""
            agent_direct_session_mismatch = False
            agent_primary_direct_session_id = ""
    session_kind = s._normalize_session_kind(raw.get("session_kind") or raw.get("sessionKind"))
    parent_session_id = str(raw.get("parent_session_id") or raw.get("parentSessionId") or "").strip()
    if session_kind == "main":
        parent_session_id = ""
    root_session_id = str(raw.get("root_session_id") or raw.get("rootSessionId") or "").strip()
    if not root_session_id:
        root_session_id = parent_session_id if session_kind == "child" and parent_session_id else conversation_id
    child_session_ids = s._normalize_string_list(raw.get("child_session_ids") or raw.get("childSessionIds"))
    if agent:
        agent_direct_session_id = str(agent.get("directSessionId") or "").strip()
        if s._conversation_agent_direct_session_is_allowed(
            conversation={
                **raw,
                "session_kind": session_kind,
                "parent_session_id": parent_session_id,
                "root_session_id": root_session_id,
                "child_session_ids": child_session_ids,
            },
            conversation_id=conversation_id,
            direct_session_id=agent_direct_session_id,
        ):
            agent_direct_session_mismatch = False
            agent_primary_direct_session_id = ""
        elif agent_direct_session_id:
            agent_direct_session_mismatch = True
            agent_primary_direct_session_id = agent_direct_session_id
    elif agent_id and agent_lookup_checked and agent is None:
        missing_agent_id = agent_id
        agent_missing = True
        agent_status_code = "missing_agent"
    elif missing_agent_id and agent_lookup_checked and agent is None:
        agent_missing = True
        agent_status_code = agent_status_code or "missing_agent"
    if lightweight:
        messages, has_ledger_messages = s._ledger_latest_preview_messages_for_session(
            conversation_id
        )
        if not has_ledger_messages:
            messages = s._normalize_latest_preview_messages(
                conversation_id,
                raw.get("messages") or [],
            )
        messages = list(messages)
        visible_runtime_notices: list[dict[str, Any]] = []
    else:
        ledger_messages = s._session_ledger_visible_messages(conversation_id)
        if ledger_messages:
            messages = ledger_messages
        else:
            messages = s._normalize_messages(conversation_id, raw.get("messages") or [])
        has_ledger_messages = bool(ledger_messages)
        runtime_notices = s._normalize_session_runtime_notices(
            raw.get("runtime_notices") or raw.get("runtimeNotices") or []
        )
        visible_runtime_notices = s._visible_session_runtime_notices(
            runtime_notices,
            messages,
        )
    last_turn_status = str(raw.get("last_turn_status") or "").strip().lower()
    last_turn_error = s._normalize_session_turn_error(raw.get("last_turn_error") or raw.get("lastTurnError"))
    last_context_composition = s._normalize_session_context_composition(
        raw.get("last_context_composition") or raw.get("lastContextComposition")
    )
    active_skill_contract = s.normalize_active_skill_contract(
        raw.get("active_skill_contract") or raw.get("activeSkillContract")
    )
    last_cache_composition = s._normalize_session_cache_composition(
        raw.get("last_cache_composition") or raw.get("lastCacheComposition")
    )
    active_child_session_id = str(raw.get("active_child_session_id") or raw.get("activeChildSessionId") or "").strip()
    task_title = s.trim_lines(raw.get("task_title") or raw.get("taskTitle") or title, max_lines=1).strip() or title
    handoff_context = s._normalize_child_handoff_context(raw.get("handoff_context") or raw.get("handoffContext"))
    result_card = s._normalize_child_result_card(raw.get("result_card") or raw.get("resultCard"))
    child_status = str(raw.get("child_status") or raw.get("childStatus") or "").strip().lower()
    if session_kind == "child" and last_turn_status:
        child_status = last_turn_status
    updated_at = (
        str(raw.get("updated_at") or "").strip()
        or s._latest_message_timestamp(messages)
    )
    active_task = raw.get("active_task")
    if not isinstance(active_task, dict):
        active_task = raw.get("activeTask")
    if not isinstance(active_task, dict):
        active_task = None
    agent_prompt_snapshot = s._public_agent_prompt_snapshot(raw.get("agentPromptSnapshot"))
    last_prompt_assembly = s._public_prompt_assembly_manifest(
        raw.get("last_prompt_assembly") or raw.get("lastPromptAssembly")
    )
    experiment_binding = _public_experiment_binding(
        raw.get("experiment_binding") or raw.get("experimentBinding")
    )
    conversation_index_classification = s._conversation_index_classification(
        raw,
        agent,
        hidden_team_member_agent_ids=hidden_team_member_agent_ids,
    )
    conversation_index_kind = str(conversation_index_classification.get("kind") or "").strip()
    conversation_index_visibility = s._conversation_index_visibility_for_classification(
        conversation_index_kind,
        agent,
        hidden_team_member_agent_ids=hidden_team_member_agent_ids,
    )
    archive_state = raw.get("archive_state") or raw.get("archiveState")
    if not isinstance(archive_state, dict):
        archive_state = {}
    return {
        "id": conversation_id,
        "title": title,
        "agentId": agent_id,
        "agentMissingId": missing_agent_id,
        "agentMissing": agent_missing,
        "agentStatusCode": agent_status_code,
        "agentDirectSessionMismatch": agent_direct_session_mismatch,
        "agentPrimaryDirectSessionId": agent_primary_direct_session_id,
        "workspacePath": workspace_path,
        "messages": messages,
        "_messagesNormalized": not lightweight,
        "_messagesPreview": bool(lightweight),
        "_hasLedgerMessages": has_ledger_messages,
        "runtimeNotices": visible_runtime_notices,
        "lastTurnStatus": last_turn_status,
        "lastTurnError": last_turn_error,
        "lastContextComposition": last_context_composition,
        "agentPromptSnapshot": agent_prompt_snapshot,
        "lastPromptAssembly": last_prompt_assembly,
        "experimentBinding": experiment_binding,
        "reasoningEffort": s.normalize_reasoning_effort(raw.get("reasoning_effort") or raw.get("reasoningEffort")),
        "activeSkillContract": active_skill_contract,
        "lastCacheComposition": last_cache_composition,
        "sessionKind": session_kind,
        "hiddenFromIndex": s._conversation_hidden_from_index(
            raw,
            agent,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
        ),
        "readOnly": bool(raw.get("read_only") or raw.get("readOnly") or archive_state),
        "archiveState": dict(archive_state),
        "conversationIndexVisibility": conversation_index_visibility,
        "conversationIndexKind": conversation_index_kind,
        "conversationIndexErrors": list(conversation_index_classification.get("errors") or []),
        "teamId": str(agent.get("teamId") or "").strip() if isinstance(agent, dict) else "",
        "teamName": str(agent.get("teamName") or "").strip() if isinstance(agent, dict) else "",
        "parentSessionId": parent_session_id,
        "rootSessionId": root_session_id,
        "childSessionIds": child_session_ids,
        "activeChildSessionId": active_child_session_id,
        "taskTitle": task_title,
        "handoffContext": handoff_context,
        "resultCard": result_card,
        "childStatus": child_status,
        "updatedAt": updated_at,
        "activeTask": dict(active_task or {}) if isinstance(active_task, dict) else None,
        "_agent": dict(agent) if isinstance(agent, dict) else None,
        "_agentLookupChecked": bool(agent_lookup_checked),
    }


def _normalize_messages(
    conversation_id: str,
    items: Any,
    *,
    source_start_index: int = 1,
    transcript_scope: Any = "all",
    include_timeline: bool = True,
) -> list[dict[str, Any]]:
    s = _service()
    ledger_events_by_turn: dict[str, list[dict[str, Any]]] | None = None
    raw_items = list(items or [])
    timeline_lang = s.get_web_language() if include_timeline else ""
    normalized_start_index = max(1, int(source_start_index or 1))
    normalized_transcript_scope = s._normalize_session_detail_transcript_scope(transcript_scope)
    timeline_target_indices = (
        s._assistant_timeline_target_indices(raw_items, source_start_index=normalized_start_index)
        if include_timeline
        else {}
    )
    messages: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_items, start=normalized_start_index):
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        raw_metadata = raw.get("metadata")
        if (
            role == "assistant"
            and isinstance(raw_metadata, dict)
            and str(raw_metadata.get("kind") or "").strip() == "checkpoint"
        ):
            continue
        content = s._sanitize_message_content(role, raw.get("content") or "")
        thought = s._normalize_message_thought(raw, role=role)
        mental_snapshot = s._normalize_mental_snapshot(raw.get("mental_snapshot") or raw.get("mentalSnapshot"))
        tool_calls = s._normalize_message_tool_calls(raw.get("tool_calls") or raw.get("toolCalls") or raw.get("tools") or [])
        feedback_events = s._normalize_message_feedback_events(raw.get("feedback_events") or raw.get("feedbackEvents") or [])
        attachments = s._normalize_message_attachments(raw.get("attachments") or raw.get("imageAttachments") or [])
        references = s._normalize_session_references(raw.get("references") or (raw.get("metadata") or {}).get("sessionReferences") or [])
        if not content and not thought and mental_snapshot is None and not tool_calls and not feedback_events and not attachments and not references:
            continue
        entry: dict[str, Any] = {
            "id": f"{conversation_id}-message-{index}",
            "role": role,
            "content": content,
            "timestamp": str(raw.get("timestamp") or "").strip(),
        }
        if thought:
            entry["thought"] = thought
        if mental_snapshot is not None:
            entry["mentalSnapshot"] = mental_snapshot
        if tool_calls:
            entry["toolCalls"] = tool_calls
        if feedback_events:
            entry["feedbackEvents"] = feedback_events
        turn_id = s._message_turn_id(raw)
        timeline_feedback_events = feedback_events
        include_assistant_text = True
        if include_timeline and role == "assistant" and turn_id:
            if ledger_events_by_turn is None:
                ledger_events_by_turn = s._assistant_timeline_events_by_turn(conversation_id)
            ordered_timeline_events = ledger_events_by_turn.get(turn_id) or []
            if ordered_timeline_events and timeline_target_indices.get(turn_id) == index:
                timeline_feedback_events = s._filter_redundant_assistant_timeline_events(
                    ordered_timeline_events,
                    content,
                )
                include_assistant_text = False
            elif ordered_timeline_events:
                timeline_feedback_events = []
                include_assistant_text = False
        if include_timeline:
            timeline_items = s._build_message_timeline_items(
                message_id=entry["id"],
                content=content,
                feedback_events=timeline_feedback_events,
                streaming=bool(raw.get("streaming")),
                include_assistant_text=include_assistant_text,
                lang=timeline_lang,
            )
            if timeline_items:
                entry["timelineItems"] = timeline_items
        if normalized_transcript_scope != "none":
            codex_transcript = s._build_codex_transcript_projection(
                message_id=entry["id"],
                role=role,
                content=content,
                feedback_events=timeline_feedback_events,
                tool_calls=tool_calls,
                streaming=bool(raw.get("streaming")),
            )
            turn_items: list[dict[str, Any]] = []
            is_terminal_error_message = (
                role == "assistant"
                and isinstance(raw_metadata, dict)
                and (
                    str(raw_metadata.get("kind") or "").strip() == "turn_error"
                    or raw_metadata.get("providerFailure") is True
                )
            )
            if is_terminal_error_message:
                turn_items = s._build_session_turn_items_projection(
                    session_id=conversation_id,
                    turn_id=turn_id,
                    message_id=entry["id"],
                    content=content,
                    thought=thought,
                    codex_transcript=codex_transcript,
                    done=True,
                    source="session_detail",
                    metadata=raw_metadata,
                )
                if turn_items:
                    entry["turnItems"] = turn_items
                terminal_error_item = s._terminal_error_turn_item(turn_items)
                if terminal_error_item:
                    codex_transcript = s._build_terminal_error_codex_transcript_projection(
                        message_id=entry["id"],
                        error_item=terminal_error_item,
                    )
            if codex_transcript:
                entry["codexTranscript"] = codex_transcript
        if attachments:
            entry["attachments"] = attachments
        if references:
            entry["references"] = references
        metadata = raw_metadata
        if isinstance(metadata, dict) and metadata:
            entry["metadata"] = dict(metadata)
            if role == "assistant" and str(metadata.get("kind") or "").strip() == "turn_error":
                entry["content"] = s._complete_turn_error_visible_content(entry["content"], metadata)
        messages.append(entry)
    return s._dedupe_turn_error_messages(messages)


def _build_session_active_task(
    session_id: str,
    result: Any,
    messages: list[dict[str, Any]],
    *,
    existing_task: dict[str, Any] | None = None,
    user_message_source: str = "",
) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(result, dict):
        return existing_task if s._is_task_tool_backed_active_task(existing_task) else None

    task_tool_called = s._result_has_task_context_tool(result)
    existing_task_tool_backed = s._is_task_tool_backed_active_task(existing_task)
    if not task_tool_called and not existing_task_tool_backed:
        return None

    contract = s.build_chat_coding_result_contract(result)
    read_files = s._normalize_project_paths(contract.get("read_files") or [], existing_only=True)
    changed_files = s._normalize_project_paths(contract.get("changed_files") or [], existing_only=False)
    if isinstance(existing_task, dict):
        if not read_files:
            read_files = s._normalize_project_paths(existing_task.get("read_files") or [], existing_only=True)
        if not changed_files:
            changed_files = s._normalize_project_paths(existing_task.get("changed_files") or [], existing_only=False)
    verification_status = str(contract.get("verification_status") or "").strip().lower()
    verification_summary = s.trim_lines(contract.get("verification_summary") or "", max_lines=4)
    blocked_reason = s.trim_lines(contract.get("blocked_reason") or "", max_lines=3)
    required_user_input = s.trim_lines(contract.get("required_user_input") or "", max_lines=3)
    next_action = s.trim_lines(contract.get("next_action") or "", max_lines=3)
    latest_summary = s.trim_lines(
        s._visible_reply_summary_candidate(result),
        max_lines=6,
    )

    if not any(
        (
            read_files,
            changed_files,
            verification_status,
            verification_summary,
            blocked_reason,
            required_user_input,
            next_action,
            latest_summary,
        )
    ):
        return existing_task

    preview_tabs = s._merge_project_paths(
        s._normalize_project_paths(changed_files, existing_only=True),
        read_files,
    )
    default_file_context = (
        changed_files[-1] if changed_files else ""
    ) or (read_files[-1] if read_files else "")
    active_preview_path = (
        s._normalize_project_path(default_file_context, existing_only=True)
        or (preview_tabs[0] if preview_tabs else "")
        or "agent"
    )
    if active_preview_path != "agent" and active_preview_path not in preview_tabs:
        preview_tabs = [active_preview_path, *preview_tabs]

    outcome = str(contract.get("outcome") or "").strip().lower()
    task_status = s._task_status_from_result_contract(
        outcome,
        read_files=read_files,
        changed_files=changed_files,
        verification_status=verification_status,
    )
    raw_last_user_message = s._latest_user_message(messages)
    last_user_message = s._latest_real_user_message(messages) or raw_last_user_message
    existing_metadata = dict(existing_task.get("metadata") or {}) if isinstance(existing_task, dict) else {}
    existing_created_at = str(existing_task.get("created_at") or "").strip() if isinstance(existing_task, dict) else ""
    existing_turn_count = (
        s._coerce_nonnegative_int(existing_task.get("turn_count") or 0) if isinstance(existing_task, dict) else 0
    )
    existing_goal = (
        s.trim_lines(existing_task.get("goal") or existing_task.get("title") or "", max_lines=2)
        if isinstance(existing_task, dict)
        else ""
    )
    history_goal = s._latest_effective_user_message(messages)
    last_is_contextual_confirmation = s._is_contextual_confirmation_message(last_user_message)
    if s._is_continue_request(last_user_message) or last_is_contextual_confirmation:
        effective_goal = existing_goal if existing_goal and s._is_effective_user_message(existing_goal) else history_goal
        history_goal_index = s._latest_effective_user_message_with_index(messages)[1]
        if s._should_prefer_history_goal_over_active_task(
            existing_task,
            messages,
            existing_goal=existing_goal,
            history_goal=history_goal,
            history_goal_index=history_goal_index,
        ):
            effective_goal = history_goal
    else:
        effective_goal = last_user_message if s._is_effective_user_message(last_user_message) else history_goal
    if not effective_goal:
        effective_goal = existing_goal if existing_goal and s._is_effective_user_message(existing_goal) else history_goal
    effective_title = (
        effective_goal
        if (s._is_continue_request(last_user_message) or last_is_contextual_confirmation) and effective_goal
        else (last_user_message if s._is_effective_user_message(last_user_message) else (effective_goal or latest_summary))
    )
    metadata = dict(existing_metadata)
    metadata.update(
        {
            "source": "task_tool",
            "outcome": outcome,
            "default_file_context": default_file_context,
            "active_preview_path": active_preview_path,
        }
    )
    if blocked_reason:
        metadata["blocked_reason"] = blocked_reason
    if required_user_input:
        metadata["required_user_input"] = required_user_input
    if str(user_message_source or "").strip() == "agent_inbox":
        metadata["last_user_message_filtered"] = True
        metadata["last_user_message_reason"] = "agent_inbox_message"
    elif raw_last_user_message and raw_last_user_message != last_user_message:
        metadata["last_user_message_filtered"] = True
        metadata["last_user_message_reason"] = "agent_inbox_message"

    return {
        "task_id": str(existing_task.get("task_id") or f"{session_id}-coding-task").strip()
        if isinstance(existing_task, dict)
        else f"{session_id}-coding-task",
        "kind": "coding",
        "status": task_status,
        "title": s.trim_lines(effective_title, max_lines=2),
        "goal": s.trim_lines(effective_goal, max_lines=2),
        "read_files": read_files,
        "changed_files": changed_files,
        "verification_status": verification_status,
        "verification_summary": verification_summary,
        "latest_summary": latest_summary,
        "next_action": next_action or required_user_input or blocked_reason,
        "last_user_message": last_user_message,
        "turn_count": max(0, existing_turn_count) + 1,
        "resume_count": (
            s._coerce_nonnegative_int(existing_task.get("resume_count") or 0)
            if isinstance(existing_task, dict)
            else 0
        ),
        "created_at": existing_created_at or s._now_timestamp(),
        "updated_at": s._now_timestamp(),
        "default_file_context": default_file_context,
        "preview_tabs": preview_tabs,
        "active_preview_path": active_preview_path,
        "metadata": metadata,
    }


def _normalize_session_active_task(value: Any) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(value, dict):
        return None

    read_files = s._normalize_project_paths(
        value.get("read_files") or value.get("readFiles") or [],
        existing_only=True,
    )
    changed_files = s._normalize_project_paths(
        value.get("changed_files") or value.get("changedFiles") or [],
        existing_only=False,
    )
    preview_tabs = s._merge_project_paths(
        s._normalize_project_paths(
            value.get("preview_tabs") or value.get("previewTabs") or [],
            existing_only=True,
        ),
        s._normalize_project_paths(changed_files, existing_only=True),
        read_files,
    )
    default_file_context = (
        s._normalize_project_path(
            value.get("default_file_context") or value.get("defaultFileContext"),
            existing_only=False,
        )
        or (changed_files[-1] if changed_files else "")
        or (read_files[-1] if read_files else "")
    )
    active_preview_path = (
        s._normalize_project_path(
            value.get("active_preview_path") or value.get("activePreviewPath"),
            existing_only=True,
        )
        or s._normalize_project_path(default_file_context, existing_only=True)
        or (preview_tabs[0] if preview_tabs else "")
    )
    if active_preview_path and active_preview_path not in preview_tabs:
        preview_tabs = [active_preview_path, *preview_tabs]
    if not active_preview_path:
        active_preview_path = "agent"

    normalized = {
        "task_id": str(value.get("task_id") or value.get("taskId") or "").strip(),
        "kind": str(value.get("kind") or "coding").strip().lower() or "coding",
        "status": str(value.get("status") or "idle").strip().lower() or "idle",
        "title": s.trim_lines(s._sanitize_message_content("assistant", value.get("title") or ""), max_lines=2),
        "goal": s.trim_lines(s._sanitize_message_content("assistant", value.get("goal") or ""), max_lines=2),
        "read_files": read_files,
        "changed_files": changed_files,
        "verification_status": str(value.get("verification_status") or value.get("verificationStatus") or "").strip().lower(),
        "verification_summary": s.trim_lines(
            s._sanitize_message_content(
                "assistant",
                value.get("verification_summary") or value.get("verificationSummary") or "",
            ),
            max_lines=4,
        ),
        "latest_summary": s.trim_lines(
            s._sanitize_message_content(
                "assistant",
                value.get("latest_summary") or value.get("latestSummary") or "",
            ),
            max_lines=6,
        ),
        "next_action": s.trim_lines(
            s._sanitize_message_content(
                "assistant",
                value.get("next_action") or value.get("nextAction") or "",
            ),
            max_lines=3,
        ),
        "last_user_message": s.trim_lines(
            value.get("last_user_message") or value.get("lastUserMessage") or "",
            max_lines=3,
        ),
        "turn_count": s._coerce_nonnegative_int(value.get("turn_count") or value.get("turnCount") or 0),
        "resume_count": s._coerce_nonnegative_int(value.get("resume_count") or value.get("resumeCount") or 0),
        "created_at": str(value.get("created_at") or value.get("createdAt") or "").strip(),
        "updated_at": str(value.get("updated_at") or value.get("updatedAt") or "").strip(),
        "default_file_context": default_file_context,
        "preview_tabs": preview_tabs,
        "active_preview_path": active_preview_path,
        "metadata": dict(value.get("metadata") or {}) if isinstance(value.get("metadata"), dict) else {},
    }
    if not any(
        (
            normalized["read_files"],
            normalized["changed_files"],
            normalized["verification_status"],
            normalized["verification_summary"],
            normalized["next_action"],
            normalized["latest_summary"],
        )
    ):
        return None
    return normalized


def _session_detail_messages_with_window(
    session_id: str,
    *,
    message_limit: Any = None,
    before_message_index: Any = None,
    transcript_scope: Any = "all",
    fallback_items: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    s = _service()
    raw_messages = s._ledger_visible_messages_for_session(session_id)
    if not raw_messages:
        raw_messages = list(fallback_items or [])
    raw_message_count = len(raw_messages)
    normalized_limit = s._coerce_session_detail_message_limit(message_limit)
    normalized_before_index = s._coerce_session_detail_before_index(before_message_index)
    normalized_transcript_scope = s._normalize_session_detail_transcript_scope(transcript_scope)
    include_live_message = normalized_before_index <= 0 or normalized_before_index > raw_message_count + 1
    live_message = s._build_live_output_message(session_id) if include_live_message else None
    if live_message is not None and normalized_transcript_scope == "none":
        live_message = dict(live_message)
        live_message.pop("codexTranscript", None)
        live_message.pop("timelineItems", None)

    total_messages = raw_message_count + (1 if live_message is not None else 0)
    if total_messages <= 0:
        message_window = {
            "mode": "window",
            "totalMessages": 0,
            "returnedMessages": 0,
            "oldestMessageIndex": 0,
            "newestMessageIndex": 0,
            "hasEarlier": False,
            "hasLater": False,
            "nextBeforeMessageIndex": None,
            "transcriptScope": normalized_transcript_scope,
        }
        return [], message_window, []

    end_index = total_messages
    if 0 < normalized_before_index <= total_messages:
        end_index = max(0, normalized_before_index - 1)
    if normalized_limit is None:
        start_index = 1 if end_index > 0 else 0
    else:
        start_index = max(1, end_index - normalized_limit + 1) if end_index > 0 else 0

    raw_start = max(0, start_index - 1)
    raw_end = min(raw_message_count, end_index)
    raw_window = raw_messages[raw_start:raw_end]
    detail_messages = s._normalize_messages(
        session_id,
        raw_window,
        source_start_index=raw_start + 1,
        transcript_scope=normalized_transcript_scope,
    )
    if live_message is not None and start_index <= total_messages <= end_index:
        detail_messages = s._without_live_turn_ledger_partials(detail_messages, live_message) + [live_message]

    stat_messages = s._normalize_messages(
        session_id,
        raw_messages,
        transcript_scope="none",
        include_timeline=False,
    )
    if live_message is not None:
        stat_messages = s._without_live_turn_ledger_partials(stat_messages, live_message) + [live_message]

    returned_messages = len(detail_messages)
    message_window = {
        "mode": "window",
        "totalMessages": total_messages,
        "returnedMessages": returned_messages,
        "oldestMessageIndex": start_index if returned_messages else 0,
        "newestMessageIndex": end_index if returned_messages else 0,
        "hasEarlier": start_index > 1,
        "hasLater": end_index < total_messages,
        "nextBeforeMessageIndex": start_index if start_index > 1 else None,
        "transcriptScope": normalized_transcript_scope,
    }
    return detail_messages, message_window, stat_messages


def _session_detail_window_requested(
    *,
    message_limit: Any = None,
    before_message_index: Any = None,
    transcript_scope: Any = "all",
) -> bool:
    s = _service()
    return (
        s._coerce_session_detail_message_limit(message_limit) is not None
        or s._coerce_session_detail_before_index(before_message_index) > 0
        or s._normalize_session_detail_transcript_scope(transcript_scope) != "all"
    )


def _build_session_turn_items_projection(
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    content: Any = "",
    thought: Any = "",
    codex_transcript: dict[str, Any] | None = None,
    done: bool = False,
    source: str = "assistant_delta",
    metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    s = _service()
    canonical_items = s.conversation_turn_items_from_events(
        s._load_session_conversation_events_cached(str(session_id or "").strip()),
        turn_id=str(turn_id or "").strip(),
    )
    if canonical_items:
        return canonical_items
    normalized_metadata = dict(metadata or {})
    normalized_turn_id = str(
        turn_id
        or normalized_metadata.get("turnId")
        or normalized_metadata.get("turn_id")
        or ""
    ).strip()
    if (
        str(normalized_metadata.get("kind") or "").strip() == "turn_error"
        or normalized_metadata.get("providerFailure") is True
    ):
        return [
            s._build_terminal_error_turn_item(
                session_id=session_id,
                turn_id=normalized_turn_id,
                message_id=message_id,
                content=content,
                metadata=normalized_metadata,
            )
        ]
    normalized_message_id = str(message_id or "").strip()
    if not normalized_message_id:
        return []
    transcript_cells = list((codex_transcript or {}).get("cells") or [])
    content_text = s._sanitize_message_content("assistant", content)
    assistant_markdown_text = s._session_turn_assistant_markdown_text(transcript_cells)
    thought_text = s._sanitize_message_content("assistant", thought)
    items: list[dict[str, Any]] = []
    agent_text = content_text or assistant_markdown_text
    if agent_text:
        items.append(
            s._compact_codex_record(
                {
                    "id": s._session_turn_agent_message_item_id(session_id, normalized_turn_id),
                    "type": "agent_message",
                    "status": "completed" if done else "in_progress",
                    "turnId": normalized_turn_id,
                    "messageId": normalized_message_id,
                    "source": source,
                    "text": agent_text,
                }
            )
        )
    if thought_text:
        items.append(
            s._compact_codex_record(
                {
                    "id": f"{s._session_turn_item_base_id(session_id, normalized_turn_id)}-reasoning",
                    "type": "reasoning",
                    "status": "completed" if done else "in_progress",
                    "turnId": normalized_turn_id,
                    "messageId": normalized_message_id,
                    "source": source,
                    "text": thought_text,
                }
            )
        )
    for index, cell in enumerate(transcript_cells, start=1):
        if not isinstance(cell, dict):
            continue
        item = s._session_turn_item_from_codex_cell(
            session_id=session_id,
            turn_id=normalized_turn_id,
            message_id=normalized_message_id,
            cell=cell,
            index=index,
            source=source,
        )
        if item:
            items.append(item)
    return items


def _build_codex_transcript_projection(
    *,
    message_id: str,
    role: str = "assistant",
    content: Any = "",
    feedback_events: Any = None,
    tool_calls: Any = None,
    streaming: bool = False,
) -> dict[str, Any] | None:
    s = _service()
    normalized_message_id = str(message_id or "").strip()
    if not normalized_message_id:
        return None
    normalized_role = str(role or "assistant").strip().lower()
    if normalized_role != "assistant":
        return None
    normalized_feedback_events = s._normalize_message_feedback_events(feedback_events or [])
    normalized_tool_calls = s._normalize_message_tool_calls(tool_calls or [])
    content_text = s._sanitize_message_content("assistant", content)
    operation_sources = s._codex_transcript_operation_sources(
        normalized_message_id,
        normalized_feedback_events,
        normalized_tool_calls,
    )
    cells: list[dict[str, Any]] = []
    lifecycle = s._empty_codex_tool_lifecycle_projection()
    rollout_events: list[dict[str, Any]] = []

    for ordinal, source in enumerate(operation_sources):
        cell, source_lifecycle, source_events = s._codex_transcript_cell_from_operation_source(
            normalized_message_id,
            source,
            ordinal,
        )
        if cell:
            cells.append(cell)
        s._extend_codex_tool_lifecycle_projection(lifecycle, source_lifecycle)
        rollout_events.extend(source_events)

    if content_text:
        cells.append(
            s._compact_codex_record(
                {
                    "id": f"{normalized_message_id}-assistant-markdown",
                    "kind": "assistant_markdown",
                    "messageId": normalized_message_id,
                    "status": "running" if streaming else "completed",
                    "tone": "running" if streaming else "neutral",
                    "text": content_text,
                }
            )
        )
    if streaming and not content_text and any(
        cell.get("status") in {"pending", "running"} for cell in cells
    ):
        cells.append(
            {
                "id": f"{normalized_message_id}-stream-tail",
                "kind": "stream_tail",
                "messageId": normalized_message_id,
                "status": "running",
                "tone": "running",
            }
        )

    if not cells and not rollout_events and not any(lifecycle.values()):
        return None
    return s._compact_codex_record(
        {
            "version": 1,
            "source": "native",
            "messageId": normalized_message_id,
            "streaming": bool(streaming),
            "cells": cells,
            "toolCalls": lifecycle["toolCalls"],
            "terminalOperations": lifecycle["terminalOperations"],
            "terminalSessions": lifecycle["terminalSessions"],
            "modelObservations": lifecycle["modelObservations"],
            "rolloutEvents": rollout_events,
        }
    )


def _build_terminal_error_codex_transcript_projection(
    *,
    message_id: str,
    error_item: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_message_id = str(message_id or error_item.get("messageId") or "").strip()
    item_id = str(error_item.get("itemId") or error_item.get("id") or "terminal-error").strip()
    diagnostic_summary = error_item.get("diagnosticSummary")
    return {
        "version": 1,
        "source": "native",
        "messageId": normalized_message_id,
        "streaming": False,
        "cells": [
            {
                "id": item_id,
                "kind": "error_notice",
                "messageId": normalized_message_id,
                "status": "failed",
                "tone": "error",
                "text": str(error_item.get("text") or "").strip(),
                "phase": "turn_failed",
                "terminal": True,
                "diagnosticSummary": dict(diagnostic_summary) if isinstance(diagnostic_summary, Mapping) else {},
                "sourceItemId": item_id,
            }
        ],
        "toolCalls": [],
        "terminalOperations": [],
        "terminalSessions": [],
        "modelObservations": [],
        "rolloutEvents": [],
    }


def _codex_tool_lifecycle_projection_from_source(
    source: dict[str, Any],
    operation_id: str,
    ordinal: int,
    status: str,
    title: str,
    summary: str,
) -> dict[str, list[dict[str, Any]]]:
    s = _service()
    lifecycle = s._empty_codex_tool_lifecycle_projection()
    if not operation_id:
        return lifecycle
    tool_call_id = f"tool_call:{operation_id}"
    runtime_kind = s._codex_runtime_kind(source)
    terminal_session_key = s._codex_terminal_session_key(source)
    terminal_request = s._codex_terminal_request(source, summary, title) if runtime_kind == "terminal" else {}
    if runtime_kind == "terminal" and not terminal_session_key and terminal_request.get("displayCommand"):
        # Direct cli_tool/exec_command events do not always carry a terminal session
        # identifier. A projection-local key preserves their real command/output
        # hierarchy without inventing one for legacy summaries or write_stdin.
        terminal_session_key = f"tool-call:{operation_id}"
    terminal_operation_id = f"terminal_operation:{ordinal}" if runtime_kind == "terminal" and terminal_session_key else ""
    tool_call = s._compact_codex_record(
        {
            "toolCallId": tool_call_id,
            "rawOperationId": operation_id,
            "status": status,
            "title": title or str(source.get("name") or "Tool call").strip() or "Tool call",
            "summary": summary,
            "rawToolName": str(source.get("name") or "").strip(),
            "runtimeKind": runtime_kind,
            "sequence": s._coerce_nonnegative_int(source.get("sequence") or source.get("_sequence")) or None,
            "timestamp": str(source.get("timestamp") or "").strip(),
            "terminalOperationId": terminal_operation_id,
            "tracePath": str(source.get("tracePath") or "").strip(),
            "error": s._trim_tool_detail_text(source.get("error") or "", max_chars=1200, max_lines=10),
            "resultPreview": s._trim_tool_detail_text(source.get("resultPreview") or "", max_chars=4000, max_lines=80),
            "resultType": str(source.get("resultType") or source.get("result_type") or "").strip(),
            "resultLength": s._coerce_tool_number(s._first_present_mapping_value(source, ("resultLength", "result_length"))),
            "resultKind": str(source.get("resultKind") or source.get("result_kind") or "").strip(),
            "truncated": bool(source.get("truncated")) if "truncated" in source else None,
            "originalLength": s._coerce_tool_number(s._first_present_mapping_value(source, ("originalLength", "original_length"))),
        }
    )
    lifecycle["toolCalls"].append(tool_call)
    if runtime_kind != "terminal" or not terminal_session_key:
        return lifecycle
    terminal_id = f"terminal:{terminal_session_key}"
    terminal_operation = s._compact_codex_record(
        {
            "operationId": terminal_operation_id,
            "toolCallId": tool_call_id,
            "terminalId": terminal_id,
            "kind": s._codex_terminal_operation_kind(source),
            "status": status,
            "request": terminal_request,
            "result": None if status in {"pending", "running"} else s._codex_terminal_result(source, summary, status),
            "durationSeconds": s._coerce_tool_number(
                s._first_present_mapping_value(source, ("durationSeconds", "duration_seconds"))
            ),
            "rawOperationId": operation_id,
            "tracePath": str(source.get("tracePath") or "").strip(),
        }
    )
    lifecycle["terminalOperations"].append(terminal_operation)
    lifecycle["terminalSessions"].append(
        {
            "terminalId": terminal_id,
            "createdByOperationId": terminal_operation_id,
            "operationIds": [terminal_operation_id],
            "status": status,
        }
    )
    lifecycle["modelObservations"].append(
        {
            "operationId": terminal_operation_id,
            "toolCallId": tool_call_id,
            "source": "DirectToolCall",
            "callItemIds": [tool_call_id],
            "outputItemIds": [] if status in {"pending", "running"} else [f"{tool_call_id}:output"],
        }
    )
    return lifecycle


def _run_session_cycle_message_projection(
    session_id: str,
    message: dict[str, Any],
    *,
    event: str,
    status: str,
    turn_id: str,
    active_task: dict[str, Any] | None = None,
) -> None:
    s = _service()
    started_at = s._perf_counter()
    outcome = "completed"
    try:
        s._record_session_cycle_message(
            session_id,
            message,
            event=event,
            status=status,
            active_task=active_task,
        )
    except Exception as exc:
        outcome = "failed"
        s._debug_logger.warning(
            f"background session cycle projection failed: {type(exc).__name__}: {exc}",
            tag="CHAT",
        )
    s._record_session_turn_lifecycle_event(
        session_id,
        "cycle_message_projection_finished",
        turn_id=turn_id,
        outcome=outcome,
        fields={
            "durationMs": s._elapsed_ms(started_at),
            "projectionMode": "background_ordered",
            "messageRole": str(message.get("role") or "").strip(),
            "event": str(event or "").strip(),
        },
    )


def _build_session_cache_usage(
    llm_usage: dict[str, Any] | None,
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    usage = s._normalize_turn_llm_usage(llm_usage)
    usage_source = str((usage or {}).get("source") or "").strip()
    observed = usage is not None and usage_source == "provider_usage"
    last_input_tokens = s._coerce_nonnegative_int((usage or {}).get("inputTokens") or 0) if observed else 0
    last_cached_input_tokens = min(
        s._coerce_nonnegative_int((usage or {}).get("cachedInputTokens") or 0),
        last_input_tokens,
    ) if last_input_tokens else 0
    last_cache_creation_input_tokens = min(
        s._coerce_nonnegative_int((usage or {}).get("cacheCreationInputTokens") or 0),
        last_input_tokens,
    ) if last_input_tokens else 0
    last_uncached_input_tokens = (
        s._coerce_nonnegative_int((usage or {}).get("uncachedInputTokens") or 0)
        if observed
        else 0
    )
    if observed and last_input_tokens:
        last_uncached_input_tokens = max(0, last_input_tokens - last_cached_input_tokens)
    turn_input_tokens = last_input_tokens
    turn_cached_input_tokens = last_cached_input_tokens
    turn_cache_creation_input_tokens = last_cache_creation_input_tokens
    turn_uncached_input_tokens = last_uncached_input_tokens
    aggregate = s._aggregate_session_provider_cache_usage(messages or [], fallback_usage=usage)
    aggregate_turn_count = s._coerce_nonnegative_int(aggregate.get("turnCount") or 0)
    if aggregate_turn_count:
        total_input_tokens = s._coerce_nonnegative_int(aggregate.get("inputTokens") or 0)
        total_cached_input_tokens = s._coerce_nonnegative_int(aggregate.get("cachedInputTokens") or 0)
        total_cache_creation_input_tokens = s._coerce_nonnegative_int(aggregate.get("cacheCreationInputTokens") or 0)
        total_uncached_input_tokens = s._coerce_nonnegative_int(aggregate.get("uncachedInputTokens") or 0)
    else:
        total_input_tokens = last_input_tokens
        total_cached_input_tokens = last_cached_input_tokens
        total_cache_creation_input_tokens = last_cache_creation_input_tokens
        total_uncached_input_tokens = last_uncached_input_tokens
    if total_input_tokens and not total_uncached_input_tokens:
        total_uncached_input_tokens = max(0, total_input_tokens - total_cached_input_tokens)
    return {
        "lastInputTokens": last_input_tokens,
        "lastCachedInputTokens": last_cached_input_tokens,
        "lastCacheReadInputTokens": last_cached_input_tokens,
        "lastCacheCreationInputTokens": last_cache_creation_input_tokens,
        "lastUncachedInputTokens": last_uncached_input_tokens,
        "turnInputTokens": turn_input_tokens,
        "turnCachedInputTokens": turn_cached_input_tokens,
        "turnCacheReadInputTokens": turn_cached_input_tokens,
        "turnCacheCreationInputTokens": turn_cache_creation_input_tokens,
        "turnUncachedInputTokens": turn_uncached_input_tokens,
        "turnCacheHitRate": (turn_cached_input_tokens / turn_input_tokens) if turn_input_tokens > 0 else 0.0,
        "totalInputTokens": total_input_tokens,
        "totalCachedInputTokens": total_cached_input_tokens,
        "totalCacheReadInputTokens": total_cached_input_tokens,
        "totalCacheCreationInputTokens": total_cache_creation_input_tokens,
        "totalUncachedInputTokens": total_uncached_input_tokens,
        "totalCacheHitRate": (total_cached_input_tokens / total_input_tokens) if total_input_tokens > 0 else 0.0,
        "totalObservedTurnCount": aggregate_turn_count or (1 if observed else 0),
        "updatedAt": str((usage or {}).get("recordedAt") or "").strip(),
        "source": "provider_usage" if observed else "not_called" if usage_source == "not_called" else "missing",
    }


def _build_session_cache_composition(
    turn_id: str,
    llm_usage: dict[str, Any] | None,
    *,
    context_composition: dict[str, Any] | None = None,
    average_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    usage = s._normalize_turn_llm_usage(llm_usage)
    if usage is None or usage.get("source") != "provider_usage":
        return s._enrich_session_cache_composition(
            {
                "turnId": turn_id,
                "recordedAt": s._now_timestamp(),
                "source": "missing",
            },
            context_composition=context_composition,
            average_cache=average_cache,
        ) or {}
    input_tokens = s._coerce_nonnegative_int(usage.get("inputTokens") or 0)
    cached_tokens = min(s._coerce_nonnegative_int(usage.get("cachedInputTokens") or 0), input_tokens) if input_tokens else 0
    cache_creation_tokens = min(s._coerce_nonnegative_int(usage.get("cacheCreationInputTokens") or 0), input_tokens) if input_tokens else 0
    uncached_tokens = max(0, input_tokens - cached_tokens)
    return s._enrich_session_cache_composition(
        {
            "turnId": turn_id,
            "recordedAt": usage.get("recordedAt") or s._now_timestamp(),
            "source": "provider_usage",
            "provider": usage.get("provider") or "",
            "model": usage.get("model") or "",
            "llmModelId": usage.get("llmModelId") or "",
            "promptCacheScope": usage.get("promptCacheScope") or "",
            "promptCachePartition": usage.get("promptCachePartition") or "",
            "inputTokens": input_tokens,
            "cachedInputTokens": cached_tokens,
            "cacheCreationInputTokens": cache_creation_tokens,
            "uncachedInputTokens": uncached_tokens,
            "segments": [
                {"key": "cached", "label": "cached", "tokens": cached_tokens, "status": "hit"},
                {"key": "cache_write", "label": "cache write", "tokens": cache_creation_tokens, "status": "write"},
                {"key": "uncached", "label": "uncached", "tokens": uncached_tokens, "status": "miss"},
            ],
        },
        context_composition=context_composition,
        average_cache=average_cache,
    ) or {}


def _build_session_context_usage(conversation: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
    s = _service()
    user_count = 0
    assistant_count = 0
    character_count = 0
    tool_call_count = 0
    for message in list(messages or []):
        role = str((message or {}).get("role") or "").strip().lower()
        if role == "user":
            user_count += 1
        elif role == "assistant":
            assistant_count += 1
        content = str((message or {}).get("content") or "")
        thought = str((message or {}).get("thought") or "")
        character_count += len(content) + len(thought)
        tool_calls = (message or {}).get("toolCalls") or (message or {}).get("tool_calls") or []
        if isinstance(tool_calls, list):
            tool_call_count += len(tool_calls)
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                character_count += len(str(tool_call.get("name") or ""))
                character_count += len(str(tool_call.get("summary") or ""))
                character_count += len(str(tool_call.get("resultPreview") or tool_call.get("result_preview") or ""))
                character_count += len(str(tool_call.get("error") or ""))
    estimated_tokens = s._estimate_session_context_tokens(character_count, tool_call_count)
    limit_payload = s._session_context_limit_payload(conversation)
    limit = s._coerce_nonnegative_int(limit_payload.get("limit") or 0)
    used = min(estimated_tokens, limit) if limit > 0 else estimated_tokens
    payload = {
        "used": used,
        "limit": limit,
        "limitSource": str(limit_payload.get("source") or "").strip(),
        "limitModelId": str(limit_payload.get("modelId") or "").strip(),
        "limitAgentId": str(limit_payload.get("agentId") or "").strip(),
        "limitError": str(limit_payload.get("error") or "").strip(),
        "estimatedTokens": estimated_tokens,
        "messageCount": len(list(messages or [])),
        "userMessageCount": user_count,
        "assistantMessageCount": assistant_count,
        "toolCallCount": tool_call_count,
        "source": "conversation_ledger",
    }
    return payload


def _normalize_session_cache_composition(value: Any) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(value, dict):
        return None
    input_tokens = s._coerce_nonnegative_int(value.get("inputTokens") or value.get("input_tokens") or 0)
    cached_tokens = s._coerce_nonnegative_int(value.get("cachedInputTokens") or value.get("cached_input_tokens") or 0)
    if input_tokens:
        cached_tokens = min(cached_tokens, input_tokens)
    else:
        cached_tokens = 0
    cache_creation_tokens = s._coerce_nonnegative_int(
        value.get("cacheCreationInputTokens")
        or value.get("cache_creation_input_tokens")
        or value.get("cacheWriteInputTokens")
        or value.get("cache_write_input_tokens")
        or 0
    )
    if input_tokens:
        cache_creation_tokens = min(cache_creation_tokens, input_tokens)
    else:
        cache_creation_tokens = 0
    uncached_tokens = s._coerce_nonnegative_int(value.get("uncachedInputTokens") or value.get("uncached_input_tokens") or 0)
    if not uncached_tokens and input_tokens:
        uncached_tokens = max(0, input_tokens - cached_tokens)
    source = str(value.get("source") or "").strip() or "missing"
    if source in {"not_called", "not_called_preflight"}:
        source = "not_called"
    segments = []
    for item in list(value.get("segments") or []):
        segment = s._normalize_session_cache_composition_segment(item, default_status="observed")
        if segment is not None:
            segments.append(segment)
    if not segments:
        if input_tokens:
            segments = [
                {"key": "cached", "label": "cached", "tokens": cached_tokens, "status": "hit"},
                {"key": "cache_write", "label": "cache write", "tokens": cache_creation_tokens, "status": "write"},
                {"key": "uncached", "label": "uncached", "tokens": uncached_tokens, "status": "miss"},
            ]
        elif source in {"missing", "not_called"}:
            segments = [{"key": "missing", "label": "missing", "tokens": 1, "status": "missing"}]
    computed_segments = []
    for item in list(value.get("computedSegments") or value.get("computed_segments") or []):
        segment = s._normalize_session_cache_composition_segment(item, default_status="computed_unknown")
        if segment is not None:
            computed_segments.append(segment)
    calibrated_segments = []
    for item in list(value.get("calibratedSegments") or value.get("calibrated_segments") or []):
        segment = s._normalize_session_cache_composition_segment(item, default_status="not_observed")
        if segment is not None:
            calibrated_segments.append(segment)
    computed_input_tokens = s._coerce_nonnegative_int(
        value.get("computedInputTokens") or value.get("computed_input_tokens") or input_tokens
    )
    computed_cached_tokens = min(
        s._coerce_nonnegative_int(
            value.get("computedCachedInputTokens")
            or value.get("computed_cached_input_tokens")
            or 0
        ),
        computed_input_tokens,
    ) if computed_input_tokens else 0
    computed_uncached_tokens = s._coerce_nonnegative_int(
        value.get("computedUncachedInputTokens")
        or value.get("computed_uncached_input_tokens")
        or 0
    )
    if computed_input_tokens and not computed_uncached_tokens:
        computed_uncached_tokens = max(0, computed_input_tokens - computed_cached_tokens)
    upper_bound_input_tokens = s._coerce_nonnegative_int(
        value.get("upperBoundInputTokens")
        or value.get("upper_bound_input_tokens")
        or computed_input_tokens
    )
    upper_bound_cached_tokens = min(
        s._coerce_nonnegative_int(
            value.get("upperBoundCachedInputTokens")
            or value.get("upper_bound_cached_input_tokens")
            or computed_cached_tokens
        ),
        upper_bound_input_tokens,
    ) if upper_bound_input_tokens else 0
    upper_bound_uncached_tokens = s._coerce_nonnegative_int(
        value.get("upperBoundUncachedInputTokens")
        or value.get("upper_bound_uncached_input_tokens")
        or 0
    )
    if upper_bound_input_tokens and not upper_bound_uncached_tokens:
        upper_bound_uncached_tokens = max(0, upper_bound_input_tokens - upper_bound_cached_tokens)
    average_input_tokens = s._coerce_nonnegative_int(
        value.get("averageInputTokens") or value.get("average_input_tokens") or 0
    )
    average_cached_tokens = min(
        s._coerce_nonnegative_int(
            value.get("averageCachedInputTokens")
            or value.get("average_cached_input_tokens")
            or 0
        ),
        average_input_tokens,
    ) if average_input_tokens else 0
    average_turn_count = s._coerce_nonnegative_int(
        value.get("averageObservedTurnCount")
        or value.get("average_observed_turn_count")
        or value.get("averageTurnCount")
        or value.get("average_turn_count")
        or 0
    )
    calibrated_cached_tokens = min(
        s._coerce_nonnegative_int(
            value.get("calibratedCachedInputTokens")
            or value.get("calibrated_cached_input_tokens")
            or cached_tokens
        ),
        input_tokens,
    ) if input_tokens else 0
    predicted_input_tokens = upper_bound_input_tokens
    predicted_cached_tokens = min(
        upper_bound_cached_tokens,
        predicted_input_tokens,
    ) if predicted_input_tokens else 0
    predicted_uncached_tokens = upper_bound_uncached_tokens
    if predicted_input_tokens and not predicted_uncached_tokens:
        predicted_uncached_tokens = max(0, predicted_input_tokens - predicted_cached_tokens)
    computed_overestimated_tokens = s._coerce_nonnegative_int(
        value.get("computedOverestimatedInputTokens")
        or value.get("computed_overestimated_input_tokens")
        or 0
    )
    provider_extra_cached_tokens = s._coerce_nonnegative_int(
        value.get("providerExtraCachedInputTokens")
        or value.get("provider_extra_cached_input_tokens")
        or 0
    )
    return {
        "turnId": str(value.get("turnId") or value.get("turn_id") or "").strip(),
        "recordedAt": str(value.get("recordedAt") or value.get("recorded_at") or "").strip(),
        "source": source,
        "provider": str(value.get("provider") or "").strip(),
        "model": str(value.get("model") or "").strip(),
        "llmModelId": str(value.get("llmModelId") or value.get("llm_model_id") or "").strip(),
        "promptCacheScope": str(value.get("promptCacheScope") or value.get("prompt_cache_scope") or "").strip(),
        "promptCachePartition": str(value.get("promptCachePartition") or value.get("prompt_cache_partition") or "").strip(),
        "inputTokens": input_tokens,
        "cachedInputTokens": cached_tokens,
        "cacheReadInputTokens": cached_tokens,
        "cacheCreationInputTokens": cache_creation_tokens,
        "uncachedInputTokens": uncached_tokens,
        "cacheHitRate": (cached_tokens / input_tokens) if input_tokens > 0 else 0.0,
        "segments": segments,
        "computedInputTokens": computed_input_tokens,
        "computedCachedInputTokens": computed_cached_tokens,
        "computedUncachedInputTokens": computed_uncached_tokens,
        "computedCacheHitRate": (computed_cached_tokens / computed_input_tokens) if computed_input_tokens > 0 else 0.0,
        "computedSegments": computed_segments,
        "upperBoundInputTokens": upper_bound_input_tokens,
        "upperBoundCachedInputTokens": upper_bound_cached_tokens,
        "upperBoundUncachedInputTokens": upper_bound_uncached_tokens,
        "upperBoundCacheHitRate": (upper_bound_cached_tokens / upper_bound_input_tokens) if upper_bound_input_tokens > 0 else 0.0,
        "calibratedInputTokens": input_tokens,
        "calibratedCachedInputTokens": calibrated_cached_tokens,
        "calibratedCacheHitRate": (calibrated_cached_tokens / input_tokens) if input_tokens > 0 else 0.0,
        "calibratedSegments": calibrated_segments,
        "predictedInputTokens": predicted_input_tokens,
        "predictedCachedInputTokens": predicted_cached_tokens,
        "predictedUncachedInputTokens": predicted_uncached_tokens,
        "predictedCacheHitRate": (predicted_cached_tokens / predicted_input_tokens) if predicted_input_tokens > 0 else 0.0,
        "computedOverestimatedInputTokens": computed_overestimated_tokens,
        "providerExtraCachedInputTokens": provider_extra_cached_tokens,
        "calibrationStatus": str(value.get("calibrationStatus") or value.get("calibration_status") or "").strip(),
        "calibrationReason": str(value.get("calibrationReason") or value.get("calibration_reason") or "").strip(),
        "predictionStatus": str(
            value.get("predictionStatus")
            or value.get("prediction_status")
            or "computed_upper_bound"
        ).strip(),
        "predictionReason": str(
            value.get("predictionReason")
            or value.get("prediction_reason")
            or "computed from stable prompt-prefix composition"
        ).strip(),
        "averageInputTokens": average_input_tokens,
        "averageCachedInputTokens": average_cached_tokens,
        "averageCacheHitRate": (average_cached_tokens / average_input_tokens) if average_input_tokens > 0 else 0.0,
        "averageObservedTurnCount": average_turn_count,
    }


def _normalize_session_cache_composition_segment(item: Any, *, default_status: str) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(item, dict):
        return None
    key = str(item.get("key") or "").strip()
    if not key:
        return None
    estimated_raw = item.get("estimated")
    if isinstance(estimated_raw, str):
        estimated = estimated_raw.strip().lower() in {"1", "true", "yes", "on"}
    else:
        estimated = bool(estimated_raw)
    return {
        "key": key,
        "label": str(item.get("label") or key).strip() or key,
        "tokens": s._coerce_nonnegative_int(item.get("tokens") or 0),
        "status": str(item.get("status") or default_status).strip() or default_status,
        "source": str(item.get("source") or "").strip(),
        "description": str(item.get("description") or "").strip(),
        "cachePolicy": str(item.get("cachePolicy") or item.get("cache_policy") or "").strip(),
        "order": s._coerce_nonnegative_int(item.get("order") or 0),
        "contentPreview": s._context_segment_content_preview(item),
        "promptCategory": str(item.get("promptCategory") or item.get("prompt_category") or "").strip(),
        "segmentKind": str(item.get("segmentKind") or item.get("segment_kind") or "").strip(),
        "accuracy": str(item.get("accuracy") or "").strip(),
        "parentKey": str(item.get("parentKey") or item.get("parent_key") or "").strip(),
        "estimated": estimated,
        "observedStatus": str(item.get("observedStatus") or item.get("observed_status") or "").strip(),
        "observedCachedInputTokens": s._coerce_nonnegative_int(
            item.get("observedCachedInputTokens") or item.get("observed_cached_input_tokens") or 0
        ),
        "observedMissedInputTokens": s._coerce_nonnegative_int(
            item.get("observedMissedInputTokens") or item.get("observed_missed_input_tokens") or 0
        ),
        "computedOverestimatedInputTokens": s._coerce_nonnegative_int(
            item.get("computedOverestimatedInputTokens") or item.get("computed_overestimated_input_tokens") or 0
        ),
        "providerExtraCachedInputTokens": s._coerce_nonnegative_int(
            item.get("providerExtraCachedInputTokens") or item.get("provider_extra_cached_input_tokens") or 0
        ),
        "calibrationReason": str(item.get("calibrationReason") or item.get("calibration_reason") or "").strip(),
    }


def _calibrate_session_cache_segments(
    *,
    source: str,
    provider: str,
    model: str,
    input_tokens: int,
    cached_tokens: int,
    cache_creation_tokens: int,
    computed_segments: list[dict[str, Any]],
    computed_cached_tokens: int,
) -> dict[str, Any]:
    s = _service()
    normalized_input_tokens = s._coerce_nonnegative_int(input_tokens)
    normalized_cached_tokens = min(s._coerce_nonnegative_int(cached_tokens), normalized_input_tokens) if normalized_input_tokens else 0
    normalized_computed_cached_tokens = min(
        s._coerce_nonnegative_int(computed_cached_tokens),
        normalized_input_tokens,
    ) if normalized_input_tokens else 0
    provider_observed = source == "provider_usage" and normalized_input_tokens > 0
    overestimated_tokens = max(0, normalized_computed_cached_tokens - normalized_cached_tokens) if provider_observed else 0
    provider_extra_cached_tokens = max(0, normalized_cached_tokens - normalized_computed_cached_tokens) if provider_observed else 0
    calibrated_segments: list[dict[str, Any]] = []
    for item in computed_segments:
        segment = dict(item)
        tokens = s._coerce_nonnegative_int(segment.get("tokens") or 0)
        status = str(segment.get("status") or "").strip()
        if not provider_observed:
            observed_status = "not_observed"
            observed_cached = 0
            observed_missed = 0
        elif status == "computed_hit":
            observed_status = "observed_hit"
            observed_cached = tokens
            observed_missed = 0
        elif status == "computed_write":
            observed_status = "computed_write"
            observed_cached = 0
            observed_missed = tokens
        elif status == "computed_miss":
            observed_status = "computed_miss"
            observed_cached = 0
            observed_missed = tokens
        else:
            observed_status = "not_observed"
            observed_cached = 0
            observed_missed = 0
        segment["observedStatus"] = observed_status
        segment["observedCachedInputTokens"] = observed_cached
        segment["observedMissedInputTokens"] = observed_missed
        segment["computedOverestimatedInputTokens"] = 0
        segment["providerExtraCachedInputTokens"] = 0
        calibrated_segments.append(segment)
    remaining_overestimate = overestimated_tokens
    primary_indices = [
        index
        for index, item in enumerate(calibrated_segments)
        if item.get("status") == "computed_hit"
        and (
            str(item.get("source") or "") == "provider_input_remainder"
            or str(item.get("cachePolicy") or "") == "assumed_stable_prefix"
        )
    ]
    fallback_indices = [
        index
        for index, item in reversed(list(enumerate(calibrated_segments)))
        if item.get("status") == "computed_hit" and index not in set(primary_indices)
    ]
    for index in primary_indices + fallback_indices:
        if remaining_overestimate <= 0:
            break
        item = calibrated_segments[index]
        available = s._coerce_nonnegative_int(item.get("observedCachedInputTokens") or 0)
        deducted = min(available, remaining_overestimate)
        if deducted <= 0:
            continue
        remaining_overestimate -= deducted
        observed_cached = max(0, available - deducted)
        observed_missed = s._coerce_nonnegative_int(item.get("observedMissedInputTokens") or 0) + deducted
        item["observedCachedInputTokens"] = observed_cached
        item["observedMissedInputTokens"] = observed_missed
        item["computedOverestimatedInputTokens"] = s._coerce_nonnegative_int(
            item.get("computedOverestimatedInputTokens") or 0
        ) + deducted
        item["observedStatus"] = "observed_miss" if observed_cached <= 0 else "observed_partial"
    if provider_extra_cached_tokens > 0:
        calibrated_segments.append(
            {
                "key": "provider_extra_hit",
                "label": "provider extra cached",
                "tokens": provider_extra_cached_tokens,
                "status": "provider_extra_hit",
                "source": "provider_usage",
                "description": "Provider reported cached input that the computed context manifest could not map to a cacheable segment.",
                "cachePolicy": "provider_observed",
                "order": len(calibrated_segments) + 1,
                "contentPreview": "Additional provider cache read outside the mapped session context manifest.",
                "observedStatus": "observed_hit",
                "observedCachedInputTokens": provider_extra_cached_tokens,
                "observedMissedInputTokens": 0,
                "computedOverestimatedInputTokens": 0,
                "providerExtraCachedInputTokens": provider_extra_cached_tokens,
                "calibrationReason": "Provider reported more cached input than computed cacheable segments.",
            }
        )
    status, reason = s._provider_cache_calibration_reason(
        provider=provider,
        model=model,
        source=source,
        cache_creation_tokens=cache_creation_tokens,
        overestimated_tokens=overestimated_tokens,
        provider_extra_cached_tokens=provider_extra_cached_tokens,
    )
    if remaining_overestimate > 0:
        status = "unmapped_provider_gap"
        reason = f"{reason} {remaining_overestimate} computed cache tokens could not be mapped to a segment."
    return {
        "calibratedInputTokens": normalized_input_tokens,
        "calibratedCachedInputTokens": normalized_cached_tokens if provider_observed else 0,
        "calibratedCacheHitRate": (normalized_cached_tokens / normalized_input_tokens)
        if provider_observed and normalized_input_tokens > 0
        else 0.0,
        "calibratedSegments": calibrated_segments,
        "computedOverestimatedInputTokens": overestimated_tokens,
        "providerExtraCachedInputTokens": provider_extra_cached_tokens,
        "calibrationStatus": status,
        "calibrationReason": reason,
    }


def _build_computed_cache_segments(
    *,
    input_tokens: int,
    context_composition: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], int, int]:
    s = _service()
    ordered_context_segments = s._ordered_model_input_context_segments(context_composition)
    context_tokens = sum(s._coerce_nonnegative_int(item.get("tokens") or 0) for item in ordered_context_segments)
    total_input_tokens = max(s._coerce_nonnegative_int(input_tokens), context_tokens)
    if total_input_tokens <= 0:
        return (
            [
                {
                    "key": "computed_missing",
                    "label": "computed missing",
                    "tokens": 1,
                    "status": "computed_unknown",
                    "source": "no_provider_input",
                    "description": "No provider input tokens were available for computed cache diagnostics.",
                    "cachePolicy": "unknown",
                    "order": 0,
                    "contentPreview": "No provider input token payload was available for computed cache diagnostics.",
                }
            ],
            0,
            0,
        )
    segments: list[dict[str, Any]] = []
    computed_cached_tokens = 0
    prefix_open = True
    unexplained_tokens = max(0, total_input_tokens - context_tokens)
    if unexplained_tokens:
        segments.extend(s._estimated_provider_prefix_cache_segments(unexplained_tokens))
        computed_cached_tokens += unexplained_tokens
    stable_policies = {"cacheable", "prefix_candidate", "assumed_stable_prefix"}
    volatile_policies = {"volatile", "never_cache", "dynamic"}
    for index, item in enumerate(ordered_context_segments, start=1 if unexplained_tokens else 0):
        tokens = s._coerce_nonnegative_int(item.get("tokens") or 0)
        if tokens <= 0:
            continue
        cache_policy = str(item.get("cachePolicy") or item.get("cache_policy") or "").strip()
        key = str(item.get("key") or "").strip() or f"segment_{index}"
        if prefix_open and cache_policy in stable_policies:
            status = "computed_hit"
            computed_cached_tokens += tokens
        elif cache_policy in stable_policies:
            status = "computed_write"
        else:
            status = "computed_miss"
            if cache_policy in volatile_policies or cache_policy:
                prefix_open = False
        if cache_policy not in stable_policies:
            prefix_open = False
        segments.append(
            {
                "key": key,
                "label": str(item.get("label") or key).strip() or key,
                "tokens": tokens,
                "status": status,
                "source": str(item.get("source") or "").strip(),
                "description": str(item.get("description") or "").strip(),
                "cachePolicy": cache_policy,
                "order": index,
                "contentPreview": s._context_segment_content_preview(item),
                "promptCategory": str(item.get("promptCategory") or item.get("prompt_category") or s._context_prompt_category(key)).strip(),
                "segmentKind": "prompt_source",
                "accuracy": "manifest",
            }
        )
    computed_cached_tokens = min(computed_cached_tokens, total_input_tokens)
    return segments, computed_cached_tokens, max(0, total_input_tokens - computed_cached_tokens)


def _enrich_session_cache_composition(
    composition: dict[str, Any] | None,
    *,
    context_composition: dict[str, Any] | None,
    average_cache: dict[str, Any] | None,
) -> dict[str, Any] | None:
    s = _service()
    normalized = s._normalize_session_cache_composition(composition)
    if normalized is None:
        return None
    input_tokens = s._coerce_nonnegative_int(normalized.get("inputTokens") or 0)
    computed_segments, computed_cached, computed_uncached = s._build_computed_cache_segments(
        input_tokens=input_tokens,
        context_composition=context_composition,
    )
    average = s._cache_average_from_usage(average_cache)
    calibration = s._calibrate_session_cache_segments(
        source=str(normalized.get("source") or ""),
        provider=str(normalized.get("provider") or ""),
        model=str(normalized.get("model") or normalized.get("llmModelId") or ""),
        input_tokens=input_tokens,
        cached_tokens=s._coerce_nonnegative_int(normalized.get("cachedInputTokens") or 0),
        cache_creation_tokens=s._coerce_nonnegative_int(normalized.get("cacheCreationInputTokens") or 0),
        computed_segments=computed_segments,
        computed_cached_tokens=computed_cached,
    )
    computed_input_total = max(
        input_tokens,
        sum(s._coerce_nonnegative_int(item.get("tokens") or 0) for item in computed_segments),
    )
    enriched = {
        **normalized,
        "computedInputTokens": computed_input_total,
        "computedCachedInputTokens": computed_cached,
        "computedUncachedInputTokens": computed_uncached,
        "computedSegments": computed_segments,
        "upperBoundInputTokens": computed_input_total,
        "upperBoundCachedInputTokens": computed_cached,
        "upperBoundUncachedInputTokens": computed_uncached,
        **calibration,
        "predictedInputTokens": computed_input_total,
        "predictedCachedInputTokens": computed_cached,
        "predictedUncachedInputTokens": computed_uncached,
        "predictionStatus": "computed_upper_bound",
        "predictionReason": "computed from stable prompt-prefix composition",
        "averageInputTokens": average["inputTokens"],
        "averageCachedInputTokens": average["cachedInputTokens"],
        "averageObservedTurnCount": average["observedTurnCount"],
    }
    return s._normalize_session_cache_composition(enriched)


def _build_last_context_composition(
    *,
    conversation: dict[str, Any],
    turn_id: str,
    user_message: str,
    history_messages: list[dict[str, Any]],
    active_task: Any,
    runtime_context_block: str = "",
    dynamic_runtime_context_block: str = "",
    dynamic_runtime_context_included: bool = False,
    runtime_context_segments: list[dict[str, Any]] | None = None,
    guidance_context_block: str = "",
    guidance_context_included: bool = False,
    skill_runtime_context_block: str = "",
    skill_runtime_context_included: bool = False,
    active_skill_context_block: str = "",
    active_skill_context_included: bool = False,
    attachments: list[dict[str, Any]] | None = None,
    prompt_cache_partition: str = "",
) -> dict[str, Any]:
    s = _service()
    segments = [
        s._context_segment(
            "current_user",
            "current user",
            content=user_message,
            chars=len(str(user_message or "")),
            item_count=1 if str(user_message or "").strip() else 0,
            source="raw_user_message",
            description="Current user message passed as the turn prompt.",
            kind="current_user",
            lifecycle="turn",
            authority=60,
            volatility=100,
            relevance=100,
            placement="current_user",
            cache_policy="never_cache",
            retention="current_turn_only",
        ),
        s._context_segment(
            "history",
            "history",
            chars=s._message_list_chars(history_messages),
            item_count=len(list(history_messages or [])),
            source="seed_chat_history",
            description="Filtered prior chat messages seeded into the agent.",
            kind="history",
            lifecycle="session",
            authority=45,
            volatility=35,
            relevance=70,
            placement="history",
            cache_policy="prefix_candidate",
            retention="carryover_summary",
        ),
    ]
    active_task_chars = s._active_task_context_chars(active_task)
    if active_task_chars:
        segments.append(
            s._context_segment(
                "active_task",
                "task state",
                chars=active_task_chars,
                item_count=1,
                status="state_only",
                source="active_task",
                description="Session task state retained outside the LLM message list.",
                kind="session_contract",
                lifecycle="task",
                authority=75,
                volatility=60,
                relevance=85,
                placement="session_state",
                cache_policy="never_cache",
                retention="carryover_summary",
                included_in_model_input=False,
            )
        )
    agent_context_segments, agent_context_previews = s._agent_context_manifest_segments(
        runtime_context_segments,
        dynamic_runtime_context_included=dynamic_runtime_context_included,
    )
    if agent_context_segments:
        segments.extend(agent_context_segments)
    elif runtime_context_block:
        segments.append(
            s._context_segment(
                "agent_context",
                "agent context",
                content=runtime_context_block,
                chars=len(runtime_context_block),
                item_count=1,
                source="context_engine",
                description="Stable runtime context seeded into the agent system prefix.",
                kind="agent_static_context",
                lifecycle="stable",
                authority=80,
                volatility=15,
                relevance=70,
                placement="system_prefix",
                cache_policy="cacheable",
                retention="persist",
            )
        )
    if dynamic_runtime_context_block:
        dynamic_included = bool(dynamic_runtime_context_included)
        segments.append(
            s._context_segment(
                "dynamic_runtime_context",
                "dynamic runtime context",
                content=dynamic_runtime_context_block,
                chars=len(dynamic_runtime_context_block),
                item_count=1,
                status="included" if dynamic_included else "omitted",
                source="context_engine",
                description=(
                    "Dynamic runtime context inserted into model input."
                    if dynamic_included
                    else "Dynamic runtime context was available but omitted from model input."
                ),
                kind="runtime_observation",
                lifecycle="turn",
                authority=50,
                volatility=90,
                relevance=55,
                placement="before_current_user" if dynamic_included else "omitted",
                cache_policy="never_cache",
                retention="current_turn_only",
                included_in_model_input=dynamic_included,
            )
        )
    if guidance_context_block:
        guidance_included = bool(guidance_context_included)
        segments.append(
            s._context_segment(
                "guidance",
                "guidance",
                content=guidance_context_block,
                chars=len(guidance_context_block),
                item_count=1,
                status="included" if guidance_included else "omitted",
                source="operator_guidance",
                description=(
                    "Recent operator guidance inserted into model input."
                    if guidance_included
                    else "Recent operator guidance was available but omitted from model input."
                ),
                kind="operator_guidance",
                lifecycle="turn",
                authority=65,
                volatility=85,
                relevance=75,
                placement="before_current_user" if guidance_included else "omitted",
                cache_policy="volatile",
                retention="current_turn_only",
                included_in_model_input=guidance_included,
            )
        )
    if skill_runtime_context_block:
        skill_included = bool(skill_runtime_context_included)
        segments.append(
            s._context_segment(
                "skill",
                "skill",
                content=skill_runtime_context_block,
                chars=len(skill_runtime_context_block),
                item_count=1,
                status="included" if skill_included else "omitted",
                source="skill_runtime_context",
                description=(
                    "Slash skill runtime context seeded into the agent before the current user message."
                    if skill_included
                    else "Slash skill runtime context was available but could not be seeded into model input."
                ),
                kind="slash_payload",
                lifecycle="turn",
                authority=70,
                volatility=95,
                relevance=90,
                placement="before_current_user" if skill_included else "omitted",
                cache_policy="volatile",
                retention="current_turn_only",
                included_in_model_input=skill_included,
            )
        )
    if active_skill_context_block:
        active_skill_included = bool(active_skill_context_included)
        segments.append(
            s._context_segment(
                "active_skill",
                "active skill",
                content=active_skill_context_block,
                chars=len(active_skill_context_block),
                item_count=1,
                status="included" if active_skill_included else "omitted",
                source="active_skill_contract",
                description=(
                    "Compact active skill contract seeded into the agent before the current user message."
                    if active_skill_included
                    else "Active skill contract was available but could not be seeded into model input."
                ),
                kind="active_skill",
                lifecycle="task",
                authority=68,
                volatility=80,
                relevance=85,
                placement="before_current_user" if active_skill_included else "omitted",
                cache_policy="volatile",
                retention="carryover_summary",
                included_in_model_input=active_skill_included,
            )
        )
    normalized_attachments = s._normalize_message_attachments(attachments)
    if normalized_attachments:
        segments.append(
            s._context_segment(
                "attachments",
                "attachments",
                chars=sum(len(str(item.get("filename") or "")) + len(str(item.get("contentType") or "")) for item in normalized_attachments),
                item_count=len(normalized_attachments),
                source="user_attachments",
                description="User image attachments prepared for this turn.",
                kind="attachment",
                lifecycle="turn",
                authority=55,
                volatility=95,
                relevance=90,
                placement="current_user",
                cache_policy="never_cache",
                retention="current_turn_only",
            )
        )
    limit_payload = s._session_context_limit_payload(conversation)
    normalized = s.build_context_manifest(
        turn_id=turn_id,
        recorded_at=s._now_timestamp(),
        source="runtime_assembly",
        limit_tokens=s._coerce_nonnegative_int(limit_payload.get("limit") or 0),
        limit_source=str(limit_payload.get("source") or "").strip(),
        limit_model_id=str(limit_payload.get("modelId") or "").strip(),
        limit_agent_id=str(limit_payload.get("agentId") or "").strip(),
        prompt_cache_partition=prompt_cache_partition,
        segments=segments,
    )
    content_previews = {
        "current_user": s._compact_preview_text(user_message, max_lines=3, max_chars=240),
        "history": s._message_list_content_preview(history_messages),
        "active_task": s._active_task_content_preview(active_task),
        "agent_context": s._compact_preview_text(runtime_context_block, max_lines=3, max_chars=240),
        "dynamic_runtime_context": s._compact_preview_text(dynamic_runtime_context_block, max_lines=3, max_chars=240),
        "guidance": s._compact_preview_text(guidance_context_block, max_lines=3, max_chars=240),
        "skill": s._compact_preview_text(skill_runtime_context_block, max_lines=3, max_chars=240),
        "active_skill": s._compact_preview_text(active_skill_context_block, max_lines=3, max_chars=240),
        "attachments": s._compact_preview_text(
            ", ".join(str(item.get("filename") or item.get("contentType") or "") for item in normalized_attachments),
            max_lines=1,
            max_chars=240,
        ),
    }
    content_previews.update(agent_context_previews)
    normalized = s._attach_context_segment_content_previews(
        normalized,
        {key: value for key, value in content_previews.items() if value},
    )
    return normalized or {
        "schemaVersion": 1,
        "turnId": str(turn_id or "").strip(),
        "recordedAt": s._now_timestamp(),
        "source": "runtime_assembly",
        "totalChars": 0,
        "totalTokens": 0,
        "limitTokens": s._coerce_nonnegative_int(limit_payload.get("limit") or 0),
        "limitSource": str(limit_payload.get("source") or "").strip(),
        "limitModelId": str(limit_payload.get("modelId") or "").strip(),
        "limitAgentId": str(limit_payload.get("agentId") or "").strip(),
        "segments": [],
        "ordering": [],
        "modelInputOrdering": [],
        "budgets": {
            "usedTokens": 0,
            "observedTokens": 0,
            "omittedTokens": 0,
            "observedChars": 0,
            "limitTokens": s._coerce_nonnegative_int(limit_payload.get("limit") or 0),
            "droppedTokens": 0,
            "overLimit": False,
        },
        "cache": {
            "stablePrefixHash": "",
            "cacheableSegmentCount": 0,
            "volatileSegmentCount": 0,
            "firstVolatileSegmentIndex": -1,
            "promptCachePartitionHash": s._short_hash(prompt_cache_partition),
            "missLikelyReason": "",
        },
    }


def _normalize_session_context_composition(value: Any) -> dict[str, Any] | None:
    s = _service()
    normalized = s.normalize_context_manifest(value)
    if normalized is None or not isinstance(value, dict):
        return normalized
    raw_segments = [item for item in list(value.get("segments") or []) if isinstance(item, dict)]
    if not raw_segments:
        return normalized
    next_segments: list[dict[str, Any]] = []
    for index, item in enumerate(list(normalized.get("segments") or [])):
        segment = dict(item)
        raw = raw_segments[index] if index < len(raw_segments) else {}
        preview = s._context_segment_content_preview(raw)
        if preview:
            segment["contentPreview"] = preview
        next_segments.append(segment)
    updated = dict(normalized)
    updated["segments"] = next_segments
    return updated


def _normalize_session_llm_payload_trace(value: Any) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(value, dict):
        return None
    trace: dict[str, Any] = {}
    for key in s._SESSION_LLM_PAYLOAD_TRACE_TEXT_FIELDS:
        text = str(value.get(key) or "").strip()
        if text:
            trace[key] = text
    for key in s._SESSION_LLM_PAYLOAD_TRACE_INT_FIELDS:
        if key in value:
            trace[key] = s._coerce_nonnegative_int(value.get(key))
    if "stream" in value:
        trace["stream"] = bool(value.get("stream"))
    roles = value.get("messageRoles")
    if isinstance(roles, list):
        safe_roles = [str(role or "").strip() for role in roles if str(role or "").strip()]
        if safe_roles:
            trace["messageRoles"] = safe_roles[:80]
    message_role_counts = s._normalize_llm_payload_trace_counts(value.get("messageRoleCounts"))
    if message_role_counts:
        trace["messageRoleCounts"] = message_role_counts
    for key, allowed_keys in s._SESSION_LLM_PAYLOAD_TRACE_MAP_FIELD_KEYS.items():
        safe_item = s._normalize_llm_payload_trace_map(value.get(key), allowed_keys)
        if safe_item:
            trace[key] = safe_item
    return trace or None


def _normalize_session_runtime_notices(items: Any) -> list[dict[str, Any]]:
    s = _service()
    notices: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(list(items or []), start=1):
        notice = s._normalize_session_runtime_notice(raw, index=index)
        if not notice:
            continue
        dedupe_key = (
            str(notice.get("kind") or ""),
            str(notice.get("message") or ""),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        notices.append(notice)
    return notices[-8:]


def _normalize_turn_llm_usage(value: Any) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(value, dict):
        return None
    source = str(value.get("source") or "").strip() or "missing"
    if source in {"not_called", "not_called_preflight"}:
        source = "not_called"
    input_tokens = s._coerce_nonnegative_int(value.get("input_tokens") or value.get("inputTokens") or 0)
    output_tokens = s._coerce_nonnegative_int(value.get("output_tokens") or value.get("outputTokens") or 0)
    total_tokens = s._coerce_nonnegative_int(value.get("total_tokens") or value.get("totalTokens") or 0)
    if not total_tokens:
        total_tokens = input_tokens + output_tokens
    cached_input_tokens = min(
        s._coerce_nonnegative_int(value.get("cached_input_tokens") or value.get("cachedInputTokens") or 0),
        input_tokens,
    ) if input_tokens else 0
    cache_creation_input_tokens = min(
        s._coerce_nonnegative_int(
            value.get("cache_creation_input_tokens")
            or value.get("cacheCreationInputTokens")
            or value.get("cache_write_input_tokens")
            or value.get("cacheWriteInputTokens")
            or 0
        ),
        input_tokens,
    ) if input_tokens else 0
    uncached_input_tokens = s._coerce_nonnegative_int(
        value.get("uncached_input_tokens") or value.get("uncachedInputTokens") or 0
    )
    if input_tokens:
        uncached_input_tokens = max(0, input_tokens - cached_input_tokens)
    else:
        uncached_input_tokens = 0
    return {
        "source": source,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
        "cachedInputTokens": cached_input_tokens,
        "cacheReadInputTokens": cached_input_tokens,
        "cacheCreationInputTokens": cache_creation_input_tokens,
        "uncachedInputTokens": uncached_input_tokens,
        "cacheHitRate": (cached_input_tokens / input_tokens) if input_tokens > 0 else 0.0,
        "provider": s.compact_repeated_metadata_text(value.get("provider") or ""),
        "model": s.compact_repeated_metadata_text(value.get("model") or ""),
        "promptCacheScope": str(value.get("prompt_cache_scope") or value.get("promptCacheScope") or "").strip(),
        "promptCachePartition": str(
            value.get("prompt_cache_partition") or value.get("promptCachePartition") or ""
        ).strip(),
        "llmModelId": str(value.get("llm_model_id") or value.get("llmModelId") or "").strip(),
        "recordedAt": str(value.get("recorded_at") or value.get("recordedAt") or "").strip(),
    }


def _session_detail_agent_snapshot(
    conversation: dict[str, Any],
    agent_id: Any,
    *,
    hydrate_agent: bool,
) -> dict[str, Any] | None:
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id or not hydrate_agent:
        return None
    cached_agent = conversation.get("_agent")
    if (
        isinstance(cached_agent, dict)
        and str(cached_agent.get("agentId") or "").strip() == normalized_agent_id
    ):
        return cached_agent
    return s.get_agent(normalized_agent_id)


def _active_task_to_api(value: dict[str, Any] | None) -> dict[str, Any] | None:
    s = _service()
    task = s._normalize_session_active_task(value)
    if not task:
        return None
    if not s._is_task_tool_backed_active_task(task):
        return None
    metadata = dict(task.get("metadata") or {}) if isinstance(task.get("metadata"), dict) else {}
    return {
        "taskId": str(task.get("task_id") or "").strip(),
        "kind": str(task.get("kind") or "").strip(),
        "status": str(task.get("status") or "").strip(),
        "title": str(task.get("title") or "").strip(),
        "goal": str(task.get("goal") or "").strip(),
        "readFiles": list(task.get("read_files") or []),
        "changedFiles": list(task.get("changed_files") or []),
        "verificationStatus": str(task.get("verification_status") or "").strip(),
        "verificationSummary": str(task.get("verification_summary") or "").strip(),
        "latestSummary": str(task.get("latest_summary") or "").strip(),
        "nextAction": str(task.get("next_action") or "").strip(),
        "lastUserMessage": str(task.get("last_user_message") or "").strip(),
        "turnCount": s._coerce_nonnegative_int(task.get("turn_count") or 0),
        "resumeCount": s._coerce_nonnegative_int(task.get("resume_count") or 0),
        "createdAt": str(task.get("created_at") or "").strip(),
        "updatedAt": str(task.get("updated_at") or "").strip(),
        "defaultFileContext": str(task.get("default_file_context") or "").strip(),
        "previewTabs": list(task.get("preview_tabs") or []),
        "activePreviewPath": str(task.get("active_preview_path") or "").strip(),
        "metadata": metadata,
    }


def _active_task_with_live_work_run(
    active_task: dict[str, Any] | None,
    live_work_run: dict[str, Any] | None,
) -> dict[str, Any] | None:
    s = _service()
    if not s._is_task_tool_backed_active_task(active_task):
        return active_task
    if not isinstance(live_work_run, dict):
        return active_task
    status = str(live_work_run.get("status") or live_work_run.get("currentPhase") or "").strip().lower()
    if status not in {"queued", "running", "stopping", "paused"}:
        return active_task
    updated = dict(active_task or {})
    summary = str(live_work_run.get("summary") or "").strip()
    user_message = str(live_work_run.get("userMessage") or "").strip()
    now = str(live_work_run.get("updatedAt") or "").strip()
    updated["task_id"] = str(updated.get("task_id") or live_work_run.get("runId") or "").strip()
    updated["kind"] = str(updated.get("kind") or "chat_turn").strip()
    updated["status"] = status
    updated["latest_summary"] = summary or updated.get("latest_summary") or updated.get("latestSummary") or ""
    if user_message and not str(updated.get("goal") or "").strip():
        updated["goal"] = user_message
    if user_message and not str(updated.get("title") or "").strip():
        updated["title"] = s.trim_lines(user_message, max_lines=1)
    if user_message:
        updated["last_user_message"] = user_message
    if now:
        updated["updated_at"] = now
    metadata = dict(updated.get("metadata") or {}) if isinstance(updated.get("metadata"), dict) else {}
    metadata["liveWorkRunId"] = str(live_work_run.get("runId") or "").strip()
    metadata["liveWorkRunStatus"] = status
    updated["metadata"] = metadata
    return updated


def _messages_with_live_output(
    session_id: str,
    *,
    normalized_messages: Any = None,
) -> list[dict[str, Any]]:
    s = _service()
    detail_messages = (
        list(normalized_messages or [])
        if normalized_messages is not None
        else s._session_ledger_visible_messages(session_id)
    )
    live_message = s._build_live_output_message(session_id)
    if live_message is None:
        return detail_messages
    detail_messages = s._without_live_turn_ledger_partials(detail_messages, live_message)
    return detail_messages + [live_message]


def _latest_message_summary(messages: list[dict[str, Any]]) -> str:
    s = _service()
    for item in reversed(messages):
        preview = s._compact_preview_text(item.get("content") or "")
        if preview:
            return preview
    return ""


def _conversation_phase(conversation_id: str, conversation: dict[str, Any]) -> str:
    s = _service()
    if s._is_session_stop_requested(conversation_id):
        return "stopping"
    normalized = str(conversation.get("last_turn_status") or conversation.get("lastTurnStatus") or "").strip().lower()
    if s._is_session_running(conversation_id):
        if normalized == "queued":
            return "queued"
        return "running"
    if normalized in {
        "queued",
        "failed",
        "ready",
        "completed",
        "needs_continue",
        "paused",
        "paused_limit",
        "stopped_by_user",
        "failed_provider",
        "failed_runtime",
        "superseded",
    }:
        return normalized
    if bool(conversation.get("_hasLedgerMessages")):
        return "ready"
    if "_hasLedgerMessages" not in conversation and s._ledger_visible_messages_for_session(conversation_id):
        return "ready"
    return "idle"


def _projection_edit_contract(kind: str, source_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    from core.agent_kernel.source_authority import projection_edit_contract

    return projection_edit_contract(kind, source_id, metadata)


def _public_prompt_assembly_manifest(prompt_assembly: Any) -> dict[str, Any]:
    if not isinstance(prompt_assembly, dict):
        return {}
    manifest: dict[str, Any] = {}
    for key in (
            "schemaVersion",
            "assemblyMode",
            "modelProtocol",
            "capabilityFingerprint",
            "permissionFingerprint",
            "stablePrefixHash",
            "sessionSnapshotHash",
            "totalEstimatedTokens",
            "budgetTokens",
    ):
        if key in prompt_assembly:
            manifest[key] = prompt_assembly.get(key)
    segments: list[dict[str, Any]] = []
    for raw_segment in prompt_assembly.get("segments") or []:
        if not isinstance(raw_segment, dict):
            continue
        segment: dict[str, Any] = {}
        for key in (
                "key",
                "tier",
                "placement",
                "stability",
                "trust",
                "source",
                "required",
                "chars",
                "contentHash",
                "estimatedTokens",
                "budgetTokens",
                "cachePolicy",
                "capabilityRequirements",
                "decision",
                "decisionReason",
                "cacheHit",
        ):
            if key in raw_segment:
                segment[key] = raw_segment.get(key)
        segments.append(segment)
    manifest["segments"] = segments
    return manifest


def _public_agent_prompt_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    result: dict[str, Any] = {}
    for key in (
        "schemaVersion",
        "promptTemplateId",
        "templateId",
        "name",
        "category",
        "sourcePath",
        "sourceExists",
        "contentHash",
        "contentLength",
        "corePromptSchemaVersion",
        "corePromptHash",
        "corePromptLength",
        "corePrompts",
        "promptAssemblySchemaVersion",
        "capturedAt",
        "agentId",
        "agentCode",
        "agentDisplayName",
        "reason",
    ):
        if key in snapshot:
            result[key] = snapshot.get(key)
    manifest = _public_prompt_assembly_manifest(snapshot.get("promptAssembly"))
    if manifest:
        result["promptAssembly"] = manifest
    return result


def _session_agent_status_payload(
    agent_id: str,
    agent: dict[str, Any] | None,
    *,
    hydrate_agent: bool = True,
    agent_lookup_checked: bool = False,
    persisted_status_code: str = "",
) -> dict[str, Any]:
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    if str(persisted_status_code or "").strip() == "deleted_agent":
        return {
            "agentMissing": True,
            "agentStatusCode": "deleted_agent",
            "agentStatusMessage": s.text_for(
                s.get_web_language(),
                zh="缺少有效 Agent：当前会话绑定的 Agent 已被彻底删除，历史会话已保留但不会自动重建 Agent。",
                en="Missing valid Agent: the Agent bound to this session was permanently deleted; history is preserved without recreating it.",
            ),
        }
    if str(persisted_status_code or "").strip() == "missing_agent":
        return {
            "agentMissing": True,
            "agentStatusCode": "missing_agent",
            "agentStatusMessage": s.text_for(
                s.get_web_language(),
                zh="缺少有效 Agent：当前会话引用的 Agent 已不存在或不可用。",
                en="Missing valid Agent: this session references an Agent that no longer exists or is unavailable.",
            ),
        }
    if not normalized_agent_id:
        return {
            "agentMissing": False,
            "agentStatusCode": "",
            "agentStatusMessage": "",
        }
    if not hydrate_agent and not isinstance(agent, dict) and not agent_lookup_checked:
        return {
            "agentMissing": False,
            "agentStatusCode": "",
            "agentStatusMessage": "",
        }
    if not isinstance(agent, dict):
        return {
            "agentMissing": True,
            "agentStatusCode": "missing_agent",
            "agentStatusMessage": s.text_for(
                s.get_web_language(),
                zh="缺少有效 Agent：当前会话引用的 Agent 已不存在或不可用。",
                en="Missing valid Agent: this session references an Agent that no longer exists or is unavailable.",
            ),
        }
    if str(agent.get("status") or "active").strip().lower() == "archived":
        return {
            "agentMissing": True,
            "agentStatusCode": "archived_agent",
            "agentStatusMessage": s.text_for(
                s.get_web_language(),
                zh="缺少有效 Agent：当前会话引用的 Agent 已归档，不能继续作为可用成员运行。",
                en="Missing valid Agent: this session references an archived Agent and cannot run it as an active member.",
            ),
        }
    return {
        "agentMissing": False,
        "agentStatusCode": "",
        "agentStatusMessage": "",
    }


def _ledger_visible_messages_for_session(session_id: str) -> list[dict[str, Any]]:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return []
    events = s._load_session_conversation_events_cached(normalized_session_id)
    if not events:
        return []
    return s.conversation_visible_messages_from_events(events)


def _ledger_latest_preview_messages_for_session(
    session_id: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Return the latest summary preview without replaying unbounded tool output."""

    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return [], False
    try:
        preview_slice = s.load_conversation_preview_slice(
            s.PROJECT_ROOT,
            normalized_session_id,
            event_limit=_SESSION_SUMMARY_EVENT_SCAN_LIMIT,
        )
    except Exception:
        preview_slice = None
    if preview_slice is not None and bool(preview_slice.safe):
        visible_messages = list(preview_slice.visible_messages or [])
        preview_messages = s._normalize_latest_preview_messages(
            normalized_session_id,
            visible_messages,
            scan_limit=_SESSION_SUMMARY_MESSAGE_SCAN_LIMIT,
        )
        if (
            bool(preview_slice.reached_start)
            or bool(preview_messages)
            or len(visible_messages) >= _SESSION_SUMMARY_MESSAGE_SCAN_LIMIT
        ):
            return preview_messages, bool(visible_messages)

    visible_messages = s._ledger_visible_messages_for_session(normalized_session_id)
    return (
        s._normalize_latest_preview_messages(
            normalized_session_id,
            visible_messages,
            scan_limit=_SESSION_SUMMARY_MESSAGE_SCAN_LIMIT,
        ),
        bool(visible_messages),
    )


def _normalize_child_handoff_context(value: Any) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(value, dict):
        return None
    return {
        "source": str(value.get("source") or "").strip(),
        "parentSessionId": str(value.get("parentSessionId") or value.get("parent_session_id") or "").strip(),
        "sourceSessionId": str(value.get("sourceSessionId") or value.get("source_session_id") or "").strip(),
        "parentMessageId": str(value.get("parentMessageId") or value.get("parent_message_id") or "").strip(),
        "triggeringUserMessage": s.trim_lines(
            value.get("triggeringUserMessage") or value.get("triggering_user_message") or "",
            max_lines=8,
        ),
        "splitReason": s.trim_lines(value.get("splitReason") or value.get("split_reason") or "", max_lines=4),
        "inheritedFacts": [
            s.trim_lines(item, max_lines=2)
            for item in s._normalize_string_list(value.get("inheritedFacts") or value.get("inherited_facts"))
        ],
        "relevantFiles": s._normalize_string_list(value.get("relevantFiles") or value.get("relevant_files")),
        "relevantLogs": s._normalize_string_list(value.get("relevantLogs") or value.get("relevant_logs")),
        "constraints": [s.trim_lines(item, max_lines=2) for item in s._normalize_string_list(value.get("constraints"))],
        "excludedContextSummary": s.trim_lines(
            value.get("excludedContextSummary") or value.get("excluded_context_summary") or "",
            max_lines=4,
        ),
    }


def _normalize_child_result_card(value: Any) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(value, dict):
        return None
    title = s.trim_lines(value.get("title") or "", max_lines=1).strip()
    summary = s.trim_lines(value.get("summary") or "", max_lines=4).strip()
    if not title and not summary:
        return None
    return {
        "status": str(value.get("status") or "").strip(),
        "title": title,
        "summary": summary,
        "changedFiles": s._normalize_string_list(value.get("changedFiles") or value.get("changed_files")),
        "validations": [
            s.trim_lines(item, max_lines=2)
            for item in s._normalize_string_list(value.get("validations"))
        ],
        "nextStep": s.trim_lines(value.get("nextStep") or value.get("next_step") or "", max_lines=2),
        "updatedAt": str(value.get("updatedAt") or value.get("updated_at") or "").strip(),
    }


def _load_conversations(
    *,
    repair: bool = True,
    agent_by_id: dict[str, dict[str, Any]] | None = None,
    hidden_team_member_agent_ids: set[str] | None = None,
    lightweight: bool = False,
    phase_timings: dict[str, int] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    s = _service()
    wait_started_at = s._perf_counter()
    with s._CHAT_STATE_LOCK, s.chat_state_transaction(s.PROJECT_ROOT):
        if phase_timings is not None:
            phase_timings["chatStateWaitMs"] = s._elapsed_ms(wait_started_at)
        read_started_at = s._perf_counter()
        payload = s.load_chat_state(s.PROJECT_ROOT)
        if phase_timings is not None:
            phase_timings["chatStateReadMs"] = s._elapsed_ms(read_started_at)
        normalize_started_at = s._perf_counter()
        if repair:
            payload = s._repair_stale_running_conversations(payload)
        active_id = str(payload.get("active_conversation_id") or s.DEFAULT_CHAT_CONVERSATION_ID).strip()
        conversations: list[dict[str, Any]] = []
        changed = False
        agent_by_id = agent_by_id if agent_by_id is not None else s._agent_lookup_for_conversations()
        hidden_team_member_agent_ids = (
            hidden_team_member_agent_ids
            if hidden_team_member_agent_ids is not None
            else s._agent_directory_stub_hidden_team_member_ids()
        )
        if repair:
            changed = s._repair_child_root_agent_direct_session_bindings(payload, agent_by_id=agent_by_id) or changed
        for raw in list(payload.get("conversations") or []):
            if repair and isinstance(raw, dict):
                changed = s._ensure_conversation_agent_metadata(raw, agent_by_id=agent_by_id) or changed
                changed = s._ensure_conversation_workspace_metadata(raw) or changed
            conversation = s._normalize_conversation(
                raw,
                agent_by_id=agent_by_id,
                hidden_team_member_agent_ids=hidden_team_member_agent_ids,
                ensure_workspace=repair,
                lightweight=lightweight,
            )
            if conversation is not None:
                conversations.append(conversation)
        if repair and changed:
            payload["updated_at"] = s._now_timestamp()
            s.save_chat_state(s.PROJECT_ROOT, payload)
        if phase_timings is not None:
            phase_timings["conversationNormalizeMs"] = s._elapsed_ms(normalize_started_at)
        return active_id or s.DEFAULT_CHAT_CONVERSATION_ID, conversations


def _append_agent_directory_conversations(
    conversations: list[dict[str, Any]],
    *,
    agent_by_id: dict[str, dict[str, Any]] | None = None,
    hidden_team_member_agent_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    s = _service()
    by_session_id = {
        str(item.get("id") or "").strip(): item
        for item in conversations
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    result = list(conversations)
    try:
        agents = list((agent_by_id if agent_by_id is not None else s._agent_lookup_for_conversations()).values())
    except Exception:
        return result
    hidden_team_member_agent_ids = (
        hidden_team_member_agent_ids
        if hidden_team_member_agent_ids is not None
        else s._agent_directory_stub_hidden_team_member_ids()
    )
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        if str(agent.get("status") or "active").strip().lower() == "archived":
            continue
        session_id = str(agent.get("directSessionId") or "").strip()
        agent_id = str(agent.get("agentId") or "").strip()
        if not session_id or not agent_id or session_id in by_session_id:
            continue
        if s._agent_directory_stub_hidden_from_user_index(agent, hidden_team_member_agent_ids):
            continue
        conversation = s._agent_directory_conversation_stub(
            agent,
            session_id=session_id,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
        )
        result.append(conversation)
        by_session_id[session_id] = conversation
        s._record_agent_directory_conversation_index_event(agent, session_id=session_id)
    return result


def _agent_lookup_for_conversations() -> dict[str, dict[str, Any]]:
    s = _service()
    s._sync_agent_directory_project_root()
    state = s.agent_directory_service.load_state()
    return {
        str(item.get("agentId") or "").strip(): s._conversation_agent_from_state(item)
        for item in state.get("agents") or []
        if isinstance(item, dict) and str(item.get("agentId") or "").strip()
    }


def _empty_direct_agent_session_hidden_from_index(
    conversation: dict[str, Any],
    hidden_team_member_agent_ids: set[str],
) -> bool:
    """Hide stale empty Agent recovery channels while preserving real conversations."""
    s = _service()

    session_id = str(conversation.get("id") or conversation.get("conversation_id") or "").strip()
    if bool(conversation.get("_hasLedgerMessages")):
        return False
    if "_hasLedgerMessages" not in conversation and s._ledger_visible_messages_for_session(session_id):
        return False
    if isinstance(conversation.get("activeTask"), dict) and conversation.get("activeTask"):
        return False
    if str(conversation.get("sessionKind") or "main").strip().lower() != "main":
        return False
    agent = conversation.get("_agent")
    if not isinstance(agent, dict):
        return False
    if not session_id or str(agent.get("directSessionId") or "").strip() != session_id:
        return False
    return s._agent_directory_stub_hidden_from_user_index(agent, hidden_team_member_agent_ids)


def _session_agent_visible_in_indexes(summary: dict[str, Any]) -> bool:
    s = _service()
    conversation_index_kind = str(summary.get("conversationIndexKind") or "").strip()
    conversation_index_visibility = str(summary.get("conversationIndexVisibility") or "").strip()
    experiment_binding = summary.get("experimentBinding") or summary.get("experiment_binding")
    experiment_agent_id = (
        str(experiment_binding.get("agentId") or "").strip()
        if isinstance(experiment_binding, dict)
        else ""
    )
    experiment_bound = bool(
        isinstance(experiment_binding, dict)
        and str(experiment_binding.get("teamId") or "").strip()
        and str(experiment_binding.get("researchProjectId") or "").strip()
        and experiment_agent_id
        and experiment_agent_id == str(summary.get("agentId") or "").strip()
    )
    if str(summary.get("agentStatusCode") or "").strip() == "deleted_agent":
        if bool(summary.get("hiddenFromIndex") or summary.get("hidden_from_index")):
            return False
        return True
    if bool(summary.get("agentMissing")):
        return False
    if conversation_index_kind == s.agent_directory_service.CONVERSATION_INDEX_KIND_INVALID:
        return True
    if conversation_index_visibility == s.agent_directory_service.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE:
        return experiment_bound and not bool(
            summary.get("hiddenFromIndex") or summary.get("hidden_from_index")
        )
    if conversation_index_visibility == s.agent_directory_service.CONVERSATION_INDEX_VISIBILITY_HIDDEN:
        return False
    if conversation_index_kind in {
        s.agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
        s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN,
    }:
        return (
            conversation_index_kind == s.agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT
            and experiment_bound
            and not bool(summary.get("hiddenFromIndex") or summary.get("hidden_from_index"))
        )
    if bool(summary.get("hiddenFromIndex") or summary.get("hidden_from_index")):
        return False
    if str(summary.get("sessionKind") or "").strip().lower() == "child":
        return False
    if str(summary.get("sessionKind") or "").strip().lower() == "supervised":
        return False
    if not bool(str(summary.get("agentId") or "").strip()):
        return True
    return not bool(summary.get("agentMissing"))


def _with_direct_session_agent_for_summary(
    conversation: dict[str, Any],
    *,
    agent_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Attach a direct-session Agent to a lightweight summary copy without repairing state."""
    s = _service()

    session_id = str(conversation.get("id") or conversation.get("conversation_id") or "").strip()
    if not session_id:
        return conversation
    existing_agent_id = str(conversation.get("agentId") or conversation.get("agent_id") or "").strip()
    existing_agent = s._agent_from_lookup(agent_by_id, existing_agent_id) if existing_agent_id else None
    if existing_agent is not None:
        updated = dict(conversation)
        updated["_agent"] = dict(existing_agent)
        updated["_agentLookupChecked"] = True
        return updated
    if existing_agent_id:
        return conversation
    for agent in agent_by_id.values():
        if not isinstance(agent, dict):
            continue
        if str(agent.get("status") or "active").strip().lower() == "archived":
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id or str(agent.get("directSessionId") or "").strip() != session_id:
            continue
        updated = dict(conversation)
        updated["agent_id"] = agent_id
        updated["agentId"] = agent_id
        updated["_agent"] = dict(agent)
        updated["_agentLookupChecked"] = True
        updated["agentMissingId"] = ""
        updated["agentMissing"] = False
        updated["agentStatusCode"] = ""
        updated["agentDirectSessionMismatch"] = False
        updated["agentPrimaryDirectSessionId"] = ""
        return updated
    return conversation


def _timestamp_sort_key(value: str) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _is_default_empty_session_title(title: str) -> bool:
    s = _service()
    normalized = str(title or "").strip()
    return normalized in {s.DEFAULT_CHAT_CONVERSATION_TITLE, "新会话", "New session"}


def _agent_inbox_pending_count_for_summary(agent: dict[str, Any] | None) -> int:
    s = _service()
    if not isinstance(agent, dict):
        return 0
    inbox_path = s.agent_directory_service._agent_workspace_event_path(
        agent,
        "agent_inbox_messages.jsonl",
    )
    return s.agent_directory_service._count_jsonl_matching_status(
        inbox_path,
        status="pending",
    )
