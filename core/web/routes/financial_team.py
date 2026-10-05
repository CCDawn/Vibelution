"""HTTP adapter for native financial analyst Agents and Session turns."""

from datetime import date as date_type
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from core.web.services import financial_team_service as service
from core.web.services import session_service
from core.web.services.agent_directory_service import AgentDirectoryError
from core.web.services.team_service import TeamServiceError

router = APIRouter(tags=["financial-team"])


class FinancialTeamRoleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["market", "fundamental", "news", "bull", "bear"]
    label: str
    agentId: str
    sessionId: str
    status: Literal["ready", "needs_attention", "not_created"]
    allowedTools: list[str]


class FinancialTeamResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assistantAgentId: str
    assistantSessionId: str
    teamId: str
    status: Literal["ready", "needs_attention", "needs_setup"]
    roles: list[FinancialTeamRoleResponse]
    modelBindings: dict
    assistantConfigRevision: int


class FinancialTeamRunRefResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agentId: str
    sessionId: str
    clientSubmissionId: str
    turnId: str


class FinancialTeamRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: int
    runId: str
    assistantAgentId: str
    teamId: str
    symbol: str
    periodDays: int
    researchDate: str | None = None
    depth: Literal["brief", "basic", "standard", "detailed", "exhaustive"] | None = None
    createdAt: str
    stage: Literal["research", "debate", "synthesis"]
    analysts: dict[str, FinancialTeamRunRefResponse]
    synthesis: FinancialTeamRunRefResponse


class FinancialTeamRunListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assistantAgentId: str
    runs: list[FinancialTeamRunResponse]


class FinancialTeamRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=16)
    periodDays: int = Field(default=30, ge=7, le=90)
    researchDate: date_type = Field(default_factory=date_type.today)
    depth: Literal["brief", "basic", "standard", "detailed", "exhaustive"] = "standard"


class FinancialTeamTurnAttachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessionId: str = Field(min_length=1, max_length=160)
    clientSubmissionId: str = Field(min_length=1, max_length=200)
    turnId: str = Field(min_length=1, max_length=200)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(
        exc,
        (
            service.FinancialTeamNotFoundError,
            service.FinancialTeamRunNotFoundError,
            session_service.SessionNotFoundError,
        ),
    ):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(
        exc,
        (
            service.FinancialTeamConflictError,
            service.FinancialTeamRunConflictError,
            service.FinancialTeamRunNotReadyError,
            session_service.SessionValidationError,
            session_service.SessionBusyError,
        ),
    ):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(
        exc, (service.FinancialTeamError, AgentDirectoryError, TeamServiceError)
    ):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="股票分析团队操作失败")


@router.get(
    "/financial-team/{assistant_agent_id}", response_model=FinancialTeamResponse
)
def financial_team_get(assistant_agent_id: str) -> dict:
    try:
        return service.get_financial_team(assistant_agent_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/financial-team/{assistant_agent_id}/provision",
    response_model=FinancialTeamResponse,
)
def financial_team_provision(assistant_agent_id: str) -> dict:
    try:
        return service.provision_financial_team(assistant_agent_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/financial-team/{assistant_agent_id}/runs",
    response_model=FinancialTeamRunListResponse,
)
def financial_team_runs_list(
    assistant_agent_id: str,
    limit: int = Query(default=20, ge=1, le=40),
) -> dict:
    try:
        return service.list_financial_team_runs(assistant_agent_id, limit=limit)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/financial-team/{assistant_agent_id}/runs", response_model=FinancialTeamRunResponse
)
def financial_team_run_create(
    assistant_agent_id: str,
    payload: FinancialTeamRunCreateRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=16, max_length=200
    ),
) -> dict:
    try:
        return service.create_financial_team_run(
            assistant_agent_id,
            symbol=payload.symbol,
            period_days=payload.periodDays,
            research_date=payload.researchDate.isoformat(),
            depth=payload.depth,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/financial-team/{assistant_agent_id}/runs/{run_id}",
    response_model=FinancialTeamRunResponse,
)
def financial_team_run_get(assistant_agent_id: str, run_id: str) -> dict:
    try:
        return service.get_financial_team_run(assistant_agent_id, run_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/financial-team/{assistant_agent_id}/runs/{run_id}/turns/{role}",
    response_model=FinancialTeamRunResponse,
)
def financial_team_turn_record(
    assistant_agent_id: str,
    run_id: str,
    role: str,
    payload: FinancialTeamTurnAttachRequest,
) -> dict:
    try:
        return service.record_financial_team_turn(
            assistant_agent_id,
            run_id,
            role,
            session_id=payload.sessionId,
            client_submission_id=payload.clientSubmissionId,
            turn_id=payload.turnId,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/financial-team/{assistant_agent_id}/runs/{run_id}/analysts/{role}/submit",
    response_model=FinancialTeamRunResponse,
)
def financial_team_primary_submit(
    assistant_agent_id: str,
    run_id: str,
    role: Literal["market", "fundamental", "news"],
) -> dict:
    try:
        return service.submit_financial_team_primary_role(
            assistant_agent_id, run_id, role
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/financial-team/{assistant_agent_id}/runs/{run_id}/synthesis",
    response_model=FinancialTeamRunResponse,
)
def financial_team_synthesis_submit(assistant_agent_id: str, run_id: str) -> dict:
    try:
        return service.submit_financial_team_synthesis(assistant_agent_id, run_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/financial-team/{assistant_agent_id}/runs/{run_id}/debate",
    response_model=FinancialTeamRunResponse,
)
def financial_team_debate_submit(assistant_agent_id: str, run_id: str) -> dict:
    try:
        return service.submit_financial_team_debate(assistant_agent_id, run_id)
    except Exception as exc:
        raise _http_error(exc) from exc
