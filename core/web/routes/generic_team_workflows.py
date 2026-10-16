"""Thin version-one generic workflow HTTP routes."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from core.web.services import generic_team_workflow_service as service
from core.web.services.team_workflow.generic.models import (
    ArtifactList, Command, Flow, FlowList, Run, RunList, SaveFlow, StartRun,
)


def _call(callback: Callable, *args):
    try:
        return callback(*args)
    except service.NotFound as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    except service.Conflict as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except (service.WorkflowError, ValidationError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc


def register_generic_team_workflow_routes(router: APIRouter) -> None:
    @router.get("/teams/{team_id}/workflows", response_model=FlowList)
    def workflows(team_id: str):
        return _call(service.list_flows, team_id)

    @router.put("/teams/{team_id}/workflows/{flow_id}", response_model=Flow)
    def save(team_id: str, flow_id: str, payload: SaveFlow):
        return _call(service.save_flow, team_id, flow_id, payload.model_dump())

    @router.get("/teams/{team_id}/workflow-runs", response_model=RunList)
    def runs(team_id: str):
        return _call(service.list_runs, team_id)

    @router.get("/teams/{team_id}/workflow-runs/{run_id}", response_model=Run)
    def run(team_id: str, run_id: str):
        return _call(service.get_run, team_id, run_id)

    @router.post("/teams/{team_id}/workflows/{flow_id}/runs", response_model=Run)
    def start(team_id: str, flow_id: str, payload: StartRun):
        return _call(service.start_run, team_id, flow_id, payload.model_dump())

    @router.post("/teams/{team_id}/workflow-runs/{run_id}/commands", response_model=Run)
    def command(team_id: str, run_id: str, payload: Command):
        return _call(service.command_run, team_id, run_id, payload.model_dump())

    @router.get("/teams/{team_id}/workflow-runs/{run_id}/artifacts", response_model=ArtifactList)
    def artifacts(team_id: str, run_id: str):
        return _call(service.artifacts, team_id, run_id)
