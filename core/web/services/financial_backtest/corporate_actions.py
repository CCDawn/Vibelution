"""Frozen cash-dividend evidence and a deterministic FIFO entitlement ledger.

This ledger models cash dividends only. Bonus shares, capitalization shares,
historical tax periods without verified effective rules, and settlement
rounding are rejected or explicitly left unclaimed rather than inferred.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from core.web.services import financial_market_service as market
from core.web.services.financial_backtest import official_pdf
from core.web.services.financial_backtest.contract import sha256_json
from core.web.services.financial_backtest.data import BacktestInputError

CASH_DIVIDEND_RULE_V1 = "ashare_cash_dividend_v1"
_SCHEMA_VERSION = 1
_MAX_EVENTS = 1_000
_MAX_EVIDENCE_PAGES = 8
_MAX_EXCERPT_CHARS = 4_000
_MAX_TITLE_CHARS = 240
_MAX_ID_CHARS = 128
_MAX_CASH_PER_SHARE = Decimal(100)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DECIMAL_RE = re.compile(r"^(?:0|[1-9]\d{0,11})(?:\.\d{1,8})?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_POLICY_START = date(2015, 9, 8)
_BSE_POLICY_START = date(2024, 7, 1)
_BSE_POLICY_END = date(2027, 12, 31)

_ARTIFACT_FIELDS = {
    "schemaVersion",
    "ruleVersion",
    "symbol",
    "coverageStartDate",
    "coverageEndDate",
    "coverageStatus",
    "events",
}
_OPTIONAL_ARTIFACT_FIELDS = {"coverageEvidence", "priceValidation"}
_EVENT_FIELDS = {
    "symbol",
    "actionId",
    "noticeId",
    "publishedDate",
    "sourceUrl",
    "pdfSha256",
    "title",
    "recordDate",
    "exDate",
    "paymentDate",
    "cashPerShare",
    "stockDividendRatio",
    "capitalizationRatio",
    "evidencePages",
}
_PAGE_FIELDS = {"page", "excerpt", "excerptSha256"}


def freeze_cash_dividend_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Canonicalize a complete draft artifact and attach its SHA-256 digest."""

    if not isinstance(payload, Mapping):
        raise BacktestInputError("现金分红快照必须是对象")
    allowed = _ARTIFACT_FIELDS | _OPTIONAL_ARTIFACT_FIELDS | {"artifactHash"}
    if not _ARTIFACT_FIELDS <= set(payload) or set(payload) - allowed:
        raise BacktestInputError("现金分红快照字段不完整或包含未知字段")
    normalized = _canonical_artifact(payload)
    digest = sha256_json(normalized)
    if "artifactHash" in payload and payload.get("artifactHash") != digest:
        raise BacktestInputError("现金分红快照摘要与内容不匹配")
    normalized["artifactHash"] = digest
    return normalized


def validate_cash_dividend_artifact(
    payload: Mapping[str, Any], *, expected_symbol: str | None = None
) -> dict[str, Any]:
    """Validate schema, official-document evidence, coverage and frozen hash."""

    if (
        not isinstance(payload, Mapping)
        or not (_ARTIFACT_FIELDS | {"artifactHash"}) <= set(payload)
        or set(payload)
        - (_ARTIFACT_FIELDS | _OPTIONAL_ARTIFACT_FIELDS | {"artifactHash"})
    ):
        raise BacktestInputError("现金分红快照格式或字段无效")
    supplied_digest = payload.get("artifactHash")
    if not isinstance(supplied_digest, str) or not _SHA256_RE.fullmatch(
        supplied_digest
    ):
        raise BacktestInputError("现金分红快照摘要无效")
    normalized = _canonical_artifact(payload)
    actual_digest = sha256_json(normalized)
    if supplied_digest != actual_digest:
        raise BacktestInputError("现金分红快照摘要与内容不匹配")
    if expected_symbol is not None:
        expected = _canonical_symbol(expected_symbol)
        if expected != normalized["symbol"]:
            raise BacktestInputError("现金分红快照标的与回测标的不匹配")
    normalized["artifactHash"] = actual_digest
    return normalized


def _canonical_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
    if (
        type(payload.get("schemaVersion")) is not int
        or payload.get("schemaVersion") != _SCHEMA_VERSION
    ):
        raise BacktestInputError("现金分红快照版本不受支持")
    if payload.get("ruleVersion") != CASH_DIVIDEND_RULE_V1:
        raise BacktestInputError("现金分红规则版本不受支持")
    symbol = _canonical_symbol(payload.get("symbol"))
    start = _date_text(payload.get("coverageStartDate"), "覆盖开始日期")
    end = _date_text(payload.get("coverageEndDate"), "覆盖结束日期")
    if start > end:
        raise BacktestInputError("现金分红覆盖日期范围无效")
    if payload.get("coverageStatus") != "complete":
        raise BacktestInputError("现金分红覆盖不完整，不能冻结账本")
    events = payload.get("events")
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        raise BacktestInputError("现金分红事件必须是列表")
    if len(events) > _MAX_EVENTS:
        raise BacktestInputError("现金分红事件超过读取上限")
    canonical_events = [
        _canonical_event(raw, symbol=symbol, start=start, end=end) for raw in events
    ]
    action_ids = [event["actionId"] for event in canonical_events]
    if len(action_ids) != len(set(action_ids)):
        raise BacktestInputError("现金分红事件actionId重复，可能存在冲突公告")
    ex_dates = [event["exDate"] for event in canonical_events]
    if len(ex_dates) != len(set(ex_dates)):
        raise BacktestInputError("现金分红存在重复除权日，需先消解公告冲突")
    evidence = _canonical_optional_evidence(payload)
    coverage = evidence.get("coverageEvidence")
    if coverage is not None:
        notice_ids = set(coverage["noticeIds"])
        for event in canonical_events:
            if event["noticeId"] not in notice_ids:
                raise BacktestInputError("现金分红公告未出现在完整查询覆盖证据中")
            if not (
                coverage["queryStartDate"]
                <= event["publishedDate"]
                <= coverage["queryEndDate"]
            ):
                raise BacktestInputError("现金分红公告日期超出查询覆盖范围")
    canonical_events.sort(
        key=lambda event: (
            event["recordDate"],
            event["exDate"],
            event["paymentDate"],
            event["actionId"],
        )
    )
    return {
        "schemaVersion": _SCHEMA_VERSION,
        "ruleVersion": CASH_DIVIDEND_RULE_V1,
        "symbol": symbol,
        "coverageStartDate": start,
        "coverageEndDate": end,
        "coverageStatus": "complete",
        "events": canonical_events,
        **evidence,
    }


def _canonical_optional_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "coverageEvidence" in payload:
        result["coverageEvidence"] = _canonical_coverage_evidence(
            payload.get("coverageEvidence")
        )
    if "priceValidation" in payload:
        result["priceValidation"] = _canonical_price_validation(
            payload.get("priceValidation")
        )
    return result


def _canonical_coverage_evidence(value: Any) -> dict[str, Any]:
    fields = {
        "source",
        "queryStartDate",
        "queryEndDate",
        "pagesRead",
        "terminalPage",
        "noticeIds",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise BacktestInputError("现金分红公告覆盖证据字段无效")
    query_start = _date_text(value.get("queryStartDate"), "公告查询开始日期")
    query_end = _date_text(value.get("queryEndDate"), "公告查询结束日期")
    if query_start > query_end:
        raise BacktestInputError("公告查询日期范围无效")
    pages_read = value.get("pagesRead")
    if type(pages_read) is not int or not 1 <= pages_read <= 500:
        raise BacktestInputError("公告覆盖页数无效")
    if value.get("source") != "cninfo" or value.get("terminalPage") is not True:
        raise BacktestInputError("公告覆盖来源或完整末页标记无效")
    raw_ids = value.get("noticeIds")
    if not isinstance(raw_ids, Sequence) or isinstance(raw_ids, (str, bytes)):
        raise BacktestInputError("公告覆盖noticeIds必须是列表")
    if len(raw_ids) > 20_000:
        raise BacktestInputError("公告覆盖noticeIds超过读取上限")
    ids = [_short_text(item, "公告覆盖noticeId", 96) for item in raw_ids]
    if len(ids) != len(set(ids)):
        raise BacktestInputError("公告覆盖noticeId重复")
    return {
        "source": "cninfo",
        "queryStartDate": query_start,
        "queryEndDate": query_end,
        "pagesRead": pages_read,
        "terminalPage": True,
        "noticeIds": ids,
    }


def _canonical_price_validation(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"detectedDates", "pairs"}:
        raise BacktestInputError("行情价差复核证据字段无效")
    raw_dates = value.get("detectedDates")
    if not isinstance(raw_dates, Sequence) or isinstance(raw_dates, (str, bytes)):
        raise BacktestInputError("行情异常日期必须是列表")
    if len(raw_dates) > 5_000:
        raise BacktestInputError("行情异常日期超过读取上限")
    dates = [_date_text(item, "行情异常日期") for item in raw_dates]
    if dates != sorted(set(dates)):
        raise BacktestInputError("行情异常日期必须唯一并按日期排序")
    raw_pairs = value.get("pairs")
    if not isinstance(raw_pairs, Sequence) or isinstance(raw_pairs, (str, bytes)):
        raise BacktestInputError("行情价差复核对必须是列表")
    if len(raw_pairs) > 5_000:
        raise BacktestInputError("行情价差复核对超过读取上限")
    pairs: list[dict[str, Any]] = []
    seen_ex_dates: set[str] = set()
    for raw_pair in raw_pairs:
        pair_fields = {
            "exDate",
            "previousDate",
            "rawPrevious",
            "rawCurrent",
            "qfqPrevious",
            "qfqCurrent",
        }
        if not isinstance(raw_pair, Mapping) or set(raw_pair) != pair_fields:
            raise BacktestInputError("行情价差复核对字段无效")
        ex_date = _date_text(raw_pair.get("exDate"), "价差除权日")
        previous_date = _date_text(raw_pair.get("previousDate"), "价差前一交易日")
        if previous_date >= ex_date or ex_date in seen_ex_dates:
            raise BacktestInputError("行情价差复核日期重复或顺序无效")
        seen_ex_dates.add(ex_date)
        prices: dict[str, dict[str, str]] = {}
        for name in ("rawPrevious", "rawCurrent", "qfqPrevious", "qfqCurrent"):
            raw_ohlc = raw_pair.get(name)
            if not isinstance(raw_ohlc, Mapping) or set(raw_ohlc) != {
                "open",
                "high",
                "low",
                "close",
            }:
                raise BacktestInputError("行情价差复核OHLC字段无效")
            prices[name] = {
                field_name: _positive_price(raw_ohlc.get(field_name))
                for field_name in ("open", "high", "low", "close")
            }
        pairs.append({"exDate": ex_date, "previousDate": previous_date, **prices})
    pairs.sort(key=lambda pair: pair["exDate"])
    return {"detectedDates": dates, "pairs": pairs}


def _positive_price(value: Any) -> str:
    price = _decimal_text(value, "复核行情价格")
    if price <= 0:
        raise BacktestInputError("复核行情价格必须大于零")
    return value


def _canonical_event(raw: Any, *, symbol: str, start: str, end: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != _EVENT_FIELDS:
        raise BacktestInputError("现金分红事件字段不完整或包含未知字段")
    event_symbol = _canonical_symbol(raw.get("symbol"))
    if event_symbol != symbol:
        raise BacktestInputError("现金分红事件标的与快照标的不一致")
    action_id = _short_text(raw.get("actionId"), "现金分红actionId", _MAX_ID_CHARS)
    notice_id = _short_text(raw.get("noticeId"), "现金分红noticeId", 96)
    published = _date_text(raw.get("publishedDate"), "公告日期")
    record = _date_text(raw.get("recordDate"), "登记日")
    ex_date = _date_text(raw.get("exDate"), "除权日")
    payment = _date_text(raw.get("paymentDate"), "派息日")
    if not (published <= record < ex_date <= payment):
        raise BacktestInputError("现金分红公告、登记、除权和派息日期顺序冲突")
    if not (start <= record <= end or start <= ex_date <= end):
        raise BacktestInputError("现金分红事件与回测行情覆盖范围不相交")
    if record >= start:
        _validate_tax_effective_period(event_symbol, record)

    cash = _decimal_text(raw.get("cashPerShare"), "每股现金红利")
    if cash <= 0 or cash > _MAX_CASH_PER_SHARE:
        raise BacktestInputError("每股现金红利数值超出支持范围")
    stock_ratio = _decimal_text(raw.get("stockDividendRatio"), "送股比例")
    capitalization_ratio = _decimal_text(raw.get("capitalizationRatio"), "转增比例")
    if stock_ratio != 0:
        raise BacktestInputError("当前账本不支持送股，不能推定新增股份")
    if capitalization_ratio != 0:
        raise BacktestInputError("当前账本不支持转增，不能推定新增股份")

    title = _short_text(raw.get("title"), "公告标题", _MAX_TITLE_CHARS)
    if "实施" not in title or not any(
        marker in title for marker in ("分红", "权益分派", "利润分配", "现金红利")
    ):
        raise BacktestInputError("现金分红公告必须是正式实施方案")
    source_url = raw.get("sourceUrl")
    safe_url = official_pdf.validate_official_pdf_url(source_url)
    if not safe_url:
        raise BacktestInputError("现金分红来源必须是官方白名单PDF")
    url_parts = urlsplit(safe_url)
    source_date = (
        url_parts.path.split("/")[2] if len(url_parts.path.split("/")) > 2 else ""
    )
    if source_date != published:
        raise BacktestInputError("现金分红来源PDF日期与公告日期不一致")
    pdf_hash = _hash_text(raw.get("pdfSha256"), "现金分红PDF摘要")
    pages = raw.get("evidencePages")
    if not isinstance(pages, Sequence) or isinstance(pages, (str, bytes)):
        raise BacktestInputError("现金分红证据页格式无效")
    if not 1 <= len(pages) <= _MAX_EVIDENCE_PAGES:
        raise BacktestInputError("现金分红证据页数量超出范围")
    canonical_pages: list[dict[str, Any]] = []
    seen_pages: set[int] = set()
    for raw_page in pages:
        if not isinstance(raw_page, Mapping) or set(raw_page) != _PAGE_FIELDS:
            raise BacktestInputError("现金分红证据页字段无效")
        page_number = raw_page.get("page")
        if type(page_number) is not int or not 1 <= page_number <= 1_000:
            raise BacktestInputError("现金分红证据页页码无效")
        if page_number in seen_pages:
            raise BacktestInputError("现金分红证据页重复")
        seen_pages.add(page_number)
        excerpt = _short_text(
            raw_page.get("excerpt"), "现金分红证据摘录", _MAX_EXCERPT_CHARS
        )
        excerpt_hash = _hash_text(raw_page.get("excerptSha256"), "现金分红证据摘要")
        actual_excerpt_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
        if excerpt_hash != actual_excerpt_hash:
            raise BacktestInputError("现金分红证据摘录摘要与内容不匹配")
        canonical_pages.append(
            {
                "page": page_number,
                "excerpt": excerpt,
                "excerptSha256": excerpt_hash,
            }
        )
    canonical_pages.sort(key=lambda page: page["page"])
    return {
        "symbol": event_symbol,
        "actionId": action_id,
        "noticeId": notice_id,
        "publishedDate": published,
        "sourceUrl": safe_url,
        "pdfSha256": pdf_hash,
        "title": title,
        "recordDate": record,
        "exDate": ex_date,
        "paymentDate": payment,
        "cashPerShare": _decimal_canonical(cash),
        "stockDividendRatio": _decimal_canonical(stock_ratio),
        "capitalizationRatio": _decimal_canonical(capitalization_ratio),
        "evidencePages": canonical_pages,
    }


def _canonical_symbol(value: Any) -> str:
    if not isinstance(value, str):
        raise BacktestInputError("现金分红快照A股标的无效")
    try:
        return market.normalize_a_share_symbol(value)
    except (market.MarketDataError, TypeError, ValueError) as exc:
        raise BacktestInputError("现金分红快照A股标的无效") from exc


def _date_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise BacktestInputError(f"{label}必须是YYYY-MM-DD日期")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise BacktestInputError(f"{label}无效") from exc
    if parsed.isoformat() != value:
        raise BacktestInputError(f"{label}格式无效")
    return value


def _decimal_text(value: Any, label: str) -> Decimal:
    if not isinstance(value, str) or not _DECIMAL_RE.fullmatch(value):
        raise BacktestInputError(f"{label}必须是非负十进制字符串")
    try:
        return Decimal(value)
    except Exception as exc:  # Decimal can reject malformed context-specific input.
        raise BacktestInputError(f"{label}无效") from exc


def _decimal_canonical(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _short_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise BacktestInputError(f"{label}无效")
    text = value.strip()
    if (
        not text
        or len(text) > maximum
        or any(ord(char) < 32 or ord(char) == 127 for char in text)
    ):
        raise BacktestInputError(f"{label}无效")
    return text


def _hash_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.lower()):
        raise BacktestInputError(f"{label}必须是SHA-256摘要")
    return value.lower()


def _validate_tax_effective_period(symbol: str, record_date: str) -> None:
    record = date.fromisoformat(record_date)
    if symbol.startswith("bj"):
        if not _BSE_POLICY_START <= record <= _BSE_POLICY_END:
            raise BacktestInputError("北交所现金分红税制有效期尚未覆盖该登记日")
    elif record < _POLICY_START:
        raise BacktestInputError("沪深现金分红税制有效期尚未覆盖该登记日")


def _month_anniversary(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    last_day = (next_month - date.resolution).day
    return date(year, month, min(value.day, last_day))


def _tax_rate(acquired: date, sold: date) -> Decimal:
    if acquired > sold:
        raise BacktestInputError("卖出日期早于股份取得日期")
    if sold > _month_anniversary(acquired, 12):
        return Decimal(0)
    if sold > _month_anniversary(acquired, 1):
        return Decimal("0.10")
    return Decimal("0.20")


@dataclass
class _Lot:
    acquired: date
    shares: int
    dividend_rights: dict[str, int] = field(default_factory=dict)


@dataclass
class _DividendState:
    event: dict[str, Any]
    entitlement_in_window: bool = True
    captured: bool = False
    entitled_shares: int = 0
    gross_amount: Decimal = Decimal(0)
    recognized: bool = False
    paid: bool = False
    tax_payable: Decimal = Decimal(0)
    tax_assessed: Decimal = Decimal(0)
    tax_paid: Decimal = Decimal(0)

    @property
    def event_id(self) -> str:
        return self.event["actionId"]

    @property
    def cash_per_share(self) -> Decimal:
        return Decimal(self.event["cashPerShare"])


class DividendLedger:
    """A-share cash-dividend entitlements and deferred tax on FIFO disposals.

    Calls are made once per simulated trading session in this order:
    ``open_session``; actual filled ``buy``/``sell`` trades; ``close_session``.
    The trading engine remains responsible for T+1 availability and executions.
    """

    def __init__(self, symbol: str, artifact: Mapping[str, Any]) -> None:
        self.symbol = _canonical_symbol(symbol)
        self.artifact = validate_cash_dividend_artifact(
            artifact, expected_symbol=self.symbol
        )
        self.rule_version = self.artifact["ruleVersion"]
        self.artifact_hash = self.artifact["artifactHash"]
        self._events = [
            _DividendState(
                event=dict(event),
                entitlement_in_window=(
                    event["recordDate"] >= self.artifact["coverageStartDate"]
                ),
            )
            for event in self.artifact["events"]
        ]
        self._event_by_id = {state.event_id: state for state in self._events}
        self._lots: list[_Lot] = []
        self._active_session: date | None = None
        self._last_closed_session: date | None = None

    @property
    def receivable(self) -> Decimal:
        return sum(
            (
                state.gross_amount
                for state in self._events
                if state.recognized and not state.paid
            ),
            Decimal(0),
        )

    @property
    def tax_payable(self) -> Decimal:
        return sum((state.tax_payable for state in self._events), Decimal(0))

    @property
    def tax_total(self) -> Decimal:
        return sum((state.tax_assessed for state in self._events), Decimal(0))

    @property
    def dividends_total(self) -> Decimal:
        return sum(
            (state.gross_amount for state in self._events if state.recognized),
            Decimal(0),
        )

    def open_session(self, day: str) -> Decimal:
        """Recognize ex-date receivables without adding spendable cash."""

        session = self._session_date(day)
        if self._active_session is not None:
            raise BacktestInputError("上一交易日尚未收盘")
        if (
            self._last_closed_session is not None
            and session <= self._last_closed_session
        ):
            raise BacktestInputError("现金分红账本交易日必须严格递增")
        for state in self._events:
            if not state.entitlement_in_window:
                continue
            record = date.fromisoformat(state.event["recordDate"])
            ex_date = date.fromisoformat(state.event["exDate"])
            payment = date.fromisoformat(state.event["paymentDate"])
            if record < session and not state.captured:
                raise BacktestInputError("行情跳过现金分红登记日，持仓权益无法确定")
            if ex_date < session and not state.recognized:
                raise BacktestInputError("行情跳过现金分红除权日，应收款无法确定")
            if payment < session and not state.paid:
                raise BacktestInputError("行情跳过现金分红派息日，现金到账无法确定")
            if ex_date == session:
                if not state.captured:
                    raise BacktestInputError("现金分红除权前未记录登记日持仓")
                state.gross_amount = state.cash_per_share * state.entitled_shares
                state.recognized = True
        self._active_session = session
        return Decimal(0)

    def buy(self, day: str, shares: int) -> None:
        """Add a filled share lot; board quantity and T+1 rules belong to engine."""

        session = self._require_active_session(day)
        quantity = self._quantity(shares)
        self._lots.append(_Lot(acquired=session, shares=quantity))

    def sell(self, day: str, shares: int) -> Decimal:
        """Consume FIFO lots and return tax immediately due for already-paid rights."""

        session = self._require_active_session(day)
        remaining = self._quantity(shares)
        held = sum(lot.shares for lot in self._lots)
        if remaining > held:
            raise BacktestInputError("卖出股数超过现金分红账本持仓")
        cash_tax = Decimal(0)
        for lot in self._lots:
            if remaining == 0:
                break
            take = min(remaining, lot.shares)
            for event_id, right_shares in tuple(lot.dividend_rights.items()):
                entitled_sale = min(take, right_shares)
                if entitled_sale <= 0:
                    continue
                state = self._event_by_id[event_id]
                _validate_tax_effective_period(self.symbol, state.event["recordDate"])
                if self.symbol.startswith("bj") and session > _BSE_POLICY_END:
                    raise BacktestInputError(
                        "北交所现金分红税制有效期尚未覆盖该卖出日期"
                    )
                rate = _tax_rate(lot.acquired, session)
                tax = state.cash_per_share * entitled_sale * rate
                state.tax_assessed += tax
                if state.paid:
                    state.tax_paid += tax
                    cash_tax += tax
                else:
                    state.tax_payable += tax
                new_right_shares = right_shares - entitled_sale
                if new_right_shares:
                    lot.dividend_rights[event_id] = new_right_shares
                else:
                    del lot.dividend_rights[event_id]
            lot.shares -= take
            remaining -= take
        self._lots = [lot for lot in self._lots if lot.shares]
        return cash_tax

    def close_session(self, day: str) -> Decimal:
        """Capture record-date net holdings and release due dividend cash."""

        session = self._require_active_session(day)
        cash_delta = Decimal(0)
        for state in self._events:
            if not state.entitlement_in_window:
                continue
            if date.fromisoformat(state.event["recordDate"]) == session:
                if state.captured:
                    raise BacktestInputError("现金分红登记日重复入账")
                state.captured = True
                state.entitled_shares = sum(lot.shares for lot in self._lots)
                for lot in self._lots:
                    if lot.shares:
                        lot.dividend_rights[state.event_id] = lot.shares
            if date.fromisoformat(state.event["paymentDate"]) == session:
                if not state.recognized:
                    raise BacktestInputError("现金分红到账前尚未确认应收款")
                if state.tax_payable > state.gross_amount:
                    raise BacktestInputError("现金分红待扣税额超过应收款")
                cash_delta += state.gross_amount - state.tax_payable
                state.tax_paid += state.tax_payable
                state.tax_payable = Decimal(0)
                state.paid = True
        self._last_closed_session = session
        self._active_session = None
        return cash_delta

    def audit(self) -> dict[str, Any]:
        """Return a bounded, reproducible ledger projection for a frozen run."""

        return {
            "schemaVersion": 1,
            "ruleVersion": self.rule_version,
            "artifactHash": self.artifact_hash,
            "symbol": self.symbol,
            "settlementRounding": "unverified_decimal_exact",
            "receivable": _amount_text(self.receivable),
            "taxPayable": _amount_text(self.tax_payable),
            "taxTotal": _amount_text(self.tax_total),
            "dividendsTotal": _amount_text(self.dividends_total),
            "events": [
                {
                    "actionId": state.event_id,
                    "noticeId": state.event["noticeId"],
                    "publishedDate": state.event["publishedDate"],
                    "sourceUrl": state.event["sourceUrl"],
                    "pdfSha256": state.event["pdfSha256"],
                    "title": state.event["title"],
                    "recordDate": state.event["recordDate"],
                    "exDate": state.event["exDate"],
                    "paymentDate": state.event["paymentDate"],
                    "cashPerShare": state.event["cashPerShare"],
                    "ledgerApplied": state.entitlement_in_window,
                    "recordCaptured": state.captured,
                    "entitledShares": state.entitled_shares,
                    "grossAmount": _amount_text(state.gross_amount),
                    "exRecognized": state.recognized,
                    "paymentComplete": state.paid,
                    "taxPayable": _amount_text(state.tax_payable),
                    "taxTotal": _amount_text(state.tax_assessed),
                    "taxPaid": _amount_text(state.tax_paid),
                }
                for state in self._events
            ],
            "lots": [
                {
                    "acquiredDate": lot.acquired.isoformat(),
                    "shares": lot.shares,
                    "dividendRights": dict(sorted(lot.dividend_rights.items())),
                }
                for lot in self._lots
            ],
        }

    @staticmethod
    def _session_date(value: str) -> date:
        _date_text(value, "账本交易日")
        return date.fromisoformat(value)

    @staticmethod
    def _quantity(value: int) -> int:
        if type(value) is not int or value <= 0:
            raise BacktestInputError("账本成交股数必须是正整数")
        return value

    def _require_active_session(self, day: str) -> date:
        session = self._session_date(day)
        if self._active_session is None:
            raise BacktestInputError("必须先开市再登记账本成交")
        if session != self._active_session:
            raise BacktestInputError("账本成交日与当前交易日不一致")
        return session


def _amount_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." not in text:
        return text + ".00"
    whole, fractional = text.split(".", 1)
    return whole + "." + fractional.rstrip("0").ljust(2, "0")


__all__ = [
    "CASH_DIVIDEND_RULE_V1",
    "DividendLedger",
    "freeze_cash_dividend_artifact",
    "validate_cash_dividend_artifact",
]
