"""Import keeps native provenance, review gates and the exact previewed PDF."""

import base64
import hashlib

import pytest

from core.web.services import financial_evidence_import as imports

URL = "https://static.cninfo.com.cn/finalpage/2026-08-15/1225475868.PDF"
DOCUMENT = b"%PDF-1.7\nexample original"
HASH = hashlib.sha256(DOCUMENT).hexdigest()


@pytest.fixture
def importer(monkeypatch):
    monkeypatch.setattr(imports.directory, "get_agent", lambda _: {"status": "active", "metadata": {"financialAssistantProfile": imports.assistants.PROFILE}})
    monkeypatch.setattr(imports.knowledge, "get_financial_knowledge_base", lambda **_: {"knowledgeBase": {"profile": "financial_reports_v1"}})
    monkeypatch.setattr(imports.official_pdf, "extract_official_pdf_pages", lambda data: {"documentSha256": hashlib.sha256(data).hexdigest(), "pageCount": 8, "byteSize": len(data), "pages": [{"page": 5, "excerpt": "营业收入 200 元\n来源原文", "excerptSha256": "unused"}], "warnings": [], "numericValidation": "not_performed"})
    return {"sourceUrl": URL, "pdfBase64": base64.b64encode(DOCUMENT).decode(), "company": "贵州茅台", "ticker": "600519", "reportPeriod": "2026H1", "reportVersion": "original", "publishedDate": "2026-08-15", "page": 5, "expectedDocumentSha256": HASH}


def test_preview_does_not_stage_or_review(importer, monkeypatch):
    monkeypatch.setattr(imports.knowledge, "stage_financial_evidence", lambda **_: pytest.fail("Preview must not write"))
    result = imports.preview_pdf("finance", URL, importer["pdfBase64"])
    assert result["pages"][0]["excerpt"] == "营业收入 200 元\n来源原文"
    assert result["numericValidation"] == "not_performed"


def test_stage_uses_reextracted_original_not_caller_text(importer, monkeypatch):
    calls = []
    monkeypatch.setattr(imports.knowledge, "stage_financial_evidence", lambda **data: calls.append(data) or {"status": "pending_review"})
    assert imports.stage_pdf_page("finance", importer)["status"] == "pending_review"
    assert calls[0]["excerpt"] == "营业收入 200 元\n来源原文"
    assert calls[0]["evidence"]["documentSha256"] == HASH
    assert calls[0]["evidence"]["page"] == 5
    assert calls[0]["evidence"]["ticker"] == "600519"


@pytest.mark.parametrize("changes", [{"expectedDocumentSha256": "a" * 64}, {"page": 4}, {"publishedDate": "2099-01-01"}, {"ticker": "usMSFT"}])
def test_invalid_stage_never_writes(importer, monkeypatch, changes):
    monkeypatch.setattr(imports.knowledge, "stage_financial_evidence", lambda **_: pytest.fail("Invalid import must not write"))
    with pytest.raises(imports.FinancialEvidenceImportError):
        imports.stage_pdf_page("finance", {**importer, **changes})


@pytest.mark.parametrize("url", ["http://127.0.0.1/private.pdf", "https://evil.example/report.pdf"])
def test_nonofficial_or_private_source_rejected(importer, url):
    with pytest.raises(imports.FinancialEvidenceImportError):
        imports.preview_pdf("finance", url, importer["pdfBase64"])


def test_wrong_agent_profile_cannot_import(importer, monkeypatch):
    monkeypatch.setattr(imports.directory, "get_agent", lambda _: {"status": "active", "metadata": {}})
    with pytest.raises(imports.FinancialEvidenceImportError, match="未找到金融助手"):
        imports.preview_pdf("other", URL, importer["pdfBase64"])


def test_truncation_preserves_exact_page_prefix(importer, monkeypatch):
    original = "\n".join(f"原文第{i}行" for i in range(70))
    monkeypatch.setattr(imports.official_pdf, "extract_official_pdf_pages", lambda _: {"documentSha256": HASH, "pages": [{"page": 5, "excerpt": original}], "warnings": []})
    result = imports.preview_pdf("finance", URL, importer["pdfBase64"])
    assert result["pages"][0]["excerpt"] == "\n".join(original.splitlines()[:60])
    assert result["warnings"]
    assert result["coverageStatus"] == "partial"


def test_http_contract_cannot_submit_an_authored_excerpt(importer):
    from pydantic import ValidationError

    from core.web.routes.financial_evidence import PdfStageRequest

    with pytest.raises(ValidationError):
        PdfStageRequest.model_validate({**importer, "excerpt": "模型生成的利润数字"})


def test_http_preview_routes_use_exact_agent_and_input(importer, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.web.routes.financial_evidence import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as client:
        response = client.post("/api/financial-assistants/finance/evidence/preview", json={"sourceUrl": URL, "pdfBase64": importer["pdfBase64"]})
        assert response.status_code == 200
        assert response.json()["documentSha256"] == HASH
        rejected = client.post("/api/financial-assistants/finance/evidence/stage", json={**importer, "expectedDocumentSha256": "a" * 64})
        assert rejected.status_code == 409
