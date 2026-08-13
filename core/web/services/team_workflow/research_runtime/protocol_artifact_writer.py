"""Validate a canonical experiment plan and register its protocol snapshot."""

from __future__ import annotations

from typing import Any

from .workflow_artifact_store import put_workflow_artifact

_PLACEHOLDER_MARKERS = (
    "PENDING_BLOCKED",
    "PENDING_",
    "TODO",
    "TBD",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        upper = value.upper()
        return any(marker in upper for marker in _PLACEHOLDER_MARKERS)
    if isinstance(value, dict):
        return any(_contains_placeholder(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_placeholder(item) for item in value)
    return False


def _required_protocol_value(name: str, *candidates: Any) -> Any:
    value = next((item for item in candidates if item not in (None, "", [], {})), None)
    if value is None:
        raise ValueError(f"Protocol draft requires {name}.")
    if _contains_placeholder(value):
        raise ValueError(f"Protocol draft {name} contains a placeholder.")
    return value


def record_protocol_draft(
    *,
    team_id: str,
    task_context: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Write one immutable protocol draft bound to the formal task and plan."""
    task = (
        task_context.get("task")
        if isinstance(task_context.get("task"), dict)
        else {}
    )
    protocol_input = (
        task_context.get("protocolInput")
        if isinstance(task_context.get("protocolInput"), dict)
        else {}
    )
    if task.get("taskKind") != "experiment_design" or task.get(
        "workflowNodeId"
    ) != "protocol_design":
        raise ValueError("Protocol draft requires a bound protocol_design task.")
    if protocol_input.get("status") != "ready":
        raise ValueError("Formal hypothesis_set is not ready for protocol design.")
    workflow_run_id = _text(task.get("workflowRunId"))
    source_run_id = _text(task.get("sourceCollectionRunId"))
    task_id = _text(task.get("taskId"))
    plan_id = _text(plan.get("planId"))
    if not workflow_run_id or not source_run_id or not task_id or not plan_id:
        raise ValueError("Bound protocol task or plan is missing workflow identity.")
    if _text(plan.get("researchProjectId")) != _text(task.get("researchProjectId")):
        raise ValueError("Protocol plan belongs to another research project.")
    if _text(plan.get("createdFromTaskId")) != task_id:
        raise ValueError("Protocol plan was not created by the bound task.")
    validation = (
        plan.get("contractValidation")
        if isinstance(plan.get("contractValidation"), dict)
        else {}
    )
    if validation.get("valid") is not True:
        raise ValueError("Protocol plan contract validation did not pass.")
    contract = (
        plan.get("experimentContract")
        if isinstance(plan.get("experimentContract"), dict)
        else {}
    )
    method = (
        contract.get("methodConfig")
        if isinstance(contract.get("methodConfig"), dict)
        else {}
    )
    metric_contract = (
        contract.get("metricContract")
        if isinstance(contract.get("metricContract"), dict)
        else {}
    )
    decision = (
        contract.get("decisionContract")
        if isinstance(contract.get("decisionContract"), dict)
        else {}
    )
    reproducibility = (
        contract.get("reproducibilityContract")
        if isinstance(contract.get("reproducibilityContract"), dict)
        else {}
    )
    dataset = _required_protocol_value("dataset", method.get("dataset"))
    baseline = _required_protocol_value("baseline", method.get("baseline"))
    metric = _required_protocol_value(
        "metric", metric_contract.get("primaryMetric")
    )
    seeds = _required_protocol_value(
        "seed", reproducibility.get("seeds"), method.get("seeds")
    )
    budget = _required_protocol_value("budget", method.get("budget"))
    stop_condition = _required_protocol_value(
        "stop_condition", decision.get("failureCriteria")
    )
    smoke_plan = _required_protocol_value("smoke_plan", method.get("smokePlan"))
    hypothesis_candidates = [
        item
        for item in list(protocol_input.get("candidates") or [])
        if isinstance(item, dict) and _text(item.get("candidateId"))
    ]
    if not hypothesis_candidates:
        raise ValueError("Protocol draft requires at least one formal hypothesis.")
    artifact_payload = {
        "protocolId": plan_id,
        "planId": plan_id,
        "status": _text(plan.get("status")) or "draft",
        "dataset": dataset,
        "baseline": baseline,
        "metric": metric,
        "seed": seeds,
        "budget": budget,
        "stop_condition": stop_condition,
        "smoke_plan": smoke_plan,
        "hypothesisPortfolioId": _text(protocol_input.get("portfolioId")),
        "hypothesisRefs": [
            _text(item.get("candidateId")) for item in hypothesis_candidates
        ],
        "contractRevision": contract.get("revision"),
        "researchProjectId": _text(task.get("researchProjectId")),
        "createdFromTaskId": task_id,
        "createdFromSessionId": _text(task.get("sessionId")),
        "createdFromTurnId": _text((task.get("turn") or {}).get("turnId")),
    }
    record = put_workflow_artifact(
        team_id,
        kind="protocol_draft",
        workflow_run_id=workflow_run_id,
        source_collection_run_id=source_run_id,
        artifact_identity=plan_id,
        payload=artifact_payload,
    )
    return {
        "artifact": {
            "recordId": _text(record.get("recordId")),
            "kind": "protocol_draft",
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": source_run_id,
            "contentHash": _text(record.get("contentHash")),
        },
        "scopeBinding": {
            "workflowRunId": workflow_run_id,
            "source": "bound_protocol_task",
        },
    }
