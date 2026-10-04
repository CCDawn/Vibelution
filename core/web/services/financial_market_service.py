"""Read-only A-share market data. Tencent is the source, never the model.

Public quotes can be delayed. Quote timestamps, forward-adjusted OHLC, lots
(100 shares) and yuan units survive the API boundary. No account/order access.
"""

import json
import math
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class MarketDataError(ValueError):
    pass


class StockNotFound(MarketDataError):
    pass


_CACHE: OrderedDict[tuple, tuple[float, object]] = OrderedDict()
_LOCK = threading.Lock()
_MARKETS = {"sh": "上交所", "sz": "深交所", "bj": "北交所"}


def normalize_symbol(value: str) -> str:
    value = str(value).strip().lower()
    if re.fullmatch(r"\d{6}", value):
        value = ("sh" if value[0] == "6" else "sz" if value[0] in "03" else "bj") + value
    if not re.fullmatch(r"(?:sh6\d{5}|sz[03]\d{5}|bj[489]\d{5})", value):
        raise MarketDataError("请输入有效的 A 股代码")
    return value


def _read(url: str, encoding: str = "utf-8") -> str:
    try:
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
        while len(_CACHE) > 64:
            _CACHE.popitem(last=False)
    return result


def _number(raw: str, *, optional: bool = False):
    try:
        value = float(raw)
        if math.isfinite(value):
            return value
    except (ValueError, TypeError):
        pass
    if optional:
        return None
    raise MarketDataError("行情源返回了无效数值")


def parse_quote(raw: str, symbol: str) -> dict:
    match = re.search(r'v_' + re.escape(symbol) + r'="([^"]*)"', raw)
    values = match.group(1).split("~") if match else []
    if len(values) < 47 or not values[1] or values[2] != symbol[2:]:
        raise StockNotFound("未找到这只股票")
    try:
        stamp = datetime.strptime(values[30], "%Y%m%d%H%M%S").isoformat() + "+08:00"
    except ValueError as exc:
        raise MarketDataError("行情源未提供有效时间") from exc
    price = _number(values[3])
    if price <= 0:
        raise MarketDataError("股票暂无有效报价")
    return {
        "symbol": symbol, "ticker": values[2], "name": values[1],
        "market": _MARKETS[symbol[:2]], "price": price,
        "previousClose": _number(values[4]), "open": _number(values[5]),
        "high": _number(values[33]), "low": _number(values[34]),
        "change": _number(values[31]), "changePercent": _number(values[32]),
        "volumeLots": _number(values[6]),
        "turnoverYuan": _number(values[37]) * 10_000,
        "peRatio": _number(values[39], optional=True),
        "pbRatio": _number(values[46], optional=True),
        "totalMarketCapYuan": (_number(values[45], optional=True) or 0) * 100_000_000 or None,
        "timestamp": stamp,
    }


def parse_candles(raw: str, symbol: str, period: str) -> list[dict]:
    try:
        payload = json.loads(raw)
        if payload.get("code") != 0:
            raise ValueError("provider error")
        data = payload["data"][symbol]
        # Never label unadjusted fallback prices as forward-adjusted data.
        rows = data.get("qfq" + period)
        if not isinstance(rows, list) or not rows:
            raise ValueError("forward-adjusted candles unavailable")
        candles = []
        for row in rows[-120:]:
            datetime.strptime(row[0], "%Y-%m-%d")
            opening, closing, high, low, volume = [_number(v) for v in row[1:6]]
            if low <= 0 or high < max(opening, closing) or low > min(opening, closing) or volume < 0:
                raise ValueError("invalid OHLC")
            candles.append({"date": row[0], "open": opening, "close": closing,
                            "high": high, "low": low, "volumeLots": volume})
        if any(a["date"] >= b["date"] for a, b in zip(candles, candles[1:])):
            raise ValueError("unordered candles")
        return candles
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        raise MarketDataError("K 线数据无效，请重试") from exc


def search_stocks(query: str) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    if len(query) > 40 or not re.fullmatch(r"[\w\s.*\-]+", query):
        raise MarketDataError("请输入股票名称、拼音或代码")
    if re.fullmatch(r"(?:(?:sh|sz|bj))?\d{6}", query.lower()):
        symbol = normalize_symbol(query)
        stock = _cached(("quote", symbol), 30, lambda: parse_quote(_read("https://qt.gtimg.cn/q=" + symbol, "gb18030"), symbol))
        return [{key: stock[key] for key in ("symbol", "ticker", "name", "market")}]

    def read():
        raw = _read("https://smartbox.gtimg.cn/s3/?" + urlencode({"q": query, "t": "all"}), "gb18030")
        # The provider returns an assignment; extract data, never eval JavaScript.
        match = re.search(r'v_hint="([^"\r\n]*)"', raw)
        text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), match.group(1)) if match else ""
        stocks, seen = [], set()
        for item in text.split("^"):
            fields = item.split("~")
            if len(fields) < 5 or fields[4] != "GP-A":
                continue
            try:
                symbol = normalize_symbol(fields[0] + fields[1])
            except MarketDataError:
                continue
            if symbol not in seen:
                seen.add(symbol)
                stocks.append({"symbol": symbol, "ticker": fields[1], "name": fields[2], "market": _MARKETS[fields[0]]})
        return stocks[:10]
    return _cached(("search", query), 300, read)


def get_stock_snapshot(symbol: str, period: str = "day") -> dict:
    symbol = normalize_symbol(symbol)
    if period not in {"day", "week", "month"}:
        raise MarketDataError("不支持的 K 线周期")
    stock = _cached(("quote", symbol), 30, lambda: parse_quote(_read("https://qt.gtimg.cn/q=" + symbol, "gb18030"), symbol))
    candle_error = ""
    try:
        candles = _cached(("candles", symbol, period), 300, lambda: parse_candles(
            _read("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?" + urlencode({"param": f"{symbol},{period},,,120,qfq"})), symbol, period))
    except MarketDataError as exc:
        candles, candle_error = [], str(exc)
    return {"stock": stock, "candles": candles, "period": period, "adjustment": "qfq",
            "source": "腾讯财经", "sourceUrl": "https://gu.qq.com/" + symbol + "/gp",
            "fetchedAt": datetime.now(timezone.utc).isoformat(), "candleError": candle_error,
            "notice": "公开行情可能延迟；K 线前复权，成交量单位为手"}
