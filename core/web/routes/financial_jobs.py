"""HTTP routes for desktop financial research schedules and batches."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from core.web.services import financial_job_service as service
from core.web.services import financial_team_service as financial_team
from core.web.services import session_service
from core.web.services.agent_directory_service import AgentDirectoryError
from core.web.services.team_service import TeamServiceError

router = APIRouter(tags=["financial-jobs"])


class FinancialJobExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["now", "once", "daily", "weekdays"]
    timezone: Literal["Asia/Shanghai"]
    scheduledAt: str | None = None
    timeOfDay: str | None = None


class FinancialResearchScheduleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: list[str] = Field(min_length=1, max_length=10)
    periodDays: Literal[7, 30, 90]
    depth: Literal["brief", "basic", "standard", "detailed", "exhaustive"]
    execution: FinancialJobExecutionRequest
    researchDate: date | None = None


class FinancialJobExecutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["now", "once", "daily", "weekdays"]
    scheduledAt: str | None
    timeOfDay: str | None
    timezone: Literal["Asia/Shanghai"]


class FinancialResearchScheduleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheduleId: str
    assistantAgentId: str
    symbols: list[str]
    periodDays: Literal[7, 30, 90]
    depth: Literal["brief", "basic", "standard", "detailed", "exhaustive"]
    execution: FinancialJobExecutionResponse
    researchDate: str | None
    enabled: bool
    createdAt: str
    updatedAt: str
    nextRunAt: str | None
    lastBatchId: str | None
    lastTriggeredAt: str | None


class FinancialResearchTurnRefResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["market", "fundamental", "news", "bull", "bear", "synthesis"]
    sessionId: str
    turnId: str


class FinancialResearchBatchItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    status: Literal[
        "queued",
        "preparing",
        "submitting",
        "running",
        "completed",
        "failed",
        "cancelled",
        "blocked",
        "skipped",
    ]
    runId: str | None
    startedAt: str | None
    completedAt: str | None
    terminalReason: str | None
    turnRefs: list[FinancialResearchTurnRefResponse]


class FinancialResearchBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batchId: str
    scheduleId: str | None
    assistantAgentId: str
    status: Literal[
        "queued",
        "running",
        "stop_requested",
        "completed",
        "partial",
        "failed",
        "stopped",
        "blocked",
    ]
    triggeredAt: str
    updatedAt: str
    researchDate: str
    periodDays: Literal[7, 30, 90]
    depth: Literal["brief", "basic", "standard", "detailed", "exhaustive"]
    symbols: list[str]
    terminalReason: str | None
    items: list[FinancialResearchBatchItemResponse]


class FinancialResearchScheduleListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assistantAgentId: str
    schedules: list[FinancialResearchScheduleResponse]


class FinancialResearchBatchListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assistantAgentId: str
    batches: list[FinancialResearchBatchResponse]


class FinancialResearchScheduleCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schedule: FinancialResearchScheduleResponse
    batch: FinancialResearchBatchResponse | None


class FinancialResearchSchedulePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(
        exc,
        (
            service.FinancialJobNotFoundError,
            financial_team.FinancialTeamNotFoundError,
        ),
    ):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(
        exc,
        (
            service.FinancialJobConflictError,
            financial_team.FinancialTeamConflictError,
            financial_team.FinancialTeamRunConflictError,
            financial_team.FinancialTeamRunNotReadyError,
            session_service.SessionBusyError,
        ),
    ):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, service.FinancialJobStoreError):
        return HTTPException(status_code=500, detail="研究任务暂时无法安全读取")
    if isinstance(
        exc,
        (
            service.FinancialJobError,
            financial_team.FinancialTeamError,
            AgentDirectoryError,
            TeamServiceError,
            session_service.SessionValidationError,
        ),
    ):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="股票研究任务操作失败")


@router.get(
    "/financial-jobs/{assistant_agent_id}/schedules",
    response_model=FinancialResearchScheduleListResponse,
)
def financial_research_schedules_list(assistant_agent_id: str) -> dict:
    try:
        return service.list_financial_research_schedules(assistant_agent_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/financial-jobs/{assistant_agent_id}/schedules",
    response_model=FinancialResearchScheduleCreateResponse,
)
def financial_research_schedule_create(
    assistant_agent_id: str,
    payload: FinancialResearchScheduleCreateRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=16, max_length=200
    ),
) -> dict:
    try:
        return service.create_financial_research_schedule(
            assistant_agent_id,
            payload.model_dump(),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/financial-jobs/{assistant_agent_id}/schedules/{schedule_id}",
    response_model=FinancialResearchScheduleResponse,
)
def financial_research_schedule_update(
    assistant_agent_id: str,
    schedule_id: str,
    payload: FinancialResearchSchedulePatchRequest,
) -> dict:
    try:
        return service.update_financial_research_schedule(
            assistant_agent_id, schedule_id, enabled=payload.enabled
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/financial-jobs/{assistant_agent_id}/batches",
    response_model=FinancialResearchBatchListResponse,
)
def financial_research_batches_list(
    assistant_agent_id: str,
    limit: int = Query(default=60, ge=1, le=60),
) -> dict:
    try:
        return service.list_financial_research_batches(
            assistant_agent_id, limit=limit
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/financial-jobs/{assistant_agent_id}/batches/{batch_id}",
    response_model=FinancialResearchBatchResponse,
)
def financial_research_batch_get(assistant_agent_id: str, batch_id: str) -> dict:
    try:
        return service.get_financial_research_batch(assistant_agent_id, batch_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/financial-jobs/{assistant_agent_id}/batches/{batch_id}/stop",
    response_model=FinancialResearchBatchResponse,
)
def financial_research_batch_stop(assistant_agent_id: str, batch_id: str) -> dict:
    try:
        return service.stop_financial_research_batch(assistant_agent_id, batch_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/financial-jobs/{assistant_agent_id}/batches/{batch_id}/retry",
    response_model=FinancialResearchBatchResponse,
)
def financial_research_batch_retry(assistant_agent_id: str, batch_id: str) -> dict:
    try:
        return service.retry_financial_research_batch(assistant_agent_id, batch_id)
    except Exception as exc:
        raise _http_error(exc) from exc
