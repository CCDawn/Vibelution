"""Operator PDF import adapter. Existing knowledge routes own review/ingestion."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.web.services import financial_evidence_import as service
from core.web.services import team_knowledge_service as knowledge

router = APIRouter(tags=["financial-evidence"])


class PdfPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sourceUrl: str = Field(min_length=1, max_length=2048)
    pdfBase64: str = Field(default="", max_length=service.MAX_BASE64_CHARS)


class PdfStageRequest(PdfPreviewRequest):
    company: str = Field(min_length=1, max_length=120)
    ticker: str = Field(pattern=r"^[036489]\d{5}$")
    reportPeriod: str = Field(pattern=r"^20\d{2}(FY|Q[1-4]|H[12])$")
    reportVersion: str = Field(default="original", min_length=1, max_length=96)
    publishedDate: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    page: int = Field(ge=1, le=240)
    expectedDocumentSha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _invoke(call, *args):
    try:
        return call(*args)
    except service.FinancialEvidenceImportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except knowledge.TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except knowledge.TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/financial-assistants/{agent_id}/evidence/preview")
def preview_financial_pdf(agent_id: str, payload: PdfPreviewRequest) -> dict:
    return _invoke(service.preview_pdf, agent_id, payload.sourceUrl, payload.pdfBase64)


@router.post("/financial-assistants/{agent_id}/evidence/stage")
def stage_financial_pdf(agent_id: str, payload: PdfStageRequest) -> dict:
    return _invoke(service.stage_pdf_page, agent_id, payload.model_dump())
