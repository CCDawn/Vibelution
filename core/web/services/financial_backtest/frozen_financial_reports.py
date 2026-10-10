"""Immutable, cutoff-scoped A-share periodic-report PDF evidence for backtests."""

from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any

from core.web.services.financial_backtest import official_pdf
from core.web.services.financial_backtest.contract import sha256_json
from core.web.services.financial_backtest.data import BacktestInputError
from core.web.services.financial_backtest.financial_report_contract import (
    _MAX_CODE_CHARS,
    _MAX_DOCUMENTS,
    _MAX_GROUPS,
    _MAX_ITEMS_PER_GROUP,
    _MAX_PERIODS_PER_GROUP,
    _MAX_REVISIONS_PER_GROUP,
    _MAX_TITLE_CHARS,
    _MAX_TOTAL_PDF_BYTES,
    _MAX_UNMAPPED_REVISIONS_PER_GROUP,
    _PAGE_KEYS,
    _PERIOD_RE,
    _SCHEMA_VERSION,
    _SHA_RE,
    _STATUS,
    _VERSION_TYPES,
    RESEARCH_KIND,
    _bounded_source_text,
    _bounded_warnings,
    _canonical_date,
    _canonical_dates,
    _canonical_symbols,
    _snapshot_hash,
    _unique_warnings,
    _valid_timestamp,
    validate_research_snapshot,
)

_SOURCE_QUERY_FAILED = "巨潮资讯定期报告查询失败。"
_NO_REPORT_WARNING = "截止日前未取得可读取的完整定期报告页摘录。"
_REVISION_WARNING = "已保留截止日前发现的修订/更正候选；其数值影响及替代关系未核实。"
_BUDGET_WARNING = "财报 PDF 下载或页文本达到本次研究预算上限，覆盖不完整。"
_PDF_FAILURE_WARNING = "部分财报 PDF 无法下载或提取，原公告来源已保留。"
_BSE_NEW_CODE_WARNING = (
    "北交所920号段与2025-10-09前旧代码未建立官方映射；"
    "本次仅按完全相同的证券代码匹配，切换前财报可能缺失。"
)
_BSE_LEGACY_CODE_WARNING = (
    "北交所于2025-10-09切换至920号段；切换后主体代码映射未经官方校验，"
    "本组仅按完全相同的证券代码匹配。"
)
_BSE_CODE_TRANSITION = date(2025, 10, 9)


def freeze_financial_report_snapshot(
    symbols: Sequence[str],
    decision_dates: Sequence[str],
    *,
    notice_loader: Callable[..., Mapping[str, Any]] | None = None,
    pdf_loader: Callable[..., Mapping[str, Any]] | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Acquire official A-share PDFs once and freeze bounded page excerpts.

    Source queries are issued once per symbol through the latest date in the
    schedule. Each date then receives only notices published strictly before
    that date. The returned artifact is self-contained for offline restore;
    restore/validation never contacts CNINFO or re-downloads a document.
    """

    canonical_symbols = _canonical_symbols(symbols)
    dates = _canonical_dates(decision_dates)
    if len(canonical_symbols) * len(dates) > _MAX_GROUPS:
        raise BacktestInputError("历史财报研究最多支持20个股票与决策日组合")

    load_notices = notice_loader or official_pdf.load_periodic_report_notices
    load_pdf = pdf_loader or official_pdf.fetch_and_extract_official_pdf
    frozen_at = _freeze_time(now_provider)
    latest_cutoff = date.fromisoformat(dates[-1]) - timedelta(days=1)
    notice_payloads: dict[str, dict[str, Any]] = {}
    for symbol in canonical_symbols:
        try:
            payload = load_notices(symbol, cutoff=latest_cutoff)
        except Exception:  # noqa: BLE001 - failed sources remain coverage state
            payload = {"status": "failed", "warnings": [_SOURCE_QUERY_FAILED]}
        notice_payloads[symbol] = _normalize_notice_payload(
            payload, symbol=symbol, cutoff=latest_cutoff, default_fetched_at=frozen_at
        )

    groups: list[dict[str, Any]] = []
    documents_by_url: dict[str, dict[str, Any]] = {}
    total_pdf_bytes = 0
    attempted_documents = 0
    for symbol in canonical_symbols:
        source_payload = notice_payloads[symbol]
        for decision_date in dates:
            decision_day = date.fromisoformat(decision_date)
            if source_payload["status"] == "failed":
                transition_warnings = _bse_code_warnings(symbol, decision_day)
                groups.append(
                    _failed_group(symbol, decision_date, source_payload["warnings"])
                )
                if transition_warnings:
                    groups[-1]["warnings"] = _unique_warnings(
                        [*groups[-1]["warnings"], *transition_warnings]
                    )
                continue
            warnings = list(source_payload["warnings"])
            warnings.extend(_bse_code_warnings(symbol, decision_day))
            eligible = [
                notice
                for notice in source_payload["items"]
                if date.fromisoformat(notice["publishedDate"]) < decision_day
            ]
            selected, selection_warnings = _select_notices_for_group(eligible)
            warnings.extend(selection_warnings)
            document_items: list[dict[str, Any]] = []
            for notice in selected:
                url = notice["url"]
                document = documents_by_url.get(url)
                if document is None:
                    if attempted_documents >= _MAX_DOCUMENTS:
                        warnings.append(_BUDGET_WARNING)
                        continue
                    remaining = _MAX_TOTAL_PDF_BYTES - total_pdf_bytes
                    if remaining <= 0:
                        warnings.append(_BUDGET_WARNING)
                        continue
                    attempted_documents += 1
                    try:
                        pdf_result = load_pdf(
                            url,
                            max_bytes=min(official_pdf.MAX_PDF_BYTES, remaining),
                            timeout=official_pdf.DEFAULT_TIMEOUT_SECONDS,
                        )
                        document = _normalize_pdf_result(
                            pdf_result,
                            url=url,
                            default_fetched_at=frozen_at,
                            max_bytes=min(official_pdf.MAX_PDF_BYTES, remaining),
                        )
                        total_pdf_bytes += document["byteSize"]
                    except Exception:  # noqa: BLE001 - retain metadata with partial evidence
                        document = _failed_document(url, frozen_at)
                    documents_by_url[url] = document
                item = _notice_item(notice, document)
                document_items.append(item)
                if item["versionType"] != "original":
                    warnings.append(_REVISION_WARNING)
                if item["coverageStatus"] != "available":
                    warnings.append(_PDF_FAILURE_WARNING)

            if not document_items:
                warnings.append(_NO_REPORT_WARNING)
            group_status = (
                "available"
                if document_items
                and not warnings
                and all(
                    item["coverageStatus"] == "available" for item in document_items
                )
                else "partial"
            )
            for item in document_items:
                item["coverageStatus"] = (
                    group_status if item["coverageStatus"] == "available" else "partial"
                )
            groups.append(
                {
                    "symbol": symbol,
                    "decisionDate": decision_date,
                    "coverageStatus": group_status,
                    "source": source_payload["source"],
                    "fetchedAt": source_payload["fetchedAt"],
                    "warnings": _unique_warnings(warnings),
                    "items": document_items,
                }
            )

    if groups and all(group["coverageStatus"] == "failed" for group in groups):
        raise BacktestInputError("历史财报公告查询全部失败，无法冻结研究证据")

    referenced_urls = {item["url"] for group in groups for item in group["items"]}
    documents = [
        documents_by_url[url]
        for url in sorted(referenced_urls)
        if url in documents_by_url
    ]
    if not any(document["pages"] for document in documents):
        raise BacktestInputError(
            "未取得可用的官方财报PDF页摘录，不能按财报证据模式回测"
        )
    snapshot: dict[str, Any] = {
        "schemaVersion": _SCHEMA_VERSION,
        "researchKind": RESEARCH_KIND,
        "symbols": list(canonical_symbols),
        "decisionDates": list(dates),
        "groups": groups,
        "documents": documents,
        "frozenAt": frozen_at,
    }
    snapshot["researchHash"] = _snapshot_hash(snapshot)
    return validate_research_snapshot(
        snapshot,
        symbols=canonical_symbols,
        decision_dates=dates,
    )


def decision_research_material(
    snapshot: Mapping[str, Any],
    *,
    symbols: Sequence[str],
    decision_date: str,
) -> dict[str, Any]:
    """Project exactly one offline financial-report group for a decision."""

    canonical_symbols = _canonical_symbols(symbols)
    canonical_date = _canonical_dates([decision_date])[0]
    valid = validate_research_snapshot(snapshot, symbols=canonical_symbols)
    if canonical_date not in valid["decisionDates"]:
        raise BacktestInputError("历史财报快照不包含当前决策日")
    documents_by_id = {
        document["documentId"]: document for document in valid["documents"]
    }
    selected_groups = [
        group
        for group in valid["groups"]
        if group["decisionDate"] == canonical_date
        and group["symbol"] in canonical_symbols
    ]
    if {group["symbol"] for group in selected_groups} != set(canonical_symbols):
        raise BacktestInputError("历史财报快照缺少当前决策标的")
    selected_groups.sort(key=lambda group: group["symbol"])
    projected_groups = []
    for group in selected_groups:
        items = []
        for reference in group["items"]:
            document = documents_by_id[reference["documentId"]]
            items.append(
                {
                    **copy.deepcopy(reference),
                    "documentSha256": document["documentSha256"],
                    "pageCount": document["pageCount"],
                    "pages": copy.deepcopy(document["pages"]),
                    "documentWarnings": list(document["warnings"]),
                    "numericValidation": "not_performed",
                    "trust": "untrusted_official_pdf_text",
                }
            )
        projected_groups.append(
            {
                "symbol": group["symbol"],
                "coverageStatus": group["coverageStatus"],
                "warnings": list(group["warnings"]),
                "items": items,
            }
        )
    status = (
        "partial"
        if any(group["coverageStatus"] != "available" for group in selected_groups)
        else "available"
    )
    item_count = sum(len(group["items"]) for group in projected_groups)
    return {
        "researchKind": RESEARCH_KIND,
        "asOfDate": canonical_date,
        "symbols": list(canonical_symbols),
        "status": status,
        "groupCount": len(projected_groups),
        "itemCount": item_count,
        "groups": projected_groups,
    }


def research_coverage_summary(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return the existing financial backtest research-coverage DTO shape."""

    valid = validate_research_snapshot(snapshot)
    groups = valid["groups"]
    status = (
        "partial"
        if any(group["coverageStatus"] != "available" for group in groups)
        else "available"
    )
    warnings = _unique_warnings(
        warning for group in groups for warning in group["warnings"]
    )
    item_count = sum(len(group["items"]) for group in groups)
    available_count = sum(group["coverageStatus"] == "available" for group in groups)
    partial_count = sum(group["coverageStatus"] == "partial" for group in groups)
    failed_count = sum(group["coverageStatus"] == "failed" for group in groups)
    if status == "partial":
        notice = "财报原件或页文本摘录覆盖不完整；已取得内容的财务数值未经独立验证。"
    elif item_count:
        notice = f"已冻结{item_count}条官方财报PDF页摘录；原始财务数值未经独立验证。"
    else:
        notice = "历史财报查询完成，但未取得可用的原始PDF页文本摘录。"
    return {
        "status": status,
        "groupCount": len(groups),
        "availableGroupCount": available_count,
        "partialGroupCount": partial_count,
        "failedGroupCount": failed_count,
        "itemCount": item_count,
        "notice": notice,
        "warnings": warnings,
    }


def _normalize_notice_payload(
    payload: Any, *, symbol: str, cutoff: date, default_fetched_at: str
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return _notice_failure(default_fetched_at)
    status = str(payload.get("status") or "")
    if status not in _STATUS:
        return _notice_failure(default_fetched_at)
    source = str(payload.get("source") or "").strip()
    fetched_at = str(payload.get("fetchedAt") or "").strip()
    warnings = _bounded_warnings(payload.get("warnings"))
    if source != official_pdf.SOURCE:
        warnings.append("公告来源不是已配置的官方披露源。")
        return _notice_failure(default_fetched_at, warnings)
    if not _valid_timestamp(fetched_at):
        fetched_at = default_fetched_at
        warnings.append("公告获取时间无效，已使用本次冻结时间。")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return _notice_failure(fetched_at, [*warnings, "公告条目结构无效。"])
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_items:
        if not isinstance(raw, Mapping):
            warnings.append("部分公告记录格式无效，已排除。")
            continue
        try:
            item_symbol = _canonical_symbols([raw.get("symbol")])[0]
            published = _canonical_date(raw.get("publishedDate"))
            url = official_pdf.validate_official_pdf_url(raw.get("url"))
        except (BacktestInputError, TypeError, ValueError):
            item_symbol, published, url = "", None, ""
        report_period = str(raw.get("reportPeriod") or "").strip()
        report_kind = str(raw.get("reportKind") or "").strip()
        version_type = str(raw.get("versionType") or "").strip()
        title = _bounded_source_text(raw.get("title"), _MAX_TITLE_CHARS)
        notice_code = _bounded_source_text(raw.get("noticeCode"), _MAX_CODE_CHARS)
        row_source = str(raw.get("source") or "").strip()
        if (
            item_symbol != symbol
            or published is None
            or published > cutoff
            or not url
            or not title
            or not notice_code
            or row_source != official_pdf.SOURCE
            or version_type not in _VERSION_TYPES
            or (report_period and not _PERIOD_RE.fullmatch(report_period))
            or (version_type == "unmapped_revision_notice" and report_period)
            or (version_type != "unmapped_revision_notice" and not report_period)
            or report_kind not in {"annual", "semiannual", "q1", "q3", "unknown"}
            or (report_kind == "unknown")
            != (version_type == "unmapped_revision_notice")
        ):
            warnings.append("部分公告缺少有效报告期、日期或官方PDF链接，已排除。")
            continue
        key = (notice_code, url)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "symbol": symbol,
                "noticeCode": notice_code,
                "reportKind": report_kind,
                "reportPeriod": report_period,
                "versionType": version_type,
                "publishedDate": published.isoformat(),
                "title": title,
                "url": url,
                "source": official_pdf.SOURCE,
            }
        )
    if status == "failed":
        return _notice_failure(fetched_at, warnings or [_SOURCE_QUERY_FAILED])
    return {
        "status": "partial" if status == "partial" or warnings else "available",
        "source": official_pdf.SOURCE,
        "fetchedAt": fetched_at,
        "items": items,
        "warnings": _unique_warnings(warnings),
    }


def _normalize_pdf_result(
    payload: Any,
    *,
    url: str,
    default_fetched_at: str,
    max_bytes: int = official_pdf.MAX_PDF_BYTES,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise BacktestInputError("PDF抽取结果结构无效")
    if str(payload.get("numericValidation") or "") != "not_performed":
        raise BacktestInputError("PDF数值校验状态无效")
    document_hash = str(payload.get("documentSha256") or "")
    page_count = payload.get("pageCount")
    byte_size = payload.get("byteSize")
    status = str(payload.get("coverageStatus") or "")
    if (
        (document_hash and not _SHA_RE.fullmatch(document_hash))
        or type(page_count) is not int
        or not 0 <= page_count <= 100_000
        or type(byte_size) is not int
        or not 0 <= byte_size <= min(max_bytes, official_pdf.MAX_PDF_BYTES)
        or status not in {"available", "partial"}
        or ((document_hash == "") != (byte_size == 0))
        or (status == "available" and (not document_hash or byte_size == 0))
    ):
        raise BacktestInputError("PDF抽取结果元数据无效")
    pages = payload.get("pages")
    if not isinstance(pages, list) or len(pages) > official_pdf.MAX_EXCERPT_PAGES:
        raise BacktestInputError("PDF页摘录数量无效")
    normalized_pages = []
    total_chars = 0
    for raw_page in pages:
        if not isinstance(raw_page, Mapping) or set(raw_page) != _PAGE_KEYS:
            raise BacktestInputError("PDF页摘录字段无效")
        page = raw_page.get("page")
        excerpt = str(raw_page.get("excerpt") or "")
        digest = str(raw_page.get("excerptSha256") or "")
        if (
            type(page) is not int
            or page < 1
            or page > min(page_count, official_pdf.MAX_PDF_PAGES)
            or not excerpt
            or len(excerpt) > official_pdf.MAX_PAGE_EXCERPT_CHARS
            or not _SHA_RE.fullmatch(digest)
            or hashlib.sha256(excerpt.encode("utf-8")).hexdigest() != digest
        ):
            raise BacktestInputError("PDF页摘录内容或摘要无效")
        total_chars += len(excerpt)
        if total_chars > official_pdf.MAX_DOCUMENT_EXCERPT_CHARS:
            raise BacktestInputError("PDF页文本超过单文档字符预算")
        normalized_pages.append(
            {"page": page, "excerpt": excerpt, "excerptSha256": digest}
        )
    if len({page["page"] for page in normalized_pages}) != len(normalized_pages):
        raise BacktestInputError("PDF页摘录页码重复")
    fetched_at = str(payload.get("fetchedAt") or default_fetched_at).strip()
    if not _valid_timestamp(fetched_at):
        fetched_at = default_fetched_at
    document_id = sha256_json({"url": url, "documentSha256": document_hash})
    return {
        "documentId": document_id,
        "url": url,
        "documentSha256": document_hash,
        "pageCount": page_count,
        "byteSize": byte_size,
        "pages": sorted(normalized_pages, key=lambda page: page["page"]),
        "coverageStatus": status,
        "warnings": _bounded_warnings(payload.get("warnings")),
        "fetchedAt": fetched_at,
        "numericValidation": "not_performed",
    }


def _failed_document(url: str, fetched_at: str) -> dict[str, Any]:
    return {
        "documentId": sha256_json({"url": url, "documentSha256": ""}),
        "url": url,
        "documentSha256": "",
        "pageCount": 0,
        "byteSize": 0,
        "pages": [],
        "coverageStatus": "partial",
        "warnings": [_PDF_FAILURE_WARNING],
        "fetchedAt": fetched_at,
        "numericValidation": "not_performed",
    }


def _bse_code_warnings(symbol: str, decision_day: date) -> list[str]:
    if symbol.startswith("bj920"):
        return [_BSE_NEW_CODE_WARNING]
    if symbol.startswith("bj") and decision_day > _BSE_CODE_TRANSITION:
        return [_BSE_LEGACY_CODE_WARNING]
    return []


def _notice_item(
    notice: Mapping[str, Any], document: Mapping[str, Any]
) -> dict[str, Any]:
    status = (
        "available"
        if document["coverageStatus"] == "available" and document["pages"]
        else "partial"
    )
    return {
        "documentId": document["documentId"],
        "symbol": notice["symbol"],
        "reportKind": notice["reportKind"],
        "reportPeriod": notice["reportPeriod"],
        "versionType": notice["versionType"],
        "noticeCode": notice["noticeCode"],
        "publishedDate": notice["publishedDate"],
        "title": notice["title"],
        "url": notice["url"],
        "source": notice["source"],
        "coverageStatus": status,
    }


def _select_notices_for_group(
    notices: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    mapped: dict[str, list[dict[str, Any]]] = {}
    unmapped_revisions = []
    for notice in notices:
        if notice["versionType"] == "unmapped_revision_notice":
            unmapped_revisions.append(notice)
        else:
            mapped.setdefault(notice["reportPeriod"], []).append(notice)
    period_order = sorted(mapped, key=_period_rank, reverse=True)
    selected_periods = period_order[:_MAX_PERIODS_PER_GROUP]
    if len(period_order) > _MAX_PERIODS_PER_GROUP:
        warnings.append("截止日前定期报告期数超过本次读取上限，仅保留最近四期。")
    selected: list[dict[str, Any]] = []
    revisions: list[dict[str, Any]] = []
    for period in selected_periods:
        period_notices = sorted(
            mapped[period],
            key=lambda item: (item["publishedDate"], item["noticeCode"]),
            reverse=True,
        )
        originals = [
            item for item in period_notices if item["versionType"] == "original"
        ]
        if originals:
            selected.append(originals[0])
        elif period_notices:
            selected.append(period_notices[0])
        revisions.extend(
            item for item in period_notices if item["versionType"] == "revision_notice"
        )
    revisions.sort(
        key=lambda item: (item["publishedDate"], item["noticeCode"]), reverse=True
    )
    if len(revisions) > _MAX_REVISIONS_PER_GROUP:
        warnings.append("修订/更正候选超过读取上限，部分候选仅计入覆盖警告。")
    selected.extend(revisions[:_MAX_REVISIONS_PER_GROUP])
    unmapped_revisions.sort(
        key=lambda item: (item["publishedDate"], item["noticeCode"]), reverse=True
    )
    if unmapped_revisions:
        warnings.append("发现无法可靠映射到报告期的修订/更正公告，已保留可读候选。")
    if len(unmapped_revisions) > _MAX_UNMAPPED_REVISIONS_PER_GROUP:
        warnings.append("未映射报告期的修订/更正公告超过读取上限。")
    selected.extend(unmapped_revisions[:_MAX_UNMAPPED_REVISIONS_PER_GROUP])
    selected.sort(
        key=lambda item: (
            _period_rank(item["reportPeriod"]) if item["reportPeriod"] else -1,
            item["publishedDate"],
            item["versionType"],
        ),
        reverse=True,
    )
    if len(selected) > _MAX_ITEMS_PER_GROUP:
        warnings.append("报告及修订候选达到本次分组上限。")
        selected = selected[:_MAX_ITEMS_PER_GROUP]
    return selected, warnings


def _period_rank(value: str) -> int:
    if not value:
        return -1
    match = re.fullmatch(r"(20\d{2})(FY|H1|Q1|Q3)", value)
    if not match:
        return -1
    year, kind = match.groups()
    quarter_rank = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}[kind]
    return int(year) * 10 + quarter_rank


def _failed_group(
    symbol: str, decision_date: str, warnings: Sequence[str]
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "decisionDate": decision_date,
        "coverageStatus": "failed",
        "source": "",
        "fetchedAt": "",
        "warnings": _unique_warnings([*warnings, _SOURCE_QUERY_FAILED]),
        "items": [],
    }


def _notice_failure(fetched_at: str, warnings: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "status": "failed",
        "source": "",
        "fetchedAt": fetched_at,
        "items": [],
        "warnings": _unique_warnings([*warnings, _SOURCE_QUERY_FAILED]),
    }


def _freeze_time(provider: Callable[[], datetime] | None) -> str:
    now = provider() if provider else datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise BacktestInputError("历史财报冻结时间必须带时区")
    return now.astimezone(timezone.utc).isoformat(timespec="seconds")


__all__ = [
    "RESEARCH_KIND",
    "decision_research_material",
    "freeze_financial_report_snapshot",
    "research_coverage_summary",
    "validate_research_snapshot",
]
