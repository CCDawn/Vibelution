"""Validate protocol plans and register their canonical workflow artifacts."""

from __future__ import annotations

import re
from typing import Any

from core.research.competition.question_result_package import (
    QuestionResultPackageError,
    normalize_research_plan,
)
from core.research.workflow.contracts import WorkflowRunInputSnapshot

from .workflow_artifact_store import put_workflow_artifact

_PLACEHOLDER_MARKERS = (
    "PENDING_BLOCKED",
    "PENDING_",
    "TODO",
    "TBD",
)
_NODE_ATTEMPT_RE = re.compile(r"-a(?P<attempt>[1-9][0-9]*)$")


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


def _formal_task(task_context: dict[str, Any]) -> dict[str, Any]:
    task = task_context.get("task")
    if not isinstance(task, dict):
        raise ValueError("Formal research plan requires a bound protocol_design task.")
    if task.get("taskKind") != "experiment_design" or task.get(
        "workflowNodeId"
    ) != "protocol_design":
        raise ValueError("Formal research plan requires a bound protocol_design task.")
    return task


def _snapshot_for_formal_task(
    *,
    team_id: str,
    task: dict[str, Any],
    protocol_input: dict[str, Any],
) -> WorkflowRunInputSnapshot:
    raw = protocol_input.get("inputSnapshot")
    if not isinstance(raw, dict) or not raw:
        raw = task.get("inputSnapshot")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("Formal protocol task is missing its frozen inputSnapshot.")
    try:
        snapshot = WorkflowRunInputSnapshot.from_dict(raw)
    except (QuestionResultPackageError, TypeError, ValueError, KeyError) as exc:
        raise ValueError(
            "Formal protocol task frozen inputSnapshot is invalid."
        ) from exc
    if snapshot.teamId != str(team_id or "").strip():
        raise ValueError(
            "Formal protocol task inputSnapshot team binding does not match."
        )
    if snapshot.projectId != _text(task.get("researchProjectId")):
        raise ValueError(
            "Formal protocol task inputSnapshot project binding does not match."
        )
    task_question_id = _text(task.get("questionId"))
    if task_question_id and snapshot.questionId != task_question_id:
        raise ValueError("Formal protocol task question binding does not match.")
    if not snapshot.researchScopeEnvelope or not snapshot.catalogScope:
        raise ValueError("Formal protocol task frozen scope is incomplete.")
    stored_hash = _text(task.get("inputSnapshotHash"))
    if stored_hash and snapshot.snapshotHash != stored_hash:
        raise ValueError("Formal protocol task inputSnapshotHash does not match.")
    return snapshot


def _producer_attempt(task: dict[str, Any]) -> int:
    try:
        attempt = int(task.get("attempt") or 0)
    except (TypeError, ValueError):
        attempt = 0
    if attempt > 0:
        return attempt
    match = _NODE_ATTEMPT_RE.search(_text(task.get("nodeRunId")))
    return int(match.group("attempt")) if match else 0


def prepare_research_plan(
    *,
    team_id: str,
    task_context: dict[str, Any],
    research_plan: Any,
) -> dict[str, Any]:
    """Validate and bind a v2 research plan before experiment-plan creation."""

    task = _formal_task(task_context)
    protocol_input = task_context.get("protocolInput")
    if not isinstance(protocol_input, dict):
        protocol_input = {}
    if research_plan in (None, "", [], {}):
        raise ValueError(
            "Formal protocol_design create_plan requires payload_json.researchPlan."
        )
    if protocol_input.get("status") != "ready":
        raise ValueError("Formal hypothesis_set is not ready for protocol design.")
    try:
        normalized = normalize_research_plan(research_plan)
    except (QuestionResultPackageError, TypeError, ValueError) as exc:
        raise ValueError(f"researchPlan is invalid: {exc}") from exc
    if _contains_placeholder(normalized):
        raise ValueError("researchPlan contains a placeholder.")

    workflow_run_id = _text(task.get("workflowRunId"))
    source_run_id = _text(task.get("sourceCollectionRunId"))
    node_run_id = _text(task.get("nodeRunId"))
    context_workflow_run_id = _text(protocol_input.get("workflowRunId"))
    context_source_run_id = _text(protocol_input.get("sourceCollectionRunId"))
    if not workflow_run_id or not source_run_id or not node_run_id:
        raise ValueError("Formal protocol task is missing workflow binding.")
    if context_workflow_run_id and context_workflow_run_id != workflow_run_id:
        raise ValueError("Formal protocol workflowRunId binding does not match.")
    if context_source_run_id and context_source_run_id != source_run_id:
        raise ValueError(
            "Formal protocol sourceCollectionRunId binding does not match."
        )
    if not node_run_id.startswith(
        f"nr-{workflow_run_id}-"
    ) or "-protocol_design-" not in node_run_id:
        raise ValueError(
            "Formal protocol nodeRunId binding does not belong to protocol_design."
        )
    snapshot = _snapshot_for_formal_task(
        team_id=team_id,
        task=task,
        protocol_input=protocol_input,
    )
    frozen_binding = (
        protocol_input.get("frozenBinding")
        if isinstance(protocol_input.get("frozenBinding"), dict)
        else {}
    )
    for field, expected in (
        ("teamId", str(team_id or "").strip()),
        ("workflowRunId", workflow_run_id),
        ("sourceCollectionRunId", source_run_id),
        ("questionId", snapshot.questionId),
        ("inputSnapshotHash", snapshot.snapshotHash),
    ):
        supplied = _text(frozen_binding.get(field))
        if supplied and supplied != expected:
            raise ValueError(f"Formal protocol frozen {field} binding does not match.")
    hypothesis_ref = _text(protocol_input.get("hypothesisSetRef"))
    hypothesis_hash = _text(protocol_input.get("hypothesisSetHash"))
    if not hypothesis_ref or not hypothesis_hash:
        raise ValueError(
            "Formal protocol input is missing the frozen hypothesis_set ref/hash."
        )
    return {
        "task": task,
        "protocolInput": protocol_input,
        "researchPlan": normalized,
        "workflowRunId": workflow_run_id,
        "sourceCollectionRunId": source_run_id,
        "snapshot": snapshot,
        "hypothesisSetRef": hypothesis_ref,
        "hypothesisSetHash": hypothesis_hash,
    }


def record_research_plan(
    *,
    team_id: str,
    task_context: dict[str, Any],
    plan_id: str,
    prepared: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one immutable research_plan sibling bound to a formal run."""

    binding = prepared or prepare_research_plan(
        team_id=team_id,
        task_context=task_context,
        research_plan=(
            task_context.get("researchPlan")
            if isinstance(task_context, dict)
            else None
        ),
    )
    task = binding["task"]
    snapshot = binding["snapshot"]
    plan_identity = _text(plan_id)
    if not plan_identity:
        raise ValueError("Formal research plan artifact requires planId.")
    producer = {
        "nodeRunId": _text(task.get("nodeRunId")),
        "attempt": _producer_attempt(task),
        "taskId": _text(task.get("taskId")),
        "sessionId": _text(task.get("sessionId")),
        "turnId": _text((task.get("turn") or {}).get("turnId")),
        "agentId": _text(task.get("agentId")),
    }
    if (
        producer["attempt"] <= 0
        or any(
            not producer[key]
            for key in ("nodeRunId", "taskId", "sessionId", "turnId", "agentId")
        )
    ):
        raise ValueError("Formal research plan producer binding is incomplete.")
    artifact_payload = {
        "planId": plan_identity,
        "teamId": _text(team_id),
        "workflowRunId": binding["workflowRunId"],
        "sourceCollectionRunId": binding["sourceCollectionRunId"],
        "questionId": snapshot.questionId,
        "inputSnapshotHash": snapshot.snapshotHash,
        "researchScopeEnvelope": dict(snapshot.researchScopeEnvelope),
        "catalogScope": dict(snapshot.catalogScope),
        "producer": producer,
        "hypothesisSetRef": binding["hypothesisSetRef"],
        "hypothesisSetHash": binding["hypothesisSetHash"],
        "researchPlan": dict(binding["researchPlan"]),
    }
    record = put_workflow_artifact(
        team_id,
        kind="research_plan",
        workflow_run_id=binding["workflowRunId"],
        source_collection_run_id=binding["sourceCollectionRunId"],
        artifact_identity=plan_identity,
        payload=artifact_payload,
    )
    return {
        "artifact": {
            "recordId": _text(record.get("recordId")),
            "kind": "research_plan",
            "workflowRunId": binding["workflowRunId"],
            "sourceCollectionRunId": binding["sourceCollectionRunId"],
            "contentHash": _text(record.get("contentHash")),
        },
        "scopeBinding": {
            "teamId": _text(team_id),
            "workflowRunId": binding["workflowRunId"],
            "sourceCollectionRunId": binding["sourceCollectionRunId"],
            "questionId": snapshot.questionId,
            "inputSnapshotHash": snapshot.snapshotHash,
        },
        "researchPlan": dict(binding["researchPlan"]),
    }


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
