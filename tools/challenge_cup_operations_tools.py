# -*- coding: utf-8 -*-
"""Controlled Challenge Cup experiment, iteration, and versioning tools."""

from __future__ import annotations

import json
from typing import Any


def challenge_cup_experiment_context_tool(team_id: str = "research-team", include_research_loop: bool = False) -> str:
    """Return bounded experiment planning ledger context for Challenge Cup Agents."""

    try:
        from core.web.services import team_workflow_orchestration_service as workflow_service

        payload: dict[str, Any] = {
            "status": "ok",
            "teamId": _text(team_id),
            "experimentPlanningStatus": workflow_service.get_experiment_planning_status(team_id),
            "boundaries": _operation_boundaries("experiment_planning_ledger_only_not_training_execution"),
        }
        if include_research_loop:
            from core.web.services import research_loop_service

            payload["researchLoopStatus"] = research_loop_service.get_research_loop_status(team_id)
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
) -> str:
    """Write experiment ledger records without executing training or smoke runners."""

    try:
        from core.web.services import team_workflow_orchestration_service as workflow_service

        normalized_operation = _text(operation)
        if normalized_operation in {"run_smoke", "execute_smoke", "run_training", "execute_training", "full_run"}:
            return _unsupported_operation(normalized_operation, boundary="experiment_planning_ledger_only_not_training_execution")
        payload = _json_object(payload_json)
        _stamp_agent(payload, recorded_by_agent, keys=("createdByAgent", "registeredByAgent", "recordedByAgent", "requestedByAgent"))
        if normalized_operation == "create_plan":
            response = workflow_service.create_experiment_plan(team_id, payload)
        elif normalized_operation == "register_baseline_artifact":
            response = workflow_service.register_experiment_baseline_artifact(team_id, plan_id, payload)
        elif normalized_operation == "register_smoke_result":
            response = workflow_service.register_experiment_smoke_result(team_id, plan_id, payload)
        elif normalized_operation == "register_full_run_result":
            response = workflow_service.register_experiment_full_run_result(team_id, plan_id, payload)
        elif normalized_operation == "request_knowledge_ingestion":
            response = workflow_service.request_experiment_result_knowledge_ingestion(team_id, plan_id, payload)
        else:
            return _unsupported_operation(normalized_operation, boundary="experiment_planning_ledger_only_not_training_execution")
        _record_tool_event(
            "tool.challenge_cup_experiment_writeback.completed",
            fields={
                "teamId": _text(team_id),
                "operation": normalized_operation,
                "planId": _text(plan_id),
                "recordedByAgent": _text(recorded_by_agent),
            },
        )
        return _json_dump({"status": "ok", "operation": normalized_operation, "response": response, "boundaries": _operation_boundaries("experiment_planning_ledger_only_not_training_execution")})
    except Exception as exc:
        return _tool_error(
            exc,
            event_code="tool.challenge_cup_experiment_writeback.failed",
            fields={"teamId": _text(team_id), "operation": _text(operation), "planId": _text(plan_id)},
        )


def challenge_cup_iteration_context_tool(team_id: str = "research-team", include_experiment: bool = True) -> str:
    """Return bounded Research Loop and optional experiment context."""

    try:
        from core.web.services import research_loop_service

        payload: dict[str, Any] = {
            "status": "ok",
            "teamId": _text(team_id),
            "templates": research_loop_service.list_research_loop_templates(),
            "researchLoopStatus": research_loop_service.get_research_loop_status(team_id),
            "boundaries": _operation_boundaries("research_loop_manual_record_and_command_preview_only"),
        }
        if include_experiment:
            from core.web.services import team_workflow_orchestration_service as workflow_service

            payload["experimentPlanningStatus"] = workflow_service.get_experiment_planning_status(team_id)
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
) -> str:
    """Write Research Loop planning/evidence/decision records without executing commands."""

    try:
        from core.web.services import research_loop_service

        normalized_operation = _text(operation)
        payload = _json_object(payload_json)
        _stamp_agent(payload, recorded_by_agent, keys=("createdByAgent", "recordedByAgent", "decidedByAgent"))
        if normalized_operation == "create_loop":
            response = research_loop_service.create_research_loop(team_id, payload)
        elif normalized_operation == "record_evidence":
            response = research_loop_service.record_research_loop_evidence(team_id, loop_id, payload)
        elif normalized_operation == "record_decision":
            response = research_loop_service.record_research_loop_decision(team_id, loop_id, payload)
        else:
            return _unsupported_operation(normalized_operation, boundary="research_loop_manual_record_and_command_preview_only")
        _record_tool_event(
            "tool.challenge_cup_iteration_writeback.completed",
            fields={
                "teamId": _text(team_id),
                "operation": normalized_operation,
                "loopId": _text(loop_id),
                "recordedByAgent": _text(recorded_by_agent),
            },
        )
        return _json_dump({"status": "ok", "operation": normalized_operation, "response": response, "boundaries": _operation_boundaries("research_loop_manual_record_and_command_preview_only")})
    except Exception as exc:
        return _tool_error(
            exc,
            event_code="tool.challenge_cup_iteration_writeback.failed",
            fields={"teamId": _text(team_id), "operation": _text(operation), "loopId": _text(loop_id)},
        )


def challenge_cup_versioning_context_tool(team_id: str = "research-team") -> str:
    """Return bounded candidate versioning ledger context."""

    try:
        from core.web.services import challenge_cup_versioning_service

        payload = {
            "status": "ok",
            "teamId": _text(team_id),
            "versioningStatus": challenge_cup_versioning_service.get_candidate_versioning_status(team_id),
            "boundaries": _operation_boundaries("candidate_versioning_ledger_only_not_official_graph"),
        }
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
) -> str:
    """Write candidate versioning ledger records without official graph/RAG writes."""

    try:
        from core.web.services import challenge_cup_versioning_service

        payload = {
            "operation": operation,
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
            "recordedByAgent": recorded_by_agent,
        }
        response = challenge_cup_versioning_service.record_candidate_version_event(team_id, payload)
        _record_tool_event(
            "tool.challenge_cup_versioning_writeback.completed",
            fields={"teamId": _text(team_id), "operation": _text(operation), "candidateId": _text(candidate_id)},
        )
        return _json_dump({"status": "ok", "operation": _text(operation), "response": response, "boundaries": _operation_boundaries("candidate_versioning_ledger_only_not_official_graph")})
    except Exception as exc:
        return _tool_error(
            exc,
            event_code="tool.challenge_cup_versioning_writeback.failed",
            fields={"teamId": _text(team_id), "operation": _text(operation), "candidateId": _text(candidate_id)},
        )


def _stamp_agent(payload: dict[str, Any], recorded_by_agent: str, *, keys: tuple[str, ...]) -> None:
    agent = _text(recorded_by_agent)
    if not agent:
        return
    for key in keys:
        payload.setdefault(key, agent)


def _unsupported_operation(operation: str, *, boundary: str) -> str:
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
    _record_tool_event(event_code, level="warning", outcome="failed", fields={**fields, "errorType": type(exc).__name__})
    return _json_dump(
        {
            "status": "error",
            "errorType": type(exc).__name__,
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
        )
    except Exception:
        return
