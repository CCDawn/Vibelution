"""Research-project scoped, flat Agent session registry."""

from __future__ import annotations

import json
import threading
import urllib.parse
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
REGISTRY_FILE_NAME = "research_project_agent_sessions.json"
ACTIVE_TASK_STATUSES = {"queued", "running"}
TERMINAL_TASK_STATUSES = {
    "blocked",
    "canceled",
    "cancelled",
    "completed",
    "error",
    "failed",
    "incomplete",
    "stopped",
    "superseded",
    "timed_out",
    "timeout",
}
ROLE_LABELS = {
    "source_finder": "资料寻找",
    "source_extractor": "资料提炼",
    "source_relation_mapper": "资料关系整理",
    "source_ingestor": "资料入库",
    "challenge_cup_experiment_planner": "实验规划",
    "challenge_cup_experiment_ledger": "实验证据",
    "challenge_cup_iteration_planner": "迭代决策",
    "challenge_cup_versioning": "版本治理",
}
_REGISTRY_LOCK = threading.RLock()


class ResearchProjectAgentSessionError(RuntimeError):
    """Raised when a project Agent session cannot be resolved safely."""


def resolve_research_project_identity(
    team_id: str,
    research_project_id: str = "",
) -> dict[str, Any]:
    """Resolve an explicit project, or the team's active project for new work."""
    s = _service()
    normalized_project_id = _text(research_project_id)
    if normalized_project_id:
        return s.get_research_project(team_id, normalized_project_id)
    return s.get_active_research_project(team_id)


def resolve_research_project_identity_from_record(
    team_id: str,
    record: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve persisted work identity without depending on the current switcher."""
    s = _service()
    payload = record if isinstance(record, dict) else {}
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    metadata = (
        payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    )
    project_id = _text(
        payload.get("researchProjectId")
        or scope.get("researchProjectId")
        or metadata.get("researchProjectId")
    )
    if not project_id:
        project_id = s.LEGACY_PROJECT_ID
    return s.get_research_project(team_id, project_id)


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def _text(value: Any, *, limit: int = 160) -> str:
    return str(value or "").strip()[:limit]


def _positive_int(value: Any, *, default: int = 1) -> int:
    try:
        return max(1, int(value or default))
    except (TypeError, ValueError):
        return max(1, default)


def research_project_agent_role_label(
    role_key: str,
    agent: dict[str, Any] | None = None,
) -> str:
    """Return a stable responsibility label rather than the Agent's person name."""
    normalized_role_key = _text(role_key, limit=80)
    payload = agent if isinstance(agent, dict) else {}
    metadata = (
        payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    )
    explicit = _text(
        payload.get("roleLabel")
        or metadata.get("functionalDisplayName")
        or metadata.get("roleLabel"),
        limit=80,
    )
    if explicit:
        return explicit
    if normalized_role_key in ROLE_LABELS:
        return ROLE_LABELS[normalized_role_key]
    return normalized_role_key.replace("_", " ").strip() or "Agent"


def _registry_path(team_id: str, research_project_id: str) -> Path:
    s = _service()
    return (
        s.resolve_research_project_workspace_root(team_id, research_project_id)
        / REGISTRY_FILE_NAME
    )


def _empty_registry(team_id: str, research_project_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": _text(team_id),
        "researchProjectId": _text(research_project_id),
        "agents": {},
        "updatedAt": "",
    }


def _read_registry(team_id: str, research_project_id: str) -> dict[str, Any]:
    path = _registry_path(team_id, research_project_id)
    if not path.exists():
        return _empty_registry(team_id, research_project_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_registry(team_id, research_project_id)
    if not isinstance(payload, dict):
        return _empty_registry(team_id, research_project_id)
    agents = payload.get("agents") if isinstance(payload.get("agents"), dict) else {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": _text(team_id),
        "researchProjectId": _text(research_project_id),
        "agents": agents,
        "updatedAt": _text(payload.get("updatedAt"), limit=120),
    }


def _write_registry(
    team_id: str, research_project_id: str, registry: dict[str, Any]
) -> None:
    s = _service()
    registry["schemaVersion"] = SCHEMA_VERSION
    registry["teamId"] = _text(team_id)
    registry["researchProjectId"] = _text(research_project_id)
    registry["updatedAt"] = s.utc_now_iso()
    s._write_json(_registry_path(team_id, research_project_id), registry)


def _normalize_attempt(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "sessionId": _text(value.get("sessionId")),
        "agentId": _text(value.get("agentId")),
        "roleKey": _text(value.get("roleKey"), limit=80),
        "attempt": _positive_int(value.get("attempt")),
        "retryOfSessionId": _text(value.get("retryOfSessionId")),
        "createdFromTaskId": _text(value.get("createdFromTaskId")),
        "createdAt": _text(value.get("createdAt"), limit=120),
    }


def _session_binding(conversation: dict[str, Any]) -> dict[str, Any]:
    binding = conversation.get("experiment_binding")
    if not isinstance(binding, dict):
        binding = conversation.get("experimentBinding")
    return binding if isinstance(binding, dict) else {}


def _recover_agent_attempts(
    team_id: str,
    research_project_id: str,
    agent_id: str,
) -> list[dict[str, Any]]:
    """Recover a missing registry from durable session bindings."""
    s = _service()
    payload = s.session_service.load_chat_state(s.session_service.PROJECT_ROOT)
    conversations = (
        payload.get("conversations")
        if isinstance(payload.get("conversations"), list)
        else []
    )
    recovered: list[dict[str, Any]] = []
    for conversation in conversations:
        if not isinstance(conversation, dict):
            continue
        binding = _session_binding(conversation)
        if (
            _text(binding.get("teamId")) != team_id
            or _text(binding.get("researchProjectId")) != research_project_id
            or _text(binding.get("agentId")) != agent_id
        ):
            continue
        session_id = _text(
            conversation.get("conversation_id") or conversation.get("id")
        )
        if not session_id:
            continue
        recovered.append(
            _normalize_attempt(
                {
                    "sessionId": session_id,
                    "agentId": agent_id,
                    "roleKey": binding.get("roleKey"),
                    "attempt": binding.get("attempt"),
                    "retryOfSessionId": binding.get("retryOfSessionId"),
                    "createdFromTaskId": binding.get("createdFromTaskId"),
                    "createdAt": binding.get("createdAt")
                    or conversation.get("created_at"),
                }
            )
        )
    recovered.sort(
        key=lambda item: (int(item["attempt"]), item["createdAt"], item["sessionId"])
    )
    return recovered


def _agent_record(
    registry: dict[str, Any],
    *,
    team_id: str,
    research_project_id: str,
    agent_id: str,
    role_key: str,
) -> tuple[dict[str, Any], bool]:
    agents = registry.setdefault("agents", {})
    raw_record = agents.get(agent_id) if isinstance(agents.get(agent_id), dict) else {}
    attempts = [
        _normalize_attempt(item)
        for item in list(raw_record.get("attempts") or [])
        if isinstance(item, dict) and _text(item.get("sessionId"))
    ]
    if not attempts:
        attempts = _recover_agent_attempts(team_id, research_project_id, agent_id)
    attempts.sort(
        key=lambda item: (int(item["attempt"]), item["createdAt"], item["sessionId"])
    )
    record = {
        "agentId": agent_id,
        "roleKey": _text(raw_record.get("roleKey") or role_key, limit=80),
        "currentAttempt": int(attempts[-1]["attempt"]) if attempts else 0,
        "attempts": attempts,
    }
    changed = raw_record != record
    agents[agent_id] = record
    return record, changed


def _session_title(experiment_name: str, role_label: str, attempt: int) -> str:
    normalized_role_label = _text(role_label, limit=64) or "Agent"
    retry_suffix = f"｜重试 {attempt}" if attempt > 1 else ""
    suffix = f"｜{normalized_role_label}{retry_suffix}"
    available = max(1, 120 - len(suffix))
    normalized_experiment_name = _text(experiment_name, limit=240) or "未命名研究项目"
    return f"{normalized_experiment_name[:available]}{suffix}"


def _binding_payload(
    *,
    team_id: str,
    research_project_id: str,
    experiment_name: str,
    agent_id: str,
    role_key: str,
    role_label: str,
    attempt: int,
    retry_of_session_id: str,
    created_from_task_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Return the allowlisted, path/secret-free binding stored with a session."""
    return {
        "teamId": _text(team_id),
        "researchProjectId": _text(research_project_id),
        "experimentName": _text(experiment_name, limit=160),
        "agentId": _text(agent_id),
        "roleKey": _text(role_key, limit=80),
        "roleLabel": _text(role_label, limit=80),
        "attempt": _positive_int(attempt),
        "retryOfSessionId": _text(retry_of_session_id),
        "createdFromTaskId": _text(created_from_task_id),
        "createdAt": _text(created_at, limit=120),
    }


def _result_payload(
    *,
    project: dict[str, Any],
    attempt: dict[str, Any],
    session_title: str,
    session_created: bool,
) -> dict[str, Any]:
    session_id = _text(attempt.get("sessionId"))
    return {
        "researchProjectId": _text(project.get("projectId")),
        "experimentName": _text(project.get("name"), limit=160),
        "sessionId": session_id,
        "sessionTitle": _text(session_title, limit=120),
        "sessionAttempt": _positive_int(attempt.get("attempt")),
        "sessionCreated": bool(session_created),
        "retryOfSessionId": _text(attempt.get("retryOfSessionId")),
        "chatRoute": f"/chat?{urllib.parse.urlencode({'session': session_id})}",
    }


def resolve_research_project_agent_session(
    team_id: str,
    *,
    research_project_id: str,
    agent_id: str,
    role_key: str,
    role_label: str = "",
    created_from_task_id: str = "",
    formal_retry: bool = False,
    previous_task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve or create the flat session for one Agent in one research project."""
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_project_id = s._normalize_required_id(
        research_project_id,
        "Research project id is required.",
    )
    normalized_agent_id = s._normalize_required_id(agent_id, "Agent id is required.")
    project = s.get_research_project(normalized_team_id, normalized_project_id)
    agent = s.agent_directory_service.get_agent(normalized_agent_id)
    if not isinstance(agent, dict):
        raise ResearchProjectAgentSessionError(
            f"Agent not found: {normalized_agent_id}"
        )
    normalized_role_key = _text(role_key or agent.get("roleKey"), limit=80)
    normalized_role_label = _text(
        role_label or research_project_agent_role_label(normalized_role_key, agent),
        limit=80,
    )
    previous = previous_task if isinstance(previous_task, dict) else {}

    with _REGISTRY_LOCK:
        registry = _read_registry(normalized_team_id, normalized_project_id)
        record, recovered = _agent_record(
            registry,
            team_id=normalized_team_id,
            research_project_id=normalized_project_id,
            agent_id=normalized_agent_id,
            role_key=normalized_role_key,
        )
        current = record["attempts"][-1] if record["attempts"] else None
        if current is not None and not formal_retry:
            if recovered:
                _write_registry(normalized_team_id, normalized_project_id, registry)
            s.lock_research_project_name(
                normalized_team_id,
                normalized_project_id,
                reason="first_experiment_session",
            )
            detail = s.session_service.get_session_detail(current["sessionId"])
            title = _text((detail or {}).get("title"), limit=120) or _session_title(
                project["name"],
                normalized_role_label,
                int(current["attempt"]),
            )
            return _result_payload(
                project=project,
                attempt=current,
                session_title=title,
                session_created=False,
            )

        if current is not None and formal_retry:
            previous_status = _text(previous.get("status"), limit=80).lower()
            if previous_status in ACTIVE_TASK_STATUSES:
                raise ResearchProjectAgentSessionError(
                    "Formal retry cannot create another session while the previous task is still active."
                )
            if previous_status not in TERMINAL_TASK_STATUSES:
                raise ResearchProjectAgentSessionError(
                    "Formal retry requires the previous task to be in a terminal state."
                )
            previous_session_id = _text(previous.get("sessionId"))
            if not previous or previous_session_id != current["sessionId"]:
                raise ResearchProjectAgentSessionError(
                    "Formal retry must reference the current project Agent session."
                )

        attempt_number = int(current["attempt"]) + 1 if current is not None else 1
        retry_of_session_id = current["sessionId"] if current is not None else ""
        title = _session_title(project["name"], normalized_role_label, attempt_number)
        created_at = s.utc_now_iso()
        binding = _binding_payload(
            team_id=normalized_team_id,
            research_project_id=normalized_project_id,
            experiment_name=project["name"],
            agent_id=normalized_agent_id,
            role_key=normalized_role_key,
            role_label=normalized_role_label,
            attempt=attempt_number,
            retry_of_session_id=retry_of_session_id,
            created_from_task_id=created_from_task_id,
            created_at=created_at,
        )
        session = s.session_service.create_chat_session(
            title=title,
            agent_id=normalized_agent_id,
            created_by="research_project_agent_session",
            conversation_index_kind=s.agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
            experiment_binding=binding,
        )
        attempt = _normalize_attempt(
            {
                "sessionId": session.get("id"),
                "agentId": normalized_agent_id,
                "roleKey": normalized_role_key,
                "attempt": attempt_number,
                "retryOfSessionId": retry_of_session_id,
                "createdFromTaskId": created_from_task_id,
                "createdAt": created_at,
            }
        )
        record["roleKey"] = normalized_role_key
        record["attempts"].append(attempt)
        record["currentAttempt"] = attempt_number
        _write_registry(normalized_team_id, normalized_project_id, registry)
        s.lock_research_project_name(
            normalized_team_id,
            normalized_project_id,
            reason="first_experiment_session",
        )
        return _result_payload(
            project=project,
            attempt=attempt,
            session_title=title,
            session_created=True,
        )
