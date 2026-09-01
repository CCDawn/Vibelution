"""Session list/detail DTO projection helpers.

Claim scope: list_sessions / get_session_detail and the summary/detail/cache
composition builders that shape API payloads.

SSE publish lives in ``publish.py``. Hot-path submit/worker/persist stay in
their own packs. Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from core.research.workflow.contracts.discussion_scope import (
    PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND,
)
from core.web.services.session.timebase import parse_timestamp_utc


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
    from . import directory_bridge, directory_runtime

    if directory_runtime.wait_for_directory_startup(
        timeout=directory_runtime.LIST_QUERY_STARTUP_WAIT_SECONDS,
    ) == "starting":
        return []
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

    directory_sessions = None
    try:
        directory_sessions = directory_bridge.list_session_summaries(
            include_hidden=include_hidden_internal,
        )
    except Exception:
        directory_sessions = None
    if directory_sessions is not None:
        s._finish_session_list_cache_build(
            signature=signature,
            sessions=directory_sessions,
            started_at=started_at,
            conversation_count=len(directory_sessions),
            agent_count=0,
        )
        s._record_session_list_loaded_event(
            session_count=len(directory_sessions),
            conversation_count=len(directory_sessions),
            agent_count=0,
            elapsed_ms=s._elapsed_ms(started_at),
            cache_hit=False,
            cache_age_ms=0,
            cache_ttl_ms=int(round(s._SESSION_LIST_CACHE_TTL_SECONDS * 1000)),
            waited_for_inflight=waited_for_inflight,
        )
        return directory_sessions

    try:
        agent_directory_started_at = s._perf_counter()
        agent_by_id = s._agent_lookup_for_conversations()
        hidden_team_member_agent_ids = s._agent_directory_stub_hidden_team_member_ids()
        load_phase_timings: dict[str, int] = {
            "agentDirectoryMs": s._elapsed_ms(agent_directory_started_at),
        }
        _, conversations = s._load_conversations(
            repair=False,
            agent_by_id=agent_by_id,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
            lightweight=True,
            defer_hidden_previews=not include_hidden_internal,
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
        agent_inbox_pending_count_cache: dict[str, int] = {}
        for item in conversations:
            summary = s._build_session_summary(
                item,
                hydrate_agent=False,
                phase_timings=load_phase_timings,
                agent_inbox_pending_count_cache=agent_inbox_pending_count_cache,
            )
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
                -s._timestamp_sort_key(item.get("updatedAt") or item.get("lastActive") or ""),
                # Same-second timestamps must not depend on input order (view
                # switching reshuffles the source rows); fall back to a stable id key.
                str(item.get("id") or ""),
            )
        )
        summary_projection_ms = s._elapsed_ms(summary_projection_started_at)
        published_signature = (
            s._session_list_source_signature(),
            bool(include_hidden_internal),
        )
        s._finish_session_list_cache_build(
            signature=signature,
            sessions=sessions,
            started_at=started_at,
            conversation_count=len(conversations),
            agent_count=len(agent_by_id),
        )
        if published_signature != signature:
            # A standalone SQLite compatibility read may create/retire its WAL
            # after the initial signature was captured. Keep the original key
            # for waiters already sharing this build, and also publish under
            # the post-read key for the immediately following request.
            s._set_session_list_cache(
                sessions,
                now=started_at,
                signature=published_signature,
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
            ledger_tail_ms=load_phase_timings.get("ledgerTailMs"),
            agent_inbox_ms=load_phase_timings.get("agentInboxMs"),
            agent_directory_ms=load_phase_timings.get("agentDirectoryMs"),
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
    include_secondary: Any = True,
    requester: Any = None,
) -> dict | None:
    """Return a session detail payload by persisted conversation id.

    include_secondary=False skips expensive side lists (inbox / governance /
    group context / next-state signals) for high-frequency poll while SSE owns
    the live transcript path.

    ``requester`` optionally declares who is reading (candidate read gate).
    ``None`` keeps the operator-channel default; only candidate hypothesis
    child sessions are gated, so normal sessions are unchanged.
    """
    s = _service()

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    include_secondary_lists = _coerce_include_secondary(include_secondary)
    window_requested = s._session_detail_window_requested(
        message_limit=message_limit,
        before_message_index=before_message_index,
        transcript_scope=transcript_scope,
    )

    # Exact deep links are allowed to recover a real, non-deleted session
    # workspace.  A missing row must not make the client silently switch to an
    # unrelated active conversation.
    agent_by_id = s._agent_lookup_for_conversations()
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
    if conversation is None:
        s._ensure_session_conversation_record(
            normalized_session_id,
            source="session.detail",
        )
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
    if conversation is None:
        fallback = s._agent_directory_session_stub_for_id(normalized_session_id, agent_by_id=agent_by_id)
        if fallback is None:
            return None
        return s._build_session_detail(
            fallback,
            message_limit=message_limit,
            before_message_index=before_message_index,
            transcript_scope=transcript_scope,
            include_secondary=include_secondary_lists,
        )
    from .candidate_read_gate import assert_candidate_session_read

    # Candidate hypothesis read gate: no-op for non-candidate targets and for
    # operator-channel (default) reads; raises before any side effect for a
    # sibling agent read of a candidate child session.
    assert_candidate_session_read(conversation, requester)

    from . import directory_bridge

    directory_bridge.sync_conversation_record(conversation)

    with s._RUNNING_SESSIONS_LOCK:
        active_turn_id = str(s._SESSION_ACTIVE_TURN_IDS.get(normalized_session_id) or "").strip()
        session_running = normalized_session_id in s._RUNNING_SESSION_IDS
    s._reconcile_stale_session_ledger(
        normalized_session_id,
        active_turn_id=active_turn_id if session_running else "",
        reason="detail_loaded_after_restart",
    )
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id) or conversation
    target = s._load_conversation_detail_target(
        normalized_session_id,
        payload={"conversations": [conversation]},
        repair=True,
        persist_session_row=True,
        agent_by_id=agent_by_id,
        lightweight=window_requested,
    )
    if target is not None:
        return s._build_session_detail(
            target,
            message_limit=message_limit,
            before_message_index=before_message_index,
            transcript_scope=transcript_scope,
            include_secondary=include_secondary_lists,
        )
    return None


def _coerce_include_secondary(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"0", "false", "no", "off"}:
        return False
    if text in {"1", "true", "yes", "on"}:
        return True
    return True


def _coerce_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def get_active_session_detail() -> dict | None:
    """Return the current active conversation detail when available."""
    s = _service()

    active_id = str(s.load_active_conversation_id(s.PROJECT_ROOT) or "").strip()
    if not active_id:
        ids = s.list_session_runtime_ids(s.PROJECT_ROOT)
        active_id = str(ids[0] or "").strip() if ids else ""
    if not active_id:
        return None
    return s.get_session_detail(active_id)


def get_active_session_summary() -> dict | None:
    """Return the current active conversation summary for shell-level polling."""
    s = _service()

    agent_by_id = s._agent_lookup_for_conversations()
    active_id, target = s._load_active_conversation_summary_target(agent_by_id=agent_by_id)
    if target is None:
        fallback_id = str(active_id or "").strip()
        if fallback_id:
            s._ensure_agent_directory_conversation_materialized(
                fallback_id,
                source="session.active_summary",
            )
            active_id, target = s._load_active_conversation_summary_target(agent_by_id=agent_by_id)
        if target is None:
            ids = s.list_session_runtime_ids(s.PROJECT_ROOT)
            fallback_id = str(ids[0] or "").strip() if ids else ""
            if fallback_id:
                raw_target = s.load_session_chat_state(s.PROJECT_ROOT, fallback_id)
                if raw_target is not None:
                    target = s._normalize_conversation(
                        raw_target,
                        agent_by_id=agent_by_id,
                        hidden_team_member_agent_ids=s._agent_directory_stub_hidden_team_member_ids(),
                        ensure_workspace=False,
                        lightweight=True,
                    )
                    active_id = fallback_id
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
    include_secondary: bool = True,
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
        include_secondary=include_secondary,
    )


def _build_session_detail_from_summary(
    conversation: dict[str, Any],
    summary: dict[str, Any],
    *,
    hydrate_agent: bool,
    message_limit: Any = None,
    before_message_index: Any = None,
    transcript_scope: Any = "all",
    include_secondary: bool = True,
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
        # Secondary lists are expensive (disk/agent-directory). Poll paths that
        # already own live transcript via SSE should set include_secondary=False.
        "secondaryHydrated": bool(include_secondary and hydrate_agent),
        "nextStateSignals": (
            s._recent_chat_next_state_signal_summaries(conversation["id"], limit=5)
            if hydrate_agent and include_secondary
            else []
        ),
        "groupContextEvents": s.list_group_context_events_for_agent(available_agent_id, limit=8)
        if available_agent_id and hydrate_agent and include_secondary
        else [],
        "agentInboxMessages": s.list_agent_inbox_messages_for_agent(available_agent_id, limit=8, status="pending")
        if available_agent_id and hydrate_agent and include_secondary
        else [],
        "pendingToolGovernanceRequests": s._pending_tool_governance_requests_for_session(available_agent_id)
        if available_agent_id and hydrate_agent and include_secondary
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


def _build_session_summary(
    conversation: dict[str, Any],
    *,
    hydrate_agent: bool = True,
    phase_timings: dict[str, int] | None = None,
    agent_inbox_pending_count_cache: dict[str, int] | None = None,
) -> dict[str, Any]:
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
    # Failed turns persist no error assistant message to the journal anymore, so
    # the last visible message may be a partial reply. Keep the operator-facing
    # task summary on the sanitized failure instead of presenting the partial
    # text as task progress.
    if status == "failed":
        last_turn_error = s._normalize_session_turn_error(
            conversation.get("last_turn_error") or conversation.get("lastTurnError")
        )
        if last_turn_error:
            failure_summary = s._compact_preview_text(
                str(last_turn_error.get("message") or "").strip()
            )
            if failure_summary:
                summary = failure_summary
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
    agent_inbox_started_at = s._perf_counter() if phase_timings is not None else None
    if (
        agent_inbox_pending_count_cache is not None
        and agent_id
        and agent_id in agent_inbox_pending_count_cache
    ):
        agent_inbox_pending_count = agent_inbox_pending_count_cache[agent_id]
    else:
        agent_inbox_pending_count = s._agent_inbox_pending_count_for_summary(agent)
        if agent_inbox_pending_count_cache is not None and agent_id:
            agent_inbox_pending_count_cache[agent_id] = agent_inbox_pending_count
    if phase_timings is not None and agent_inbox_started_at is not None:
        phase_timings["agentInboxMs"] = (
            phase_timings.get("agentInboxMs", 0)
            + s._elapsed_ms(agent_inbox_started_at)
        )
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
    # Keep default placeholders ("新会话" / "New session") so create→rename UX is not
    # prefilled with the Agent display name before the user can type a session title.
    # Agent identity stays on agentDisplayName / icon, not the tab title field.
    if session_kind == "child" or not s._is_default_empty_session_title(task_title):
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
        "createdAt": str(conversation.get("createdAt") or conversation.get("created_at") or "").strip(),
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
    raw_discussion_scope = value.get("discussionScope")
    is_preformal_review = bool(
        isinstance(raw_discussion_scope, dict)
        and str(raw_discussion_scope.get("kind") or "").strip()
        == PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND
    )
    if is_preformal_review:
        if research_project_id or value.get("workflowRunId") or value.get("workflowNodeId"):
            return None
    elif not research_project_id or not agent_id:
        return None
    if not agent_id:
        return None
    try:
        attempt = max(1, int(value.get("attempt") or 1))
    except (TypeError, ValueError):
        attempt = 1
    binding = {
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
    workflow_run_id = str(value.get("workflowRunId") or "").strip()[:160]
    workflow_node_id = str(value.get("workflowNodeId") or "").strip()[:80]
    if bool(workflow_run_id) != bool(workflow_node_id):
        return None
    if workflow_run_id and workflow_node_id:
        binding["workflowRunId"] = workflow_run_id
        binding["workflowNodeId"] = workflow_node_id
    selection_id = str(value.get("selectionId") or "").strip()[:160]
    candidate_id = str(value.get("candidateId") or "").strip()[:160]
    if bool(selection_id) != bool(candidate_id):
        return None
    if selection_id and candidate_id:
        if not is_preformal_review and (not workflow_run_id or not workflow_node_id):
            return None
        binding["selectionId"] = selection_id
        binding["candidateId"] = candidate_id

    raw_scope = value.get("scope")
    if raw_scope is not None:
        if not isinstance(raw_scope, dict):
            return None
        expected_scope = {
            "version": 3,
            "kind": "workflow_candidate" if candidate_id else "workflow_node_root",
            "teamId": binding["teamId"],
            "researchProjectId": research_project_id,
            "agentId": agent_id,
            "workflowRunId": workflow_run_id,
            "workflowNodeId": workflow_node_id,
        }
        if candidate_id:
            expected_scope["selectionId"] = selection_id
            expected_scope["candidateId"] = candidate_id
        if any(raw_scope.get(key) != expected for key, expected in expected_scope.items()):
            return None
        binding["scope"] = expected_scope
    from .discussion_scope_binding import (
        DiscussionScopeBindingError,
        normalize_discussion_scope_binding,
    )

    try:
        binding.update(
            normalize_discussion_scope_binding(
                value,
                team_id=binding["teamId"],
                research_project_id=research_project_id,
                workflow_run_id=workflow_run_id,
                workflow_node_id=workflow_node_id,
                selection_id=selection_id,
                candidate_id=candidate_id,
            )
        )
    except DiscussionScopeBindingError:
        return None
    return binding


def _load_lightweight_conversation_preview(
    conversation_id: str,
    raw_messages: Any,
    *,
    phase_timings: dict[str, int] | None = None,
    ledger_workspace_root: Path | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    s = _service()
    ledger_tail_started_at = s._perf_counter() if phase_timings is not None else None
    messages, has_ledger_messages = s._ledger_latest_preview_messages_for_session(
        conversation_id,
        ledger_workspace_root=ledger_workspace_root,
    )
    if not has_ledger_messages:
        messages = s._normalize_latest_preview_messages(
            conversation_id,
            raw_messages or [],
        )
    if phase_timings is not None and ledger_tail_started_at is not None:
        phase_timings["ledgerTailMs"] = (
            phase_timings.get("ledgerTailMs", 0)
            + s._elapsed_ms(ledger_tail_started_at)
        )
    return list(messages), has_ledger_messages


def _normalize_conversation(
    raw: Any,
    *,
    agent_by_id: dict[str, dict[str, Any]] | None = None,
    hidden_team_member_agent_ids: set[str] | None = None,
    ensure_workspace: bool = True,
    lightweight: bool = False,
    load_message_preview: bool = True,
    phase_timings: dict[str, int] | None = None,
    ledger_workspace_root: Path | None = None,
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
    if lightweight and load_message_preview:
        messages, has_ledger_messages = _load_lightweight_conversation_preview(
            conversation_id,
            raw.get("messages") or [],
            phase_timings=phase_timings,
            ledger_workspace_root=ledger_workspace_root,
        )
        visible_runtime_notices: list[dict[str, Any]] = []
    elif lightweight:
        messages = []
        has_ledger_messages = False
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
        "terminalReason": s._terminal_reason_from_conversation(raw),
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


# Journal tool events are projected as role=assistant shells for process data.
# Only the per-turn timeline target may surface as a bubble host; the rest are air.
_TOOL_EVENT_BUBBLE_KINDS = frozenset(
    {
        "tool_result",
        "tool_call_started",
        "cli_task_result",
        "cli_task_sent",
        "cli_session_lifecycle",
    }
)


def _is_ephemeral_tool_event_bubble(
    raw: dict[str, Any],
    *,
    content: str,
    thought: str,
    mental_snapshot: Any,
    feedback_events: list[Any],
    attachments: list[Any],
    references: list[Any],
) -> bool:
    """True when this row is only a tool journal shell with no user-visible answer text."""

    if str(raw.get("role") or "").strip().lower() != "assistant":
        return False
    if str(content or "").strip() or str(thought or "").strip():
        return False
    if mental_snapshot is not None or feedback_events or attachments or references:
        return False
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    kind = str(metadata.get("kind") or "").strip().lower()
    if kind in _TOOL_EVENT_BUBBLE_KINDS:
        return True
    # Defensive: empty assistant rows that only carry toolCalls and tool-ish kinds.
    tool_calls = raw.get("tool_calls") or raw.get("toolCalls") or raw.get("tools") or []
    if tool_calls and (kind.startswith("tool") or kind.startswith("cli_")):
        return True
    return False


def _merge_assistant_turn_items(
    existing_items: Any,
    incoming_items: Any,
) -> list[dict[str, Any]]:
    """Merge duplicate projections of one turn into one ordered item list."""

    merged_by_key: dict[str, dict[str, Any]] = {}
    insertion_order: dict[str, int] = {}
    for raw_item in [*list(existing_items or []), *list(incoming_items or [])]:
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        key = str(item.get("itemId") or item.get("id") or "").strip()
        if not key:
            key = "|".join(
                [
                    str(item.get("type") or ""),
                    str(item.get("callId") or ""),
                    str(item.get("sequence") or ""),
                    str(len(insertion_order)),
                ]
            )
        if key not in insertion_order:
            insertion_order[key] = len(insertion_order)
        previous = merged_by_key.get(key)
        if previous is None:
            merged_by_key[key] = item
            continue
        richer = dict(previous)
        richer.update(item)
        for field in ("text", "input", "output", "summary"):
            previous_text = str(previous.get(field) or "")
            incoming_text = str(item.get(field) or "")
            if len(previous_text) > len(incoming_text):
                richer[field] = previous_text
        richer["sequence"] = max(
            int(previous.get("sequence") or 0),
            int(item.get("sequence") or 0),
        )
        merged_by_key[key] = richer
    return [
        item
        for key, item in sorted(
            merged_by_key.items(),
            key=lambda pair: (
                int(pair[1].get("sequence") or 0),
                insertion_order[pair[0]],
            ),
        )
    ]


def _coalesce_assistant_messages_by_turn(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose exactly one assistant message for each canonical turn."""

    result: list[dict[str, Any]] = []
    assistant_index_by_turn: dict[str, int] = {}
    for raw_message in messages:
        message = dict(raw_message)
        if str(message.get("role") or "") != "assistant":
            result.append(message)
            continue
        turn_id = str(message.get("turnId") or "").strip()
        if not turn_id or turn_id not in assistant_index_by_turn:
            if turn_id:
                assistant_index_by_turn[turn_id] = len(result)
            result.append(message)
            continue
        target_index = assistant_index_by_turn[turn_id]
        existing = dict(result[target_index])
        existing["turnItems"] = _merge_assistant_turn_items(
            existing.get("turnItems"),
            message.get("turnItems"),
        )
        existing_metadata = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}
        incoming_metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        existing["metadata"] = {**existing_metadata, **incoming_metadata}
        if str(message.get("timestamp") or "") > str(existing.get("timestamp") or ""):
            existing["timestamp"] = message["timestamp"]
        if str(message.get("status") or "") in {"running", "failed"}:
            existing["status"] = message["status"]
        result[target_index] = existing
    return result


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
    # Always compute per-turn hosts so tool-event air bubbles can be collapsed even
    # when timeline/transcript enrichment is disabled for a payload window.
    timeline_target_indices = s._assistant_timeline_target_indices(
        raw_items,
        source_start_index=normalized_start_index,
    )
    client_submission_id_by_turn: dict[str, str] = {}
    for raw in raw_items:
        if not isinstance(raw, dict) or str(raw.get("role") or "").strip().lower() != "user":
            continue
        turn_id = s._message_turn_id(raw)
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        client_submission_id = str(
            metadata.get("clientSubmissionId")
            or metadata.get("client_submission_id")
            or ""
        ).strip()
        if turn_id and client_submission_id:
            client_submission_id_by_turn[turn_id] = client_submission_id
    messages: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_items, start=normalized_start_index):
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        raw_metadata = raw.get("metadata")
        is_context_compression_marker = (
            role == "assistant"
            and isinstance(raw_metadata, dict)
            and str(raw_metadata.get("kind") or "").strip() == "context_compression_marker"
        )
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
        if (
            not content
            and not thought
            and mental_snapshot is None
            and not tool_calls
            and not feedback_events
            and not attachments
            and not references
            and not is_context_compression_marker
        ):
            continue
        # Mature chat list: one process host per turn (timeline target). Intermediate
        # tool_result shells are process data, not empty avatar bubbles.
        turn_id = s._message_turn_id(raw)
        if _is_ephemeral_tool_event_bubble(
            raw,
            content=content,
            thought=thought or "",
            mental_snapshot=mental_snapshot,
            feedback_events=feedback_events,
            attachments=attachments,
            references=references,
        ):
            if not turn_id or timeline_target_indices.get(turn_id) != index:
                continue
        entry: dict[str, Any] = {
            "id": f"{conversation_id}-message-{index}",
            "role": role,
            "content": content,
            "timestamp": str(raw.get("timestamp") or "").strip(),
        }
        turn_items: list[dict[str, Any]] = []
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
                # Keep process/commentary from the ledger, but still project the committed
                # final answer when no remaining assistant_text covers it. Otherwise short
                # orphan capture fragments or intermediate commentary alone suppress the
                # real answer in the UI (timeline owns assistant_text; response is hidden).
                include_assistant_text = not s._assistant_timeline_covers_final_content(
                    timeline_feedback_events,
                    content,
                )
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
            is_streaming_message = bool(raw.get("streaming"))
            is_terminal_error_message = (
                role == "assistant"
                and isinstance(raw_metadata, dict)
                and (
                    str(raw_metadata.get("kind") or "").strip() == "turn_error"
                    or raw_metadata.get("providerFailure") is True
                )
            )
            # Phase A: assistant messages always carry SessionTurnItem v2 as the UI
            # source of truth. codexTranscript is a one-way renderer projection.
            # Window payloads slim heavy diagnostics but never drop final-answer text.
            should_build_full_codex_transcript = (
                normalized_transcript_scope == "all"
                or is_streaming_message
                or is_terminal_error_message
            )
            codex_transcript = None
            if should_build_full_codex_transcript:
                codex_transcript = s._build_codex_transcript_projection(
                    message_id=entry["id"],
                    role=role,
                    content=content,
                    feedback_events=timeline_feedback_events,
                    tool_calls=tool_calls,
                    streaming=is_streaming_message,
                )
            if role == "assistant":
                turn_items = s._build_session_turn_items_projection(
                    session_id=conversation_id,
                    turn_id=turn_id,
                    message_id=entry["id"],
                    content=content,
                    thought=thought,
                    mental_snapshot=mental_snapshot,
                    codex_transcript=codex_transcript,
                    done=not is_streaming_message,
                    source="session_detail",
                    metadata=raw_metadata if isinstance(raw_metadata, dict) else {},
                    stage=raw.get("streamStage"),
                )
                if (
                    turn_items
                    and normalized_transcript_scope == "window"
                    and not is_streaming_message
                ):
                    turn_items = s._slim_session_turn_items_for_window_payload(turn_items)
                if turn_items:
                    entry["turnItems"] = turn_items
                if is_terminal_error_message:
                    terminal_error_item = s._terminal_error_turn_item(turn_items)
                    if terminal_error_item:
                        codex_transcript = s._build_terminal_error_codex_transcript_projection(
                            message_id=entry["id"],
                            error_item=terminal_error_item,
                        )
            if (
                codex_transcript
                and normalized_transcript_scope == "window"
                and not is_streaming_message
            ):
                codex_transcript = s._slim_codex_transcript_for_window_payload(codex_transcript)
            # Prefer transcript derived from turnItems (single package → cells).
            if (
                role == "assistant"
                and turn_items
                and (
                    not codex_transcript
                    or (
                        normalized_transcript_scope == "window"
                        and not is_streaming_message
                        and not is_terminal_error_message
                    )
                )
            ):
                derived = s._build_codex_transcript_from_turn_items(
                    message_id=entry["id"],
                    turn_items=turn_items,
                    streaming=is_streaming_message,
                    window_slimmed=normalized_transcript_scope == "window" and not is_streaming_message,
                )
                if derived:
                    codex_transcript = derived
            if (
                role == "assistant"
                and not codex_transcript
                and content
                and normalized_transcript_scope == "window"
                and not is_streaming_message
                and not is_terminal_error_message
            ):
                codex_transcript = s._build_window_final_answer_transcript(
                    message_id=entry["id"],
                    content=content,
                )
            # `codex_transcript` is deliberately not serialized.  It used to be
            # a second assistant representation; the web renderer now derives
            # cells locally from `turnItems`.
        if attachments:
            entry["attachments"] = attachments
        if references:
            entry["references"] = references
        metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        if role == "assistant" and turn_id:
            client_submission_id = client_submission_id_by_turn.get(turn_id, "")
            if client_submission_id:
                metadata.setdefault("clientSubmissionId", client_submission_id)
        if isinstance(metadata, dict) and metadata:
            entry["metadata"] = dict(metadata)
            if role == "assistant" and str(metadata.get("kind") or "").strip() == "turn_error":
                entry["content"] = s._complete_turn_error_visible_content(entry["content"], metadata)
        if role == "assistant":
            if not turn_items:
                turn_items = s._build_session_turn_items_projection(
                    session_id=conversation_id,
                    turn_id=turn_id,
                    message_id=entry["id"],
                    content=content,
                    thought=thought,
                    mental_snapshot=mental_snapshot,
                    done=not bool(raw.get("streaming")),
                    source="session_detail",
                    metadata=raw_metadata if isinstance(raw_metadata, dict) else {},
                    stage=raw.get("streamStage"),
                )
            assistant_status = (
                "running"
                if bool(raw.get("streaming"))
                else "failed"
                if isinstance(raw_metadata, dict)
                and (
                    str(raw_metadata.get("kind") or "").strip() == "turn_error"
                    or raw_metadata.get("providerFailure") is True
                )
                else "completed"
            )
            entry = {
                "id": entry["id"],
                "role": "assistant",
                "timestamp": entry["timestamp"],
                "turnId": turn_id,
                "status": assistant_status,
                "turnItems": turn_items,
                "metadata": dict(metadata) if isinstance(metadata, dict) else {},
            }
        messages.append(entry)
    return _coalesce_assistant_messages_by_turn(s._dedupe_turn_error_messages(messages))


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


def _stamp_turn_items_message_id(items: list[dict[str, Any]], message_id: str) -> list[dict[str, Any]]:
    normalized_message_id = str(message_id or "").strip()
    if not normalized_message_id:
        return list(items or [])
    stamped: list[dict[str, Any]] = []
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        next_item = dict(item)
        if not str(next_item.get("messageId") or "").strip():
            next_item["messageId"] = normalized_message_id
        stamped.append(next_item)
    return stamped


def _is_session_turn_final_answer_item(item: Mapping[str, Any] | None) -> bool:
    if not isinstance(item, Mapping):
        return False
    kind = str(item.get("kind") or item.get("type") or "").strip().lower()
    channel = str(item.get("channel") or "").strip().lower()
    phase = str(item.get("phase") or "").strip().lower()
    if phase in {"commentary", "interim"}:
        return False
    return phase == "final_answer" or (
        kind in {"assistant_message", "agent_message"}
        and channel in {"", "answer"}
    )


def _is_committed_session_turn_final_answer_item(item: Mapping[str, Any] | None) -> bool:
    if not _is_session_turn_final_answer_item(item):
        return False
    assert isinstance(item, Mapping)
    if item.get("provisional") is True:
        return False
    status = str(item.get("status") or "").strip().lower()
    return item.get("terminal") is True or status in {"completed", "done", "failed"}


def _is_session_turn_reasoning_item(item: Mapping[str, Any] | None) -> bool:
    if not isinstance(item, Mapping):
        return False
    kind = str(item.get("kind") or item.get("type") or "").strip().lower()
    phase = str(item.get("phase") or "").strip().lower()
    channel = str(item.get("channel") or "").strip().lower()
    return kind in {"reasoning", "analysis"} or phase == "reasoning" or channel in {"analysis", "reasoning"}


def _is_session_turn_commentary_item(item: Mapping[str, Any] | None) -> bool:
    """Commentary rows also carry thought text (protocol commits tool-lead text as commentary)."""
    if not isinstance(item, Mapping):
        return False
    kind = str(item.get("kind") or item.get("type") or "").strip().lower()
    phase = str(item.get("phase") or "").strip().lower()
    channel = str(item.get("channel") or "").strip().lower()
    return kind == "commentary" or phase in {"commentary", "interim"} or channel in {"commentary", "interim"}


# Stages where the model is still (or about to start) thinking. Once the stream
# moves past these (answer/tool/terminal), the reasoning row is done even though
# the turn itself has not committed yet.
_SESSION_TURN_THINKING_STAGES = {
    "model_thinking",
    "server_thinking",
    "thinking",
    "reasoning",
    "model_request",
    "agent_prepare",
    "user_submit",
    "context_prepare",
    "prepare",
    "request",
}


def _session_turn_stage_past_thinking(stage: Any) -> bool:
    normalized = str(stage or "").strip().lower()
    if not normalized:
        return False
    return normalized not in _SESSION_TURN_THINKING_STAGES


def _build_session_turn_reasoning_item(
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    thought: Any,
    done: bool = False,
    source: str = "assistant_delta",
    sequence: int = 0,
) -> dict[str, Any] | None:
    """Build a SessionTurnItem v2 reasoning row from live/durable thought text."""
    s = _service()
    thought_text = s._sanitize_thought_text(thought)
    if not thought_text:
        return None
    reasoning_id = f"{s._session_turn_item_base_id(session_id, turn_id or 'turn')}-reasoning"
    return s._compact_codex_record(
        {
            "version": 2,
            "id": f"{reasoning_id}:0",
            "itemId": reasoning_id,
            "type": "reasoning",
            "kind": "reasoning",
            "channel": "analysis",
            "phase": "reasoning",
            "status": "completed" if done else "in_progress",
            "provisional": not bool(done),
            "terminal": False,
            "revision": 0,
            "sequence": max(0, int(sequence or 0)),
            "sessionId": str(session_id or "").strip(),
            "turnId": str(turn_id or "").strip(),
            "messageId": str(message_id or "").strip(),
            "source": source,
            "protocol": "session_detail",
            "text": thought_text,
        }
    )


def _merge_live_thought_into_turn_items(
    items: list[dict[str, Any]],
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    thought: Any = "",
    done: bool = False,
    source: str = "assistant_delta",
    stage: Any = "",
) -> list[dict[str, Any]]:
    """Keep journal package authority while bridging live/durable thought as reasoning.

    Wire/journal often commits final_answer without a reasoning item even when the turn
    streamed thought. Without this bridge, package_cells drops thinking the moment the
    journal final answer lands (turnItemCount collapses to answer-only).

    Segment lifecycle: the reasoning row must settle to ``completed`` the moment the
    stream leaves the thinking stage (answer/tool delta), not wait for the turn-level
    ``done``. Otherwise the UI keeps the thinking spinner after the thought segment
    finished streaming.
    """
    s = _service()
    merged = [dict(item) for item in list(items or []) if isinstance(item, dict)]
    thought_text = s._sanitize_thought_text(thought)
    if not thought_text:
        return merged

    reasoning_index = next(
        (index for index, item in enumerate(merged) if _is_session_turn_reasoning_item(item)),
        -1,
    )
    if reasoning_index >= 0:
        existing = merged[reasoning_index]
        existing_text = str(existing.get("text") or existing.get("summary") or "").strip()
        # Prefer longer live thought while the reasoning row is still provisional/streaming.
        existing_status = str(existing.get("status") or "").strip().lower()
        can_extend = (
            existing.get("provisional") is True
            or existing_status in {"", "pending", "running", "in_progress", "streaming"}
        )
        thought_done = bool(done) or _session_turn_stage_past_thinking(stage)
        if thought_done and can_extend and existing_status not in {"completed", "done", "success"}:
            # The stream already moved past thinking: close the reasoning row so the
            # segment spinner stops with the thought content, independent of turn done.
            next_item = dict(existing)
            next_item["status"] = "completed"
            next_item["provisional"] = False
            merged[reasoning_index] = s._compact_codex_record(next_item)
            return merged
        if (
            can_extend
            and len(thought_text) > len(existing_text)
            and (
                not existing_text
                or thought_text.startswith(existing_text)
                or existing_text in thought_text
            )
        ):
            next_item = dict(existing)
            next_item["text"] = thought_text
            next_item["status"] = "completed" if thought_done else (existing_status or "in_progress")
            next_item["provisional"] = not bool(done)
            if not str(next_item.get("messageId") or "").strip():
                next_item["messageId"] = str(message_id or "").strip()
            if not str(next_item.get("source") or "").strip():
                next_item["source"] = source
            merged[reasoning_index] = s._compact_codex_record(next_item)
        return merged

    # No reasoning row: a protocol commentary row may already carry the same
    # thought text (tool-lead summaries). Merge the complete live thought into
    # it instead of creating a second reasoning item — otherwise the UI paints
    # the same thinking twice (reasoning_summary + commentary cells).
    commentary_index = next(
        (index for index, item in enumerate(merged) if _is_session_turn_commentary_item(item)),
        -1,
    )
    if commentary_index >= 0:
        existing = merged[commentary_index]
        existing_text = str(existing.get("text") or existing.get("summary") or "").strip()
        existing_status = str(existing.get("status") or "").strip().lower()
        thought_overlaps_commentary = (
            not existing_text
            or thought_text == existing_text
            or thought_text.startswith(existing_text)
            or existing_text in thought_text
            or existing_text.startswith(thought_text)
        )
        if thought_overlaps_commentary and len(thought_text) >= len(existing_text):
            next_item = dict(existing)
            next_item["text"] = thought_text
            # Committed/terminal commentary keeps its final state; streaming rows
            # settle with the segment lifecycle.
            if existing_status not in {"completed", "done", "success", "failed", "degraded"}:
                next_item["status"] = "completed" if (done or _session_turn_stage_past_thinking(stage)) else (
                    existing_status or "in_progress"
                )
                next_item["provisional"] = not bool(done)
            if not str(next_item.get("messageId") or "").strip():
                next_item["messageId"] = str(message_id or "").strip()
            if not str(next_item.get("source") or "").strip():
                next_item["source"] = source
            merged[commentary_index] = s._compact_codex_record(next_item)
            return merged

    reasoning_item = _build_session_turn_reasoning_item(
        session_id=session_id,
        turn_id=turn_id,
        message_id=message_id,
        thought=thought_text,
        done=bool(done) or _session_turn_stage_past_thinking(stage),
        source=source,
        sequence=0,
    )
    if reasoning_item is None:
        return merged
    # Reasoning belongs before tools/answer so chrono rails stay thought → work → answer.
    return [reasoning_item, *merged]


def _merge_live_content_into_turn_items(
    items: list[dict[str, Any]],
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    content: Any = "",
    done: bool = False,
    source: str = "assistant_delta",
) -> list[dict[str, Any]]:
    """Keep journal/tool package authority while bridging live content into the same track.

    When journal already has process items (tools/status) but no covering final_answer yet,
    streaming content must still appear as a provisional final_answer item so live overlay
    and assistant_delta share the package_cells path with settled detail.
    """
    s = _service()
    merged = [dict(item) for item in list(items or []) if isinstance(item, dict)]
    content_text = s._sanitize_message_content("assistant", content)
    if not content_text:
        return merged

    final_index = next(
        (index for index, item in enumerate(merged) if _is_session_turn_final_answer_item(item)),
        -1,
    )
    if final_index >= 0:
        final_item = merged[final_index]
        if _is_committed_session_turn_final_answer_item(final_item):
            # Committed journal final answer remains the sole authority. Some
            # providers commit their last commentary segment again as the final
            # answer; keep the answer and remove only that exact duplicate.
            final_text_key = s._assistant_projection_text_key(
                final_item.get("text") or final_item.get("summary") or ""
            )
            if not final_text_key:
                return merged
            return [
                item
                for index, item in enumerate(merged)
                if index == final_index
                or not (
                    _is_session_turn_commentary_item(item)
                    and s._assistant_projection_text_key(
                        item.get("text") or item.get("summary") or ""
                    )
                    == final_text_key
                )
            ]
        item_text = str(final_item.get("text") or "").strip()
        if (
            len(content_text) > len(item_text)
            and (
                not item_text
                or content_text.startswith(item_text)
                or item_text in content_text
            )
        ):
            next_item = dict(final_item)
            next_item["text"] = content_text
            next_item["status"] = "completed" if done else "in_progress"
            next_item["provisional"] = not bool(done)
            next_item["terminal"] = bool(done)
            if not str(next_item.get("messageId") or "").strip():
                next_item["messageId"] = str(message_id or "").strip()
            if not str(next_item.get("source") or "").strip():
                next_item["source"] = source
            merged[final_index] = s._compact_codex_record(next_item)
        return merged

    content_key = s._assistant_projection_text_key(content_text)
    if content_key:
        for item in merged:
            if not _is_session_turn_commentary_item(item):
                continue
            commentary_text = s._sanitize_message_content(
                "assistant",
                item.get("text") or item.get("summary") or "",
            )
            commentary_key = s._assistant_projection_text_key(commentary_text)
            if not commentary_key:
                continue
            # Responses-style providers expose the latest commentary segment as
            # live ``content`` until a distinct final-answer segment arrives.
            # Mirroring that envelope into a provisional final row renders the
            # same text twice and later replaces the active row identity.  A
            # shorter live prefix is covered by the committed commentary too;
            # content that extends beyond commentary remains eligible to bridge.
            if content_key == commentary_key or (
                len(content_key) >= 24 and content_key in commentary_key
            ):
                return merged

    item_id = s._session_turn_agent_message_item_id(session_id, turn_id or "turn")
    sequence = max(
        (int(item.get("sequence") or 0) for item in merged),
        default=0,
    ) + 1
    merged.append(
        s._compact_codex_record(
            {
                "version": 2,
                "id": f"{item_id}:0",
                "itemId": item_id,
                "type": "assistant_message",
                "kind": "assistant_message",
                "channel": "answer",
                "phase": "final_answer",
                "status": "completed" if done else "in_progress",
                "provisional": not bool(done),
                "terminal": bool(done),
                "revision": 0,
                "sequence": sequence,
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "messageId": str(message_id or "").strip(),
                "source": source,
                "protocol": "session_detail",
                "text": content_text,
            }
        )
    )
    return merged


def _merge_live_tool_start_metadata_into_turn_items(
    items: list[dict[str, Any]],
    codex_transcript: dict[str, Any] | None,
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    source: str,
) -> list[dict[str, Any]]:
    """Merge executor-only live tool facts into a canonical journal package.

    The journal remains authoritative for item identity, order, and status.  The
    executor start epoch is captured before execution and can arrive only on the
    live tool revision. A just-started call may also be newer than the cached
    journal projection, so append only that missing live call by stable callId.
    """
    s = _service()
    transcript_cells = list((codex_transcript or {}).get("cells") or [])
    live_cell_by_call_id: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, cell in enumerate(transcript_cells, start=1):
        if not isinstance(cell, dict):
            continue
        call_id = str(cell.get("callId") or "").strip()
        if call_id:
            live_cell_by_call_id[call_id] = (index, cell)
    if not live_cell_by_call_id:
        return items

    merged: list[dict[str, Any]] = []
    existing_call_ids: set[str] = set()
    for raw in items:
        item = dict(raw)
        call_id = str(item.get("callId") or "").strip()
        if call_id:
            existing_call_ids.add(call_id)
        live_cell = live_cell_by_call_id.get(call_id, (0, {}))[1]
        exact_start = s._coerce_tool_number(
            live_cell.get("executionStartedAtEpochMs")
            or live_cell.get("execution_started_at_epoch_ms")
        )
        if exact_start is not None and exact_start > 0:
            metadata = dict(item.get("metadata") or {}) if isinstance(item.get("metadata"), dict) else {}
            metadata["executionStartedAtEpochMs"] = exact_start
            item["metadata"] = metadata
        merged.append(item)

    for call_id, (index, cell) in live_cell_by_call_id.items():
        if call_id in existing_call_ids:
            continue
        live_item = s._session_turn_item_from_codex_cell(
            session_id=session_id,
            turn_id=turn_id,
            message_id=message_id,
            cell=cell,
            index=index,
            source=source,
        )
        if live_item and str(live_item.get("type") or "").strip() == "tool_call":
            live_item["sequence"] = max(
                s._coerce_nonnegative_int(live_item.get("sequence")),
                max((s._coerce_nonnegative_int(item.get("sequence")) for item in merged), default=0) + 1,
            )
            merged.append(live_item)
    return merged


def _merge_live_reasoning_cells_into_turn_items(
    items: list[dict[str, Any]],
    codex_transcript: dict[str, Any] | None,
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    source: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Merge each feedback reasoning segment by stable identity, never as one turn blob."""

    s = _service()
    merged = [dict(item) for item in list(items or []) if isinstance(item, dict)]
    reasoning_cells = [
        (index, cell)
        for index, cell in enumerate(list((codex_transcript or {}).get("cells") or []), start=1)
        if isinstance(cell, dict) and str(cell.get("kind") or "").strip() == "reasoning_summary"
    ]
    if not reasoning_cells:
        return merged, False

    next_sequence = max((s._coerce_nonnegative_int(item.get("sequence")) for item in merged), default=0)
    for index, cell in reasoning_cells:
        live_item = s._session_turn_item_from_codex_cell(
            session_id=session_id,
            turn_id=turn_id,
            message_id=message_id,
            cell=cell,
            index=index,
            source=source,
        )
        if not live_item:
            continue
        feedback_sequence = s._coerce_nonnegative_int(cell.get("sequence") or index)
        item_id = f"{s._session_turn_item_base_id(session_id, turn_id)}-reasoning-{feedback_sequence}"
        live_item["id"] = f"{item_id}:{s._coerce_nonnegative_int(live_item.get('revision'))}"
        live_item["itemId"] = item_id
        live_text = str(live_item.get("text") or live_item.get("summary") or "").strip()
        existing_index = next(
            (
                item_index
                for item_index, item in enumerate(merged)
                if str(item.get("itemId") or item.get("id") or "").split(":", 1)[0] == item_id
            ),
            -1,
        )
        if existing_index >= 0:
            existing = merged[existing_index]
            existing_text = str(existing.get("text") or existing.get("summary") or "").strip()
            if (
                s._coerce_nonnegative_int(live_item.get("revision"))
                > s._coerce_nonnegative_int(existing.get("revision"))
                or len(live_text) > len(existing_text)
            ):
                live_item["sequence"] = existing.get("sequence")
                merged[existing_index] = live_item
            continue
        live_text_key = s._assistant_projection_text_key(live_text)
        if live_text_key and any(
            _is_session_turn_reasoning_item(item)
            and s._assistant_projection_text_key(item.get("text") or item.get("summary") or "") == live_text_key
            for item in merged
        ):
            continue
        next_sequence += 1
        live_item["sequence"] = next_sequence
        merged.append(live_item)
    return merged, True


def _build_session_turn_items_projection(
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    content: Any = "",
    thought: Any = "",
    mental_snapshot: Mapping[str, Any] | None = None,
    codex_transcript: dict[str, Any] | None = None,
    done: bool = False,
    source: str = "assistant_delta",
    metadata: Mapping[str, Any] | None = None,
    stage: Any = "",
) -> list[dict[str, Any]]:
    """Project SessionTurnItem v2 for a turn.

    Prefer journal assistant_item_committed records (canonical). Fall back to a
    deterministic final_answer item from content so window/detail always have a
    single UI source of truth for the committed body.
    """
    s = _service()
    normalized_metadata = dict(metadata or {})
    normalized_turn_id = str(
        turn_id
        or normalized_metadata.get("turnId")
        or normalized_metadata.get("turn_id")
        or ""
    ).strip()
    normalized_message_id = str(message_id or "").strip()
    if str(normalized_metadata.get("kind") or "").strip() == "context_compression_marker":
        marker_status = str(normalized_metadata.get("status") or "").strip()
        marker_title = str(normalized_metadata.get("title") or "").strip()
        marker_detail = str(normalized_metadata.get("detail") or "").strip()
        event_id = str(normalized_metadata.get("eventId") or "").strip()
        item_id = (
            f"{s._session_turn_item_base_id(session_id, normalized_turn_id or 'context-compression')}"
            f"-context-compression-{event_id or marker_status or 'marker'}"
        )
        return _canonicalize_session_turn_items_for_protocol(
            [
                {
                    "id": item_id,
                    "itemId": item_id,
                    "version": 2,
                    "sessionId": session_id,
                    "turnId": normalized_turn_id,
                    "messageId": normalized_message_id,
                    "type": "status",
                    "status": "failed" if marker_status == "failed_preserved" else "completed",
                    "revision": 0,
                    "sequence": 1,
                    "terminal": True,
                    "code": f"context_compression_{marker_status or 'marker'}",
                    "title": marker_title or "上下文压缩",
                    "text": marker_detail or marker_title or "上下文压缩状态已更新",
                    "diagnosticSummary": {
                        "kind": "context_compression_marker",
                        "status": marker_status or "marker",
                    },
                    "metadata": normalized_metadata,
                    "source": source,
                }
            ],
            session_id=session_id,
            turn_id=normalized_turn_id,
        )
    # Require turn_id for journal projection so we never return other turns' items.
    if normalized_turn_id:
        canonical_items = s.conversation_turn_items_from_events(
            s._load_session_conversation_events_cached(str(session_id or "").strip()),
            turn_id=normalized_turn_id,
        )
        if canonical_items:
            stamped = s._stamp_turn_items_message_id(canonical_items, normalized_message_id)
            stamped = _merge_live_tool_start_metadata_into_turn_items(
                stamped,
                codex_transcript,
                session_id=session_id,
                turn_id=normalized_turn_id,
                message_id=normalized_message_id,
                source=source,
            )
            stamped, has_reasoning_cells = _merge_live_reasoning_cells_into_turn_items(
                stamped,
                codex_transcript,
                session_id=session_id,
                turn_id=normalized_turn_id,
                message_id=normalized_message_id,
                source=source,
            )
            merged = _merge_live_content_into_turn_items(
                stamped,
                session_id=session_id,
                turn_id=normalized_turn_id,
                message_id=normalized_message_id,
                content=content,
                done=done,
                source=source,
            )
            # Legacy sources without segment cells still need the aggregate bridge.
            if not has_reasoning_cells:
                merged = _merge_live_thought_into_turn_items(
                    merged,
                    session_id=session_id,
                    turn_id=normalized_turn_id,
                    message_id=normalized_message_id,
                    thought=thought,
                    done=done,
                    source=source,
                    stage=stage,
                )
            return _canonicalize_session_turn_items_for_protocol(
                merged,
                session_id=session_id,
                turn_id=normalized_turn_id,
            )
    if (
        str(normalized_metadata.get("kind") or "").strip() == "turn_error"
        or normalized_metadata.get("providerFailure") is True
    ):
        return _canonicalize_session_turn_items_for_protocol(
            [
                s._build_terminal_error_turn_item(
                    session_id=session_id,
                    turn_id=normalized_turn_id,
                    message_id=message_id,
                    content=content,
                    metadata=normalized_metadata,
                )
            ],
            session_id=session_id,
            turn_id=normalized_turn_id,
        )
    if not normalized_message_id:
        return []
    transcript_cells = list((codex_transcript or {}).get("cells") or [])
    has_transcript_reasoning = any(
        isinstance(cell, dict) and str(cell.get("kind") or "").strip() == "reasoning_summary"
        for cell in transcript_cells
    )
    content_text = s._sanitize_message_content("assistant", content)
    assistant_markdown_text = s._session_turn_assistant_markdown_text(transcript_cells)
    thought_text = s._sanitize_message_content("assistant", thought)
    items: list[dict[str, Any]] = []
    # Prefer explicit final_answer cells from transcript over raw content when present.
    final_cell_text = ""
    for cell in transcript_cells:
        if not isinstance(cell, dict):
            continue
        if str(cell.get("kind") or "").strip() != "assistant_markdown":
            continue
        phase = str(cell.get("phase") or "").strip().lower()
        if phase == "commentary" or phase == "interim":
            continue
        text = str(cell.get("text") or cell.get("markdown") or "").strip()
        if phase == "final_answer" or cell.get("terminal") is True:
            final_cell_text = text
            break
        if not final_cell_text and text:
            final_cell_text = text
    agent_text = content_text or final_cell_text or assistant_markdown_text
    if agent_text:
        item_id = s._session_turn_agent_message_item_id(session_id, normalized_turn_id or "turn")
        items.append(
            s._compact_codex_record(
                {
                    "version": 2,
                    "id": f"{item_id}:0",
                    "itemId": item_id,
                    "type": "assistant_message",
                    "kind": "assistant_message",
                    "channel": "answer",
                    "phase": "final_answer",
                    "status": "completed" if done else "in_progress",
                    "provisional": not bool(done),
                    "terminal": bool(done),
                    "revision": 0,
                    "sequence": 1,
                    "sessionId": str(session_id or "").strip(),
                    "turnId": normalized_turn_id,
                    "messageId": normalized_message_id,
                    "source": source,
                    "protocol": "session_detail",
                    "text": agent_text,
                }
            )
        )
    if thought_text and not has_transcript_reasoning:
        reasoning_id = f"{s._session_turn_item_base_id(session_id, normalized_turn_id or 'turn')}-reasoning"
        items.append(
            s._compact_codex_record(
                {
                    "version": 2,
                    "id": f"{reasoning_id}:0",
                    "itemId": reasoning_id,
                    "type": "reasoning",
                    "kind": "reasoning",
                    "channel": "analysis",
                    "phase": "reasoning",
                    "status": "completed"
                    if (done or _session_turn_stage_past_thinking(stage) or bool(agent_text))
                    else "in_progress",
                    "provisional": not bool(done),
                    "terminal": False,
                    "revision": 0,
                    "sequence": 0,
                    "sessionId": str(session_id or "").strip(),
                    "turnId": normalized_turn_id,
                    "messageId": normalized_message_id,
                    "source": source,
                    "protocol": "session_detail",
                    "text": thought_text,
                }
            )
        )
    normalized_mental_snapshot = s._normalize_mental_snapshot(mental_snapshot)
    if normalized_mental_snapshot is not None:
        mental_item_id = f"{s._session_turn_item_base_id(session_id, normalized_turn_id or 'turn')}-mental"
        mental_summary = s._sanitize_message_content(
            "assistant",
            normalized_mental_snapshot.get("summary")
            or normalized_mental_snapshot.get("feeling")
            or normalized_mental_snapshot.get("whisper")
            or normalized_mental_snapshot.get("mood")
            or "Mental state updated.",
        )
        items.append(
            s._compact_codex_record(
                {
                    "version": 2,
                    "id": f"{mental_item_id}:0",
                    "itemId": mental_item_id,
                    "type": "status",
                    "kind": "status",
                    "code": "mental_snapshot",
                    "title": "Mental state",
                    "status": "completed" if done else "running",
                    "provisional": not bool(done),
                    "terminal": False,
                    "revision": 0,
                    "sequence": 1,
                    "sessionId": str(session_id or "").strip(),
                    "turnId": normalized_turn_id,
                    "messageId": normalized_message_id,
                    "source": source,
                    "protocol": "session_detail",
                    "text": mental_summary,
                    "mentalSnapshot": normalized_mental_snapshot,
                }
            )
        )
    for index, cell in enumerate(transcript_cells, start=1):
        if not isinstance(cell, dict):
            continue
        cell_kind = str(cell.get("kind") or "").strip()
        # A stream tail was only a renderer placeholder for the retired
        # transcript envelope.  The running status item is the authoritative
        # progress signal now, so emitting both would show duplicate spinners.
        if cell_kind == "stream_tail":
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
            if cell_kind == "reasoning_summary":
                feedback_sequence = s._coerce_nonnegative_int(cell.get("sequence") or index)
                item_id = (
                    f"{s._session_turn_item_base_id(session_id, normalized_turn_id or 'turn')}"
                    f"-reasoning-{feedback_sequence}"
                )
                item["id"] = f"{item_id}:{s._coerce_nonnegative_int(item.get('revision'))}"
                item["itemId"] = item_id
            # Promote legacy cell-derived rows to v2 identity when missing.
            if not item.get("version"):
                item["version"] = 2
            if not item.get("itemId"):
                item["itemId"] = str(item.get("id") or f"{normalized_message_id}-cell-{index}")
            if not item.get("kind"):
                item["kind"] = str(item.get("type") or "tool_call")
            items.append(item)
    return _canonicalize_session_turn_items_for_protocol(
        items,
        session_id=session_id,
        turn_id=normalized_turn_id,
    )


def _canonicalize_session_turn_items_for_protocol(
    items: list[dict[str, Any]] | None,
    *,
    session_id: str,
    turn_id: str,
) -> list[dict[str, Any]]:
    """Emit the v3 SessionTurnItem algebra and discard v2 renderer aliases.

    Journal and live-output internals may use richer records while executing a
    turn.  The session DTO is intentionally narrower: it has one revisioned
    item list, not parallel content/thought/timeline/transcript projections.
    """
    s = _service()
    canonical: list[dict[str, Any]] = []
    for index, raw in enumerate(items or []):
        if not isinstance(raw, dict):
            continue
        raw_type = str(raw.get("type") or raw.get("kind") or "status").strip().lower()
        item_type = {
            "assistant_message": "agent_message",
            "assistant_text": "agent_message",
            "commentary": "agent_message",
            "analysis": "reasoning",
            "thought": "reasoning",
            "tool_result": "tool_call",
            "tool": "tool_call",
            "tool_call_started": "tool_call",
            "retrying": "retry",
            "model_retry": "retry",
        }.get(raw_type, raw_type)
        if item_type not in {"agent_message", "reasoning", "tool_call", "retry", "status", "error"}:
            item_type = "status"
        raw_status = str(raw.get("status") or "").strip().lower()
        status = {
            "in_progress": "running",
            "streaming": "running",
            "done": "completed",
            "degraded": "failed",
            "error": "failed",
        }.get(raw_status, raw_status)
        if status not in {"pending", "running", "completed", "failed"}:
            status = "completed" if raw.get("terminal") is True else "running"
        item_id = str(raw.get("itemId") or raw.get("id") or "").strip()
        if not item_id:
            item_id = f"{s._session_turn_item_base_id(session_id, turn_id or 'turn')}-{index + 1}"
        revision = max(0, int(raw.get("revision") or 0))
        text = s._sanitize_message_content(
            "assistant",
            raw.get("text") or raw.get("summary") or raw.get("title") or "",
        )
        raw_item_metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        metadata = {
            key: value
            for key, value in raw.items()
            if key not in {
                "id", "itemId", "version", "type", "kind", "status", "revision", "sequence",
                "sessionId", "turnId", "messageId", "channel", "phase", "protocol", "provisional",
                "terminal", "callId", "toolName", "title", "summary", "text", "diagnosticSummary",
                "source", "sourceCellId", "sourceCellKind", "sourceItemId", "metadata", "code",
                "input", "output", "createdAt", "updatedAt",
            }
        }
        if raw_item_metadata:
            metadata = {**raw_item_metadata, **metadata}
        item: dict[str, Any] = {
            "id": f"{item_id}:{revision}",
            "itemId": item_id,
            "version": 3,
            "sessionId": str(raw.get("sessionId") or session_id).strip(),
            "turnId": str(raw.get("turnId") or turn_id).strip(),
            "type": item_type,
            "status": status,
            "revision": revision,
            "sequence": max(0, int(raw.get("sequence") or index + 1)),
            "createdAt": str(raw.get("createdAt") or "").strip() or None,
            "updatedAt": str(raw.get("updatedAt") or "").strip() or None,
            "terminal": bool(raw.get("terminal")) or status in {"completed", "failed"},
            "title": str(raw.get("title") or "").strip() or None,
            "summary": str(raw.get("summary") or "").strip() or None,
            "diagnosticSummary": dict(raw.get("diagnosticSummary") or {}) if isinstance(raw.get("diagnosticSummary"), dict) else None,
            "metadata": metadata or None,
        }
        if item_type == "agent_message":
            item["phase"] = "commentary" if str(raw.get("phase") or "").strip().lower() in {"commentary", "interim"} else "final_answer"
            item["text"] = text
        elif item_type == "reasoning":
            item["text"] = text
        elif item_type == "tool_call":
            item["callId"] = str(raw.get("callId") or item_id).strip()
            item["toolName"] = str(raw.get("toolName") or raw.get("title") or "tool").strip()
            item["input"] = str(raw.get("input") or "").strip() or None
            item["output"] = text or None
        elif item_type == "retry":
            item["attempt"] = max(1, int(raw.get("attempt") or raw.get("iteration") or 1))
            item["targetItemId"] = str(raw.get("targetItemId") or raw.get("sourceItemId") or item_id).strip()
            item["reason"] = text
        else:
            item["code"] = str(raw.get("code") or raw.get("name") or raw.get("title") or item_type).strip()
            item["text"] = text
        canonical.append(s._compact_codex_record(item))
    # A fallback final answer is synthesized before legacy tool cells are
    # converted.  Keep the visual/event order truthful: process items precede
    # the terminal answer even when that old source did not carry a sequence.
    process_max_sequence = max(
        (
            int(item.get("sequence") or 0)
            for item in canonical
            if item.get("type") != "agent_message"
        ),
        default=0,
    )
    final_answer_offset = 0
    for item in canonical:
        if item.get("type") != "agent_message" or item.get("phase") != "final_answer":
            continue
        if int(item.get("sequence") or 0) <= process_max_sequence:
            final_answer_offset += 1
            item["sequence"] = process_max_sequence + final_answer_offset
    return sorted(canonical, key=lambda item: (int(item.get("sequence") or 0), str(item.get("itemId") or "")))


def _slim_session_turn_items_for_window_payload(
    items: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Keep turn-item semantics for window payloads; only trim heavy tool text.

    Final-answer and non-commentary assistant text must stay complete so the UI
    has a single authoritative body without length heuristics.
    """
    s = _service()
    slim_items: list[dict[str, Any]] = []
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        next_item = dict(item)
        kind = str(next_item.get("kind") or next_item.get("type") or "").strip().lower()
        phase = str(next_item.get("phase") or "").strip().lower()
        keep_full_text = (
            kind in {"assistant_message", "agent_message"}
            and phase != "commentary"
            and phase != "interim"
        ) or phase == "final_answer" or next_item.get("terminal") is True
        for field in ("text", "summary", "title"):
            value = next_item.get(field)
            if not isinstance(value, str) or not value.strip():
                continue
            if keep_full_text and field == "text":
                continue
            if len(value) > 400:
                next_item[field] = f"{value[:400]}…"
        # Drop unbounded diagnostic blobs from window payloads.
        diagnostic = next_item.get("diagnosticSummary")
        if isinstance(diagnostic, dict) and len(json.dumps(diagnostic, ensure_ascii=False)) > 1200:
            next_item["diagnosticSummary"] = {
                key: diagnostic[key]
                for key in (
                    "reasonCode",
                    "reasonSummary",
                    "httpStatus",
                    "providerErrorType",
                    "provider",
                    "model",
                    "eventCode",
                    "traceId",
                )
                if key in diagnostic
            }
        compact = s._compact_codex_record(next_item)
        if compact:
            slim_items.append(compact)
    return slim_items



def _build_codex_transcript_from_turn_items(*args, **kwargs):
    from core.web.services.session import projection_codex_transcript as _m
    return _m._build_codex_transcript_from_turn_items(*args, **kwargs)


def _build_window_final_answer_transcript(*args, **kwargs):
    from core.web.services.session import projection_codex_transcript as _m
    return _m._build_window_final_answer_transcript(*args, **kwargs)


def _slim_codex_transcript_for_window_payload(*args, **kwargs):
    from core.web.services.session import projection_codex_transcript as _m
    return _m._slim_codex_transcript_for_window_payload(*args, **kwargs)


def _build_codex_transcript_projection(*args, **kwargs):
    from core.web.services.session import projection_codex_transcript as _m
    return _m._build_codex_transcript_projection(*args, **kwargs)


def _build_terminal_error_codex_transcript_projection(*args, **kwargs):
    from core.web.services.session import projection_codex_transcript as _m
    return _m._build_terminal_error_codex_transcript_projection(*args, **kwargs)


def _codex_tool_lifecycle_projection_from_source(*args, **kwargs):
    from core.web.services.session import projection_codex_transcript as _m
    return _m._codex_tool_lifecycle_projection_from_source(*args, **kwargs)

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
    observed = (
        usage is not None
        and usage_source == "provider_usage"
        and bool(usage.get("cacheUsageObserved"))
    )
    cache_usage_missing_reason = str(
        (usage or {}).get("cacheUsageMissingReason") or ""
    ).strip()
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
        "cacheUsageObserved": observed,
        "cacheUsageMissingReason": cache_usage_missing_reason if not observed else "",
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
    if (
        usage is None
        or usage.get("source") != "provider_usage"
        or not bool(usage.get("cacheUsageObserved"))
    ):
        return s._enrich_session_cache_composition(
            {
                "turnId": turn_id,
                "recordedAt": s._now_timestamp(),
                "source": "missing",
                "cacheUsageObserved": False,
                "cacheUsageMissingReason": str(
                    (usage or {}).get("cacheUsageMissingReason")
                    or "provider_cache_usage_missing"
                ).strip(),
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
            "cacheUsageObserved": True,
            "cacheUsageMissingReason": "",
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
            character_count += len(str((message or {}).get("content") or ""))
        elif role == "assistant":
            assistant_count += 1
            for turn_item in list((message or {}).get("turnItems") or []):
                if not isinstance(turn_item, dict):
                    continue
                character_count += len(str(turn_item.get("text") or ""))
                if str(turn_item.get("type") or "").strip() != "tool_call":
                    continue
                tool_call_count += 1
                character_count += len(str(turn_item.get("toolName") or ""))
                character_count += len(str(turn_item.get("summary") or ""))
                character_count += len(str(turn_item.get("input") or ""))
                character_count += len(str(turn_item.get("output") or ""))
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
    explicit_cache_usage_observed = _coerce_optional_bool(
        value.get("cacheUsageObserved")
        if "cacheUsageObserved" in value
        else value.get("cache_usage_observed")
    )
    cache_usage_observed = (
        explicit_cache_usage_observed
        if explicit_cache_usage_observed is not None
        else cached_tokens > 0 or cache_creation_tokens > 0
    )
    return {
        "turnId": str(value.get("turnId") or value.get("turn_id") or "").strip(),
        "recordedAt": str(value.get("recordedAt") or value.get("recorded_at") or "").strip(),
        "source": source,
        "cacheUsageObserved": cache_usage_observed,
        "cacheUsageMissingReason": str(
            value.get("cacheUsageMissingReason")
            or value.get("cache_usage_missing_reason")
            or ("provider_cache_usage_missing" if source == "provider_usage" and not cache_usage_observed else "")
        ).strip(),
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
    explicit_cache_observed = value.get("cache_usage_observed")
    if explicit_cache_observed is None:
        explicit_cache_observed = value.get("cacheUsageObserved")
    parsed_cache_observed = _coerce_optional_bool(explicit_cache_observed)
    if parsed_cache_observed is None:
        cache_usage_observed = cached_input_tokens > 0 or cache_creation_input_tokens > 0
    else:
        cache_usage_observed = parsed_cache_observed
    cache_usage_missing_reason = str(
        value.get("cache_usage_missing_reason")
        or value.get("cacheUsageMissingReason")
        or ("provider_cache_usage_missing" if source == "provider_usage" and not cache_usage_observed else "")
    ).strip()
    uncached_input_tokens = s._coerce_nonnegative_int(
        value.get("uncached_input_tokens") or value.get("uncachedInputTokens") or 0
    )
    if cache_usage_observed and input_tokens:
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
        "cacheUsageObserved": cache_usage_observed,
        "cacheUsageMissingReason": cache_usage_missing_reason if not cache_usage_observed else "",
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
    live_metadata = (
        live_message.get("metadata")
        if isinstance(live_message.get("metadata"), dict)
        else {}
    )
    live_turn_id = str(
        live_message.get("turnId") or live_metadata.get("turnId") or ""
    ).strip()
    if live_turn_id and s._session_events_have_terminal_turn(
        s._load_session_conversation_events_cached(session_id),
        live_turn_id,
    ):
        # The journal is the Turn SSOT.  A checkpoint/live cache surviving a
        # restart or late failure cannot reopen a terminal turn in the UI.
        return detail_messages
    detail_messages = s._without_live_turn_ledger_partials(detail_messages, live_message)
    return detail_messages + [live_message]


def _latest_message_summary(messages: list[dict[str, Any]]) -> str:
    s = _service()
    for item in reversed(messages):
        preview_source = item.get("content") or ""
        if str(item.get("role") or "").strip().lower() == "assistant":
            turn_items = [
                turn_item
                for turn_item in list(item.get("turnItems") or [])
                if isinstance(turn_item, dict)
            ]
            final_answer = next(
                (
                    str(turn_item.get("text") or "").strip()
                    for turn_item in reversed(turn_items)
                    if str(turn_item.get("type") or "").strip() == "agent_message"
                    and str(turn_item.get("phase") or "final_answer").strip() == "final_answer"
                    and str(turn_item.get("text") or "").strip()
                ),
                "",
            )
            preview_source = final_answer or preview_source
        preview = s._compact_preview_text(preview_source)
        if preview:
            return preview
    return ""


def _conversation_phase(conversation_id: str, conversation: dict[str, Any]) -> str:
    s = _service()
    if s._is_session_stop_requested(conversation_id):
        return "stopping"
    normalized = str(conversation.get("last_turn_status") or conversation.get("lastTurnStatus") or "").strip().lower()
    if s._is_session_running(conversation_id):
        # C1: worker may still claim a hung turn after tool timeout — settle if hang criteria hit.
        try:
            s.reconcile_stale_chat_turn_work_runs()
        except Exception:
            pass
        if s._is_session_running(conversation_id):
            if normalized == "queued":
                return "queued"
            return "running"
        # Hang settlement may have cleared in-memory running; fall through to ready path.
    # Process-local worker is gone. If a chat_turn work-run is still marked
    # active for this session, release it so shell/top-bar stop showing "running".
    stale_work_run = s._active_chat_turn_work_run_for_session(conversation_id)
    if isinstance(stale_work_run, dict):
        finished_at = str(stale_work_run.get("updatedAt") or s._now_timestamp()).strip() or s._now_timestamp()
        s._release_stale_chat_turn_work_run(
            session_id=conversation_id,
            finished_at=finished_at,
            summary=s.text_for(
                s.get_web_language(),
                zh="会话 worker 已结束，已清除残留运行态。",
                en="Session worker finished; cleared residual running state.",
            ),
        )
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
    *,
    ledger_workspace_root: Path | None = None,
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
            ledger_workspace_root=ledger_workspace_root,
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
    defer_hidden_previews: bool = False,
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
        agent_by_id = agent_by_id if agent_by_id is not None else s._agent_lookup_for_conversations()
        hidden_team_member_agent_ids = (
            hidden_team_member_agent_ids
            if hidden_team_member_agent_ids is not None
            else s._agent_directory_stub_hidden_team_member_ids()
        )
        ledger_workspace_root = None
        if lightweight:
            try:
                ledger_workspace_root = s.conversation_ledger_workspace_root(
                    s.PROJECT_ROOT
                )
            except Exception:
                ledger_workspace_root = None
        if repair:
            s._repair_child_root_agent_direct_session_bindings(payload, agent_by_id=agent_by_id)
        dirty_runtime_rows: list[dict[str, Any]] = []
        for raw in list(payload.get("conversations") or []):
            if repair and isinstance(raw, dict):
                row_changed = s._ensure_conversation_agent_metadata(raw, agent_by_id=agent_by_id)
                row_changed = s._ensure_conversation_workspace_metadata(raw) or row_changed
                if row_changed:
                    dirty_runtime_rows.append(raw)
            conversation = s._normalize_conversation(
                raw,
                agent_by_id=agent_by_id,
                hidden_team_member_agent_ids=hidden_team_member_agent_ids,
                ensure_workspace=repair,
                lightweight=lightweight,
                load_message_preview=not (lightweight and defer_hidden_previews),
                phase_timings=phase_timings,
                ledger_workspace_root=ledger_workspace_root,
            )
            if (
                conversation is not None
                and lightweight
                and defer_hidden_previews
                and s._session_agent_visible_in_indexes(conversation)
            ):
                messages, has_ledger_messages = _load_lightweight_conversation_preview(
                    conversation["id"],
                    raw.get("messages") or [],
                    phase_timings=phase_timings,
                    ledger_workspace_root=ledger_workspace_root,
                )
                conversation["messages"] = messages
                conversation["_hasLedgerMessages"] = has_ledger_messages
            if conversation is not None:
                conversations.append(conversation)
        if dirty_runtime_rows:
            payload["updated_at"] = s._now_timestamp()
            s._persist_dirty_session_runtime_rows(dirty_runtime_rows)
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
        # Intentional delete/clear/reset: never append a stub for a deleted session.
        if s._is_session_workspace_intentionally_deleted(session_id):
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
    avatar_url_cache: dict[str, str] = {}
    return {
        str(item.get("agentId") or "").strip(): s._conversation_agent_from_state(
            item,
            avatar_url_cache=avatar_url_cache,
        )
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
    parsed = parse_timestamp_utc(value)
    if parsed is None:
        return 0.0
    return parsed.timestamp()


def _is_default_empty_session_title(title: str) -> bool:
    s = _service()
    normalized = str(title or "").strip()
    # Keep in sync with web isDefaultNewSessionTitle (create placeholders / action labels).
    return normalized in {
        s.DEFAULT_CHAT_CONVERSATION_TITLE,
        "新会话",
        "新建会话",
        "新对话",
        "默认对话",
        "New session",
        "New chat",
        "Untitled",
    }


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
