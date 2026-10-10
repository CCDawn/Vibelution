"""Canonical schema validation for frozen A-share report evidence."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from core.web.services import financial_market_service as market
from core.web.services.financial_backtest import official_pdf
from core.web.services.financial_backtest.contract import sha256_json
from core.web.services.financial_backtest.data import BacktestInputError

RESEARCH_KIND = "financial_reports"

_SCHEMA_VERSION = 1

_MAX_SYMBOLS = 3

_MAX_DECISION_DATES = 20

_MAX_GROUPS = 20

_MAX_PERIODS_PER_GROUP = 4

_MAX_REVISIONS_PER_GROUP = 4

_MAX_UNMAPPED_REVISIONS_PER_GROUP = 2

_MAX_ITEMS_PER_GROUP = (
    _MAX_PERIODS_PER_GROUP
    + _MAX_REVISIONS_PER_GROUP
    + _MAX_UNMAPPED_REVISIONS_PER_GROUP
)

_MAX_DOCUMENTS = 80

_MAX_TOTAL_PDF_BYTES = 100_000_000

_MAX_TITLE_CHARS = 240

_MAX_CODE_CHARS = 96

_MAX_SOURCE_CHARS = 80

_MAX_TIMESTAMP_CHARS = 64

_MAX_WARNING_CHARS = 300

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

_PERIOD_RE = re.compile(r"^20\d{2}(?:FY|H1|Q1|Q3)$")

_VERSION_TYPES = {"original", "revision_notice", "unmapped_revision_notice"}

_STATUS = {"available", "partial", "failed"}

_SNAPSHOT_KEYS = {
    "schemaVersion",
    "researchKind",
    "symbols",
    "decisionDates",
    "groups",
    "documents",
    "frozenAt",
    "researchHash",
}

_GROUP_KEYS = {
    "symbol",
    "decisionDate",
    "coverageStatus",
    "source",
    "fetchedAt",
    "warnings",
    "items",
}

_ITEM_KEYS = {
    "documentId",
    "symbol",
    "reportKind",
    "reportPeriod",
    "versionType",
    "noticeCode",
    "publishedDate",
    "title",
    "url",
    "source",
    "coverageStatus",
}

_DOCUMENT_KEYS = {
    "documentId",
    "url",
    "documentSha256",
    "pageCount",
    "byteSize",
    "pages",
    "coverageStatus",
    "warnings",
    "fetchedAt",
    "numericValidation",
}

_PAGE_KEYS = {"page", "excerpt", "excerptSha256"}


def validate_research_snapshot(
    payload: Mapping[str, Any],
    *,
    expected_hash: str | None = None,
    symbols: Sequence[str] | None = None,
    decision_dates: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Validate the financial-report kind, evidence references and digest."""

    if (
        not isinstance(payload, Mapping)
        or set(payload) != _SNAPSHOT_KEYS
        or type(payload.get("schemaVersion")) is not int
        or payload.get("schemaVersion") != _SCHEMA_VERSION
        or payload.get("researchKind") != RESEARCH_KIND
    ):
        raise BacktestInputError("历史财报快照格式、版本或研究类型无效")
    actual_symbols = _canonical_symbols(payload.get("symbols"))
    actual_dates = _canonical_dates(payload.get("decisionDates"))
    if len(actual_symbols) * len(actual_dates) > _MAX_GROUPS:
        raise BacktestInputError("历史财报快照超过20个股票与决策日组合")
    if symbols is not None and actual_symbols != _canonical_symbols(symbols):
        raise BacktestInputError("历史财报快照标的与回测不匹配")
    if decision_dates is not None and actual_dates != _canonical_dates(decision_dates):
        raise BacktestInputError("历史财报快照决策日与回测不匹配")
    frozen_at = _validated_timestamp(payload.get("frozenAt"), "快照冻结时间")
    expected_pairs = {
        (symbol, decision_date)
        for symbol in actual_symbols
        for decision_date in actual_dates
    }
    raw_groups = payload.get("groups")
    if not isinstance(raw_groups, list) or len(raw_groups) != len(expected_pairs):
        raise BacktestInputError("历史财报快照分组不完整")
    groups: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for raw_group in raw_groups:
        if not isinstance(raw_group, Mapping):
            raise BacktestInputError("历史财报快照分组格式无效")
        group = _validate_group(raw_group, expected_pairs)
        pair = (group["symbol"], group["decisionDate"])
        if pair in seen_pairs:
            raise BacktestInputError("历史财报快照分组重复")
        seen_pairs.add(pair)
        groups.append(group)
    if seen_pairs != expected_pairs:
        raise BacktestInputError("历史财报快照分组标识不匹配")
    groups.sort(key=lambda group: (group["symbol"], group["decisionDate"]))

    raw_documents = payload.get("documents")
    if not isinstance(raw_documents, list) or len(raw_documents) > _MAX_DOCUMENTS:
        raise BacktestInputError("历史财报快照文件列表无效或超过上限")
    documents: list[dict[str, Any]] = []
    documents_by_url: dict[str, dict[str, Any]] = {}
    for raw_document in raw_documents:
        if not isinstance(raw_document, Mapping):
            raise BacktestInputError("历史财报PDF记录格式无效")
        document = _validate_document(raw_document)
        url = document["url"]
        if url in documents_by_url:
            raise BacktestInputError("历史财报PDF URL重复")
        documents_by_url[url] = document
        documents.append(document)
    documents.sort(key=lambda item: item["url"])

    referenced_urls: set[str] = set()
    normalized_groups = []
    for group in groups:
        normalized_items = []
        decision_day = date.fromisoformat(group["decisionDate"])
        for item in group["items"]:
            document = documents_by_url.get(item["url"])
            if (
                document is None
                or document["documentId"] != item["documentId"]
                or date.fromisoformat(item["publishedDate"]) >= decision_day
            ):
                raise BacktestInputError("历史财报条目缺少离线PDF或晚于决策日")
            referenced_urls.add(item["url"])
            normalized_items.append(item)
        normalized_groups.append({**group, "items": normalized_items})
    if referenced_urls != set(documents_by_url):
        raise BacktestInputError("历史财报快照包含未引用的PDF记录")

    normalized: dict[str, Any] = {
        "schemaVersion": _SCHEMA_VERSION,
        "researchKind": RESEARCH_KIND,
        "symbols": list(actual_symbols),
        "decisionDates": list(actual_dates),
        "groups": normalized_groups,
        "documents": documents,
        "frozenAt": frozen_at,
    }
    raw_hash = str(payload.get("researchHash") or "")
    if raw_hash != _snapshot_hash(normalized):
        raise BacktestInputError("历史财报快照摘要校验失败")
    if expected_hash is not None and raw_hash != str(expected_hash).strip():
        raise BacktestInputError("历史财报快照与回测引用摘要不匹配")
    normalized["researchHash"] = raw_hash
    return normalized


def _validate_group(
    payload: Mapping[str, Any], expected_pairs: set[tuple[str, str]]
) -> dict[str, Any]:
    if set(payload) != _GROUP_KEYS:
        raise BacktestInputError("历史财报分组包含不支持的字段")
    symbol = _canonical_symbols([payload.get("symbol")])[0]
    decision_date = _canonical_dates([payload.get("decisionDate")])[0]
    if (symbol, decision_date) not in expected_pairs:
        raise BacktestInputError("历史财报分组标识不匹配")
    status = str(payload.get("coverageStatus") or "")
    if status not in _STATUS:
        raise BacktestInputError("历史财报分组覆盖状态无效")
    source = _validated_text(payload.get("source"), _MAX_SOURCE_CHARS)
    fetched_at = _validated_text(payload.get("fetchedAt"), _MAX_TIMESTAMP_CHARS)
    warnings = _validated_warnings(payload.get("warnings"))
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or len(raw_items) > _MAX_ITEMS_PER_GROUP:
        raise BacktestInputError("历史财报分组条目无效或超过上限")
    if status == "failed":
        if raw_items or not warnings:
            raise BacktestInputError("失败的历史财报分组必须为空并说明原因")
    elif not source or not _valid_timestamp(fetched_at):
        raise BacktestInputError("历史财报分组缺少来源或获取时间")
    elif status == "available" and (not raw_items or warnings):
        raise BacktestInputError("完整覆盖的历史财报分组不能缺少证据或含警告")
    elif status == "partial" and not warnings:
        raise BacktestInputError("不完整的历史财报分组必须说明覆盖缺口")

    items: list[dict[str, Any]] = []
    seen_documents: set[str] = set()
    decision_day = date.fromisoformat(decision_date)
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping) or set(raw_item) != _ITEM_KEYS:
            raise BacktestInputError("历史财报引用字段无效")
        item_symbol = _canonical_symbols([raw_item.get("symbol")])[0]
        period = str(raw_item.get("reportPeriod") or "")
        kind = str(raw_item.get("reportKind") or "")
        version = str(raw_item.get("versionType") or "")
        published = _canonical_date(raw_item.get("publishedDate"))
        title = _validated_text(raw_item.get("title"), _MAX_TITLE_CHARS)
        notice_code = _validated_text(raw_item.get("noticeCode"), _MAX_CODE_CHARS)
        url = official_pdf.validate_official_pdf_url(raw_item.get("url"))
        item_source = _validated_text(raw_item.get("source"), _MAX_SOURCE_CHARS)
        document_id = str(raw_item.get("documentId") or "")
        item_status = str(raw_item.get("coverageStatus") or "")
        if (
            item_symbol != symbol
            or (period and not _PERIOD_RE.fullmatch(period))
            or version not in _VERSION_TYPES
            or (version == "unmapped_revision_notice") != (not period)
            or kind not in {"annual", "semiannual", "q1", "q3", "unknown"}
            or (kind == "unknown") != (version == "unmapped_revision_notice")
            or published >= decision_day
            or not title
            or not notice_code
            or not url
            or item_source != official_pdf.SOURCE
            or not _SHA_RE.fullmatch(document_id)
            or item_status not in {"available", "partial"}
            or document_id in seen_documents
        ):
            raise BacktestInputError("历史财报引用来源、版本或截止日无效")
        seen_documents.add(document_id)
        items.append(
            {
                "documentId": document_id,
                "symbol": item_symbol,
                "reportKind": kind,
                "reportPeriod": period,
                "versionType": version,
                "noticeCode": notice_code,
                "publishedDate": published.isoformat(),
                "title": title,
                "url": url,
                "source": item_source,
                "coverageStatus": item_status,
            }
        )
    if status == "failed" and items:
        raise BacktestInputError("失败的历史财报分组不能包含证据")
    if status == "available" and any(
        item["coverageStatus"] != "available" for item in items
    ):
        raise BacktestInputError("完整覆盖的历史财报分组含不完整PDF")
    return {
        "symbol": symbol,
        "decisionDate": decision_date,
        "coverageStatus": status,
        "source": source,
        "fetchedAt": fetched_at,
        "warnings": warnings,
        "items": items,
    }


def _validate_document(payload: Mapping[str, Any]) -> dict[str, Any]:
    if set(payload) != _DOCUMENT_KEYS:
        raise BacktestInputError("历史财报PDF记录包含不支持的字段")
    url = official_pdf.validate_official_pdf_url(payload.get("url"))
    if not url:
        raise BacktestInputError("历史财报PDF来源URL无效")
    document_hash = str(payload.get("documentSha256") or "")
    if document_hash and not _SHA_RE.fullmatch(document_hash):
        raise BacktestInputError("历史财报原件摘要格式无效")
    page_count = payload.get("pageCount")
    byte_size = payload.get("byteSize")
    status = str(payload.get("coverageStatus") or "")
    if (
        type(page_count) is not int
        or not 0 <= page_count <= 100_000
        or type(byte_size) is not int
        or not 0 <= byte_size <= official_pdf.MAX_PDF_BYTES
        or status not in {"available", "partial"}
        or payload.get("numericValidation") != "not_performed"
    ):
        raise BacktestInputError("历史财报PDF元数据无效")
    if (document_hash == "") != (byte_size == 0):
        raise BacktestInputError("历史财报原件摘要与字节数不匹配")
    fetched_at = _validated_timestamp(payload.get("fetchedAt"), "PDF获取时间")
    pages_payload = payload.get("pages")
    if (
        not isinstance(pages_payload, list)
        or len(pages_payload) > official_pdf.MAX_EXCERPT_PAGES
    ):
        raise BacktestInputError("历史财报PDF页摘录数量无效")
    pages = []
    seen_pages: set[int] = set()
    total_chars = 0
    for raw_page in pages_payload:
        if not isinstance(raw_page, Mapping) or set(raw_page) != _PAGE_KEYS:
            raise BacktestInputError("历史财报页摘录格式无效")
        page = raw_page.get("page")
        excerpt = _validated_text(
            raw_page.get("excerpt"), official_pdf.MAX_PAGE_EXCERPT_CHARS
        )
        digest = str(raw_page.get("excerptSha256") or "")
        if (
            type(page) is not int
            or not 1 <= page <= min(page_count, official_pdf.MAX_PDF_PAGES)
            or page in seen_pages
            or not _SHA_RE.fullmatch(digest)
            or hashlib.sha256(excerpt.encode("utf-8")).hexdigest() != digest
        ):
            raise BacktestInputError("历史财报页摘录摘要或页码无效")
        seen_pages.add(page)
        total_chars += len(excerpt)
        pages.append({"page": page, "excerpt": excerpt, "excerptSha256": digest})
    if total_chars > official_pdf.MAX_DOCUMENT_EXCERPT_CHARS:
        raise BacktestInputError("历史财报PDF页文本超过单文档上限")
    warnings = _validated_warnings(payload.get("warnings"))
    document_id = str(payload.get("documentId") or "")
    expected_id = sha256_json({"url": url, "documentSha256": document_hash})
    if document_id != expected_id:
        raise BacktestInputError("历史财报PDF标识不匹配")
    return {
        "documentId": document_id,
        "url": url,
        "documentSha256": document_hash,
        "pageCount": page_count,
        "byteSize": byte_size,
        "pages": sorted(pages, key=lambda row: row["page"]),
        "coverageStatus": status,
        "warnings": warnings,
        "fetchedAt": fetched_at,
        "numericValidation": "not_performed",
    }


def _canonical_symbols(values: Any) -> tuple[str, ...]:
    if (
        not isinstance(values, Sequence)
        or isinstance(values, (str, bytes))
        or not values
    ):
        raise BacktestInputError("历史财报研究必须指定A股标的")
    if len(values) > _MAX_SYMBOLS:
        raise BacktestInputError("历史财报研究最多支持3只A股")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise BacktestInputError("历史财报研究包含无效A股代码")
        try:
            normalized.append(market.normalize_a_share_symbol(value))
        except market.MarketDataError as exc:
            raise BacktestInputError("历史财报研究仅支持A股") from exc
    if len(set(normalized)) != len(normalized):
        raise BacktestInputError("历史财报研究标的不能重复")
    return tuple(sorted(normalized))


def _canonical_dates(values: Any) -> tuple[str, ...]:
    if (
        not isinstance(values, Sequence)
        or isinstance(values, (str, bytes))
        or not values
    ):
        raise BacktestInputError("历史财报研究必须指定决策日")
    if len(values) > _MAX_DECISION_DATES:
        raise BacktestInputError("历史财报研究最多支持20个决策日")
    dates = [_canonical_date(value).isoformat() for value in values]
    if len(set(dates)) != len(dates) or dates != sorted(dates):
        raise BacktestInputError("历史财报研究决策日必须按时间递增且不重复")
    return tuple(dates)


def _canonical_date(value: Any) -> date:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise BacktestInputError("历史财报日期必须是YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise BacktestInputError("历史财报日期无效") from exc
    if parsed.isoformat() != value:
        raise BacktestInputError("历史财报日期无效")
    return parsed


def _valid_timestamp(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > _MAX_TIMESTAMP_CHARS
    ):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return False
    return parsed.tzinfo is not None


def _validated_timestamp(value: Any, label: str) -> str:
    text = _validated_text(value, _MAX_TIMESTAMP_CHARS)
    if not _valid_timestamp(text):
        raise BacktestInputError(f"历史财报{label}无效")
    return text


def _bounded_source_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"[\r\n\t]+", " ", value).strip()
    text = " ".join(text.split())
    if any(ord(char) < 32 for char in text):
        return ""
    return text[:limit]


def _validated_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        raise BacktestInputError("历史财报快照文本字段无效")
    text = value.strip()
    if (
        value != text
        or len(text) > limit
        or any(ord(char) < 32 and char not in "\n\t" for char in text)
    ):
        raise BacktestInputError("历史财报快照文本字段超限或含控制字符")
    return text


def _bounded_warnings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _unique_warnings(value)


def _validated_warnings(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > 80:
        raise BacktestInputError("历史财报覆盖警告格式无效")
    warnings = []
    for warning in value:
        text = _validated_text(warning, _MAX_WARNING_CHARS)
        if not text:
            raise BacktestInputError("历史财报覆盖警告不能为空")
        warnings.append(text)
    return _unique_warnings(warnings)


def _unique_warnings(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _bounded_source_text(str(value or ""), _MAX_WARNING_CHARS)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
            if len(result) >= 80:
                break
    return result


def _snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    return sha256_json(
        {key: value for key, value in snapshot.items() if key != "researchHash"}
    )


__all__ = ["RESEARCH_KIND", "validate_research_snapshot"]
