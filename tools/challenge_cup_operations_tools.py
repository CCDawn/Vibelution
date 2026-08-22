# -*- coding: utf-8 -*-
"""Controlled Challenge Cup experiment, iteration, and versioning tools."""

from __future__ import annotations

import json
from typing import Any


_CANONICAL_CHALLENGE_CUP_ROLES = frozenset(
    {
        "challenge_cup_search",
        "challenge_cup_extractor",
        "challenge_cup_knowledge_manager",
        "challenge_cup_execution_steward",
        "challenge_cup_experiment_revision",
        "challenge_cup_evaluator",
    }
)
_CANONICAL_EXPERIMENT_WRITEBACK_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "challenge_cup_experiment_revision": {
        "record_hypothesis_fragment": ("hypothesis_design",),
        "record_hypothesis_set": ("hypothesis_design",),
        "create_plan": ("experiment_design",),
    },
    "challenge_cup_evaluator": {
        "record_protocol_review": ("protocol_review",),
        "register_baseline_artifact": ("experiment_evidence_review",),
        "register_smoke_result": ("experiment_evidence_review",),
        "register_full_run_result": ("experiment_evidence_review",),
    },
    "challenge_cup_execution_steward": {
        "register_baseline_artifact": ("experiment_evidence_review",),
        "register_smoke_result": ("experiment_evidence_review",),
        "register_full_run_result": ("experiment_evidence_review",),
    },
}
_CANONICAL_ITERATION_WRITEBACK_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "challenge_cup_experiment_revision": {
        "create_loop": ("iteration_decision",),
        "record_evidence": ("iteration_decision",),
        "record_decision": ("iteration_decision",),
    },
    "challenge_cup_evaluator": {
        "record_evidence": ("experiment_evidence_review",),
    },
}


class _CanonicalRoleWritebackError(ValueError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def _iteration_writeback_contract() -> dict[str, Any]:
    return {
        "create_loop": {
            "requiredFields": ["researchQuestion"],
            "example": {
                "researchQuestion": "Does the candidate improve the registered metric?",
                "templateId": "algorithm_model_experiment",
                "title": "Registered metric review",
            },
        },
        "record_evidence": {
            "requiredFields": ["evidenceType"],
            "oneOfEvidenceFields": [
                "summary",
                "metricName",
                "metricValue",
                "baselineMetricValue",
                "delta",
                "metrics",
                "artifact",
                "commandPreview",
                "source",
                "artifactRefs",
                "sourceRefs",
                "datasetRefs",
                "environmentRefs",
                "logRefs",
            ],
            "statusValues": [
                "passed",
                "failed",
                "needs_review",
                "not_applicable",
            ],
            "example": {
                "evidenceType": "metric_report",
                "status": "passed",
                "summary": (
                    "reconstruction_mse improved from 0.025838 to 0.007935"
                ),
                "metrics": {
                    "baseline": 0.025838,
                    "variant": 0.007935,
                    "improvement": 0.017903,
                },
            },
        },
        "record_decision": {
            "requiredFields": ["decision", "rationale"],
            "decisionValues": [
                "promote_to_iteration",
                "repair_and_repeat",
                "needs_more_evidence",
                "reject_or_archive",
                "accept_for_writeup",
            ],
            "example": {
                "decision": "accept_for_writeup",
                "rationale": (
                    "Registered evidence is sufficient for a bounded write-up."
                ),
                "nextActions": [
                    "Preserve the proxy-only boundary in the report."
                ],
            },
        },
    }


def challenge_cup_experiment_context_tool(
    team_id: str = "research-team",
    include_research_loop: bool = False,
    research_project_id: str = "",
    task_id: str = "",
) -> str:
    """Return bounded experiment planning ledger context for Challenge Cup Agents."""

    try:
        from core.web.services import team_workflow_orchestration_service as workflow_service

        project_task_binding = _project_task_binding(
            workflow_service,
            team_id=team_id,
            research_project_id=research_project_id,
            task_id=task_id,
            allowed_task_kinds=(
                "hypothesis_design",
                "experiment_design",
                "protocol_review",
                "experiment_evidence_review",
            ),
            recorded_by_agent="",
            load_context=True,
        )
        payload: dict[str, Any] = {
            "status": "ok",
            "teamId": _text(team_id),
            "boundaries": _operation_boundaries(
                "experiment_planning_ledger_only_not_training_execution"
            ),
        }
        if project_task_binding:
            bound_project_id, _bound_task_id = _project_task_identity(
                project_task_binding
            )
            payload["researchProjectId"] = bound_project_id
            payload["taskContext"] = project_task_binding
            payload["experimentPlanningStatus"] = project_task_binding.get(
                "experiment",
                {},
            )
        else:
            payload["experimentPlanningStatus"] = (
                workflow_service.get_experiment_planning_status(team_id)
            )
        if include_research_loop:
            if project_task_binding:
                payload["researchLoopStatus"] = {
                    "status": "project_scoped_unavailable",
                    "reason": (
                        "Project-scoped experiment task context does not expose "
                        "the team-wide Research Loop projection."
                    ),
                }
            else:
                from core.web.services import research_loop_service

                payload["researchLoopStatus"] = (
                    research_loop_service.get_research_loop_status(team_id)
                )
        _record_tool_event(
            "tool.challenge_cup_experiment_context.completed",
            fields={"teamId": _text(team_id), "includeResearchLoop": bool(include_research_loop)},
        )
        return _json_dump(payload)
    except Exception as exc:
        return _tool_error(
            exc,
            event_code="tool.challenge_cup_experiment_context.failed",
            fields={"teamId": _text(team_id)},
        )


def challenge_cup_experiment_writeback_tool(
    team_id: str = "research-team",
    operation: str = "create_plan",
    plan_id: str = "",
    payload_json: str = "",
    recorded_by_agent: str = "",
    research_project_id: str = "",
    task_id: str = "",
) -> str:
    """Write experiment ledger records without executing training or smoke runners."""

    try:
        from core.web.services import team_workflow_orchestration_service as workflow_service

        normalized_operation = _text(operation)
        if normalized_operation in {"run_smoke", "execute_smoke", "run_training", "execute_training", "full_run"}:
            return _unsupported_operation(normalized_operation, boundary="experiment_planning_ledger_only_not_training_execution")
        if normalized_operation in {
            "record_hypothesis_fragment",
            "record_hypothesis_set",
        }:
            allowed_task_kinds = ("hypothesis_design",)
        elif normalized_operation == "create_plan":
            allowed_task_kinds = ("experiment_design",)
        elif normalized_operation == "record_protocol_review":
            allowed_task_kinds = ("protocol_review",)
        else:
            allowed_task_kinds = ("experiment_evidence_review",)
        canonical_authority = _canonical_writeback_authority(
            surface="experiment",
            operation=normalized_operation,
            team_id=team_id,
            recorded_by_agent=recorded_by_agent,
        )
        if canonical_authority:
            allowed_task_kinds = canonical_authority["allowedTaskKinds"]
            recorded_by_agent = canonical_authority["agentId"]
        task_binding = _project_task_binding(
            workflow_service,
            team_id=team_id,
            research_project_id=research_project_id,
            task_id=task_id,
            allowed_task_kinds=allowed_task_kinds,
            recorded_by_agent=recorded_by_agent,
            load_context=normalized_operation
            in {
                "record_hypothesis_fragment",
                "record_hypothesis_set",
                "record_protocol_review",
            },
            require_binding=bool(canonical_authority),
        )
        _validate_canonical_task_binding(canonical_authority, task_binding)
        bound_project_id, bound_task_id = _project_task_identity(task_binding)
        task = (
            task_binding.get("task")
            if isinstance(task_binding, dict)
            and isinstance(task_binding.get("task"), dict)
            else task_binding
        )
        payload = _json_object(payload_json)
        actor_agent_id = (
            _text(task.get("agentId"))
            if isinstance(task, dict)
            else _text(recorded_by_agent)
        )
        _stamp_agent(
            payload,
            actor_agent_id,
            keys=(
                "createdByAgent",
                "registeredByAgent",
                "recordedByAgent",
                "requestedByAgent",
            ),
        )
        if task:
            payload["researchProjectId"] = bound_project_id
            payload["createdFromTaskId"] = bound_task_id
            payload["createdFromSessionId"] = _text(task.get("sessionId"))
            payload["createdFromTurnId"] = _text(
                (task.get("turn") or {}).get("turnId")
            )
        if normalized_operation == "record_hypothesis_fragment":
            if not isinstance(task_binding, dict) or not isinstance(task, dict):
                raise ValueError(
                    "record_hypothesis_fragment requires a bound candidate task."
                )
            from core.web.services.team_workflow.research_runtime.hypothesis_scoped_execution import (
                record_candidate_fragment_and_maybe_aggregate,
            )

            response = record_candidate_fragment_and_maybe_aggregate(
                team_id=team_id,
                task_context=task_binding,
                payload=payload,
            )
        elif normalized_operation == "record_hypothesis_set":
            if not isinstance(task_binding, dict) or not isinstance(task, dict):
                raise ValueError(
                    "record_hypothesis_set requires a bound hypothesis task."
                )
            from core.web.services.team_workflow.research_runtime.hypothesis_artifact_writer import (
                record_hypothesis_set,
            )

            response = record_hypothesis_set(
                team_id=team_id,
                task_context=task_binding,
                payload=payload,
            )
        elif normalized_operation == "record_protocol_review":
            if not isinstance(task_binding, dict) or not isinstance(task, dict):
                raise ValueError(
                    "record_protocol_review requires a bound protocol review task."
                )
            from core.web.services.team_workflow.research_runtime.protocol_review_artifact_writer import (
                record_protocol_review_report,
            )

            response = record_protocol_review_report(
                team_id=team_id,
                task_context=task_binding,
                payload=payload,
            )
        elif normalized_operation == "create_plan":
            response = workflow_service.create_experiment_plan(team_id, payload)
            if task:
                created_plan = (
                    response.get("plan")
                    if isinstance(response.get("plan"), dict)
                    else {}
                )
                if (
                    _text(created_plan.get("researchProjectId"))
                    != bound_project_id
                ):
                    raise ValueError(
                        "Created experiment plan was not bound to the requested research project."
                    )
                if _text(task.get("workflowNodeId")) == "protocol_design":
                    from core.web.services.team_workflow.research_project_protocol_context import (
                        build_protocol_input_context,
                    )
                    from core.web.services.team_workflow.research_runtime.protocol_artifact_writer import (
                        record_protocol_draft,
                    )

                    response["protocolDraft"] = record_protocol_draft(
                        team_id=team_id,
                        task_context={
                            "task": task,
                            "protocolInput": build_protocol_input_context(
                                team_id,
                                task,
                            ),
                        },
                        plan=created_plan,
                    )
        elif normalized_operation in {
            "register_baseline_artifact",
            "register_smoke_result",
            "register_full_run_result",
            "request_knowledge_ingestion",
        }:
            if task:
                workflow_service.require_research_project_experiment_plan(
                    team_id,
                    bound_project_id,
                    plan_id,
                )
            if normalized_operation == "register_baseline_artifact":
                response = workflow_service.register_experiment_baseline_artifact(
                    team_id,
                    plan_id,
                    payload,
                )
            elif normalized_operation == "register_smoke_result":
                response = workflow_service.register_experiment_smoke_result(
                    team_id,
                    plan_id,
                    payload,
                )
            elif normalized_operation == "register_full_run_result":
                response = workflow_service.register_experiment_full_run_result(
                    team_id,
                    plan_id,
                    payload,
                )
            else:
                response = (
                    workflow_service.request_experiment_result_knowledge_ingestion(
                        team_id,
                        plan_id,
                        payload,
                    )
                )
        else:
            return _unsupported_operation(
                normalized_operation,
                boundary="experiment_planning_ledger_only_not_training_execution",
            )
        task_status = None
        if task:
            if normalized_operation == "record_hypothesis_fragment":
                result_refs = [
                    _text(
                        ((response.get("fragment") or {}).get("artifact") or {}).get(
                            "recordId"
                        )
                    ),
                    _text(response.get("hypothesisSetRef")),
                ]
            else:
                result_refs = (
                [_text((response.get("artifact") or {}).get("recordId"))]
                if normalized_operation
                in {"record_hypothesis_set", "record_protocol_review"}
                else _experiment_writeback_result_refs(
                    operation=normalized_operation,
                    requested_plan_id=_text(plan_id),
                    response=response,
                )
                )
            result_refs = [item for item in result_refs if item]
            task_status = (
                workflow_service.update_research_project_agent_task_status(
                    team_id,
                    bound_project_id,
                    bound_task_id,
                    status="running",
                    result_refs=result_refs,
                )
            )
        _record_tool_event(
            "tool.challenge_cup_experiment_writeback.completed",
            fields={
                "teamId": _text(team_id),
                "researchProjectId": bound_project_id,
                "taskId": bound_task_id,
                "operation": normalized_operation,
                "planId": _text(plan_id),
                "recordedByAgent": actor_agent_id,
            },
        )
        return _json_dump(
            {
                "status": "ok",
                "operation": normalized_operation,
                "response": response,
                "task": task_status,
                "boundaries": _operation_boundaries(
                    "experiment_planning_ledger_only_not_training_execution"
                ),
            }
        )
    except Exception as exc:
        return _tool_error(
            exc,
            event_code="tool.challenge_cup_experiment_writeback.failed",
            fields={"teamId": _text(team_id), "operation": _text(operation), "planId": _text(plan_id)},
        )


def challenge_cup_iteration_context_tool(
    team_id: str = "research-team",
    include_experiment: bool = True,
    research_project_id: str = "",
    task_id: str = "",
) -> str:
    """Return bounded Research Loop and optional experiment context."""

    try:
        from core.web.services import research_loop_service

        from core.web.services import (
            team_workflow_orchestration_service as workflow_service,
        )

        project_task_context = _project_task_binding(
            workflow_service,
            team_id=team_id,
            research_project_id=research_project_id,
            task_id=task_id,
            allowed_task_kinds=("iteration_decision",),
            recorded_by_agent="",
            load_context=True,
        )
        bound_project_id, _bound_task_id = _project_task_identity(
            project_task_context
        )
        payload: dict[str, Any] = {
            "status": "ok",
            "teamId": _text(team_id),
            "templates": research_loop_service.list_research_loop_templates(),
            "writebackContract": _iteration_writeback_contract(),
            "researchLoopStatus": (
                _bounded_research_loop_status(
                    research_loop_service.get_research_loop_status(
                        team_id,
                        research_project_id=bound_project_id,
                    )
                )
                if project_task_context
                else research_loop_service.get_research_loop_status(team_id)
            ),
            "boundaries": _operation_boundaries("research_loop_manual_record_and_command_preview_only"),
        }
        if project_task_context:
            payload["researchProjectId"] = bound_project_id
            payload["taskContext"] = project_task_context
        if include_experiment:
            payload["experimentPlanningStatus"] = (
                project_task_context.get("experiment", {})
                if project_task_context
                else workflow_service.get_experiment_planning_status(team_id)
            )
        _record_tool_event(
            "tool.challenge_cup_iteration_context.completed",
            fields={"teamId": _text(team_id), "includeExperiment": bool(include_experiment)},
        )
        return _json_dump(payload)
    except Exception as exc:
        return _tool_error(
            exc,
            event_code="tool.challenge_cup_iteration_context.failed",
            fields={"teamId": _text(team_id)},
        )


def challenge_cup_iteration_writeback_tool(
    team_id: str = "research-team",
    operation: str = "create_loop",
    loop_id: str = "",
    payload_json: str = "",
    recorded_by_agent: str = "",
    research_project_id: str = "",
    task_id: str = "",
) -> str:
    """Write Research Loop planning/evidence/decision records without executing commands."""

    try:
        from core.web.services import research_loop_service
        from core.web.services import (
            team_workflow_orchestration_service as workflow_service,
        )

        normalized_operation = _text(operation)
        canonical_authority = _canonical_writeback_authority(
            surface="iteration",
            operation=normalized_operation,
            team_id=team_id,
            recorded_by_agent=recorded_by_agent,
        )
        allowed_task_kinds = (
            canonical_authority["allowedTaskKinds"]
            if canonical_authority
            else ("iteration_decision",)
        )
        if canonical_authority:
            recorded_by_agent = canonical_authority["agentId"]
        task = _project_task_binding(
            workflow_service,
            team_id=team_id,
            research_project_id=research_project_id,
            task_id=task_id,
            allowed_task_kinds=allowed_task_kinds,
            recorded_by_agent=recorded_by_agent,
            require_binding=bool(canonical_authority),
        )
        _validate_canonical_task_binding(canonical_authority, task)
        bound_project_id, bound_task_id = _project_task_identity(task)
        payload = _json_object(payload_json)
        actor_agent_id = (
            _text(task.get("agentId"))
            if isinstance(task, dict)
            else _text(recorded_by_agent)
        )
        _stamp_agent(
            payload,
            actor_agent_id,
            keys=("createdByAgent", "recordedByAgent", "decidedByAgent"),
        )
        if task:
            payload["researchProjectId"] = bound_project_id
        if normalized_operation == "create_loop":
            response = research_loop_service.create_research_loop(team_id, payload)
            if task:
                created_loop = (
                    response.get("loop")
                    if isinstance(response.get("loop"), dict)
                    else {}
                )
                if (
                    _text(created_loop.get("researchProjectId"))
                    != bound_project_id
                ):
                    raise ValueError(
                        "Created Research Loop was not bound to the requested research project."
                    )
        elif normalized_operation == "record_evidence":
            if task:
                research_loop_service.require_research_loop(
                    team_id,
                    loop_id,
                    research_project_id=bound_project_id,
                )
            response = research_loop_service.record_research_loop_evidence(team_id, loop_id, payload)
        elif normalized_operation == "record_decision":
            if task:
                research_loop_service.require_research_loop(
                    team_id,
                    loop_id,
                    research_project_id=bound_project_id,
                )
            response = research_loop_service.record_research_loop_decision(team_id, loop_id, payload)
        else:
            return _unsupported_operation(normalized_operation, boundary="research_loop_manual_record_and_command_preview_only")
        task_status = task
        if task and normalized_operation == "record_decision":
            task_status = (
                workflow_service.update_research_project_agent_task_status(
                    team_id,
                    bound_project_id,
                    bound_task_id,
                    status="completed",
                    result_refs=_iteration_writeback_result_refs(
                        requested_loop_id=_text(loop_id),
                        response=response,
                    ),
                )
            )
        _record_tool_event(
            "tool.challenge_cup_iteration_writeback.completed",
            fields={
                "teamId": _text(team_id),
                "researchProjectId": bound_project_id,
                "taskId": bound_task_id,
                "operation": normalized_operation,
                "loopId": _text(loop_id),
                "recordedByAgent": actor_agent_id,
            },
            child_log_payload=_iteration_writeback_child_log_payload(
                team_id=_text(team_id),
                operation=normalized_operation,
                requested_loop_id=_text(loop_id),
                response=response,
            ),
        )
        return _json_dump(
            {
                "status": "ok",
                "operation": normalized_operation,
                "response": response,
                "task": task_status,
                "boundaries": _operation_boundaries(
                    "research_loop_manual_record_and_command_preview_only"
                ),
            }
        )
    except Exception as exc:
        return _tool_error(
            exc,
            event_code="tool.challenge_cup_iteration_writeback.failed",
            fields={"teamId": _text(team_id), "operation": _text(operation), "loopId": _text(loop_id)},
        )


def challenge_cup_versioning_context_tool(
    team_id: str = "research-team",
    research_project_id: str = "",
    task_id: str = "",
) -> str:
    """Return bounded candidate versioning ledger context."""

    try:
        from core.web.services import challenge_cup_versioning_service
        from core.web.services import (
            team_workflow_orchestration_service as workflow_service,
        )

        project_task_context = _project_task_binding(
            workflow_service,
            team_id=team_id,
            research_project_id=research_project_id,
            task_id=task_id,
            allowed_task_kinds=("version_governance",),
            recorded_by_agent="",
            load_context=True,
        )
        bound_project_id, _bound_task_id = _project_task_identity(
            project_task_context
        )
        payload = {
            "status": "ok",
            "teamId": _text(team_id),
            "versioningStatus": (
                _bounded_versioning_status(
                    challenge_cup_versioning_service.get_candidate_versioning_status(
                        team_id,
                        research_project_id=bound_project_id,
                    )
                )
                if project_task_context
                else challenge_cup_versioning_service.get_candidate_versioning_status(
                    team_id
                )
            ),
            "boundaries": _operation_boundaries("candidate_versioning_ledger_only_not_official_graph"),
        }
        if project_task_context:
            payload["researchProjectId"] = bound_project_id
            payload["taskContext"] = project_task_context
        _record_tool_event("tool.challenge_cup_versioning_context.completed", fields={"teamId": _text(team_id)})
        return _json_dump(payload)
    except Exception as exc:
        return _tool_error(
            exc,
            event_code="tool.challenge_cup_versioning_context.failed",
            fields={"teamId": _text(team_id)},
        )


def challenge_cup_versioning_writeback_tool(
    team_id: str = "research-team",
    operation: str = "record_version",
    candidate_id: str = "",
    version_label: str = "",
    summary: str = "",
    reason: str = "",
    related_candidate_id: str = "",
    supersedes_version_id: str = "",
    derived_from_version_id: str = "",
    evidence_refs_json: str = "",
    change_set_json: str = "",
    metadata_json: str = "",
    recorded_by_agent: str = "",
    research_project_id: str = "",
    task_id: str = "",
) -> str:
    """Write candidate versioning ledger records without official graph/RAG writes."""

    try:
        from core.web.services import challenge_cup_versioning_service
        from core.web.services import (
            team_workflow_orchestration_service as workflow_service,
        )

        task = _project_task_binding(
            workflow_service,
            team_id=team_id,
            research_project_id=research_project_id,
            task_id=task_id,
            allowed_task_kinds=("version_governance",),
            recorded_by_agent=recorded_by_agent,
        )
        bound_project_id, bound_task_id = _project_task_identity(task)
        actor_agent_id = (
            _text(task.get("agentId"))
            if isinstance(task, dict)
            else _text(recorded_by_agent)
        )
        payload = {
            "operation": operation,
            "researchProjectId": bound_project_id if task else "",
            "candidateId": candidate_id,
            "versionLabel": version_label,
            "summary": summary,
            "reason": reason,
            "relatedCandidateId": related_candidate_id,
            "supersedesVersionId": supersedes_version_id,
            "derivedFromVersionId": derived_from_version_id,
            "evidenceRefs": _json_list(evidence_refs_json),
            "changeSet": _json_list(change_set_json),
            "metadata": _json_object(metadata_json),
            "recordedByAgent": actor_agent_id,
        }
        normalized_operation = _text(operation)
        if task and normalized_operation == "supersede":
            challenge_cup_versioning_service.require_candidate_version(
                team_id,
                supersedes_version_id,
                research_project_id=bound_project_id,
            )
        elif task and normalized_operation == "derive":
            challenge_cup_versioning_service.require_candidate_version(
                team_id,
                derived_from_version_id,
                research_project_id=bound_project_id,
            )
        response = challenge_cup_versioning_service.record_candidate_version_event(team_id, payload)
        if task:
            created_version = (
                response.get("event")
                if isinstance(response.get("event"), dict)
                else {}
            )
            if (
                _text(created_version.get("researchProjectId"))
                != bound_project_id
            ):
                raise ValueError(
                    "Created candidate version was not bound to the requested research project."
                )
        task_status = None
        if task:
            result_refs = _versioning_writeback_result_refs(response)
            task_status = (
                workflow_service.update_research_project_agent_task_status(
                    team_id,
                    bound_project_id,
                    bound_task_id,
                    status="completed",
                    result_refs=result_refs,
                )
            )
        _record_tool_event(
            "tool.challenge_cup_versioning_writeback.completed",
            fields={
                "teamId": _text(team_id),
                "researchProjectId": bound_project_id,
                "taskId": bound_task_id,
                "operation": normalized_operation,
                "candidateId": _text(candidate_id),
            },
            child_log_payload=_versioning_writeback_child_log_payload(
                team_id=_text(team_id),
                operation=_text(operation),
                response=response,
            ),
        )
        return _json_dump(
            {
                "status": "ok",
                "operation": normalized_operation,
                "response": response,
                "task": task_status,
                "boundaries": _operation_boundaries(
                    "candidate_versioning_ledger_only_not_official_graph"
                ),
            }
        )
    except Exception as exc:
        return _tool_error(
            exc,
            event_code="tool.challenge_cup_versioning_writeback.failed",
            fields={"teamId": _text(team_id), "operation": _text(operation), "candidateId": _text(candidate_id)},
        )


def research_knowledge_collection_tool(
    action: str = "inspect",
    scope: str = "",
    searchEnvelope: str = "",
    requirements: str = "",
    writebackPolicy: str = "",
) -> str:
    """D03 stage-1 knowledge collection through the single facade tool.

    This is the only Agent-visible interface for stage-1 knowledge collection.
    It validates the ResearchScopeEnvelope and the search envelope, then reuses
    the existing source-collection node/ledger/storage.  It never runs a
    provider search and never performs formal-knowledge, RAG, or graph writes.
    """

    try:
        from core.web.services.team_workflow.source_collection.facade import (
            research_knowledge_collection_facade,
        )

        payload = research_knowledge_collection_facade(
            action=action,
            scope=_json_object(scope),
            searchEnvelope=_json_object(searchEnvelope),
            requirements=_json_object(requirements),
            writebackPolicy=_json_object(writebackPolicy),
        )
        _record_tool_event(
            "tool.research_knowledge_collection.completed",
            fields={
                "action": _text(action),
                "scopeHash": _text(
                    (payload.get("scope") if isinstance(payload.get("scope"), dict) else {}).get("scopeHash")
                ),
                "runId": _text(
                    (payload.get("locator") if isinstance(payload.get("locator"), dict) else {}).get("runId")
                ),
                "created": bool(payload.get("created")),
                "found": bool(payload.get("found")),
                "status": _text(payload.get("status")),
            },
        )
        return _json_dump(payload)
    except Exception as exc:
        _record_tool_event(
            "tool.research_knowledge_collection.failed",
            level="warning",
            outcome="failed",
            fields={
                "action": _text(action),
                "errorType": type(exc).__name__,
            },
        )
        return _knowledge_collection_tool_error(exc, action=action)


def _knowledge_collection_tool_error(exc: Exception, *, action: str) -> str:
    return _json_dump(
        {
            "status": "error",
            "errorType": type(exc).__name__,
            "message": str(exc),
            "action": _text(action),
            "boundaries": {
                "autoExecution": False,
                "autoApply": False,
                "externalExecution": False,
                "writesFormalKnowledge": False,
                "writesRag": False,
                "writesOfficialGraph": False,
                "networkExecution": False,
                "providerWriteback": False,
                "directStageWriteback": False,
                "singleVisibleInterface": True,
                "boundary": "d03_knowledge_collection_facade_only",
            },
        }
    )


def _project_task_binding(
    workflow_service,
    *,
    team_id: str,
    research_project_id: str,
    task_id: str,
    allowed_task_kinds: tuple[str, ...],
    recorded_by_agent: str,
    load_context: bool = False,
    require_binding: bool = False,
) -> dict[str, Any] | None:
    project_id = _text(research_project_id)
    normalized_task_id = _text(task_id)
    allow_incomplete_recovery = False
    if bool(project_id) != bool(normalized_task_id):
        raise ValueError(
            "research_project_id and task_id must be provided together."
        )
    if not project_id:
        from core.web.services import agent_directory_service, session_service

        runtime = agent_directory_service.current_agent_runtime()
        runtime_session_id = _text(runtime.get("sessionId"))
        runtime_turn_id = _text(runtime.get("turnId"))
        runtime_agent_id = _text(runtime.get("agentId"))
        if not runtime_session_id or not runtime_turn_id:
            if require_binding:
                raise _CanonicalRoleWritebackError(
                    "formal_task_binding_required",
                    "Canonical Challenge Cup writeback requires a formal task-bound runtime.",
                )
            return None
        detail = session_service.get_session_detail(
            runtime_session_id,
            message_limit=0,
            transcript_scope="none",
        )
        experiment_binding = (
            detail.get("experimentBinding")
            if isinstance(detail, dict)
            and isinstance(detail.get("experimentBinding"), dict)
            else {}
        )
        if not experiment_binding:
            if require_binding:
                raise _CanonicalRoleWritebackError(
                    "formal_task_binding_required",
                    "Canonical Challenge Cup writeback requires a formal task binding.",
                )
            return None
        if _text(experiment_binding.get("teamId")) != _text(team_id):
            if require_binding:
                raise _CanonicalRoleWritebackError(
                    "role_operation_denied",
                    "Current runtime research project task belongs to another team.",
                )
            raise ValueError(
                "Current runtime research project task belongs to another team."
            )
        project_id = _text(experiment_binding.get("researchProjectId"))
        if not project_id:
            if require_binding:
                raise _CanonicalRoleWritebackError(
                    "formal_task_binding_required",
                    "Current runtime experiment binding is missing researchProjectId.",
                )
            raise ValueError(
                "Current runtime experiment binding is missing researchProjectId."
            )
        binding_agent_id = _text(experiment_binding.get("agentId"))
        if (
            runtime_agent_id
            and binding_agent_id
            and runtime_agent_id != binding_agent_id
        ):
            if require_binding:
                raise _CanonicalRoleWritebackError(
                    "role_operation_denied",
                    "Current runtime Agent does not match the experiment binding.",
                )
            raise ValueError(
                "Current runtime Agent does not match the experiment binding."
            )
        status = workflow_service.get_research_project_agent_task_status(
            team_id,
            project_id,
        )
        session_candidates = [
            item
            for item in list(status.get("tasks") or [])
            if isinstance(item, dict)
            and _text(item.get("sessionId")) == runtime_session_id
            and (
                not runtime_agent_id
                or _text(item.get("agentId")) == runtime_agent_id
            )
            and item.get("taskKind") in set(allowed_task_kinds)
        ]
        candidates = [
            item
            for item in session_candidates
            if _text((item.get("turn") or {}).get("turnId"))
            == runtime_turn_id
        ]
        used_session_fallback = not candidates and len(session_candidates) == 1
        if used_session_fallback:
            candidates = session_candidates
        if len(candidates) != 1:
            if require_binding:
                raise _CanonicalRoleWritebackError(
                    "formal_task_binding_required",
                    "Current runtime does not resolve to exactly one compatible research project Agent task.",
                )
            raise ValueError(
                "Current runtime does not resolve to exactly one compatible "
                "research project Agent task."
            )
        selected_task = candidates[0]
        normalized_task_id = _text(selected_task.get("taskId"))
        allow_incomplete_recovery = bool(
            used_session_fallback
            and selected_task.get("status") == "incomplete"
            and _text(selected_task.get("failureCode"))
            == "task_result_not_recorded"
            and not list(selected_task.get("resultRefs") or [])
        )
        recorded_by_agent = runtime_agent_id or recorded_by_agent
    if load_context:
        context_kwargs = (
            {"require_active": False}
            if allow_incomplete_recovery
            else {}
        )
        context = workflow_service.get_research_project_agent_task_context(
            team_id,
            project_id,
            normalized_task_id,
            **context_kwargs,
        )
        task = context.get("task") if isinstance(context.get("task"), dict) else {}
        if task.get("taskKind") not in set(allowed_task_kinds):
            raise ValueError(
                "Research project Agent task responsibility does not allow this context."
            )
        return context
    try:
        return workflow_service.require_research_project_agent_task(
            team_id,
            project_id,
            normalized_task_id,
            allowed_task_kinds=allowed_task_kinds,
            recorded_by_agent=_text(recorded_by_agent),
            require_active=not allow_incomplete_recovery,
        )
    except workflow_service.ResearchProjectAgentTaskError as exc:
        if not require_binding:
            raise
        error_type = (
            "formal_task_binding_required"
            if _text(getattr(exc, "code", "")) == "task_not_found"
            else "role_operation_denied"
        )
        raise _CanonicalRoleWritebackError(error_type, str(exc)) from exc


def _canonical_writeback_authority(
    *,
    surface: str,
    operation: str,
    team_id: str,
    recorded_by_agent: str,
) -> dict[str, Any] | None:
    from core.web.services import agent_directory_service

    runtime = agent_directory_service.current_agent_runtime()
    if not isinstance(runtime, dict):
        return None
    agent = runtime.get("agent") if isinstance(runtime.get("agent"), dict) else {}
    metadata = (
        agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    )
    role_candidates = {
        _text(value).lower()
        for value in (
            metadata.get("challengeCupTeamRoleKey"),
            metadata.get("challengeCupTeamRole"),
            agent.get("roleKey"),
            runtime.get("roleKey"),
        )
        if _text(value).lower() in _CANONICAL_CHALLENGE_CUP_ROLES
    }
    if not role_candidates:
        return None
    if len(role_candidates) != 1:
        raise _CanonicalRoleWritebackError(
            "role_operation_denied",
            "Canonical Challenge Cup runtime exposes conflicting product roles.",
        )
    role_key = next(iter(role_candidates))
    runtime_agent_id = _text(runtime.get("agentId"))
    nested_agent_id = _text(agent.get("agentId"))
    if runtime_agent_id and nested_agent_id and runtime_agent_id != nested_agent_id:
        raise _CanonicalRoleWritebackError(
            "role_operation_denied",
            "Canonical Challenge Cup runtime Agent identity is inconsistent.",
        )
    agent_id = runtime_agent_id or nested_agent_id
    if not agent_id:
        raise _CanonicalRoleWritebackError(
            "formal_task_binding_required",
            "Canonical Challenge Cup writeback requires a runtime Agent identity.",
        )
    managed_team_id = _text(metadata.get("challengeCupTeamId"))
    if managed_team_id and managed_team_id != _text(team_id):
        raise _CanonicalRoleWritebackError(
            "role_operation_denied",
            "Canonical Challenge Cup runtime belongs to another team.",
        )
    requested_actor = _text(recorded_by_agent)
    if requested_actor and requested_actor != agent_id:
        raise _CanonicalRoleWritebackError(
            "role_operation_denied",
            "Writeback actor does not match the canonical runtime Agent.",
        )
    rules = (
        _CANONICAL_EXPERIMENT_WRITEBACK_RULES
        if surface == "experiment"
        else _CANONICAL_ITERATION_WRITEBACK_RULES
    )
    allowed_task_kinds = rules.get(role_key, {}).get(operation)
    if not allowed_task_kinds:
        raise _CanonicalRoleWritebackError(
            "role_operation_denied",
            f"Canonical role {role_key} may not perform {surface} operation {operation}.",
        )
    return {
        "agentId": agent_id,
        "roleKey": role_key,
        "allowedTaskKinds": allowed_task_kinds,
    }


def _validate_canonical_task_binding(
    authority: dict[str, Any] | None,
    binding: dict[str, Any] | None,
) -> None:
    if not authority:
        return
    if not isinstance(binding, dict):
        raise _CanonicalRoleWritebackError(
            "formal_task_binding_required",
            "Canonical Challenge Cup writeback requires a formal task binding.",
        )
    task = binding.get("task") if isinstance(binding.get("task"), dict) else binding
    if not isinstance(task, dict) or not _text(task.get("taskId")):
        raise _CanonicalRoleWritebackError(
            "formal_task_binding_required",
            "Canonical Challenge Cup writeback requires an identified formal task.",
        )
    if _text(task.get("agentId")) != authority["agentId"]:
        raise _CanonicalRoleWritebackError(
            "role_operation_denied",
            "Formal task is assigned to another Agent.",
        )
    if _text(task.get("taskKind")) not in set(authority["allowedTaskKinds"]):
        raise _CanonicalRoleWritebackError(
            "role_operation_denied",
            "Formal task responsibility does not allow this role operation.",
        )


def _project_task_identity(
    binding: dict[str, Any] | None,
) -> tuple[str, str]:
    payload = binding if isinstance(binding, dict) else {}
    task = (
        payload.get("task")
        if isinstance(payload.get("task"), dict)
        else payload
    )
    return (
        _text(task.get("researchProjectId") or payload.get("researchProjectId")),
        _text(task.get("taskId")),
    )


def _experiment_writeback_result_refs(
    *,
    operation: str,
    requested_plan_id: str,
    response: dict[str, Any],
) -> list[str]:
    refs: list[str] = []
    candidate_records = [
        response.get("plan"),
        response.get("baselineArtifact"),
        response.get("smokeResult"),
        response.get("fullRunResult"),
        response.get("experimentResultPack"),
        (
            response.get("protocolDraft", {}).get("artifact")
            if isinstance(response.get("protocolDraft"), dict)
            else None
        ),
    ]
    for record in candidate_records:
        if not isinstance(record, dict):
            continue
        for key in (
            "planId",
            "artifactId",
            "smokeResultId",
            "fullRunResultId",
            "packId",
            "recordId",
        ):
            value = _text(record.get(key))
            if value and value not in refs:
                refs.append(value)
    if operation != "create_plan" and requested_plan_id and requested_plan_id not in refs:
        refs.insert(0, requested_plan_id)
    return refs[:24]


def _iteration_writeback_result_refs(
    *,
    requested_loop_id: str,
    response: dict[str, Any],
) -> list[str]:
    refs: list[str] = []
    loop = response.get("loop") if isinstance(response.get("loop"), dict) else {}
    decision = (
        response.get("decision")
        if isinstance(response.get("decision"), dict)
        else {}
    )
    proposal = (
        response.get("iterationProposal")
        if isinstance(response.get("iterationProposal"), dict)
        else {}
    )
    for value in (
        requested_loop_id,
        _text(loop.get("loopId")),
        _text(decision.get("decisionId")),
        _text(proposal.get("proposalId")),
    ):
        if value and value not in refs:
            refs.append(value)
    return refs[:24]


def _versioning_writeback_result_refs(
    response: dict[str, Any],
) -> list[str]:
    refs: list[str] = []
    event = response.get("event") if isinstance(response.get("event"), dict) else {}
    relation = (
        response.get("relation")
        if isinstance(response.get("relation"), dict)
        else {}
    )
    rejection = (
        response.get("rejection")
        if isinstance(response.get("rejection"), dict)
        else {}
    )
    for value in (
        _text(event.get("versionId")),
        _text(event.get("candidateId")),
        _text(relation.get("relationId")),
        _text(rejection.get("rejectionId")),
    ):
        if value and value not in refs:
            refs.append(value)
    return refs[:24]


def _bounded_research_loop_status(status: dict[str, Any]) -> dict[str, Any]:
    active_loop = (
        status.get("activeLoop")
        if isinstance(status.get("activeLoop"), dict)
        else {}
    )
    linked_experiment = (
        active_loop.get("linkedExperiment")
        if isinstance(active_loop.get("linkedExperiment"), dict)
        else {}
    )
    evidence = [
        {
            "evidenceId": _text(item.get("evidenceId")),
            "evidenceType": _text(item.get("evidenceType")),
            "status": _text(item.get("status")),
            "summary": _text(item.get("summary"))[:1200],
            "metricName": _text(item.get("metricName"))[:240],
            "metricValue": _text(item.get("metricValue"))[:240],
            "delta": _text(item.get("delta"))[:240],
        }
        for item in list(active_loop.get("evidenceRecords") or [])[-24:]
        if isinstance(item, dict)
    ]
    decisions = [
        {
            "decisionId": _text(item.get("decisionId")),
            "decision": _text(item.get("decision")),
            "statusAfterDecision": _text(item.get("statusAfterDecision")),
            "rationale": _text(item.get("rationale"))[:1200],
        }
        for item in list(active_loop.get("decisions") or [])[-12:]
        if isinstance(item, dict)
    ]
    return {
        "schemaVersion": status.get("schemaVersion", 1),
        "teamId": _text(status.get("teamId")),
        "researchProjectId": _text(status.get("researchProjectId")),
        "activeLoopId": _text(status.get("activeLoopId")),
        "activeLoop": {
            "loopId": _text(active_loop.get("loopId")),
            "researchProjectId": _text(active_loop.get("researchProjectId")),
            "templateId": _text(active_loop.get("templateId")),
            "title": _text(active_loop.get("title"))[:240],
            "researchQuestion": _text(active_loop.get("researchQuestion"))[:2000],
            "status": _text(active_loop.get("status")),
            "linkedExperiment": {
                "stageRoundId": _text(linked_experiment.get("stageRoundId")),
                "planId": _text(linked_experiment.get("planId")),
            },
            "evidenceRecords": evidence,
            "decisions": decisions,
            "readiness": dict(active_loop.get("readiness") or {}),
        }
        if active_loop
        else None,
        "loops": list(status.get("loops") or [])[-40:],
        "pendingDesignProposals": list(
            status.get("pendingDesignProposals") or []
        )[-12:],
        "summary": dict(status.get("summary") or {}),
        "boundaries": dict(status.get("boundaries") or {}),
    }


def _bounded_versioning_status(status: dict[str, Any]) -> dict[str, Any]:
    versions = [
        {
            "versionId": _text(item.get("versionId")),
            "researchProjectId": _text(item.get("researchProjectId")),
            "operation": _text(item.get("operation")),
            "candidateId": _text(item.get("candidateId")),
            "versionLabel": _text(item.get("versionLabel"))[:120],
            "summary": _text(item.get("summary"))[:1200],
            "reason": _text(item.get("reason"))[:1200],
            "status": _text(item.get("status")),
            "supersedesVersionId": _text(item.get("supersedesVersionId")),
            "derivedFromVersionId": _text(item.get("derivedFromVersionId")),
        }
        for item in list(status.get("versionHistory") or [])[-40:]
        if isinstance(item, dict)
    ]
    return {
        "schemaVersion": status.get("schemaVersion", 1),
        "teamId": _text(status.get("teamId")),
        "researchProjectId": _text(status.get("researchProjectId")),
        "versionHistory": versions,
        "relations": [
            {
                "relationId": _text(item.get("relationId")),
                "relationType": _text(item.get("relationType")),
                "sourceVersionId": _text(item.get("sourceVersionId")),
                "targetVersionId": _text(item.get("targetVersionId")),
                "candidateId": _text(item.get("candidateId")),
            }
            for item in list(status.get("relations") or [])[-60:]
            if isinstance(item, dict)
        ],
        "rejectionArchive": [
            {
                "rejectionId": _text(item.get("rejectionId")),
                "candidateId": _text(item.get("candidateId")),
                "versionId": _text(item.get("versionId")),
                "reason": _text(item.get("reason"))[:1200],
                "summary": _text(item.get("summary"))[:1200],
            }
            for item in list(status.get("rejectionArchive") or [])[-40:]
            if isinstance(item, dict)
        ],
        "summary": dict(status.get("summary") or {}),
        "boundaries": dict(status.get("boundaries") or {}),
    }


def _stamp_agent(payload: dict[str, Any], recorded_by_agent: str, *, keys: tuple[str, ...]) -> None:
    agent = _text(recorded_by_agent)
    if not agent:
        return
    for key in keys:
        payload.setdefault(key, agent)


def _iteration_writeback_child_log_payload(
    *,
    team_id: str,
    operation: str,
    requested_loop_id: str,
    response: dict[str, Any],
) -> dict[str, Any]:
    loop = response.get("loop") if isinstance(response.get("loop"), dict) else {}
    evidence = response.get("evidence") if isinstance(response.get("evidence"), dict) else {}
    decision = response.get("decision") if isinstance(response.get("decision"), dict) else {}
    proposal = response.get("iterationProposal") if isinstance(response.get("iterationProposal"), dict) else {}
    readiness = loop.get("readiness") if isinstance(loop.get("readiness"), dict) else {}
    return {
        "kind": "challenge_cup_iteration_writeback",
        "teamId": team_id,
        "operation": operation,
        "loopId": _text(requested_loop_id or loop.get("loopId") or response.get("loopId")),
        "templateId": _text(loop.get("templateId")),
        "evidenceId": _text(evidence.get("evidenceId")),
        "evidenceType": _text(evidence.get("evidenceType")),
        "evidenceStatus": _text(evidence.get("status")),
        "decisionId": _text(decision.get("decisionId")),
        "decision": _text(decision.get("decision")),
        "statusAfterDecision": _text(decision.get("statusAfterDecision") or loop.get("status")),
        "iterationProposalId": _text(proposal.get("proposalId") or decision.get("iterationProposalId")),
        "readyForDecision": bool(readiness.get("readyForDecision")),
        "artifactRefCount": len([item for item in list(evidence.get("artifactRefs") or []) if isinstance(item, dict)]),
        "sourceRefCount": len([item for item in list(evidence.get("sourceRefs") or []) if isinstance(item, dict)]),
        "boundary": "research_loop_manual_record_and_command_preview_only",
    }


def _versioning_writeback_child_log_payload(
    *,
    team_id: str,
    operation: str,
    response: dict[str, Any],
) -> dict[str, Any]:
    event = response.get("event") if isinstance(response.get("event"), dict) else {}
    relation = response.get("relation") if isinstance(response.get("relation"), dict) else {}
    rejection = response.get("rejection") if isinstance(response.get("rejection"), dict) else {}
    return {
        "kind": "challenge_cup_versioning_writeback",
        "teamId": team_id,
        "operation": operation,
        "candidateId": _text(event.get("candidateId")),
        "versionId": _text(event.get("versionId")),
        "versionLabel": _text(event.get("versionLabel")),
        "relationId": _text(relation.get("relationId")),
        "rejectionId": _text(rejection.get("rejectionId")),
        "evidenceRefCount": len([item for item in list(event.get("evidenceRefs") or []) if isinstance(item, dict)]),
        "changeSetCount": len([item for item in list(event.get("changeSet") or []) if isinstance(item, dict)]),
        "boundary": "candidate_versioning_ledger_only_not_official_graph",
    }


def _unsupported_operation(operation: str, *, boundary: str) -> str:
    _record_tool_event(
        "tool.challenge_cup_operation.unsupported_blocked",
        level="warning",
        outcome="blocked",
        fields={
            "operation": _text(operation),
            "boundary": _text(boundary),
            "errorType": "unsupported_operation",
        },
    )
    return _json_dump(
        {
            "status": "error",
            "errorType": "unsupported_operation",
            "message": f"Unsupported or unsafe operation: {operation}.",
            "operation": operation,
            "boundaries": _operation_boundaries(boundary),
        }
    )


def _tool_error(exc: Exception, *, event_code: str, fields: dict[str, Any]) -> str:
    error_type = _text(getattr(exc, "error_type", "")) or type(exc).__name__
    _record_tool_event(event_code, level="warning", outcome="failed", fields={**fields, "errorType": error_type})
    return _json_dump(
        {
            "status": "error",
            "errorType": error_type,
            "message": str(exc),
            "boundaries": _operation_boundaries("manual_ledger_only"),
        }
    )


def _operation_boundaries(boundary: str) -> dict[str, bool | str]:
    return {
        "autoExecution": False,
        "autoApply": False,
        "externalExecution": False,
        "trainingRunner": False,
        "sandboxRunner": False,
        "writesFormalKnowledge": False,
        "writesRag": False,
        "writesOfficialGraph": False,
        "createsExperimentAttempt": False,
        "requiresUserDecision": True,
        "boundary": boundary,
    }


def _json_object(raw: str) -> dict[str, Any]:
    text = _text(raw)
    if not text:
        return {}
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Expected JSON object.")
    return payload


def _json_list(raw: str) -> list[Any]:
    text = _text(raw)
    if not text:
        return []
    payload = json.loads(text)
    if not isinstance(payload, list):
        raise ValueError("Expected JSON array.")
    return payload


def _json_dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _record_tool_event(
    event_code: str,
    *,
    level: str = "info",
    outcome: str = "completed",
    fields: dict[str, Any] | None = None,
    child_log_payload: dict[str, Any] | None = None,
) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "challenge_cup_operations_tool",
            "tool",
            event_code,
            level=level,
            message=event_code,
            fields={"outcome": outcome, **dict(fields or {})},
            child_log_path="artifacts/challenge-cup-operations-tool-writeback.jsonl",
            child_log_payload=child_log_payload,
        )
    except Exception:
        return
