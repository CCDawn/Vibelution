"""Bounded, read-only A-share quote and candle access for finance Agents.

This adapter delegates market access and caching to the existing financial
market service. Public quotes may be delayed and cached. The tool returns
daily, weekly, or monthly forward-adjusted candles, never minute data. Treat
``fetchedAt`` as this query's time; ``quote.timestamp`` and candle dates are
the provider's market-data times and may be historical.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone

from core.web.services import financial_market_service as market
from core.web.services import financial_research_service as research

MAX_RESULT_CHARS = 3_200
MAX_SCREEN_RESULT_CHARS = 6_000
_TICKER = re.compile(r"(?:\d{6}|sh6\d{5}|sz[03]\d{5}|bj[489]\d{5})\Z", re.IGNORECASE)
_CANDLE_COLUMNS = ["date", "open", "close", "high", "low", "volumeLots"]
_PROVIDER = "腾讯财经"
_SAFE_CANDLE_ERRORS = {
    "行情源暂时不可用，请重试",
    "K 线数据无效，请重试",
    "行情数据超过读取上限",
}


def _query_time() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _safe_text(value, fallback: str, limit: int) -> str:
    if (
        isinstance(value, str)
        and value.strip()
        and len(value) <= limit
        and not any(ord(char) < 32 for char in value)
    ):
        return value
    return fallback


def _unavailable(
    message: str,
    *,
    error_code: str = "market_data_unavailable",
    ticker: str | None = None,
    period: str | None = None,
    limit: int | None = None,
) -> str:
    payload = {
        "ok": False,
        "status": "unavailable",
        "message": message,
        "errorCode": error_code,
        "ticker": ticker,
        "requestedLimit": limit,
        "availableCandleCount": 0,
        "returnedCandleCount": 0,
        "omittedCandleCount": 0,
        "source": _PROVIDER,
        "sourceUrl": (
            f"https://gu.qq.com/{ticker}/gp" if ticker else None
        ),
        "fetchedAt": _query_time(),
        "quote": None,
        "period": period,
        "adjustment": "qfq",
        "priceUnit": "元",
        "volumeUnit": "手（1手=100股）",
        "candles": {"columns": _CANDLE_COLUMNS, "rows": []},
        "candleError": "",
    }
    try:
        return _encode(payload)
    except (TypeError, ValueError):
        # All fields above are fixed or validated primitives. Keep a final
        # bounded, valid JSON response if an unexpected encoder issue occurs.
        return _encode(
            {
                "ok": False,
                "status": "unavailable",
                "errorCode": "market_data_unavailable",
                "message": "行情暂不可用，请稍后重试。",
            }
        )


def _invalid_request(
    message: str,
    *,
    error_code: str = "invalid_request",
    ticker: str | None = None,
    limit=None,
) -> str:
    return _encode(
        {
            "ok": False,
            "status": "invalid_request",
            "message": message,
            "errorCode": error_code,
            "ticker": ticker,
            "requestedLimit": limit if type(limit) is int else None,
            "availableCandleCount": 0,
            "returnedCandleCount": 0,
            "omittedCandleCount": 0,
        }
    )


def _candle_row(value) -> list:
    if not isinstance(value, dict):
        raise ValueError("invalid candle")
    date = value.get("date")
    if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("invalid candle date")
    row = [date]
    for key in ("open", "close", "high", "low", "volumeLots"):
        number = value.get(key)
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise ValueError("invalid candle value")
        if not math.isfinite(number):
            raise ValueError("invalid candle value")
        row.append(number)
    return row


def financial_market_snapshot_tool(
    ticker: str, period: str = "day", limit: int = 20
) -> str:
    """Return a bounded public A-share quote and its latest forward-adjusted K lines.

    ``ticker`` must be a six-digit code or an exchange-prefixed code such as
    ``600519``, ``sh600519``, ``sz000001``, or ``bj430047``. ``period`` is ``day``, ``week``, or
    ``month``; ``limit`` is an integer from 1 through 120. This tool does not
    accept company names or search text. Quotes are public and may be delayed;
    service-level quote and candle caches may return earlier observations.
    Minute candles are not available. ``fetchedAt`` records query time, while
    ``quote.timestamp`` and candle dates retain the provider's data times.
    Prices are yuan; volume is lots (one lot is 100 shares). No account,
    portfolio, or order data is accessed.
    """
    if not isinstance(ticker, str):
        return _invalid_request(
            "ticker 必须为六位 A 股代码或带交易所前缀的代码。",
            error_code="invalid_ticker",
        )
    candidate = ticker.strip().lower()
    if not _TICKER.fullmatch(candidate):
        return _invalid_request(
            "ticker 必须为六位 A 股代码或带交易所前缀的代码。",
            error_code="invalid_ticker",
        )
    try:
        symbol = market.normalize_symbol(candidate)
    except Exception:
        return _invalid_request("ticker 不是有效的 A 股代码。", error_code="invalid_ticker")

    if not isinstance(period, str) or period not in {"day", "week", "month"}:
        return _invalid_request(
            "period 仅支持 day、week 或 month。",
            error_code="invalid_period",
            ticker=symbol,
            limit=limit,
        )
    if type(limit) is not int or not 1 <= limit <= 120:
        return _invalid_request(
            "limit 必须为 1 到 120 之间的整数。",
            error_code="invalid_limit",
            ticker=symbol,
        )

    try:
        snapshot = market.get_stock_snapshot(symbol, period)
    except market.StockNotFound:
        return _unavailable(
            "行情源未找到这只股票，本次未返回行情数据。",
            error_code="stock_not_found",
            ticker=symbol,
            period=period,
            limit=limit,
        )
    except market.MarketDataError:
        return _unavailable(
            "行情数据暂不可用，请稍后重试；本次未返回行情数据。",
            error_code="market_data_error",
            ticker=symbol,
            period=period,
            limit=limit,
        )
    except Exception:
        # Provider exceptions can contain internal tracebacks or request URLs.
        # Never include their raw text in an Agent-visible result.
        return _unavailable(
            "公开行情暂不可用，请稍后重试；本次未返回行情数据。",
            error_code="provider_error",
            ticker=symbol,
            period=period,
            limit=limit,
        )

    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("stock"), dict):
        return _unavailable(
            "行情源暂未返回有效报价，本次未返回行情数据。",
            error_code="invalid_market_response",
            ticker=symbol,
            period=period,
            limit=limit,
        )

    stock = snapshot["stock"]
    raw_candles = snapshot.get("candles")
    candle_error = bool(snapshot.get("candleError")) or not isinstance(raw_candles, list)
    try:
        candles = [_candle_row(candle) for candle in raw_candles] if isinstance(raw_candles, list) else []
    except (TypeError, ValueError, OverflowError):
        candles = []
        candle_error = True

    available = len(raw_candles) if isinstance(raw_candles, list) else 0
    chosen = candles[-limit:]
    source = _safe_text(snapshot.get("source"), _PROVIDER, 100)
    source_url = _safe_text(
        snapshot.get("sourceUrl"), f"https://gu.qq.com/{symbol}/gp", 512
    )
    fetched_at = _safe_text(snapshot.get("fetchedAt"), _query_time(), 64)
    raw_candle_error = snapshot.get("candleError")
    reported_candle_error = ""
    if candle_error:
        reported_candle_error = (
            raw_candle_error
            if isinstance(raw_candle_error, str) and raw_candle_error in _SAFE_CANDLE_ERRORS
            else "K 线数据暂不可用，报价仍可供参考。"
        )
    notice = (
        "公开报价可能延迟；仅提供日/周/月前复权 K 线，不含分钟数据。"
        "fetchedAt 为本次查询时间，quote.timestamp 与 K 线日期为数据源时间。"
    )

    def make_payload(rows: list[list]) -> dict:
        returned = len(rows)
        omitted = max(0, available - returned)
        clipped = omitted > 0
        status = "partial" if candle_error or clipped else "ok"
        if candle_error:
            message = reported_candle_error
        elif clipped:
            message = "已按请求数量或输出长度限制保留最新 K 线。"
        else:
            message = ""
        return {
            "ok": True,
            "status": status,
            "message": message,
            "ticker": symbol,
            "requestedLimit": limit,
            "availableCandleCount": available,
            "returnedCandleCount": returned,
            "omittedCandleCount": omitted,
            "source": source,
            "sourceUrl": source_url,
            "fetchedAt": fetched_at,
            "quote": stock,
            "period": period,
            "adjustment": "qfq",
            "priceUnit": "元",
            "volumeUnit": "手（1手=100股）",
            "candles": {"columns": _CANDLE_COLUMNS, "rows": rows},
            "candleError": reported_candle_error,
            "notice": notice,
        }

    try:
        payload = make_payload(chosen)
        encoded = _encode(payload)
        # Remove only the oldest selected rows; the newest provider candles
        # remain visible as the result is reduced to the character budget.
        while len(encoded) > MAX_RESULT_CHARS and chosen:
            chosen = chosen[1:]
            payload = make_payload(chosen)
            encoded = _encode(payload)
        if len(encoded) <= MAX_RESULT_CHARS:
            return encoded
    except (TypeError, ValueError, OverflowError):
        pass

    return _unavailable(
        "行情响应超过工具输出上限，未返回未经验证的数据。",
        error_code="response_too_large",
        ticker=symbol,
        period=period,
        limit=limit,
    )


_SCREEN_VALUE_BOUNDS = {
    "min_price": (0, 100_000_000),
    "max_price": (0, 100_000_000),
    "min_change_percent": (-100, 10_000),
    "max_change_percent": (-100, 10_000),
    "min_pe": (-10_000, 100_000),
    "max_pe": (-10_000, 100_000),
    "min_volume_lots": (0, 1_000_000_000_000_000),
    "min_pb": (-10_000, 100_000),
    "max_pb": (-10_000, 100_000),
    "min_turnover_yuan": (0, 1_000_000_000_000_000),
    "max_turnover_yuan": (0, 1_000_000_000_000_000),
}
_SCREEN_SORT_FIELDS = {
    "changePercent", "turnoverYuan", "price", "volumeLots", "peRatio", "pbRatio",
}
_SCREEN_CANDIDATE_FIELDS = (
    "symbol", "ticker", "name", "market", "price", "changePercent",
    "peRatio", "pbRatio", "volumeLots", "turnoverYuan", "timeOfDay",
)


def _screen_error(message: str, error_code: str) -> str:
    return _encode({
        "ok": False,
        "status": "unavailable" if error_code != "invalid_request" else "invalid_request",
        "message": message,
        "errorCode": error_code,
        "source": "新浪财经",
        "fetchedAt": _query_time(),
        "coverage": {"providerTotal": 0, "loaded": 0, "complete": False, "totalFiltered": 0},
        "returnedCount": 0,
        "items": [],
    })


def _screen_candidate(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    item: dict = {}
    for key in _SCREEN_CANDIDATE_FIELDS:
        value = raw.get(key)
        if key in {"symbol", "ticker", "name", "market", "timeOfDay"}:
            if value is not None and isinstance(value, str) and len(value) <= 100 and not any(ord(char) < 32 for char in value):
                item[key] = value
            elif key != "timeOfDay":
                return None
            else:
                item[key] = None
        elif value is None:
            item[key] = None
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            item[key] = value
        else:
            item[key] = None
    return item


def financial_market_screen_tool(
    *,
    min_price: float | None = None,
    max_price: float | None = None,
    min_change_percent: float | None = None,
    max_change_percent: float | None = None,
    min_pe: float | None = None,
    max_pe: float | None = None,
    min_volume_lots: float | None = None,
    min_pb: float | None = None,
    max_pb: float | None = None,
    min_turnover_yuan: float | None = None,
    max_turnover_yuan: float | None = None,
    sort_by: str = "changePercent",
    direction: str = "desc",
    limit: int = 15,
) -> str:
    """Return a bounded, read-only screen of the provider's Shanghai/Shenzhen/Beijing A-share universe.

    The provider does not guarantee a transaction date or market-cap unit. Its
    fetch time is kept separate from the provider's intraday time. Returned
    candidates and coverage always come from the fixed public-data service.
    """
    for key, (minimum, maximum) in _SCREEN_VALUE_BOUNDS.items():
        value = locals()[key]
        if value is None:
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < minimum
            or value > maximum
        ):
            return _screen_error("筛选条件超出支持范围。", "invalid_request")
    for lower_key, upper_key in (
        ("min_price", "max_price"),
        ("min_change_percent", "max_change_percent"),
        ("min_pe", "max_pe"),
        ("min_pb", "max_pb"),
        ("min_turnover_yuan", "max_turnover_yuan"),
    ):
        lower, upper = locals()[lower_key], locals()[upper_key]
        if lower is not None and upper is not None and lower > upper:
            return _screen_error("最小值不能大于最大值。", "invalid_request")
    if sort_by not in _SCREEN_SORT_FIELDS or direction not in {"asc", "desc"}:
        return _screen_error("不支持的排序方式。", "invalid_request")
    if type(limit) is not int or not 1 <= limit <= 20:
        return _screen_error("结果数量必须为 1 到 20。", "invalid_request")

    values = locals()
    criteria = {key: values[key] for key in _SCREEN_VALUE_BOUNDS}
    requested_filters = {key: value for key, value in criteria.items() if value is not None}
    try:
        result = research.screen_stocks(
            **criteria,
            sort_by=sort_by,
            direction=direction,
            page=1,
            page_size=limit,
        )
    except research.FinancialResearchInputError:
        return _screen_error("筛选条件无效，请核对最小值、最大值与单位。", "invalid_request")
    except research.FinancialResearchDataError:
        return _screen_error("公开股票池暂不可用，本次未返回筛选结果。", "provider_unavailable")
    except Exception:
        # Provider exceptions can contain URLs or local diagnostics.
        return _screen_error("公开股票池暂不可用，本次未返回筛选结果。", "provider_error")

    if not isinstance(result, dict) or not isinstance(result.get("coverage"), dict) or not isinstance(result.get("items"), list):
        return _screen_error("筛选服务未返回有效数据，本次未返回候选股票。", "invalid_response")
    coverage = result["coverage"]
    raw_items = result["items"][:limit]
    items = [candidate for raw in raw_items if (candidate := _screen_candidate(raw)) is not None]
    complete = coverage.get("complete") is True
    payload = {
        "ok": True,
        "status": "complete" if complete else "partial",
        "source": _safe_text(result.get("source"), "新浪财经", 100),
        "sourceUrl": _safe_text(result.get("sourceUrl"), "https://vip.stock.finance.sina.com.cn/mkt/#hs_a", 512),
        "fetchedAt": _safe_text(result.get("fetchedAt"), _query_time(), 64),
        "dataDate": result.get("dataDate") if isinstance(result.get("dataDate"), str) else None,
        "dataTime": result.get("dataTime") if isinstance(result.get("dataTime"), str) else None,
        "resultScope": "provider_universe" if complete else "loaded_subset",
        "coverage": {
            "providerTotal": coverage.get("providerTotal") if type(coverage.get("providerTotal")) is int else 0,
            "loaded": coverage.get("loaded") if type(coverage.get("loaded")) is int else 0,
            "complete": complete,
            "failedPages": [page for page in coverage.get("failedPages", []) if type(page) is int][:100]
            if isinstance(coverage.get("failedPages"), list) else [],
            "invalidRows": coverage.get("invalidRows") if type(coverage.get("invalidRows")) is int else 0,
            "duplicateRows": coverage.get("duplicateRows") if type(coverage.get("duplicateRows")) is int else 0,
            "totalFiltered": coverage.get("totalFiltered") if type(coverage.get("totalFiltered")) is int else 0,
        },
        "requestedFilters": requested_filters,
        "sortBy": sort_by,
        "direction": direction,
        "requestedLimit": limit,
        "returnedCount": len(items),
        "priceUnit": "元",
        "volumeUnit": "手（1手=100股）",
        "turnoverUnit": "元",
        "items": items,
        "notice": "来源只提供行情时分，未提供交易日期；抓取时间不代表行情日期。市值单位未核实，未用于筛选。",
    }
    try:
        encoded = _encode(payload)
        while len(encoded) > MAX_SCREEN_RESULT_CHARS and payload["items"]:
            payload["items"].pop()
            payload["returnedCount"] = len(payload["items"])
            encoded = _encode(payload)
        if len(encoded) <= MAX_SCREEN_RESULT_CHARS:
            return encoded
    except (TypeError, ValueError, OverflowError):
        pass
    return _screen_error("筛选结果超过工具输出上限，未返回未核验数据。", "response_too_large")
