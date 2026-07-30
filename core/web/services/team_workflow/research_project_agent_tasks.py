"""Project-scoped Agent task lifecycle over flat research sessions."""

from __future__ import annotations

import json
import re
import threading
import uuid
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
TASK_STORE_FILE_NAME = "research_project_agent_tasks.json"
MAX_TASKS = 500
ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {
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
ALLOWED_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
_TASK_LOCK = threading.RLock()

TASK_KIND_CONTRACTS: dict[str, dict[str, Any]] = {
    "experiment_design": {
        "teamRole": "experiment_planner",
        "roleKey": "challenge_cup_experiment_planner",
        "roleLabel": "实验规划",
        "title": "生成或修订冻结前的实验设计",
        "objective": "读取当前项目的受控实验上下文，生成可审查的实验计划，并通过实验写回工具登记结果。",
        "checklist": [
            "核对研究问题、dataset、baseline、变量、metric 与成功/失败门禁",
            "保持训练与执行为人工触发边界",
            "通过 challenge_cup_experiment_writeback_tool 登记计划或修订",
        ],
    },
    "experiment_evidence_review": {
        "teamRole": "experiment_ledger",
        "roleKey": "challenge_cup_experiment_ledger",
        "roleLabel": "实验证据",
        "title": "复核并登记实验结果证据",
        "objective": "读取指定实验计划的受控证据，复核 artifact、metric 与结果边界，并通过实验写回工具登记结论。",
        "checklist": [
            "区分 baseline、smoke 与 full-run 证据",
            "保留 artifact、metric、日志引用和失败边界",
            "不得自动启动训练或 smoke runner",
        ],
    },
    "iteration_decision": {
        "teamRole": "iteration_planner",
        "roleKey": "challenge_cup_iteration_planner",
        "roleLabel": "迭代决策",
        "title": "复盘结果并形成下一轮决策",
        "objective": "读取项目内实验与 Research Loop 证据，形成接受、修复、重试或归档决策，并通过迭代写回工具登记。",
        "checklist": [
            "引用成功、失败和边界证据",
            "明确仅允许改变的变量与保持固定的控制项",
            "通过 challenge_cup_iteration_writeback_tool 登记证据和决策",
        ],
    },
    "version_governance": {
        "teamRole": "iteration_versioning",
        "roleKey": "challenge_cup_versioning",
        "roleLabel": "版本治理",
        "title": "维护候选版本、晋升和拒绝归档",
        "objective": "根据项目内迭代决策维护版本关系、晋升、淘汰和拒绝归档，并通过版本治理工具登记。",
        "checklist": [
            "保持 supersedes 与 derived_from 关系可追溯",
            "记录晋升、淘汰或归档的证据引用",
            "不得把候选版本直接写成正式研究图结论",
        ],
    },
}


class ResearchProjectAgentTaskError(RuntimeError):
    """Raised when a project-scoped Agent task cannot start safely."""

    def __init__(self, message: str, *, code: str = "research_project_agent_task_error"):
        super().__init__(message)
        self.code = code


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def _text(value: Any, *, limit: int = 160) -> str:
    return str(value or "").strip()[:limit]


def _safe_ref(value: Any, *, field_name: str) -> str:
    normalized = _text(value, limit=200)
    if normalized and not _SAFE_REF.fullmatch(normalized):
        raise ResearchProjectAgentTaskError(
            f"{field_name} must be a bounded identifier, not a path or URL.",
            code="invalid_task_reference",
        )
    return normalized


def _safe_route(value: Any) -> str:
    normalized = _text(value, limit=1000)
    if not normalized:
        return ""
    if not normalized.startswith("/") or normalized.startswith("//") or "://" in normalized:
        raise ResearchProjectAgentTaskError(
            "returnTo must be an internal application route.",
            code="invalid_return_route",
        )
    return normalized


def _positive_int(value: Any, *, default: int = 1) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _store_path(team_id: str, research_project_id: str) -> Path:
    s = _service()
    return (
        s.resolve_research_project_workspace_root(team_id, research_project_id)
        / TASK_STORE_FILE_NAME
    )


def _empty_store(team_id: str, research_project_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": _text(team_id),
        "researchProjectId": _text(research_project_id),
        "tasks": [],
        "updatedAt": "",
    }


def _normalize_turn(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    return {
        "accepted": bool(payload.get("accepted")),
        "turnId": _text(payload.get("turnId") or payload.get("startedTurnId")),
        "status": _text(payload.get("status"), limit=80),
        "acceptedAt": _text(payload.get("acceptedAt"), limit=120),
    }


def _normalize_task(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    status = _text(payload.get("status"), limit=80).lower()
    if status not in ALLOWED_STATUSES:
        status = "queued"
    task_kind = _text(payload.get("taskKind"), limit=80)
    contract = TASK_KIND_CONTRACTS.get(task_kind) or {}
    result_refs = [
        item
        for item in (
            _text(item, limit=200) for item in list(payload.get("resultRefs") or [])
        )
        if item and _SAFE_REF.fullmatch(item)
    ][:24]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "taskId": _text(payload.get("taskId")),
        "idempotencyKey": _text(payload.get("idempotencyKey"), limit=240),
        "taskKind": task_kind,
        "taskTitle": _text(
            payload.get("taskTitle") or contract.get("title"),
            limit=160,
        ),
        "teamId": _text(payload.get("teamId")),
        "researchProjectId": _text(payload.get("researchProjectId")),
        "experimentName": _text(payload.get("experimentName"), limit=160),
        "targetRef": _text(payload.get("targetRef"), limit=200),
        "agentId": _text(payload.get("agentId")),
        "teamRole": _text(payload.get("teamRole"), limit=80),
        "roleKey": _text(payload.get("roleKey"), limit=80),
        "roleLabel": _text(payload.get("roleLabel"), limit=80),
        "sessionId": _text(payload.get("sessionId")),
        "sessionTitle": _text(payload.get("sessionTitle"), limit=120),
        "sessionAttempt": _positive_int(payload.get("sessionAttempt")),
        "sessionCreated": bool(payload.get("sessionCreated")),
        "retryOfSessionId": _text(payload.get("retryOfSessionId")),
        "retrySourceTaskId": _text(payload.get("retrySourceTaskId")),
        "formalRetry": bool(payload.get("formalRetry")),
        "status": status,
        "turn": _normalize_turn(payload.get("turn")),
        "resultRefs": result_refs,
        "failureCode": _text(payload.get("failureCode"), limit=120),
        "returnTo": _text(payload.get("returnTo"), limit=1000),
        "returnLabel": _text(payload.get("returnLabel"), limit=240),
        "createdAt": _text(payload.get("createdAt"), limit=120),
        "updatedAt": _text(payload.get("updatedAt"), limit=120),
    }


def _read_store(team_id: str, research_project_id: str) -> dict[str, Any]:
    path = _store_path(team_id, research_project_id)
    if not path.exists():
        return _empty_store(team_id, research_project_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store(team_id, research_project_id)
    if not isinstance(payload, dict):
        return _empty_store(team_id, research_project_id)
    tasks = [
        _normalize_task(item)
        for item in list(payload.get("tasks") or [])
        if isinstance(item, dict) and _text(item.get("taskId"))
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": _text(team_id),
        "researchProjectId": _text(research_project_id),
        "tasks": tasks[-MAX_TASKS:],
        "updatedAt": _text(payload.get("updatedAt"), limit=120),
    }


def _write_store(
    team_id: str,
    research_project_id: str,
    store: dict[str, Any],
) -> None:
    s = _service()
    store["schemaVersion"] = SCHEMA_VERSION
    store["teamId"] = _text(team_id)
    store["researchProjectId"] = _text(research_project_id)
    store["tasks"] = [
        _normalize_task(item)
        for item in list(store.get("tasks") or [])[-MAX_TASKS:]
        if isinstance(item, dict)
    ]
    store["updatedAt"] = s.utc_now_iso()
    s._write_json(_store_path(team_id, research_project_id), store)


def _resolve_role_agent(
    team_id: str,
    contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    s = _service()
    team = s.team_service.get_team(team_id)
    expected_team_role = _text(contract.get("teamRole"), limit=80)
    expected_role_key = _text(contract.get("roleKey"), limit=80)
    member = next(
        (
            item
            for item in list(team.get("members") or [])
            if isinstance(item, dict)
            and _text(item.get("role"), limit=80) == expected_team_role
            and _text(item.get("agentId"))
        ),
        None,
    )
    if member is None:
        raise ResearchProjectAgentTaskError(
            f"Research team role {expected_team_role} is not bound to an Agent.",
            code="agent_role_unbound",
        )
    agent_id = _text(member.get("agentId"))
    agent = s.agent_directory_service.get_agent(agent_id)
    if not isinstance(agent, dict):
        raise ResearchProjectAgentTaskError(
            f"Agent bound to research team role {expected_team_role} was not found.",
            code="agent_role_unbound",
        )
    actual_role_key = _text(agent.get("roleKey"), limit=80)
    if actual_role_key and actual_role_key != expected_role_key:
        raise ResearchProjectAgentTaskError(
            f"Agent role mismatch for {expected_team_role}: expected {expected_role_key}.",
            code="agent_role_mismatch",
        )
    return member, agent


def _task_message(
    *,
    task: dict[str, Any],
    contract: dict[str, Any],
) -> str:
    checklist = "\n".join(
        f"- {item}" for item in list(contract.get("checklist") or [])[:8]
    )
    target_line = (
        f"\n目标记录：{task['targetRef']}" if task.get("targetRef") else ""
    )
    retry_line = (
        f"\n本任务是正式重试，上一任务：{task['retrySourceTaskId']}。"
        if task.get("formalRetry")
        else ""
    )
    return (
        f"你正在处理研究项目“{task['experimentName']}”中的{task['roleLabel']}任务。"
        f"\n任务：{task['taskTitle']}{target_line}{retry_line}"
        f"\n目标：{contract.get('objective', '')}"
        f"\n完成检查：\n{checklist}"
        "\n请先读取受控项目上下文，再使用当前职责允许的工具完成写回。"
        "\n普通文本回答不能代替正式工具写回，也不得自动执行训练或扩大项目边界。"
    )


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_task(task)
    session_id = normalized["sessionId"]
    return {
        **normalized,
        "chatRoute": f"/chat?session={session_id}" if session_id else "",
    }


def _task_response(
    task: dict[str, Any],
    *,
    idempotent_replay: bool,
) -> dict[str, Any]:
    public_task = _public_task(task)
    return {
        "task": public_task,
        "researchProjectId": public_task["researchProjectId"],
        "experimentName": public_task["experimentName"],
        "sessionId": public_task["sessionId"],
        "sessionTitle": public_task["sessionTitle"],
        "sessionAttempt": public_task["sessionAttempt"],
        "sessionCreated": public_task["sessionCreated"],
        "retryOfSessionId": public_task["retryOfSessionId"],
        "chatRoute": public_task["chatRoute"],
        "idempotentReplay": bool(idempotent_replay),
    }


def require_research_project_agent_task(
    team_id: str,
    research_project_id: str,
    task_id: str,
    *,
    allowed_task_kinds: tuple[str, ...] = (),
    recorded_by_agent: str = "",
    require_active: bool = True,
) -> dict[str, Any]:
    """Resolve and verify one project task before a controlled tool writeback."""
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_project_id = s._normalize_required_id(
        research_project_id,
        "Research project id is required.",
    )
    normalized_task_id = s._normalize_required_id(task_id, "Task id is required.")
    s.get_research_project(normalized_team_id, normalized_project_id)
    with _TASK_LOCK:
        store = _read_store(normalized_team_id, normalized_project_id)
        task = next(
            (
                item
                for item in store["tasks"]
                if item.get("taskId") == normalized_task_id
            ),
            None,
        )
    if task is None:
        raise ResearchProjectAgentTaskError(
            "Research project Agent task not found.",
            code="task_not_found",
        )
    if allowed_task_kinds and task.get("taskKind") not in set(allowed_task_kinds):
        raise ResearchProjectAgentTaskError(
            "Research project Agent task responsibility does not allow this operation.",
            code="task_kind_mismatch",
        )
    if require_active and task.get("status") not in ACTIVE_STATUSES:
        raise ResearchProjectAgentTaskError(
            "Research project Agent task is no longer active.",
            code="task_not_active",
        )
    actor_agent_id = _text(recorded_by_agent)
    if actor_agent_id and actor_agent_id != task.get("agentId"):
        raise ResearchProjectAgentTaskError(
            "Tool actor does not match the Agent bound to this research task.",
            code="task_agent_mismatch",
        )
    return _public_task(task)


def _compact_experiment_result(
    value: Any,
    *,
    id_keys: tuple[str, ...],
) -> dict[str, Any] | None:
    record = value if isinstance(value, dict) else {}
    result_id = next(
        (_text(record.get(key)) for key in id_keys if _text(record.get(key))),
        "",
    )
    if not result_id:
        return None
    return {
        "resultId": result_id,
        "status": _text(record.get("status"), limit=80),
        "metricName": _text(
            record.get("metricName") or record.get("metric"),
            limit=240,
        ),
        "metricValue": _text(record.get("metricValue"), limit=240),
        "delta": _text(record.get("delta"), limit=240),
    }


def _compact_experiment_plan(plan: dict[str, Any]) -> dict[str, Any]:
    contract = (
        plan.get("experimentContract")
        if isinstance(plan.get("experimentContract"), dict)
        else {}
    )
    legacy_plan = (
        plan.get("experimentPlan")
        if isinstance(plan.get("experimentPlan"), dict)
        else {}
    )
    readiness = (
        plan.get("readiness") if isinstance(plan.get("readiness"), dict) else {}
    )
    validation = (
        plan.get("contractValidation")
        if isinstance(plan.get("contractValidation"), dict)
        else {}
    )
    knowledge_ingestion = (
        plan.get("knowledgeIngestion")
        if isinstance(plan.get("knowledgeIngestion"), dict)
        else {}
    )
    return {
        "planId": _text(plan.get("planId")),
        "stageRoundId": _text(plan.get("stageRoundId")),
        "researchProjectId": _text(plan.get("researchProjectId")),
        "experimentName": _text(plan.get("experimentName"), limit=160),
        "title": _text(plan.get("title"), limit=240),
        "status": _text(plan.get("status"), limit=80),
        "revision": _positive_int(plan.get("revision")),
        "researchQuestion": _text(
            contract.get("researchQuestion")
            or plan.get("goal")
            or plan.get("topic"),
            limit=1200,
        ),
        "researchMode": _text(contract.get("researchMode"), limit=120),
        "experimentMethod": _text(contract.get("experimentMethod"), limit=120),
        "dataset": _text(
            contract.get("dataset") or legacy_plan.get("dataset"),
            limit=500,
        ),
        "baseline": _text(
            contract.get("baseline") or legacy_plan.get("baseline"),
            limit=500,
        ),
        "metric": _text(
            contract.get("metric") or legacy_plan.get("metric"),
            limit=500,
        ),
        "selectedHypothesisIds": [
            _text(item.get("candidateId"))
            for item in list(plan.get("selectedHypotheses") or [])[:16]
            if isinstance(item, dict) and _text(item.get("candidateId"))
        ],
        "readiness": {
            "readyForPlanReview": bool(readiness.get("readyForPlanReview")),
            "readyForSmoke": bool(readiness.get("readyForSmoke")),
            "readyForFullRun": bool(readiness.get("readyForFullRun")),
            "readyForKnowledgeIngestion": bool(
                readiness.get("readyForKnowledgeIngestion")
            ),
        },
        "contractValidation": {
            "valid": bool(validation.get("valid")),
            "adapterAvailable": bool(validation.get("adapterAvailable")),
        },
        "activeBaselineArtifactId": _text(plan.get("activeBaselineArtifactId")),
        "activeSmokeResultId": _text(plan.get("activeSmokeResultId")),
        "activeFullRunResultId": _text(plan.get("activeFullRunResultId")),
        "baselineArtifact": _compact_experiment_result(
            (
                plan.get("baselineSelection", {}).get("activeBaselineArtifact")
                if isinstance(plan.get("baselineSelection"), dict)
                else None
            ),
            id_keys=("artifactId",),
        ),
        "smokeResult": _compact_experiment_result(
            plan.get("activeSmokeResult"),
            id_keys=("smokeResultId",),
        ),
        "fullRunResult": _compact_experiment_result(
            plan.get("activeFullRunResult"),
            id_keys=("fullRunResultId",),
        ),
        "knowledgeIngestionStatus": _text(
            knowledge_ingestion.get("status"),
            limit=80,
        ),
        "updatedAt": _text(plan.get("updatedAt"), limit=120),
    }


def require_research_project_experiment_plan(
    team_id: str,
    research_project_id: str,
    plan_id: str,
) -> dict[str, Any]:
    """Reject experiment ledger operations that target another project."""
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_project_id = s._normalize_required_id(
        research_project_id,
        "Research project id is required.",
    )
    normalized_plan_id = s._normalize_required_id(plan_id, "Plan id is required.")
    s.get_research_project(normalized_team_id, normalized_project_id)
    with s._WORKFLOW_LOCK:
        store = s._load_experiment_plan_store(normalized_team_id)
        plan = next(
            (
                item
                for item in list(store.get("plans") or [])
                if isinstance(item, dict)
                and _text(item.get("planId")) == normalized_plan_id
            ),
            None,
        )
    if plan is None:
        raise ResearchProjectAgentTaskError(
            "Experiment plan not found.",
            code="experiment_plan_not_found",
        )
    if _text(plan.get("researchProjectId")) != normalized_project_id:
        raise ResearchProjectAgentTaskError(
            "Experiment plan does not belong to this research project.",
            code="experiment_plan_project_mismatch",
        )
    return _compact_experiment_plan(plan)


def get_research_project_agent_task_context(
    team_id: str,
    research_project_id: str,
    task_id: str,
) -> dict[str, Any]:
    """Build a bounded project/task context without paths, prompts, or raw logs."""
    s = _service()
    task = require_research_project_agent_task(
        team_id,
        research_project_id,
        task_id,
    )
    project = s.get_research_project(team_id, research_project_id)
    with s._WORKFLOW_LOCK:
        plan_store = s._load_experiment_plan_store(team_id)
    plans = [
        _compact_experiment_plan(item)
        for item in list(plan_store.get("plans") or [])
        if isinstance(item, dict)
        and _text(item.get("researchProjectId")) == task["researchProjectId"]
    ]
    target_ref = _text(task.get("targetRef"))
    if task.get("taskKind") == "experiment_evidence_review" and target_ref:
        plans = [item for item in plans if item.get("planId") == target_ref]
    plans = plans[-12:]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": _text(team_id),
        "researchProjectId": _text(research_project_id),
        "experimentName": _text(project.get("name"), limit=160),
        "task": task,
        "experiment": {
            "planCount": len(plans),
            "plans": plans,
            "latestPlan": plans[-1] if plans else None,
        },
        "boundaries": {
            "projectScoped": True,
            "taskScoped": True,
            "autoExecution": False,
            "trainingRunner": False,
            "rawLogsIncluded": False,
        },
    }


def research_project_iteration_readiness(
    team_id: str,
    research_project_id: str,
) -> dict[str, Any]:
    """Return the non-bypassable prerequisites for an iteration decision."""
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_project_id = s._normalize_required_id(
        research_project_id,
        "Research project id is required.",
    )
    s.get_research_project(normalized_team_id, normalized_project_id)
    with s._WORKFLOW_LOCK:
        store = s._load_experiment_plan_store(normalized_team_id)
    plans = [
        item
        for item in list(store.get("plans") or [])
        if isinstance(item, dict)
        and (
            not _text(item.get("researchProjectId"))
            or _text(item.get("researchProjectId")) == normalized_project_id
        )
    ]
    frozen_plan = s._latest_frozen_experiment_design(plans)
    if frozen_plan is None:
        return {
            "ready": False,
            "code": "missing_frozen_experiment_design",
            "reason": "Iteration requires a frozen executable experiment design.",
            "reasonZh": "需要先冻结一份可执行的实验设计。",
            "planId": "",
            "resultId": "",
        }
    result = next(
        (
            candidate
            for candidate in (
                frozen_plan.get("activeFullRunResult"),
                frozen_plan.get("activeSmokeResult"),
            )
            if isinstance(candidate, dict)
            and _text(candidate.get("status"), limit=80).lower()
            in {"passed", "failed", "needs_review"}
        ),
        None,
    )
    if result is None:
        return {
            "ready": False,
            "code": "missing_experiment_result",
            "reason": "Iteration requires at least one registered smoke or full-run result.",
            "reasonZh": "需要先登记至少一条 smoke 或 full-run 实验结果。",
            "planId": _text(frozen_plan.get("planId")),
            "resultId": "",
        }
    return {
        "ready": True,
        "code": "ready",
        "reason": "A frozen design and registered experiment result are available.",
        "reasonZh": "冻结设计与实验结果均已登记，可以进入迭代决策。",
        "planId": _text(frozen_plan.get("planId")),
        "resultId": _text(
            result.get("fullRunResultId") or result.get("smokeResultId")
        ),
    }


def start_research_project_agent_task(
    team_id: str,
    research_project_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one bounded task turn in the correct flat project Agent session."""
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_project_id = s._normalize_required_id(
        research_project_id,
        "Research project id is required.",
    )
    request_payload = payload if isinstance(payload, dict) else {}
    task_kind = _text(request_payload.get("taskKind"), limit=80)
    contract = TASK_KIND_CONTRACTS.get(task_kind)
    if contract is None:
        raise ResearchProjectAgentTaskError(
            f"Unsupported research project Agent task kind: {task_kind or '(empty)'}.",
            code="unsupported_task_kind",
        )
    project = s.get_research_project(normalized_team_id, normalized_project_id)
    if task_kind == "experiment_design":
        from core.web.services.team_workflow.experiment_kernel import (
            materialize_candidate_graph_hypotheses_for_experiment_design,
        )

        materialize_candidate_graph_hypotheses_for_experiment_design(
            normalized_team_id,
            normalized_project_id,
        )
    if task_kind == "iteration_decision":
        readiness = research_project_iteration_readiness(
            normalized_team_id,
            normalized_project_id,
        )
        if not readiness["ready"]:
            raise ResearchProjectAgentTaskError(
                readiness["reason"],
                code=readiness["code"],
            )
    _member, agent = _resolve_role_agent(normalized_team_id, contract)
    agent_id = _text(agent.get("agentId"))
    target_ref = _safe_ref(request_payload.get("targetRef"), field_name="targetRef")
    idempotency_key = _text(request_payload.get("idempotencyKey"), limit=240)
    formal_retry = bool(request_payload.get("formalRetry"))
    retry_task_id = _safe_ref(
        request_payload.get("retryTaskId"),
        field_name="retryTaskId",
    )
    return_to = _safe_route(request_payload.get("returnTo"))
    return_label = _text(request_payload.get("returnLabel"), limit=240)
    now = s.utc_now_iso()

    with _TASK_LOCK:
        store = _read_store(normalized_team_id, normalized_project_id)
        tasks = store["tasks"]
        if idempotency_key:
            existing = next(
                (
                    item
                    for item in tasks
                    if item.get("idempotencyKey") == idempotency_key
                ),
                None,
            )
            if existing is not None:
                return _task_response(existing, idempotent_replay=True)

        active_for_agent = [
            item
            for item in tasks
            if item.get("agentId") == agent_id
            and item.get("status") in ACTIVE_STATUSES
        ]
        previous_task: dict[str, Any] | None = None
        if formal_retry:
            if not retry_task_id:
                raise ResearchProjectAgentTaskError(
                    "Formal retry requires retryTaskId.",
                    code="retry_task_required",
                )
            previous_task = next(
                (item for item in tasks if item.get("taskId") == retry_task_id),
                None,
            )
            if (
                previous_task is None
                or previous_task.get("agentId") != agent_id
                or previous_task.get("taskKind") != task_kind
            ):
                raise ResearchProjectAgentTaskError(
                    "Formal retry must reference the latest task for the same project Agent responsibility.",
                    code="invalid_retry_source",
                )
            if previous_task.get("status") in ACTIVE_STATUSES:
                raise ResearchProjectAgentTaskError(
                    "Formal retry cannot start because the previous task is still active.",
                    code="agent_task_active",
                )
            if previous_task.get("status") not in TERMINAL_STATUSES:
                raise ResearchProjectAgentTaskError(
                    "Formal retry requires a terminal previous task.",
                    code="retry_task_not_terminal",
                )
            same_agent_tasks = [
                item for item in tasks if item.get("agentId") == agent_id
            ]
            if not same_agent_tasks or same_agent_tasks[-1].get("taskId") != retry_task_id:
                raise ResearchProjectAgentTaskError(
                    "Formal retry must reference the latest task for this project Agent.",
                    code="invalid_retry_source",
                )
        elif active_for_agent:
            same_active = next(
                (
                    item
                    for item in active_for_agent
                    if item.get("taskKind") == task_kind
                    and item.get("targetRef") == target_ref
                ),
                None,
            )
            if same_active is not None:
                return _task_response(same_active, idempotent_replay=True)
            raise ResearchProjectAgentTaskError(
                "This project Agent already has an active task turn.",
                code="agent_task_active",
            )

        task_id = f"research-agent-task-{uuid.uuid4().hex[:16]}"
        try:
            session = s.resolve_research_project_agent_session(
                normalized_team_id,
                research_project_id=normalized_project_id,
                agent_id=agent_id,
                role_key=_text(contract.get("roleKey"), limit=80),
                role_label=_text(contract.get("roleLabel"), limit=80),
                created_from_task_id=task_id,
                formal_retry=formal_retry,
                previous_task=previous_task,
            )
        except s.ResearchProjectAgentSessionError as exc:
            raise ResearchProjectAgentTaskError(
                str(exc),
                code="session_resolution_failed",
            ) from exc
        task = _normalize_task(
            {
                "taskId": task_id,
                "idempotencyKey": idempotency_key,
                "taskKind": task_kind,
                "taskTitle": contract["title"],
                "teamId": normalized_team_id,
                "researchProjectId": normalized_project_id,
                "experimentName": project.get("name"),
                "targetRef": target_ref,
                "agentId": agent_id,
                "teamRole": contract["teamRole"],
                "roleKey": contract["roleKey"],
                "roleLabel": contract["roleLabel"],
                "sessionId": session["sessionId"],
                "sessionTitle": session["sessionTitle"],
                "sessionAttempt": session["sessionAttempt"],
                "sessionCreated": session["sessionCreated"],
                "retryOfSessionId": session["retryOfSessionId"],
                "retrySourceTaskId": previous_task.get("taskId")
                if previous_task
                else "",
                "formalRetry": formal_retry,
                "status": "queued",
                "turn": {},
                "returnTo": return_to,
                "returnLabel": return_label,
                "createdAt": now,
                "updatedAt": now,
            }
        )
        tasks.append(task)
        store["tasks"] = tasks
        _write_store(normalized_team_id, normalized_project_id, store)

    try:
        turn = s.session_service.submit_session_message(
            task["sessionId"],
            _task_message(task=task, contract=contract),
            mental_model_enabled=False,
            turn_mode="task",
            write_intent=False,
            message_source="agent_inbox",
            message_metadata={
                "kind": "research_project_agent_task",
                "sourceSurface": "team_workflow_project_agent_task",
                "teamId": normalized_team_id,
                "researchProjectId": normalized_project_id,
                "experimentName": task["experimentName"],
                "taskId": task_id,
                "taskKind": task_kind,
                "targetRef": target_ref,
                "agentId": agent_id,
                "teamRole": contract["teamRole"],
                "roleKey": contract["roleKey"],
                "sessionAttempt": task["sessionAttempt"],
                "retryOfSessionId": task["retryOfSessionId"],
                "retrySourceTaskId": task["retrySourceTaskId"],
                "formalRetry": formal_retry,
            },
            include_started_turn_id=True,
            lightweight_response=True,
        )
        turn_payload = _normalize_turn(turn)
        next_status = "running" if turn_payload["accepted"] else "blocked"
        failure_code = "" if turn_payload["accepted"] else "turn_not_accepted"
    except Exception as exc:
        turn_payload = _normalize_turn({})
        next_status = "failed"
        failure_code = f"turn_submit_{type(exc).__name__.lower()}"[:120]

    with _TASK_LOCK:
        store = _read_store(normalized_team_id, normalized_project_id)
        stored = next(
            (item for item in store["tasks"] if item.get("taskId") == task_id),
            None,
        )
        if stored is None:
            raise ResearchProjectAgentTaskError(
                "Project Agent task disappeared before turn submission completed.",
                code="task_store_inconsistent",
            )
        stored["status"] = next_status
        stored["turn"] = turn_payload
        stored["failureCode"] = failure_code
        stored["updatedAt"] = s.utc_now_iso()
        _write_store(normalized_team_id, normalized_project_id, store)
        task = stored

    s._record_workflow_event(
        "research_project_agent_task_started",
        normalized_team_id,
        fields={
            "researchProjectId": normalized_project_id,
            "taskId": task_id,
            "taskKind": task_kind,
            "agentId": agent_id,
            "sessionId": task["sessionId"],
            "sessionAttempt": task["sessionAttempt"],
            "formalRetry": formal_retry,
            "status": task["status"],
        },
        outcome="accepted" if task["status"] == "running" else "rejected",
        level="info" if task["status"] == "running" else "warning",
    )
    s.lock_research_project_name(
        normalized_team_id,
        normalized_project_id,
        reason="first_experiment_task",
    )
    return _task_response(task, idempotent_replay=False)


def update_research_project_agent_task_status(
    team_id: str,
    research_project_id: str,
    task_id: str,
    *,
    status: str,
    result_refs: list[str] | None = None,
    failure_code: str = "",
) -> dict[str, Any]:
    """Update lifecycle facts from a trusted task reconciler or tool result."""
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_project_id = s._normalize_required_id(
        research_project_id,
        "Research project id is required.",
    )
    normalized_task_id = s._normalize_required_id(task_id, "Task id is required.")
    normalized_status = _text(status, limit=80).lower()
    if normalized_status not in ALLOWED_STATUSES:
        raise ResearchProjectAgentTaskError(
            f"Unsupported project Agent task status: {normalized_status}.",
            code="invalid_task_status",
        )
    normalized_refs = [
        _safe_ref(item, field_name="resultRef")
        for item in list(result_refs or [])[:24]
        if _text(item, limit=200)
    ]
    with _TASK_LOCK:
        store = _read_store(normalized_team_id, normalized_project_id)
        task = next(
            (
                item
                for item in store["tasks"]
                if item.get("taskId") == normalized_task_id
            ),
            None,
        )
        if task is None:
            raise ResearchProjectAgentTaskError(
                "Research project Agent task not found.",
                code="task_not_found",
            )
        task["status"] = normalized_status
        task["resultRefs"] = normalized_refs
        task["failureCode"] = _text(failure_code, limit=120)
        task["updatedAt"] = s.utc_now_iso()
        _write_store(normalized_team_id, normalized_project_id, store)
        return _public_task(task)


def get_research_project_agent_task_status(
    team_id: str,
    research_project_id: str,
) -> dict[str, Any]:
    """Return a path/secret/prompt-free task projection for one project."""
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_project_id = s._normalize_required_id(
        research_project_id,
        "Research project id is required.",
    )
    project = s.get_research_project(normalized_team_id, normalized_project_id)
    with _TASK_LOCK:
        store = _read_store(normalized_team_id, normalized_project_id)
        active_tasks = [
            dict(item)
            for item in store["tasks"]
            if item.get("status") in ACTIVE_STATUSES
        ]
    reconciled: dict[str, dict[str, Any]] = {}
    for task in active_tasks:
        terminal = _reconcile_project_agent_task_from_session(
            normalized_team_id,
            normalized_project_id,
            task,
        )
        if terminal is not None:
            reconciled[task["taskId"]] = terminal
    if reconciled:
        with _TASK_LOCK:
            store = _read_store(normalized_team_id, normalized_project_id)
            changed = False
            for task in store["tasks"]:
                terminal = reconciled.get(task.get("taskId"))
                if terminal is None or task.get("status") not in ACTIVE_STATUSES:
                    continue
                task["status"] = terminal["status"]
                task["resultRefs"] = terminal["resultRefs"]
                task["failureCode"] = terminal["failureCode"]
                turn = (
                    task.get("turn")
                    if isinstance(task.get("turn"), dict)
                    else {}
                )
                turn["status"] = terminal["status"]
                task["turn"] = turn
                task["updatedAt"] = s.utc_now_iso()
                changed = True
            if changed:
                _write_store(normalized_team_id, normalized_project_id, store)
    with _TASK_LOCK:
        store = _read_store(normalized_team_id, normalized_project_id)
        tasks = [_public_task(item) for item in store["tasks"]]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "researchProjectId": normalized_project_id,
        "experimentName": _text(project.get("name"), limit=160),
        "tasks": tasks,
        "activeTasks": [
            item for item in tasks if item.get("status") in ACTIVE_STATUSES
        ],
        "supportedTaskKinds": [
            {
                "taskKind": task_kind,
                "teamRole": contract["teamRole"],
                "roleKey": contract["roleKey"],
                "roleLabel": contract["roleLabel"],
                "title": contract["title"],
            }
            for task_kind, contract in TASK_KIND_CONTRACTS.items()
        ],
        "updatedAt": _text(store.get("updatedAt"), limit=120),
    }


def _reconcile_project_agent_task_from_session(
    team_id: str,
    research_project_id: str,
    task: dict[str, Any],
) -> dict[str, Any] | None:
    s = _service()
    session_id = _text(task.get("sessionId"))
    if not session_id:
        return None
    try:
        detail = s.session_service.get_session_detail(
            session_id,
            message_limit=0,
            transcript_scope="none",
        )
    except Exception:
        return None
    if not isinstance(detail, dict):
        return None
    phase = _text(
        detail.get("currentPhase") or detail.get("status"),
        limit=80,
    ).lower()
    if detail.get("activeTask") or phase in {
        "accepted",
        "queued",
        "running",
        "starting",
        "stopping",
        "tool_call",
        "thinking",
    }:
        return None
    result_refs = _project_agent_task_result_refs(
        team_id,
        research_project_id,
        task,
    )
    if phase in {"error", "failed", "timed_out", "timeout"}:
        return {
            "status": "failed",
            "resultRefs": result_refs,
            "failureCode": f"session_{phase}",
        }
    if phase in {"cancelled", "canceled", "stopped"}:
        return {
            "status": "stopped",
            "resultRefs": result_refs,
            "failureCode": f"session_{phase}",
        }
    if result_refs:
        return {
            "status": "completed",
            "resultRefs": result_refs,
            "failureCode": "",
        }
    if phase in {"ready", "completed", "complete", "idle"}:
        return {
            "status": "incomplete",
            "resultRefs": [],
            "failureCode": "task_result_not_recorded",
        }
    return None


def _project_agent_task_result_refs(
    team_id: str,
    research_project_id: str,
    task: dict[str, Any],
) -> list[str]:
    s = _service()
    if task.get("taskKind") != "experiment_design":
        return [
            _safe_ref(item, field_name="resultRef")
            for item in list(task.get("resultRefs") or [])[:24]
            if _text(item, limit=200)
        ]
    root = s.resolve_research_project_workspace_root(
        team_id,
        research_project_id,
    )
    store = s._read_json(root / "experiment_plans" / "index.json")
    created_at = s._workflow_timestamp_sort_key(task.get("createdAt"))
    agent_id = _text(task.get("agentId"))
    matching = [
        item
        for item in list(store.get("plans") or [])
        if isinstance(item, dict)
        and _text(item.get("researchProjectId")) == research_project_id
        and _text(item.get("createdByAgent")) == agent_id
        and s._workflow_timestamp_sort_key(item.get("createdAt")) >= created_at
        and _text(item.get("planId"))
    ]
    matching.sort(
        key=lambda item: (
            _text(item.get("updatedAt"), limit=120),
            _text(item.get("createdAt"), limit=120),
        )
    )
    if not matching:
        return []
    plan_id = _text(matching[-1].get("planId"), limit=200)
    return [plan_id] if _SAFE_REF.fullmatch(plan_id) else []
