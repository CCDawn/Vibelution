"""Context assembly boundary for long-lived Agent runtimes."""

from __future__ import annotations

import json
import re
import hashlib
import threading
import time
import copy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.runtime_manager import agent_run_store
from core.web.services.runtime_scene_service import record_runtime_scene_event


AGENT_RUN_KIND = agent_run_store.AGENT_RUN_KIND
SUB_AGENT_RUN_KIND = agent_run_store.SUB_AGENT_RUN_KIND
_RESEARCH_ORG_CONTEXT_CACHE_TTL_SECONDS = 5.0
_RESEARCH_ORG_CONTEXT_CACHE_LOCK = threading.Lock()
_RESEARCH_ORG_CONTEXT_CACHE: dict[tuple[str, int, tuple[tuple[str, int, str], ...]], dict[str, Any]] = {}
_PROJECT_RULES_CONTEXT_CACHE_LOCK = threading.Lock()
_PROJECT_RULES_CONTEXT_CACHE: dict[tuple[str, int, int], str] = {}
_PROJECT_AGENT_REGISTRY_CACHE_LOCK = threading.Lock()
_PROJECT_AGENT_REGISTRY_CACHE: dict[tuple[str, int, int], dict[str, Any]] = {}
_ACTIVE_AGENT_DIRECTORY_CACHE_LOCK = threading.Lock()
_ACTIVE_AGENT_DIRECTORY_CACHE: dict[tuple[str, int, int], list[dict[str, Any]]] = {}


def _perf_counter() -> float:
    return time.perf_counter()


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((_perf_counter() - started_at) * 1000)))


def _file_signature(path: Path) -> tuple[str, int, int] | None:
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return (str(Path(path)), int(stat.st_mtime_ns), int(stat.st_size))


def _context_hash(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _context_segment(
    key: str,
    block: str,
    *,
    placement: str,
    stability: str,
    cache_hit: bool | None = None,
) -> dict[str, Any] | None:
    text = str(block or "").strip()
    if not text:
        return None
    return asdict(
        AgentContextSegment(
            key=str(key or "").strip(),
            block=text,
            placement=str(placement or "").strip(),
            stability=str(stability or "").strip(),
            chars=len(text),
            hash=_context_hash(text),
            cache_hit=cache_hit,
        )
    )


def _join_context_segments(segments: list[dict[str, Any]], placement: str) -> str:
    normalized_placement = str(placement or "").strip()
    return "\n\n".join(
        str(segment.get("block") or "").strip()
        for segment in list(segments or [])
        if str(segment.get("placement") or "").strip() == normalized_placement
        and str(segment.get("block") or "").strip()
    ).strip()


def _join_context_blocks(*blocks: str) -> str:
    return "\n\n".join(str(block or "").strip() for block in blocks if str(block or "").strip()).strip()


def _split_agent_runtime_context_block(block: str) -> tuple[str, str]:
    text = str(block or "").strip()
    if not text:
        return "", ""
    lines = text.splitlines()
    dynamic_markers = ("GroupContextEvents:", "AgentInboxMessages:")
    dynamic_start: int | None = None
    for index, line in enumerate(lines):
        stripped = str(line or "").strip()
        if any(stripped.startswith(marker) for marker in dynamic_markers):
            dynamic_start = index
            break
    if dynamic_start is None:
        return text, ""
    return "\n".join(lines[:dynamic_start]).strip(), "\n".join(lines[dynamic_start:]).strip()


def _context_segment_log_summary(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for segment in list(segments or []):
        if not isinstance(segment, dict):
            continue
        summary = {
            "key": str(segment.get("key") or "").strip(),
            "placement": str(segment.get("placement") or "").strip(),
            "stability": str(segment.get("stability") or "").strip(),
            "chars": _safe_int(segment.get("chars")),
            "hash": str(segment.get("hash") or "").strip(),
        }
        if segment.get("cache_hit") is not None:
            summary["cacheHit"] = bool(segment.get("cache_hit"))
        summaries.append(summary)
    return summaries


@dataclass(frozen=True)
class AgentContextSegment:
    key: str
    block: str
    placement: str
    stability: str
    chars: int = 0
    hash: str = ""
    cache_hit: bool | None = None


@dataclass(frozen=True)
class AgentContextPacket:
    agent_id: str
    agent_code: str = ""
    display_name: str = ""
    session_id: str = ""
    run_id: str = ""
    workspace_path: str = ""
    dialogue_model_id: str = ""
    prompt_template_id: str = ""
    role_key: str = ""
    memory_policy: dict[str, Any] = field(default_factory=dict)
    tool_policy: dict[str, Any] = field(default_factory=dict)
    group_context_events: list[dict[str, Any]] = field(default_factory=list)
    inbox_messages: list[dict[str, Any]] = field(default_factory=list)
    static_context_block: str = ""
    dynamic_context_block: str = ""
    context_segments: list[dict[str, Any]] = field(default_factory=list)
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
    raw_runtime_context_block = agent_directory_service.build_agent_runtime_context_block(normalized_agent_id, limit=limit)
    timings["runtimeContextBlockMs"] = _elapsed_ms(stage_started_at)
    agent_static_context_block, agent_dynamic_context_block = _split_agent_runtime_context_block(raw_runtime_context_block)
    research_org_context_block = ""
    if _agent_needs_research_organization_context(agent):
        stage_started_at = _perf_counter()
        research_org_result = _build_research_organization_context_block(
            normalized_agent_id,
            limit=limit,
        )
        research_org_context_block = research_org_result["contextBlock"]
        timings["researchOrgContextMs"] = _elapsed_ms(stage_started_at)
        timings["researchOrgContextCacheHit"] = research_org_result["cacheHit"]
        timings["researchOrgContextCacheAgeMs"] = research_org_result["cacheAgeMs"]
    else:
        timings["researchOrgContextMs"] = 0
        timings["researchOrgContextSkipped"] = True
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
    project_agent_registry_context_block = ""
    if _agent_allows_project_agent_registry_context(agent):
        stage_started_at = _perf_counter()
        project_agent_registry_context_block = _build_project_agent_registry_context_block(
            agent_directory_service.PROJECT_ROOT,
            current_agent=agent,
            session_id=str(session_id or "").strip(),
            run_id=str(run_id or "").strip(),
        )
        timings["projectAgentRegistryContextMs"] = _elapsed_ms(stage_started_at)
    else:
        timings["projectAgentRegistryContextMs"] = 0
        timings["projectAgentRegistryContextSkipped"] = True
    context_segments = [
        segment
        for segment in (
            _context_segment(
                "agent_runtime",
                agent_static_context_block,
                placement="cache_prefix",
                stability="agent_static",
            ),
            _context_segment(
                "research_organization",
                research_org_context_block,
                placement="cache_prefix",
                stability="project_static",
                cache_hit=timings.get("researchOrgContextCacheHit") if "researchOrgContextCacheHit" in timings else None,
            ),
            _context_segment(
                "prompt_template",
                prompt_context_block,
                placement="cache_prefix",
                stability="agent_static",
            ),
            _context_segment(
                "project_rules",
                project_rules_context_block,
                placement="cache_prefix",
                stability="project_static",
            ),
            _context_segment(
                "project_agent_registry",
                project_agent_registry_context_block,
                placement="volatile_turn",
                stability="turn_dynamic",
            ),
            _context_segment(
                "agent_messages",
                agent_dynamic_context_block,
                placement="volatile_turn",
                stability="turn_dynamic",
            ),
        )
        if segment is not None
    ]
    static_context_block = _join_context_segments(context_segments, "cache_prefix")
    dynamic_context_block = _join_context_segments(context_segments, "volatile_turn")
    runtime_context_block = _join_context_blocks(static_context_block, dynamic_context_block)
    stage_started_at = _perf_counter()
    memory_policy = agent_directory_service.resolve_memory_policy_for_agent(normalized_agent_id)
    timings["memoryPolicyMs"] = _elapsed_ms(stage_started_at)
    stage_started_at = _perf_counter()
    tool_policy = agent_directory_service.resolve_tool_policy_for_agent(normalized_agent_id)
    timings["toolPolicyMs"] = _elapsed_ms(stage_started_at)
    timings["staticContextChars"] = len(static_context_block)
    timings["dynamicContextChars"] = len(dynamic_context_block)
    timings["staticContextHash"] = _context_hash(static_context_block)
    timings["dynamicContextHash"] = _context_hash(dynamic_context_block)
    timings["contextSegmentCount"] = len(context_segments)
    timings["totalDurationMs"] = _elapsed_ms(context_started_at)
    packet = AgentContextPacket(
        agent_id=normalized_agent_id,
        agent_code=str(agent.get("agentCode") or "").strip(),
        display_name=str(agent.get("displayName") or "").strip(),
        session_id=str(session_id or "").strip(),
        run_id=str(run_id or "").strip(),
        workspace_path=str(agent.get("workspacePath") or "").strip(),
        dialogue_model_id=agent_directory_service.agent_dialogue_model_id(agent),
        prompt_template_id=prompt_template_id,
        role_key=str(agent.get("roleKey") or "").strip(),
        memory_policy=memory_policy,
        tool_policy=tool_policy,
        group_context_events=group_events,
        inbox_messages=inbox_messages,
        static_context_block=static_context_block,
        dynamic_context_block=dynamic_context_block,
        context_segments=context_segments,
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
            "dialogueModelId": packet.dialogue_model_id,
            "promptTemplateId": packet.prompt_template_id,
            "roleKey": packet.role_key,
            "groupContextEventCount": len(packet.group_context_events),
            "inboxMessageCount": len(packet.inbox_messages),
            "researchOrgContextIncluded": bool(research_org_context_block),
            "researchOrgContextCacheHit": bool(timings.get("researchOrgContextCacheHit")),
            "researchOrgContextCacheAgeMs": timings.get("researchOrgContextCacheAgeMs", 0),
            "projectRulesContextIncluded": bool(project_rules_context_block),
            "projectAgentRegistryContextIncluded": bool(project_agent_registry_context_block),
            "staticContextChars": timings["staticContextChars"],
            "dynamicContextChars": timings["dynamicContextChars"],
            "staticContextHash": timings["staticContextHash"],
            "dynamicContextHash": timings["dynamicContextHash"],
            "contextSegmentCount": timings["contextSegmentCount"],
            "contextSegments": _context_segment_log_summary(context_segments),
            "source": "ContextEngine",
        },
    )
    return packet


def _build_research_organization_context_block(agent_id: str, *, limit: int = 6) -> dict[str, Any]:
    """Return the research organization context block, logging service failures at the turn seam."""

    normalized_agent_id = str(agent_id or "").strip()
    bounded_limit = max(1, int(limit or 1))
    try:
        from core.web.services import agent_directory_service, research_organization_service

        project_root = Path(agent_directory_service.PROJECT_ROOT)
        signature = _research_organization_context_signature(project_root, research_organization_service)
        cache_key = (normalized_agent_id, bounded_limit, signature)
        now = _perf_counter()
        with _RESEARCH_ORG_CONTEXT_CACHE_LOCK:
            cached = _RESEARCH_ORG_CONTEXT_CACHE.get(cache_key)
            if cached:
                age_seconds = now - float(cached.get("createdAt") or 0)
                if 0 <= age_seconds <= _RESEARCH_ORG_CONTEXT_CACHE_TTL_SECONDS:
                    return {
                        "contextBlock": str(cached.get("contextBlock") or ""),
                        "cacheHit": True,
                        "cacheAgeMs": max(0, int(round(age_seconds * 1000))),
                    }
                _RESEARCH_ORG_CONTEXT_CACHE.pop(cache_key, None)

        context_block = research_organization_service.build_research_organization_context_block(
            normalized_agent_id,
            limit=bounded_limit,
        )
        signature = _research_organization_context_signature(project_root, research_organization_service)
        cache_key = (normalized_agent_id, bounded_limit, signature)
        with _RESEARCH_ORG_CONTEXT_CACHE_LOCK:
            _RESEARCH_ORG_CONTEXT_CACHE[cache_key] = {
                "createdAt": _perf_counter(),
                "contextBlock": context_block,
            }
        return {
            "contextBlock": str(context_block or ""),
            "cacheHit": False,
            "cacheAgeMs": 0,
        }
    except Exception as exc:
        _record_context_event(
            "agent_runtime.research_org_context_failed",
            outcome="failed",
            level="warning",
            fields={
                "agentId": normalized_agent_id,
                "reason": type(exc).__name__,
                "source": "ContextEngine",
            },
        )
        return {
            "contextBlock": "",
            "cacheHit": False,
            "cacheAgeMs": 0,
        }


def _research_organization_context_signature(
    project_root: Path,
    research_organization_service: Any,
) -> tuple[tuple[str, int, str], ...]:
    watched_paths = [
        Path(project_root) / "workspace" / "agents" / "agents.json",
    ]
    try:
        workspace = research_organization_service.get_workspace()
        getter = getattr(workspace, "get_research_organization_path", None)
        if callable(getter):
            watched_paths.append(Path(getter()))
    except Exception:
        watched_paths.append(Path(project_root) / "workspace" / "research" / "organization_graph.json")
    return tuple(_file_signature(path) for path in watched_paths)


def _file_signature(path: Path) -> tuple[str, int, str]:
    try:
        payload = Path(path).read_bytes()
    except OSError:
        return (str(path), -1, "")
    return (str(path), len(payload), hashlib.sha256(payload).hexdigest())


def _agent_needs_research_organization_context(agent: dict[str, Any]) -> bool:
    """Return true only for Agents that can reasonably belong to the research org graph."""

    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    primary_mode = str(agent.get("primaryMode") or metadata.get("primaryMode") or "").strip().lower()
    if primary_mode == "research":
        return True
    role_key = str(agent.get("roleKey") or metadata.get("roleKey") or "").strip().lower()
    if role_key.startswith("research_") or role_key in {"ceo", "organization_advisor", "capability_steward"}:
        return True
    prompt_template_id = str(agent.get("promptTemplateId") or metadata.get("promptTemplateId") or "").strip().lower()
    if prompt_template_id.startswith("prompt-research"):
        return True
    research_role = str(metadata.get("researchOrgRole") or metadata.get("systemRole") or "").strip()
    return bool(research_role)


def _agent_allows_project_agent_registry_context(agent: dict[str, Any]) -> bool:
    """Keep development-lane registry context out of product Agent prompts unless explicitly enabled."""

    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    for key in (
        "includeProjectAgentRegistryContext",
        "projectAgentRegistryContextEnabled",
        "runtimeProjectRegistryContext",
    ):
        value = metadata.get(key)
        if value is True:
            return True
        if str(value or "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


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


def list_agent_runs_for_agents(agent_ids: list[str], *, limit: int = 20) -> dict[str, Any]:
    """Return recent bounded AgentRun/SubAgentRun snapshots for many persistent Agents."""

    return agent_run_store.list_agent_runs_for_agents(agent_ids, limit=limit)


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
        is_default_chat_template = normalized == "prompt-chat-default"
        _record_context_event(
            "agent_runtime.prompt_template_empty_fallback" if is_default_chat_template else "agent_runtime.prompt_template_missing",
            outcome="empty_prompt_template" if is_default_chat_template else "missing_prompt_template",
            level="info" if is_default_chat_template else "warning",
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
    signature = _file_signature(agents_path)
    if signature is None:
        return ""
    with _PROJECT_RULES_CONTEXT_CACHE_LOCK:
        cached_block = _PROJECT_RULES_CONTEXT_CACHE.get(signature)
    if cached_block is not None:
        _record_context_event(
            "agent_runtime.project_rules_context_loaded",
            outcome="included",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "runId": run_id,
                "sourcePath": str(agents_path),
                "section": "Session-Level Agent Memory Coordination,Session Agent Territory And Handoff",
                "characterCount": len(cached_block),
                "cacheHit": True,
                "source": "ContextEngine",
            },
        )
        return cached_block
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
    with _PROJECT_RULES_CONTEXT_CACHE_LOCK:
        _PROJECT_RULES_CONTEXT_CACHE.clear()
        _PROJECT_RULES_CONTEXT_CACHE[signature] = block
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
            "cacheHit": False,
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
    active_agents, active_agent_cache_hit = _active_project_agents_from_directory(agent_directory_service)
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
            "cacheHit": bool(registry.get("_cacheHit")),
            "activeAgentDirectoryCacheHit": active_agent_cache_hit,
            "registryAgentCount": len(entries),
            "handoffTargetCount": len(handoff_entries),
            "source": "ContextEngine",
        },
    )
    return block


def _active_project_agents_from_directory(agent_directory_service: Any) -> tuple[list[dict[str, Any]], bool]:
    signature = _file_signature(agent_directory_service.registry_path())
    if signature is not None:
        with _ACTIVE_AGENT_DIRECTORY_CACHE_LOCK:
            cached = _ACTIVE_AGENT_DIRECTORY_CACHE.get(signature)
        if isinstance(cached, list):
            return copy.deepcopy(cached), True
    active_agents = [
        item
        for item in agent_directory_service.list_agents(include_archived=False)
        if isinstance(item, dict) and str(item.get("agentId") or "").strip()
    ]
    if signature is not None:
        with _ACTIVE_AGENT_DIRECTORY_CACHE_LOCK:
            _ACTIVE_AGENT_DIRECTORY_CACHE.clear()
            _ACTIVE_AGENT_DIRECTORY_CACHE[signature] = copy.deepcopy(active_agents)
    return active_agents, False


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
        return _default_project_agent_registry(registry_path.parent, auto_initialized=False)
    default_registry = _default_project_agent_registry(registry_path.parent)
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
    signature = _file_signature(registry_path)
    if signature is None:
        return {}
    with _PROJECT_AGENT_REGISTRY_CACHE_LOCK:
        cached = _PROJECT_AGENT_REGISTRY_CACHE.get(signature)
    if isinstance(cached, dict):
        payload = copy.deepcopy(cached)
        payload["_cacheHit"] = True
        return payload
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
    if not isinstance(payload, dict):
        return {}
    with _PROJECT_AGENT_REGISTRY_CACHE_LOCK:
        _PROJECT_AGENT_REGISTRY_CACHE.clear()
        _PROJECT_AGENT_REGISTRY_CACHE[signature] = copy.deepcopy(payload)
    payload["_cacheHit"] = False
    return payload


def _default_project_agent_registry(
    memory_dir: Path | None = None,
    *,
    auto_initialized: bool = True,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
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
        "laneTerritories": _default_project_agent_lane_territories(memory_dir),
        "agents": [],
    }


def _default_project_agent_lane_territories(memory_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    from_lanes = _project_agent_lane_territories_from_memory(memory_dir) if memory_dir else {}
    return from_lanes or _fallback_project_agent_lane_territories()


def _project_agent_lane_territories_from_memory(memory_dir: Path | None) -> dict[str, dict[str, Any]]:
    if not memory_dir:
        return {}
    lane_dir = Path(memory_dir) / "lanes"
    if not lane_dir.exists():
        return {}
    territories: dict[str, dict[str, Any]] = {}
    for lane_path in sorted(lane_dir.glob("*.json")):
        try:
            lane = json.loads(lane_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(lane, dict):
            continue
        lane_id = str(lane.get("id") or lane_path.stem).strip()
        if not lane_id:
            continue
        title = str(lane.get("title") or lane_id).strip()
        focus = str(lane.get("focus") or "").strip()
        summary = f"负责 {title}"
        if focus:
            summary = f"{summary}；当前焦点：{focus}"
        territories[lane_id] = {
            "managementScope": {
                "summary": summary,
                "files": _project_agent_lane_related_files(lane),
                "taskTypes": _project_agent_lane_task_types(lane_id, title),
            },
            "handoffTargets": _default_handoff_targets_for_lane(lane_id),
            "outOfScopePolicy": "recommend_handoff",
        }
    return territories


def _project_agent_lane_related_files(lane: dict[str, Any]) -> list[str]:
    files: list[str] = []
    for module in list(lane.get("modules") or [])[:8]:
        if not isinstance(module, dict):
            continue
        for item in list(module.get("relatedFiles") or []):
            value = str(item or "").strip()
            if value and value not in files:
                files.append(value)
            if len(files) >= 8:
                return files
    return files


def _project_agent_lane_task_types(lane_id: str, title: str) -> list[str]:
    task_types: list[str] = []
    for part in re.split(r"[^A-Za-z0-9]+", f"{lane_id} {title}".lower()):
        value = str(part or "").strip()
        if value and value not in task_types:
            task_types.append(value)
        if len(task_types) >= 6:
            break
    return task_types


def _default_handoff_targets_for_lane(lane_id: str) -> list[str]:
    defaults = [
        "agent-runtime-core",
        "chat-coding-surface",
        "web-workbench-surface",
        "quality-and-operations",
        "evolution-control-plane",
        "self-evolution-loop",
    ]
    return [item for item in defaults if item != lane_id][:3]


def _fallback_project_agent_lane_territories() -> dict[str, dict[str, Any]]:
    return {
        "agent-runtime-core": {
            "managementScope": {
                "summary": "负责 Agent 运行主干、上下文装配、身份绑定、工具/记忆/委托策略。",
                "files": ["core/orchestration/**", "core/runtime_manager/**", "agent.py"],
                "taskTypes": [
                    "runtime-context",
                    "agent-directory",
                    "memory-policy",
                    "tool-policy",
                    "delegation",
                ],
            },
            "handoffTargets": ["chat-coding-surface", "quality-and-operations"],
            "outOfScopePolicy": "recommend_handoff",
        },
        "chat-coding-surface": {
            "managementScope": {
                "summary": "负责 Chat/Coding 会话、群聊、消息生命周期和前端对话体验。",
                "files": [
                    "core/web/services/session_service.py",
                    "core/web/services/chat_room_service.py",
                    "web/src/routes/**",
                ],
                "taskTypes": [
                    "chat-session",
                    "group-chat",
                    "message-lifecycle",
                    "conversation-ui",
                ],
            },
            "handoffTargets": ["agent-runtime-core", "web-workbench-surface"],
            "outOfScopePolicy": "recommend_handoff",
        },
        "quality-and-operations": {
            "managementScope": {
                "summary": "负责测试、日志、诊断、发布收口和工作树卫生。",
                "files": ["tests/**", "logs/runtime_scenes/**", ".docs/project-memory/**"],
                "taskTypes": [
                    "testing",
                    "logging",
                    "diagnosis",
                    "release",
                    "git-hygiene",
                ],
            },
            "handoffTargets": ["agent-runtime-core", "chat-coding-surface"],
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
    llm_bindings = json.dumps(agent.get("llmBindings") or {}, ensure_ascii=False, sort_keys=True)
    haystack = " ".join([primary_mode, role_key, prompt_template_id, llm_bindings]).lower()
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
    return datetime.now(timezone.utc).isoformat()


def _now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")


def packet_to_dict(packet: AgentContextPacket | SubAgentContextPacket) -> dict[str, Any]:
    return asdict(packet)
