"""Context assembly boundary for long-lived Agent runtimes."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.runtime_manager import agent_run_store
from core.web.services.runtime_scene_service import record_runtime_scene_event


AGENT_RUN_KIND = agent_run_store.AGENT_RUN_KIND
SUB_AGENT_RUN_KIND = agent_run_store.SUB_AGENT_RUN_KIND


def _perf_counter() -> float:
    return time.perf_counter()


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((_perf_counter() - started_at) * 1000)))


@dataclass(frozen=True)
class AgentContextPacket:
    agent_id: str
    agent_code: str = ""
    display_name: str = ""
    session_id: str = ""
    run_id: str = ""
    workspace_path: str = ""
    profile_id: str = ""
    prompt_template_id: str = ""
    role_key: str = ""
    memory_policy: dict[str, Any] = field(default_factory=dict)
    tool_policy: dict[str, Any] = field(default_factory=dict)
    group_context_events: list[dict[str, Any]] = field(default_factory=list)
    inbox_messages: list[dict[str, Any]] = field(default_factory=list)
    context_block: str = ""
    timings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SubAgentContextPacket:
    parent_agent_id: str
    parent_session_id: str
    context_mode: str
    parent_context: AgentContextPacket | None = None


def build_agent_context(agent_id: str, *, session_id: str = "", run_id: str = "", limit: int = 6) -> AgentContextPacket:
    """Build the bounded context packet used by a persistent Agent turn."""

    from core.web.services import agent_directory_service

    context_started_at = _perf_counter()
    timings: dict[str, Any] = {}
    normalized_agent_id = str(agent_id or "").strip()
    stage_started_at = _perf_counter()
    agent = agent_directory_service.get_agent(normalized_agent_id, include_archived=False)
    historical_agent = (
        None
        if agent
        else agent_directory_service.get_agent(normalized_agent_id, include_archived=True)
    )
    timings["agentLookupMs"] = _elapsed_ms(stage_started_at)
    if not agent:
        status = str((historical_agent or {}).get("status") or "").strip().lower()
        reason = "archived_agent" if status == "archived" else "missing_agent"
        _record_context_event(
            "agent_runtime.resolve_failed",
            outcome="failed",
            level="error",
            fields={
                "agentId": normalized_agent_id,
                "sessionId": str(session_id or "").strip(),
                "runId": str(run_id or "").strip(),
                "reason": reason,
                "agentStatus": status,
                "source": "ContextEngine",
            },
        )
        return AgentContextPacket(
            agent_id=normalized_agent_id,
            session_id=session_id,
            run_id=run_id,
            timings={
                "reason": reason,
                "agentStatus": status,
                "totalDurationMs": _elapsed_ms(context_started_at),
                **timings,
            },
        )

    stage_started_at = _perf_counter()
    group_events = agent_directory_service.list_group_context_events_for_agent(
        normalized_agent_id,
        limit=limit,
        prompt_eligible_only=True,
    )
    timings["groupContextEventsMs"] = _elapsed_ms(stage_started_at)
    stage_started_at = _perf_counter()
    inbox_messages = agent_directory_service.list_agent_inbox_messages_for_agent(
        normalized_agent_id,
        limit=limit,
        status="pending",
        prompt_eligible_only=True,
    )
    timings["inboxMessagesMs"] = _elapsed_ms(stage_started_at)
    stage_started_at = _perf_counter()
    runtime_context_block = agent_directory_service.build_agent_runtime_context_block(normalized_agent_id, limit=limit)
    timings["runtimeContextBlockMs"] = _elapsed_ms(stage_started_at)
    stage_started_at = _perf_counter()
    research_org_context_block = _build_research_organization_context_block(
        normalized_agent_id,
        limit=limit,
    )
    timings["researchOrgContextMs"] = _elapsed_ms(stage_started_at)
    prompt_template_id = str(agent.get("promptTemplateId") or "").strip()
    stage_started_at = _perf_counter()
    prompt_context_block = _build_prompt_template_context_block(
        prompt_template_id,
        project_root=agent_directory_service.PROJECT_ROOT,
        agent_id=normalized_agent_id,
        session_id=str(session_id or "").strip(),
        run_id=str(run_id or "").strip(),
    )
    timings["promptTemplateContextMs"] = _elapsed_ms(stage_started_at)
    stage_started_at = _perf_counter()
    project_rules_context_block = _build_project_rules_context_block(
        agent_directory_service.PROJECT_ROOT,
        agent_id=normalized_agent_id,
        session_id=str(session_id or "").strip(),
        run_id=str(run_id or "").strip(),
    )
    timings["projectRulesContextMs"] = _elapsed_ms(stage_started_at)
    stage_started_at = _perf_counter()
    project_agent_registry_context_block = _build_project_agent_registry_context_block(
        agent_directory_service.PROJECT_ROOT,
        current_agent=agent,
        session_id=str(session_id or "").strip(),
        run_id=str(run_id or "").strip(),
    )
    timings["projectAgentRegistryContextMs"] = _elapsed_ms(stage_started_at)
    runtime_context_block = "\n\n".join(
        part
        for part in (
            runtime_context_block,
            research_org_context_block,
            prompt_context_block,
            project_rules_context_block,
            project_agent_registry_context_block,
        )
        if str(part or "").strip()
    )
    stage_started_at = _perf_counter()
    memory_policy = agent_directory_service.resolve_memory_policy_for_agent(normalized_agent_id)
    timings["memoryPolicyMs"] = _elapsed_ms(stage_started_at)
    stage_started_at = _perf_counter()
    tool_policy = agent_directory_service.resolve_tool_policy_for_agent(normalized_agent_id)
    timings["toolPolicyMs"] = _elapsed_ms(stage_started_at)
    timings["totalDurationMs"] = _elapsed_ms(context_started_at)
    packet = AgentContextPacket(
        agent_id=normalized_agent_id,
        agent_code=str(agent.get("agentCode") or "").strip(),
        display_name=str(agent.get("displayName") or "").strip(),
        session_id=str(session_id or "").strip(),
        run_id=str(run_id or "").strip(),
        workspace_path=str(agent.get("workspacePath") or "").strip(),
        profile_id=str(agent.get("profileId") or "").strip(),
        prompt_template_id=prompt_template_id,
        role_key=str(agent.get("roleKey") or "").strip(),
        memory_policy=memory_policy,
        tool_policy=tool_policy,
        group_context_events=group_events,
        inbox_messages=inbox_messages,
        context_block=runtime_context_block,
        timings=dict(timings),
    )
    _record_context_event(
        "agent_runtime.resolved",
        outcome="resolved",
        fields={
            "agentId": packet.agent_id,
            "agentCode": packet.agent_code,
            "sessionId": packet.session_id,
            "runId": packet.run_id,
            "profileId": packet.profile_id,
            "promptTemplateId": packet.prompt_template_id,
            "roleKey": packet.role_key,
            "groupContextEventCount": len(packet.group_context_events),
            "inboxMessageCount": len(packet.inbox_messages),
            "researchOrgContextIncluded": bool(research_org_context_block),
            "projectRulesContextIncluded": bool(project_rules_context_block),
            "projectAgentRegistryContextIncluded": bool(project_agent_registry_context_block),
            "source": "ContextEngine",
        },
    )
    return packet


def _build_research_organization_context_block(agent_id: str, *, limit: int = 6) -> str:
    """Return the research organization context block, logging service failures at the turn seam."""

    try:
        from core.web.services import research_organization_service

        return research_organization_service.build_research_organization_context_block(
            agent_id,
            limit=limit,
        )
    except Exception as exc:
        _record_context_event(
            "agent_runtime.research_org_context_failed",
            outcome="failed",
            level="warning",
            fields={
                "agentId": str(agent_id or "").strip(),
                "reason": type(exc).__name__,
                "source": "ContextEngine",
            },
        )
        return ""


def prepare_subagent_spawn(
    parent_agent_id: str,
    parent_session_id: str,
    *,
    context_mode: str,
    requested_depth: int | None = None,
) -> SubAgentContextPacket:
    """Prepare an isolated or explicit fork context for a temporary sub-agent."""

    normalized_mode = str(context_mode or "isolated").strip().lower()
    if normalized_mode not in {"isolated", "fork"}:
        raise ValueError("Sub-agent context_mode must be isolated or fork.")
    from core.web.services import agent_directory_service

    decision = agent_directory_service.evaluate_delegation_policy(
        agent_directory_service.resolve_delegation_policy_for_agent(parent_agent_id),
        agent_id=str(parent_agent_id or "").strip(),
        context_mode=normalized_mode,
        requested_depth=requested_depth,
    )
    if not decision.allowed:
        _record_context_event(
            "subagent.context_blocked",
            outcome="blocked",
            level="warning",
            fields={
                "parentAgentId": str(parent_agent_id or "").strip(),
                "parentSessionId": str(parent_session_id or "").strip(),
                "contextMode": normalized_mode,
                "reason": decision.reason,
                "maxDepth": decision.max_depth,
            },
        )
        raise ValueError(decision.message or "Sub-agent spawn blocked by DelegationPolicy.")
    parent_context = (
        build_agent_context(parent_agent_id, session_id=parent_session_id)
        if normalized_mode == "fork"
        else None
    )
    packet = SubAgentContextPacket(
        parent_agent_id=str(parent_agent_id or "").strip(),
        parent_session_id=str(parent_session_id or "").strip(),
        context_mode=normalized_mode,
        parent_context=parent_context,
    )
    _record_context_event(
        "subagent.context_prepared",
        outcome="prepared",
        fields={
            "parentAgentId": packet.parent_agent_id,
            "parentSessionId": packet.parent_session_id,
            "contextMode": packet.context_mode,
            "forked": packet.parent_context is not None,
        },
    )
    return packet


def record_agent_turn_result(
    agent_id: str,
    session_id: str,
    result: dict[str, Any],
    *,
    run_id: str = "",
) -> dict[str, Any] | None:
    """Persist a bounded result breadcrumb for an Agent turn."""

    from core.web.services import agent_directory_service

    normalized_agent_id = str(agent_id or "").strip()
    agent = agent_directory_service.get_agent(normalized_agent_id)
    if not agent:
        return None
    result_payload = result if isinstance(result, dict) else {}
    event_id = f"turn-{_now_compact()}"
    source_run_id = str(run_id or result_payload.get("runId") or result_payload.get("turnId") or "").strip()
    status = agent_run_store.result_status(result_payload)
    summary = agent_run_store.result_summary(result_payload)
    tool_call_count = _safe_int(result_payload.get("tool_call_count") or result_payload.get("toolCallCount"))
    created_at = _now()
    payload = {
        "eventId": event_id,
        "runId": source_run_id,
        "agentId": normalized_agent_id,
        "sessionId": str(session_id or "").strip(),
        "status": status,
        "summary": summary,
        "toolCallCount": tool_call_count,
        "createdAt": created_at,
    }
    _append_agent_event(agent_directory_service.PROJECT_ROOT, str(agent.get("workspacePath") or ""), "agent_turn_results.jsonl", payload)
    snapshot = agent_run_store.persist_agent_run_snapshot(
        agent,
        source_run_id=source_run_id or event_id,
        session_id=str(session_id or "").strip(),
        status=status,
        summary=summary,
        tool_call_count=tool_call_count,
        timestamp=created_at,
        result=result_payload,
    )
    _record_context_event(
        "agent_context.turn_result_recorded",
        outcome="written",
        fields={
            "agentId": normalized_agent_id,
            "runId": snapshot.get("runId") if snapshot else "",
            "sourceRunId": source_run_id,
            "sessionId": payload["sessionId"],
            "status": payload["status"],
            "toolCallCount": payload["toolCallCount"],
        },
    )
    return snapshot


def record_subagent_result(parent_run_id: str, sub_run_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Persist a bounded sub-agent completion breadcrumb."""

    from core.web.services import agent_directory_service

    result_payload = result if isinstance(result, dict) else {}
    status = agent_run_store.result_status(result_payload)
    summary = agent_run_store.result_summary(result_payload)
    created_at = _now()
    payload = {
        "parentRunId": str(parent_run_id or "").strip(),
        "subRunId": str(sub_run_id or "").strip(),
        "status": status,
        "summary": summary,
        "createdAt": created_at,
    }
    path = Path(agent_directory_service.PROJECT_ROOT) / "workspace" / "agent_runs" / "subagent_results.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    snapshot = agent_run_store.persist_sub_agent_run_snapshot(
        parent_run_id=payload["parentRunId"],
        sub_run_id=payload["subRunId"],
        status=status,
        summary=summary,
        tool_call_count=_safe_int(result_payload.get("tool_call_count") or result_payload.get("toolCallCount")),
        timestamp=created_at,
        result=result_payload,
    )
    _record_context_event(
        "subagent.result_recorded",
        outcome="written",
        fields={
            "parentRunId": payload["parentRunId"],
            "subRunId": payload["subRunId"],
            "runId": snapshot.get("runId") or "",
            "status": payload["status"],
        },
    )
    return snapshot


def list_agent_runs_for_agent(agent_id: str, *, limit: int = 20) -> dict[str, Any]:
    """Return recent bounded AgentRun/SubAgentRun snapshots for one persistent Agent."""

    return agent_run_store.list_agent_runs_for_agent(agent_id, limit=limit)


def _append_agent_event(project_root: Path, workspace_path: str, filename: str, payload: dict[str, Any]) -> None:
    safe_workspace = str(workspace_path or "").strip()
    if not safe_workspace:
        return
    root = Path(project_root).resolve()
    event_path = (root / safe_workspace / "events" / filename).resolve()
    if root != event_path and root not in event_path.parents:
        return
    event_path.parent.mkdir(parents=True, exist_ok=True)
    with event_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _build_prompt_template_context_block(
    prompt_template_id: str,
    *,
    project_root: Path,
    agent_id: str,
    session_id: str,
    run_id: str,
) -> str:
    normalized = str(prompt_template_id or "").strip()
    if not normalized:
        return ""
    from core.web.services import prompt_template_service

    result = prompt_template_service.build_agent_prompt_template_context(
        normalized,
        project_root=project_root,
    )
    reason = str(result.get("reason") or "").strip()
    if reason == "missing_template":
        _record_context_event(
            "agent_runtime.prompt_template_missing",
            outcome="missing_prompt_template",
            level="warning",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "runId": run_id,
                "promptTemplateId": normalized,
                "reason": "missing_template",
                "source": "ContextEngine",
            },
        )
        return ""
    if reason == "empty_template_content":
        _record_context_event(
            "agent_runtime.prompt_template_missing",
            outcome="missing_prompt_template",
            level="warning",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "runId": run_id,
                "promptTemplateId": normalized,
                "sourcePath": str(result.get("sourcePath") or "").strip(),
                "sourceExists": bool(result.get("sourceExists")),
                "reason": "empty_template_content",
                "source": "ContextEngine",
            },
        )
        return ""
    return str(result.get("contextBlock") or "").strip()


def _build_project_rules_context_block(
    project_root: Path,
    *,
    agent_id: str,
    session_id: str,
    run_id: str,
) -> str:
    agents_path = Path(project_root) / "AGENTS.md"
    if not agents_path.exists():
        return ""
    try:
        content = agents_path.read_text(encoding="utf-8")
    except OSError as exc:
        _record_context_event(
            "agent_runtime.project_rules_context_failed",
            outcome="failed",
            level="warning",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "runId": run_id,
                "sourcePath": str(agents_path),
                "reason": type(exc).__name__,
                "source": "ContextEngine",
            },
        )
        return ""
    section_names = (
        "Session-Level Agent Memory Coordination",
        "Session Agent Territory And Handoff",
    )
    sections = [(name, _extract_markdown_section(content, name)) for name in section_names]
    included_sections = [(name, section) for name, section in sections if section]
    if not included_sections:
        return ""
    block = "\n".join(
        [
            "## Project Operating Rules",
            "Source: AGENTS.md#Session-Level Agent Memory Coordination + #Session Agent Territory And Handoff",
            *(
                "\n".join([f"### {name}", section]).strip()
                for name, section in included_sections
            ),
        ]
    ).strip()
    _record_context_event(
        "agent_runtime.project_rules_context_loaded",
        outcome="included",
        fields={
            "agentId": agent_id,
            "sessionId": session_id,
            "runId": run_id,
            "sourcePath": str(agents_path),
            "section": ",".join(name for name, _section in included_sections),
            "characterCount": len(block),
            "source": "ContextEngine",
        },
    )
    return block


def _build_project_agent_registry_context_block(
    project_root: Path,
    *,
    current_agent: dict[str, Any],
    session_id: str,
    run_id: str,
) -> str:
    """Return project-local Agent territory and handoff context for a session Agent."""

    agent_id = str(current_agent.get("agentId") or "").strip()
    if not agent_id:
        return ""
    from core.web.services import agent_directory_service

    registry_path = Path(project_root) / ".docs" / "project-memory" / "agent-registry.json"
    registry = _ensure_project_agent_registry(
        registry_path,
        agent_id=agent_id,
        session_id=session_id,
        run_id=run_id,
    )
    active_agents = [
        item
        for item in agent_directory_service.list_agents(include_archived=False)
        if isinstance(item, dict) and str(item.get("agentId") or "").strip()
    ]
    entries = _merge_project_agent_registry_entries(registry, active_agents)
    current_entry = _find_project_agent_registry_entry(
        entries,
        agent_id=agent_id,
        session_id=session_id or str(current_agent.get("directSessionId") or "").strip(),
    )
    if not current_entry:
        return ""
    handoff_entries = _project_agent_handoff_entries(current_entry, entries, limit=8)
    lines = [
        "## Project Agent Territory Registry",
        "Source: .docs/project-memory/agent-registry.json + active AgentDirectory",
        "Contract:",
        "- You are bound to the sessionId and management territory listed below.",
        (
            "- If a user request is outside your management scope, say it is out of scope "
            "and recommend a matching Agent/session from HandoffTargets."
        ),
        (
            "- Do not silently take over another Agent's territory; recommend handoff "
            "unless the user explicitly asks you to coordinate."
        ),
        "CurrentAgent:",
        _format_project_agent_registry_entry(current_entry, include_scope=True),
    ]
    if handoff_entries:
        lines.append("HandoffTargets:")
        lines.extend(
            _format_project_agent_registry_entry(entry, include_scope=True, prefix="- ")
            for entry in handoff_entries
        )
    else:
        lines.append("HandoffTargets: none")
    block = "\n".join(line for line in lines if str(line or "").strip()).strip()
    _record_context_event(
        "agent_runtime.project_agent_registry_context_loaded",
        outcome="included",
        fields={
            "agentId": agent_id,
            "sessionId": session_id,
            "runId": run_id,
            "sourcePath": str(registry_path),
            "sourceExists": registry_path.exists(),
            "autoInitialized": bool(registry.get("_autoInitialized")),
            "registryAgentCount": len(entries),
            "handoffTargetCount": len(handoff_entries),
            "source": "ContextEngine",
        },
    )
    return block


def _ensure_project_agent_registry(
    registry_path: Path,
    *,
    agent_id: str,
    session_id: str,
    run_id: str,
) -> dict[str, Any]:
    registry = _read_project_agent_registry(
        registry_path,
        agent_id=agent_id,
        session_id=session_id,
        run_id=run_id,
    )
    if registry:
        return registry
    if registry_path.exists():
        return _default_project_agent_registry(auto_initialized=False)
    default_registry = _default_project_agent_registry()
    try:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps(default_registry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        _record_context_event(
            "agent_runtime.project_agent_registry_auto_init_failed",
            outcome="failed",
            level="warning",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "runId": run_id,
                "sourcePath": str(registry_path),
                "reason": type(exc).__name__,
                "source": "ContextEngine",
            },
        )
        return default_registry
    default_registry["_autoInitialized"] = True
    _record_context_event(
        "agent_runtime.project_agent_registry_auto_initialized",
        outcome="created",
        fields={
            "agentId": agent_id,
            "sessionId": session_id,
            "runId": run_id,
            "sourcePath": str(registry_path),
            "laneTerritoryCount": len(default_registry.get("laneTerritories") or {}),
            "source": "ContextEngine",
        },
    )
    return default_registry


def _read_project_agent_registry(
    registry_path: Path,
    *,
    agent_id: str,
    session_id: str,
    run_id: str,
) -> dict[str, Any]:
    if not registry_path.exists():
        return {}
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _record_context_event(
            "agent_runtime.project_agent_registry_context_failed",
            outcome="failed",
            level="warning",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "runId": run_id,
                "sourcePath": str(registry_path),
                "reason": type(exc).__name__,
                "source": "ContextEngine",
            },
        )
        return {}
    return payload if isinstance(payload, dict) else {}


def _default_project_agent_registry(*, auto_initialized: bool = True) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "updatedAt": datetime.now(UTC).isoformat(),
        "sourceOfTruth": {
            "identityBinding": "AgentDirectory",
            "territoryDefaults": ".docs/project-memory/agent-registry.json",
            "runtimeInjection": "core/orchestration/context_engine.py",
        },
        "policy": {
            "outOfScopeDefault": "recommend_handoff",
            "automaticForwarding": False,
            "memoryWriteMode": "serialized_single_writer",
            "autoInitialized": auto_initialized,
        },
        "laneTerritories": _default_project_agent_lane_territories(),
        "agents": [],
    }


def _default_project_agent_lane_territories() -> dict[str, dict[str, Any]]:
    return {
        "agent-runtime-core": {
            "managementScope": {
                "summary": "负责 Agent 运行主干、ContextEngine、AgentDirectory、工具/记忆/委托策略和运行时上下文装配。",
                "files": [
                    "core/orchestration/**",
                    "core/web/services/agent_directory_service.py",
                    "core/runtime_manager/**",
                    "agent.py",
                ],
                "taskTypes": [
                    "runtime-context",
                    "agent-directory",
                    "memory-policy",
                    "tool-policy",
                    "delegation",
                ],
            },
            "handoffTargets": [
                "chat-coding-surface",
                "quality-and-operations",
                "evolution-control-plane",
            ],
            "outOfScopePolicy": "recommend_handoff",
        },
        "chat-coding-surface": {
            "managementScope": {
                "summary": "负责 Chat/Coding 会话体验、直接会话、群聊、消息撤回/删除、进度反馈和前后端会话协同。",
                "files": [
                    "core/web/services/session_service.py",
                    "core/web/services/chat_room_service.py",
                    "web/src/routes/ChatCodingRoute.tsx",
                    "web/src/api/**",
                ],
                "taskTypes": [
                    "chat-session",
                    "group-chat",
                    "message-lifecycle",
                    "conversation-ui",
                ],
            },
            "handoffTargets": [
                "agent-runtime-core",
                "web-workbench-surface",
                "quality-and-operations",
            ],
            "outOfScopePolicy": "recommend_handoff",
        },
        "web-workbench-surface": {
            "managementScope": {
                "summary": "负责 Web 工作台、Agent Center、Teams、Research Flow Canvas、配置页和前端信息架构。",
                "files": [
                    "web/src/routes/**",
                    "web/src/components/**",
                    "core/web/routes/**",
                    "core/web/services/team_service.py",
                ],
                "taskTypes": [
                    "frontend",
                    "agent-center",
                    "teams",
                    "canvas",
                    "web-api-adapter",
                ],
            },
            "handoffTargets": [
                "chat-coding-surface",
                "agent-runtime-core",
                "quality-and-operations",
            ],
            "outOfScopePolicy": "recommend_handoff",
        },
        "quality-and-operations": {
            "managementScope": {
                "summary": "负责测试策略、日志证据、运行时场景诊断、发布收口、版本判断和工作树卫生。",
                "files": [
                    "tests/**",
                    "logs/runtime_scenes/**",
                    "CHANGELOG.md",
                    "VERSION",
                    ".docs/project-memory/**",
                ],
                "taskTypes": [
                    "testing",
                    "logging",
                    "diagnosis",
                    "release",
                    "git-hygiene",
                ],
            },
            "handoffTargets": [
                "agent-runtime-core",
                "chat-coding-surface",
                "web-workbench-surface",
            ],
            "outOfScopePolicy": "recommend_handoff",
        },
        "evolution-control-plane": {
            "managementScope": {
                "summary": "负责监督进化、候选/基线对比、Gym 晋升、评审门禁和进化控制面。",
                "files": [
                    "core/evolution/**",
                    "core/web/services/self_evolution_control_service.py",
                    "workspace/evolution/**",
                    ".docs/project-memory/lanes/evolution-control-plane.json",
                ],
                "taskTypes": [
                    "supervised-evolution",
                    "gym-promotion",
                    "baseline-candidate",
                    "review-gate",
                ],
            },
            "handoffTargets": [
                "self-evolution-loop",
                "agent-runtime-core",
                "quality-and-operations",
            ],
            "outOfScopePolicy": "recommend_handoff",
        },
        "self-evolution-loop": {
            "managementScope": {
                "summary": "负责自进化循环、反思、能力沉淀、提示词/技能改进和长期改进闭环。",
                "files": [
                    "core/self_evolution/**",
                    "workspace/prompts/**",
                    ".docs/project-memory/lanes/self-evolution-loop.json",
                    "AGENTS.md",
                ],
                "taskTypes": [
                    "self-evolution",
                    "reflection",
                    "prompt-improvement",
                    "skill-improvement",
                ],
            },
            "handoffTargets": [
                "evolution-control-plane",
                "agent-runtime-core",
                "quality-and-operations",
            ],
            "outOfScopePolicy": "recommend_handoff",
        },
    }


def _merge_project_agent_registry_entries(
    registry: dict[str, Any],
    active_agents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    registry_entries = [
        item
        for item in registry.get("agents") or []
        if isinstance(item, dict) and str(item.get("status") or "active").strip().lower() != "archived"
    ]
    entries_by_agent_id: dict[str, dict[str, Any]] = {}
    entries_by_session_id: dict[str, dict[str, Any]] = {}
    for entry in registry_entries:
        agent_id = str(entry.get("agentId") or "").strip()
        session_id = str(entry.get("sessionId") or entry.get("directSessionId") or "").strip()
        if agent_id:
            entries_by_agent_id[agent_id] = entry
        if session_id:
            entries_by_session_id[session_id] = entry

    lane_defaults = _project_agent_registry_lane_defaults(registry)
    merged: list[dict[str, Any]] = []
    seen_agent_ids: set[str] = set()
    for agent in active_agents:
        agent_id = str(agent.get("agentId") or "").strip()
        session_id = str(agent.get("directSessionId") or "").strip()
        explicit = entries_by_agent_id.get(agent_id) or entries_by_session_id.get(session_id) or {}
        merged.append(_project_agent_registry_entry_from_sources(agent, explicit, lane_defaults=lane_defaults))
        seen_agent_ids.add(agent_id)

    for entry in registry_entries:
        agent_id = str(entry.get("agentId") or "").strip()
        if agent_id and agent_id in seen_agent_ids:
            continue
        if str(entry.get("status") or "active").strip().lower() != "active":
            continue
        merged.append(_project_agent_registry_entry_from_sources({}, entry, lane_defaults=lane_defaults))
    return merged


def _project_agent_registry_entry_from_sources(
    agent: dict[str, Any],
    explicit: dict[str, Any],
    *,
    lane_defaults: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    responsibility_lane = str(
        explicit.get("responsibilityLane")
        or metadata.get("responsibilityLane")
        or _infer_project_agent_responsibility_lane(agent)
    ).strip()
    lane_default = lane_defaults.get(responsibility_lane) or {}
    management_scope = explicit.get("managementScope")
    if not isinstance(management_scope, dict):
        management_scope = (
            metadata.get("managementScope")
            if isinstance(metadata.get("managementScope"), dict)
            else {}
        )
    if not management_scope and isinstance(lane_default.get("managementScope"), dict):
        management_scope = lane_default.get("managementScope") or {}
    return {
        "agentId": str(explicit.get("agentId") or agent.get("agentId") or "").strip(),
        "agentCode": str(explicit.get("agentCode") or agent.get("agentCode") or "").strip(),
        "sessionId": str(
            explicit.get("sessionId") or explicit.get("directSessionId") or agent.get("directSessionId") or ""
        ).strip(),
        "displayName": str(explicit.get("displayName") or agent.get("displayName") or "").strip(),
        "responsibilityLane": responsibility_lane,
        "managementScope": {
            "summary": str(management_scope.get("summary") or "").strip(),
            "files": [
                str(item or "").strip()
                for item in list(management_scope.get("files") or [])[:8]
                if str(item or "").strip()
            ],
            "taskTypes": [
                str(item or "").strip()
                for item in list(management_scope.get("taskTypes") or [])[:8]
                if str(item or "").strip()
            ],
        },
        "handoffTargets": [
            str(item or "").strip()
            for item in list(
                explicit.get("handoffTargets")
                or metadata.get("handoffTargets")
                or lane_default.get("handoffTargets")
                or []
            )[:8]
            if str(item or "").strip()
        ],
        "outOfScopePolicy": str(
            explicit.get("outOfScopePolicy")
            or metadata.get("outOfScopePolicy")
            or lane_default.get("outOfScopePolicy")
            or "recommend_handoff"
        ).strip(),
        "status": str(explicit.get("status") or agent.get("status") or "active").strip() or "active",
    }


def _project_agent_registry_lane_defaults(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = registry.get("laneTerritories") if isinstance(registry.get("laneTerritories"), dict) else {}
    defaults: dict[str, dict[str, Any]] = {}
    for lane_id, value in raw.items():
        normalized_lane = str(lane_id or "").strip()
        if not normalized_lane or not isinstance(value, dict):
            continue
        defaults[normalized_lane] = value
    return defaults


def _find_project_agent_registry_entry(
    entries: list[dict[str, Any]],
    *,
    agent_id: str,
    session_id: str,
) -> dict[str, Any] | None:
    normalized_agent_id = str(agent_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    for entry in entries:
        if normalized_agent_id and str(entry.get("agentId") or "").strip() == normalized_agent_id:
            return entry
    for entry in entries:
        if normalized_session_id and str(entry.get("sessionId") or "").strip() == normalized_session_id:
            return entry
    return None


def _project_agent_handoff_entries(
    current_entry: dict[str, Any],
    entries: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    current_agent_id = str(current_entry.get("agentId") or "").strip()
    targets = [
        str(item or "").strip()
        for item in list(current_entry.get("handoffTargets") or [])
        if str(item or "").strip()
    ]
    active_entries = [
        item
        for item in entries
        if str(item.get("status") or "active").strip().lower() == "active"
        and str(item.get("agentId") or "").strip() != current_agent_id
    ]
    if targets:
        matched = [
            item
            for item in active_entries
            if str(item.get("agentId") or "").strip() in targets
            or str(item.get("sessionId") or "").strip() in targets
            or str(item.get("responsibilityLane") or "").strip() in targets
        ]
        if matched:
            return matched[:limit]
    return active_entries[:limit]


def _format_project_agent_registry_entry(
    entry: dict[str, Any],
    *,
    include_scope: bool,
    prefix: str = "",
) -> str:
    scope = entry.get("managementScope") if isinstance(entry.get("managementScope"), dict) else {}
    parts = [
        f"agentId={entry.get('agentId') or ''}",
        f"sessionId={entry.get('sessionId') or ''}",
        f"agentCode={entry.get('agentCode') or ''}",
        f"name={entry.get('displayName') or ''}",
        f"lane={entry.get('responsibilityLane') or 'unassigned'}",
        f"outOfScopePolicy={entry.get('outOfScopePolicy') or 'recommend_handoff'}",
    ]
    if include_scope:
        summary = str(scope.get("summary") or "").strip()
        files = ", ".join(str(item or "").strip() for item in list(scope.get("files") or [])[:4] if str(item or "").strip())
        task_types = ", ".join(
            str(item or "").strip() for item in list(scope.get("taskTypes") or [])[:4] if str(item or "").strip()
        )
        if summary:
            parts.append(f"scope={summary}")
        if files:
            parts.append(f"files={files}")
        if task_types:
            parts.append(f"taskTypes={task_types}")
    return prefix + "; ".join(parts)


def _infer_project_agent_responsibility_lane(agent: dict[str, Any]) -> str:
    primary_mode = str(agent.get("primaryMode") or "").strip()
    role_key = str(agent.get("roleKey") or "").strip()
    prompt_template_id = str(agent.get("promptTemplateId") or "").strip()
    profile_id = str(agent.get("profileId") or "").strip()
    haystack = " ".join([primary_mode, role_key, prompt_template_id, profile_id]).lower()
    if "self_evolution" in haystack or "self-evolution" in haystack:
        return "self-evolution-loop"
    if "supervised_evolution" in haystack or "supervised-evolution" in haystack:
        return "evolution-control-plane"
    if "research" in haystack:
        return "agent-runtime-core"
    if "chat" in haystack:
        return "chat-coding-surface"
    return "agent-runtime-core"


def _extract_markdown_section(content: str, heading: str) -> str:
    target = f"## {heading}".strip()
    lines = str(content or "").splitlines()
    captured: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_section:
                break
            if stripped == target:
                in_section = True
            continue
        if in_section:
            captured.append(line.rstrip())
    return "\n".join(captured).strip()


def _record_context_event(event_code: str, *, outcome: str, fields: dict[str, Any], level: str = "info") -> None:
    try:
        record_runtime_scene_event(
            "agent_context",
            "context_engine",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields=fields,
            lifecycle=True,
        )
    except Exception:
        return


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _now_compact() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")


def packet_to_dict(packet: AgentContextPacket | SubAgentContextPacket) -> dict[str, Any]:
    return asdict(packet)
