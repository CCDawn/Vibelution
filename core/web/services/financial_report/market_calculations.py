"""Verify explicitly named market calculations from one complete Turn snapshot.

Only values that can be recomputed from the same successful daily candle
payload are returned as exact report-text spans. This deliberately does not
infer trading calendars or authorize arbitrary values that happen to match.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from zoneinfo import ZoneInfo

from core.web.services.financial_report.conclusion_figures import (
    _AMOUNT,
    _CLAIM_DATE,
    _FINANCIAL_SOURCE_URL,
    _HIGH_RISK_CLAIM,
    _SENTENCE_BOUNDARY,
    _amount_decimal,
    _conclusion_spans,
    _contains_other_stock,
    _contains_quote_date,
    _contains_quote_identity,
    _market_quote_payload,
    _paragraph_spans,
    _visible_report_text,
    _without_code,
)

_SUCCESSFUL_TOOL_STATUSES = {"completed", "success"}
_MAX_TOOL_OUTPUT_CHARS = 8_000
_MAX_CANDLES = 120
_REQUEST_LIMIT_MESSAGE = "已按请求数量或输出长度限制保留最新 K 线。"
_PRICE_PRECISION = Decimal("0.01")
_PERCENT_PRECISION = Decimal("0.01")
_NUMBER = r"(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d+)?"
_ISO_DATE = r"\d{4}-\d{2}-\d{2}"
_PRICE_UNIT = r"(?:CNY|RMB|HKD|USD|港元|美元|元)(?:\s*/\s*(?:股|share))?"
_MA_CLAIM = re.compile(
    rf"(?<![A-Za-z0-9])(?P<label>(?:MA\s*(?P<ma_window>5|10|20)|"
    rf"(?P<days_window>5|10|20)\s*日(?:移动)?均线))"
    rf"(?:\*\*)?\s*(?:为|是|[:：=])?\s*"
    rf"(?:\*\*)?(?P<number>[+-]?{_NUMBER})\s*(?P<unit>{_PRICE_UNIT})"
    rf"(?:\*\*)?",
    re.IGNORECASE,
)
_RETURN_LABEL = r"(?:区间(?:收益率|收益|涨跌幅|涨幅)|收益率|涨幅)"
_RETURN_CLAIMS = (
    re.compile(
        rf"(?P<start_date>{_ISO_DATE})\s*(?:至|到)\s*(?P<end_date>{_ISO_DATE})"
        rf"\s*(?:的)?\s*(?P<label>{_RETURN_LABEL})\s*(?:为|是|[:：=])?\s*"
        rf"(?P<number>[+-]?{_NUMBER})\s*(?P<unit>[%％])",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<label>{_RETURN_LABEL})\s*[（(]?\s*(?P<start_date>{_ISO_DATE})"
        rf"\s*(?:至|到)\s*(?P<end_date>{_ISO_DATE})\s*[）)]?\s*"
        rf"(?:为|是|[:：=])?\s*(?P<number>[+-]?{_NUMBER})\s*(?P<unit>[%％])",
        re.IGNORECASE,
    ),
)
_MARKET_METADATA = {
    "CN": {
        "currency": "CNY",
        "adjustment": "qfq",
        "root_price_unit": "元",
        "quote_price_unit": "CNY/share",
        "volume_column": "volumeLots",
        "time_zone": "Asia/Shanghai",
    },
    "HK": {
        "currency": "HKD",
        "adjustment": "raw",
        "root_price_unit": "HKD/share",
        "quote_price_unit": "HKD/share",
        "volume_column": "volume",
        "time_zone": "Asia/Hong_Kong",
    },
    "US": {
        "currency": "USD",
        "adjustment": "raw",
        "root_price_unit": "USD/share",
        "quote_price_unit": "USD/share",
        "volume_column": "volume",
        "time_zone": "America/New_York",
    },
}
_TICKER_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?P<ticker>[A-Z][A-Z0-9]{1,4}(?:[.-][A-Z0-9]{1,4})?)(?![A-Za-z0-9])"
)
_NON_TICKER_TOKENS = {
    "ADR", "AI", "AMEX", "API", "BSE", "CAGR", "CAPEX", "CEO", "CN",
    "CNY", "CPU", "DCF", "DPS", "EBITDA", "EPS", "ESG", "ETF", "EUR",
    "EV", "FCF", "GAAP", "GBP", "GDP", "GPU", "HK", "HKD", "HKEX",
    "IFRS", "IRR", "JPY", "LLM", "LSE", "MA", "MA5", "MA10", "MA20",
    "MOM", "NASDAQ", "NAV", "NPV", "NSE", "NYSE", "OPEX", "PB", "PE",
    "PMI", "PPI", "QOQ", "RMB", "ROA", "ROE", "SSE", "SZSE", "TTM",
    "USD", "US", "WACC", "YTD", "YOY",
}


def market_calculation_spans(
    report_text: str,
    records: list[tuple[str, str, str]],
) -> list[tuple[int, int]]:
    """Return only conclusion amounts verified by one same-Turn market result."""

    conclusions = _conclusion_spans(report_text)
    if not conclusions:
        return []

    snapshots = _unique_complete_snapshots(records)
    if len(snapshots) != 1:
        return []
    snapshot = snapshots[0]
    quote = snapshot["quote"]
    if not _report_has_single_quote_context(report_text, quote):
        return []

    kept: set[tuple[int, int]] = set()
    for start, end in conclusions:
        chunk = report_text[start:end]
        for paragraph_start, paragraph_end in _paragraph_spans(
            chunk, split_list_items=True
        ):
            paragraph = chunk[paragraph_start:paragraph_end]
            clean = _without_code(paragraph)
            base = start + paragraph_start

            for match in _MA_CLAIM.finditer(clean):
                window = int(match.group("ma_window") or match.group("days_window"))
                closes = [row[1] for row in snapshot["rows"][-window:]]
                if len(closes) != window:
                    continue
                value = _quantized_mean(closes)
                if value is None or not _claim_is_safe(
                    clean,
                    match,
                    quote_date=quote["date"],
                    quote_symbol=quote["symbol"],
                ):
                    continue
                if not _claim_matches(
                    match.group("number"), value, snapshot["currency"], match.group("unit")
                ):
                    continue
                amount = _amount_span(clean, match.start("number"))
                if amount is not None:
                    kept.add((base + amount[0], base + amount[1]))

            for pattern in _RETURN_CLAIMS:
                for match in pattern.finditer(clean):
                    value = _range_return(
                        snapshot["rows"], match.group("start_date"), match.group("end_date")
                    )
                    if value is None or not _claim_is_safe(
                        clean, match, quote_symbol=quote["symbol"]
                    ):
                        continue
                    if not _claim_matches(match.group("number"), value, "percent", match.group("unit")):
                        continue
                    amount = _amount_span(clean, match.start("number"))
                    if amount is not None:
                        kept.add((base + amount[0], base + amount[1]))
    return sorted(kept)


def _unique_complete_snapshots(
    records: list[tuple[str, str, str]],
) -> list[dict]:
    snapshots: dict[tuple, dict] = {}
    for name, output, tool_status in records:
        if (
            name != "financial_market_snapshot_tool"
            or tool_status.strip().lower() not in _SUCCESSFUL_TOOL_STATUSES
            or len(output) > _MAX_TOOL_OUTPUT_CHARS
        ):
            continue
        snapshot = _complete_snapshot(output)
        if snapshot is None:
            continue
        snapshots[snapshot["signature"]] = snapshot
    return list(snapshots.values())


def _complete_snapshot(output: str) -> dict | None:
    try:
        payload = json.loads(output)
    except (json.JSONDecodeError, TypeError, ValueError, UnicodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("ok") is not True
        or str(payload.get("status") or "").strip().lower() not in {"ok", "partial"}
        or payload.get("period") != "day"
        or payload.get("source") != "腾讯财经"
        or payload.get("candleError") not in (None, "")
    ):
        return None

    quote = _market_quote_payload(output)
    if quote is None:
        return None
    symbol = quote["symbol"]
    market_code = "CN" if symbol[:2].lower() in {"sh", "sz", "bj"} else symbol[:2].upper()
    metadata = _MARKET_METADATA.get(market_code)
    raw_quote = payload.get("quote")
    if metadata is None or not isinstance(raw_quote, dict):
        return None
    if (
        str(payload.get("ticker") or "").casefold() != symbol.casefold()
        or str(payload.get("marketCode") or "").upper() != market_code
        or str(raw_quote.get("marketCode") or "").upper() != market_code
        or str(payload.get("currency") or "").upper() != metadata["currency"]
        or str(raw_quote.get("currency") or "").upper() != metadata["currency"]
        or payload.get("adjustment") != metadata["adjustment"]
        or payload.get("priceUnit") != metadata["root_price_unit"]
        or raw_quote.get("priceUnit") != metadata["quote_price_unit"]
        or raw_quote.get("marketTimeZone") != metadata["time_zone"]
    ):
        return None

    quote_timestamp_text = raw_quote.get("timestamp")
    if not isinstance(quote_timestamp_text, str):
        return None
    try:
        quote_timestamp = datetime.fromisoformat(
            quote_timestamp_text.strip().replace("Z", "+00:00")
        )
        if quote_timestamp.tzinfo is None:
            return None
        market_quote_date = quote_timestamp.astimezone(
            ZoneInfo(metadata["time_zone"])
        ).date().isoformat()
    except (KeyError, OSError, OverflowError, TypeError, ValueError):
        return None
    if market_quote_date != quote["date"]:
        return None

    candles = payload.get("candles")
    expected_columns = ["date", "open", "close", "high", "low", metadata["volume_column"]]
    if not isinstance(candles, dict) or candles.get("columns") != expected_columns:
        return None
    rows = candles.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_CANDLES:
        return None
    requested = _count(payload.get("requestedLimit"))
    available = _count(payload.get("availableCandleCount"))
    returned = _count(payload.get("returnedCandleCount"))
    omitted = _count(payload.get("omittedCandleCount"))
    request_window_count = (
        min(requested, available)
        if requested is not None and available is not None
        else None
    )
    payload_status = str(payload.get("status") or "").strip().lower()
    message = payload.get("message")
    if (
        requested is None
        or not 1 <= requested <= _MAX_CANDLES
        or available is None
        or returned is None
        or omitted is None
        or request_window_count is None
        or returned != request_window_count
        or len(rows) != request_window_count
        or omitted != available - returned
    ):
        return None
    if payload_status == "partial":
        if (
            requested >= available
            or omitted <= 0
            or message != _REQUEST_LIMIT_MESSAGE
        ):
            return None
    elif payload_status != "ok" or omitted != 0 or message not in (None, ""):
        return None

    parsed_rows = []
    previous_date = None
    for raw_row in rows:
        row = _parse_candle(raw_row)
        if row is None or (previous_date is not None and row[0] <= previous_date):
            return None
        previous_date = row[0]
        parsed_rows.append(row)
    if parsed_rows[-1][0].isoformat() != quote["date"]:
        return None

    signature = (
        symbol.casefold(),
        market_code,
        metadata["currency"],
        metadata["adjustment"],
        quote["date"],
        quote["price"],
        quote.get("changePercent"),
        quote.get("peRatio"),
        quote.get("pbRatio"),
        tuple(parsed_rows),
    )
    return {
        "signature": signature,
        "quote": quote,
        "currency": metadata["currency"],
        "rows": parsed_rows,
    }


def _count(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _parse_candle(value: object) -> tuple[date, Decimal] | None:
    if not isinstance(value, list) or len(value) != 6:
        return None
    raw_date = value[0]
    if not isinstance(raw_date, str):
        return None
    try:
        candle_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
    except (TypeError, ValueError, OverflowError):
        return None
    if candle_date.isoformat() != raw_date:
        return None
    numbers = [_decimal_number(item) for item in value[1:]]
    if any(item is None for item in numbers):
        return None
    opening, close, high, low, volume = numbers
    if (
        opening <= 0
        or close <= 0
        or high <= 0
        or low <= 0
        or high < max(opening, close, low)
        or low > min(opening, close, high)
        or volume < 0
    ):
        return None
    return candle_date, close


def _decimal_number(value: object) -> Decimal | None:
    if type(value) not in (int, float):
        return None
    try:
        if not math.isfinite(value):
            return None
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return None
    return result if result.is_finite() else None


def _quantized_mean(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    try:
        with localcontext() as context:
            context.prec = 28
            return (sum(values, Decimal(0)) / Decimal(len(values))).quantize(
                _PRICE_PRECISION, rounding=ROUND_HALF_UP
            )
    except (InvalidOperation, ArithmeticError):
        return None


def _range_return(rows: list[tuple[date, Decimal]], start_text: str, end_text: str) -> Decimal | None:
    try:
        start = date.fromisoformat(start_text)
        end = date.fromisoformat(end_text)
    except (TypeError, ValueError, OverflowError):
        return None
    if start >= end:
        return None
    closes = {day: close for day, close in rows}
    first = closes.get(start)
    last = closes.get(end)
    if first is None or last is None or first <= 0:
        return None
    try:
        with localcontext() as context:
            context.prec = 28
            return (((last - first) / first) * Decimal(100)).quantize(
                _PERCENT_PRECISION, rounding=ROUND_HALF_UP
            )
    except (InvalidOperation, ArithmeticError):
        return None


def _claim_matches(number_text: str, expected: Decimal, currency: str, unit: str) -> bool:
    value = _amount_decimal(number_text)
    if value is None or abs(value.as_tuple().exponent) > 2:
        return False
    if currency == "percent":
        if unit not in {"%", "％"}:
            return False
    else:
        from core.web.services.financial_report.conclusion_figures import _currency_for_unit

        if _currency_for_unit(unit) != currency:
            return False
    try:
        return value.quantize(_PRICE_PRECISION, rounding=ROUND_HALF_UP) == expected
    except (InvalidOperation, ArithmeticError):
        return False


def _amount_span(text: str, start: int) -> tuple[int, int] | None:
    amount = _AMOUNT.match(text, start)
    if amount is None or amount.start() != start:
        return None
    return amount.start(), amount.end()


def _claim_is_safe(
    paragraph: str,
    match: re.Match[str],
    *,
    quote_date: str | None = None,
    quote_symbol: str,
) -> bool:
    start, end = match.span()
    sentence_start = 0
    sentence_end = len(paragraph)
    for boundary in _SENTENCE_BOUNDARY.finditer(paragraph):
        if boundary.end() <= start:
            sentence_start = boundary.end()
        elif boundary.start() >= end:
            sentence_end = boundary.start()
            break
    sentence = paragraph[sentence_start:sentence_end]
    visible = _visible_report_text(sentence)
    if _HIGH_RISK_CLAIM.search(visible):
        return False
    if _contains_other_ticker(visible, quote_symbol):
        return False
    prefix = paragraph[sentence_start:start].rstrip()
    tail = paragraph[end:sentence_end].lstrip()
    if re.search(r"[+\-−×*/÷=＝≈]\s*$", prefix):
        return False
    if re.match(r"[+\-−×*/÷=＝≈]\s*\d", tail):
        return False
    if quote_date is not None:
        dates = {item.group("date") for item in _CLAIM_DATE.finditer(visible)}
        if any(value not in {quote_date, quote_date[5:]} for value in dates):
            return False
    return True


def _contains_other_ticker(text: str, quote_symbol: str) -> bool:
    symbol = str(quote_symbol or "").strip().casefold()
    allowed = {symbol}
    if symbol[:2] in {"sh", "sz", "bj", "hk", "us"}:
        allowed.add(symbol[2:])
    for match in _TICKER_TOKEN.finditer(text):
        ticker = match.group("ticker").upper()
        if ticker in _NON_TICKER_TOKENS or ticker.casefold() in allowed:
            continue
        return True
    return False


def _report_has_single_quote_context(report_text: str, quote: dict) -> bool:
    visible = _visible_report_text(report_text)
    sources = {
        match.group(0)
        for match in _FINANCIAL_SOURCE_URL.finditer(_without_code(report_text))
    }
    if (
        not _contains_quote_identity(visible, quote)
        or _contains_other_stock(_without_calculation_claims(visible), quote)
        or sources != {quote["sourceUrl"]}
    ):
        return False
    return any(
        quote["sourceUrl"] in _without_code(report_text[left:right])
        and _contains_quote_date(report_text[left:right], quote["date"])
        for left, right in _paragraph_spans(report_text)
    )


def _without_calculation_claims(text: str) -> str:
    """Keep currency codes inside a formula from looking like US tickers."""

    characters = list(text)
    patterns = (*_RETURN_CLAIMS, _MA_CLAIM)
    for pattern in patterns:
        for match in pattern.finditer(text):
            characters[match.start() : match.end()] = " " * (match.end() - match.start())
    return "".join(characters)
