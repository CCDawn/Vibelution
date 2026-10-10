"""Bounded Sina A-share daily history and qfq-factor adapter.

The K-line endpoint is requested at scale 240 with a fixed 1,023-bar ceiling.
Provider wrappers are parsed as delimiters around strict JSON; no JavaScript is
evaluated.
The endpoint's ``volume`` field is in shares. The shared market parser expects
CN provider volume in lots, so this adapter divides by 100 before returning
the provider-row shape consumed by ``data._parse_rows``.
"""

from __future__ import annotations

import json
import re
from bisect import bisect_right
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from urllib.parse import urlencode

from core.web.services import financial_market_service as market

from .transport import HistoricalReadError, read_historical

_KLINE_URL = "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData"
_QFQ_URL = "https://finance.sina.com.cn/realstock/company/{symbol}/qfq.js"
_SCALE = "240"
_MAX_BARS = 1023
_PRICE_QUANTUM = Decimal("0.01")
_JSONP_ASSIGNMENT = re.compile(r"(?:(?:var|let|const)\s+)?([A-Za-z_$][A-Za-z0-9_$]*)")
_KLINE_PREAMBLE = "/*<script>location.href='//sina.com';</script>*/"


def _error(message: str):
    from .data import BacktestDataError

    return BacktestDataError(message)


def _context(symbol: str, start: date, end: date, adjustment: str) -> str:
    return f"{symbol} {start.isoformat()}至{end.isoformat()} · {adjustment}"


def _read(url: str, context: str) -> str:
    try:
        return read_historical(url)
    except HistoricalReadError as exc:
        raise _error(f"新浪历史行情读取失败（{context}）：{exc}") from exc


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"非标准JSON常量：{value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("重复JSON字段")
        result[key] = value
    return result


def _parse_jsonp(raw: str, context: str) -> Any:
    if not isinstance(raw, str) or not raw or len(raw) > 1_000_000:
        raise _error(f"新浪历史行情响应长度无效（{context}）")
    text = raw.lstrip("\ufeff\r\n\t ")
    marker = text.find("=(")
    if marker < 0:
        raise _error(f"新浪历史行情JSONP边界无效（{context}）")

    prefix = text[:marker].strip()
    if prefix:
        if prefix != _KLINE_PREAMBLE:
            matched = _JSONP_ASSIGNMENT.fullmatch(prefix)
            if matched is None:
                raise _error(f"新浪历史行情JSONP回调名无效（{context}）")

    payload_text = text[marker + 2 :].lstrip()
    try:
        payload, consumed = json.JSONDecoder(
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_object,
        ).raw_decode(payload_text)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _error(f"新浪历史行情JSON内容无效（{context}）") from exc
    if payload_text[consumed:].strip() != ");":
        raise _error(f"新浪历史行情JSONP边界无效（{context}）")
    return payload


def _parse_json_assignment(raw: str, context: str, *, expected_assignment: str) -> Any:
    """Parse Sina's qfq variable assignment without evaluating JavaScript."""
    if not isinstance(raw, str) or not raw or len(raw) > 1_000_000:
        raise _error(f"新浪复权因子响应长度无效（{context}）")
    text = raw.lstrip("\ufeff\r\n\t ")
    match = re.match(
        r"(?:(?:var|let|const)\s+)?([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*",
        text,
    )
    if match is None or match.group(1) != expected_assignment:
        raise _error(f"新浪复权因子身份无效（{context}）")

    value_source = text[match.end() :].lstrip()
    try:
        payload, consumed = json.JSONDecoder(
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_object,
        ).raw_decode(value_source)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _error(f"新浪复权因子JSON内容无效（{context}）") from exc

    trailing = value_source[consumed:].strip()
    if trailing.startswith(";"):
        trailing = trailing[1:].strip()
    if trailing and re.fullmatch(r"/\*[\s\S]*\*/", trailing) is None:
        raise _error(f"新浪复权因子赋值边界无效（{context}）")
    return payload


def _decimal(value: Any, field: str, context: str) -> Decimal:
    if isinstance(value, bool) or value is None or isinstance(value, (dict, list)):
        raise _error(f"新浪历史行情{field}格式无效（{context}）")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise _error(f"新浪历史行情{field}格式无效（{context}）") from exc
    if not number.is_finite():
        raise _error(f"新浪历史行情{field}必须是有限数值（{context}）")
    return number


def _day(value: Any, context: str) -> date:
    if not isinstance(value, str):
        raise _error(f"新浪历史行情日期格式无效（{context}）")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise _error(f"新浪历史行情日期格式无效（{context}）") from exc
    if parsed.isoformat() != value:
        raise _error(f"新浪历史行情日期格式无效（{context}）")
    return parsed


def _parse_bars(raw: str, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
    context = _context(symbol, start, end, "raw")
    payload = _parse_jsonp(raw, context)
    if not isinstance(payload, list) or len(payload) > _MAX_BARS:
        raise _error(f"新浪历史日K行数或格式无效（{context}）")

    bars: list[dict[str, Any]] = []
    previous_day: date | None = None
    for row in payload:
        if not isinstance(row, dict):
            raise _error(f"新浪历史日K行格式无效（{context}）")
        day = _day(row.get("day"), context)
        if previous_day is not None and day <= previous_day:
            raise _error(f"新浪历史日K存在重复日期或乱序（{context}）")
        previous_day = day

        opening = _decimal(row.get("open"), "open", context)
        high = _decimal(row.get("high"), "high", context)
        low = _decimal(row.get("low"), "low", context)
        closing = _decimal(row.get("close"), "close", context)
        volume = _decimal(row.get("volume"), "volume", context)
        if volume != volume.to_integral_value():
            raise _error(f"新浪历史日K成交量必须是整数股（{context}）")
        if (
            min(opening, high, low, closing) <= 0
            or high < max(opening, closing)
            or low > min(opening, closing)
            or volume < 0
        ):
            raise _error(f"新浪历史日K OHLC或成交量校验失败（{context}）")
        if start <= day <= end:
            bars.append(
                {
                    "date": day.isoformat(),
                    "open": opening,
                    "high": high,
                    "low": low,
                    "close": closing,
                    "volume": volume,
                }
            )
    return bars


def _parse_factors(raw: str, symbol: str, start: date, end: date) -> list[tuple[date, Decimal]]:
    context = _context(symbol, start, end, "qfq factor")
    payload = _parse_json_assignment(
        raw,
        context,
        expected_assignment=f"{symbol}qfq",
    )
    if not isinstance(payload, dict):
        raise _error(f"新浪复权因子映射格式无效（{context}）")
    rows = payload.get("data")
    total = payload.get("total")
    if (
        not isinstance(rows, list)
        or not rows
        or len(rows) > 20_000
        or type(total) is not int
        or total != len(rows)
    ):
        raise _error(f"新浪复权因子覆盖不完整（{context}）")

    by_date: dict[date, Decimal] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"d", "f"}:
            raise _error(f"新浪复权因子行格式无效（{context}）")
        factor_day = _day(row.get("d"), context)
        factor = _decimal(row.get("f"), "qfq factor", context)
        if factor <= 0 or factor_day in by_date:
            raise _error(f"新浪复权因子日期或数值无效（{context}）")
        by_date[factor_day] = factor

    return sorted(by_date.items())


def _apply_qfq(
    bars: list[dict[str, Any]], factors: list[tuple[date, Decimal]], context: str
) -> list[dict[str, Any]]:
    if not bars:
        return []
    factor_dates = [item[0] for item in factors]
    if not factor_dates or factor_dates[0] > date.fromisoformat(bars[0]["date"]):
        raise _error(f"新浪复权因子缺少行情窗口之前的有效基准（{context}）")

    adjusted: list[dict[str, Any]] = []
    for bar in bars:
        bar_day = date.fromisoformat(bar["date"])
        factor_index = bisect_right(factor_dates, bar_day) - 1
        if factor_index < 0:
            raise _error(f"新浪复权因子无法覆盖交易日（{context}）")
        factor = factors[factor_index][1]
        row = dict(bar)
        try:
            for field in ("open", "high", "low", "close"):
                row[field] = (bar[field] / factor).quantize(
                    _PRICE_QUANTUM, rounding=ROUND_HALF_UP
                )
        except (InvalidOperation, ZeroDivisionError) as exc:
            raise _error(f"新浪复权OHLC计算失败（{context}）") from exc
        adjusted.append(row)
    return adjusted


def _provider_rows(bars: list[dict[str, Any]]) -> list[list[str]]:
    result: list[list[str]] = []
    for bar in bars:
        # data._parse_rows reuses the existing CN parser, whose wire contract is
        # lots. Preserve Sina's share count by staging fractional lots here.
        volume_lots = bar["volume"] / Decimal(100)
        result.append(
            [
                bar["date"],
                format(bar["open"], "f"),
                format(bar["close"], "f"),
                format(bar["high"], "f"),
                format(bar["low"], "f"),
                format(volume_lots, "f"),
            ]
        )
    return result


def fetch_window(symbol: str, start: date, end: date, adjustment: str) -> list[list[str]]:
    """Return one bounded, date-filtered Sina raw or qfq window.

    This adapter supports A-share symbol normalization only and deliberately
    does not translate between legacy and current Beijing Stock Exchange codes.
    Older windows outside Sina's trailing 1,023-bar response fail through the
    caller's ordinary coverage and index-calendar checks.
    """
    from .data import BacktestDataError, _CALENDAR_SYMBOL

    if adjustment not in {"none", "qfq"}:
        raise BacktestDataError("新浪复权模式无效")
    if type(start) is not date or type(end) is not date or start > end:
        raise BacktestDataError("新浪历史行情日期窗口无效")
    if symbol == _CALENDAR_SYMBOL:
        normalized = symbol
    else:
        try:
            normalized = market.normalize_a_share_symbol(symbol)
        except market.MarketDataError as exc:
            raise BacktestDataError(f"新浪A股代码无效：{exc}") from exc

    context = _context(normalized, start, end, adjustment)
    params = urlencode(
        {"symbol": normalized, "scale": _SCALE, "ma": "no", "datalen": str(_MAX_BARS)}
    )
    bars = _parse_bars(
        _read(f"{_KLINE_URL}?{params}", context), normalized, start, end
    )
    if adjustment == "qfq" and bars:
        factors = _parse_factors(
            _read(_QFQ_URL.format(symbol=normalized), context), normalized, start, end
        )
        bars = _apply_qfq(bars, factors, context)
    return _provider_rows(bars)
