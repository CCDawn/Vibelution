"""Exact Agent task adapters for workflow NodeRuns."""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from typing import Any

from core.research.competition.question_result_package import (
    QuestionResultPackageError,
    canonical_model_policy,
)
from core.research.workflow.contracts import WorkflowSessionScopeV3
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.models import NodeSessionScopePolicy

from .budget_lifecycle import BudgetLifecycleError, reserve_node_budget
from .hypothesis_scoped_execution import load_hypothesis_fan_out_input
from .hypothesis_session_scope_mode import (
    evaluate_hypothesis_scope_shadow,
    resolve_hypothesis_scope_activation,
    resolve_hypothesis_session_scope_mode,
)
from .model_routing import ModelRoutingError, select_model_route
from .node_execution import start_node_execution
from .node_execution_support import NodeExecutionError, latest_node_run, replace_by_id
from .session_binding_bridge import SessionBindingBridge, SessionBindingError
from .store import WorkflowRunStore
from .task_adapter_registry import PROJECT_NODE_TASKS, SOURCE_NODE_TASKS
from .task_bundle_lifecycle import (
    TaskBundleError,
    bind_agent_task_bundle,
    create_agent_task_bundle,
    ensure_task_bundle_capacity,
    fail_agent_task_bundle_subtask,
    replace_agent_task_bundle_subtask,
    task_bundle_id,
)


class AgentNodeExecutionError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


_MODEL_INVOCATION_OUTCOME_KINDS: dict[str, tuple[str, ...]] = {
    # Source collection calls are auditable model invocations too.  They use
    # an additional outcome kind so source evidence does not satisfy the
    # five formal candidate/plan/review/revision/final-output categories.
    "source_finding": ("source_evidence",),
    "source_extraction": ("source_evidence",),
    "evidence_relations": ("source_evidence",),
    "knowledge_ingestion": ("source_evidence",),
    "hypothesis_design": ("candidate",),
    "protocol_design": ("plan", "revision"),
    "protocol_review": ("review",),
    "result_evaluation": ("review",),
    "iteration_decision": ("revision",),
    "version_governance": ("final_output",),
}
_MODEL_INVOCATION_STAGES: dict[str, str] = {
    "source_finding": "generation",
    "source_extraction": "generation",
    "evidence_relations": "generation",
    "knowledge_ingestion": "generation",
    "hypothesis_design": "generation",
    "protocol_design": "revision",
    "protocol_review": "review",
    "result_evaluation": "review",
    "iteration_decision": "revision",
    "version_governance": "revision",
}


def _model_invocation_receipt_binding(
    record: dict[str, Any],
    *,
    node_id: str,
    node_run_id: str,
    task_id: str = "",
    session_id: str = "",
    turn_id: str = "",
) -> dict[str, Any]:
    outcome_kinds = _MODEL_INVOCATION_OUTCOME_KINDS.get(node_id, ())
    question_stage = _MODEL_INVOCATION_STAGES.get(node_id, "")
    snapshot = record.get("inputSnapshot") if isinstance(record.get("inputSnapshot"), dict) else {}
    question_id = str(record.get("questionId") or snapshot.get("questionId") or "").strip().upper()
    workflow_run_id = str(record.get("runId") or "").strip()
    workflow_id = str(
        record.get("workflowId")
        or snapshot.get("workflowId")
        or "challenge-cup-research"
    ).strip()
    workflow_version_id = str(
        record.get("workflowVersionId") or snapshot.get("workflowVersionId") or ""
    ).strip()
    node_run = latest_node_run(record, node_id)
    model_policy = dict(snapshot.get("modelRoutingPolicy") or {})
    required_model_policy = model_policy.get("requiredModelPolicy")
    model_policy_sha256 = str(
        model_policy.get("modelPolicySha256") or ""
    ).strip().lower()
    try:
        canonical_required_model_policy = canonical_model_policy(
            required_model_policy
        )
    except (QuestionResultPackageError, TypeError, ValueError):
        return {}
    if (
        not isinstance(required_model_policy, dict)
        or required_model_policy != canonical_required_model_policy
        or model_policy_sha256
        != canonical_required_model_policy["policySha256"]
    ):
        return {}
    if (
        not question_id
        or not workflow_run_id
        or not workflow_id
        or not workflow_version_id
        or not node_run_id
        or not outcome_kinds
        or not question_stage
        or len(model_policy_sha256) != 64
        or any(char not in "0123456789abcdef" for char in model_policy_sha256)
    ):
        return {}
    return {
        "questionId": question_id,
        "questionRunId": workflow_run_id,
        "workflowRunId": workflow_run_id,
        "workflowId": workflow_id,
        "workflowVersionId": workflow_version_id,
        "formalNodeId": node_id,
        "formalNodeRunId": node_run_id,
        "formalNodeAttempt": int(node_run.get("attempt") or 1),
        "questionStage": question_stage,
        "taskId": str(task_id or ""),
        "sessionId": str(session_id or ""),
        "turnId": str(turn_id or ""),
        "outcomeKinds": list(outcome_kinds),
        "modelPolicySha256": model_policy_sha256,
    }


def _challenge_task_contract(
    record: dict[str, Any],
    *,
    node_id: str,
    node_run_id: str,
    agent_id: str,
) -> dict[str, Any]:
    """Create the server-owned contract persisted with a project Agent task."""

    snapshot = (
        record.get("inputSnapshot")
        if isinstance(record.get("inputSnapshot"), dict)
        else {}
    )
    model_policy = (
        snapshot.get("modelRoutingPolicy")
        if isinstance(snapshot.get("modelRoutingPolicy"), dict)
        else {}
    )
    if not model_policy:
        return {}
    node_run = latest_node_run(record, node_id)
    try:
        route = select_model_route(record, node_run, {})
    except ModelRoutingError as exc:
        raise AgentNodeExecutionError(
            str(exc),
            code=str(getattr(exc, "code", "agent_route_invalid")),
        ) from exc
    required_policy = model_policy.get("requiredModelPolicy")
    policy_sha256 = str(model_policy.get("modelPolicySha256") or "").strip().lower()
    question_id = str(
        record.get("questionId") or snapshot.get("questionId") or ""
    ).strip().upper()
    workflow_run_id = str(record.get("runId") or "").strip()
    workflow_id = str(
        record.get("workflowId")
        or snapshot.get("workflowId")
        or "challenge-cup-research"
    ).strip()
    workflow_version_id = str(
        record.get("workflowVersionId") or snapshot.get("workflowVersionId") or ""
    ).strip()
    project_id = str(record.get("projectId") or "").strip()
    input_snapshot_hash = str(node_run.get("inputSnapshotHash") or "").strip()
    stage_id = _MODEL_INVOCATION_STAGES.get(node_id, "")
    if (
        not isinstance(required_policy, dict)
        or not policy_sha256
        or not question_id
        or not workflow_run_id
        or not workflow_id
        or not workflow_version_id
        or not project_id
        or not input_snapshot_hash
        or not stage_id
        or str(route.get("agentId") or "").strip() != str(agent_id or "").strip()
    ):
        raise AgentNodeExecutionError(
            "formal project Agent task contract is incomplete",
            code="challenge_task_contract_incomplete",
        )
    return {
        "schemaVersion": 1,
        "questionId": question_id,
        "researchProjectId": project_id,
        "runId": workflow_run_id,
        "workflowRunId": workflow_run_id,
        "workflowId": workflow_id,
        "workflowVersionId": workflow_version_id,
        "workflowNodeId": node_id,
        "nodeRunId": str(node_run_id or "").strip(),
        "nodeAttempt": int(node_run.get("attempt") or 1),
        "inputSnapshotHash": input_snapshot_hash,
        "modelPolicySha256": policy_sha256,
        "requiredModelPolicy": dict(required_policy),
        "stageId": stage_id,
        "agentId": str(agent_id or "").strip(),
        "productRoleId": str(route.get("productRoleId") or "").strip(),
        "effectiveRoute": {
            "modelRef": str(route.get("modelRef") or "").strip(),
            "providerId": str(route.get("providerId") or "").strip(),
            "modelId": str(route.get("modelId") or "").strip(),
        },
        "executionPolicy": {
            "routeSource": "workflow_run_model_routing_policy",
            "configuredModelAuthoritative": True,
        },
        "evidencePolicy": {
            "recordCanonicalSuccessOnly": True,
            "rawPayloadPersistence": "forbidden",
            "publishRequiredForProgramLedger": True,
            "officialEvidenceEligible": True,
        },
    }


def _formal_task_authorities(
    *,
    action: Any,
    input_snapshot: Mapping[str, Any],
    agent_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build both server-owned contracts for a Ledger ``PendingAction``.

    ``RealDomainPorts`` is backed by the Ledger rather than the legacy
    ``WorkflowRunStore``.  Build the smallest record shape understood by the
    existing authority helpers so their node/model mappings remain the single
    source of truth.  Incomplete or drifted action/snapshot identity is a hard
    stop: an empty binding must never be sent to a real Agent task.
    """

    snapshot = dict(input_snapshot) if isinstance(input_snapshot, Mapping) else {}
    run_id = str(getattr(action, "run_id", "") or "").strip()
    node_id = str(getattr(action, "node_id", "") or "").strip()
    node_run_id = str(getattr(action, "node_run_id", "") or "").strip()
    question_id = str(snapshot.get("questionId") or "").strip().upper()
    project_id = str(snapshot.get("projectId") or "").strip()
    workflow_id = str(snapshot.get("workflowId") or "").strip()
    workflow_version_id = str(snapshot.get("workflowVersionId") or "").strip()
    action_snapshot_hash = str(
        getattr(action, "input_snapshot_hash", "") or ""
    ).strip()
    snapshot_hash = str(snapshot.get("snapshotHash") or "").strip()
    if snapshot_hash and action_snapshot_hash and snapshot_hash != action_snapshot_hash:
        raise AgentNodeExecutionError(
            "formal task authority input snapshot hash drifted",
            code="formal_task_authority_snapshot_mismatch",
        )
    input_snapshot_hash = action_snapshot_hash or snapshot_hash
    try:
        node_attempt = int(getattr(action, "attempt", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise AgentNodeExecutionError(
            "formal task authority node attempt is invalid",
            code="formal_task_authority_incomplete",
        ) from exc
    if not all(
        (
            run_id,
            node_id,
            node_run_id,
            question_id,
            project_id,
            workflow_id,
            workflow_version_id,
            str(agent_id or "").strip(),
            input_snapshot_hash,
        )
    ) or node_attempt <= 0:
        raise AgentNodeExecutionError(
            "formal task authority is incomplete",
            code="formal_task_authority_incomplete",
        )
    record = {
        "runId": run_id,
        "questionId": question_id,
        "projectId": project_id,
        "workflowId": workflow_id,
        "workflowVersionId": workflow_version_id,
        "inputSnapshot": snapshot,
        "nodeRuns": [
            {
                "nodeId": node_id,
                "nodeRunId": node_run_id,
                "attempt": node_attempt,
                "agentId": str(agent_id).strip(),
                "inputSnapshotHash": input_snapshot_hash,
            }
        ],
    }
    contract = _challenge_task_contract(
        record,
        node_id=node_id,
        node_run_id=node_run_id,
        agent_id=str(agent_id).strip(),
    )
    receipt_binding = _model_invocation_receipt_binding(
        record,
        node_id=node_id,
        node_run_id=node_run_id,
    )
    if not contract or not receipt_binding:
        raise AgentNodeExecutionError(
            "formal task model invocation authority is unavailable",
            code="formal_task_authority_missing",
        )
    if (
        str(contract.get("workflowRunId") or "") != run_id
        or str(contract.get("workflowNodeId") or "") != node_id
        or str(contract.get("nodeRunId") or "") != node_run_id
        or str(receipt_binding.get("workflowRunId") or "") != run_id
        or str(receipt_binding.get("formalNodeId") or "") != node_id
        or str(receipt_binding.get("formalNodeRunId") or "") != node_run_id
        or int(contract.get("nodeAttempt") or 0) != node_attempt
        or int(receipt_binding.get("formalNodeAttempt") or 0) != node_attempt
    ):
        raise AgentNodeExecutionError(
            "formal task model invocation authority scope mismatch",
            code="formal_task_authority_scope_mismatch",
        )
    return contract, receipt_binding


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


def _hypothesis_chain_state(record: dict[str, Any]) -> dict[str, Any]:
    """Read the existing hypothesis chain state for the frozen run scope."""
    snapshot = record.get("inputSnapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    team_id = str(record.get("teamId") or snapshot.get("teamId") or "").strip()
    question_id = str(record.get("questionId") or snapshot.get("questionId") or "").strip()
    if not team_id or not question_id:
        return {}
    try:
        from core.web.services.team_workflow.research_runtime import hypothesis_first_chain

        state = hypothesis_first_chain.chain_state(team_id, question_id)
    except Exception:
        return {}
    return dict(state) if isinstance(state, dict) else {}


def _start_external_task(
    store: WorkflowRunStore,
    record: dict[str, Any],
    *,
    node_id: str,
    node_run_id: str,
    agent_id: str,
    idempotency_key: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    return_to = _return_to(record, node_id)
    if node_id in SOURCE_NODE_TASKS:
        record, source_run_id = _ensure_source_collection_run(store, record)
        stage_id, role_key = SOURCE_NODE_TASKS[node_id]
        source_challenge_task_contract = _challenge_task_contract(
            record,
            node_id=node_id,
            node_run_id=node_run_id,
            agent_id=agent_id,
        )
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
                    # A remediation scope must not force a fresh project-Agent
                    # session.  Stage-session status is the sole authority for
                    # deciding whether a formal retry is required.
                    "formalRetry": False,
                    "evidenceRemediationContract": dict(
                        record.get("evidenceRemediationContract") or {}
                    ),
                },
                # Keyword-only authority cannot be supplied through the
                # request payload handled by public source-task routes.
                _challenge_task_contract=source_challenge_task_contract,
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
            "targetRef": str(
                payload.get("targetRef") or f"node-run:{node_run_id}"
            ),
            "workflowRunId": str(record.get("runId") or ""),
            "workflowNodeId": node_id,
            "nodeRunId": node_run_id,
            "selectionId": str(payload.get("selectionId") or ""),
            "candidateId": str(payload.get("candidateId") or ""),
            "selectedCandidateIds": list(payload.get("selectedCandidateIds") or []),
            "subtaskId": str(payload.get("subtaskId") or ""),
            "candidateContext": dict(payload.get("candidateContext") or {}),
            "formalRetry": bool(payload.get("formalRetry")),
            "retryTaskId": str(payload.get("retryTaskId") or ""),
            "sourceCollectionRunId": str(
                record.get("sourceCollectionRunId") or ""
            ),
            "returnTo": return_to,
            "returnLabel": "科研工作流",
        },
        _challenge_task_contract=_challenge_task_contract(
            record,
            node_id=node_id,
            node_run_id=node_run_id,
            agent_id=agent_id,
        ),
        _model_invocation_receipt_binding=_model_invocation_receipt_binding(
            record,
            node_id=node_id,
            node_run_id=node_run_id,
        ),
    )
    return record, started


def _start_candidate_tasks(
    store: WorkflowRunStore,
    record: dict[str, Any],
    *,
    node_id: str,
    node_run_id: str,
    agent_id: str,
    idempotency_key: str,
    payload: dict[str, Any],
    bundle: dict[str, Any],
    fan_out: dict[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    snapshots = list(fan_out["candidateSnapshots"])
    subtasks = list(bundle.get("subtasks") or [])
    if len(subtasks) != len(snapshots):
        raise AgentNodeExecutionError(
            "TaskBundle candidate count no longer matches the bound selection",
            code="hypothesis_selection_replay_conflict",
        )
    starts: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    started_subtasks: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    from core.web.services.team_workflow.research_project_agent_tasks import (
        ResearchProjectAgentTaskError,
    )

    for subtask, candidate_context in zip(subtasks, snapshots, strict=True):
        scope = dict(subtask.get("scope") or {})
        candidate_id = str(scope.get("candidateId") or "").strip()
        if candidate_id != str(candidate_context.get("candidateId") or "").strip():
            raise AgentNodeExecutionError(
                "TaskBundle candidate order conflicts with the bound selection",
                code="hypothesis_selection_replay_conflict",
            )
        if str(subtask.get("taskId") or "").strip():
            if subtask.get("status") == "failed":
                raise AgentNodeExecutionError(
                    f"candidate {candidate_id} requires an explicit retryCandidateId",
                    code="candidate_retry_required",
                )
            anchor = {
                "agentId": agent_id,
                "taskId": str(subtask.get("taskId") or ""),
                "sessionId": str(subtask.get("sessionId") or ""),
                "sessionAttempt": int(subtask.get("attempt") or 1),
                "turnId": str(subtask.get("turnId") or ""),
            }
            starts.append(
                {
                    "taskId": anchor["taskId"],
                    "sessionId": anchor["sessionId"],
                    "sessionAttempt": anchor["sessionAttempt"],
                    "turn": {"turnId": anchor["turnId"]},
                    "chatRoute": (
                        f"/chat?session={anchor['sessionId']}"
                        if anchor["sessionId"]
                        else ""
                    ),
                    "idempotentReplay": True,
                }
            )
            anchors.append(anchor)
            started_subtasks.append(dict(subtask))
            continue
        try:
            record, started = _start_external_task(
                store,
                record,
                node_id=node_id,
                node_run_id=node_run_id,
                agent_id=agent_id,
                idempotency_key=f"{idempotency_key}:{candidate_id}",
                payload={
                    **payload,
                    "targetRef": f"hypothesis:{fan_out['selectionId']}:{candidate_id}",
                    "selectionId": fan_out["selectionId"],
                    "candidateId": candidate_id,
                    "selectedCandidateIds": list(fan_out["selectedCandidateIds"]),
                    "subtaskId": str(subtask.get("subtaskId") or ""),
                    "candidateContext": dict(candidate_context),
                },
            )
            anchor = _task_anchor(started)
            if str(anchor["agentId"] or "") != agent_id:
                raise AgentNodeExecutionError(
                    "started task Agent does not match the frozen NodeRun binding",
                    code="binding_agent_mismatch",
                )
            missing = [
                key
                for key in ("taskId", "sessionId", "turnId")
                if not str(anchor[key] or "")
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
            bundle = bind_agent_task_bundle(
                store,
                run_id=str(record["runId"]),
                bundle_id=str(bundle["bundleId"]),
                subtask_id=str(subtask.get("subtaskId") or ""),
                task_id=str(anchor["taskId"]),
                session_id=str(anchor["sessionId"]),
                turn_id=str(anchor["turnId"]),
            )
        except (AgentNodeExecutionError, ResearchProjectAgentTaskError, TaskBundleError) as exc:
            try:
                fail_agent_task_bundle_subtask(
                    store,
                    run_id=str(record["runId"]),
                    node_run_id=node_run_id,
                    subtask_id=str(subtask.get("subtaskId") or ""),
                    failure_code=str(
                        getattr(exc, "code", "candidate_task_start_failed")
                    ),
                    failure_summary=str(exc),
                    attempt=int(subtask.get("attempt") or 1),
                )
            except TaskBundleError:
                pass
            failures.append(
                {
                    "candidateId": candidate_id,
                    "code": str(getattr(exc, "code", "candidate_task_start_failed")),
                    "summary": str(exc),
                }
            )
            record = store.get_run(str(record["runId"])) or record
            bundle = next(
                item
                for item in record.get("taskBundles") or []
                if item.get("bundleId") == bundle.get("bundleId")
            )
            continue
        record = store.get_run(str(record["runId"])) or record
        starts.append(started)
        anchors.append(anchor)
        started_subtasks.append(dict(subtask))
    if not anchors:
        first_failure = failures[0] if failures else {
            "code": "candidate_task_start_failed",
            "summary": "No candidate task could be started.",
        }
        raise AgentNodeExecutionError(
            f"all candidate tasks failed to start: {first_failure['summary']}",
            code="candidate_fan_out_start_failed",
        )
    return record, bundle, starts, anchors, started_subtasks


def _retry_candidate_task(
    store: WorkflowRunStore,
    record: dict[str, Any],
    *,
    node_id: str,
    node_run: dict[str, Any],
    agent_id: str,
    idempotency_key: str,
    payload: dict[str, Any],
    fan_out: dict[str, Any],
    retry_candidate_id: str,
) -> dict[str, Any]:
    bundle_id = task_bundle_id(str(node_run["nodeRunId"]))
    bundle = next(
        (
            dict(item)
            for item in record.get("taskBundles") or []
            if item.get("bundleId") == bundle_id
        ),
        None,
    )
    if bundle is None:
        raise AgentNodeExecutionError(
            "candidate retry requires a persisted TaskBundle",
            code="candidate_retry_bundle_missing",
        )
    if retry_candidate_id not in {
        str(item) for item in fan_out.get("selectedCandidateIds") or []
    }:
        raise AgentNodeExecutionError(
            f"candidate retry target is outside the selected fan-out: {retry_candidate_id}",
            code="candidate_retry_not_selected",
        )
    target = next(
        (
            dict(item)
            for item in bundle.get("subtasks") or []
            if str((item.get("scope") or {}).get("candidateId") or "")
            == retry_candidate_id
        ),
        None,
    )
    if target is None:
        raise AgentNodeExecutionError(
            f"candidate retry target not found: {retry_candidate_id}",
            code="candidate_retry_target_missing",
        )
    target_subtask_id = str(target.get("subtaskId") or "")
    current_attempt = int(target.get("attempt") or 1)
    has_previous_task = bool(str(target.get("taskId") or "").strip())
    retry_key = str(idempotency_key or "").strip() or (
        f"agent-task:{node_run['nodeRunId']}:retry:{retry_candidate_id}:"
        f"a{current_attempt + (1 if has_previous_task else 0)}"
    )
    if (
        target.get("status") in {"pending", "queued", "running"}
        and str(target.get("retryIdempotencyKey") or "") == retry_key
    ):
        current = store.get_run(str(record["runId"])) or record
        route = next(
            (
                dict(item)
                for item in current.get("modelRoutingDecisions") or []
                if item.get("nodeRunId") == node_run.get("nodeRunId")
            ),
            {},
        )
        return {
            "command": "start_agent_task",
            "taskId": str(target.get("taskId") or ""),
            "chatRoute": (
                f"/chat?session={target.get('sessionId')}"
                if target.get("sessionId")
                else ""
            ),
            "sessionBinding": current.get("sessionBindings", {}).get(node_id, {})
            if isinstance(current.get("sessionBindings"), dict)
            else {},
            "taskBundle": next(
                item
                for item in current.get("taskBundles") or []
                if item.get("bundleId") == bundle_id
            ),
            "modelRoute": route,
            "idempotentReplay": True,
        }
    if target.get("status") != "failed":
        raise AgentNodeExecutionError(
            f"candidate retry requires failed subtask, got {target.get('status')}",
            code="candidate_retry_not_failed",
        )
    previous_task_id = str(target.get("taskId") or "").strip()
    candidate_context = next(
        (
            dict(item)
            for item in list(fan_out.get("candidateSnapshots") or [])
            if str(item.get("candidateId") or "") == retry_candidate_id
        ),
        {"candidateId": retry_candidate_id},
    )
    retry_payload = {
        **payload,
        "targetRef": f"hypothesis:{fan_out['selectionId']}:{retry_candidate_id}",
        "selectionId": fan_out["selectionId"],
        "candidateId": retry_candidate_id,
        "selectedCandidateIds": list(fan_out["selectedCandidateIds"]),
        "subtaskId": target_subtask_id,
        "candidateContext": candidate_context,
    }
    if previous_task_id:
        retry_payload.update(
            {
                "formalRetry": True,
                "retryTaskId": previous_task_id,
            }
        )
    record, started = _start_external_task(
        store,
        record,
        node_id=node_id,
        node_run_id=str(node_run.get("nodeRunId") or ""),
        agent_id=agent_id,
        idempotency_key=retry_key,
        payload=retry_payload,
    )
    anchor = _task_anchor(started)
    if str(anchor["agentId"] or "") != agent_id:
        raise AgentNodeExecutionError(
            "started retry task Agent does not match the frozen NodeRun binding",
            code="binding_agent_mismatch",
        )
    missing = [
        key for key in ("taskId", "sessionId", "turnId") if not str(anchor[key] or "")
    ]
    if missing:
        raise AgentNodeExecutionError(
            f"Agent retry task anchor is incomplete: {', '.join(missing)}",
            code="incomplete_task_anchor",
        )
    expected_attempt = current_attempt + (1 if previous_task_id else 0)
    if int(anchor["sessionAttempt"] or 1) != expected_attempt:
        raise AgentNodeExecutionError(
            "formal retry session attempt does not increment the candidate attempt",
            code="candidate_retry_attempt_mismatch",
        )
    _require_canonical_task_session(
        session_id=str(anchor["sessionId"]),
        agent_id=agent_id,
    )
    try:
        bundle = replace_agent_task_bundle_subtask(
            store,
            run_id=str(record["runId"]),
            bundle_id=bundle_id,
            subtask_id=target_subtask_id,
            retry_task_id=previous_task_id,
            task_id=str(anchor["taskId"]),
            session_id=str(anchor["sessionId"]),
            turn_id=str(anchor["turnId"]),
            attempt=expected_attempt,
            idempotency_key=retry_key,
        )
    except TaskBundleError as exc:
        raise AgentNodeExecutionError(
            str(exc),
            code=str(getattr(exc, "code", "candidate_retry_persistence_failed")),
        ) from exc
    record = store.get_run(str(record["runId"])) or record

    def reopen_candidate_node(current: dict[str, Any]) -> dict[str, Any]:
        node_runs = [dict(item) for item in current.get("nodeRuns") or []]
        current_node_run = next(
            (
                dict(item)
                for item in node_runs
                if item.get("nodeRunId") == node_run.get("nodeRunId")
            ),
            None,
        )
        if current_node_run is None:
            return current
        if current_node_run.get("status") == "blocked":
            current_node_run.update(
                {
                    "status": "running",
                    "finishedAt": "",
                    "failureCode": "",
                    "failureSummary": "",
                }
            )
            replace_by_id(
                node_runs,
                "nodeRunId",
                str(node_run["nodeRunId"]),
                current_node_run,
            )
        leases = [dict(item) for item in current.get("taskLeases") or []]
        for lease in leases:
            if (
                lease.get("nodeRunId") == node_run.get("nodeRunId")
                and lease.get("status") == "failed"
            ):
                lease["status"] = "running"
        return {
            **current,
            "status": "running" if current.get("status") == "blocked" else current.get("status"),
            "blockedReason": "" if current.get("status") == "blocked" else current.get("blockedReason", ""),
            "nodeRuns": node_runs,
            "taskLeases": leases,
        }

    record = store.mutate_run(str(record["runId"]), reopen_candidate_node)
    first_candidate_id = str(
        next(
            iter(fan_out.get("selectedCandidateIds") or []),
            retry_candidate_id,
        )
    )
    binding = (
        store.get_session_binding(str(record["runId"]), node_id)
        or {}
    )
    current_node_run = latest_node_run(record, node_id)
    if retry_candidate_id == first_candidate_id or not current_node_run.get("taskId"):
        role_key = next(
            (
                str(item.get("roleKey") or "")
                for item in record.get("bindingSnapshots") or []
                if item.get("nodeId") == node_id
            ),
            "",
        )
        binding = SessionBindingBridge(store).put(
            record,
            node_id,
            {
                "agentId": agent_id,
                "roleKey": role_key,
                "nodeRunId": str(node_run.get("nodeRunId") or ""),
                "nodeAttempt": int(node_run.get("attempt") or 1),
                "sessionId": str(anchor["sessionId"]),
                "sessionAttempt": int(anchor["sessionAttempt"]),
                "taskId": str(anchor["taskId"]),
                "turnId": str(anchor["turnId"]),
                "checkpointId": str(node_run.get("checkpointId") or ""),
            },
        )

        def sync_node_anchor(current: dict[str, Any]) -> dict[str, Any]:
            node_runs = [dict(item) for item in current.get("nodeRuns") or []]
            current_node_run = next(
                (
                    dict(item)
                    for item in node_runs
                    if item.get("nodeRunId") == node_run.get("nodeRunId")
                ),
                None,
            )
            if current_node_run is None:
                return current
            current_node_run.update(
                {
                    "taskId": str(anchor["taskId"]),
                    "sessionId": str(anchor["sessionId"]),
                    "turnId": str(anchor["turnId"]),
                    "failureCode": "",
                    "failureSummary": "",
                }
            )
            replace_by_id(
                node_runs,
                "nodeRunId",
                str(node_run["nodeRunId"]),
                current_node_run,
            )
            return {**current, "nodeRuns": node_runs}

        record = store.mutate_run(str(record["runId"]), sync_node_anchor)
    route = next(
        (
            dict(item)
            for item in record.get("modelRoutingDecisions") or []
            if item.get("nodeRunId") == node_run.get("nodeRunId")
        ),
        {},
    )
    if latest_node_run(record, node_id).get("status") == "ready":
        target_budget_ref = next(
            (
                str(item.get("budgetReservationRef") or "")
                for item in record.get("taskBundles") or []
                if item.get("bundleId") == bundle_id
                for item in item.get("subtasks") or []
                if str(item.get("subtaskId") or "") == target_subtask_id
            ),
            "",
        )
        try:
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
                    "budgetReservationRef": target_budget_ref,
                    "modelRef": route.get("modelRef", ""),
                    "modelPurpose": route.get("purpose", ""),
                    "estimatedCost": route.get("estimatedCost", 0),
                    "escalationReason": route.get("escalationReason", ""),
                },
            )
        except NodeExecutionError as exc:
            raise AgentNodeExecutionError(
                str(exc),
                code=str(getattr(exc, "code", "candidate_retry_execution_start_failed")),
            ) from exc
        record = store.get_run(str(record["runId"])) or record
    return {
        "command": "start_agent_task",
        "taskId": str(anchor["taskId"]),
        "chatRoute": str(started.get("chatRoute") or ""),
        "sessionBinding": binding,
        "taskBundle": bundle,
        "modelRoute": route,
        "idempotentReplay": bool(started.get("idempotentReplay")),
    }


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
    retry_candidate_id = str(payload.get("retryCandidateId") or "").strip()
    node_spec = next(
        item
        for item in build_challenge_cup_workflow_definition().nodes
        if item.nodeId == node_id
    )
    fan_out = None
    scope_shadow: dict[str, Any] | None = None
    scope_fallback: dict[str, str] | None = None
    candidate_fan_out: dict[str, Any] | None = None
    scope_mode = resolve_hypothesis_session_scope_mode(
        record.get("inputSnapshot") or {}
    )
    if (
        node_spec.sessionScopePolicy is NodeSessionScopePolicy.CANDIDATE_FAN_OUT
        and scope_mode != "off"
    ):
        scope_decision = resolve_hypothesis_scope_activation(
            record,
            chain_state=_hypothesis_chain_state(record),
        )
        if (
            scope_decision["fanOutEnabled"]
            or scope_decision["selectionRequired"]
        ):
            try:
                candidate_fan_out = load_hypothesis_fan_out_input(record)
            except ValueError as exc:
                raise AgentNodeExecutionError(
                    str(exc),
                    code="hypothesis_selection_invalid",
                ) from exc
        else:
            scope_fallback = {
                "status": "compatibility",
                "reason": str(scope_decision["fallbackReason"]),
                "mode": str(scope_decision["mode"]),
            }
        if scope_mode == "shadow" and candidate_fan_out is not None:
            selected_count = len(candidate_fan_out["selectedCandidateIds"])
            configured_limit = int(payload.get("maxConcurrency") or 3)
            budget_limit = int(
                ((record.get("inputSnapshot") or {}).get("budgetPolicy") or {}).get(
                    "maxParallelTasks"
                )
                or configured_limit
            )
            try:
                scope_shadow = evaluate_hypothesis_scope_shadow(
                    candidate_fan_out,
                    max_parallel=min(
                        selected_count,
                        configured_limit,
                        budget_limit,
                    ),
                )
            except ValueError as exc:
                raise AgentNodeExecutionError(
                    str(exc),
                    code="hypothesis_scope_shadow_invalid",
                ) from exc
        # Shadow evaluates the v3 scope contract but preserves the legacy
        # single-session execution.  Only explicit ``on`` may fan out into
        # candidate child sessions.
        fan_out = candidate_fan_out if scope_mode == "on" else None
    if node_run.get("status") == "running" and node_run.get("taskId") and not retry_candidate_id:
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
        route = next(
            (
                item
                for item in record.get("modelRoutingDecisions") or []
                if item.get("nodeRunId") == node_run["nodeRunId"]
            ),
            {},
        )
        replay = {
            "command": "start_agent_task",
            "taskId": str(node_run.get("taskId") or ""),
            "chatRoute": "",
            "sessionBinding": binding or {},
            "taskBundle": bundle,
            "modelRoute": route,
            "idempotentReplay": True,
        }
        if scope_shadow is not None:
            replay["sessionScopeShadow"] = scope_shadow
        if scope_fallback is not None:
            replay["sessionScopeFallback"] = dict(scope_fallback)
        return replay
    if retry_candidate_id:
        if fan_out is None:
            raise AgentNodeExecutionError(
                "retryCandidateId is only valid for candidate fan-out nodes",
                code="candidate_retry_not_supported",
            )
        if not agent_id:
            raise AgentNodeExecutionError(
                "agent node is unbound",
                code="agent_unbound",
            )
        return _retry_candidate_task(
            store,
            record,
            node_id=node_id,
            node_run=node_run,
            agent_id=agent_id,
            idempotency_key=idempotency_key,
            payload=payload,
            fan_out=fan_out,
            retry_candidate_id=retry_candidate_id,
        )
    if node_run.get("status") != "ready":
        raise AgentNodeExecutionError(
            f"Agent node must be ready, got {node_run.get('status')}",
            code="invalid_node_state",
        )
    if not agent_id:
        raise AgentNodeExecutionError("agent node is unbound", code="agent_unbound")
    subtask_specs: list[dict[str, Any]] | None = None
    max_concurrency: int | None = None
    if fan_out is not None:
        selected_candidate_ids = list(fan_out["selectedCandidateIds"])
        raw_configured_limit = payload.get("maxConcurrency", 3)
        if (
            isinstance(raw_configured_limit, bool)
            or not isinstance(raw_configured_limit, int)
            or raw_configured_limit < 1
        ):
            raise AgentNodeExecutionError(
                "maxConcurrency must be a positive integer",
                code="invalid_max_concurrency",
            )
        configured_limit = raw_configured_limit
        budget_limit = int(
            ((record.get("inputSnapshot") or {}).get("budgetPolicy") or {}).get(
                "maxParallelTasks"
            )
            or configured_limit
        )
        max_concurrency = min(
            len(selected_candidate_ids), configured_limit, budget_limit
        )
        if len(selected_candidate_ids) > max_concurrency:
            raise AgentNodeExecutionError(
                "selected candidate count exceeds the effective maxConcurrency; "
                "reduce the selection or increase the concurrency limit",
                code="candidate_fan_out_concurrency_exceeded",
            )
        subtask_specs = [
            {
                "subtaskId": f"{node_run['nodeRunId']}:{fan_out['selectionId']}:{candidate_id}",
                "scope": WorkflowSessionScopeV3.candidate(
                    teamId=str(record.get("teamId") or ""),
                    researchProjectId=str(record.get("projectId") or ""),
                    agentId=agent_id,
                    workflowRunId=str(record.get("runId") or ""),
                    workflowNodeId=node_id,
                    selectionId=str(fan_out["selectionId"]),
                    candidateId=str(candidate_id),
                ).to_dict(),
            }
            for candidate_id in selected_candidate_ids
        ]
    try:
        model_route = select_model_route(record, node_run, payload)
        ensure_task_bundle_capacity(
            record,
            node_run_id=str(node_run["nodeRunId"]),
            subtask_count=len(subtask_specs or [{}]),
            max_concurrency=max_concurrency,
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
            subtask_specs=subtask_specs,
            max_concurrency=max_concurrency,
            selection_id=str((fan_out or {}).get("selectionId") or ""),
        )
    except (BudgetLifecycleError, ModelRoutingError, TaskBundleError) as exc:
        raise AgentNodeExecutionError(
            str(exc),
            code=str(getattr(exc, "code", "agent_task_contract_invalid")),
        ) from exc
    record = store.get_run(str(record["runId"])) or record
    if fan_out is not None:
        try:
            record, bundle, starts, anchors, started_subtasks = _start_candidate_tasks(
                store,
                record,
                node_id=node_id,
                node_run_id=str(node_run.get("nodeRunId") or ""),
                agent_id=agent_id,
                idempotency_key=idempotency_key,
                payload=payload,
                bundle=bundle,
                fan_out=fan_out,
            )
            primary = anchors[0]
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
                    "sessionId": str(primary["sessionId"]),
                    "sessionAttempt": int(primary["sessionAttempt"]),
                    "taskId": str(primary["taskId"]),
                    "turnId": str(primary["turnId"]),
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
                    "taskId": str(primary["taskId"]),
                    "sessionId": str(primary["sessionId"]),
                    "budgetReservationRef": str(
                        bundle["subtasks"][0]["budgetReservationRef"]
                    ),
                    "modelRef": model_route["modelRef"],
                    "modelPurpose": model_route["purpose"],
                    "estimatedCost": model_route["estimatedCost"],
                    "escalationReason": model_route["escalationReason"],
                },
            )
        except (SessionBindingError, NodeExecutionError, TaskBundleError) as exc:
            raise AgentNodeExecutionError(
                str(exc),
                code=str(getattr(exc, "code", "agent_task_persistence_failed")),
            ) from exc
        scoped_sessions = []
        for started, anchor, subtask in zip(
            starts, anchors, started_subtasks, strict=True
        ):
            detail = None
            try:
                from core.web.services import session_service

                detail = session_service.get_session_detail(
                    str(anchor["sessionId"]),
                    message_limit=0,
                    transcript_scope="none",
                )
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                detail = None
            scoped_sessions.append(
                {
                    "subtaskId": str(subtask.get("subtaskId") or ""),
                    "candidateId": str(
                        (subtask.get("scope") or {}).get("candidateId") or ""
                    ),
                    "taskId": str(anchor["taskId"]),
                    "sessionId": str(anchor["sessionId"]),
                    "parentSessionId": str(
                        (detail or {}).get("parentSessionId") or ""
                    ),
                    "rootSessionId": str((detail or {}).get("rootSessionId") or ""),
                    "chatRoute": str(started.get("chatRoute") or ""),
                }
            )
        return {
            "command": "start_agent_task",
            "taskId": str(primary["taskId"]),
            "taskIds": [str(item["taskId"]) for item in anchors],
            "chatRoute": str(starts[0].get("chatRoute") or ""),
            "sessionBinding": binding,
            "scopedSessions": scoped_sessions,
            "taskBundle": bundle,
            "modelRoute": model_route,
            "selection": dict(fan_out["selection"]),
            "idempotentReplay": all(
                bool(item.get("idempotentReplay")) for item in starts
            ),
        }
    record, started = _start_external_task(
        store,
        record,
        node_id=node_id,
        node_run_id=str(node_run.get("nodeRunId") or ""),
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
    result = {
        "command": "start_agent_task",
        "taskId": str(anchor["taskId"]),
        "chatRoute": str(started.get("chatRoute") or ""),
        "sessionBinding": binding,
        "taskBundle": bundle,
        "modelRoute": model_route,
        "idempotentReplay": False,
    }
    if scope_shadow is not None:
        result["sessionScopeShadow"] = scope_shadow
    if scope_fallback is not None:
        result["sessionScopeFallback"] = dict(scope_fallback)
    return result
