"""Agent directory list/get API projection helpers.

Claim scope: list/get agents, API hydration cache, runtime context block,
and agent-to-API summary/detail builders.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..agent_config_authority import (
    normalize_permission_preset,
    permission_runtime_contract,
)


def _service():
    from core.web.services import agent_directory_service

    return agent_directory_service


def _format_personal_episodes_context(episodes: list[dict[str, Any]]) -> list[str]:
    s = _service()
    from . import episodic_memory as episodic_memory_mod

    if not episodes:
        return ["## 个人记忆", "无"]
    lines = [
        "## 个人记忆",
        "本轮必须使用。这是当前 Agent 的跨会话私有记忆，不是世代交接，也不是团队/公共知识。",
    ]
    for item in episodes[: episodic_memory_mod.PROMPT_LIST_LIMIT]:
        episode_id = str(item.get("episodeId") or item.get("eventId") or "").strip()
        kind = str(item.get("kind") or "note").strip() or "note"
        text = s.trim_lines(str(item.get("text") or ""), max_lines=episodic_memory_mod.PROMPT_TEXT_LINES)
        lines.append(f"- episodeId={episode_id} kind={kind}")
        if text:
            lines.append(f"  text: {text}")
    return lines


def build_agent_runtime_context_block(
    agent_id: str,
    *,
    limit: int = 6,
    agent_snapshot: dict[str, Any] | None = None,
    group_events_snapshot: list[dict[str, Any]] | None = None,
    inbox_messages_snapshot: list[dict[str, Any]] | None = None,
    episodic_events_snapshot: list[dict[str, Any]] | None = None,
    memory_policy_snapshot: dict[str, Any] | None = None,
) -> str:
    s = _service()
    agent = dict(agent_snapshot) if isinstance(agent_snapshot, dict) else s.get_agent(agent_id)
    if not agent:
        return ""
    events = (
        list(group_events_snapshot)
        if group_events_snapshot is not None
        else s.list_group_context_events_for_agent(agent_id, limit=limit, prompt_eligible_only=True)
    )
    inbox_messages = (
        list(inbox_messages_snapshot)
        if inbox_messages_snapshot is not None
        else s.list_agent_inbox_messages_for_agent(
            agent_id,
            limit=limit,
            status="pending",
            prompt_eligible_only=True,
        )
    )
    from . import episodic_memory as episodic_memory_mod

    episodes = (
        list(episodic_events_snapshot)
        if episodic_events_snapshot is not None
        else s.list_current_episodic_events(agent_id, limit=episodic_memory_mod.PROMPT_LIST_LIMIT)
    )
    memory_policy = (
        dict(memory_policy_snapshot)
        if isinstance(memory_policy_snapshot, dict)
        else s.resolve_memory_policy_for_agent(agent_id)
    )
    tool_policy = (
        agent.get("toolPolicy")
        if isinstance(agent.get("toolPolicy"), dict)
        else s.resolve_tool_policy_for_agent(str(agent.get("agentId") or "").strip())
    )
    max_calls = 0
    if isinstance(tool_policy, dict):
        try:
            max_calls = int(tool_policy.get("maxCallsPerTurn") or 0)
        except (TypeError, ValueError):
            max_calls = 0
    budget_lines: list[str] = []
    if max_calls > 0:
        reserve = max(2, min(3, max_calls // 8 or 2))
        explore_cap = max(1, max_calls - reserve)
        budget_lines = [
            f"ToolCallBudget: maxCallsPerTurn={max_calls}",
            f"- Explore/search budget soft cap: <= {explore_cap}",
            f"- Reserve at least {reserve} calls for lint/test/git verification",
            "- After one shell failure of the same intent, switch to code_symbol_tool/grep_search_tool",
        ]
    lines = [
        "## Agent Runtime Context",
        f"AgentId: {agent.get('agentId') or ''}",
        f"AgentCode: {agent.get('agentCode') or ''}",
        f"AgentName: {agent.get('displayName') or ''}",
        f"AgentWorkspace: {agent.get('workspacePath') or ''}",
        f"MemoryRoot: {memory_policy.get('privateMemoryRoot') or ''}",
        f"ProjectMemoryUpdatesPath: {memory_policy.get('projectMemoryUpdatesPath') or ''}",
        *budget_lines,
        "TeamKnowledgeAccess:",
        f"- ReadKnowledgeBaseIds: {', '.join(list(memory_policy.get('readKnowledgeBaseIds') or [])) or 'team-membership'}",
        f"- ProposeKnowledgeBaseIds: {', '.join(list(memory_policy.get('proposeKnowledgeBaseIds') or [])) or 'team-membership'}",
        f"- ReviewKnowledgeBaseIds: {', '.join(list(memory_policy.get('reviewKnowledgeBaseIds') or [])) or 'team-review-roles'}",
        f"- RateKnowledgeBaseIds: {', '.join(list(memory_policy.get('rateKnowledgeBaseIds') or [])) or 'team-review-roles'}",
        "- Knowledge bodies are tool-readable only; do not treat team knowledge as prompt-injected memory.",
    ]
    persona_lines = s._format_persona_profile_context(agent.get("personaProfile"))
    if persona_lines:
        lines.extend(persona_lines)
    task_lines = s._format_task_profile_context(agent.get("taskProfile"))
    if task_lines:
        lines.extend(task_lines)
    lines.extend(_format_personal_episodes_context(episodes))
    if events:
        lines.append("GroupContextEvents:")
        for event in events[-limit:]:
            topic = s.trim_lines(str(event.get("topic") or ""), max_lines=1)
            summary = s.trim_lines(str(event.get("summary") or ""), max_lines=2)
            own = s.trim_lines(str(event.get("ownMessage") or ""), max_lines=2)
            peers = "; ".join(
                s.trim_lines(str(item or ""), max_lines=1)
                for item in list(event.get("peerHighlights") or [])[:3]
                if str(item or "").strip()
            )
            lines.append(f"- room={event.get('sourceRoomId') or ''} round={event.get('sourceRoundId') or ''}")
            if topic:
                lines.append(f"  topic: {topic}")
            if summary:
                lines.append(f"  summary: {summary}")
            if own:
                lines.append(f"  ownMessage: {own}")
            if peers:
                lines.append(f"  peerHighlights: {peers}")
    else:
        lines.append("GroupContextEvents: none")
    if inbox_messages:
        lines.append("AgentInboxMessages:")
        for message in inbox_messages[-limit:]:
            source_label = s._agent_message_source_label(message)
            content = s.trim_lines(str(message.get("content") or message.get("summary") or ""), max_lines=3)
            summary = s.trim_lines(str(message.get("summary") or ""), max_lines=2)
            lines.append(
                f"- messageId={message.get('messageId') or ''} from={source_label} status={message.get('status') or 'pending'}"
            )
            if content:
                lines.append(f"  content: {content}")
            if summary and summary != content:
                lines.append(f"  summary: {summary}")
            if message.get("sourceRoomId") or message.get("sourceRoundId"):
                lines.append(
                    f"  source: room={message.get('sourceRoomId') or ''} round={message.get('sourceRoundId') or ''}"
                )
    else:
        lines.append("AgentInboxMessages: none")
    from core.web.services import team_service

    lines.extend(team_service.build_team_roster_context_lines(str(agent.get("agentId") or agent_id or "").strip()))
    return "\n".join(line for line in lines if line is not None).strip()


def _agent_to_api(
    agent: dict[str, Any],
    *,
    hydration: Any | None = None,
    include_activity: bool = True,
    include_tool_governance: bool = False,
    include_inbox_pending_count: bool = False,
) -> dict[str, Any]:
    s = _service()
    workspace = str(agent.get("workspacePath") or "").strip()
    metadata = dict(agent.get("metadata") or {})
    avatar_path = s.resolve_agent_avatar_path_for_projection({**agent, "metadata": metadata})
    profileless_session_agent = s._is_profileless_session_agent({**agent, "metadata": metadata})
    if profileless_session_agent:
        metadata.pop("personaProfile", None)
        metadata.pop("taskProfile", None)
    persona_profile = {} if profileless_session_agent else s._persona_profile_for_agent({**agent, "metadata": metadata})
    task_profile = {} if profileless_session_agent else s._task_profile_for_agent({**agent, "metadata": metadata})
    agent_id = str(agent.get("agentId") or "").strip()
    tool_policy = s._tool_policy_for_agent(agent, hydration=hydration)
    agent_source_ref = s._source_authority_ref("agent", agent_id)
    agent_projection_edit = s._projection_edit_contract("agent", agent_id)
    conversation_index_classification = s.agent_conversation_index_classification({**agent, "metadata": metadata})
    conversation_index_visibility = s.agent_conversation_index_visibility({**agent, "metadata": metadata})
    prompt_binding = s._agent_prompt_template_binding({**agent, "metadata": metadata})
    return {
        "agentId": agent_id,
        "agentCode": s._normalize_agent_code(agent.get("agentCode"))
        or s._fallback_agent_code(agent.get("agentId")),
        "displayName": str(agent.get("displayName") or "").strip(),
        "kind": str(agent.get("kind") or s.DEFAULT_AGENT_KIND).strip() or s.DEFAULT_AGENT_KIND,
        "primaryMode": s._normalize_primary_mode(agent.get("primaryMode") or s._infer_agent_primary_mode(agent)),
        "roleKey": s._normalize_role_key(agent.get("roleKey") or s._infer_agent_role_key(agent)),
        "llmBindings": s.normalize_agent_llm_bindings(agent.get("llmBindings")),
        "contextCompressionPolicy": s.normalize_agent_context_compression_policy(
            agent.get("contextCompressionPolicy") if isinstance(agent.get("contextCompressionPolicy"), dict) else None
        ),
        "contextCompressionEffectivePolicy": s.effective_agent_context_compression_policy(
            agent,
            hydration.context_compression_base_policy if hydration is not None else None,
            context_window_limit=s._agent_context_window_limit(agent, hydration=hydration),
        ),
        "promptTemplateId": prompt_binding["promptTemplateId"],
        "defaultPromptTemplateId": prompt_binding["defaultPromptTemplateId"],
        "promptTemplateCustomized": prompt_binding["promptTemplateCustomized"],
        "directSessionId": str(agent.get("directSessionId") or "").strip(),
        "conversationIndexVisibility": conversation_index_visibility,
        "conversationIndexKind": str(conversation_index_classification.get("kind") or "").strip(),
        "conversationIndexErrors": list(conversation_index_classification.get("errors") or []),
        "workspacePath": workspace,
        "workspaceTerritory": s._agent_workspace_territory(agent),
        "toolPolicyId": str(agent.get("toolPolicyId") or s.DEFAULT_TOOL_POLICY_ID).strip() or s.DEFAULT_TOOL_POLICY_ID,
        "memoryPolicyId": str(agent.get("memoryPolicyId") or "").strip(),
        "avatarImagePath": avatar_path,
        "avatarImageUrl": s.agent_avatar_image_url(avatar_path),
        "personaProfile": persona_profile,
        "taskProfile": task_profile,
        "createdBy": str(agent.get("createdBy") or "").strip(),
        "status": str(agent.get("status") or "active").strip() or "active",
        "metadata": metadata,
        "createdAt": str(agent.get("createdAt") or "").strip(),
        "updatedAt": str(agent.get("updatedAt") or "").strip(),
        "configSchemaVersion": int(agent.get("configSchemaVersion") or 0),
        "configRevision": int(agent.get("configRevision") or 0),
        "configHash": str(agent.get("configHash") or "").strip(),
        "permissionPreset": str(agent.get("permissionPreset") or "").strip(),
        "runtimePermissions": (
            permission_runtime_contract(agent.get("permissionPreset"))
            if str(agent.get("permissionPreset") or "").strip()
            else None
        ),
        "memoryPolicy": s._memory_policy_for_agent(agent, hydration=hydration),
        "toolPolicy": tool_policy,
        "toolPolicySource": s._tool_policy_source_for_agent(agent, tool_policy),
        "toolGovernanceRequests": (
            s._tool_governance_requests_for_agent(agent_id, hydration=hydration, limit=6)
            if include_activity or include_tool_governance
            else []
        ),
        "groupContextEvents": s._group_context_events_for_agent(agent, hydration=hydration, limit=8) if include_activity else [],
        "agentInboxMessages": (
            s._agent_inbox_messages_for_agent(agent, hydration=hydration, limit=8, status="pending") if include_activity else []
        ),
        "agentInboxPendingCount": (
            s._agent_inbox_pending_count_for_agent(agent, hydration=hydration, status="pending")
            if include_activity or include_inbox_pending_count
            else 0
        ),
        "sourceRef": agent_source_ref,
        "projectionEdit": agent_projection_edit,
        "activityHydration": (
            "full"
            if include_activity
            else ("config" if include_tool_governance or include_inbox_pending_count else "deferred")
        ),
    }


def _build_agent_api_hydration_context(
    state: dict[str, Any],
    agents: list[dict[str, Any]],
    *,
    timings: dict[str, float] | None = None,
) -> Any:
    s = _service()
    timings_ref = timings if timings is not None else {}
    started = time.perf_counter()
    fast_signature = ("full", s._agent_api_hydration_fast_signature(agents))
    cached = s._get_agent_api_hydration_fast_cache(fast_signature, now=started)
    if cached is not None:
        timings_ref["cache_lookup"] = round((time.perf_counter() - started) * 1000, 1)
        timings_ref["cache_hit"] = 1.0
        timings_ref["cache_fast_hit"] = 1.0
        return cached
    signature: tuple[Any, ...] | None = None
    if s._agent_api_hydration_cache_matches_mode("full"):
        signature = ("full", s._agent_api_hydration_signature(agents))
        cached = s._get_agent_api_hydration_cache(signature)
        timings_ref["cache_lookup"] = round((time.perf_counter() - started) * 1000, 1)
        if cached is not None:
            timings_ref["cache_hit"] = 1.0
            timings_ref["cache_fast_hit"] = 0.0
            s._refresh_agent_api_hydration_fast_cache(fast_signature)
            return cached
    else:
        timings_ref["cache_lookup"] = round((time.perf_counter() - started) * 1000, 1)
    timings_ref["cache_hit"] = 0.0
    timings_ref["cache_fast_hit"] = 0.0
    started = time.perf_counter()
    tool_policies = s._tool_policies(state)
    timings_ref["tool_policies"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    memory_policies = s._memory_policies(state)
    timings_ref["memory_policies"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    context_compression_base_policy = s._context_compression_base_policy_for_agents()
    timings_ref["context_compression_policy"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    model_context_window_limits = s._model_context_window_limits_for_agents(agents)
    timings_ref["model_context_windows"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    tool_governance_requests_by_agent = s._load_recent_tool_governance_requests_for_agents(agents, limit=6)
    timings_ref["tool_governance_requests"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    group_context_events_by_agent: dict[str, list[dict[str, Any]]] = {}
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        group_context_events_by_agent[agent_id] = s._read_recent_jsonl(
            s._resolve_project_path(str(agent.get("workspacePath") or "")) / "events" / "group_context_events.jsonl",
            limit=8,
        )
    timings_ref["group_context_events"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    agent_inbox_messages_by_agent: dict[str, list[dict[str, Any]]] = {}
    agent_inbox_pending_count_by_agent: dict[str, int] = {}
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        path = s._agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
        recent, pending_count = s._read_recent_jsonl_with_count(
            path,
            limit=8,
            status="pending",
        )
        agent_inbox_messages_by_agent[agent_id] = recent
        agent_inbox_pending_count_by_agent[agent_id] = pending_count
    timings_ref["agent_inbox_messages"] = round((time.perf_counter() - started) * 1000, 1)
    context = s.AgentApiHydrationContext(
        state=state,
        tool_policies=tool_policies,
        memory_policies=memory_policies,
        context_compression_base_policy=context_compression_base_policy,
        model_context_window_limits_by_model_id=model_context_window_limits,
        tool_governance_requests_by_agent=tool_governance_requests_by_agent,
        group_context_events_by_agent=group_context_events_by_agent,
        agent_inbox_messages_by_agent=agent_inbox_messages_by_agent,
        agent_inbox_pending_count_by_agent=agent_inbox_pending_count_by_agent,
    )
    s._remember_agent_api_hydration_cache(signature, fast_signature, context)
    return context


def list_agents(
    *,
    include_archived: bool = False,
    detail: str = "full",
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """List Agent API projections.

    ``project_root`` 为显式解析根；缺省回落模块级 ``PROJECT_ROOT``。并发
    调用方（如 research agent runner）必须显式传参，不得改写模块级根。
    """

    s = _service()
    with s.scoped_project_root(project_root):
        return _list_agents(include_archived=include_archived, detail=detail)


def _list_agents(*, include_archived: bool, detail: str) -> list[dict[str, Any]]:
    s = _service()
    started = time.perf_counter()
    timings: dict[str, float] = {}
    normalized_detail = str(detail or "full").strip().lower()
    if normalized_detail not in {"full", "summary", "config"}:
        normalized_detail = "full"
    repair_cache_hit = False
    lock_wait_started = time.perf_counter()
    with s._STATE_LOCK:
        timings["lock_wait"] = round((time.perf_counter() - lock_wait_started) * 1000, 1)
        stage_started = time.perf_counter()
        state, repair_cache_hit = s._load_repaired_state_for_read()
        timings["repair"] = round((time.perf_counter() - stage_started) * 1000, 1)
    stage_started = time.perf_counter()
    raw_agents = [
        item
        for item in state.get("agents") or []
        if isinstance(item, dict) and (include_archived or str(item.get("status") or "active") != "archived")
    ]
    timings["filter"] = round((time.perf_counter() - stage_started) * 1000, 1)
    hydration_timings: dict[str, float] = {}
    if normalized_detail == "summary":
        timings["hydrate"] = 0.0
        stage_started = time.perf_counter()
        avatar_url_cache: dict[str, str] = {}
        available_avatars = s._available_agent_avatar_filenames()
        agents = [
            s._agent_to_api_summary(item, avatar_url_cache=avatar_url_cache, available_avatar_filenames=available_avatars)
            for item in raw_agents
        ]
        timings["to_api"] = round((time.perf_counter() - stage_started) * 1000, 1)
    elif normalized_detail == "config":
        stage_started = time.perf_counter()
        hydration = s._build_agent_api_config_hydration_context(state, raw_agents, timings=hydration_timings)
        timings["hydrate"] = round((time.perf_counter() - stage_started) * 1000, 1)
        hydration_timings["activity_hydration"] = 0.0
        stage_started = time.perf_counter()
        agents = [
            s._agent_to_api(
                item,
                hydration=hydration,
                include_activity=False,
                include_tool_governance=True,
                include_inbox_pending_count=True,
            )
            for item in raw_agents
        ]
        timings["to_api"] = round((time.perf_counter() - stage_started) * 1000, 1)
    else:
        stage_started = time.perf_counter()
        hydration = s._build_agent_api_hydration_context(state, raw_agents, timings=hydration_timings)
        timings["hydrate"] = round((time.perf_counter() - stage_started) * 1000, 1)
        stage_started = time.perf_counter()
        agents = [s._agent_to_api(item, hydration=hydration) for item in raw_agents]
        timings["to_api"] = round((time.perf_counter() - stage_started) * 1000, 1)
    stage_started = time.perf_counter()
    agents.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    timings["sort"] = round((time.perf_counter() - stage_started) * 1000, 1)
    timings["total"] = round((time.perf_counter() - started) * 1000, 1)
    s._record_agent_list_loaded(
        include_archived=include_archived,
        detail=normalized_detail,
        raw_agent_count=len(raw_agents),
        returned_agent_count=len(agents),
        timings=timings,
        hydration_timings=hydration_timings,
        repair_cache_hit=repair_cache_hit,
    )
    return agents


def _agent_to_api_summary(
    agent: dict[str, Any],
    *,
    avatar_url_cache: dict[str, str] | None = None,
    available_avatar_filenames: list[str] | None = None,
) -> dict[str, Any]:
    s = _service()
    workspace = str(agent.get("workspacePath") or "").strip()
    metadata = dict(agent.get("metadata") or {})
    avatar_path = s.resolve_agent_avatar_path_for_projection(
        {**agent, "metadata": metadata},
        available_avatar_filenames=available_avatar_filenames,
    )
    profileless_session_agent = s._is_profileless_session_agent({**agent, "metadata": metadata})
    if profileless_session_agent:
        metadata.pop("personaProfile", None)
        metadata.pop("taskProfile", None)
    agent_id = str(agent.get("agentId") or "").strip()
    agent_source_ref = s._source_authority_ref("agent", agent_id)
    agent_projection_edit = s._projection_edit_contract("agent", agent_id)
    conversation_index_classification = s.agent_conversation_index_classification({**agent, "metadata": metadata})
    conversation_index_visibility = s.agent_conversation_index_visibility({**agent, "metadata": metadata})
    prompt_binding = s._agent_prompt_template_binding({**agent, "metadata": metadata})
    avatar_image_url = avatar_url_cache.get(avatar_path) if avatar_url_cache is not None and avatar_path else None
    if avatar_image_url is None:
        avatar_image_url = s.agent_avatar_image_url(avatar_path)
        if avatar_url_cache is not None and avatar_path:
            avatar_url_cache[avatar_path] = avatar_image_url
    return {
        "agentId": agent_id,
        "agentCode": s._normalize_agent_code(agent.get("agentCode"))
        or s._fallback_agent_code(agent.get("agentId")),
        "displayName": str(agent.get("displayName") or "").strip(),
        "kind": str(agent.get("kind") or s.DEFAULT_AGENT_KIND).strip() or s.DEFAULT_AGENT_KIND,
        "primaryMode": s._normalize_primary_mode(agent.get("primaryMode") or s._infer_agent_primary_mode(agent)),
        "roleKey": s._normalize_role_key(agent.get("roleKey") or s._infer_agent_role_key(agent)),
        "llmBindings": s.normalize_agent_llm_bindings(agent.get("llmBindings")),
        "contextCompressionPolicy": s.normalize_agent_context_compression_policy(
            agent.get("contextCompressionPolicy") if isinstance(agent.get("contextCompressionPolicy"), dict) else None
        ),
        "contextCompressionEffectivePolicy": s.effective_agent_context_compression_policy(
            agent,
            context_window_limit=s._agent_context_window_limit(agent),
        ),
        "promptTemplateId": prompt_binding["promptTemplateId"],
        "defaultPromptTemplateId": prompt_binding["defaultPromptTemplateId"],
        "promptTemplateCustomized": prompt_binding["promptTemplateCustomized"],
        "directSessionId": str(agent.get("directSessionId") or "").strip(),
        "conversationIndexVisibility": conversation_index_visibility,
        "conversationIndexKind": str(conversation_index_classification.get("kind") or "").strip(),
        "conversationIndexErrors": list(conversation_index_classification.get("errors") or []),
        "workspacePath": workspace,
        "workspaceTerritory": s._agent_workspace_territory(agent),
        "toolPolicyId": str(agent.get("toolPolicyId") or s.DEFAULT_TOOL_POLICY_ID).strip() or s.DEFAULT_TOOL_POLICY_ID,
        "memoryPolicyId": str(agent.get("memoryPolicyId") or "").strip(),
        "avatarImagePath": avatar_path,
        "avatarImageUrl": avatar_image_url,
        "personaProfile": {} if profileless_session_agent else s._persona_profile_for_agent({**agent, "metadata": metadata}),
        "taskProfile": {} if profileless_session_agent else s._task_profile_for_agent({**agent, "metadata": metadata}),
        "createdBy": str(agent.get("createdBy") or "").strip(),
        "status": str(agent.get("status") or "active").strip() or "active",
        "metadata": metadata,
        "createdAt": str(agent.get("createdAt") or "").strip(),
        "updatedAt": str(agent.get("updatedAt") or "").strip(),
        "configSchemaVersion": int(agent.get("configSchemaVersion") or 0),
        "configRevision": int(agent.get("configRevision") or 0),
        "configHash": str(agent.get("configHash") or "").strip(),
        "permissionPreset": str(agent.get("permissionPreset") or "").strip(),
        "runtimePermissions": (
            permission_runtime_contract(agent.get("permissionPreset"))
            if str(agent.get("permissionPreset") or "").strip()
            else None
        ),
        "sourceRef": agent_source_ref,
        "projectionEdit": agent_projection_edit,
    }


def _build_agent_api_config_hydration_context(
    state: dict[str, Any],
    agents: list[dict[str, Any]],
    *,
    timings: dict[str, float] | None = None,
) -> Any:
    s = _service()
    timings_ref = timings if timings is not None else {}
    started = time.perf_counter()
    fast_signature = ("config", s._agent_api_hydration_fast_signature(agents))
    cached = s._get_agent_api_hydration_fast_cache(fast_signature, now=started)
    if cached is not None:
        timings_ref["cache_lookup"] = round((time.perf_counter() - started) * 1000, 1)
        timings_ref["cache_hit"] = 1.0
        timings_ref["cache_fast_hit"] = 1.0
        return cached
    signature: tuple[Any, ...] | None = None
    if s._agent_api_hydration_cache_matches_mode("config"):
        signature = ("config", s._agent_api_config_hydration_signature(agents))
        cached = s._get_agent_api_hydration_cache(signature)
        timings_ref["cache_lookup"] = round((time.perf_counter() - started) * 1000, 1)
        if cached is not None:
            timings_ref["cache_hit"] = 1.0
            timings_ref["cache_fast_hit"] = 0.0
            s._refresh_agent_api_hydration_fast_cache(fast_signature)
            return cached
    else:
        timings_ref["cache_lookup"] = round((time.perf_counter() - started) * 1000, 1)
    timings_ref["cache_hit"] = 0.0
    timings_ref["cache_fast_hit"] = 0.0
    started = time.perf_counter()
    tool_policies = s._tool_policies(state)
    timings_ref["tool_policies"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    memory_policies = s._memory_policies(state)
    timings_ref["memory_policies"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    context_compression_base_policy = s._context_compression_base_policy_for_agents()
    timings_ref["context_compression_policy"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    model_context_window_limits = s._model_context_window_limits_for_agents(agents)
    timings_ref["model_context_windows"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    tool_governance_requests_by_agent = s._load_recent_tool_governance_requests_for_agents(agents, limit=6)
    timings_ref["tool_governance_requests"] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    agent_inbox_pending_count_by_agent = s._count_pending_agent_inbox_messages_for_agents(agents)
    timings_ref["agent_inbox_pending_counts"] = round((time.perf_counter() - started) * 1000, 1)
    timings_ref["group_context_events"] = 0.0
    timings_ref["agent_inbox_messages"] = 0.0
    context = s.AgentApiHydrationContext(
        state=state,
        tool_policies=tool_policies,
        memory_policies=memory_policies,
        context_compression_base_policy=context_compression_base_policy,
        model_context_window_limits_by_model_id=model_context_window_limits,
        tool_governance_requests_by_agent=tool_governance_requests_by_agent,
        group_context_events_by_agent={},
        agent_inbox_messages_by_agent={},
        agent_inbox_pending_count_by_agent=agent_inbox_pending_count_by_agent,
    )
    s._remember_agent_api_hydration_cache(signature, fast_signature, context)
    return context


def agent_conversation_index_classification(
    agent: dict[str, Any] | None,
    *,
    hidden_team_member_agent_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Return the strict conversation index classification for an Agent direct session."""
    s = _service()

    if not isinstance(agent, dict):
        return {"kind": s.CONVERSATION_INDEX_KIND_HIDDEN, "errors": []}
    if str(agent.get("kind") or s.DEFAULT_AGENT_KIND).strip() != s.DEFAULT_AGENT_KIND:
        return {"kind": s.CONVERSATION_INDEX_KIND_HIDDEN, "errors": []}
    if str(agent.get("status") or "active").strip().lower() == "archived":
        return {"kind": s.CONVERSATION_INDEX_KIND_HIDDEN, "errors": []}
    agent_id = str(agent.get("agentId") or "").strip()
    direct_session_id = str(agent.get("directSessionId") or "").strip()
    if not agent_id or not direct_session_id:
        return {"kind": s.CONVERSATION_INDEX_KIND_HIDDEN, "errors": []}

    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    raw_kind = str(agent.get("conversationIndexKind") or metadata.get("conversationIndexKind") or "").strip()
    explicit_kind = s.normalize_conversation_index_kind(raw_kind)
    errors: list[str] = []
    if raw_kind and not explicit_kind:
        errors.append("invalid_conversation_index_kind")
    if not explicit_kind:
        errors.append("missing_conversation_index_kind")

    role_key = s._normalize_role_key(agent.get("roleKey") or s._infer_agent_role_key(agent))
    creation_spec = metadata.get("creationSpec") if isinstance(metadata.get("creationSpec"), dict) else {}
    created_by = str(agent.get("createdBy") or creation_spec.get("source") or "").strip()
    has_team_marker = bool(
        str(metadata.get("teamId") or "").strip()
        or str(metadata.get("challengeCupTeamId") or "").strip()
        or str(metadata.get("knowledgeExpansionTeamId") or "").strip()
        or (hidden_team_member_agent_ids and agent_id in hidden_team_member_agent_ids)
    )
    looks_team_owned = (
        has_team_marker
        or role_key.startswith(("challenge_cup_", "knowledge_expansion_"))
        or created_by in s.TEAM_PRIVATE_DIRECT_SESSION_CREATED_BY
    )
    if not explicit_kind and looks_team_owned:
        errors.append("team_agent_missing_conversation_index_kind")
    if not explicit_kind and created_by == "session_repair":
        errors.append("session_repair_missing_conversation_index_kind")
    if not explicit_kind and created_by in s.INTERNAL_RECOVERY_DIRECT_SESSION_CREATED_BY:
        errors.append("internal_recovery_missing_conversation_index_kind")

    kind = explicit_kind or s.CONVERSATION_INDEX_KIND_INVALID
    if kind == s.CONVERSATION_INDEX_KIND_HIDDEN:
        return {"kind": kind, "errors": errors}
    if kind == s.CONVERSATION_INDEX_KIND_USER_CHAT:
        errors.append("agent_direct_session_cannot_be_user_chat")
    if kind == s.CONVERSATION_INDEX_KIND_TEAM_AGENT and not has_team_marker:
        errors.append("team_agent_missing_team_id")
    if kind == s.CONVERSATION_INDEX_KIND_SYSTEM_ENTRY:
        errors.append("agent_direct_session_cannot_be_system_entry")
    if errors:
        kind = s.CONVERSATION_INDEX_KIND_INVALID
    return {"kind": kind, "errors": sorted(set(errors))}


@contextmanager
def active_agent_runtime(
    agent_id: str = "",
    *,
    session_id: str = "",
    turn_id: str = "",
    room_id: str = "",
    round_id: str = "",
    supervised_role: str = "",
    runtime_tool_grants: Iterable[Any] | None = None,
    runtime_tool_source: str = "",
    runtime_metadata: dict[str, Any] | None = None,
):
    s = _service()
    agent = s.get_agent(agent_id) if agent_id else None
    agent_snapshot = copy.deepcopy(agent) if isinstance(agent, dict) else {}
    normalized_supervised_role = str(supervised_role or "").strip()
    grants = (
        s._tool_name_list(runtime_tool_grants or [])
        if runtime_tool_grants is not None
        else s.supervised_role_runtime_tools(normalized_supervised_role)
    )
    metadata = (
        agent_snapshot.get("metadata")
        if isinstance(agent_snapshot.get("metadata"), dict)
        else {}
    )
    delegation_policy = (
        s.normalize_delegation_policy(metadata.get("delegationPolicy"))
        if agent_snapshot
        else s.resolve_delegation_policy_for_agent(agent_id)
    )
    tool_policy = (
        s.normalize_tool_policy(
            agent_snapshot.get("toolPolicy"),
            str(agent_snapshot.get("toolPolicyId") or s.DEFAULT_TOOL_POLICY_ID),
        )
        if isinstance(agent_snapshot.get("toolPolicy"), dict)
        else s.resolve_tool_policy_for_agent(
            agent_id,
            session_id=session_id,
            turn_id=turn_id,
        )
    )
    tool_policy = s._with_temporary_tool_grants(
        tool_policy,
        agent_id=agent_id,
        session_id=session_id,
        turn_id=turn_id,
    )
    tool_policy = s._with_runtime_tool_grants(
        tool_policy,
        grants,
        source=str(runtime_tool_source or "").strip()
        or ("supervised_conversation_harness" if normalized_supervised_role else ""),
    )
    tool_policy = s._effective_agent_tool_policy(tool_policy, delegation_policy)
    memory_policy = (
        copy.deepcopy(agent_snapshot.get("memoryPolicy"))
        if isinstance(agent_snapshot.get("memoryPolicy"), dict)
        else s.resolve_memory_policy_for_agent(agent_id)
    )
    supervision_policy = (
        s.normalize_supervision_policy(metadata.get("supervisionPolicy"))
        if agent_snapshot
        else s.resolve_supervision_policy_for_agent(agent_id)
    )
    permission_preset = _runtime_permission_preset(
        agent_snapshot.get("permissionPreset") if agent_snapshot else "",
        runtime_tool_source=str(runtime_tool_source or "").strip(),
    )
    externally_blocked_tools: list[str] = []
    if agent_id:
        from core.agent_plugins.runtime_extensions import (
            blocked_agent_plugin_tool_names,
        )

        externally_blocked_tools = blocked_agent_plugin_tool_names(agent_id)
    context = {
        "agentId": str(agent_id or "").strip(),
        "sessionId": str(session_id or "").strip(),
        "turnId": str(turn_id or "").strip(),
        "roomId": str(room_id or "").strip(),
        "roundId": str(round_id or "").strip(),
        "supervisedRole": normalized_supervised_role,
        "agent": agent_snapshot,
        "agentConfigSnapshot": {
            "agentId": str(agent_snapshot.get("agentId") or agent_id or "").strip(),
            "configRevision": int(agent_snapshot.get("configRevision") or 0),
            "configHash": str(agent_snapshot.get("configHash") or "").strip(),
        },
        "permissionPreset": permission_preset,
        "runtimePermissions": (
            permission_runtime_contract(permission_preset)
            if permission_preset
            else None
        ),
        "runtimeToolSource": str(runtime_tool_source or "").strip(),
        "runtimeMetadata": copy.deepcopy(runtime_metadata)
        if isinstance(runtime_metadata, dict)
        else {},
        "toolPolicy": tool_policy,
        "externallyBlockedTools": externally_blocked_tools,
        "memoryPolicy": memory_policy,
        "delegationPolicy": delegation_policy,
        "supervisionPolicy": supervision_policy,
    }
    token = s._CURRENT_AGENT_RUNTIME.set(context)
    try:
        yield context
    finally:
        s._CURRENT_AGENT_RUNTIME.reset(token)


def _runtime_permission_preset(
    value: Any,
    *,
    runtime_tool_source: str = "",
) -> str:
    if str(runtime_tool_source or "").strip().startswith("external_agent_task:"):
        return "request_approval"
    return normalize_permission_preset(value) if str(value or "").strip() else ""


def _format_task_profile_context(profile: Any) -> list[str]:
    s = _service()
    normalized = s.normalize_task_profile(profile if isinstance(profile, dict) else {})
    if not s._task_profile_has_content(normalized):
        return []
    labels = {
        "mission": "Mission",
        "responsibilities": "Responsibilities",
        "preferredTasks": "PreferredTasks",
        "avoidTasks": "AvoidTasks",
        "successCriteria": "SuccessCriteria",
        "deliverables": "Deliverables",
        "constraints": "Constraints",
        "handoffNotes": "HandoffNotes",
    }
    lines = [
        "AgentTaskProfile:",
        "- Contract: descriptive task-fit and operating-scope guidance; do not use it as an automatic permission, routing, or scheduling gate.",
    ]
    task_types = [str(item or "").strip() for item in list(normalized.get("taskTypes") or []) if str(item or "").strip()]
    if task_types:
        lines.append(f"- TaskTypes: {', '.join(task_types[:16])}")
    for field in s.AGENT_TASK_PROFILE_TEXT_FIELDS:
        value = str(normalized.get(field) or "").strip()
        if value:
            lines.append(f"- {labels[field]}: {value}")
    return lines


def _format_persona_profile_context(profile: Any) -> list[str]:
    s = _service()
    normalized = s.normalize_persona_profile(profile if isinstance(profile, dict) else {})
    if not s._persona_profile_has_content(normalized):
        return []
    labels = {
        "gender": "Gender",
        "age": "Age",
        "pronouns": "Pronouns",
        "personality": "Personality",
        "communicationStyle": "CommunicationStyle",
        "background": "Background",
        "collaborationPreference": "CollaborationPreference",
        "identityNotes": "IdentityNotes",
    }
    lines = [
        "AgentPersonaProfile:",
        "- Contract: descriptive persona and collaboration guidance; do not use age/gender as capability, permission, or safety gates.",
    ]
    for field in s.AGENT_PERSONA_PROFILE_TEXT_FIELDS:
        value = str(normalized.get(field) or "").strip()
        if value:
            lines.append(f"- {labels[field]}: {value}")
    expertise = [str(item or "").strip() for item in list(normalized.get("expertise") or []) if str(item or "").strip()]
    if expertise:
        lines.append(f"- Expertise: {', '.join(expertise[:12])}")
    return lines


def _agent_api_hydration_signature(agents: list[dict[str, Any]]) -> tuple[Any, ...]:
    s = _service()
    agent_signatures: list[tuple[Any, ...]] = []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        workspace = str(agent.get("workspacePath") or "").strip()
        agent_signatures.append(
            (
                agent_id,
                workspace,
                s._jsonl_signature(s._agent_workspace_event_path(agent, "tool_governance_requests.jsonl")),
                s._jsonl_signature(s._agent_workspace_event_path(agent, "group_context_events.jsonl")),
                s._jsonl_signature(s._agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")),
            )
        )
    return (s._registry_state_signature(), s._agent_api_hydration_event_version(), tuple(agent_signatures))


def _agent_api_config_hydration_signature(agents: list[dict[str, Any]]) -> tuple[Any, ...]:
    s = _service()
    agent_signatures: list[tuple[Any, ...]] = []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        workspace = str(agent.get("workspacePath") or "").strip()
        agent_signatures.append(
            (
                agent_id,
                workspace,
                s._jsonl_signature(s._agent_workspace_event_path(agent, "tool_governance_requests.jsonl")),
                s._jsonl_signature(s._agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")),
            )
        )
    return (s._registry_state_signature(), s._agent_api_hydration_event_version(), tuple(agent_signatures))


def _remember_agent_api_hydration_cache(
    signature: tuple[Any, ...] | None,
    fast_signature: tuple[Any, ...],
    context: Any,
) -> None:
    s = _service()
    with s._AGENT_API_HYDRATION_CACHE_LOCK:
        s._AGENT_API_HYDRATION_CACHE_SIGNATURE = signature
        s._AGENT_API_HYDRATION_CACHE_FAST_SIGNATURE = fast_signature
        s._AGENT_API_HYDRATION_CACHE_VALIDATED_AT = time.perf_counter()
        s._AGENT_API_HYDRATION_CACHE = context


def _get_agent_api_hydration_fast_cache(
    fast_signature: tuple[Any, ...],
    *,
    now: float,
) -> Any | None:
    s = _service()
    with s._AGENT_API_HYDRATION_CACHE_LOCK:
        if s._AGENT_API_HYDRATION_CACHE is None:
            return None
        if s._AGENT_API_HYDRATION_CACHE_FAST_SIGNATURE != fast_signature:
            return None
        if now - s._AGENT_API_HYDRATION_CACHE_VALIDATED_AT > s._AGENT_API_HYDRATION_FAST_TTL_SECONDS:
            return None
        return s._AGENT_API_HYDRATION_CACHE


def record_agent_api_hydration_event_file_changed(path: Path | str) -> None:
    """Invalidate the fast Agent API hydration cache when Agent event logs change."""
    s = _service()

    try:
        filename = Path(path).name
    except TypeError:
        filename = ""
    if filename not in s._AGENT_API_HYDRATION_EVENT_FILENAMES:
        return
    with s._AGENT_API_HYDRATION_CACHE_LOCK:
        s._AGENT_API_HYDRATION_EVENT_VERSION += 1


def _agent_api_hydration_fast_signature(agents: list[dict[str, Any]]) -> tuple[Any, ...]:
    s = _service()
    agent_keys: list[tuple[str, str]] = []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        agent_keys.append(
            (
                str(agent.get("agentId") or "").strip(),
                str(agent.get("workspacePath") or "").strip(),
            )
        )
    return (s._registry_state_signature(), s._agent_api_hydration_event_version(), tuple(agent_keys))


def get_agent(
    agent_id: str,
    *,
    include_archived: bool = True,
    project_root: Path | None = None,
) -> dict[str, Any] | None:
    """Return one Agent API projection under the explicit (or default) root."""

    s = _service()
    with s.scoped_project_root(project_root):
        return _get_agent(agent_id, include_archived=include_archived)


def _get_agent(agent_id: str, *, include_archived: bool) -> dict[str, Any] | None:
    s = _service()
    normalized = str(agent_id or "").strip()
    if not normalized:
        return None
    with s._STATE_LOCK:
        state, _ = s._load_repaired_state_for_read()
        agent = s._find_agent(state, normalized)
    if not agent:
        return None
    if not include_archived and str(agent.get("status") or "") == "archived":
        return None
    return s._agent_to_api(agent)


def _agent_api_hydration_cache_matches_mode(mode: str) -> bool:
    s = _service()
    normalized_mode = str(mode or "").strip()
    if not normalized_mode:
        return False
    with s._AGENT_API_HYDRATION_CACHE_LOCK:
        for signature in (s._AGENT_API_HYDRATION_CACHE_FAST_SIGNATURE, s._AGENT_API_HYDRATION_CACHE_SIGNATURE):
            if isinstance(signature, tuple) and signature and signature[0] == normalized_mode:
                return True
    return False


def _refresh_agent_api_hydration_fast_cache(fast_signature: tuple[Any, ...]) -> None:
    s = _service()
    with s._AGENT_API_HYDRATION_CACHE_LOCK:
        s._AGENT_API_HYDRATION_CACHE_FAST_SIGNATURE = fast_signature
        s._AGENT_API_HYDRATION_CACHE_VALIDATED_AT = time.perf_counter()


def _get_agent_api_hydration_cache(signature: tuple[Any, ...]) -> Any | None:
    s = _service()
    with s._AGENT_API_HYDRATION_CACHE_LOCK:
        if s._AGENT_API_HYDRATION_CACHE_SIGNATURE == signature:
            return s._AGENT_API_HYDRATION_CACHE
    return None


def _agent_api_hydration_event_version() -> int:
    s = _service()
    with s._AGENT_API_HYDRATION_CACHE_LOCK:
        return s._AGENT_API_HYDRATION_EVENT_VERSION
