"""Bounded public A-share benchmark-index context from Tencent Finance."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode


class IndexDataError(ValueError):
    """The public index response could not be validated safely."""


INDEX_NAMES: dict[str, str] = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    "sh000300": "沪深300",
    "sh000905": "中证500",
}

SOURCE_NAME = "腾讯财经"
_SOURCE_URLS = {
    symbol: f"https://gu.qq.com/{symbol}/gp" for symbol in INDEX_NAMES
}
_QUOTE_URL = "https://qt.gtimg.cn/q=" + ",".join(INDEX_NAMES)
_MAX_LIMIT = 20
_MIN_LIMIT = 2
_CN_TZ = timezone(timedelta(hours=8))


def _number(value: object) -> float:
    if isinstance(value, bool):
        raise IndexDataError("行情源返回无效数值")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise IndexDataError("行情源返回无效数值") from exc
    if not math.isfinite(result):
        raise IndexDataError("行情源返回非有限数值")
    return result


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _iso_date(value: object) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("daily index date must use YYYY-MM-DD")
    return date.fromisoformat(value)


def _quote_time(value: str) -> str:
    if not re.fullmatch(r"\d{14}", value):
        raise IndexDataError("行情源未提供可识别的指数报价时间")
    try:
        local = datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=_CN_TZ)
    except ValueError as exc:
        raise IndexDataError("行情源未提供可识别的指数报价时间") from exc
    return local.isoformat(timespec="seconds")


def _parse_quote(raw: str, symbol: str) -> dict:
    matches = list(re.finditer(r"v_" + re.escape(symbol) + r'=\"([^\"]*)\"', raw))
    if len(matches) != 1:
        raise IndexDataError("行情源未唯一声明请求的指数代码")
    fields = matches[0].group(1).split("~")
    expected_code = symbol[2:]
    if len(fields) < 35 or fields[2].strip() != expected_code:
        raise IndexDataError("行情源返回的指数代码与请求不匹配")

    price = _number(fields[3])
    previous_close = _number(fields[4])
    opening = _number(fields[5])
    high = _number(fields[33])
    low = _number(fields[34])
    change = _number(fields[31])
    change_percent = _number(fields[32])
    if (
        min(price, previous_close, opening, high, low) <= 0
        or high < max(price, opening)
        or low > min(price, opening)
        or high < low
        or not math.isclose(change, price - previous_close, abs_tol=0.03)
        or not math.isclose(
            change_percent,
            (price - previous_close) / previous_close * 100,
            abs_tol=0.03,
        )
    ):
        raise IndexDataError("指数报价 OHLC 或涨跌值无效")

    return {
        "price": price,
        "previousClose": previous_close,
        "change": change,
        "changePercent": change_percent,
        "open": opening,
        "high": high,
        "low": low,
        "timestamp": _quote_time(fields[30].strip()),
    }


def _parse_bars(raw: str, symbol: str, *, cutoff: date | None, limit: int) -> tuple[list[dict], int]:
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise ValueError("provider error")
        data = payload["data"]
        if not isinstance(data, dict) or symbol not in data:
            raise ValueError("requested index unavailable")
        rows = data[symbol].get("day")
        if not isinstance(rows, list) or not rows:
            raise ValueError("daily index data unavailable")

        candles: list[dict] = []
        rejected_future_rows = 0
        last_date: date | None = None
        for row in rows:
            if not isinstance(row, list) or len(row) < 5:
                raise ValueError("malformed daily index row")
            row_date = _iso_date(row[0])
            if cutoff is not None and row_date > cutoff:
                rejected_future_rows += 1
                continue
            if last_date is not None and row_date <= last_date:
                raise ValueError("unordered or duplicate daily index dates")
            opening, closing, high, low = (_number(value) for value in row[1:5])
            if (
                min(opening, closing, high, low) <= 0
                or high < max(opening, closing)
                or low > min(opening, closing)
                or high < low
            ):
                raise ValueError("invalid daily index OHLC")
            candles.append(
                {
                    "date": row_date.isoformat(),
                    "open": opening,
                    "close": closing,
                    "high": high,
                    "low": low,
                }
            )
            last_date = row_date
        candles = candles[-limit:]
        return candles, rejected_future_rows
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        if isinstance(exc, IndexDataError):
            raise
        raise IndexDataError("指数日线数据无效或不可用") from exc


def _daily_quote(candles: list[dict]) -> dict:
    latest = candles[-1]
    previous_close = candles[-2]["close"] if len(candles) >= 2 else None
    change = latest["close"] - previous_close if previous_close is not None else None
    change_percent = (
        change / previous_close * 100
        if change is not None and previous_close is not None and previous_close > 0
        else None
    )
    return {
        "price": latest["close"],
        "previousClose": previous_close,
        "change": change,
        "changePercent": change_percent,
        "open": latest["open"],
        "high": latest["high"],
        "low": latest["low"],
        "date": latest["date"],
    }


def _item_status(
    quote: dict | None,
    candles: list[dict],
    *,
    historical: bool,
    rejected_future_rows: int,
) -> str:
    if rejected_future_rows:
        return "partial"
    has_data = quote is not None or bool(candles)
    if not has_data:
        return "unavailable"
    quote_failed = not historical and quote is None
    candles_failed = not candles
    return "partial" if quote_failed or candles_failed else "available"


def _daily_url(symbol: str, *, cutoff: date | None, limit: int) -> str:
    end_date = cutoff.isoformat() if cutoff is not None else ""
    param = f"{symbol},day,,{end_date},{limit},none"
    return "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?" + urlencode(
        {"param": param}
    )


def get_index_context(
    *,
    cutoff: date | None = None,
    limit: int = 2,
    read: Callable,
    cached: Callable,
) -> dict:
    """Return bounded benchmark quotes and/or cutoff-safe daily index bars.

    Supplying ``cutoff`` is historical mode: it never requests the real-time
    quote endpoint and only includes daily rows on or before that date.
    """

    if type(limit) is not int or not _MIN_LIMIT <= limit <= _MAX_LIMIT:
        raise ValueError("指数日线 limit 必须在 2–20 之间")
    if cutoff is not None and type(cutoff) is not date:
        raise ValueError("cutoff 必须是 datetime.date")

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    historical = cutoff is not None
    quotes: dict[str, dict] = {}
    quote_errors: dict[str, str] = {}
    if not historical:
        try:
            raw = cached(
                ("index-quotes", tuple(INDEX_NAMES)),
                30,
                lambda: read(_QUOTE_URL, "gb18030"),
            )
            for symbol in INDEX_NAMES:
                try:
                    quotes[symbol] = _parse_quote(raw, symbol)
                except (IndexDataError, TypeError) as exc:
                    quote_errors[symbol] = str(exc) or "指数报价不可用"
        except (IndexDataError, OSError, TimeoutError, TypeError, ValueError, RuntimeError) as exc:
            for symbol in INDEX_NAMES:
                quote_errors[symbol] = str(exc) or "指数报价暂时不可用"

    items: list[dict] = []
    for symbol, name in INDEX_NAMES.items():
        candles: list[dict] = []
        rejected_future_rows = 0
        candles_error = ""
        try:
            url = _daily_url(symbol, cutoff=cutoff, limit=limit)
            raw = cached(
                ("index-candles", symbol, cutoff.isoformat() if cutoff else None, limit),
                300,
                lambda url=url: read(url),
            )
            candles, rejected_future_rows = _parse_bars(
                raw, symbol, cutoff=cutoff, limit=limit
            )
        except (IndexDataError, OSError, TimeoutError, TypeError, ValueError, RuntimeError) as exc:
            candles_error = str(exc) or "指数日线暂时不可用"

        quote = quotes.get(symbol)
        if candles and (historical or quote is None):
            quote = _daily_quote(candles)

        status = _item_status(
            quotes.get(symbol),
            candles,
            historical=historical,
            rejected_future_rows=rejected_future_rows,
        )
        # A live daily close can provide explicit context when the live quote
        # failed, but the item remains partial so the substitution is visible.
        basis = (
            "quote"
            if not historical and symbol in quotes
            else "daily_close"
            if quote is not None
            else None
        )
        item = {
            "symbol": symbol,
            "name": name,
            "status": status,
            "sourceUrl": _SOURCE_URLS[symbol],
            "candles": candles,
        }
        if basis is not None:
            item["basis"] = basis
        if quote is not None:
            item["quote"] = {
                key: value for key, value in quote.items() if value is not None
            }
        if not historical and symbol not in quotes:
            item["quoteError"] = quote_errors.get(symbol, "指数报价不可用")[:160]
        if candles_error:
            item["candlesError"] = candles_error[:160]
        if rejected_future_rows:
            item["rejectedFutureRows"] = rejected_future_rows
        items.append(item)

    statuses = {item["status"] for item in items}
    global_status = (
        "available"
        if statuses == {"available"}
        else "unavailable"
        if statuses == {"unavailable"}
        else "partial"
    )
    return {
        "status": global_status,
        "mode": "historical" if historical else "realtime",
        "requestedCutoff": cutoff.isoformat() if cutoff else None,
        "fetchedAt": fetched_at,
        "limit": limit,
        "source": SOURCE_NAME,
        "priceUnit": "points",
        "adjustment": "raw_index",
        "items": items,
    }


__all__ = ["INDEX_NAMES", "IndexDataError", "get_index_context"]
