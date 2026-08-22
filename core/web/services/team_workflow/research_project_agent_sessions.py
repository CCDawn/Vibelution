"""Research-project Agent session registry with exact workflow-node scopes."""

from __future__ import annotations

import json
import threading
import urllib.parse
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.research.workflow.contracts.research_team_role_contract import (
    CURRENT_RESEARCH_TEAM_ROLE_CONTRACT,
)
from core.research.workflow.contracts.session_scope import (
    ContractValidationError,
    WorkflowSessionScopeV3,
)

SCHEMA_VERSION = 3
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
    **{
        role.product_role_id: role.label
        for role in CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.product_agents
    },
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
        "workflowNodes": {},
        "workflowCandidates": {},
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
    workflow_nodes = (
        payload.get("workflowNodes")
        if isinstance(payload.get("workflowNodes"), dict)
        else {}
    )
    workflow_candidates = (
        payload.get("workflowCandidates")
        if isinstance(payload.get("workflowCandidates"), dict)
        else {}
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": _text(team_id),
        "researchProjectId": _text(research_project_id),
        "agents": agents,
        "workflowNodes": workflow_nodes,
        "workflowCandidates": workflow_candidates,
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
    normalized = {
        "sessionId": _text(value.get("sessionId")),
        "agentId": _text(value.get("agentId")),
        "roleKey": _text(value.get("roleKey"), limit=80),
        "attempt": _positive_int(value.get("attempt")),
        "retryOfSessionId": _text(value.get("retryOfSessionId")),
        "createdFromTaskId": _text(value.get("createdFromTaskId")),
        "createdAt": _text(value.get("createdAt"), limit=120),
    }
    recovery_reason = _text(value.get("recoveryReason"), limit=80)
    if recovery_reason:
        normalized["recoveryReason"] = recovery_reason
    workflow_run_id = _text(value.get("workflowRunId"))
    workflow_node_id = _text(value.get("workflowNodeId"), limit=80)
    if workflow_run_id and workflow_node_id:
        normalized["workflowRunId"] = workflow_run_id
        normalized["workflowNodeId"] = workflow_node_id
    selection_id = _text(value.get("selectionId"))
    candidate_id = _text(value.get("candidateId"))
    if selection_id and candidate_id:
        normalized["selectionId"] = selection_id
        normalized["candidateId"] = candidate_id
    scope = value.get("scope")
    if isinstance(scope, dict):
        normalized_scope = dict(scope)
        normalized_scope.pop("attempt", None)
        if normalized_scope:
            normalized["scope"] = normalized_scope
    return normalized


def _session_binding(conversation: dict[str, Any]) -> dict[str, Any]:
    binding = conversation.get("experiment_binding")
    if not isinstance(binding, dict):
        binding = conversation.get("experimentBinding")
    return binding if isinstance(binding, dict) else {}


def _canonical_root_detail_matches_session(
    detail: Mapping[str, Any] | None,
    session_id: str,
) -> bool:
    """Return whether a session detail is safe to use as a node root.

    The v2 root binding did not carry a structured scope, so this check is
    deliberately limited to the canonical Chat lineage fields. Missing
    ``sessionKind``/``rootSessionId`` remains compatible with those rows;
    child/supervised rows, parented rows, and rows naming another root do not.
    """

    normalized_session_id = _text(session_id)
    if not normalized_session_id or not isinstance(detail, Mapping):
        return False
    session_kind = _text(
        detail.get("sessionKind") or detail.get("session_kind"),
        limit=40,
    ).lower()
    if session_kind and session_kind != "main":
        return False
    parent_session_id = _text(
        detail.get("parentSessionId") or detail.get("parent_session_id")
    )
    if parent_session_id:
        return False
    root_session_id = _text(
        detail.get("rootSessionId") or detail.get("root_session_id")
    )
    return not root_session_id or root_session_id == normalized_session_id


def _recover_agent_attempts(
    team_id: str,
    research_project_id: str,
    agent_id: str,
    *,
    workflow_run_id: str = "",
    workflow_node_id: str = "",
    selection_id: str = "",
    candidate_id: str = "",
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
        session_id = _text(
            conversation.get("conversation_id") or conversation.get("conversationId")
            or conversation.get("id")
        )
        if not session_id:
            continue
        binding = _session_binding(conversation)
        if (
            _text(binding.get("teamId")) != team_id
            or _text(binding.get("researchProjectId")) != research_project_id
            or _text(binding.get("agentId")) != agent_id
            or _text(binding.get("workflowRunId")) != workflow_run_id
            or _text(binding.get("workflowNodeId"), limit=80)
            != workflow_node_id
        ):
            continue
        binding_selection_id = _text(binding.get("selectionId"))
        binding_candidate_id = _text(binding.get("candidateId"))
        if selection_id or candidate_id:
            if (
                binding_selection_id != selection_id
                or binding_candidate_id != candidate_id
            ):
                continue
            session_kind = _text(
                conversation.get("sessionKind") or conversation.get("session_kind"),
                limit=40,
            ).lower()
            if session_kind != "child":
                continue
            hidden_from_index = conversation.get("hiddenFromIndex")
            if hidden_from_index is None:
                hidden_from_index = conversation.get("hidden_from_index")
            if hidden_from_index not in (True, 1):
                continue
            parent_session_id = _text(
                conversation.get("parentSessionId")
                or conversation.get("parent_session_id")
            )
            root_session_id = _text(
                conversation.get("rootSessionId")
                or conversation.get("root_session_id")
            )
            if not parent_session_id or parent_session_id != root_session_id:
                continue
        elif binding_selection_id or binding_candidate_id:
            # A node root must never recover a candidate child as its own
            # session when the registry is rebuilt from durable bindings.
            continue
        elif not _canonical_root_detail_matches_session(conversation, session_id):
            # Durable recovery must not turn a hidden child/supervised session
            # or a malformed lineage row into the formal node root.
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
                    "workflowRunId": workflow_run_id,
                    "workflowNodeId": workflow_node_id,
                    "selectionId": selection_id,
                    "candidateId": candidate_id,
                    "scope": binding.get("scope"),
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
    workflow_run_id: str = "",
    workflow_node_id: str = "",
    selection_id: str = "",
    candidate_id: str = "",
) -> tuple[dict[str, Any], bool]:
    if workflow_run_id and workflow_node_id and selection_id and candidate_id:
        records = registry.setdefault("workflowCandidates", {})
        record_key = WorkflowSessionScopeV3.candidate(
            teamId=team_id,
            researchProjectId=research_project_id,
            agentId=agent_id,
            workflowRunId=workflow_run_id,
            workflowNodeId=workflow_node_id,
            selectionId=selection_id,
            candidateId=candidate_id,
        ).key
    elif workflow_run_id and workflow_node_id:
        records = registry.setdefault("workflowNodes", {})
        record_key = f"{agent_id}::{workflow_run_id}::{workflow_node_id}"
    else:
        records = registry.setdefault("agents", {})
        record_key = agent_id
    raw_record = (
        records.get(record_key)
        if isinstance(records.get(record_key), dict)
        else {}
    )
    attempts = [
        _normalize_attempt(item)
        for item in list(raw_record.get("attempts") or [])
        if isinstance(item, dict) and _text(item.get("sessionId"))
    ]
    if not attempts:
        attempts = _recover_agent_attempts(
            team_id,
            research_project_id,
            agent_id,
            workflow_run_id=workflow_run_id,
            workflow_node_id=workflow_node_id,
            selection_id=selection_id,
            candidate_id=candidate_id,
        )
    attempts.sort(
        key=lambda item: (int(item["attempt"]), item["createdAt"], item["sessionId"])
    )
    record = {
        "agentId": agent_id,
        "roleKey": _text(raw_record.get("roleKey") or role_key, limit=80),
        "currentAttempt": int(attempts[-1]["attempt"]) if attempts else 0,
        "attempts": attempts,
    }
    if workflow_run_id and workflow_node_id:
        record["workflowRunId"] = workflow_run_id
        record["workflowNodeId"] = workflow_node_id
    if selection_id and candidate_id:
        record["selectionId"] = selection_id
        record["candidateId"] = candidate_id
    changed = raw_record != record
    records[record_key] = record
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
    workflow_run_id: str = "",
    workflow_node_id: str = "",
    selection_id: str = "",
    candidate_id: str = "",
    scope: WorkflowSessionScopeV3 | None = None,
    recovery_reason: str = "",
) -> dict[str, Any]:
    """Return the allowlisted, path/secret-free binding stored with a session."""
    binding = {
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
    normalized_recovery_reason = _text(recovery_reason, limit=80)
    if normalized_recovery_reason:
        binding["recoveryReason"] = normalized_recovery_reason
    if workflow_run_id and workflow_node_id:
        binding["workflowRunId"] = _text(workflow_run_id)
        binding["workflowNodeId"] = _text(workflow_node_id, limit=80)
    if selection_id and candidate_id:
        binding["selectionId"] = _text(selection_id)
        binding["candidateId"] = _text(candidate_id)
    if scope is not None:
        binding["scope"] = scope.to_dict()
    return binding


def _result_payload(
    *,
    project: dict[str, Any],
    attempt: dict[str, Any],
    session_title: str,
    session_created: bool,
    detail: dict[str, Any] | None = None,
    scope: WorkflowSessionScopeV3 | None = None,
    parent_session_id: str = "",
) -> dict[str, Any]:
    session_id = _text(attempt.get("sessionId"))
    result = {
        "researchProjectId": _text(project.get("projectId")),
        "experimentName": _text(project.get("name"), limit=160),
        "sessionId": session_id,
        "sessionTitle": _text(session_title, limit=120),
        "sessionAttempt": _positive_int(attempt.get("attempt")),
        "sessionCreated": bool(session_created),
        "retryOfSessionId": _text(attempt.get("retryOfSessionId")),
        "chatRoute": f"/chat?{urllib.parse.urlencode({'session': session_id})}",
    }
    recovery_reason = _text(attempt.get("recoveryReason"), limit=80)
    if recovery_reason:
        result["recoveryReason"] = recovery_reason
    if scope is not None:
        result["scope"] = scope.to_dict()
        result["scopeKey"] = scope.key
    if isinstance(detail, dict):
        result["sessionKind"] = _text(detail.get("sessionKind"), limit=40) or (
            "child" if scope is not None and scope.is_candidate else "main"
        )
        result["hiddenFromIndex"] = bool(detail.get("hiddenFromIndex"))
        result["parentSessionId"] = _text(
            detail.get("parentSessionId") or parent_session_id
        )
        result["rootSessionId"] = _text(detail.get("rootSessionId"))
    elif parent_session_id:
        result["sessionKind"] = "child"
        result["hiddenFromIndex"] = True
        result["parentSessionId"] = _text(parent_session_id)
        result["rootSessionId"] = _text(parent_session_id)
    return result


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
    recover_missing_session: bool = False,
    workflow_run_id: str = "",
    workflow_node_id: str = "",
    selection_id: str = "",
    candidate_id: str = "",
    scope: WorkflowSessionScopeV3 | Mapping[str, Any] | None = None,
    selected_candidate_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve a flat, node-root, or candidate-scoped Agent session.

    ``workflowRunId`` + ``workflowNodeId`` identify the node root.  Adding
    ``selectionId`` + ``candidateId`` switches the logical scope to a hidden
    child session whose parent is that node root.  The legacy node arguments
    remain accepted so existing stage callers keep their v2 behavior.
    """
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_project_id = s._normalize_required_id(
        research_project_id,
        "Research project id is required.",
    )
    normalized_agent_id = s._normalize_required_id(agent_id, "Agent id is required.")
    if scope is not None:
        normalized_scope = (
            scope
            if isinstance(scope, WorkflowSessionScopeV3)
            else WorkflowSessionScopeV3.from_mapping(scope)
        )
        if (
            normalized_scope.teamId != normalized_team_id
            or normalized_scope.researchProjectId != normalized_project_id
            or normalized_scope.agentId != normalized_agent_id
        ):
            raise ResearchProjectAgentSessionError(
                "Workflow session scope identity does not match the resolver owner."
            )
        workflow_run_id = normalized_scope.workflowRunId
        workflow_node_id = normalized_scope.workflowNodeId
        selection_id = normalized_scope.selectionId
        candidate_id = normalized_scope.candidateId
    normalized_workflow_run_id = _text(workflow_run_id)
    normalized_workflow_node_id = _text(workflow_node_id, limit=80)
    normalized_selection_id = _text(selection_id)
    normalized_candidate_id = _text(candidate_id)
    if bool(normalized_workflow_run_id) != bool(normalized_workflow_node_id):
        raise ResearchProjectAgentSessionError(
            "Formal workflow sessions require both workflowRunId and workflowNodeId."
        )
    if bool(normalized_selection_id) != bool(normalized_candidate_id):
        raise ResearchProjectAgentSessionError(
            "Candidate workflow sessions require both selectionId and candidateId."
        )
    if selected_candidate_ids is not None:
        normalized_selected_candidate_ids = {
            _text(item) for item in selected_candidate_ids if _text(item)
        }
        if normalized_candidate_id not in normalized_selected_candidate_ids:
            raise ResearchProjectAgentSessionError(
                "candidateId must belong to the selected candidate set."
            )
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
    root_scope = (
        WorkflowSessionScopeV3.root(
            teamId=normalized_team_id,
            researchProjectId=normalized_project_id,
            agentId=normalized_agent_id,
            workflowRunId=normalized_workflow_run_id,
            workflowNodeId=normalized_workflow_node_id,
        )
        if normalized_workflow_run_id and normalized_workflow_node_id
        else None
    )
    candidate_scope = (
        WorkflowSessionScopeV3.candidate(
            teamId=normalized_team_id,
            researchProjectId=normalized_project_id,
            agentId=normalized_agent_id,
            workflowRunId=normalized_workflow_run_id,
            workflowNodeId=normalized_workflow_node_id,
            selectionId=normalized_selection_id,
            candidateId=normalized_candidate_id,
        )
        if normalized_selection_id and normalized_candidate_id
        else None
    )
    previous = previous_task if isinstance(previous_task, dict) else {}
    missing_session_recovery = False

    if candidate_scope is not None:
        return _resolve_candidate_session(
            team_id=normalized_team_id,
            research_project_id=normalized_project_id,
            agent_id=normalized_agent_id,
            project=project,
            role_key=normalized_role_key,
            role_label=normalized_role_label,
            created_from_task_id=created_from_task_id,
            formal_retry=formal_retry,
            previous_task=previous,
            recover_missing_session=recover_missing_session,
            root_scope=root_scope,
            candidate_scope=candidate_scope,
        )

    with _REGISTRY_LOCK:
        registry = _read_registry(normalized_team_id, normalized_project_id)
        record, recovered = _agent_record(
            registry,
            team_id=normalized_team_id,
            research_project_id=normalized_project_id,
            agent_id=normalized_agent_id,
            role_key=normalized_role_key,
            workflow_run_id=normalized_workflow_run_id,
            workflow_node_id=normalized_workflow_node_id,
        )
        current = record["attempts"][-1] if record["attempts"] else None
        if current is not None and not formal_retry:
            detail = s.session_service.get_session_detail(current["sessionId"])
            if not isinstance(detail, dict):
                if not recover_missing_session:
                    raise ResearchProjectAgentSessionError(
                        "Project Agent session registry points to a missing canonical session: "
                        f"{current['sessionId']}. A formal retry with terminal task lineage is required."
                    )
                formal_retry = True
                missing_session_recovery = True
            elif not _canonical_root_detail_matches_session(
                detail,
                current["sessionId"],
            ):
                raise ResearchProjectAgentSessionError(
                    "Project Agent session registry points to a non-canonical root session: "
                    f"{current['sessionId']}. Child/supervised or mismatched-lineage sessions cannot be used as a node root."
                )
            else:
                if recovered:
                    _write_registry(normalized_team_id, normalized_project_id, registry)
                s.lock_research_project_name(
                    normalized_team_id,
                    normalized_project_id,
                    reason="first_experiment_session",
                )
                title = _text(detail.get("title"), limit=120) or _session_title(
                    project["name"],
                    normalized_role_label,
                    int(current["attempt"]),
                )
                return _result_payload(
                    project=project,
                    attempt=current,
                    session_title=title,
                    session_created=False,
                    detail=detail,
                    scope=root_scope,
                )

        if current is not None and formal_retry and not missing_session_recovery:
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
            workflow_run_id=normalized_workflow_run_id,
            workflow_node_id=normalized_workflow_node_id,
            scope=root_scope,
            recovery_reason=(
                "missing_canonical_session" if missing_session_recovery else ""
            ),
        )
        session = s.session_service.create_chat_session(
            title=title,
            agent_id=normalized_agent_id,
            created_by="research_project_agent_session",
            conversation_index_kind=s.agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
            experiment_binding=binding,
        )
        created_session_id = _text(session.get("id"))
        canonical_detail = (
            s.session_service.get_session_detail(created_session_id)
            if created_session_id
            else None
        )
        canonical_agent_id = _text(
            canonical_detail.get("agentId") if isinstance(canonical_detail, dict) else ""
        )
        canonical_binding = (
            canonical_detail.get("experimentBinding")
            if isinstance(canonical_detail, dict)
            and isinstance(canonical_detail.get("experimentBinding"), dict)
            else {}
        )
        if (
            not isinstance(canonical_detail, dict)
            or not _canonical_root_detail_matches_session(
                canonical_detail,
                created_session_id,
            )
            or canonical_agent_id != normalized_agent_id
            or _text(canonical_binding.get("teamId")) != normalized_team_id
            or _text(canonical_binding.get("researchProjectId")) != normalized_project_id
            or _text(canonical_binding.get("workflowRunId"))
            != normalized_workflow_run_id
            or _text(canonical_binding.get("workflowNodeId"), limit=80)
            != normalized_workflow_node_id
        ):
            raise ResearchProjectAgentSessionError(
                "New project Agent session is missing from the canonical session index; "
                "the registry was not updated. Retry only after the session authority error is repaired."
            )
        attempt = _normalize_attempt(
            {
                "sessionId": created_session_id,
                "agentId": normalized_agent_id,
                "roleKey": normalized_role_key,
                "attempt": attempt_number,
                "retryOfSessionId": retry_of_session_id,
                "createdFromTaskId": created_from_task_id,
                "createdAt": created_at,
                "workflowRunId": normalized_workflow_run_id,
                "workflowNodeId": normalized_workflow_node_id,
                "scope": root_scope.to_dict() if root_scope is not None else None,
                "recoveryReason": (
                    "missing_canonical_session" if missing_session_recovery else ""
                ),
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
            detail=canonical_detail,
            scope=root_scope,
        )


def _candidate_session_title(
    experiment_name: str,
    role_label: str,
    candidate_id: str,
    attempt: int,
) -> str:
    """Build a readable child title without making it part of identity."""

    retry_suffix = f"｜重试 {attempt}" if attempt > 1 else ""
    suffix = f"｜{_text(role_label, limit=48) or '假说'}｜{_text(candidate_id, limit=48)}{retry_suffix}"
    available = max(1, 120 - len(suffix))
    return f"{(_text(experiment_name, limit=240) or '未命名研究项目')[:available]}{suffix}"


def _candidate_detail_matches_scope(
    detail: dict[str, Any] | None,
    *,
    scope: WorkflowSessionScopeV3,
    root_session_id: str,
) -> bool:
    """Fail closed unless the canonical public child projection matches scope."""

    if not isinstance(detail, dict):
        return False
    detail_agent_id = _text(detail.get("agentId"))
    if detail_agent_id != scope.agentId:
        return False
    detail_kind = _text(detail.get("sessionKind"), limit=40).lower()
    if detail_kind != "child":
        return False
    if detail.get("hiddenFromIndex") is not True:
        return False
    detail_parent_id = _text(detail.get("parentSessionId"))
    detail_root_id = _text(detail.get("rootSessionId"))
    if detail_parent_id != root_session_id or detail_root_id != root_session_id:
        return False
    binding = detail.get("experimentBinding")
    if not isinstance(binding, dict):
        return False
    if _text(binding.get("selectionId")) != scope.selectionId:
        return False
    if _text(binding.get("candidateId")) != scope.candidateId:
        return False
    raw_scope = binding.get("scope")
    if not isinstance(raw_scope, dict):
        return False
    try:
        return WorkflowSessionScopeV3.from_mapping(raw_scope).key == scope.key
    except ContractValidationError:
        return False


def _public_candidate_detail(
    detail: dict[str, Any] | None,
    *,
    scope: WorkflowSessionScopeV3,
) -> dict[str, Any] | None:
    """Attach the structured scope to this resolver's canonical projection.

    Older public session projection code only exposes the v2 binding fields;
    the durable raw row remains the authority and this bounded projection keeps
    the resolver response diagnosable until the general DTO is upgraded.
    """

    if not isinstance(detail, dict):
        return None
    projected = dict(detail)
    binding = dict(projected.get("experimentBinding") or {})
    binding["selectionId"] = scope.selectionId
    binding["candidateId"] = scope.candidateId
    binding["scope"] = scope.to_dict()
    projected["experimentBinding"] = binding
    projected["scope"] = scope.to_dict()
    projected["scopeKey"] = scope.key
    return projected


def _resolve_candidate_session(
    *,
    team_id: str,
    research_project_id: str,
    agent_id: str,
    project: dict[str, Any],
    role_key: str,
    role_label: str,
    created_from_task_id: str,
    formal_retry: bool,
    previous_task: dict[str, Any],
    recover_missing_session: bool,
    root_scope: WorkflowSessionScopeV3,
    candidate_scope: WorkflowSessionScopeV3,
) -> dict[str, Any]:
    """Resolve one candidate child without ever falling back to the root."""

    s = _service()
    root_result = resolve_research_project_agent_session(
        team_id,
        research_project_id=research_project_id,
        agent_id=agent_id,
        role_key=role_key,
        role_label=role_label,
        created_from_task_id=created_from_task_id,
        recover_missing_session=recover_missing_session,
        workflow_run_id=root_scope.workflowRunId,
        workflow_node_id=root_scope.workflowNodeId,
    )
    root_session_id = _text(root_result.get("sessionId"))
    if not root_session_id:
        raise ResearchProjectAgentSessionError(
            "Candidate workflow session requires a canonical node root session."
        )

    missing_session_recovery = False
    with _REGISTRY_LOCK:
        registry = _read_registry(team_id, research_project_id)
        record, recovered = _agent_record(
            registry,
            team_id=team_id,
            research_project_id=research_project_id,
            agent_id=agent_id,
            role_key=role_key,
            workflow_run_id=candidate_scope.workflowRunId,
            workflow_node_id=candidate_scope.workflowNodeId,
            selection_id=candidate_scope.selectionId,
            candidate_id=candidate_scope.candidateId,
        )
        current = record["attempts"][-1] if record["attempts"] else None
        if current is not None and not formal_retry:
            detail = s.session_service.get_session_detail(current["sessionId"])
            if not _candidate_detail_matches_scope(
                detail,
                scope=candidate_scope,
                root_session_id=root_session_id,
            ):
                if not recover_missing_session:
                    raise ResearchProjectAgentSessionError(
                        "Project Agent candidate session registry points to a missing or mismatched canonical session: "
                        f"{current['sessionId']}. A formal retry with terminal task lineage is required."
                    )
                formal_retry = True
                missing_session_recovery = True
            else:
                if recovered:
                    _write_registry(team_id, research_project_id, registry)
                title = _text(detail.get("title"), limit=120) or _candidate_session_title(
                    project["name"],
                    role_label,
                    candidate_scope.candidateId,
                    int(current["attempt"]),
                )
                projected = _public_candidate_detail(detail, scope=candidate_scope)
                return _result_payload(
                    project=project,
                    attempt=current,
                    session_title=title,
                    session_created=False,
                    detail=projected,
                    scope=candidate_scope,
                    parent_session_id=root_session_id,
                )

        if current is not None and formal_retry and not missing_session_recovery:
            previous_status = _text(previous_task.get("status"), limit=80).lower()
            if previous_status in ACTIVE_TASK_STATUSES:
                raise ResearchProjectAgentSessionError(
                    "Formal retry cannot create another candidate session while the previous task is still active."
                )
            if previous_status not in TERMINAL_TASK_STATUSES:
                raise ResearchProjectAgentSessionError(
                    "Formal retry requires the previous candidate task to be in a terminal state."
                )
            previous_session_id = _text(previous_task.get("sessionId"))
            if previous_session_id != current["sessionId"]:
                raise ResearchProjectAgentSessionError(
                    "Formal retry must reference the current candidate project Agent session."
                )

        attempt_number = int(current["attempt"]) + 1 if current is not None else 1
        retry_of_session_id = current["sessionId"] if current is not None else ""
        title = _candidate_session_title(
            project["name"],
            role_label,
            candidate_scope.candidateId,
            attempt_number,
        )
        created_at = s.utc_now_iso()
        binding = _binding_payload(
            team_id=team_id,
            research_project_id=research_project_id,
            experiment_name=project["name"],
            agent_id=agent_id,
            role_key=role_key,
            role_label=role_label,
            attempt=attempt_number,
            retry_of_session_id=retry_of_session_id,
            created_from_task_id=created_from_task_id,
            created_at=created_at,
            workflow_run_id=candidate_scope.workflowRunId,
            workflow_node_id=candidate_scope.workflowNodeId,
            selection_id=candidate_scope.selectionId,
            candidate_id=candidate_scope.candidateId,
            scope=candidate_scope,
            recovery_reason=(
                "missing_canonical_session" if missing_session_recovery else ""
            ),
        )
        child_result = s.session_service.create_child_session(
            root_session_id,
            user_request=f"独立处理候选 {candidate_scope.candidateId}",
            task_title=title,
            split_reason="workflow_candidate_scope_v3",
            auto_start=False,
            switch_to_child=False,
            source="research_project_agent_session",
            experiment_binding=binding,
        )
        created_session_id = _text(child_result.get("childSessionId"))
        canonical_detail = (
            s.session_service.get_session_detail(created_session_id)
            if created_session_id
            else None
        )
        if not _candidate_detail_matches_scope(
            canonical_detail,
            scope=candidate_scope,
            root_session_id=root_session_id,
        ):
            raise ResearchProjectAgentSessionError(
                "New candidate project Agent session is missing its canonical hidden child scope; "
                "the registry was not updated."
            )
        attempt = _normalize_attempt(
            {
                "sessionId": created_session_id,
                "agentId": agent_id,
                "roleKey": role_key,
                "attempt": attempt_number,
                "retryOfSessionId": retry_of_session_id,
                "createdFromTaskId": created_from_task_id,
                "createdAt": created_at,
                "workflowRunId": candidate_scope.workflowRunId,
                "workflowNodeId": candidate_scope.workflowNodeId,
                "selectionId": candidate_scope.selectionId,
                "candidateId": candidate_scope.candidateId,
                "scope": candidate_scope.to_dict(),
                "recoveryReason": (
                    "missing_canonical_session" if missing_session_recovery else ""
                ),
            }
        )
        record["roleKey"] = role_key
        record["attempts"].append(attempt)
        record["currentAttempt"] = attempt_number
        _write_registry(team_id, research_project_id, registry)
        s.lock_research_project_name(
            team_id,
            research_project_id,
            reason="first_experiment_session",
        )
        projected = _public_candidate_detail(canonical_detail, scope=candidate_scope)
        return _result_payload(
            project=project,
            attempt=attempt,
            session_title=title,
            session_created=True,
            detail=projected,
            scope=candidate_scope,
            parent_session_id=root_session_id,
        )
