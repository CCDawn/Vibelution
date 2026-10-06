"""Read-only public CN/HK/US stock search, quote, and OHLC service."""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from core.web.services.financial_market import tencent

MarketDataError = tencent.MarketDataError
StockNotFound = tencent.StockNotFound
normalize_symbol = tencent.normalize_symbol
normalize_a_share_symbol = tencent.normalize_a_share_symbol
market_code_for_symbol = tencent.market_code_for_symbol
parse_quote = tencent.parse_quote
parse_candles = tencent.parse_candles
adjustment_for_market = tencent.adjustment_for_market

_CACHE: OrderedDict[tuple, tuple[float, object]] = OrderedDict()
_LOCK = threading.Lock()
_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0
_CACHE_LIMIT = 64
_REQUEST_INTERVAL_SECONDS = 0.25


def _read(url: str, encoding: str = "utf-8") -> str:
    global _LAST_REQUEST_AT
    try:
        with _REQUEST_LOCK:
            wait = _REQUEST_INTERVAL_SECONDS - (time.monotonic() - _LAST_REQUEST_AT)
            if wait > 0:
                time.sleep(wait)
            _LAST_REQUEST_AT = time.monotonic()
        request = Request(url, headers={"User-Agent": "Vibelution/2 financial-research"})
        with urlopen(request, timeout=6) as response:
            body = response.read(1_000_001)
        if len(body) > 1_000_000:
            raise MarketDataError("行情数据超过读取上限")
        return body.decode(encoding)
    except MarketDataError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise MarketDataError("行情源暂时不可用，请重试") from exc


def _cached(key: tuple, ttl: int, read):
    with _LOCK:
        entry = _CACHE.get(key)
        if entry and time.monotonic() - entry[0] < ttl:
            _CACHE.move_to_end(key)
            return entry[1]
    result = read()
    with _LOCK:
        _CACHE[key] = (time.monotonic(), result)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
    return result


def _valid_market(value: str) -> str:
    market_code = str(value or "CN").strip().upper()
    if market_code not in {"CN", "HK", "US"}:
        raise MarketDataError("市场只能是 CN、HK 或 US")
    return market_code


def _direct_lookup_symbol(query: str, market_code: str) -> str | None:
    raw = query.strip()
    lowered = raw.lower()
    try:
        if market_code == "CN" and (
            re.fullmatch(r"\d{6}", lowered)
            or re.fullmatch(r"(?:sh|sz|bj)\w+", lowered)
        ):
            return normalize_symbol(raw)
        if market_code == "HK" and (
            re.fullmatch(r"\d{1,5}", lowered) or re.fullmatch(r"hk\d{1,5}", lowered)
        ):
            return normalize_symbol("hk" + lowered.removeprefix("hk"))
        if market_code == "US" and re.fullmatch(r"us[A-Za-z][A-Za-z0-9.\-]{0,9}", raw):
            return normalize_symbol(raw)
    except MarketDataError:
        return None
    return None


def _quote(symbol: str) -> dict:
    normalized = normalize_symbol(symbol)
    return _cached(
        ("quote", normalized),
        30,
        lambda: parse_quote(_read("https://qt.gtimg.cn/q=" + normalized, "gb18030"), normalized),
    )


def search_stocks(query: str, market: str = "CN") -> list[dict]:
    market_code = _valid_market(market)
    query = str(query or "").strip()
    if not query:
        return []
    if len(query) > 40 or not re.fullmatch(r"[\w\s.*\-]+", query):
        raise MarketDataError("请输入股票名称、拼音或代码")

    direct_symbol = _direct_lookup_symbol(query, market_code)
    if direct_symbol is not None:
        if market_code_for_symbol(direct_symbol) != market_code:
            return []
        stock = _quote(direct_symbol)
        return [
            {
                key: stock[key]
                for key in (
                    "symbol",
                    "ticker",
                    "name",
                    "market",
                    "marketCode",
                    "currency",
                    "marketTimeZone",
                )
            }
        ]

    def read():
        url = "https://smartbox.gtimg.cn/s3/?" + urlencode({"q": query, "t": "all"})
        raw = _read(url, "gb18030")
        return tencent.parse_search_results(raw, market_code, limit=10)

    return _cached(("search", market_code, query.casefold()), 300, read)


def get_stock_snapshot(symbol: str, period: str = "day") -> dict:
    normalized = normalize_symbol(symbol)
    market_code = market_code_for_symbol(normalized)
    if period not in {"day", "week", "month"}:
        raise MarketDataError("不支持的 K 线周期")
    stock = _quote(normalized)
    adjustment = tencent.adjustment_for_market(market_code)
    candle_error = ""
    try:
        candles = _cached(
            ("candles", normalized, period),
            300,
            lambda: parse_candles(
                _read(
                    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
                    + urlencode({"param": f"{normalized},{period},,,120,qfq"})
                ),
                normalized,
                period,
            ),
        )
    except MarketDataError as exc:
        candles, candle_error = [], str(exc)
    if market_code == "CN":
        notice = "公开行情可能延迟；A股K线前复权，成交量统一字段为股（旧字段为手）。"
    else:
        notice = f"公开行情可能延迟；{market_code} K线未复权，成交量单位为股。"
    return {
        "stock": stock,
        "candles": candles,
        "period": period,
        "adjustment": adjustment,
        "source": "腾讯财经",
        "sourceUrl": "https://gu.qq.com/" + normalized + "/gp",
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "candleError": candle_error,
        "notice": notice,
    }
