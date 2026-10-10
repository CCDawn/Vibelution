"""Freeze official CNINFO A-share cash-dividend implementation notices.

The result is a deterministic input artifact for historical backtests. Notice
searches are bounded and must reach an explicitly declared final page. PDFs are
downloaded only from the existing official-host allowlist and every page is
scanned before an event is accepted. Unsupported share distributions,
corrections, conflicting notices, and truncated evidence fail closed.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

from core.web.services import financial_market_service as market
from core.web.services.financial_backtest import official_pdf
from core.web.services.financial_research import official_filings

SOURCE = "cninfo"
FILING_SOURCE = official_filings.FILING_SOURCE
ARTIFACT_SCHEMA_VERSION = 1
ACTION_RULE_VERSION = "ashare_cash_dividend_v1"
MAX_ACTION_QUERY_PAGES = 20
MAX_ACTION_PDF_BYTES = official_pdf.MAX_PDF_BYTES
MAX_ACTION_PDF_PAGES = 30
MAX_PAGE_TEXT_CHARS = 60_000
MAX_DOCUMENT_TEXT_CHARS = 600_000
MAX_EVIDENCE_PAGES = 8
MAX_EVIDENCE_EXCERPT_CHARS = 4_000
_HTML_TAG = re.compile(r"<[^>]{0,160}>")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_NOTICE_ID = re.compile(r"^[0-9]{1,32}$")
_NUMBER = r"(?:\d{1,12}(?:\.\d{1,8})?)"
_CASH_PATTERNS = (
    re.compile(rf"(?:[AＡ]股)?每股(?:派发)?现金红利(?:人民币)?(?P<amount>{_NUMBER})元"),
    re.compile(rf"每股派发现金股利(?:人民币)?(?P<amount>{_NUMBER})元"),
    re.compile(
        rf"每(?P<shares>\d{{1,5}})股(?:派发|派|支付)现金(?:红利|股利)(?:人民币)?(?P<amount>{_NUMBER})元"
    ),
)
_STOCK_DISTRIBUTION = re.compile(
    rf"每(?P<base>\d{{1,5}})?股(?P<kind>送红股|送股|转增)(?P<amount>{_NUMBER})股"
)
_DATE = re.compile(r"(?P<year>20\d{2})[年/.-](?P<month>\d{1,2})[月/.-](?P<day>\d{1,2})日?")
_DATE_LABELS = {
    "recordDate": re.compile(r"股权登记日"),
    "exDate": re.compile(r"(?:除权(?:[（(]?息[）)]?|除息)?|除息)日"),
    "paymentDate": re.compile(r"(?:现金)?红利发放日"),
}
_REVISION_MARKERS = ("更正", "修订", "补充", "補充", "勘误", "修改", "调整", "延期", "取消", "终止")
_DIVIDEND_TITLE_MARKERS = (
    "分红",
    "派息",
    "权益分派",
    "权益分配",
    "现金红利",
    "利润分配",
    "股利分配",
    "股利",
    "送股",
    "送转",
    "转增",
    "配股",
)
_PROPOSAL_MARKERS = (
    "预案",
    "方案公告",
    "方案说明",
    "利润分配方案",
    "权益分派方案",
    "权益分配方案",
    "股东大会决议",
    "分红回报规划",
    "现金分红规划",
)
_ANCILLARY_SUPPORT_MARKERS = (
    "法律意见书",
    "独立董事意见",
    "董事会决议",
    "监事会决议",
    "回购股份价格上限",
)


class OfficialDividendError(ValueError):
    """An official dividend artifact could not be completed safely."""


def load_cash_dividend_artifact(
    symbol: str, *, start_date: str, end_date: str
) -> dict[str, Any]:
    """Return a complete, hash-ready draft of official cash-dividend events.

    CNINFO publication-date searches cover the two calendar years preceding
    ``start_date`` through ``end_date``. An incomplete query or an event that
    cannot be resolved from its full implementation PDF raises a backtest data
    error; callers must not substitute an empty action list.
    """

    start = _parse_iso_day(start_date, "回测开始日期")
    end = _parse_iso_day(end_date, "回测结束日期")
    if start > end:
        _raise_backtest_input_error("公司行动覆盖日期顺序无效")
    try:
        canonical_symbol = market.normalize_a_share_symbol(symbol)
    except (market.MarketDataError, TypeError, ValueError) as exc:
        _raise_backtest_input_error("公司行动标的不是有效A股代码", cause=exc)

    query_start = _subtract_calendar_years(start, 2)
    code = canonical_symbol[-6:]
    try:
        identity = official_filings._post_json(
            "/new/information/topSearch/query", {"keyWord": code}
        )
        located = _issuer_identity(identity, code)
        if located is None:
            _raise_backtest_data_error("巨潮资讯未返回唯一的A股发行人身份")
        org_id, column = located
        rows, pages_read, terminal = _query_all_announcements(
            code=code,
            org_id=org_id,
            column=column,
            query_start=query_start,
            query_end=end,
        )
        notices: dict[str, dict[str, Any]] = {}
        notice_ids: set[str] = set()
        for row in rows:
            notice = _normalize_notice(row, code=code, symbol=canonical_symbol)
            notice_ids.add(notice["noticeId"])
            prior = notices.get(notice["noticeId"])
            if prior is not None and prior != notice:
                _raise_backtest_data_error("同一公告编号返回了冲突的公告信息")
            notices[notice["noticeId"]] = notice

        events: list[dict[str, Any]] = []
        actions_by_ex_date: dict[str, dict[str, Any]] = {}
        implementation_candidates: dict[str, dict[str, Any]] = {}
        revision_notices: list[dict[str, Any]] = []
        for notice in sorted(
            notices.values(), key=lambda item: (item["publishedDate"], item["noticeId"])
        ):
            if not _is_dividend_notice(notice["title"]):
                continue
            if _is_proposal_title(notice["title"]):
                continue
            if _is_ancillary_support_title(notice["title"]):
                continue
            if _is_revision_title(notice["title"]):
                revision_notices.append(notice)
                continue
            if not _is_implementation_title(notice["title"]):
                raise OfficialDividendError(
                    _notice_error_text("无法确认公告是否为已实施公司行动", notice)
                )

            try:
                document = _validated_notice_document(
                    notice, expected_symbol=canonical_symbol
                )
                record_day, ex_day = _parse_implementation_dates(document)
            except OfficialDividendError as exc:
                raise OfficialDividendError(
                    _notice_error_text("实施公告日期无法完整解析", notice)
                ) from exc
            implementation_candidates[notice["noticeId"]] = {
                "notice": notice,
                "recordDate": record_day,
                "exDate": ex_day,
            }
            if not _dates_intersect_window(record_day, ex_day, start, end):
                continue
            if "配股" in notice["title"]:
                raise OfficialDividendError(
                    _notice_error_text("回测期间存在配股实施公告，当前公司行动账本不支持配股", notice)
                )
            try:
                event = _parse_cash_dividend_document(document)
            except OfficialDividendError as exc:
                raise OfficialDividendError(
                    _notice_error_text("回测期间的分红实施公告无法完整核算", notice)
                ) from exc
            if event["stockDividendRatio"] != "0" or event["capitalizationRatio"] != "0":
                raise OfficialDividendError(
                    _notice_error_text("回测期间含送股或转增股份，当前公司行动账本不支持", notice)
                )
            prior = actions_by_ex_date.get(event["exDate"])
            if prior is not None:
                raise OfficialDividendError(
                    _notice_error_text("同一除权日存在多个实施公告，无法唯一确认公司行动", notice)
                )
            actions_by_ex_date[event["exDate"]] = event
            events.append(event)

        for notice in revision_notices:
            linked = _find_revision_implementation(notice, implementation_candidates)
            if linked is None:
                raise OfficialDividendError(
                    _notice_error_text("更正、延期或调整公告无法关联唯一的原实施公告", notice)
                )
            original_record = linked["recordDate"]
            original_ex = linked["exDate"]
            if _dates_intersect_window(original_record, original_ex, start, end):
                raise OfficialDividendError(
                    _notice_error_text("关联的原实施公告涉及当前回测窗口，修订后的公司行动无法确认", notice)
                )
            if any(marker in notice["title"] for marker in ("取消", "終止", "终止")):
                continue
            try:
                revised_record_dates, revised_ex_dates = _parse_revision_schedule_dates(
                    notice, expected_symbol=canonical_symbol
                )
            except OfficialDividendError as exc:
                raise OfficialDividendError(
                    _notice_error_text("修订公告未提供可核验的登记日和除权日，无法证明与当前窗口无关", notice)
                ) from exc
            if any(start <= value <= end for value in revised_record_dates | revised_ex_dates):
                raise OfficialDividendError(
                    _notice_error_text("修订公告涉及当前回测窗口，最终公司行动无法确认", notice)
                )

        return {
            "schemaVersion": ARTIFACT_SCHEMA_VERSION,
            "ruleVersion": ACTION_RULE_VERSION,
            "symbol": canonical_symbol,
            "coverageStartDate": start.isoformat(),
            "coverageEndDate": end.isoformat(),
            "coverageStatus": "complete",
            "events": sorted(events, key=lambda item: (item["exDate"], item["noticeId"])),
            "coverageEvidence": {
                "source": SOURCE,
                "queryStartDate": query_start.isoformat(),
                "queryEndDate": end.isoformat(),
                "pagesRead": pages_read,
                "terminalPage": terminal,
                "noticeIds": sorted(notice_ids, key=_notice_id_sort_key),
            },
        }
    except OfficialDividendError as exc:
        _raise_backtest_data_error(str(exc), cause=exc)
    except Exception as exc:  # noqa: BLE001 - source and parser failures are fail-closed
        _raise_backtest_data_error("巨潮资讯公司行动公告读取或解析失败", cause=exc)


def parse_official_cash_dividend_notice(
    notice: Mapping[str, Any],
    *,
    expected_symbol: str,
    pdf_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Parse one full official implementation PDF into the ledger event shape.

    ``pdf_bytes`` is injectable for deterministic tests. Production calls use
    the existing safe downloader and official-host redirect checks.
    """

    if not isinstance(notice, Mapping):
        raise OfficialDividendError("分红公告元数据无效")
    title = _clean_title(notice.get("title"))
    if any(marker in title for marker in _REVISION_MARKERS):
        raise OfficialDividendError("分红实施公告包含更正或修订标记")
    if not _is_implementation_title(title):
        raise OfficialDividendError("公告标题不是明确的分红实施公告")
    document = _validated_notice_document(
        notice, expected_symbol=expected_symbol, pdf_bytes=pdf_bytes
    )
    return _parse_cash_dividend_document(document)


def _validated_notice_document(
    notice: Mapping[str, Any],
    *,
    expected_symbol: str,
    pdf_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Download and validate a complete official notice PDF exactly once."""

    if not isinstance(notice, Mapping):
        raise OfficialDividendError("公司行动公告元数据无效")
    try:
        symbol = market.normalize_a_share_symbol(expected_symbol)
    except (market.MarketDataError, TypeError, ValueError) as exc:
        raise OfficialDividendError("公司行动公告标的无效") from exc
    notice_id = _valid_notice_id(notice.get("noticeId"))
    try:
        published = _parse_iso_day(notice.get("publishedDate"), "公告日期")
    except Exception as exc:
        raise OfficialDividendError("公司行动公告日期无效") from exc
    title = _clean_title(notice.get("title"))
    try:
        source_url = official_pdf.validate_official_pdf_url(notice.get("sourceUrl"))
    except official_pdf.OfficialPdfError as exc:
        raise OfficialDividendError("公司行动公告PDF地址不在官方白名单") from exc
    if not notice_id or not title or not source_url:
        raise OfficialDividendError("公司行动公告缺少有效编号、日期、标题或官方PDF地址")

    if pdf_bytes is None:
        try:
            pdf_bytes = official_pdf.download_official_pdf(
                source_url, max_bytes=MAX_ACTION_PDF_BYTES
            )
        except official_pdf.OfficialPdfError as exc:
            raise OfficialDividendError("官方公司行动PDF无法完整下载") from exc
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes or len(pdf_bytes) > MAX_ACTION_PDF_BYTES:
        raise OfficialDividendError("官方公司行动PDF大小无效")
    if not official_pdf._looks_like_pdf(pdf_bytes):
        raise OfficialDividendError("公告内容不是有效PDF")

    document_hash = hashlib.sha256(pdf_bytes).hexdigest()
    page_texts = _extract_all_pdf_pages(pdf_bytes)
    compact_pages = [_compact_with_positions(text) for text in page_texts]
    all_compact = "".join(compact for compact, _positions in compact_pages)
    if not _pdf_matches_issuer(all_compact, symbol[-6:]):
        raise OfficialDividendError("公司行动PDF未能核对A股证券代码")
    if not _pdf_matches_notice_title(page_texts, title):
        raise OfficialDividendError("公司行动PDF标题与公告目录不一致")

    return {
        "symbol": symbol,
        "noticeId": notice_id,
        "publishedDate": published,
        "sourceUrl": source_url,
        "pdfSha256": document_hash,
        "title": title,
        "pageTexts": page_texts,
        "compactPages": compact_pages,
    }


def _parse_cash_dividend_document(document: Mapping[str, Any]) -> dict[str, Any]:
    symbol = document["symbol"]
    notice_id = document["noticeId"]
    published = document["publishedDate"]
    title = document["title"]
    source_url = document["sourceUrl"]
    document_hash = document["pdfSha256"]
    page_texts = document["pageTexts"]
    compact_pages = document["compactPages"]

    cash, cash_spans = _parse_cash_per_share(compact_pages)
    record_day, record_spans = _parse_labeled_date(compact_pages, "recordDate")
    ex_day, ex_spans = _parse_labeled_date(compact_pages, "exDate")
    payment_day, payment_spans = _parse_labeled_date(compact_pages, "paymentDate")
    if not published <= record_day < ex_day <= payment_day:
        raise OfficialDividendError("分红登记日、除权日与到账日顺序不成立")
    stock_ratio, stock_spans = _parse_share_ratio(compact_pages, kind="送股")
    capitalization_ratio, capital_spans = _parse_share_ratio(compact_pages, kind="转增")
    if _has_unparsed_share_distribution(page_texts, stock_ratio, capitalization_ratio):
        raise OfficialDividendError("分红公告包含无法核算的送股或转增股份")

    relevant_spans: dict[int, list[tuple[int, int]]] = {}
    for span_map in (cash_spans, record_spans, ex_spans, payment_spans, stock_spans, capital_spans):
        for page_number, spans in span_map.items():
            relevant_spans.setdefault(page_number, []).extend(spans)
    identity_page = _page_with_identity(page_texts, symbol[-6:])
    if identity_page is not None:
        compact, _positions = compact_pages[identity_page - 1]
        code_at = compact.find(symbol[-6:])
        if code_at >= 0:
            relevant_spans.setdefault(identity_page, []).append((code_at, code_at + 6))
    evidence_pages = _make_evidence_pages(page_texts, relevant_spans)
    if not evidence_pages:
        raise OfficialDividendError("分红实施公告没有可冻结的页码证据")

    return {
        "actionId": f"{symbol}-{notice_id}-{record_day.isoformat()}-{ex_day.isoformat()}",
        "noticeId": notice_id,
        "symbol": symbol,
        "publishedDate": published.isoformat(),
        "sourceUrl": source_url,
        "pdfSha256": document_hash,
        "title": title,
        "recordDate": record_day.isoformat(),
        "exDate": ex_day.isoformat(),
        "paymentDate": payment_day.isoformat(),
        "cashPerShare": _canonical_decimal(cash),
        "stockDividendRatio": _canonical_decimal(stock_ratio),
        "capitalizationRatio": _canonical_decimal(capitalization_ratio),
        "evidencePages": evidence_pages,
    }


def _parse_implementation_dates(document: Mapping[str, Any]) -> tuple[date, date]:
    compact_pages = document["compactPages"]
    record_day, _record_spans = _parse_labeled_date(compact_pages, "recordDate")
    ex_day, _ex_spans = _parse_labeled_date(compact_pages, "exDate")
    if record_day >= ex_day:
        raise OfficialDividendError("实施公告股权登记日与除权日顺序不成立")
    return record_day, ex_day


def _parse_revision_schedule_dates(
    notice: Mapping[str, Any], *, expected_symbol: str
) -> tuple[set[date], set[date]]:
    document = _validated_notice_document(
        notice, expected_symbol=expected_symbol
    )
    record_dates = {
        value
        for value, _page_number, _span in _parse_labeled_date_candidates(
            document["compactPages"], "recordDate"
        )
    }
    ex_dates = {
        value
        for value, _page_number, _span in _parse_labeled_date_candidates(
            document["compactPages"], "exDate"
        )
    }
    if not record_dates or not ex_dates:
        raise OfficialDividendError("修订公告没有完整的登记日和除权日字段")
    return record_dates, ex_dates


def _query_all_announcements(
    *, code: str, org_id: str, column: str, query_start: date, query_end: date
) -> tuple[list[dict[str, Any]], int, bool]:
    """Read the issuer's complete, bounded notice list for the lookback window."""

    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    expected_total: int | None = None
    pages_read = 0
    reached_end = False
    for page_number in range(1, MAX_ACTION_QUERY_PAGES + 1):
        helper_page = min(page_number, official_filings.MAX_ANNOUNCEMENT_PAGES)
        fields = official_filings._announcement_fields(
            code,
            org_id,
            column,
            query_end,
            official_filings._SCREEN_CATEGORY,
            page_num=helper_page,
        )
        # The shared helper validates issuer identity and the common query
        # contract. One all-category query keeps coverage independent of title
        # vocabulary. This module applies its own hard cap of twenty pages.
        fields["pageNum"] = str(page_number)
        fields["category"] = ""
        fields["searchkey"] = ""
        fields["seDate"] = f"{query_start.isoformat()}~{query_end.isoformat()}"
        payload = official_filings._post_json("/new/hisAnnouncement/query", fields)
        if not isinstance(payload, dict):
            raise OfficialDividendError("巨潮资讯公告分页响应无效")
        page_rows = payload.get("announcements")
        total = _announced_total(payload)
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise OfficialDividendError("巨潮资讯公告总数在分页期间发生变化")
        if page_rows is None and total == 0:
            page_rows = []
        if not isinstance(page_rows, list) or len(page_rows) > official_filings.ANNOUNCEMENT_PAGE_SIZE:
            raise OfficialDividendError("巨潮资讯公告分页列表无效")
        more = _explicit_has_more(payload)
        if more is None:
            raise OfficialDividendError("巨潮资讯未明确公告分页是否结束")
        if official_filings._has_more_announcement_pages(payload) != more:
            raise OfficialDividendError("巨潮资讯公告分页状态无法校验")
        if not page_rows and more:
            raise OfficialDividendError("巨潮资讯空公告页仍标记有后续页面")

        pages_read += 1
        for row in page_rows:
            if not isinstance(row, dict):
                raise OfficialDividendError("巨潮资讯公告记录格式无效")
            notice_id = _valid_notice_id(row.get("announcementId"))
            if not notice_id:
                raise OfficialDividendError("巨潮资讯公告记录缺少稳定编号")
            if notice_id in seen_ids:
                raise OfficialDividendError("巨潮资讯公告分页存在重复编号")
            seen_ids.add(notice_id)
            rows.append(row)
        if not more:
            reached_end = True
            break
        if page_number == MAX_ACTION_QUERY_PAGES:
            raise OfficialDividendError("巨潮资讯公告分页达到上限，覆盖不完整")
    if not reached_end or expected_total is None or len(rows) != expected_total:
        raise OfficialDividendError("巨潮资讯公告分页数量与官方总数不一致")
    return rows, pages_read, reached_end


def _normalize_notice(row: dict[str, Any], *, code: str, symbol: str) -> dict[str, Any]:
    if str(row.get("secCode") or "").strip() != code:
        raise OfficialDividendError("巨潮资讯公告发行人代码与查询标的不一致")
    notice_id = _valid_notice_id(row.get("announcementId"))
    announced = official_filings._epoch_day(row.get("announcementTime"))
    title = _clean_title(row.get("announcementTitle"))
    source_url = official_filings._document_url(row.get("adjunctUrl"))
    if not notice_id or announced is None or not title:
        raise OfficialDividendError("巨潮资讯公告元数据缺少编号、日期或标题")
    return {
        "symbol": symbol,
        "noticeId": notice_id,
        "publishedDate": announced.isoformat(),
        "title": title,
        "sourceUrl": source_url,
    }


def _issuer_identity(payload: object, code: str) -> tuple[str, str] | None:
    return official_filings._org_and_column(payload, code)


def _extract_all_pdf_pages(pdf_bytes: bytes) -> list[str]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(pdf_bytes), strict=False)
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    raise OfficialDividendError("官方分红PDF加密，不能完整解析")
            except OfficialDividendError:
                raise
            except Exception as exc:
                raise OfficialDividendError("官方分红PDF加密，不能完整解析") from exc
        page_count = len(reader.pages)
    except OfficialDividendError:
        raise
    except Exception as exc:
        raise OfficialDividendError("官方分红PDF解析失败") from exc
    if not 1 <= page_count <= MAX_ACTION_PDF_PAGES:
        raise OfficialDividendError("官方分红PDF页数超出完整扫描上限")
    pages: list[str] = []
    total_chars = 0
    for page_number in range(1, page_count + 1):
        try:
            text = str(reader.pages[page_number - 1].extract_text() or "")
        except Exception as exc:
            raise OfficialDividendError(f"官方分红PDF第{page_number}页无法提取文本") from exc
        text = _CONTROL.sub("", text).replace("\u3000", " ").strip()
        if not text:
            raise OfficialDividendError(f"官方分红PDF第{page_number}页无可检索文本")
        if len(text) > MAX_PAGE_TEXT_CHARS:
            raise OfficialDividendError(f"官方分红PDF第{page_number}页超过解析字符上限")
        total_chars += len(text)
        if total_chars > MAX_DOCUMENT_TEXT_CHARS:
            raise OfficialDividendError("官方分红PDF全文超过解析字符上限")
        pages.append(text)
    return pages


def _parse_cash_per_share(
    pages: list[tuple[str, list[int]]],
) -> tuple[Decimal, dict[int, list[tuple[int, int]]]]:
    matches: list[tuple[Decimal, int, tuple[int, int], bool]] = []
    for page_number, (compact, _positions) in enumerate(pages, start=1):
        for pattern in _CASH_PATTERNS:
            for match in pattern.finditer(compact):
                amount = _decimal(match.group("amount"))
                shares_text = match.groupdict().get("shares")
                if shares_text:
                    amount /= Decimal(shares_text)
                a_share_context = re.search(
                    r"[AＡ]股", compact[max(0, match.start() - 50) : match.end()]
                ) is not None
                matches.append((amount, page_number, match.span(), a_share_context))
    if not matches:
        raise OfficialDividendError("分红实施PDF未找到明确的A股每股现金红利")
    a_share_matches = [item for item in matches if item[3]]
    selected = a_share_matches or matches
    amounts = {item[0] for item in selected}
    if len(amounts) != 1 or next(iter(amounts)) <= 0:
        raise OfficialDividendError("分红实施PDF中的A股每股现金红利存在歧义")
    amount = next(iter(amounts))
    spans = _spans_by_page((page, span) for value, page, span, _a_share in selected if value == amount)
    return amount, spans


def _parse_labeled_date(
    pages: list[tuple[str, list[int]]], field: str
) -> tuple[date, dict[int, list[tuple[int, int]]]]:
    found = _parse_labeled_date_candidates(pages, field)
    if not found:
        raise OfficialDividendError(f"分红实施PDF缺少{_field_label(field)}")
    values = {item[0] for item in found}
    if len(values) != 1:
        raise OfficialDividendError(f"分红实施PDF中的{_field_label(field)}存在多个日期")
    value = next(iter(values))
    return value, _spans_by_page((page, span) for item, page, span in found if item == value)


def _parse_labeled_date_candidates(
    pages: list[tuple[str, list[int]]], field: str
) -> list[tuple[date, int, tuple[int, int]]]:
    pattern = _DATE_LABELS[field]
    found: list[tuple[date, int, tuple[int, int]]] = []
    for page_number, (compact, _positions) in enumerate(pages, start=1):
        for value, span in _date_table_values(compact, field):
            found.append((value, page_number, span))
        for label_match in pattern.finditer(compact):
            search_start = label_match.end()
            search_end = min(len(compact), search_start + 48)
            date_match = _DATE.search(compact, search_start, search_end)
            if not date_match:
                continue
            gap = compact[search_start : date_match.start()]
            if re.search(r"[AＡ]股", gap) or any(
                marker in gap for marker in ("最后交易日", "除权", "除息", "发放日")
            ):
                continue
            parsed = _build_date(date_match)
            found.append((parsed, page_number, (label_match.start(), date_match.end())))
    return found


def _date_table_values(
    compact: str, field: str
) -> list[tuple[date, tuple[int, int]]]:
    """Read the common A-share record/ex/payment date table row."""

    fields = ("recordDate", "exDate", "paymentDate")
    field_index = fields.index(field)
    record_pattern = _DATE_LABELS["recordDate"]
    ex_pattern = _DATE_LABELS["exDate"]
    payment_pattern = _DATE_LABELS["paymentDate"]
    results: list[tuple[date, tuple[int, int]]] = []
    for record_match in record_pattern.finditer(compact):
        ex_match = ex_pattern.search(compact, record_match.end(), min(len(compact), record_match.end() + 72))
        if ex_match is None:
            continue
        payment_match = payment_pattern.search(compact, ex_match.end(), min(len(compact), ex_match.end() + 72))
        if payment_match is None:
            continue
        if payment_match.end() - record_match.start() > 150:
            continue
        stock_row = re.search(
            r"[AＡ]股",
            compact[payment_match.end() : min(len(compact), payment_match.end() + 40)],
        )
        if stock_row is None:
            continue
        stock_start = payment_match.end() + stock_row.end()
        dates = list(_DATE.finditer(compact, stock_start, min(len(compact), stock_start + 120)))
        if len(dates) < 3:
            continue
        selected = dates[field_index]
        parsed = _build_date(selected)
        selected_label = (record_match, ex_match, payment_match)[field_index]
        results.append((parsed, (selected_label.start(), selected.end())))
    return results


def _parse_share_ratio(
    pages: list[tuple[str, list[int]]], *, kind: str
) -> tuple[Decimal, dict[int, list[tuple[int, int]]]]:
    matches: list[tuple[Decimal, int, tuple[int, int]]] = []
    for page_number, (compact, _positions) in enumerate(pages, start=1):
        for match in _STOCK_DISTRIBUTION.finditer(compact):
            if match.group("kind") != kind:
                continue
            base = Decimal(match.group("base") or "1")
            ratio = _decimal(match.group("amount")) / base
            matches.append((ratio, page_number, match.span()))
    if not matches:
        return Decimal(0), {}
    values = {item[0] for item in matches}
    if len(values) != 1:
        raise OfficialDividendError(f"分红实施PDF中的{kind}比例存在歧义")
    value = next(iter(values))
    return value, _spans_by_page((page, span) for ratio, page, span in matches if ratio == value)


def _has_unparsed_share_distribution(
    pages: list[str], stock_ratio: Decimal, capitalization_ratio: Decimal
) -> bool:
    compact = "".join(re.sub(r"\s+", "", page) for page in pages)
    compact = compact.replace("差异化分红送转：否", "").replace("差异化分红送转否", "")
    compact = re.sub(r"(?:不送红股|不送股|不转增|不进行送股|不进行转增|不涉及送股|不涉及转增)", "", compact)
    recognized: dict[str, list[tuple[int, int]]] = {"送股": [], "转增": []}
    for match in _STOCK_DISTRIBUTION.finditer(compact):
        recognized[match.group("kind")].append(match.span())
    for marker, ratio in (("送红股", stock_ratio), ("送股", stock_ratio), ("转增", capitalization_ratio)):
        for match in re.finditer(marker, compact):
            if any(start <= match.start() < end for start, end in recognized["送股"] + recognized["转增"]):
                continue
            if ratio == 0:
                return True
    return "送转" in compact


def _make_evidence_pages(
    page_texts: list[str], spans_by_page: dict[int, list[tuple[int, int]]]
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for page_number in sorted(spans_by_page):
        if not 1 <= page_number <= len(page_texts):
            raise OfficialDividendError("分红PDF页码证据超出原件范围")
        _compact, positions = _compact_with_positions(page_texts[page_number - 1])
        original = page_texts[page_number - 1]
        ranges: list[tuple[int, int]] = []
        for start, end in spans_by_page[page_number]:
            if not (0 <= start < end <= len(positions)):
                continue
            left = max(0, positions[start] - 100)
            right = min(len(original), positions[end - 1] + 180)
            ranges.append((left, right))
        merged = _merge_ranges(ranges)
        excerpt = " … ".join(re.sub(r"\s+", " ", original[left:right]).strip() for left, right in merged)
        if not excerpt:
            continue
        if len(excerpt) > MAX_EVIDENCE_EXCERPT_CHARS:
            raise OfficialDividendError("分红PDF证据摘录超过冻结上限")
        pages.append(
            {
                "page": page_number,
                "excerpt": excerpt,
                "excerptSha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            }
        )
    if len(pages) > MAX_EVIDENCE_PAGES:
        raise OfficialDividendError("分红PDF证据页数超过冻结上限")
    return pages


def _compact_with_positions(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(text):
        if char.isspace():
            continue
        chars.append(char)
        positions.append(index)
    return "".join(chars), positions


def _spans_by_page(items) -> dict[int, list[tuple[int, int]]]:
    output: dict[int, list[tuple[int, int]]] = {}
    for page_number, span in items:
        output.setdefault(page_number, []).append(span)
    return output


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for left, right in sorted(ranges):
        if merged and left <= merged[-1][1] + 32:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    return merged


def _pdf_matches_issuer(compact: str, code: str) -> bool:
    return re.search(rf"(?<!\d){re.escape(code)}(?!\d)", compact) is not None


def _pdf_matches_notice_title(page_texts: list[str], title: str) -> bool:
    title_compact = _compact_text(title)
    if not title_compact:
        return False
    first_pages = _compact_text("".join(page_texts[:2]))
    return title_compact in first_pages or _title_core(title_compact) in first_pages


def _title_core(title: str) -> str:
    # CNINFO sometimes inserts a company suffix or market marker into its title
    # while the original PDF uses the short issuer name. Keep the event wording
    # and year as the minimum cross-checkable identity.
    match = re.search(r"20\d{2}.*", title)
    return match.group(0) if match else title


def _page_with_identity(page_texts: list[str], code: str) -> int | None:
    for page_number, text in enumerate(page_texts, start=1):
        if _pdf_matches_issuer(_compact_text(text), code):
            return page_number
    return None


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", _CONTROL.sub("", _HTML_TAG.sub("", text)))


def _clean_title(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = _HTML_TAG.sub("", value)
    text = _CONTROL.sub("", text)
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if 1 <= len(text) <= 240 else ""


def _is_dividend_notice(title: str) -> bool:
    compact = _compact_text(title)
    return any(marker in compact for marker in _DIVIDEND_TITLE_MARKERS)


def _is_proposal_title(title: str) -> bool:
    if _is_implementation_title(title):
        return False
    compact = _compact_text(title)
    if "年度报告" in compact and any(
        marker in compact for marker in ("利润分配方案", "利润分配预案")
    ):
        return True
    return any(marker in compact for marker in _PROPOSAL_MARKERS)


def _is_revision_title(title: str) -> bool:
    compact = _compact_text(title)
    return any(marker in compact for marker in _REVISION_MARKERS)


def _is_ancillary_support_title(title: str) -> bool:
    compact = _compact_text(title)
    return any(marker in compact for marker in _ANCILLARY_SUPPORT_MARKERS)


def _revision_base_title(title: str) -> str | None:
    compact = _canonical_notice_title(title)
    matches = [compact.find(marker) for marker in _REVISION_MARKERS if compact.find(marker) > 0]
    if not matches:
        return None
    prefix = compact[: min(matches)].rstrip("的")
    return prefix or None


def _canonical_notice_title(title: str) -> str:
    compact = _compact_text(title)
    compact = compact.replace("关于", "")
    return re.sub(r"[，,。；;：:、（）()【】\[\]<>《》\-—_\s]", "", compact)


def _find_revision_implementation(
    revision: Mapping[str, Any], implementation_candidates: Mapping[str, Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    base_title = _revision_base_title(str(revision.get("title") or ""))
    if base_title is None or not re.search(r"20\d{2}", base_title):
        return None
    matches = [
        candidate
        for candidate in implementation_candidates.values()
        if _canonical_notice_title(str(candidate["notice"].get("title") or "")) == base_title
    ]
    return matches[0] if len(matches) == 1 else None


def _dates_intersect_window(record_day: date, ex_day: date, start: date, end: date) -> bool:
    return start <= record_day <= end or start <= ex_day <= end


def _notice_error_text(reason: str, notice: Mapping[str, Any]) -> str:
    notice_id = _valid_notice_id(notice.get("noticeId")) or "未知编号"
    title = _clean_title(notice.get("title")) or "未知标题"
    return f"{reason}（公告编号 {notice_id}，标题：{title}）"


def _is_implementation_title(title: str) -> bool:
    compact = _compact_text(title)
    return "实施公告" in compact or "實施公告" in compact


def _announced_total(payload: dict[str, Any]) -> int:
    value = payload.get("totalAnnouncement")
    if isinstance(value, bool):
        raise OfficialDividendError("巨潮资讯公告总数无效")
    if isinstance(value, int):
        total = value
    elif isinstance(value, str) and value.strip().isdigit():
        total = int(value.strip())
    else:
        raise OfficialDividendError("巨潮资讯未返回有效公告总数")
    if not 0 <= total <= MAX_ACTION_QUERY_PAGES * official_filings.ANNOUNCEMENT_PAGE_SIZE:
        raise OfficialDividendError("巨潮资讯公告结果超过分页上限")
    return total


def _explicit_has_more(payload: dict[str, Any]) -> bool | None:
    if "hasMore" not in payload:
        return None
    value = payload.get("hasMore")
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value > 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes"}:
            return True
        if text in {"false", "0", "no"}:
            return False
    return None


def _valid_notice_id(value: object) -> str:
    if isinstance(value, bool):
        return ""
    text = str(value).strip() if isinstance(value, (str, int)) else ""
    return text if _NOTICE_ID.fullmatch(text) else ""


def _notice_id_sort_key(value: str) -> tuple[int, str]:
    try:
        return int(value), value
    except (TypeError, ValueError):
        return 0, value


def _decimal(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise OfficialDividendError("官方分红金额或比例无法解析") from exc
    if not result.is_finite() or result < 0:
        raise OfficialDividendError("官方分红金额或比例超出有效范围")
    return result


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite() or value < 0:
        raise OfficialDividendError("官方分红金额或比例无效")
    text = format(value.normalize(), "f")
    return "0" if text in {"-0", ""} else text


def _build_date(match: re.Match[str]) -> date:
    try:
        return date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
    except (TypeError, ValueError) as exc:
        raise OfficialDividendError("官方分红日期不是有效日历日期") from exc


def _parse_iso_day(value: object, label: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        _raise_backtest_input_error(f"{label}格式无效")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        _raise_backtest_input_error(f"{label}不是有效日期", cause=exc)


def _subtract_calendar_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


def _field_label(field: str) -> str:
    return {"recordDate": "股权登记日", "exDate": "除权日", "paymentDate": "现金红利发放日"}.get(field, field)


def _raise_backtest_input_error(message: str, *, cause: Exception | None = None) -> None:
    _raise_backtest_error("BacktestInputError", message, cause=cause)


def _raise_backtest_data_error(message: str, *, cause: Exception | None = None) -> None:
    _raise_backtest_error("BacktestDataError", message, cause=cause)


def _raise_backtest_error(
    error_name: str, message: str, *, cause: Exception | None = None
) -> None:
    try:
        from core.web.services.financial_backtest import data as backtest_data

        error_class = getattr(backtest_data, error_name)
    except Exception:  # noqa: BLE001 - avoid an import cycle during module loading
        error_class = OfficialDividendError
    error = error_class(message)
    if cause is not None:
        raise error from cause
    raise error
