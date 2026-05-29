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
    agent = agent_directory_service.get_agent(normalized_agent_id)
    timings["agentLookupMs"] = _elapsed_ms(stage_started_at)
    if not agent:
        _record_context_event(
            "agent_runtime.resolve_failed",
            outcome="failed",
            level="error",
            fields={
                "agentId": normalized_agent_id,
                "sessionId": str(session_id or "").strip(),
                "runId": str(run_id or "").strip(),
                "reason": "missing_agent",
                "source": "ContextEngine",
            },
        )
        return AgentContextPacket(
            agent_id=normalized_agent_id,
            session_id=session_id,
            run_id=run_id,
            timings={
                "reason": "missing_agent",
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
    if prompt_context_block:
        runtime_context_block = "\n\n".join(
            part
            for part in (runtime_context_block, research_org_context_block, prompt_context_block)
            if str(part or "").strip()
        )
    elif research_org_context_block:
        runtime_context_block = "\n\n".join(
            part for part in (runtime_context_block, research_org_context_block) if str(part or "").strip()
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
