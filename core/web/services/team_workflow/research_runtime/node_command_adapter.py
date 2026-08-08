"""Node-level command adapter for research workflow runs.

Every command the frontend may render has a REAL backend handler here, or is
declared explicitly unavailable with a reason. The frontend never derives the
next node or fakes success: it renders only commands the adapter reports as
available (via node_command_capabilities) and executes them through
apply_node_command — no self-computed transitions.

Current wiring:
- start_agent_task -> research project Agent task only for roles with a
                       concrete task-kind mapping;
- rebind_node      -> controlled rebind keeping snapshot lineage (handled by
                       the runtime service);
- session navigation is reported separately by the runtime service once the
  full session/task/turn anchor exists;
- smoke, controlled-run, artifact and roadmap actions are not advertised
  until their node-specific UI contract supplies the required context.
"""

from __future__ import annotations

import uuid
from typing import Any

from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import ActorKind

from .session_binding_bridge import SessionBindingBridge


class NodeCommandUnavailable(Exception):
    def __init__(self, message: str, *, code: str = "node_command_unavailable"):
        super().__init__(message)
        self.code = code


class NodeCommandError(Exception):
    def __init__(self, message: str, *, code: str = "node_command_error"):
        super().__init__(message)
        self.code = code


# research-project Agent task kinds per workflow primary role.
TASK_KIND_BY_ROLE: dict[str, str] = {
    "experiment_planner": "experiment_design",
    "experiment_ledger": "experiment_evidence_review",
    "iteration_planner": "iteration_decision",
    "iteration_versioning": "version_governance",
}

def _node_spec(node_id: str) -> dict[str, Any] | None:
    definition = build_challenge_cup_workflow_definition()
    return next((n.to_dict() for n in definition.nodes if n.nodeId == node_id), None)


def _snapshot_agent_id(record: dict[str, Any], node_id: str) -> str:
    for snap in record.get("bindingSnapshots") or []:
        if str(snap.get("nodeId") or "") == node_id:
            return str(snap.get("agentId") or "").strip()
    return ""


def node_command_capabilities(
    record: dict[str, Any],
    node_id: str,
) -> list[dict[str, Any]]:
    """Per-node capability list driving the frontend (no fake buttons)."""
    node = _node_spec(node_id)
    if node is None:
        return []
    actor_kind = str(node.get("actorKind") or "")

    if actor_kind == ActorKind.AGENT.value:
        if node_id == "evidence_relations":
            from .evidence_graph_projection import evidence_graph_availability

            available, reason = evidence_graph_availability(record)
            return [
                {"command": "open_evidence_graph", "available": available, "reason": reason}
            ]
        role = str(node.get("primaryRoleKey") or "")
        if role not in TASK_KIND_BY_ROLE:
            return []
        agent_id = _snapshot_agent_id(record, node_id)
        if not agent_id:
            return [{
                "command": "start_agent_task",
                "available": False,
                "reason": "节点尚未绑定 Agent，先完成绑定",
            }]
        if not str(record.get("projectId") or "").strip():
            return [{
                "command": "start_agent_task",
                "available": False,
                "reason": "运行尚无 research project 上下文（缺少 projectId）",
            }]
        return [{"command": "start_agent_task", "available": True, "reason": ""}]

    if actor_kind == ActorKind.HUMAN.value and any(
        str(task.get("nodeId") or "") == node_id and str(task.get("status") or "") == "pending"
        for task in record.get("humanTasks") or []
        if isinstance(task, dict)
    ):
        return [
            {"command": command, "available": True, "reason": ""}
            for command in ("accept_handoff", "reject_handoff", "revise")
        ]

    if actor_kind == ActorKind.SYSTEM.value and node_id == "result_package":
        from .result_package import result_package_availability

        available, reason = result_package_availability(record)
        return [
            {"command": "build_package", "available": available, "reason": reason},
            {"command": "view_artifacts", "available": True, "reason": ""},
        ]
    return []


def apply_node_command(
    *,
    store: Any,
    record: dict[str, Any],
    node_id: str,
    command: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one node command against a real backend handler."""
    payload = payload or {}
    node = _node_spec(node_id)
    if node is None:
        raise NodeCommandError(f"Unknown nodeId: {node_id}", code="unknown_node")
    if command == "open_session":
        raise NodeCommandUnavailable("会话入口必须通过节点详情中的精确链接打开", code="navigation_only")
    if command in {"accept_handoff", "reject_handoff", "revise"}:
        raise NodeCommandUnavailable("人工任务必须通过人工任务接口处理", code="human_task_resolution_required")
    capability = next(
        (item for item in node_command_capabilities(record, node_id) if item["command"] == command),
        None,
    )
    if capability is None:
        raise NodeCommandUnavailable("该命令不适用于当前节点", code="command_not_allowed_for_node")
    if not capability["available"]:
        reason = str(capability["reason"] or "该命令当前不可用")
        code = (
            "no_project_context"
            if "projectId" in reason
            else "unbound_node"
            if "绑定 Agent" in reason
            else "node_command_unavailable"
        )
        raise NodeCommandUnavailable(reason, code=code)
    if command == "start_agent_task":
        return _start_agent_task(store, record, node, payload)
    if command == "run_smoke":
        return _run_smoke(record, payload)
    if command == "start_controlled_run":
        return _start_controlled_run(record, payload)
    if command == "view_artifacts":
        return _view_artifacts(record, node_id)
    if command == "build_package":
        return _build_package(store, record, payload)
    if command == "open_evidence_graph":
        return _open_evidence_graph(record)
    if command == "rebind_node":
        raise NodeCommandError(
            "rebind_node is handled by the runtime service command path",
            code="delegate_to_runtime_command",
        )
    raise NodeCommandError(f"Unknown node command: {command}", code="unknown_command")


def _require_project(record: dict[str, Any], payload: dict[str, Any]) -> tuple[str, str]:
    team_id = str(record.get("teamId") or "").strip()
    # Project scope is frozen on the WorkflowRun. A command payload cannot
    # smuggle a different project into an existing run.
    project_id = str(record.get("projectId") or "").strip()
    if not team_id or not project_id:
        raise NodeCommandUnavailable(
            "运行缺少 research project 上下文（teamId/projectId）",
            code="no_project_context",
        )
    return team_id, project_id


def _start_agent_task(
    store: Any,
    record: dict[str, Any],
    node: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    role = str(node.get("primaryRoleKey") or "")
    task_kind = TASK_KIND_BY_ROLE.get(role)
    if not task_kind:
        raise NodeCommandUnavailable(
            f"角色 {role} 尚无对应的 research project Agent task kind",
            code="no_task_kind",
        )
    team_id, project_id = _require_project(record, payload)
    node_id = str(node.get("nodeId") or "")
    if not _snapshot_agent_id(record, node_id):
        raise NodeCommandUnavailable(
            f"节点 {node_id} 未绑定 Agent，无法启动任务",
            code="unbound_node",
        )

    from core.web.services.team_workflow.research_project_agent_tasks import (
        start_research_project_agent_task,
    )

    started = start_research_project_agent_task(
        team_id,
        project_id,
        {
            "taskKind": task_kind,
            "idempotencyKey": str(payload.get("idempotencyKey") or f"wf-{node_id}-{uuid.uuid4().hex[:8]}"),
            "returnTo": f"/teams?researchView=workflow&runId={record.get('runId')}&node={node_id}&returnLabel=workflow",
            "returnLabel": "workflow",
            "targetRef": str(payload.get("targetRef") or "") or f"run:{record.get('runId')}:node:{node_id}",
        },
    )
    task = started.get("task") or {}
    turn = task.get("turn") or {}
    turn_id = str(turn.get("turnId") or started.get("startedTurnId") or "")

    bridge = SessionBindingBridge(store)
    node_attempts = record.get("nodeAttempts") if isinstance(record.get("nodeAttempts"), dict) else {}
    binding = bridge.put(
        record,
        node_id,
        {
            "agentId": str(task.get("agentId") or ""),
            "roleKey": role,
            "nodeRunId": f"nr-{node_id}",
            "nodeAttempt": int(node_attempts.get(node_id) or 1),
            "sessionId": str(started.get("sessionId") or task.get("sessionId") or ""),
            "sessionAttempt": int(started.get("sessionAttempt") or task.get("sessionAttempt") or 1),
            "taskId": str(task.get("taskId") or ""),
            "turnId": turn_id,
            "checkpointId": str(payload.get("checkpointId") or ""),
            "supersedesBindingId": str(payload.get("supersedesBindingId") or ""),
        },
    )
    return {
        "command": "start_agent_task",
        "taskId": str(task.get("taskId") or ""),
        "taskKind": task_kind,
        "chatRoute": started.get("chatRoute") or "",
        "sessionBinding": binding,
    }


def _run_smoke(record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    team_id, _project_id = _require_project(record, payload)
    plan_id = str(payload.get("planId") or "").strip()
    if not plan_id:
        raise NodeCommandUnavailable(
            "run_smoke 需要 planId（冻结实验计划）",
            code="missing_plan",
        )
    from core.web.services.team_workflow.experiment_api.smoke import (
        run_experiment_smoke_run,
    )

    result = run_experiment_smoke_run(team_id, plan_id, payload)
    return {"command": "run_smoke", "smoke": result}


def _start_controlled_run(record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    team_id, _project_id = _require_project(record, payload)
    plan_id = str(payload.get("planId") or "").strip()
    if not plan_id:
        raise NodeCommandUnavailable(
            "start_controlled_run 需要 planId（冻结实验计划）",
            code="missing_plan",
        )
    from core.web.services.team_workflow.experiment_api.full_run import (
        execute_experiment_full_run,
    )

    result = execute_experiment_full_run(team_id, plan_id, payload)
    return {"command": "start_controlled_run", "run": result}


def _view_artifacts(record: dict[str, Any], node_id: str) -> dict[str, Any]:
    artifacts = (record.get("langGraph") or {}).get("artifacts") or {}
    return {
        "command": "view_artifacts",
        "nodeId": node_id,
        "artifacts": artifacts,
    }


def _build_package(
    store: Any,
    record: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .result_package import build_result_package

    package = build_result_package(record)
    run_id = str(record.get("runId") or "")
    stored = record.get("resultPackage")
    if not (isinstance(stored, dict) and stored.get("packageId") == package["packageId"]):
        store.update_run(
            run_id,
            {
                "resultPackage": package,
                "resultPackageRef": package["packageRef"],
            },
        )
    return {"command": "build_package", "resultPackage": package}


def _open_evidence_graph(record: dict[str, Any]) -> dict[str, Any]:
    from .evidence_graph_projection import project_evidence_graph

    graph = project_evidence_graph(record)
    return {"command": "open_evidence_graph", "graph": graph}
