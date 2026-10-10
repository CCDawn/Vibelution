from __future__ import annotations

import copy
import hashlib
import io
from datetime import date, datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from core.web.services.financial_backtest import (
    financial_report_contract as report_contract,
)
from core.web.services.financial_backtest import frozen_financial_reports as frozen
from core.web.services.financial_backtest import official_pdf
from core.web.services.financial_backtest.contract import sha256_json
from core.web.services.financial_backtest.data import BacktestInputError

SOURCE = official_pdf.SOURCE
FETCHED_AT = "2025-11-04T00:00:00+00:00"
PDF_A = "https://static.cninfo.com.cn/finalpage/2025-03-30/a.pdf"
PDF_B = "https://static.cninfo.com.cn/finalpage/2025-04-02/b.pdf"


def _notice(
    *,
    published: str = "2025-03-30",
    url: str = PDF_A,
    code: str = "n1",
    period: str = "2024FY",
    version: str = "original",
    symbol: str = "sh600519",
) -> dict[str, str]:
    return {
        "symbol": symbol,
        "noticeCode": code,
        "reportKind": "annual",
        "reportPeriod": period,
        "versionType": version,
        "publishedDate": published,
        "title": "贵州茅台2024年年度报告",
        "url": url,
        "source": SOURCE,
    }


def _notice_payload(items, *, status="available", warnings=None):
    return {
        "status": status,
        "source": SOURCE,
        "fetchedAt": FETCHED_AT,
        "items": list(items),
        "warnings": list(warnings or []),
    }


def _pdf_result(url: str, *, text: str = "主要会计数据"):
    excerpt = text
    digest = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
    return {
        "documentSha256": hashlib.sha256(("pdf:" + url).encode()).hexdigest(),
        "pageCount": 1,
        "byteSize": 100,
        "pages": [{"page": 1, "excerpt": excerpt, "excerptSha256": digest}],
        "coverageStatus": "available",
        "warnings": [],
        "fetchedAt": FETCHED_AT,
        "numericValidation": "not_performed",
    }


def _freeze(
    items,
    *,
    symbols=("sh600519",),
    dates=("2025-04-03",),
    pdf_loader=None,
    notice_status="available",
    notice_warnings=None,
):
    return frozen.freeze_financial_report_snapshot(
        symbols,
        dates,
        notice_loader=lambda _symbol, *, cutoff: _notice_payload(
            items, status=notice_status, warnings=notice_warnings
        ),
        pdf_loader=pdf_loader or (lambda url, **_kwargs: _pdf_result(url)),
        now_provider=lambda: datetime(2025, 11, 4, tzinfo=timezone.utc),
    )


def test_freeze_uses_day_before_latest_decision_and_excludes_same_day_notices():
    calls = []
    items = [
        _notice(published="2025-04-01", url=PDF_A, code="n1"),
        _notice(published="2025-04-02", url=PDF_B, code="n2", period="2025Q1"),
        _notice(
            published="2025-04-03",
            url="https://static.cninfo.com.cn/finalpage/2025-04-03/c.pdf",
            code="n3",
            period="2025Q1",
        ),
    ]

    def notice_loader(symbol, *, cutoff):
        calls.append((symbol, cutoff))
        return _notice_payload(items)

    snapshot = frozen.freeze_financial_report_snapshot(
        ["sh600519"],
        ["2025-04-01", "2025-04-03", "2025-04-04"],
        notice_loader=notice_loader,
        pdf_loader=lambda url, **_kwargs: _pdf_result(url),
        now_provider=lambda: datetime(2025, 11, 4, tzinfo=timezone.utc),
    )

    assert calls == [("sh600519", date(2025, 4, 3))]
    groups = {group["decisionDate"]: group for group in snapshot["groups"]}
    assert groups["2025-04-01"]["items"] == []
    assert groups["2025-04-01"]["coverageStatus"] == "partial"
    assert {item["publishedDate"] for item in groups["2025-04-03"]["items"]} == {
        "2025-04-01",
        "2025-04-02",
    }
    assert groups["2025-04-03"]["coverageStatus"] == "available"
    assert groups["2025-04-04"]["coverageStatus"] == "available"
    assert "2025-04-03" in {
        item["publishedDate"] for item in groups["2025-04-04"]["items"]
    }
    assert all(
        item["publishedDate"] < group["decisionDate"]
        for group in snapshot["groups"]
        for item in group["items"]
    )


@pytest.mark.parametrize(("code", "org_id"), [("002656", "9900022094"), ("300750", "GD165627")])
def test_modern_issuer_ids_reach_historical_pdf_directory_without_future_notices(monkeypatch, code, org_id):
    calls = []

    def provider(path, fields):
        calls.append((path, dict(fields)))
        if path.endswith("topSearch/query"):
            return [{"code": code, "category": "A股", "orgId": org_id, "delisted": "false"}]
        return {"hasMore": False, "announcements": [
            {"secCode": code, "announcementId": str(index), "announcementTitle": "2024年年度报告",
             "adjunctUrl": f"finalpage/{day}/{index}.pdf",
             "announcementTime": int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)}
            for index, day in enumerate(["2025-03-30", "2026-01-01"])
        ]}

    monkeypatch.setattr(official_pdf.official_filings, "_post_json", provider)
    result = official_pdf.load_periodic_report_notices("sz" + code, cutoff=date(2025, 12, 31))
    assert result["status"] == "available"
    assert len(result["items"]) == 1 and result["items"][0]["publishedDate"] == "2025-03-30"
    assert calls[1][1]["stock"] == f"{code},{org_id}"
    assert calls[1][1]["column"] == "szse"
    assert calls[1][1]["seDate"].endswith("2025-12-31")


def test_revision_candidates_are_retained_with_uncertainty_warning():
    items = [
        _notice(published="2025-03-30", url=PDF_A, code="original"),
        _notice(
            published="2025-04-01",
            url=PDF_B,
            code="revision",
            version="revision_notice",
        ),
    ]
    snapshot = _freeze(items)
    group = snapshot["groups"][0]

    assert [item["versionType"] for item in group["items"]] == [
        "revision_notice",
        "original",
    ]
    assert group["coverageStatus"] == "partial"
    assert any("修订/更正候选" in warning for warning in group["warnings"])


def test_snapshot_restores_entirely_offline_and_projects_frozen_pages(monkeypatch):
    snapshot = _freeze([_notice()])

    def no_network(*_args, **_kwargs):
        raise AssertionError("offline restore attempted a source request")

    monkeypatch.setattr(official_pdf, "load_periodic_report_notices", no_network)
    monkeypatch.setattr(official_pdf, "fetch_and_extract_official_pdf", no_network)
    restored = frozen.validate_research_snapshot(
        snapshot, expected_hash=snapshot["researchHash"]
    )
    material = frozen.decision_research_material(
        restored, symbols=["sh600519"], decision_date="2025-04-03"
    )

    assert material["status"] == "available"
    assert material["groups"][0]["items"][0]["pages"][0]["excerpt"] == "主要会计数据"
    assert material["groups"][0]["items"][0]["trust"] == "untrusted_official_pdf_text"


def test_excerpt_digest_is_checked_even_if_outer_snapshot_hash_is_recomputed():
    snapshot = _freeze([_notice()])
    tampered = copy.deepcopy(snapshot)
    tampered["documents"][0]["pages"][0]["excerpt"] = "已篡改"
    tampered["researchHash"] = sha256_json(
        {key: value for key, value in tampered.items() if key != "researchHash"}
    )

    with pytest.raises(BacktestInputError, match="页摘录摘要"):
        frozen.validate_research_snapshot(tampered)


def test_cninfo_url_guard_and_redirect_guard_fail_closed():
    assert not official_pdf.validate_official_pdf_url(
        "https://127.0.0.1/finalpage/2025-01-01/a.pdf"
    )
    assert not official_pdf.validate_official_pdf_url(
        "https://static.cninfo.com.cn/finalpage/2025-01-01/a.pdf?next=1"
    )
    handler = official_pdf._OfficialPdfRedirectHandler(official_pdf.MAX_REDIRECTS)
    with pytest.raises(HTTPError, match="redirect rejected"):
        handler.redirect_request(
            Request(PDF_A),
            io.BytesIO(),
            302,
            "Found",
            {},
            "http://127.0.0.1/private.pdf",
        )


def test_download_enforces_byte_limit_and_converts_timeout_to_source_error():
    class Response:
        def __init__(self, body):
            self.body = body
            self.headers = {}
            self.read_limit = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return PDF_A

        def read(self, limit):
            self.read_limit = limit
            return self.body[:limit]

    class Opener:
        def __init__(self, response=None, error=None):
            self.response = response
            self.error = error
            self.timeout = None

        def open(self, _request, *, timeout):
            self.timeout = timeout
            if self.error:
                raise self.error
            return self.response

    response = Response(b"%PDF-" + b"x" * 20)
    opener = Opener(response)
    with pytest.raises(official_pdf.OfficialPdfError, match="超过安全读取上限"):
        official_pdf.download_official_pdf(PDF_A, max_bytes=10, opener=opener)
    assert response.read_limit == 11
    assert opener.timeout == official_pdf.DEFAULT_TIMEOUT_SECONDS

    with pytest.raises(official_pdf.OfficialPdfError, match="暂时无法读取"):
        official_pdf.download_official_pdf(PDF_A, opener=Opener(error=TimeoutError()))


def test_extraction_caps_pages_and_total_excerpt_text(monkeypatch):
    import pypdf

    class Page:
        def extract_text(self):
            return "合并资产负债表" + ("甲" * 5_000)

    class Reader:
        is_encrypted = False

        def __init__(self, *_args, **_kwargs):
            self.pages = [Page() for _ in range(official_pdf.MAX_PDF_PAGES + 1)]

    monkeypatch.setattr(pypdf, "PdfReader", Reader)
    result = official_pdf.extract_official_pdf_pages(b"%PDF-test")

    assert result["pageCount"] == official_pdf.MAX_PDF_PAGES + 1
    assert len(result["pages"]) <= official_pdf.MAX_EXCERPT_PAGES
    assert (
        sum(len(page["excerpt"]) for page in result["pages"])
        <= official_pdf.MAX_DOCUMENT_EXCERPT_CHARS
    )
    assert any("页数超过解析上限" in warning for warning in result["warnings"])
    assert any("单页摘录达到字符上限" in warning for warning in result["warnings"])


def test_aggregate_pdf_byte_budget_is_enforced_against_loader_result(monkeypatch):
    monkeypatch.setattr(frozen, "_MAX_TOTAL_PDF_BYTES", 10)
    first = _notice(url=PDF_A, code="n1", period="2024FY")
    second = _notice(
        published="2025-04-01",
        url=PDF_B,
        code="n2",
        period="2025Q1",
    )
    budgets = []

    def pdf_loader(url, *, max_bytes, **_kwargs):
        budgets.append(max_bytes)
        result = _pdf_result(url)
        result["byteSize"] = 7 if len(budgets) == 1 else 4
        return result

    snapshot = _freeze([first, second], pdf_loader=pdf_loader)

    assert budgets == [10, 3]
    assert sum(document["byteSize"] for document in snapshot["documents"]) <= 10
    assert snapshot["groups"][0]["coverageStatus"] == "partial"


def test_all_notice_sources_failed_does_not_masquerade_as_empty_success():
    with pytest.raises(BacktestInputError, match="全部失败"):
        frozen.freeze_financial_report_snapshot(
            ["sh600519"],
            ["2025-04-03"],
            notice_loader=lambda *_args, **_kwargs: {
                "status": "failed",
                "source": SOURCE,
                "fetchedAt": FETCHED_AT,
                "items": [],
                "warnings": ["模拟来源失败"],
            },
        )


def test_bse_transition_keeps_exact_historical_code_and_warns_across_boundary():
    legacy_notice = _notice(
        published="2025-03-30",
        url=PDF_A,
        code="old-code-report",
        symbol="bj835185",
    )
    before = _freeze(
        [legacy_notice],
        symbols=("bj835185",),
        dates=("2025-10-09",),
    )
    after = _freeze(
        [legacy_notice],
        symbols=("bj835185",),
        dates=("2025-10-10",),
    )

    assert before["groups"][0]["coverageStatus"] == "available"
    assert after["groups"][0]["coverageStatus"] == "partial"
    assert any("2025-10-09" in warning for warning in after["groups"][0]["warnings"])


def test_920_code_warns_for_unmapped_legacy_reports_and_never_aliases_old_sec_code():
    snapshot = _freeze(
        [
            _notice(
                published="2025-03-30",
                url=PDF_A,
                code="current-code-report",
                symbol="bj920185",
            )
        ],
        symbols=("bj920185",),
        dates=("2025-11-03",),
    )
    row = {
        "secCode": "835185",
        "announcementTime": int(
            datetime(2025, 3, 30, tzinfo=timezone.utc).timestamp() * 1000
        ),
        "adjunctUrl": "finalpage/2025-03-30/a.pdf",
        "announcementTitle": "贝特瑞2024年年度报告",
        "announcementId": "legacy-report",
    }

    assert snapshot["groups"][0]["coverageStatus"] == "partial"
    assert any(
        "未建立官方映射" in warning for warning in snapshot["groups"][0]["warnings"]
    )
    assert (
        official_pdf._notice_from_row(
            row,
            code="920185",
            symbol="bj920185",
            cutoff=date(2025, 11, 2),
        )
        is None
    )


@pytest.mark.parametrize("unreadable", ["download", "scanned_pdf"])
def test_freeze_requires_at_least_one_usable_page_excerpt(unreadable):
    notice = _notice()

    def failed_download(_url, **_kwargs):
        raise official_pdf.OfficialPdfError("download failed")

    def scanned_pdf(_url, **_kwargs):
        result = _pdf_result(_url)
        result.update(
            {"pages": [], "coverageStatus": "partial", "warnings": ["未执行OCR"]}
        )
        return result

    with pytest.raises(BacktestInputError, match="未取得可用的官方财报PDF页摘录"):
        _freeze(
            [notice],
            pdf_loader=failed_download if unreadable == "download" else scanned_pdf,
        )


def test_revision_document_tampering_without_a_valid_page_hash_is_rejected():
    result = _pdf_result(PDF_A)
    result["pages"][0]["excerptSha256"] = "0" * 64
    with pytest.raises(BacktestInputError, match="内容或摘要"):
        frozen._normalize_pdf_result(
            result,
            url=PDF_A,
            default_fetched_at=FETCHED_AT,
        )


def test_page_number_cannot_exceed_declared_or_scanned_page_count():
    excerpt = "资产负债表"
    page = {
        "page": 200,
        "excerpt": excerpt,
        "excerptSha256": hashlib.sha256(excerpt.encode()).hexdigest(),
    }
    result = _pdf_result(PDF_A)
    result["pageCount"] = 2
    result["pages"] = [page]
    with pytest.raises(BacktestInputError, match="内容或摘要"):
        frozen._normalize_pdf_result(
            result,
            url=PDF_A,
            default_fetched_at=FETCHED_AT,
        )

    document_hash = hashlib.sha256(b"original").hexdigest()
    document = {
        "documentId": sha256_json({"url": PDF_A, "documentSha256": document_hash}),
        "url": PDF_A,
        "documentSha256": document_hash,
        "pageCount": 2,
        "byteSize": 100,
        "pages": [page],
        "coverageStatus": "available",
        "warnings": [],
        "fetchedAt": FETCHED_AT,
        "numericValidation": "not_performed",
    }
    with pytest.raises(BacktestInputError, match="摘要或页码"):
        report_contract._validate_document(document)
