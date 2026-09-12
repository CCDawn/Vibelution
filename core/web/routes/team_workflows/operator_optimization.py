"""Independent operator campaign API, scoped by explicit project identity."""
from __future__ import annotations

from fastapi import HTTPException, Request
from pydantic import Field

from core.research.operator_optimization.contracts import (
    CampaignBudget,
    Contract,
    OperatorObjective,
    OptimizationCampaign,
    Text,
)
from core.research.operator_optimization.cuda_runner import CudaEnvironmentUnavailable
from core.research.operator_optimization.measurement import MeasurementProtocol
from core.web.services.team_service import TeamNotFoundError
from core.web.services.team_workflow.operator_optimization import store
from core.web.services.team_workflow.operator_optimization.baseline import (
    prepare_baseline,
)
from core.web.services.team_workflow.operator_optimization.commands import (
    authorize_campaign,
)
from core.web.services.team_workflow.research_projects import ResearchProjectError
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope_from_http,
)

from ._router import router
from .research_runtime_models import ResearchWorkflowCommandReceiptResponse


class CampaignCreateRequest(Contract):
    title: Text
    idempotencyKey: str = Field(min_length=1, max_length=200)
    objective: OperatorObjective = Field(default_factory=OperatorObjective)
    budget: CampaignBudget = Field(default_factory=CampaignBudget)


class CampaignCommandRequest(Contract):
    expectedCampaignVersion: int = Field(ge=1, strict=True)
    idempotencyKey: str = Field(min_length=1, max_length=200)


class CampaignListResponse(Contract):
    campaigns: tuple[OptimizationCampaign, ...]


class BaselinePrepareRequest(CampaignCommandRequest):
    protocol: MeasurementProtocol


class BaselineStartRequest(Contract):
    idempotencyKey: str = Field(min_length=1, max_length=200)
    expectedRunVersion: int = Field(ge=1, strict=True)


_PATH = "/teams/{team_id}/workflow-orchestration/research-projects/{project_id}/operator-experiments"


def _invoke(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except PermissionError as exc:
        raise HTTPException(403, detail={"code": "command_forbidden", "message": str(exc)}) from exc
    except store.CampaignConflict as exc:
        raise HTTPException(409, detail={"code": "campaign_conflict", "message": str(exc)}) from exc
    except CudaEnvironmentUnavailable as exc:
        raise HTTPException(409, detail={"code": "cuda_environment_unavailable", "message": str(exc)}) from exc
    except (FileNotFoundError, TeamNotFoundError) as exc:
        raise HTTPException(404, detail={"code": "campaign_scope_not_found", "message": str(exc)}) from exc
    except (ValueError, ResearchProjectError) as exc:
        raise HTTPException(422, detail={"code": "invalid_campaign_request", "message": str(exc)}) from exc


@router.post(_PATH, response_model=OptimizationCampaign)
def operator_campaign_create(team_id: str, project_id: str, payload: CampaignCreateRequest):
    return _invoke(store.create_campaign, team_id, project_id, payload.model_dump(mode="json"))


@router.get(_PATH, response_model=CampaignListResponse)
def operator_campaign_list(team_id: str, project_id: str):
    return {"campaigns": _invoke(store.list_campaigns, team_id, project_id)}


@router.get(_PATH + "/{campaign_id}", response_model=OptimizationCampaign)
def operator_campaign_get(team_id: str, project_id: str, campaign_id: str):
    return _invoke(store.read_campaign, team_id, project_id, campaign_id)


@router.post(_PATH + "/{campaign_id}/authorize", response_model=OptimizationCampaign)
def operator_campaign_authorize(team_id: str, project_id: str, campaign_id: str, payload: CampaignCommandRequest, request: Request):
    try:
        with server_operator_scope_from_http(request):
            return _invoke(authorize_campaign, team_id, project_id, campaign_id,
                expected_version=payload.expectedCampaignVersion, command_key=payload.idempotencyKey)
    except PermissionError as exc:
        raise HTTPException(403, detail={"code": "command_forbidden"}) from exc


@router.post(_PATH + "/{campaign_id}/baseline", response_model=OptimizationCampaign)
def operator_baseline_prepare(team_id: str, project_id: str, campaign_id: str, payload: BaselinePrepareRequest, request: Request):
    try:
        with server_operator_scope_from_http(request):
            return _invoke(prepare_baseline, team_id, project_id, campaign_id, protocol=payload.protocol,
                expected_version=payload.expectedCampaignVersion, command_key=payload.idempotencyKey)
    except PermissionError as exc:
        raise HTTPException(403, detail={"code": "command_forbidden"}) from exc


@router.post(_PATH + "/{campaign_id}/baseline/start",
    response_model=ResearchWorkflowCommandReceiptResponse, response_model_exclude_unset=True)
def operator_baseline_start(team_id: str, project_id: str, campaign_id: str, payload: BaselineStartRequest, request: Request):
    from core.research.workflow.contracts import WorkflowCommandKind

    from .research_runtime import _submit_workflow_command
    campaign = _invoke(store.read_campaign, team_id, project_id, campaign_id)
    if not campaign.baselineRunId:
        raise HTTPException(409, detail={"code": "baseline_not_prepared"})
    # Run version/idempotency and fresh readiness are owned by the canonical
    # command service. Campaign version must not mask a command replay.
    return _submit_workflow_command(run_id=campaign.baselineRunId, team_id=team_id,
        kind=WorkflowCommandKind.START_NODE, node_id="operator_baseline",
        expected_run_version=payload.expectedRunVersion, idempotency_key=payload.idempotencyKey,
        payload={}, request=request)


@router.post(_PATH + "/{campaign_id}/rounds", response_model=OptimizationCampaign)
def operator_round_prepare(team_id: str, project_id: str, campaign_id: str, payload: CampaignCommandRequest):
    from core.web.services.team_workflow.operator_optimization.rounds import (
        prepare_round,
    )
    return _invoke(prepare_round, team_id, project_id, campaign_id,
        expected_version=payload.expectedCampaignVersion, command_key=payload.idempotencyKey)
