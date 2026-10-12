"""PDF preview and staging adapter over the governed financial evidence store."""

from __future__ import annotations

import base64
import binascii
import hashlib
from datetime import date, datetime
from zoneinfo import ZoneInfo

from core.web.services import agent_directory_service as directory
from core.web.services import financial_assistant_service as assistants
from core.web.services import team_knowledge_service as knowledge
from core.web.services.financial_backtest import official_pdf

MAX_BASE64_CHARS = ((official_pdf.MAX_PDF_BYTES + 2) // 3) * 4


class FinancialEvidenceImportError(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _require_assistant(agent_id: str) -> None:
    try:
        agent = directory.get_agent(agent_id)
    except directory.AgentDirectoryError as exc:
        raise FinancialEvidenceImportError("未找到金融助手", 404) from exc
    if not isinstance(agent, dict) or (agent.get("metadata") or {}).get("financialAssistantProfile") != assistants.PROFILE:
        raise FinancialEvidenceImportError("未找到金融助手", 404)
    if agent.get("status") != "active":
        raise FinancialEvidenceImportError("已归档的助手不能导入财报", 409)
    if not knowledge.get_financial_knowledge_base(agent_id=agent_id)["knowledgeBase"]:
        raise FinancialEvidenceImportError("财报专库尚未就绪", 409)


def preview_pdf(agent_id: str, source_url: str, pdf_base64: str = "", page: int | None = None) -> dict:
    """Read only: original bytes stay local; nothing is searchable or staged."""
    _require_assistant(agent_id)
    try:
        url = official_pdf.validate_official_pdf_url(source_url)
        if not url:
            raise FinancialEvidenceImportError("请提供巨潮资讯或交易所的官方HTTPS财报PDF链接")
        if pdf_base64:
            if len(pdf_base64) > MAX_BASE64_CHARS:
                raise FinancialEvidenceImportError("PDF不能超过20MB")
            try:
                pdf_bytes = base64.b64decode(pdf_base64, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise FinancialEvidenceImportError("PDF上传数据无效") from exc
            result = official_pdf.extract_official_pdf_pages(pdf_bytes, page=page)
        else:
            result = official_pdf.fetch_and_extract_official_pdf(url, page=page)
    except official_pdf.OfficialPdfError as exc:
        raise FinancialEvidenceImportError(str(exc)) from exc
    # The existing financial profile allows at most 60 excerpt lines. Keep an
    # exact prefix of each extracted page, never a generated financial summary.
    pages = []
    warnings = list(result.get("warnings") or [])
    for extracted_page in result.get("pages") or []:
        original = str(extracted_page["excerpt"])
        excerpt = "\n".join(original.splitlines()[:60]).strip()
        if excerpt != original.strip():
            warnings.append("部分页面仅预览前60行原文，未覆盖部分不进入证据库。")
        if excerpt:
            pages.append({"page": extracted_page["page"], "excerpt": excerpt, "excerptSha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest()})
    if not pages:
        raise FinancialEvidenceImportError("PDF没有可读取的文本页；扫描件需要先完成OCR，不能以模型回答替代原文")
    return {**result, "sourceUrl": url, "pages": pages, "warnings": list(dict.fromkeys(warnings)), "coverageStatus": "partial" if warnings else result.get("coverageStatus", "available")}


def stage_pdf_page(agent_id: str, payload: dict) -> dict:
    """Re-extract the same original and submit exactly one page for review."""
    parsed = preview_pdf(agent_id, payload["sourceUrl"], payload.get("pdfBase64", ""), payload["page"])
    if parsed["documentSha256"] != payload["expectedDocumentSha256"]:
        raise FinancialEvidenceImportError("PDF原件已变化，请重新预览后提交", 409)
    page = next((p for p in parsed["pages"] if p["page"] == payload["page"]), None)
    if page is None:
        raise FinancialEvidenceImportError("所选页不在原文预览范围内")
    ticker = payload["ticker"].strip()
    if len(ticker) != 6 or not ticker.isascii() or not ticker.isdigit() or ticker[0] not in "036489":
        raise FinancialEvidenceImportError("请填写六位A股代码")
    try:
        published = date.fromisoformat(payload["publishedDate"])
    except ValueError as exc:
        raise FinancialEvidenceImportError("披露日期无效") from exc
    if published > datetime.now(ZoneInfo("Asia/Shanghai")).date():
        raise FinancialEvidenceImportError("披露日期不能晚于今天")
    document_hash = parsed["documentSha256"]
    evidence = {
        "schemaVersion": 1, "evidenceKind": "original_pdf_excerpt",
        "sourceId": f"pdf-{document_hash[:24]}", "company": payload["company"],
        "ticker": ticker, "reportPeriod": payload["reportPeriod"],
        "reportVersion": payload["reportVersion"], "documentSha256": document_hash,
        "page": page["page"], "sourceUrl": parsed["sourceUrl"],
        "publishedAt": f"{published.isoformat()}T00:00:00+08:00",
        "excerptSha256": page["excerptSha256"],
    }
    # Native staging owns idempotency, provenance, review and library writes.
    return knowledge.stage_financial_evidence(agent_id=agent_id, evidence=evidence, excerpt=page["excerpt"])
