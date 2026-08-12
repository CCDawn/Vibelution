"""Exact Agent task adapters for workflow NodeRuns."""

from __future__ import annotations

import urllib.parse
from typing import Any

from core.research.workflow.definition import build_challenge_cup_workflow_definition

from .budget_lifecycle import BudgetLifecycleError, reserve_node_budget
from .model_routing import ModelRoutingError, select_model_route
from .node_execution import start_node_execution
from .node_execution_support import NodeExecutionError, latest_node_run
from .session_binding_bridge import SessionBindingBridge, SessionBindingError
from .store import WorkflowRunStore
from .task_adapter_registry import PROJECT_NODE_TASKS, SOURCE_NODE_TASKS
from .task_bundle_lifecycle import (
    TaskBundleError,
    bind_agent_task_bundle,
    create_agent_task_bundle,
    ensure_task_bundle_capacity,
    task_bundle_id,
)


class AgentNodeExecutionError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def _return_to(record: dict[str, Any], node_id: str) -> str:
    return "/teams?" + urllib.parse.urlencode(
        {
            "teamId": str(record.get("teamId") or ""),
            "researchView": "workflow",
            "runId": str(record.get("runId") or ""),
            "node": node_id,
            "panel": "node",
        }
    )


def _source_agent_ids(record: dict[str, Any]) -> dict[str, str]:
    roles = {role for _, role in SOURCE_NODE_TASKS.values()}
    return {
        str(item.get("roleKey") or ""): str(item.get("agentId") or "")
        for item in record.get("bindingSnapshots") or []
        if str(item.get("roleKey") or "") in roles
        and str(item.get("agentId") or "").strip()
    }


def _find_source_collection_run(record: dict[str, Any]) -> str:
    from core.web.services import data_processing_service

    payload = data_processing_service.list_processing_runs(
        limit=200,
        metadata_filters={
            "startedFrom": "team_workflow_source_collection",
            "teamId": str(record.get("teamId") or ""),
        },
        scope_filters={
            "workflowRunId": str(record.get("runId") or ""),
            "researchProjectId": str(record.get("projectId") or ""),
        },
    )
    runs = [item for item in payload.get("runs") or [] if isinstance(item, dict)]
    if not runs:
        return ""
    return str(runs[0].get("runId") or "").strip()


def _ensure_source_collection_run(
    store: WorkflowRunStore,
    record: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    source_run_id = str(record.get("sourceCollectionRunId") or "").strip()
    if not source_run_id:
        source_run_id = _find_source_collection_run(record)
    if not source_run_id:
        from core.web.services.team_workflow.source_collection.runs import (
            start_source_collection_run,
        )

        input_snapshot = record.get("inputSnapshot") or {}
        objective = input_snapshot.get("researchObjectiveContract") or {}
        started = start_source_collection_run(
            str(record.get("teamId") or ""),
            {
                "researchProjectId": str(record.get("projectId") or ""),
                "title": "Challenge Cup workflow source collection",
                "goal": str(objective.get("question") or ""),
                "topic": str(objective.get("question") or ""),
                "inputRefs": list(input_snapshot.get("datasetRefs") or []),
                "agentRoles": list(_source_agent_ids(record)),
                "agentIds": _source_agent_ids(record),
                "scope": {
                    "workflowRunId": str(record.get("runId") or ""),
                    "researchProjectId": str(record.get("projectId") or ""),
                },
            },
        )
        source_run_id = str((started.get("run") or {}).get("runId") or "").strip()
    if not source_run_id:
        raise AgentNodeExecutionError(
            "source collection adapter did not return a runId",
            code="source_collection_run_missing",
        )
    if source_run_id != str(record.get("sourceCollectionRunId") or ""):
        record = store.update_run(
            str(record.get("runId") or ""),
            {"sourceCollectionRunId": source_run_id},
        )
    return record, source_run_id


def _task_anchor(started: dict[str, Any]) -> dict[str, str | int]:
    task = started.get("task") if isinstance(started.get("task"), dict) else {}
    turn = started.get("turn") if isinstance(started.get("turn"), dict) else {}
    task_turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    return {
        "agentId": str(started.get("agentId") or task.get("agentId") or ""),
        "taskId": str(started.get("taskId") or task.get("taskId") or ""),
        "sessionId": str(started.get("sessionId") or task.get("sessionId") or ""),
        "sessionAttempt": int(
            started.get("sessionAttempt") or task.get("sessionAttempt") or 1
        ),
        "turnId": str(
            turn.get("turnId")
            or task_turn.get("turnId")
            or started.get("startedTurnId")
            or ""
        ),
    }


def _require_canonical_task_session(*, session_id: str, agent_id: str) -> None:
    """Reject a task anchor unless its session resolves through the Chat authority."""
    from core.web.services import session_service

    normalized_session_id = str(session_id or "").strip()
    try:
        detail = session_service.get_session_detail(
            normalized_session_id,
            message_limit=0,
            transcript_scope="none",
        )
    except Exception as exc:
        raise AgentNodeExecutionError(
            "Agent task session authority could not be verified",
            code="task_session_authority_unavailable",
        ) from exc
    if not isinstance(detail, dict) or str(detail.get("id") or "").strip() != normalized_session_id:
        raise AgentNodeExecutionError(
            "Agent task session is missing from the canonical session index",
            code="task_session_not_canonical",
        )
    canonical_agent_id = str(detail.get("agentId") or "").strip()
    if canonical_agent_id and canonical_agent_id != agent_id:
        raise AgentNodeExecutionError(
            "Agent task session Agent does not match the frozen NodeRun binding",
            code="task_session_agent_mismatch",
        )


def _start_external_task(
    store: WorkflowRunStore,
    record: dict[str, Any],
    *,
    node_id: str,
    agent_id: str,
    idempotency_key: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    return_to = _return_to(record, node_id)
    if node_id in SOURCE_NODE_TASKS:
        record, source_run_id = _ensure_source_collection_run(store, record)
        stage_id, role_key = SOURCE_NODE_TASKS[node_id]
        from core.web.services.team_workflow.source_collection.stage_session import (
            start_source_collection_stage_session_task,
        )
        from core.web.services.team_workflow_orchestration_service import (
            TeamWorkflowOrchestrationError,
        )

        try:
            started = start_source_collection_stage_session_task(
                str(record.get("teamId") or ""),
                source_run_id,
                {
                    "stageId": stage_id,
                    "agentId": agent_id,
                    "agentRole": role_key,
                    "idempotencyKey": idempotency_key,
                    "returnTo": return_to,
                    "returnLabel": "科研工作流",
                    "formalRetry": bool(record.get("evidenceRemediationContract")),
                    "evidenceRemediationContract": dict(
                        record.get("evidenceRemediationContract") or {}
                    ),
                },
            )
        except TeamWorkflowOrchestrationError as exc:
            raise AgentNodeExecutionError(
                str(exc),
                code="source_stage_preflight_failed",
            ) from exc
        return record, started
    task_kind = PROJECT_NODE_TASKS.get(node_id)
    if not task_kind:
        raise AgentNodeExecutionError(
            f"Agent node {node_id} has no task adapter",
            code="agent_task_adapter_missing",
        )
    from core.web.services.team_workflow.research_project_agent_tasks import (
        start_research_project_agent_task,
    )

    started = start_research_project_agent_task(
        str(record.get("teamId") or ""),
        str(record.get("projectId") or ""),
        {
            "taskKind": task_kind,
            "agentId": agent_id,
            "idempotencyKey": idempotency_key,
            "targetRef": str(payload.get("targetRef") or f"node-run:{node_id}"),
            "returnTo": return_to,
            "returnLabel": "科研工作流",
        },
    )
    return record, started


def start_agent_node_execution(
    store: WorkflowRunStore,
    *,
    record: dict[str, Any],
    node_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    node_run = latest_node_run(record, node_id)
    agent_id = str(node_run.get("agentId") or "").strip()
    requested_agent_id = str(payload.get("agentId") or "").strip()
    if requested_agent_id and requested_agent_id != agent_id:
        raise AgentNodeExecutionError(
            "requested agentId does not match the frozen NodeRun binding",
            code="binding_agent_mismatch",
        )
    idempotency_key = str(
        payload.get("idempotencyKey") or f"agent-task:{node_run['nodeRunId']}"
    ).strip()
    if node_run.get("status") == "running" and node_run.get("taskId"):
        binding = store.get_session_binding(str(record.get("runId") or ""), node_id)
        bundle_id = task_bundle_id(str(node_run["nodeRunId"]))
        bundle = next(
            (
                item
                for item in record.get("taskBundles") or []
                if item.get("bundleId") == bundle_id
            ),
            {},
        )
        persisted_key = str(bundle.get("idempotencyKey") or "").strip()
        if not persisted_key or persisted_key != idempotency_key:
            raise AgentNodeExecutionError(
                "Agent task replay idempotencyKey conflicts with the persisted TaskBundle",
                code="agent_task_idempotency_conflict",
            )
        if bundle and bundle.get("status") == "pending" and binding:
            bundle = bind_agent_task_bundle(
                store,
                run_id=str(record["runId"]),
                bundle_id=bundle_id,
                task_id=str(node_run["taskId"]),
                session_id=str(node_run["sessionId"]),
                turn_id=str(binding.get("focusTurnId") or ""),
            )
        route = next(
            (
                item
                for item in record.get("modelRoutingDecisions") or []
                if item.get("nodeRunId") == node_run["nodeRunId"]
            ),
            {},
        )
        return {
            "command": "start_agent_task",
            "taskId": str(node_run.get("taskId") or ""),
            "chatRoute": "",
            "sessionBinding": binding or {},
            "taskBundle": bundle,
            "modelRoute": route,
            "idempotentReplay": True,
        }
    if node_run.get("status") != "ready":
        raise AgentNodeExecutionError(
            f"Agent node must be ready, got {node_run.get('status')}",
            code="invalid_node_state",
        )
    if not agent_id:
        raise AgentNodeExecutionError("agent node is unbound", code="agent_unbound")
    node_spec = next(
        item
        for item in build_challenge_cup_workflow_definition().nodes
        if item.nodeId == node_id
    )
    try:
        model_route = select_model_route(record, node_run, payload)
        ensure_task_bundle_capacity(
            record,
            node_run_id=str(node_run["nodeRunId"]),
        )
        reservation = reserve_node_budget(
            store,
            record=record,
            node_run=node_run,
            stage_id=node_spec.stageId.value,
            request=dict(payload.get("budgetRequest") or {}),
            idempotency_key=idempotency_key,
        )
        record = store.get_run(str(record["runId"])) or record
        bundle = create_agent_task_bundle(
            store,
            record=record,
            node_run=node_run,
            node_spec=node_spec,
            model_route=model_route,
            budget_reservation_ref=str(reservation["reservationId"]),
            idempotency_key=idempotency_key,
            deadline_seconds=int(payload.get("deadlineSeconds") or 1800),
        )
    except (BudgetLifecycleError, ModelRoutingError, TaskBundleError) as exc:
        raise AgentNodeExecutionError(
            str(exc),
            code=str(getattr(exc, "code", "agent_task_contract_invalid")),
        ) from exc
    record = store.get_run(str(record["runId"])) or record
    record, started = _start_external_task(
        store,
        record,
        node_id=node_id,
        agent_id=agent_id,
        idempotency_key=idempotency_key,
        payload=payload,
    )
    anchor = _task_anchor(started)
    if str(anchor["agentId"] or "") != agent_id:
        raise AgentNodeExecutionError(
            "started task Agent does not match the frozen NodeRun binding",
            code="binding_agent_mismatch",
        )
    missing = [
        key for key in ("taskId", "sessionId", "turnId") if not str(anchor[key] or "")
    ]
    if missing:
        raise AgentNodeExecutionError(
            f"Agent task anchor is incomplete: {', '.join(missing)}",
            code="incomplete_task_anchor",
        )
    _require_canonical_task_session(
        session_id=str(anchor["sessionId"]),
        agent_id=agent_id,
    )
    try:
        binding = SessionBindingBridge(store).put(
            record,
            node_id,
            {
                "agentId": agent_id,
                "roleKey": next(
                    (
                        str(item.get("roleKey") or "")
                        for item in record.get("bindingSnapshots") or []
                        if item.get("nodeId") == node_id
                    ),
                    "",
                ),
                "nodeRunId": str(node_run.get("nodeRunId") or ""),
                "nodeAttempt": int(node_run.get("attempt") or 1),
                "sessionId": str(anchor["sessionId"]),
                "sessionAttempt": int(anchor["sessionAttempt"]),
                "taskId": str(anchor["taskId"]),
                "turnId": str(anchor["turnId"]),
                "checkpointId": str(node_run.get("checkpointId") or ""),
            },
        )
        start_node_execution(
            store,
            run_id=str(record.get("runId") or ""),
            node_id=node_id,
            payload={
                "idempotencyKey": idempotency_key,
                "leaseOwner": f"agent-task:{agent_id}",
                "leaseSeconds": int(payload.get("leaseSeconds") or 60),
                "deadlineSeconds": int(payload.get("deadlineSeconds") or 1800),
                "taskId": str(anchor["taskId"]),
                "sessionId": str(anchor["sessionId"]),
                "budgetReservationRef": str(
                    bundle["subtasks"][0]["budgetReservationRef"]
                ),
                "modelRef": model_route["modelRef"],
                "modelPurpose": model_route["purpose"],
                "estimatedCost": model_route["estimatedCost"],
                "escalationReason": model_route["escalationReason"],
            },
        )
        bundle = bind_agent_task_bundle(
            store,
            run_id=str(record["runId"]),
            bundle_id=str(bundle["bundleId"]),
            task_id=str(anchor["taskId"]),
            session_id=str(anchor["sessionId"]),
            turn_id=str(anchor["turnId"]),
        )
    except (SessionBindingError, NodeExecutionError, TaskBundleError) as exc:
        raise AgentNodeExecutionError(
            str(exc),
            code=str(getattr(exc, "code", "agent_task_persistence_failed")),
        ) from exc
    return {
        "command": "start_agent_task",
        "taskId": str(anchor["taskId"]),
        "chatRoute": str(started.get("chatRoute") or ""),
        "sessionBinding": binding,
        "taskBundle": bundle,
        "modelRoute": model_route,
        "idempotentReplay": False,
    }
