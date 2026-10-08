"""Bounded export endpoint for completed financial research Turns."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from core.web.services import financial_report_service as service
from core.web.services.financial_preferences_service import FinancialPreferenceError
from .financial_evaluation_models import (
    BacktestRequest, BacktestResult, ClaimPage, ClaimRecord, ClaimRequest,
    FeedbackPrompt, LessonRecord, LessonRequest, ReflectionContext,
)

router = APIRouter(tags=["financial-reports"])


def _evaluation(call, *args):
    try:
        return call(*args)
    except FinancialPreferenceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except service.FinancialReportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.FinancialReportUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.FinancialReportInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/financial-reports/{assistant_agent_id}/validations", response_model=ClaimPage)
def report_validations(assistant_agent_id: str) -> dict:
    return _evaluation(service.list_report_validations, assistant_agent_id)


@router.post("/financial-reports/{assistant_agent_id}/validations", response_model=ClaimRecord)
def create_report_validation(assistant_agent_id: str, payload: ClaimRequest) -> dict:
    return _evaluation(service.create_report_validation, assistant_agent_id, payload.model_dump())


@router.post("/financial-reports/{assistant_agent_id}/validations/{validation_id}/check", response_model=ClaimRecord)
def check_report_validation(assistant_agent_id: str, validation_id: str) -> dict:
    return _evaluation(service.check_report_validation, assistant_agent_id, validation_id)


@router.get("/financial-reports/{assistant_agent_id}/validations/{validation_id}/feedback", response_model=FeedbackPrompt)
def report_feedback(assistant_agent_id: str, validation_id: str) -> dict:
    return _evaluation(service.report_feedback_prompt, assistant_agent_id, validation_id)


@router.post("/financial-reports/{assistant_agent_id}/validations/{validation_id}/lesson", response_model=LessonRecord)
def report_lesson(assistant_agent_id: str, validation_id: str, payload: LessonRequest) -> dict:
    return _evaluation(service.save_report_lesson, assistant_agent_id, validation_id, payload.text, payload.clientRequestId)


@router.get("/financial-reports/{assistant_agent_id}/reflection-context", response_model=ReflectionContext)
def reflection_context(assistant_agent_id: str, symbol: str = Query(max_length=24), analysisDate: str = Query(min_length=10, max_length=10)) -> dict:
    return _evaluation(service.report_reflection_context, assistant_agent_id, symbol, analysisDate)


@router.post("/financial-reports/{assistant_agent_id}/backtest", response_model=BacktestResult)
def report_backtest(assistant_agent_id: str, payload: BacktestRequest) -> dict:
    return _evaluation(service.backtest_research_strategy, assistant_agent_id, payload.model_dump())


class FinancialReportExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessionId: str = Field(min_length=1, max_length=160)
    turnId: str = Field(min_length=1, max_length=160)
    format: Literal["markdown", "json", "docx", "pdf", "pdf-file"]


class FinancialReportExportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessionId: str
    turnId: str
    format: Literal["markdown", "json", "docx", "pdf", "pdf-file"]
    fileName: str
    mediaType: str
    encoding: Literal["utf8", "base64"]
    content: str


class FinancialReportSummary(BaseModel):
    sessionId: str
    turnId: str
    title: str
    sessionTitle: str
    ticker: str | None
    marketCode: Literal["CN", "HK", "US"] | None
    completedAt: str
    preview: str
    chars: int
    kind: Literal["research", "review"]


class FinancialReportPage(BaseModel):
    items: list[FinancialReportSummary]
    nextCursor: str | None
    scannedSessions: int
    order: Literal["session_recency"]


class FinancialReportTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessionId: str = Field(min_length=1, max_length=160)
    turnId: str = Field(min_length=1, max_length=160)


class FinancialReportsExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    targets: list[FinancialReportTarget] = Field(min_length=1, max_length=20)
    format: Literal["markdown", "json", "docx"]


class FinancialReportsExportResponse(BaseModel):
    fileName: str
    mediaType: Literal["application/zip"]
    encoding: Literal["base64"]
    content: str
    count: int


@router.get("/financial-reports/{assistant_agent_id}", response_model=FinancialReportPage)
def financial_report_list(assistant_agent_id: str, cursor: str = Query(default="", max_length=512), limit: int = Query(default=30, ge=1, le=50), q: str = Query(default="", max_length=120), marketCode: Literal["CN", "HK", "US", ""] = "", dateFrom: str = Query(default="", max_length=10), dateTo: str = Query(default="", max_length=10), kind: Literal["research", "review", ""] = "") -> dict:
    try:
        return service.list_financial_reports(assistant_agent_id, cursor=cursor, limit=limit, q=q, market_code=marketCode, date_from=dateFrom, date_to=dateTo, kind=kind)
    except service.FinancialReportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.FinancialReportInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/financial-reports/{assistant_agent_id}/export-batch", response_model=FinancialReportsExportResponse)
def financial_reports_export(assistant_agent_id: str, payload: FinancialReportsExportRequest) -> dict:
    try:
        return service.export_financial_reports(assistant_agent_id, targets=[target.model_dump() for target in payload.targets], format=payload.format)
    except service.FinancialReportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.FinancialReportTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except service.FinancialReportUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.FinancialReportInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/financial-reports/{assistant_agent_id}/export",
    response_model=FinancialReportExportResponse,
)
def financial_report_export(
    assistant_agent_id: str, payload: FinancialReportExportRequest
) -> dict[str, str]:
    try:
        return service.export_financial_report(
            assistant_agent_id,
            session_id=payload.sessionId,
            turn_id=payload.turnId,
            format=payload.format,
        )
    except service.FinancialReportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.FinancialReportTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except service.FinancialReportUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.FinancialReportInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
