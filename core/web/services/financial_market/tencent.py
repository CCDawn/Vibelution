"""Tencent public-quote symbol, payload, unit, and timestamp conventions."""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone


class MarketDataError(ValueError):
    """Input or public market data could not be interpreted safely."""


class StockNotFound(MarketDataError):
    """Tencent did not return a quote for a valid canonical symbol."""


_CN_MARKETS = {"sh": "上交所", "sz": "深交所", "bj": "北交所"}
_CURRENCY = {"CN": "CNY", "HK": "HKD", "US": "USD"}
_PRICE_UNIT = {"CN": "CNY/share", "HK": "HKD/share", "US": "USD/share"}
_MARKET_TIME_ZONE = {
    "CN": "Asia/Shanghai",
    "HK": "Asia/Hong_Kong",
    "US": "America/New_York",
}
_CN_SYMBOL_RE = re.compile(r"(?:sh6\d{5}|sz[03]\d{5}|bj[489]\d{5})")
_HK_SYMBOL_RE = re.compile(r"hk\d{5}")
_US_SYMBOL_RE = re.compile(r"us[A-Z][A-Z0-9.-]{0,9}")
_US_EXCHANGE_SUFFIX_RE = re.compile(r"\.(?:OQ|N|AM|PK|PNK|NYSE|NASDAQ)$", re.IGNORECASE)


def market_code_for_symbol(symbol: str) -> str:
    value = str(symbol).strip()
    prefix = value[:2].lower()
    if prefix in _CN_MARKETS:
        return "CN"
    if prefix == "hk":
        return "HK"
    if prefix == "us":
        return "US"
    raise MarketDataError("请输入有效的股票代码")


def normalize_symbol(value: str) -> str:
    raw = str(value).strip()
    lowered = raw.lower()

    if re.fullmatch(r"\d{6}", lowered):
        lowered = ("sh" if lowered[0] == "6" else "sz" if lowered[0] in "03" else "bj") + lowered
    elif lowered.startswith("hk"):
        code = lowered[2:]
        if code.isdigit() and 1 <= len(code) <= 5:
            lowered = "hk" + code.zfill(5)
    elif lowered.startswith("us"):
        ticker = raw[2:].strip()
        if not ticker:
            raise MarketDataError("请输入有效的美股代码")
        ticker = _US_EXCHANGE_SUFFIX_RE.sub("", ticker).upper()
        lowered = "us" + ticker

    if _CN_SYMBOL_RE.fullmatch(lowered):
        return lowered
    if _HK_SYMBOL_RE.fullmatch(lowered):
        return lowered
    if _US_SYMBOL_RE.fullmatch(lowered):
        return lowered
    raise MarketDataError("请输入有效的 A 股、港股或美股代码")


def normalize_a_share_symbol(value: str) -> str:
    """Strict paper-ledger normalizer; reject HK/US before broad normalization."""
    raw = str(value).strip().lower()
    if raw.startswith(("hk", "us")):
        raise MarketDataError("模拟交易账本仅支持 A 股")
    try:
        normalized = normalize_symbol(raw)
    except MarketDataError as exc:
        raise MarketDataError("模拟交易账本仅支持 A 股") from exc
    if market_code_for_symbol(normalized) != "CN":
        raise MarketDataError("模拟交易账本仅支持 A 股")
    return normalized


def market_identity(market_code: str, symbol: str, ticker: str | None = None) -> dict[str, str]:
    if market_code == "CN":
        display = _CN_MARKETS[symbol[:2]]
    elif market_code == "HK":
        display = "港交所"
    elif market_code == "US":
        source_ticker = str(ticker or symbol[2:]).upper()
        if source_ticker.endswith(".OQ"):
            display = "NASDAQ"
        elif source_ticker.endswith(".N"):
            display = "NYSE"
        elif source_ticker.endswith(".AM"):
            display = "NYSE American"
        else:
            display = "美股"
    else:
        raise MarketDataError("不支持的市场")
    return {
        "marketCode": market_code,
        "currency": _CURRENCY[market_code],
        "marketTimeZone": _MARKET_TIME_ZONE[market_code],
        "market": display,
    }


def _provider_us_base_ticker(value: str) -> str:
    return _US_EXCHANGE_SUFFIX_RE.sub("", str(value).strip()).upper()


def _number(raw: object, *, optional: bool = False) -> float | None:
    try:
        value = float(raw)
        if math.isfinite(value):
            return value
    except (ValueError, TypeError, OverflowError):
        pass
    if optional:
        return None
    raise MarketDataError("行情源返回了无效数值")


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    first = date(year, month, 1)
    first_match = 1 + (weekday - first.weekday()) % 7
    return date(year, month, first_match + (occurrence - 1) * 7)


def _new_york_offset(local_time: datetime) -> timedelta:
    # Tencent provides wall-clock exchange time without an offset. Apply the
    # post-2007 US rule explicitly so Windows does not need an external tzdata
    # package. Ambiguous/nonexistent DST transition hours are rejected.
    year = local_time.year
    if year < 2007:
        raise MarketDataError("美股报价时间超出可验证的时区规则范围")
    spring = _nth_weekday(year, 3, 6, 2)
    fall = _nth_weekday(year, 11, 6, 1)
    day = local_time.date()
    if day == spring and local_time.hour == 2:
        raise MarketDataError("美股报价时间落在夏令时切换空档")
    if day == fall and local_time.hour == 1:
        raise MarketDataError("美股报价时间落在夏令时重复时段")
    daylight = spring < day < fall
    if day == spring:
        daylight = local_time.hour >= 3
    elif day == fall:
        daylight = local_time.hour < 1
    return timedelta(hours=-4 if daylight else -5)


def _parse_timestamp(value: str, market_code: str) -> str:
    formats = {
        "CN": ("%Y%m%d%H%M%S", timedelta(hours=8)),
        "HK": ("%Y/%m/%d %H:%M:%S", timedelta(hours=8)),
        "US": ("%Y-%m-%d %H:%M:%S", None),
    }
    try:
        local_time = datetime.strptime(value, formats[market_code][0])
    except (KeyError, TypeError, ValueError) as exc:
        raise MarketDataError("行情源未提供可识别的交易所时间") from exc
    offset = formats[market_code][1]
    if market_code == "US":
        offset = _new_york_offset(local_time)
    assert offset is not None
    return local_time.replace(tzinfo=timezone(offset)).isoformat(timespec="seconds")


def _decode_search_text(raw: str) -> str:
    return re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda match: chr(int(match.group(1), 16)),
        raw,
    )


def _symbol_from_search_fields(fields: list[str], market_code: str) -> dict[str, str] | None:
    if len(fields) < 5:
        return None
    provider_market = fields[0].strip().lower()
    provider_code = fields[1].strip()
    name = fields[2].strip()
    security_type = fields[4].strip().upper()
    if not provider_code or not name:
        return None
    if market_code == "CN":
        if provider_market not in _CN_MARKETS or security_type != "GP-A":
            return None
        try:
            symbol = normalize_symbol(provider_market + provider_code)
        except MarketDataError:
            return None
        ticker = provider_code
    elif market_code == "HK":
        if provider_market != "hk" or security_type not in {"GP", "GP-H"} or not provider_code.isdigit():
            return None
        try:
            symbol = normalize_symbol("hk" + provider_code.zfill(5))
        except MarketDataError:
            return None
        ticker = symbol[2:]
    else:
        if provider_market != "us" or security_type != "GP":
            return None
        provider_ticker = provider_code.upper()
        base_ticker = _provider_us_base_ticker(provider_ticker)
        try:
            symbol = normalize_symbol("us" + base_ticker)
        except MarketDataError:
            return None
        ticker = provider_ticker
    identity = market_identity(market_code, symbol, ticker)
    return {
        "symbol": symbol,
        "ticker": ticker,
        "name": name,
        "market": identity["market"],
        "marketCode": identity["marketCode"],
        "currency": identity["currency"],
        "marketTimeZone": identity["marketTimeZone"],
    }


def parse_search_results(raw: str, market_code: str, limit: int = 10) -> list[dict[str, str]]:
    match = re.search(r'v_hint="([^"\r\n]*)"', raw)
    text = _decode_search_text(match.group(1)) if match else ""
    stocks: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in text.split("^"):
        row = _symbol_from_search_fields(item.split("~"), market_code)
        if row is None or row["symbol"] in seen:
            continue
        seen.add(row["symbol"])
        stocks.append(row)
        if len(stocks) >= limit:
            break
    return stocks


def parse_quote(raw: str, symbol: str) -> dict:
    normalized = normalize_symbol(symbol)
    code = market_code_for_symbol(normalized)
    match = re.search(r"v_" + re.escape(normalized) + r'=\"([^\"]*)\"', raw)
    values = match.group(1).split("~") if match else []
    if len(values) < 47 or not values[1]:
        raise StockNotFound("未找到这只股票")
    ticker = values[2].strip()
    if code == "US":
        matches_symbol = _provider_us_base_ticker(ticker) == normalized[2:]
        if len(values) <= 35 or values[35].strip().upper() != "USD":
            raise MarketDataError("腾讯美股报价未声明 USD 计价")
    else:
        matches_symbol = ticker == normalized[2:]
    if not matches_symbol:
        raise StockNotFound("行情源返回的股票代码与请求不匹配")
    timestamp = _parse_timestamp(values[30], code)
    price = _number(values[3])
    previous_close = _number(values[4])
    opening = _number(values[5])
    high = _number(values[33])
    low = _number(values[34])
    change = _number(values[31])
    change_percent = _number(values[32])
    provider_volume = _number(values[6])
    if (
        price is None
        or price <= 0
        or provider_volume is None
        or provider_volume < 0
        or high < max(price, opening)
        or low > min(price, opening)
        or high < low
    ):
        raise MarketDataError("股票暂无有效报价")
    volume_shares = provider_volume * 100 if code == "CN" else provider_volume
    turnover_source = _number(values[37], optional=True)
    turnover = None
    if turnover_source is not None and turnover_source >= 0:
        turnover = turnover_source * 10_000 if code == "CN" else turnover_source
        if volume_shares > 0:
            turnover_per_share_value = turnover / (price * volume_shares)
            if not 0.05 <= turnover_per_share_value <= 20:
                turnover = None
    market_cap_source = _number(values[45], optional=True)
    market_cap = None
    if market_cap_source is not None and market_cap_source > 0:
        market_cap = market_cap_source * 100_000_000
    pe_ratio = _number(values[39], optional=True)
    pb_ratio = _number(values[46], optional=True) if code == "CN" else None
    identity = market_identity(code, normalized, ticker)
    return {
        "symbol": normalized,
        "ticker": ticker,
        "name": values[1],
        "market": identity["market"],
        "marketCode": code,
        "currency": identity["currency"],
        "marketTimeZone": identity["marketTimeZone"],
        "price": price,
        "priceUnit": _PRICE_UNIT[code],
        "previousClose": previous_close,
        "open": opening,
        "high": high,
        "low": low,
        "change": change,
        "changePercent": change_percent,
        "volume": volume_shares,
        "volumeUnit": "shares",
        "volumeLots": provider_volume if code == "CN" else None,
        "turnover": turnover,
        "turnoverYuan": turnover if code == "CN" else None,
        "peRatio": pe_ratio,
        "pbRatio": pb_ratio,
        "marketCap": market_cap,
        "totalMarketCapYuan": market_cap if code == "CN" else None,
        "timestamp": timestamp,
    }


def adjustment_for_market(market_code: str) -> str:
    return "qfq" if market_code == "CN" else "raw"


def parse_candles(raw: str, symbol: str, period: str) -> list[dict]:
    normalized = normalize_symbol(symbol)
    code = market_code_for_symbol(normalized)
    if period not in {"day", "week", "month"}:
        raise MarketDataError("不支持的 K 线周期")
    try:
        payload = json.loads(raw)
        if payload.get("code") != 0:
            raise ValueError("provider error")
        data = payload["data"][normalized]
        adjustment = adjustment_for_market(code)
        rows = data.get(("qfq" if adjustment == "qfq" else "") + period)
        if not isinstance(rows, list) or not rows:
            raise ValueError("requested candles unavailable")
        candles = []
        for row in rows[-120:]:
            datetime.strptime(row[0], "%Y-%m-%d")
            opening, closing, high, low, provider_volume = [
                _number(value) for value in row[1:6]
            ]
            if (
                None in (opening, closing, high, low, provider_volume)
                or min(opening, closing, high, low) <= 0
                or high < max(opening, closing)
                or low > min(opening, closing)
                or provider_volume < 0
            ):
                raise ValueError("invalid OHLC or volume")
            volume_shares = provider_volume * 100 if code == "CN" else provider_volume
            candles.append(
                {
                    "date": row[0],
                    "open": opening,
                    "close": closing,
                    "high": high,
                    "low": low,
                    "volume": volume_shares,
                    "volumeUnit": "shares",
                    "volumeLots": provider_volume if code == "CN" else None,
                }
            )
        if any(a["date"] >= b["date"] for a, b in zip(candles, candles[1:])):
            raise ValueError("unordered candles")
        return candles
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        if isinstance(exc, MarketDataError):
            raise
        raise MarketDataError("K 线数据无效，请重试") from exc
