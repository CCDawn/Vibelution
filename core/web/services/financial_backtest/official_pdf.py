"""Bounded acquisition and page-text extraction for official A-share reports.

CNINFO's existing query helpers remain the metadata authority. This module
retains periodic-report revisions instead of applying the title filter used by
summary/reprint lookups, and never interprets extracted figures as verified
financial values.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from core.infrastructure.url_guard import validate_public_http_url
from core.web.services import financial_market_service as market
from core.web.services.financial_research import official_filings
from core.web.services.team_workflow.source_collection.local_parsing import (
    normalize_text_safety,
    scan_prompt_injection,
)

SOURCE = official_filings.FILING_SOURCE
DEFAULT_TIMEOUT_SECONDS = 6.0
MAX_REDIRECTS = 3
MAX_PDF_BYTES = 20_000_000
MAX_PDF_PAGES = 240
MAX_EXCERPT_PAGES = 8
MAX_PAGE_EXCERPT_CHARS = 4_000
MAX_DOCUMENT_EXCERPT_CHARS = 22_000
MAX_NOTICE_PAGES = official_filings.MAX_ANNOUNCEMENT_PAGES
MAX_NOTICES_PER_PAGE = official_filings.ANNOUNCEMENT_PAGE_SIZE

_REVISION_MARKERS = ("更正", "修订", "補充", "补充", "勘误", "修改", "更新")
_SUMMARY_MARKERS = ("摘要", "英文")
_REPORT_PERIOD_RE = re.compile(r"(?<!\d)(20\d{2})年")
_REPORT_PATTERNS = (
    ("semiannual", re.compile(r"半年度报告"), "H1"),
    ("q1", re.compile(r"(?:第一|第1|一)季度报告"), "Q1"),
    ("q3", re.compile(r"(?:第三|第3|三)季度报告"), "Q3"),
    ("annual", re.compile(r"年度报告"), "FY"),
)
_STATEMENT_MARKERS = (
    ("主要会计数据", 0),
    ("主要财务指标", 0),
    ("合并资产负债表", 1),
    ("资产负债表", 2),
    ("合并利润表", 1),
    ("利润表", 2),
    ("合并现金流量表", 1),
    ("现金流量表", 2),
    ("审计报告", 3),
    ("财务报表", 4),
)


class OfficialPdfError(ValueError):
    """An official PDF request or parse failed closed."""


def classify_report_title(title: object) -> dict[str, str] | None:
    """Map a periodic-report title to its period without dropping revisions."""

    if not isinstance(title, str):
        return None
    compact = re.sub(r"\s+", "", re.sub(r"<[^>]{0,80}>", "", title))
    if not compact or any(marker in compact for marker in _SUMMARY_MARKERS):
        return None
    match = _REPORT_PERIOD_RE.search(compact)
    if not match:
        return None
    year = match.group(1)
    for kind, pattern, suffix in _REPORT_PATTERNS:
        if pattern.search(compact):
            revision = any(marker in compact for marker in _REVISION_MARKERS)
            return {
                "reportKind": kind,
                "reportPeriod": year + suffix,
                "versionType": "revision_notice" if revision else "original",
            }
    return None


def load_periodic_report_notices(symbol: str, *, cutoff: date) -> dict[str, Any]:
    """Read bounded raw periodic-category announcements for one A-share.

    `cutoff` is inclusive here; the snapshot owner passes decision_date - 1 day
    so decision-day notices are excluded even though CNINFO exposes only days.
    Rows with a correction/revision marker are retained as candidates. Rows
    that cannot be mapped to a report period remain visible as warning notices.
    """

    try:
        canonical = market.normalize_a_share_symbol(symbol)
    except (market.MarketDataError, TypeError, ValueError) as exc:
        raise OfficialPdfError("A股标的无效") from exc
    if not isinstance(cutoff, date) or isinstance(cutoff, datetime):
        raise OfficialPdfError("公告截止日期无效")
    code = canonical[-6:]
    fetched_at = _utc_now()
    try:
        searched = official_filings._post_json(
            "/new/information/topSearch/query", {"keyWord": code}
        )
        located = official_filings._org_and_column(searched, code)
        if located is None:
            return _notice_result(
                "failed", fetched_at, [], ["未取得该A股的巨潮资讯公告目录。"]
            )
        org_id, column = located
        notices: list[dict[str, Any]] = []
        warnings: list[str] = []
        has_more = False
        for page_num in range(1, MAX_NOTICE_PAGES + 1):
            fields = official_filings._announcement_fields(
                code,
                org_id,
                column,
                cutoff,
                official_filings._SCREEN_CATEGORY,
                page_num=page_num,
            )
            payload = official_filings._post_json("/new/hisAnnouncement/query", fields)
            rows = payload.get("announcements") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                warnings.append("巨潮资讯公告分页结构无效。")
                return _notice_result(
                    "partial" if notices else "failed", fetched_at, notices, warnings
                )
            if not rows:
                has_more = False
                break
            for row in rows:
                notice = _notice_from_row(
                    row, code=code, symbol=canonical, cutoff=cutoff
                )
                if notice is not None:
                    notices.append(notice)
            has_more = official_filings._has_more_announcement_pages(payload)
            if not has_more:
                break
        if has_more:
            warnings.append("巨潮资讯公告分页达到读取上限，历史报告覆盖不完整。")
        status = "partial" if warnings else "available"
        return _notice_result(status, fetched_at, notices, warnings)
    except Exception:  # noqa: BLE001 - public source errors become coverage state
        warnings = ["巨潮资讯公告读取失败。"]
        return _notice_result(
            "partial" if "notices" in locals() and notices else "failed",
            fetched_at,
            notices if "notices" in locals() else [],
            warnings,
        )


def _notice_from_row(
    row: object, *, code: str, symbol: str, cutoff: date
) -> dict[str, Any] | None:
    if not isinstance(row, dict) or str(row.get("secCode") or "").strip() != code:
        return None
    announced = official_filings._epoch_day(row.get("announcementTime"))
    if announced is None or announced > cutoff:
        return None
    url = official_filings._document_url(row.get("adjunctUrl"))
    if not url:
        return None
    raw_title = row.get("announcementTitle")
    if not isinstance(raw_title, str):
        return None
    title = re.sub(r"<[^>]{0,80}>", "", raw_title)
    title = re.sub(r"[\r\n\t]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    if not title or len(title) > 240 or any(ord(char) < 32 for char in title):
        return None
    classification = classify_report_title(title)
    has_revision = any(marker in title for marker in _REVISION_MARKERS)
    if classification is None and not has_revision:
        return None
    if classification is None:
        classification = {
            "reportKind": "unknown",
            "reportPeriod": "",
            "versionType": "unmapped_revision_notice",
        }
    notice_code = str(row.get("announcementId") or "").strip()
    if not notice_code:
        notice_code = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    if len(notice_code) > 96 or any(ord(char) < 32 for char in notice_code):
        notice_code = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return {
        "symbol": symbol,
        "noticeCode": notice_code,
        "reportKind": classification["reportKind"],
        "reportPeriod": classification["reportPeriod"],
        "versionType": classification["versionType"],
        "publishedDate": announced.isoformat(),
        "title": title,
        "url": url,
        "source": SOURCE,
    }


def _notice_result(
    status: str, fetched_at: str, notices: list[dict[str, Any]], warnings: list[str]
) -> dict[str, Any]:
    notices.sort(
        key=lambda row: (
            row["publishedDate"],
            row["reportPeriod"],
            row["noticeCode"],
        ),
        reverse=True,
    )
    return {
        "status": status,
        "source": SOURCE,
        "fetchedAt": fetched_at,
        "items": notices[: MAX_NOTICE_PAGES * MAX_NOTICES_PER_PAGE],
        "warnings": _unique(warnings),
    }


def validate_official_pdf_url(value: object) -> str:
    """Return a strictly allowlisted official PDF URL, or an empty string."""

    text = str(value or "").strip()
    if not text or official_filings._allowed_document_url(text) != text:
        return ""
    if validate_public_http_url(text):
        return ""
    parsed = urlsplit(text)
    if parsed.query or parsed.fragment or not parsed.path.lower().endswith(".pdf"):
        return ""
    return text


class _OfficialPdfRedirectHandler(HTTPRedirectHandler):
    """Limit redirects and validate every target before urllib opens it."""

    def __init__(self, max_redirects: int) -> None:
        super().__init__()
        self._max_redirects = max_redirects
        self._redirects = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, str(newurl))
        if self._redirects >= self._max_redirects or not validate_official_pdf_url(
            target
        ):
            raise HTTPError(
                target,
                code,
                "official PDF redirect rejected",
                headers,
                fp,
            )
        self._redirects += 1
        return super().redirect_request(req, fp, code, msg, headers, target)


def download_official_pdf(
    url: str,
    *,
    max_bytes: int = MAX_PDF_BYTES,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    opener=None,
) -> bytes:
    """Fetch one allowlisted PDF with bounded redirects, time, and bytes."""

    safe_url = validate_official_pdf_url(url)
    if not safe_url:
        raise OfficialPdfError("财报PDF来源地址不在官方白名单内")
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_PDF_BYTES:
        raise OfficialPdfError("财报PDF下载上限无效")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0.1 <= timeout <= 30
    ):
        raise OfficialPdfError("财报PDF请求超时设置无效")
    if opener is None:
        opener = build_opener(_OfficialPdfRedirectHandler(MAX_REDIRECTS))
    request = Request(
        safe_url,
        headers={
            "Accept": "application/pdf,application/octet-stream;q=0.8",
            "User-Agent": "Vibelution/1 financial-backtest",
        },
        method="GET",
    )
    try:
        with opener.open(request, timeout=float(timeout)) as response:
            final_url = validate_official_pdf_url(response.geturl())
            if not final_url:
                raise OfficialPdfError("财报PDF最终地址不在官方白名单内")
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                text_length = str(content_length).strip()
                if not text_length.isdigit() or int(text_length) > max_bytes:
                    raise OfficialPdfError("财报PDF超过安全读取上限")
            body = response.read(max_bytes + 1)
    except OfficialPdfError:
        raise
    except HTTPError as exc:
        exc.close()
        raise OfficialPdfError("财报PDF请求失败或重定向被拒绝") from None
    except (OSError, URLError, TimeoutError, ValueError) as exc:
        raise OfficialPdfError("财报PDF暂时无法读取") from exc
    if len(body) > max_bytes:
        raise OfficialPdfError("财报PDF超过安全读取上限")
    if not _looks_like_pdf(body):
        raise OfficialPdfError("官方文档响应不是可识别的PDF")
    return body


def fetch_and_extract_official_pdf(
    url: str,
    *,
    max_bytes: int = MAX_PDF_BYTES,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Download one original and return bounded page-level text evidence."""

    pdf_bytes = download_official_pdf(url, max_bytes=max_bytes, timeout=timeout)
    return extract_official_pdf_pages(pdf_bytes)


def extract_official_pdf_pages(pdf_bytes: bytes) -> dict[str, Any]:
    """Hash and extract selected financial-report pages without value validation."""

    if (
        not isinstance(pdf_bytes, bytes)
        or not pdf_bytes
        or len(pdf_bytes) > MAX_PDF_BYTES
    ):
        raise OfficialPdfError("财报PDF字节数无效")
    if not _looks_like_pdf(pdf_bytes):
        raise OfficialPdfError("财报原件不是可识别的PDF")
    document_hash = hashlib.sha256(pdf_bytes).hexdigest()
    warnings: list[str] = []
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(pdf_bytes), strict=False)
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    return _partial_pdf_result(
                        document_hash,
                        0,
                        len(pdf_bytes),
                        ["财报PDF加密，无法提取页文本。"],
                    )
            except Exception:  # noqa: BLE001 - encrypted/unsupported files become partial evidence
                return _partial_pdf_result(
                    document_hash, 0, len(pdf_bytes), ["财报PDF加密，无法提取页文本。"]
                )
        page_count = len(reader.pages)
    except Exception:  # noqa: BLE001 - pypdf has multiple parse exception types
        return _partial_pdf_result(
            document_hash, 0, len(pdf_bytes), ["财报PDF解析失败，原件哈希已保留。"]
        )

    scan_count = min(page_count, MAX_PDF_PAGES)
    if page_count > MAX_PDF_PAGES:
        warnings.append("财报PDF页数超过解析上限，后续页面未扫描。")
    extracted: list[tuple[int, str]] = []
    for page_number in range(1, scan_count + 1):
        try:
            raw_text = str(reader.pages[page_number - 1].extract_text() or "")
        except Exception:  # noqa: BLE001 - preserve other readable pages
            warnings.append("部分财报PDF页面提取失败。")
            continue
        if not raw_text.strip():
            continue
        if len(raw_text) > MAX_PAGE_EXCERPT_CHARS * 3:
            warnings.append("财报PDF单页提取文本超过扫描预算，页面内容已截断。")
        bounded_raw_text = raw_text[: MAX_PAGE_EXCERPT_CHARS * 3]
        normalized, safety_warnings = normalize_text_safety(bounded_raw_text)
        if safety_warnings:
            warnings.append("财报PDF中的不可见或控制字符已清理。")
        if scan_prompt_injection(normalized):
            warnings.append("财报PDF含有可疑指令文本；内容仍按非可信来源处理。")
        if len(normalized.strip()) > MAX_PAGE_EXCERPT_CHARS:
            warnings.append("财报PDF单页摘录达到字符上限，页面内容已截断。")
        text = normalized.strip()[:MAX_PAGE_EXCERPT_CHARS]
        if text:
            extracted.append((page_number, text))

    selected_pages = _select_statement_pages(extracted)
    if not selected_pages:
        if extracted:
            selected_pages = extracted[:1]
            warnings.append("未识别到财务报表或主要指标页，仅保留首页文本摘录。")
        else:
            warnings.append("财报PDF没有可提取的文本页面，未执行OCR。")
    selected_pages = selected_pages[:MAX_EXCERPT_PAGES]
    pages: list[dict[str, Any]] = []
    total_chars = 0
    for page_number, full_text in selected_pages:
        remaining = MAX_DOCUMENT_EXCERPT_CHARS - total_chars
        if remaining <= 0:
            warnings.append("财报页文本达到单文档字符上限，后续摘录未纳入。")
            break
        excerpt = full_text[: min(MAX_PAGE_EXCERPT_CHARS, remaining)]
        if len(excerpt) < len(full_text):
            warnings.append("财报页文本达到单页或单文档字符上限，摘录已截断。")
        digest = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
        pages.append({"page": page_number, "excerpt": excerpt, "excerptSha256": digest})
        total_chars += len(excerpt)
    return {
        "documentSha256": document_hash,
        "pageCount": page_count,
        "byteSize": len(pdf_bytes),
        "pages": pages,
        "coverageStatus": "partial" if warnings or not pages else "available",
        "warnings": _unique(warnings),
        "numericValidation": "not_performed",
    }


def _select_statement_pages(extracted: list[tuple[int, str]]) -> list[tuple[int, str]]:
    ranked: list[tuple[int, int, str]] = []
    for page_number, text in extracted:
        compact = re.sub(r"\s+", "", text)
        matches = [
            priority for marker, priority in _STATEMENT_MARKERS if marker in compact
        ]
        if matches:
            ranked.append((min(matches), page_number, text))
    if not ranked:
        return []
    ranked.sort(key=lambda row: (row[0], row[1]))
    selected: dict[int, str] = {}
    for _priority, page_number, text in ranked:
        selected.setdefault(page_number, text)
        # The following page can carry continued rows of a financial table.
        next_page = next(
            (candidate for candidate in extracted if candidate[0] == page_number + 1),
            None,
        )
        if next_page is not None:
            selected.setdefault(next_page[0], next_page[1])
        if len(selected) >= MAX_EXCERPT_PAGES:
            break
    return sorted(selected.items())


def _partial_pdf_result(
    document_hash: str, page_count: int, byte_size: int, warnings: list[str]
) -> dict[str, Any]:
    return {
        "documentSha256": document_hash,
        "pageCount": page_count,
        "byteSize": byte_size,
        "pages": [],
        "coverageStatus": "partial",
        "warnings": _unique(warnings),
        "numericValidation": "not_performed",
    }


def _looks_like_pdf(value: bytes) -> bool:
    return isinstance(value, bytes) and b"%PDF-" in value[:1024]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _unique(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text[:300])
    return result
