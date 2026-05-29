"""AgentRun and SubAgentRun snapshot helpers built on WorkRunStore."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from core.chat.chat_task_types import trim_lines

from . import work_run_store


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


def result_status(result: dict[str, Any]) -> str:
    status = str(result.get("status") or result.get("currentPhase") or "").strip().lower()
    if status:
        return status
    if result.get("error") or result.get("errorType") or result.get("error_type"):
        return "failed"
    return "completed"


def result_summary(result: dict[str, Any]) -> str:
    raw = result.get("summary") or result.get("raw_output") or result.get("content") or result.get("message") or ""
    return _redact_sensitive_text(trim_lines(str(raw or ""), max_lines=4))


def persist_agent_run_snapshot(
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
    previous = _store().load_snapshot(AGENT_RUN_KIND, run_id) or {}
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
    return _store().persist_snapshot(AGENT_RUN_KIND, snapshot, active_run_id=active_run_id)


def persist_sub_agent_run_snapshot(
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
    previous = _store().load_snapshot(SUB_AGENT_RUN_KIND, run_id) or {}
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
    return _store().persist_snapshot(SUB_AGENT_RUN_KIND, snapshot, active_run_id=active_run_id)


def list_agent_runs_for_agent(agent_id: str, *, limit: int = 20) -> dict[str, Any]:
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


def _store() -> work_run_store.WorkRunStore:
    return work_run_store.WorkRunStore(root=work_run_store.WORK_RUNS_DIR)


def _load_work_run_snapshots(run_kind: str) -> list[dict[str, Any]]:
    return _store().list_snapshots(run_kind)


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


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _now_compact() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
