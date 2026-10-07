"""Read-only market screening and cited stock research projections.

Tencent remains the quote authority used by the Finance workspace. Sina public
pages provide the broad A-share screen. Eastmoney provides news, ordinary
company notices, and reported financial indicators. The A-share annual report
on the stock page is the cninfo original when one is found. Provider times
and nulls are preserved instead of being inferred by the model.
"""

from __future__ import annotations

import html
import json
import math
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from core.web.services import financial_market_service as market
from core.web.services.financial_research.official_filings import (
    FILING_SOURCE,
    accepted_annual_filing,
    annual_filing_code,
    lookup_annual_filings,
    mentions_annual_report,
)

EASTMONEY_SOURCE = "东方财富"
EASTMONEY_NOTICES_URL = "https://data.eastmoney.com/notices/"
CNINFO_NOTICES_URL = "https://www.cninfo.com.cn/"
_ANNUAL_ORIGINAL_MISSING = "没有核到巨潮资讯年报原文，未列出年报转载。"
_OTHER_NOTICES_UNAVAILABLE = "其它公告暂时不可用。"
SINA_SOURCE = "新浪财经"
SINA_SCREEN_URL = "https://vip.stock.finance.sina.com.cn/mkt/#hs_a"
SINA_LIST_ENDPOINT = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
SINA_COUNT_ENDPOINT = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount?node=hs_a"
SCREEN_PAGE_SIZE = 80
SCREEN_MAX_ROWS = 8_000
SCREEN_RESPONSE_MAX_BYTES = 2_000_000
SCREEN_REQUEST_TIMEOUT_SECONDS = 6
SCREEN_UNIVERSE_DEADLINE_SECONDS = 15
SCREEN_CACHE_SECONDS = 600
RESEARCH_NEWS_CACHE_SECONDS = 180
RESEARCH_ANNOUNCEMENT_CACHE_SECONDS = 900
RESEARCH_FUNDAMENTALS_CACHE_SECONDS = 1_800

_SCREEN_SORT_FIELDS = {
    "changePercent": "changePercent",
    "turnoverYuan": "turnoverYuan",
    "price": "price",
    "volumeLots": "volumeLots",
    "peRatio": "peRatio",
    "pbRatio": "pbRatio",
}
_FUNDAMENTAL_FIELDS = (
    ("EPSJB", "每股收益", "元/股"),
    ("BPS", "每股净资产", "元/股"),
    ("TOTALOPERATEREVE", "营业收入", "元"),
    ("PARENTNETPROFIT", "归母净利润", "元"),
    ("TOTALOPERATEREVETZ", "营业收入同比", "%"),
    ("PARENTNETPROFITTZ", "归母净利润同比", "%"),
    ("ROEJQ", "净资产收益率", "%"),
    ("XSJLL", "销售净利率", "%"),
    ("XSMLL", "销售毛利率", "%"),
    ("ZCFZL", "资产负债率", "%"),
)
_SINA_MARKETS = {"sh": "上交所", "sz": "深交所", "bj": "北交所"}
_SCREEN_CACHE_LOCK = threading.Lock()
_SCREEN_CACHE: tuple[float, dict[str, Any]] | None = None
_SCREEN_LOAD_LOCK = threading.Lock()


class FinancialResearchInputError(ValueError):
    """A bounded Finance query cannot be interpreted safely."""


class FinancialResearchDataError(RuntimeError):
    """A fixed public provider did not return a complete, usable response."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[ T].*)?$", text)
    return match.group(1) if match else None


def _read_json(url: str) -> Any:
    """Read a fixed Eastmoney URL through the existing bounded market reader."""
    try:
        raw = market._read(url, "utf-8")
        text = raw.strip()
        if text.startswith("callback(") and text.endswith(");"):
            text = text[len("callback(") : -2]
        elif text.startswith("callback(") and text.endswith(")"):
            text = text[len("callback(") : -1]
        return json.loads(text)
    except market.MarketDataError as exc:
        raise FinancialResearchDataError("东方财富数据源暂时不可用") from exc
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise FinancialResearchDataError("东方财富返回的数据格式无效") from exc


def _read_sina(url: str) -> str:
    """Read one fixed Sina screen URL with a dedicated 2 MB response cap."""
    try:
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
                "Referer": "https://finance.sina.com.cn/",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        with urlopen(request, timeout=SCREEN_REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read(SCREEN_RESPONSE_MAX_BYTES + 1)
        if len(body) > SCREEN_RESPONSE_MAX_BYTES:
            raise FinancialResearchDataError("新浪股票池数据超过读取上限")
        return body.decode("gb18030")
    except FinancialResearchDataError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise FinancialResearchDataError("新浪 A 股行情源暂时不可用") from exc


def _sina_screen_page(page: int) -> list[dict[str, Any]]:
    query = urlencode(
        {
            "page": page,
            "num": SCREEN_PAGE_SIZE,
            "sort": "symbol",
            "asc": 1,
            "node": "hs_a",
            "symbol": "",
            "_s_r_a": "page",
        }
    )
    try:
        payload = json.loads(_read_sina(SINA_LIST_ENDPOINT + "?" + query))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise FinancialResearchDataError("新浪返回的 A 股列表格式无效") from exc
    if not isinstance(payload, list) or any(
        not isinstance(row, dict) for row in payload
    ):
        raise FinancialResearchDataError("新浪未返回有效的 A 股列表")
    return payload


def _screen_identity(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        ticker = str(raw.get("code") or "").strip()
        symbol = market.normalize_symbol(str(raw.get("symbol") or ""))
        if symbol[-6:] != ticker:
            raise ValueError("symbol/code mismatch")
        market_name = _SINA_MARKETS[symbol[:2]]
    except (KeyError, TypeError, ValueError, market.MarketDataError) as exc:
        raise FinancialResearchDataError("新浪股票池包含无法识别的股票代码") from exc
    name = html.unescape(str(raw.get("name") or "")).strip()
    if not name or len(name) > 80:
        raise FinancialResearchDataError("新浪股票池包含无效的股票名称")
    volume_shares = _number(raw.get("volume"))
    timestamp = str(raw.get("ticktime") or "").strip()
    if not re.fullmatch(r"\d{2}:\d{2}:\d{2}", timestamp):
        timestamp = ""
    return {
        "symbol": symbol,
        "ticker": ticker,
        "name": name,
        "market": market_name,
        "price": _number(raw.get("trade")),
        "change": _number(raw.get("pricechange")),
        "changePercent": _number(raw.get("changepercent")),
        "volumeLots": volume_shares / 100 if volume_shares is not None else None,
        "turnoverYuan": _number(raw.get("amount")),
        "open": _number(raw.get("open")),
        "high": _number(raw.get("high")),
        "low": _number(raw.get("low")),
        "previousClose": _number(raw.get("settlement")),
        "peRatio": _number(raw.get("per")),
        "pbRatio": _number(raw.get("pb")),
        # Sina's screen payload exposes mktcap without a documented unit. Keep
        # this nullable until the source unit can be verified against an
        # authoritative contract; the Tencent detail quote has its own known unit.
        "totalMarketCapYuan": None,
        "timestamp": None,
        "timeOfDay": timestamp or None,
    }


def _load_screen_universe() -> dict[str, Any]:
    deadline = time.monotonic() + SCREEN_UNIVERSE_DEADLINE_SECONDS
    try:
        count_payload = _read_sina(SINA_COUNT_ENDPOINT).strip()
        try:
            count_value = json.loads(count_payload)
        except json.JSONDecodeError:
            count_value = count_payload
        count_text = (
            str(count_value)
            if isinstance(count_value, (int, str)) and not isinstance(count_value, bool)
            else ""
        )
        if not re.fullmatch(r"\d{1,6}", count_text):
            raise ValueError("invalid count")
        total = int(count_text)
    except (FinancialResearchDataError, ValueError) as exc:
        raise FinancialResearchDataError("新浪未返回有效的沪深京 A 股覆盖数") from exc
    if total < 0 or total > SCREEN_MAX_ROWS:
        raise FinancialResearchDataError("A 股股票池超出安全读取上限")
    page_count = max(1, math.ceil(total / SCREEN_PAGE_SIZE))
    page_rows: dict[int, list[dict[str, Any]]] = {}
    failed_pages: list[int] = []

    def read_page_before_deadline(page: int) -> list[dict[str, Any]]:
        if time.monotonic() >= deadline:
            raise TimeoutError("Sina screen load deadline exceeded")
        return _sina_screen_page(page)

    def collect_page_result(future: Any, page: int) -> None:
        try:
            rows = future.result()
            expected = min(SCREEN_PAGE_SIZE, total - ((page - 1) * SCREEN_PAGE_SIZE))
            if len(rows) != expected:
                failed_pages.append(page)
            page_rows[page] = rows
        except (FinancialResearchDataError, OSError, UnicodeError, ValueError):
            failed_pages.append(page)

    pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="finance-screen")
    futures: dict[Any, int] = {}
    next_page = 1
    try:
        while next_page <= page_count or futures:
            while (
                next_page <= page_count
                and len(futures) < 3
                and time.monotonic() < deadline
            ):
                futures[pool.submit(read_page_before_deadline, next_page)] = next_page
                next_page += 1

            if not futures:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            completed, _ = wait(
                tuple(futures), timeout=remaining, return_when=FIRST_COMPLETED
            )
            if not completed:
                break
            for future in completed:
                page = futures.pop(future)
                collect_page_result(future, page)

        for future, page in tuple(futures.items()):
            if future.done():
                collect_page_result(future, page)
            else:
                future.cancel()
                failed_pages.append(page)
        failed_pages.extend(range(next_page, page_count + 1))
    finally:
        deadline_expired = time.monotonic() >= deadline and (
            next_page <= page_count or any(not future.done() for future in futures)
        )
        pool.shutdown(wait=not deadline_expired, cancel_futures=deadline_expired)
    failed_pages = sorted(set(failed_pages))
    stocks: list[dict[str, Any]] = []
    invalid_rows = 0
    for page in range(1, page_count + 1):
        for raw in page_rows.get(page, []):
            try:
                stocks.append(_screen_identity(raw))
            except FinancialResearchDataError:
                invalid_rows += 1
    unique: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for stock in stocks:
        if stock["symbol"] in unique:
            duplicate_count += 1
        else:
            unique[stock["symbol"]] = stock
    stocks = list(unique.values())
    coverage_complete = (
        len(stocks) == total
        and not failed_pages
        and invalid_rows == 0
        and duplicate_count == 0
    )
    times = [stock["timeOfDay"] for stock in stocks if stock["timeOfDay"]]
    data_time = max(set(times), key=times.count) if times else None
    return {
        "cacheKey": f"sina:hs_a:{data_time or 'time-unavailable'}",
        "stocks": stocks,
        "coverage": {
            "providerTotal": total,
            "loaded": len(stocks),
            "complete": coverage_complete,
            "failedPages": failed_pages,
            "invalidRows": invalid_rows,
            "duplicateRows": duplicate_count,
        },
        "dataDate": None,
        "dataTime": data_time,
        "fetchedAt": _utc_now(),
        "cacheSeconds": SCREEN_CACHE_SECONDS,
    }


def _screen_universe() -> dict[str, Any]:
    global _SCREEN_CACHE
    now = time.monotonic()
    with _SCREEN_CACHE_LOCK:
        if _SCREEN_CACHE and now - _SCREEN_CACHE[0] < SCREEN_CACHE_SECONDS:
            return _SCREEN_CACHE[1]
    with _SCREEN_LOAD_LOCK:
        now = time.monotonic()
        with _SCREEN_CACHE_LOCK:
            if _SCREEN_CACHE and now - _SCREEN_CACHE[0] < SCREEN_CACHE_SECONDS:
                return _SCREEN_CACHE[1]
        result = _load_screen_universe()
        with _SCREEN_CACHE_LOCK:
            _SCREEN_CACHE = (time.monotonic(), result)
        return result


def _screen_bounds(
    *,
    min_price: float | None,
    max_price: float | None,
    min_change_percent: float | None,
    max_change_percent: float | None,
    min_pe: float | None,
    max_pe: float | None,
    min_volume_lots: float | None,
    min_pb: float | None = None,
    max_pb: float | None = None,
    min_turnover_yuan: float | None = None,
    max_turnover_yuan: float | None = None,
) -> tuple[tuple[str, float | None, float | None], ...]:
    bounds: tuple[tuple[str, float | None, float | None], ...] = (
        ("price", min_price, max_price),
        ("changePercent", min_change_percent, max_change_percent),
        ("peRatio", min_pe, max_pe),
        ("volumeLots", min_volume_lots, None),
        ("pbRatio", min_pb, max_pb),
        ("turnoverYuan", min_turnover_yuan, max_turnover_yuan),
    )
    for field, lower, upper in bounds:
        if any(value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)) for value in (lower, upper)):
            raise FinancialResearchInputError(f"{field} 条件必须为有限数值")
        if field in {"price", "volumeLots", "turnoverYuan"} and any(value is not None and value < 0 for value in (lower, upper)):
            raise FinancialResearchInputError(f"{field} 条件不能为负数")
        if lower is not None and upper is not None and lower > upper:
            raise FinancialResearchInputError(f"{field} 最小值不能大于最大值")
    return bounds


def _screen_values(
    stocks: list[dict[str, Any]],
    bounds: tuple[tuple[str, float | None, float | None], ...],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for stock in stocks:
        accepted = True
        for field, lower, upper in bounds:
            value = stock.get(field)
            if lower is not None and (value is None or value < lower):
                accepted = False
                break
            if upper is not None and (value is None or value > upper):
                accepted = False
                break
        if accepted:
            filtered.append(stock)
    return filtered


def screen_stocks(
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
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    if sort_by not in _SCREEN_SORT_FIELDS or direction not in {"asc", "desc"}:
        raise FinancialResearchInputError("不支持的股票排序方式")
    if page < 1 or page > 100_000 or page_size < 1 or page_size > 100:
        raise FinancialResearchInputError("页码或每页数量超出范围")
    bounds = _screen_bounds(
        min_price=min_price,
        max_price=max_price,
        min_change_percent=min_change_percent,
        max_change_percent=max_change_percent,
        min_pe=min_pe,
        max_pe=max_pe,
        min_volume_lots=min_volume_lots,
        min_pb=min_pb,
        max_pb=max_pb,
        min_turnover_yuan=min_turnover_yuan,
        max_turnover_yuan=max_turnover_yuan,
    )
    snapshot = _screen_universe()
    matches = _screen_values(snapshot["stocks"], bounds)
    field = _SCREEN_SORT_FIELDS[sort_by]
    present = [stock for stock in matches if stock.get(field) is not None]
    missing = [stock for stock in matches if stock.get(field) is None]
    present.sort(
        key=lambda stock: (stock[field], stock["symbol"]), reverse=direction == "desc"
    )
    ordered = present + sorted(missing, key=lambda stock: stock["symbol"])
    start = (page - 1) * page_size
    return {
        "source": SINA_SOURCE,
        "sourceUrl": SINA_SCREEN_URL,
        "fetchedAt": snapshot["fetchedAt"],
        "dataDate": snapshot["dataDate"],
        "dataTime": snapshot["dataTime"],
        "cacheKey": snapshot["cacheKey"],
        "cacheSeconds": snapshot["cacheSeconds"],
        "coverage": {
            **snapshot["coverage"],
            "totalFiltered": len(ordered),
        },
        "resultScope": "provider_universe"
        if snapshot["coverage"]["complete"]
        else "loaded_subset",
        "sortBy": sort_by,
        "direction": direction,
        "page": page,
        "pageSize": page_size,
        "items": ordered[start : start + page_size],
        "notice": "新浪返回行情时分但未提供交易日期；不确定日期的报价不会被标成当日行情。",
    }


def batch_quotes(values: list[str]) -> dict[str, Any]:
    if not values or len(values) > 50:
        raise FinancialResearchInputError("一次最多查询 50 只股票")
    normalized: dict[str, str] = {}
    for value in values:
        raw = str(value).strip()
        try:
            normalized[raw] = market.normalize_symbol(raw)
        except market.MarketDataError:
            normalized[raw] = ""
    symbols = tuple(sorted({symbol for symbol in normalized.values() if symbol}))
    raw_quotes: str | None = None
    fetched_at = ""
    quote_error = ""
    if symbols:
        try:

            def read_quote_batch() -> tuple[str, str]:
                payload = market._read(
                    "https://qt.gtimg.cn/q=" + ",".join(symbols), "gb18030"
                )
                return payload, _utc_now()

            raw_quotes, fetched_at = market._cached(
                ("quote-batch", symbols),
                30,
                read_quote_batch,
            )
        except market.MarketDataError as exc:
            quote_error = str(exc)
    items: list[dict[str, Any]] = []
    for raw, symbol in normalized.items():
        if not symbol:
            items.append(
                {"symbol": raw[:24], "quote": None, "error": "请输入有效的 A 股代码"}
            )
            continue
        if raw_quotes is None:
            items.append(
                {
                    "symbol": symbol,
                    "quote": None,
                    "error": quote_error or "行情源暂时不可用，请重试",
                }
            )
            continue
        try:
            items.append(
                {
                    "symbol": symbol,
                    "quote": market.parse_quote(raw_quotes, symbol),
                    "error": None,
                }
            )
        except market.MarketDataError as exc:
            items.append({"symbol": symbol, "quote": None, "error": str(exc)})
    return {
        "source": "腾讯财经",
        "sourceUrl": "https://gu.qq.com/",
        "fetchedAt": fetched_at or _utc_now(),
        "items": items,
    }


def _eastmoney_stock(symbol: str) -> dict[str, str]:
    normalized = market.normalize_symbol(symbol)
    if normalized.startswith(("hk", "us")):
        code = "HK" if normalized.startswith("hk") else "US"
        try:
            matches = market.search_stocks(normalized[2:], market=code)
            candidate = next((row for row in matches if row.get("symbol") == normalized), None)
            if candidate:
                return candidate
        except market.MarketDataError:
            pass
        return {"symbol": normalized, "ticker": normalized[2:], "name": normalized[2:], "market": "港交所" if code == "HK" else "美股", "marketCode": code}
    try:
        result = market.search_stocks(normalized[-6:])
        candidate = next(
            (row for row in result if row.get("symbol") == normalized), None
        )
    except market.MarketDataError:
        candidate = None
    if candidate:
        return candidate
    ticker = normalized[-6:]
    market_name = {"sh": "上交所", "sz": "深交所", "bj": "北交所"}[normalized[:2]]
    return {
        "symbol": normalized,
        "ticker": ticker,
        "name": ticker,
        "market": market_name,
    }


def _strip_markup(value: Any) -> str:
    text = html.unescape(str(value or ""))
    return re.sub(r"<[^>]{0,200}>", "", text).strip()


def _safe_eastmoney_url(value: Any) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"https", "http"} or not (
        host == "eastmoney.com" or host.endswith(".eastmoney.com")
    ):
        return ""
    if parsed.username or parsed.password:
        return ""
    return urlunparse(("https", host, parsed.path, "", parsed.query, ""))


def _news_url(keyword: str) -> str:
    params = {
        "uid": "",
        "keyword": keyword,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": 1,
                "pageSize": 8,
                "preTag": "<em>",
                "postTag": "</em>",
            }
        },
    }
    query = urlencode(
        {
            "cb": "callback",
            "param": json.dumps(params, ensure_ascii=False, separators=(",", ":")),
        }
    )
    return "https://search-api-web.eastmoney.com/search/jsonp?" + query


def _load_news(stock: dict[str, str]) -> dict[str, Any]:
    keyword = stock["name"] if stock["name"] != stock["ticker"] else stock["ticker"]
    payload = _read_json(_news_url(keyword))
    rows = (
        (payload.get("result") or {}).get("cmsArticleWebOld")
        if isinstance(payload, dict)
        else None
    )
    if not isinstance(rows, list):
        raise FinancialResearchDataError("东方财富未返回股票新闻")
    items = []
    for row in rows[:8]:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        link = _safe_eastmoney_url(row.get("url"))
        if not link and re.fullmatch(r"\d{12,20}", code):
            link = f"https://finance.eastmoney.com/a/{code}.html"
        title = _strip_markup(row.get("title"))
        if title:
            items.append(
                {
                    "title": title,
                    "publishedAt": str(row.get("date") or "").strip() or None,
                    "publisher": _strip_markup(row.get("mediaName"))
                    or EASTMONEY_SOURCE,
                    "url": link or None,
                }
            )
    return {
        "status": "available",
        "source": EASTMONEY_SOURCE,
        "sourceUrl": "https://so.eastmoney.com/news/s?"
        + urlencode({"keyword": stock["ticker"]}),
        "fetchedAt": _utc_now(),
        "error": None,
        "items": items,
    }


def _load_announcements(stock: dict[str, str]) -> dict[str, Any]:
    """A-share notices. The annual report is the cninfo PDF, not a reprint."""

    notices, notice_error = _eastmoney_notice_items(stock)
    filing = _official_annual_notice(stock["ticker"])
    if filing is None and notice_error is not None and not notices:
        raise FinancialResearchDataError(notice_error)
    items: list[dict[str, Any]] = []
    if filing is not None:
        items.append(filing)
    for item in notices:
        if mentions_annual_report(item.get("title")):
            continue
        items.append({**item, "publisher": EASTMONEY_SOURCE})
    if filing is not None:
        source = FILING_SOURCE
        source_url = CNINFO_NOTICES_URL
        error = _OTHER_NOTICES_UNAVAILABLE if notice_error is not None else None
    else:
        source = EASTMONEY_SOURCE
        source_url = EASTMONEY_NOTICES_URL
        error = _ANNUAL_ORIGINAL_MISSING
    return {
        "status": "available",
        "source": source,
        "sourceUrl": source_url,
        "fetchedAt": _utc_now(),
        "error": error,
        "items": items,
    }


def _eastmoney_notice_items(
    stock: dict[str, str],
) -> tuple[list[dict[str, Any]], str | None]:
    query = urlencode(
        {
            "page_size": 10,
            "page_index": 1,
            "ann_type": "A",
            "client_source": "web",
            "stock_list": stock["ticker"],
        }
    )
    try:
        payload = _read_json(
            "https://np-anotice-stock.eastmoney.com/api/security/ann?" + query
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("list") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise FinancialResearchDataError("东方财富未返回公司公告")
    except (
        FinancialResearchDataError,
        market.MarketDataError,
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
    ) as exc:
        message = str(exc).strip() or "数据源暂时不可用，请重试"
        return [], message[:160]
    items: list[dict[str, Any]] = []
    for row in rows[:10]:
        if not isinstance(row, dict):
            continue
        codes = row.get("codes") if isinstance(row.get("codes"), list) else []
        if codes and not any(
            str(code.get("stock_code") or "") == stock["ticker"]
            for code in codes
            if isinstance(code, dict)
        ):
            continue
        code = str(row.get("art_code") or "").strip()
        if not re.fullmatch(r"AN\d{10,24}", code):
            continue
        title = _strip_markup(row.get("title_ch") or row.get("title"))
        if not title:
            continue
        items.append(
            {
                "title": title,
                "publishedAt": str(
                    row.get("display_time") or row.get("notice_date") or ""
                ).strip()
                or None,
                "noticeDate": _date(row.get("notice_date")),
                "url": (
                    "https://data.eastmoney.com/notices/detail/"
                    f"{stock['ticker']}/{code}.html"
                ),
                "articleCode": code,
            }
        )
    return items, None


def _official_annual_notice(ticker: str) -> dict[str, str] | None:
    try:
        found = lookup_annual_filings([ticker], cutoff=None)
        code = annual_filing_code(ticker)
        raw = found.get(code) if isinstance(found, dict) and code else None
        accepted = accepted_annual_filing(raw, cutoff=None)
    except Exception:
        return None
    if accepted is None:
        return None
    day = accepted["announcedOn"]
    return {
        "title": accepted["title"],
        "publishedAt": day,
        "noticeDate": day,
        "url": accepted["url"],
        "articleCode": f"cninfo-{day}",
        "publisher": FILING_SOURCE,
    }


def _load_fundamentals(stock: dict[str, str]) -> dict[str, Any]:
    exchange = {"sh": "SH", "sz": "SZ", "bj": "BJ"}[stock["symbol"][:2]]
    secucode = stock["ticker"] + "." + exchange
    columns = (
        "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,NOTICE_DATE,"
        + ",".join(item[0] for item in _FUNDAMENTAL_FIELDS)
    )
    filter_value = f'(SECUCODE="{secucode}")'
    query = urlencode(
        {
            "reportName": "RPT_F10_FINANCE_MAINFINADATA",
            "columns": columns,
            "filter": filter_value,
            "pageNumber": 1,
            "pageSize": 1,
            "sortTypes": -1,
            "sortColumns": "REPORT_DATE",
            "source": "HSF10",
            "client": "PC",
        }
    )
    payload = _read_json(
        "https://datacenter.eastmoney.com/securities/api/data/v1/get?" + query
    )
    result = payload.get("result") if isinstance(payload, dict) else None
    rows = result.get("data") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise FinancialResearchDataError("东方财富未返回财务指标")
    row = rows[0] if rows and isinstance(rows[0], dict) else {}
    report_date = _date(row.get("REPORT_DATE"))
    notice_date = _date(row.get("NOTICE_DATE"))
    items = [
        {
            "key": key,
            "label": label,
            "value": _number(row.get(key)),
            "unit": unit,
            "reportDate": report_date,
            "publishedAt": notice_date,
        }
        for key, label, unit in _FUNDAMENTAL_FIELDS
    ]
    return {
        "status": "available",
        "source": EASTMONEY_SOURCE,
        "sourceUrl": "https://data.eastmoney.com/bbsj/",
        "fetchedAt": _utc_now(),
        "reportDate": report_date,
        "publishedAt": notice_date,
        "error": None,
        "items": items,
    }


def _unavailable(source_url: str, error: Exception) -> dict[str, Any]:
    message = str(error).strip()
    if not message:
        message = "数据源暂时不可用，请重试"
    return {
        "status": "unavailable",
        "source": EASTMONEY_SOURCE,
        "sourceUrl": source_url,
        "fetchedAt": _utc_now(),
        "error": message[:160],
        "items": [],
    }


def stock_research(symbol: str) -> dict[str, Any]:
    try:
        normalized = market.normalize_symbol(symbol)
    except market.MarketDataError as exc:
        raise FinancialResearchInputError(str(exc)) from exc
    stock = _eastmoney_stock(normalized)
    if normalized.startswith(("hk", "us")):
        # News search is keyword based; mainland security identifiers are
        # never reused for international announcements or financial metrics.
        try:
            news = market._cached(("finance-research-v1", "news", normalized), RESEARCH_NEWS_CACHE_SECONDS, lambda: _load_news(stock))
        except (FinancialResearchDataError, market.MarketDataError, OSError, ValueError, TypeError, KeyError):
            news = _unavailable("https://so.eastmoney.com/news/", FinancialResearchDataError("股票新闻源暂不可用，可让研究助手继续查证"))
        from core.web.services.financial_research import fetch_international_facets

        return {"stock": stock, "news": news, **fetch_international_facets(stock)}
    readers = (
        (
            "news",
            RESEARCH_NEWS_CACHE_SECONDS,
            lambda: _load_news(stock),
            "https://so.eastmoney.com/news/",
        ),
        (
            "announcements",
            RESEARCH_ANNOUNCEMENT_CACHE_SECONDS,
            lambda: _load_announcements(stock),
            "https://data.eastmoney.com/notices/",
        ),
        (
            "fundamentals",
            RESEARCH_FUNDAMENTALS_CACHE_SECONDS,
            lambda: _load_fundamentals(stock),
            "https://data.eastmoney.com/bbsj/",
        ),
    )
    projected: dict[str, Any] = {"stock": stock}
    with ThreadPoolExecutor(
        max_workers=3, thread_name_prefix="finance-research"
    ) as pool:
        futures = {
            pool.submit(
                market._cached, ("finance-research-v1", key, normalized), ttl, reader
            ): (key, source_url)
            for key, ttl, reader, source_url in readers
        }
        for future, (key, source_url) in (
            (future, item) for future, item in futures.items()
        ):
            try:
                projected[key] = future.result()
            except (
                FinancialResearchDataError,
                market.MarketDataError,
                OSError,
                UnicodeError,
                ValueError,
                TypeError,
                KeyError,
                IndexError,
            ) as exc:
                projected[key] = _unavailable(source_url, exc)
    return projected


__all__ = [
    "EASTMONEY_SOURCE",
    "SINA_SOURCE",
    "FinancialResearchDataError",
    "FinancialResearchInputError",
    "batch_quotes",
    "screen_stocks",
    "stock_research",
]
