"""Context assembly boundary for long-lived Agent runtimes."""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines
from core.web.services.runtime_scene_service import record_runtime_scene_event


AGENT_RUN_KIND = "agent_run"
SUB_AGENT_RUN_KIND = "sub_agent_run"
_SAFE_RUN_FRAGMENT_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_ACTIVE_RUN_STATUSES = {"queued", "running", "stopping", "paused"}
_TERMINAL_RUN_STATUSES = {
    "completed",
    "done",
    "failed",
    "stopped",
    "cancelled",
    "paused_limit",
    "needs_continue",
    "stopped_by_user",
}
_PUBLIC_AGENT_RUN_KEYS = {
    "runId",
    "runKind",
    "sourceRunId",
    "agentId",
    "agentCode",
    "displayName",
    "primaryMode",
    "roleKey",
    "profileId",
    "promptTemplateId",
    "toolPolicyId",
    "memoryPolicyId",
    "workspacePath",
    "sessionId",
    "status",
    "currentPhase",
    "summary",
    "toolCallCount",
    "startedAt",
    "updatedAt",
    "finishedAt",
}
_PUBLIC_SUB_AGENT_RUN_KEYS = {
    "runId",
    "runKind",
    "parentRunId",
    "subRunId",
    "parentAgentId",
    "parentSessionId",
    "agentId",
    "contextMode",
    "status",
    "currentPhase",
    "summary",
    "toolCallCount",
    "depth",
    "maxDepth",
    "resultRef",
    "createdAt",
    "updatedAt",
    "endedAt",
}


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


@dataclass(frozen=True)
class SubAgentContextPacket:
    parent_agent_id: str
    parent_session_id: str
    context_mode: str
    parent_context: AgentContextPacket | None = None


def build_agent_context(agent_id: str, *, session_id: str = "", run_id: str = "", limit: int = 6) -> AgentContextPacket:
    """Build the bounded context packet used by a persistent Agent turn."""

    from core.web.services import agent_directory_service

    normalized_agent_id = str(agent_id or "").strip()
    agent = agent_directory_service.get_agent(normalized_agent_id)
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
        return AgentContextPacket(agent_id=normalized_agent_id, session_id=session_id, run_id=run_id)

    group_events = agent_directory_service.list_group_context_events_for_agent(
        normalized_agent_id,
        limit=limit,
        prompt_eligible_only=True,
    )
    inbox_messages = agent_directory_service.list_agent_inbox_messages_for_agent(
        normalized_agent_id,
        limit=limit,
        status="pending",
        prompt_eligible_only=True,
    )
    runtime_context_block = agent_directory_service.build_agent_runtime_context_block(normalized_agent_id, limit=limit)
    research_org_context_block = _build_research_organization_context_block(
        normalized_agent_id,
        limit=limit,
    )
    prompt_template_id = str(agent.get("promptTemplateId") or "").strip()
    prompt_context_block = _build_prompt_template_context_block(
        prompt_template_id,
        project_root=agent_directory_service.PROJECT_ROOT,
        agent_id=normalized_agent_id,
        session_id=str(session_id or "").strip(),
        run_id=str(run_id or "").strip(),
    )
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
        memory_policy=agent_directory_service.resolve_memory_policy_for_agent(normalized_agent_id),
        tool_policy=agent_directory_service.resolve_tool_policy_for_agent(normalized_agent_id),
        group_context_events=group_events,
        inbox_messages=inbox_messages,
        context_block=runtime_context_block,
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
    status = _result_status(result_payload)
    summary = _result_summary(result_payload)
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
    snapshot = _persist_agent_run_snapshot(
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
    status = _result_status(result_payload)
    summary = _result_summary(result_payload)
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
    snapshot = _persist_sub_agent_run_snapshot(
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

    normalized_agent_id = str(agent_id or "").strip()
    bounded_limit = _bounded_limit(limit)
    agent_runs = [
        _public_snapshot(item, _PUBLIC_AGENT_RUN_KEYS)
        for item in _load_work_run_snapshots(AGENT_RUN_KIND)
        if str(item.get("agentId") or "").strip() == normalized_agent_id
    ]
    sub_agent_runs = [
        _public_snapshot(item, _PUBLIC_SUB_AGENT_RUN_KEYS)
        for item in _load_work_run_snapshots(SUB_AGENT_RUN_KIND)
        if str(item.get("parentAgentId") or "").strip() == normalized_agent_id
        or str(item.get("agentId") or "").strip() == normalized_agent_id
    ]
    agent_runs.sort(key=_run_sort_key, reverse=True)
    sub_agent_runs.sort(key=_run_sort_key, reverse=True)
    return {
        "agentId": normalized_agent_id,
        "limit": bounded_limit,
        "runs": agent_runs[:bounded_limit],
        "subAgentRuns": sub_agent_runs[:bounded_limit],
    }


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


def _persist_agent_run_snapshot(
    agent: dict[str, Any],
    *,
    source_run_id: str,
    session_id: str,
    status: str,
    summary: str,
    tool_call_count: int,
    timestamp: str,
    result: dict[str, Any],
) -> dict[str, Any] | None:
    normalized_agent_id = str(agent.get("agentId") or "").strip()
    if not normalized_agent_id:
        return None
    run_id = _agent_run_id(normalized_agent_id, source_run_id)
    previous = _work_run_store().load_snapshot(AGENT_RUN_KIND, run_id) or {}
    started_at = str(result.get("startedAt") or result.get("createdAt") or previous.get("startedAt") or timestamp).strip()
    updated_at = str(result.get("updatedAt") or timestamp).strip()
    normalized_status = status or str(previous.get("status") or "completed").strip() or "completed"
    snapshot = {
        **previous,
        "runId": run_id,
        "runKind": AGENT_RUN_KIND,
        "sourceRunId": str(source_run_id or "").strip(),
        "agentId": normalized_agent_id,
        "agentCode": str(agent.get("agentCode") or "").strip(),
        "displayName": str(agent.get("displayName") or "").strip(),
        "primaryMode": str(agent.get("primaryMode") or "").strip(),
        "roleKey": str(agent.get("roleKey") or "").strip(),
        "profileId": str(agent.get("profileId") or "").strip(),
        "promptTemplateId": str(agent.get("promptTemplateId") or "").strip(),
        "toolPolicyId": str(agent.get("toolPolicyId") or "").strip(),
        "memoryPolicyId": str(agent.get("memoryPolicyId") or "").strip(),
        "workspacePath": str(agent.get("workspacePath") or "").strip(),
        "sessionId": str(session_id or "").strip(),
        "status": normalized_status,
        "currentPhase": normalized_status,
        "summary": summary,
        "toolCallCount": max(0, int(tool_call_count or 0)),
        "startedAt": started_at,
        "updatedAt": updated_at,
        "finishedAt": str(result.get("finishedAt") or "").strip()
        or (updated_at if normalized_status in _TERMINAL_RUN_STATUSES else ""),
    }
    active_run_id = run_id if normalized_status in _ACTIVE_RUN_STATUSES else ""
    return _work_run_store().persist_snapshot(AGENT_RUN_KIND, snapshot, active_run_id=active_run_id)


def _persist_sub_agent_run_snapshot(
    *,
    parent_run_id: str,
    sub_run_id: str,
    status: str,
    summary: str,
    tool_call_count: int,
    timestamp: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    run_id = _sub_agent_run_id(parent_run_id, sub_run_id)
    previous = _work_run_store().load_snapshot(SUB_AGENT_RUN_KIND, run_id) or {}
    normalized_status = status or str(previous.get("status") or "completed").strip() or "completed"
    updated_at = str(result.get("updatedAt") or timestamp).strip()
    snapshot = {
        **previous,
        "runId": run_id,
        "runKind": SUB_AGENT_RUN_KIND,
        "parentRunId": str(parent_run_id or "").strip(),
        "subRunId": str(sub_run_id or "").strip(),
        "parentAgentId": str(result.get("parentAgentId") or previous.get("parentAgentId") or "").strip(),
        "parentSessionId": str(result.get("parentSessionId") or previous.get("parentSessionId") or "").strip(),
        "agentId": str(result.get("agentId") or previous.get("agentId") or "").strip(),
        "contextMode": str(result.get("contextMode") or previous.get("contextMode") or "isolated").strip(),
        "status": normalized_status,
        "currentPhase": normalized_status,
        "summary": summary,
        "toolCallCount": max(0, int(tool_call_count or 0)),
        "depth": _safe_int(result.get("depth") or previous.get("depth")),
        "maxDepth": _safe_int(result.get("maxDepth") or previous.get("maxDepth")),
        "resultRef": str(result.get("resultRef") or previous.get("resultRef") or "").strip(),
        "createdAt": str(result.get("createdAt") or previous.get("createdAt") or timestamp).strip(),
        "updatedAt": updated_at,
        "endedAt": str(result.get("endedAt") or "").strip()
        or (updated_at if normalized_status in _TERMINAL_RUN_STATUSES else ""),
    }
    active_run_id = run_id if normalized_status in _ACTIVE_RUN_STATUSES else ""
    return _work_run_store().persist_snapshot(SUB_AGENT_RUN_KIND, snapshot, active_run_id=active_run_id)


def _work_run_store():
    from core.runtime_manager import work_run_store

    return work_run_store.WorkRunStore(root=work_run_store.WORK_RUNS_DIR)


def _load_work_run_snapshots(run_kind: str) -> list[dict[str, Any]]:
    store = _work_run_store()
    runs_dir = store.runs_dir(run_kind)
    if not runs_dir.exists():
        return []
    snapshots: list[dict[str, Any]] = []
    for path in sorted(runs_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            snapshots.append(payload)
    return snapshots


def _public_snapshot(snapshot: dict[str, Any], allowed_keys: set[str]) -> dict[str, Any]:
    return {key: snapshot.get(key) for key in sorted(allowed_keys) if key in snapshot}


def _run_sort_key(snapshot: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(snapshot.get("updatedAt") or ""),
        str(snapshot.get("finishedAt") or snapshot.get("endedAt") or ""),
        str(snapshot.get("startedAt") or snapshot.get("createdAt") or ""),
        str(snapshot.get("runId") or ""),
    )


def _agent_run_id(agent_id: str, source_run_id: str) -> str:
    return _bounded_run_id("agentrun", agent_id, source_run_id or _now_compact())


def _sub_agent_run_id(parent_run_id: str, sub_run_id: str) -> str:
    return _bounded_run_id("subagentrun", parent_run_id or "parent", sub_run_id or _now_compact())


def _bounded_run_id(prefix: str, first: str, second: str) -> str:
    first_fragment = _safe_run_fragment(first, fallback="ref")
    second_fragment = _safe_run_fragment(second, fallback="run")
    candidate = f"{prefix}-{first_fragment}-{second_fragment}"
    if len(candidate) <= 120:
        return candidate
    digest = hashlib.sha256(f"{first}\0{second}".encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{prefix}-{first_fragment[:48].rstrip('._-') or 'ref'}-{digest}"


def _safe_run_fragment(value: Any, *, fallback: str) -> str:
    raw = str(value or "").strip()
    token = _SAFE_RUN_FRAGMENT_RE.sub("-", raw).strip("._-")
    if not token:
        token = fallback
    if token != raw or len(token) > 80:
        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:10]
        token = f"{token[:64].rstrip('._-') or fallback}-{digest}"
    return token


def _result_status(result: dict[str, Any]) -> str:
    status = str(result.get("status") or result.get("currentPhase") or "").strip().lower()
    if status:
        return status
    if result.get("error") or result.get("errorType") or result.get("error_type"):
        return "failed"
    return "completed"


def _result_summary(result: dict[str, Any]) -> str:
    raw = result.get("summary") or result.get("raw_output") or result.get("content") or result.get("message") or ""
    return _redact_sensitive_text(trim_lines(str(raw or ""), max_lines=4))


def _redact_sensitive_text(text: str) -> str:
    redacted = str(text or "")
    redacted = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "sk-***", redacted)
    redacted = re.sub(
        r"(?i)\b(authorization)(\s*[:=]\s*)bearer\s+[^\s,;]+",
        lambda match: f"{match.group(1)}{match.group(2)}Bearer ***",
        redacted,
    )
    redacted = re.sub(
        r"(?i)\b(authorization)(\s*[:=]\s*)(?!bearer\b)([^\s,;]+)",
        lambda match: f"{match.group(1)}{match.group(2)}***",
        redacted,
    )
    redacted = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+", "Bearer ***", redacted)
    redacted = re.sub(
        r"(?i)\b(api[_-]?key|token|secret)(\s*[:=]\s*)([^\s,;]+)",
        lambda match: f"{match.group(1)}{match.group(2)}***",
        redacted,
    )
    return redacted


def _bounded_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 20
    return max(1, min(value, 100))


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
