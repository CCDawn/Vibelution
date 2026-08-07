"""Thin HTTP routes for research workflow runtime (ADR 0006)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Query
from pydantic import BaseModel, Field

from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
    get_research_workflow_runtime_service,
)

from ._router import router


class CreateRunPayload(BaseModel):
    teamId: str = ""
    projectId: str = ""
    idempotencyKey: str = ""


class HumanTaskResolvePayload(BaseModel):
    accept: bool
    resolvedBy: str = ""


class CommandPayload(BaseModel):
    command: str
    idempotencyKey: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class SessionBindingPayload(BaseModel):
    sessionId: str = ""
    taskId: str = ""
    turnId: str = ""
    agentId: str = ""
    roleKey: str = ""
    nodeRunId: str = ""
    nodeAttempt: int = 1
    sessionAttempt: int = 1
    checkpointId: str = ""
    supersedesBindingId: str = ""


def _svc():
    return get_research_workflow_runtime_service()


def _map_error(exc: ResearchWorkflowError) -> HTTPException:
    code = exc.code
    status = 404 if code.startswith("unknown") else 422
    return HTTPException(status_code=status, detail={"code": code, "message": str(exc)})


@router.get("/research/workflows/{workflow_id}/definition")
def research_workflow_definition(workflow_id: str) -> dict:
    try:
        return _svc().get_definition(workflow_id)
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.get("/research/workflows/{workflow_id}/runs")
def research_workflow_runs(workflow_id: str) -> dict:
    return _svc().list_runs(workflow_id)


@router.post("/research/workflows/{workflow_id}/runs", status_code=201)
def research_workflow_create_run(workflow_id: str, payload: CreateRunPayload) -> dict:
    try:
        return _svc().create_run(
            workflow_id,
            team_id=payload.teamId,
            project_id=payload.projectId,
            idempotency_key=payload.idempotencyKey,
        )
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.get("/research/workflow-runs/{run_id}")
def research_workflow_run(run_id: str) -> dict:
    try:
        return _svc().get_run(run_id)
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.get("/research/workflow-runs/{run_id}/canvas")
def research_workflow_run_canvas(run_id: str) -> dict:
    try:
        return _svc().get_canvas_projection(run_id)
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.get("/research/workflow-runs/{run_id}/nodes/{node_id}")
def research_workflow_node_detail(run_id: str, node_id: str) -> dict:
    try:
        return _svc().get_node_detail(run_id, node_id)
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.get("/research/workflow-runs/{run_id}/events")
def research_workflow_events(
    run_id: str,
    after_sequence: int = Query(0, alias="afterSequence"),
) -> dict:
    try:
        return _svc().list_events(run_id, after_sequence=after_sequence)
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.post("/research/workflow-runs/{run_id}/commands")
def research_workflow_command(run_id: str, payload: CommandPayload) -> dict:
    try:
        return _svc().apply_command(
            run_id,
            payload.command,
            idempotency_key=payload.idempotencyKey,
            payload=payload.payload,
        )
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.post("/research/workflow-runs/{run_id}/human-tasks/{task_id}/resolve")
def research_workflow_human_resolve(run_id: str, task_id: str, payload: HumanTaskResolvePayload) -> dict:
    try:
        return _svc().resolve_human_task(
            run_id,
            task_id,
            accept=payload.accept,
            resolved_by=payload.resolvedBy,
        )
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.put("/research/workflow-runs/{run_id}/nodes/{node_id}/session-binding")
def research_workflow_session_binding(run_id: str, node_id: str, payload: SessionBindingPayload) -> dict:
    try:
        return _svc().put_session_binding(run_id, node_id, payload.model_dump())
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc
