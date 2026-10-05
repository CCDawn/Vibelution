"""Bounded export endpoint for completed financial research Turns."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.web.services import financial_report_service as service

router = APIRouter(tags=["financial-reports"])


class FinancialReportExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessionId: str = Field(min_length=1, max_length=160)
    turnId: str = Field(min_length=1, max_length=160)
    format: Literal["markdown", "json", "docx", "pdf"]


class FinancialReportExportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessionId: str
    turnId: str
    format: Literal["markdown", "json", "docx", "pdf"]
    fileName: str
    mediaType: str
    encoding: Literal["utf8", "base64"]
    content: str


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
