"""Bounded public disclosure and fundamentals adapters for HK and US equities.

HK filings come from HKEXnews; HK headline metrics come from Eastmoney's public
F10 endpoint with report currency resolved from its report list. US filings and
standard facts come from SEC EDGAR's public submissions and CompanyFacts APIs.
"""

from __future__ import annotations

import html
import json
import math
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from core.web.services import financial_market_service as market

HKEX_SOURCE = "香港交易所披露易"
HKEX_BASE_URL = "https://www1.hkexnews.hk"
HKEX_STOCK_LIST_URL = f"{HKEX_BASE_URL}/ncms/script/eds/activestock_sehk_e.json"
HKEX_SEARCH_URL = f"{HKEX_BASE_URL}/search/titleSearchServlet.do"
HKEX_TITLE_SEARCH_URL = f"{HKEX_BASE_URL}/search/titlesearch.xhtml"

EASTMONEY_SOURCE = "东方财富"
EASTMONEY_DATA_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
HK_EASTMONEY_FUNDAMENTALS_URL = (
    "https://emweb.securities.eastmoney.com/PC_HKF10/NewFinancialAnalysis/index"
)
US_EASTMONEY_FUNDAMENTALS_URL = (
    "https://emweb.eastmoney.com/PC_USF10/pages/index.html"
)
US_EASTMONEY_PROFILE_REPORT = "RPT_USF10_INFO_ORGPROFILE"
US_EASTMONEY_INDICATOR_REPORT = "RPT_USF10_FN_GMAININDICATOR"
US_EASTMONEY_SOURCE = "东方财富 USF10"

SEC_SOURCE = "SEC EDGAR"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_BROWSE_URL = "https://www.sec.gov/edgar/browse/?CIK={cik}"

_REQUEST_TIMEOUT_SECONDS = 8
_REQUEST_INTERVAL_SECONDS = 0.25
_HKEX_STOCK_LIST_MAX_BYTES = 1_200_000
_SEC_JSON_MAX_BYTES = 8_000_000
_DEFAULT_JSON_MAX_BYTES = 1_000_000
_CACHE_DAY_SECONDS = 24 * 60 * 60
_US_FUNDAMENTALS_CACHE_SECONDS = 60 * 60
_MAX_ANNOUNCEMENTS = 12
_US_EASTMONEY_PAGE_SIZE = 12
_US_EXCHANGE_SUFFIX_RE = re.compile(
    r"\.(?:OQ|N|AM|PK|PNK|NYSE|NASDAQ)$", re.IGNORECASE
)
_US_REPORTED_PERIOD_RE = re.compile(r"(?:\d{4}/FY|\d{4}/Q[1-4])$", re.IGNORECASE)
_KNOWN_CURRENCY_CODES = frozenset(
    {
        "AUD",
        "BRL",
        "CAD",
        "CHF",
        "CNY",
        "DKK",
        "EUR",
        "GBP",
        "HKD",
        "IDR",
        "ILS",
        "INR",
        "JPY",
        "KRW",
        "MXN",
        "MYR",
        "NOK",
        "NZD",
        "SEK",
        "SGD",
        "THB",
        "TWD",
        "USD",
        "ZAR",
    }
)

_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0


class FinancialDisclosureDataError(RuntimeError):
    """A fixed public disclosure source returned unusable or unavailable data."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date(value: Any) -> str | None:
    text = str(value or "").strip()
    match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[ T].*)?$", text)
    return match.group(1) if match else None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _read_json(
    url: str,
    *,
    source: str,
    max_bytes: int = _DEFAULT_JSON_MAX_BYTES,
    referer: str | None = None,
    user_agent: str = "Vibelution/2 financial-research",
) -> Any:
    """Read a fixed HTTPS source with a request budget and a strict byte cap."""
    global _LAST_REQUEST_AT
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise FinancialDisclosureDataError(f"{source} 请求地址无效")
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json,text/plain,*/*",
    }
    if referer:
        headers["Referer"] = referer
    request = Request(url, headers=headers)
    try:
        with _REQUEST_LOCK:
            delay = _REQUEST_INTERVAL_SECONDS - (time.monotonic() - _LAST_REQUEST_AT)
            if delay > 0:
                time.sleep(delay)
            _LAST_REQUEST_AT = time.monotonic()
        with urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            final_url = urlparse(response.geturl())
            final_host = final_url.hostname or ""
            requested_host = parsed.hostname.lower()
            final_host = final_host.lower()
            if final_url.scheme.lower() != "https":
                raise FinancialDisclosureDataError(
                    f"{source} 重定向降级到非 HTTPS"
                )
            if final_host != requested_host and not final_host.endswith(
                "." + requested_host
            ):
                raise FinancialDisclosureDataError(f"{source} 跳转到非预期域名")
            content_length = response.headers.get("Content-Length")
            if content_length and content_length.isdigit() and int(content_length) > max_bytes:
                raise FinancialDisclosureDataError(f"{source} 返回内容超过读取上限")
            body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise FinancialDisclosureDataError(f"{source} 返回内容超过读取上限")
        try:
            text = body.decode("utf-8-sig")
            return json.loads(text)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FinancialDisclosureDataError(f"{source} 返回的数据格式无效") from exc
    except FinancialDisclosureDataError:
        raise
    except HTTPError as exc:
        raise FinancialDisclosureDataError(f"{source} HTTP {exc.code}") from exc
    except (OSError, URLError, TimeoutError, ValueError) as exc:
        raise FinancialDisclosureDataError(f"{source} 暂时不可用") from exc


def _unavailable(source: str, source_url: str, error: Exception | str, *, fundamentals: bool = False) -> dict[str, Any]:
    message = str(error).strip() or "公开数据源暂时不可用"
    result: dict[str, Any] = {
        "status": "unavailable",
        "source": source,
        "sourceUrl": source_url,
        "fetchedAt": _utc_now(),
        "error": message[:160],
        "items": [],
    }
    if fundamentals:
        result.update({"reportDate": None, "publishedAt": None})
    return result


def _available(
    source: str,
    source_url: str,
    items: list[dict[str, Any]],
    *,
    report_date: str | None = None,
    published_at: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "available",
        "source": source,
        "sourceUrl": source_url,
        "fetchedAt": _utc_now(),
        "error": error,
        "items": items,
    }
    if report_date is not None or published_at is not None:
        result.update({"reportDate": report_date, "publishedAt": published_at})
    return result


def _load_cached(key: tuple[Any, ...], ttl: int, loader):
    return market._cached(key, ttl, loader)


# --- HKEXnews filings -------------------------------------------------------


def _hk_code(stock: dict[str, Any]) -> str:
    symbol = str(stock.get("symbol") or "").strip()
    ticker = str(stock.get("ticker") or "").strip()
    candidate = ticker if ticker else symbol[2:] if symbol.lower().startswith("hk") else ""
    if not re.fullmatch(r"\d{1,5}", candidate):
        raise FinancialDisclosureDataError("HKEX 未找到有效的港股代码")
    return candidate.zfill(5)


def _load_hk_stock_ids() -> dict[str, str]:
    payload = _read_json(
        HKEX_STOCK_LIST_URL,
        source=HKEX_SOURCE,
        max_bytes=_HKEX_STOCK_LIST_MAX_BYTES,
        referer=HKEX_TITLE_SEARCH_URL + "?lang=en",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/130 Safari/537.36"
        ),
    )
    if not isinstance(payload, list):
        raise FinancialDisclosureDataError("HKEX 股票代码表格式无效")
    result: dict[str, str] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        code = str(row.get("c") or "").strip()
        stock_id = str(row.get("i") or "").strip()
        if re.fullmatch(r"\d{5}", code) and re.fullmatch(r"\d{1,12}", stock_id):
            result[code] = stock_id
    if not result:
        raise FinancialDisclosureDataError("HKEX 股票代码表没有有效证券")
    return result


def _hk_stock_ids() -> dict[str, str]:
    return _load_cached(
        ("financial-disclosures-v1", "hkex-stock-ids"),
        _CACHE_DAY_SECONDS,
        _load_hk_stock_ids,
    )


def _hk_title_search_url(stock_id: str) -> str:
    return HKEX_TITLE_SEARCH_URL + "?" + urlencode(
        {"category": 0, "lang": "EN", "market": "SEHK", "stockId": stock_id}
    )


def _hk_date_time(value: Any) -> tuple[str | None, str | None]:
    text = str(value or "").strip()
    try:
        parsed = datetime.strptime(text, "%d/%m/%Y %H:%M").replace(
            tzinfo=timezone(timedelta(hours=8))
        )
    except ValueError:
        return None, None
    return parsed.isoformat(), parsed.date().isoformat()


def _plain_text(value: Any, limit: int = 500) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<br\s*/?>", " / ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]*>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _hk_pdf_url(value: Any) -> str | None:
    path = str(value or "").strip()
    if not re.fullmatch(
        r"/listedco/listconews/sehk/\d{4}/\d{4}/[A-Za-z0-9._-]{1,100}\.pdf",
        path,
        flags=re.IGNORECASE,
    ):
        return None
    return HKEX_BASE_URL + path


def _load_hk_announcements(stock: dict[str, Any]) -> dict[str, Any]:
    code = _hk_code(stock)
    stock_id = _hk_stock_ids().get(code)
    if not stock_id:
        raise FinancialDisclosureDataError("HKEX 未找到该港股代码")
    params = {
        "sortDir": "0",
        "sortByOptions": "DateTime",
        "category": "0",
        "market": "SEHK",
        "stockId": stock_id,
        "documentType": "-1",
        "fromDate": "",
        "toDate": "",
        "title": "",
        "searchType": "0",
        "t1code": "-2",
        "t2Gcode": "-2",
        "t2code": "-2",
        "rowRange": str(_MAX_ANNOUNCEMENTS),
        "lang": "E",
    }
    payload = _read_json(
        HKEX_SEARCH_URL + "?" + urlencode(params),
        source=HKEX_SOURCE,
        referer=HKEX_TITLE_SEARCH_URL + "?lang=en",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/130 Safari/537.36"
        ),
    )
    result = payload.get("result") if isinstance(payload, dict) else None
    if isinstance(result, str):
        try:
            rows = json.loads(result)
        except json.JSONDecodeError as exc:
            raise FinancialDisclosureDataError("HKEX 公告列表格式无效") from exc
    else:
        rows = result
    if not isinstance(rows, list):
        raise FinancialDisclosureDataError("HKEX 未返回有效公告列表")
    items: list[dict[str, Any]] = []
    for row in rows[:_MAX_ANNOUNCEMENTS]:
        if not isinstance(row, dict):
            continue
        link = _hk_pdf_url(row.get("FILE_LINK"))
        title = _plain_text(row.get("LONG_TEXT") or row.get("TITLE"))
        if not link or not title:
            continue
        published_at, notice_date = _hk_date_time(row.get("DATE_TIME"))
        article_code = str(row.get("NEWS_ID") or "").strip()
        if not re.fullmatch(r"\d{1,24}", article_code):
            article_code = link.rsplit("/", 1)[-1]
        items.append(
            {
                "title": title,
                "publishedAt": published_at,
                "noticeDate": notice_date,
                "url": link,
                "articleCode": article_code,
            }
        )
    return _available(
        HKEX_SOURCE,
        _hk_title_search_url(stock_id),
        items,
    )


# --- HK Eastmoney F10 fundamentals -----------------------------------------


def _eastmoney_json_url(params: dict[str, Any]) -> str:
    return EASTMONEY_DATA_URL + "?" + urlencode(params)


def _load_hk_indicator_rows(code: str) -> list[dict[str, Any]]:
    params = {
        "reportName": "RPT_HKF10_FN_MAININDICATOR",
        "columns": "HKF10_FN_MAININDICATOR",
        "quoteColumns": "",
        "pageNumber": "1",
        "pageSize": "9",
        "sortTypes": "-1",
        "sortColumns": "STD_REPORT_DATE",
        "source": "F10",
        "client": "PC",
        "v": "01975982096513973",
        "filter": f'(SECUCODE="{code}.HK")(DATE_TYPE_CODE="001")',
    }
    payload = _read_json(
        _eastmoney_json_url(params),
        source=EASTMONEY_SOURCE,
        referer=(
            f"{HK_EASTMONEY_FUNDAMENTALS_URL}?type=web&code={code}"
        ),
    )
    result = payload.get("result") if isinstance(payload, dict) else None
    rows = result.get("data") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise FinancialDisclosureDataError("东方财富未返回港股主要财务指标")
    return [row for row in rows if isinstance(row, dict)]


def _load_hk_report_currencies(code: str) -> dict[str, str]:
    params = {
        "reportName": "RPT_CUSTOM_HKSK_APPFN_CASHFLOW_SUMMARY",
        "columns": (
            "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,START_DATE,REPORT_DATE,"
            "FISCAL_YEAR,CURRENCY,ACCOUNT_STANDARD,REPORT_TYPE"
        ),
        "quoteColumns": "",
        "filter": f'(SECUCODE="{code}.HK")',
        "source": "F10",
        "client": "PC",
        "v": "02092616586970355",
    }
    payload = _read_json(
        _eastmoney_json_url(params),
        source=EASTMONEY_SOURCE,
        referer=(
            f"{HK_EASTMONEY_FUNDAMENTALS_URL}?type=web&code={code}"
        ),
    )
    result = payload.get("result") if isinstance(payload, dict) else None
    rows = result.get("data") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise FinancialDisclosureDataError("东方财富未返回港股财报币种表")
    report_list = next(
        (
            row.get("REPORT_LIST")
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("REPORT_LIST"), list)
        ),
        None,
    )
    if not isinstance(report_list, list):
        raise FinancialDisclosureDataError("东方财富港股财报币种表为空")
    result_map: dict[str, str] = {}
    for row in report_list:
        if not isinstance(row, dict):
            continue
        report_date = _date(row.get("REPORT_DATE"))
        currency = str(row.get("CURRENCY") or "").strip()
        if report_date and currency:
            result_map.setdefault(report_date, currency)
    return result_map


def _hk_currency(value: str | None) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"CNY", "RMB"} or "人民币" in text:
        return "CNY"
    if text == "HKD" or "港元" in text:
        return "HKD"
    if text == "USD" or "美元" in text or "美金" in text:
        return "USD"
    return None


_HK_METRICS: tuple[tuple[str, str, str], ...] = (
    ("OPERATE_INCOME", "营业收入", "currency"),
    ("OPERATE_INCOME_YOY", "营业收入同比", "%"),
    ("HOLDER_PROFIT", "归母净利润", "currency"),
    ("HOLDER_PROFIT_YOY", "归母净利润同比", "%"),
    ("BASIC_EPS", "基本每股收益", "per_share"),
    ("BPS", "每股净资产", "per_share"),
    ("ROE_AVG", "净资产收益率", "%"),
    ("GROSS_PROFIT_RATIO", "销售毛利率", "%"),
    ("NET_PROFIT_RATIO", "销售净利率", "%"),
    ("DEBT_ASSET_RATIO", "资产负债率", "%"),
    ("CURRENT_RATIO", "流动比率", "倍"),
)


def _load_hk_fundamentals(stock: dict[str, Any]) -> dict[str, Any]:
    code = _hk_code(stock)
    rows = _load_hk_indicator_rows(code)
    if not rows:
        raise FinancialDisclosureDataError("东方财富暂未提供该港股财报指标")
    rows.sort(key=lambda row: _date(row.get("REPORT_DATE")) or "", reverse=True)
    row = rows[0]
    report_date = _date(row.get("REPORT_DATE"))
    if not report_date:
        raise FinancialDisclosureDataError("东方财富财务指标缺少报告期")

    # Eastmoney's indicator CURRENCY is wrong for some issuers. Resolve the
    # period's reporting currency from the separate report list instead.
    report_currencies = _load_hk_report_currencies(code)
    currency = _hk_currency(report_currencies.get(report_date))
    published_at = _date(
        row.get("NOTICE_DATE")
        or row.get("PUBLISHED_DATE")
        or row.get("ACTUAL_NOTICE_DATE")
    )
    items: list[dict[str, Any]] = []
    for key, label, unit_type in _HK_METRICS:
        value = _number(row.get(key))
        if value is None:
            continue
        if unit_type == "currency":
            if currency is None:
                continue
            unit = currency
        elif unit_type == "per_share":
            if currency is None:
                continue
            unit = f"{currency}/股"
        else:
            unit = unit_type
        items.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "unit": unit,
                "reportDate": report_date,
                "publishedAt": published_at,
            }
        )
    if not items:
        raise FinancialDisclosureDataError("东方财富没有可核实币种与单位的港股指标")
    error = (
        None
        if currency is not None
        else "本期财报币种未能从财报清单核实，已隐藏金额和每股指标"
    )
    source_url = (
        f"{HK_EASTMONEY_FUNDAMENTALS_URL}?type=web&code={code}"
    )
    return _available(
        EASTMONEY_SOURCE,
        source_url,
        items,
        report_date=report_date,
        published_at=published_at,
        error=error,
    )


# --- SEC EDGAR submissions and CompanyFacts -------------------------------


def _us_ticker(stock: dict[str, Any]) -> str:
    candidate = _us_source_ticker(stock)
    return candidate.replace(".", "-")


def _us_source_ticker(stock: dict[str, Any]) -> str:
    symbol = str(stock.get("symbol") or "").strip()
    ticker = str(stock.get("ticker") or "").strip()
    candidate = ticker if ticker else symbol[2:] if symbol.lower().startswith("us") else ""
    candidate = _US_EXCHANGE_SUFFIX_RE.sub("", candidate).strip()
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,10}", candidate):
        raise FinancialDisclosureDataError("未找到有效的美股代码")
    return candidate.upper()


def _load_sec_ticker_ids() -> dict[str, tuple[str, str]]:
    payload = _read_json(
        SEC_TICKERS_URL,
        source=SEC_SOURCE,
        max_bytes=_SEC_JSON_MAX_BYTES,
    )
    values = payload.values() if isinstance(payload, dict) else payload
    if not isinstance(values, (list, type({}.values()))):
        raise FinancialDisclosureDataError("SEC 交易代码表格式无效")
    result: dict[str, tuple[str, str]] = {}
    for row in values:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip().upper().replace(".", "-")
        cik_raw = row.get("cik_str")
        title = str(row.get("title") or "").strip()
        try:
            cik_number = int(cik_raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if ticker and cik_number > 0 and len(ticker) <= 10:
            result.setdefault(ticker, (f"{cik_number:010d}", title[:160]))
    if not result:
        raise FinancialDisclosureDataError("SEC 交易代码表没有有效证券")
    return result


def _sec_ticker_ids() -> dict[str, tuple[str, str]]:
    return _load_cached(
        ("financial-disclosures-v1", "sec-ticker-ids"),
        _CACHE_DAY_SECONDS,
        _load_sec_ticker_ids,
    )


def _filing_rows(submissions: Any) -> list[dict[str, Any]]:
    filings = submissions.get("filings") if isinstance(submissions, dict) else None
    recent = filings.get("recent") if isinstance(filings, dict) else None
    if not isinstance(recent, dict):
        raise FinancialDisclosureDataError("SEC Submissions 未返回近期申报")
    forms = recent.get("form")
    filed_dates = recent.get("filingDate")
    report_dates = recent.get("reportDate")
    accessions = recent.get("accessionNumber")
    documents = recent.get("primaryDocument")
    descriptions = recent.get("primaryDocDescription")
    if not all(isinstance(value, list) for value in (forms, filed_dates, report_dates, accessions)):
        raise FinancialDisclosureDataError("SEC Submissions 申报列表格式无效")
    size = min(len(forms), len(filed_dates), len(report_dates), len(accessions))
    rows: list[dict[str, Any]] = []
    for index in range(size):
        rows.append(
            {
                "form": forms[index],
                "filingDate": filed_dates[index],
                "reportDate": report_dates[index] if index < len(report_dates) else "",
                "accessionNumber": accessions[index],
                "primaryDocument": documents[index] if isinstance(documents, list) and index < len(documents) else "",
                "primaryDocDescription": descriptions[index] if isinstance(descriptions, list) and index < len(descriptions) else "",
            }
        )
    return rows


_SEC_PUBLIC_FORMS = {"8-K", "8-K/A", "10-K", "10-K/A", "10-Q", "10-Q/A", "6-K", "6-K/A", "20-F", "20-F/A"}
_SEC_FINANCIAL_FORMS = {"10-K", "10-Q", "20-F", "40-F", "6-K"}


def _sec_document_url(cik: str, accession: str, document: str) -> str:
    accession_compact = accession.replace("-", "")
    safe_document = str(document or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", safe_document):
        safe_document = ""
    base = (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{int(cik)}/{accession_compact}/"
    )
    return base + safe_document if safe_document else base


def _load_us_announcements(
    ticker: str, cik: str, submissions: Any
) -> dict[str, Any]:
    source_url = SEC_BROWSE_URL.format(cik=str(int(cik)))
    rows = _filing_rows(submissions)
    items: list[dict[str, Any]] = []
    for row in rows:
        form = str(row.get("form") or "").strip().upper()
        filing_date = _date(row.get("filingDate"))
        accession = str(row.get("accessionNumber") or "").strip()
        if form not in _SEC_PUBLIC_FORMS or not filing_date:
            continue
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
            continue
        report_date = _date(row.get("reportDate"))
        description = _plain_text(row.get("primaryDocDescription"), 180)
        if not description:
            description = form
        period_note = f"（报告期 {report_date}）" if report_date else ""
        items.append(
            {
                "title": f"{form} · {description}{period_note}"[:300],
                "publishedAt": filing_date,
                "noticeDate": None,
                "url": _sec_document_url(
                    cik, accession, str(row.get("primaryDocument") or "")
                ),
                "articleCode": accession,
            }
        )
        if len(items) >= _MAX_ANNOUNCEMENTS:
            break
    return _available(SEC_SOURCE, source_url, items)


def _facts_root(payload: Any) -> dict[str, Any]:
    facts = payload.get("facts") if isinstance(payload, dict) else None
    us_gaap = facts.get("us-gaap") if isinstance(facts, dict) else None
    if not isinstance(us_gaap, dict):
        raise FinancialDisclosureDataError("SEC CompanyFacts 未返回 US-GAAP 指标")
    return us_gaap


def _fact_records(
    us_gaap: dict[str, Any],
    tags: tuple[str, ...],
    *,
    accession: str,
    form: str,
    report_date: str,
    duration: bool,
) -> tuple[float, str] | None:
    for tag in tags:
        fact = us_gaap.get(tag)
        units = fact.get("units") if isinstance(fact, dict) else None
        if not isinstance(units, dict):
            continue
        unit_names = sorted(units, key=lambda unit: (unit != "USD", unit))
        for unit in unit_names:
            rows = units.get(unit)
            if not isinstance(rows, list):
                continue
            matching = [
                row
                for row in rows
                if isinstance(row, dict)
                and str(row.get("accn") or "") == accession
                and str(row.get("form") or "").upper() == form.upper()
                and _date(row.get("end")) == report_date
            ]
            if duration:
                matching = [row for row in matching if _date(row.get("start"))]
                if matching:
                    def period_days(item: dict[str, Any]) -> int:
                        try:
                            start = date.fromisoformat(
                                _date(item.get("start")) or ""
                            )
                            end = date.fromisoformat(report_date)
                            return (end - start).days + 1
                        except ValueError:
                            return 10_000

                    bounded = [item for item in matching if 45 <= period_days(item) <= 400]
                    if bounded:
                        if form.upper() in {"10-K", "20-F", "40-F"}:
                            annual = [item for item in bounded if period_days(item) >= 300]
                            matching = annual
                        elif form.upper() == "10-Q":
                            matching = [
                                item for item in bounded if period_days(item) <= 140
                            ]
                        else:
                            matching = bounded
                    else:
                        matching = []
            else:
                matching = [row for row in matching if not row.get("start")]
            if not matching:
                continue
            matching.sort(key=lambda item: str(item.get("filed") or ""), reverse=True)
            value = _number(matching[0].get("val"))
            if value is not None:
                return value, str(unit)
    return None


_SEC_METRICS: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    (
        "revenue",
        "营业收入",
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueNet",
            "Revenues",
        ),
        True,
    ),
    ("operatingIncome", "营业利润", ("OperatingIncomeLoss",), True),
    ("netIncome", "净利润", ("NetIncomeLoss", "ProfitLoss"), True),
    ("assets", "总资产", ("Assets",), False),
    ("equity", "股东权益", ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"), False),
    ("basicEps", "基本每股收益", ("EarningsPerShareBasic",), True),
)


def _latest_financial_filing(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        row
        for row in rows
        if str(row.get("form") or "").upper() in _SEC_FINANCIAL_FORMS
        and _date(row.get("reportDate"))
        and re.fullmatch(r"\d{10}-\d{2}-\d{6}", str(row.get("accessionNumber") or ""))
    ]
    candidates.sort(
        key=lambda row: (
            _date(row.get("filingDate")) or "",
            _date(row.get("reportDate")) or "",
        ),
        reverse=True,
    )
    return candidates[0] if candidates else None


def _load_us_fundamentals(
    cik: str, facts_payload: Any, submissions: Any
) -> dict[str, Any]:
    us_gaap = _facts_root(facts_payload)
    rows = _filing_rows(submissions)
    selected: dict[str, Any] | None = None
    for candidate in sorted(
        (
            row
            for row in rows
            if str(row.get("form") or "").upper() in _SEC_FINANCIAL_FORMS
            and _date(row.get("reportDate"))
            and re.fullmatch(
                r"\d{10}-\d{2}-\d{6}", str(row.get("accessionNumber") or "")
            )
        ),
        key=lambda row: (_date(row.get("filingDate")) or "", _date(row.get("reportDate")) or ""),
        reverse=True,
    ):
        accession = str(candidate["accessionNumber"])
        form = str(candidate["form"])
        report_date = _date(candidate.get("reportDate")) or ""
        probe = _fact_records(
            us_gaap,
            ("Assets",),
            accession=accession,
            form=form,
            report_date=report_date,
            duration=False,
        )
        if probe is not None:
            selected = candidate
            break
    if selected is None:
        selected = _latest_financial_filing(rows)
    if selected is None:
        raise FinancialDisclosureDataError("SEC Submissions 未找到财报申报期")

    accession = str(selected["accessionNumber"])
    form = str(selected["form"])
    report_date = _date(selected.get("reportDate"))
    filing_date = _date(selected.get("filingDate"))
    if not report_date:
        raise FinancialDisclosureDataError("SEC 财报申报缺少报告期")
    items: list[dict[str, Any]] = []
    for key, label, tags, is_duration in _SEC_METRICS:
        fact = _fact_records(
            us_gaap,
            tags,
            accession=accession,
            form=form,
            report_date=report_date,
            duration=is_duration,
        )
        if fact is None:
            continue
        value, unit = fact
        items.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "unit": unit,
                "reportDate": report_date,
                "publishedAt": filing_date,
            }
        )
    if not items:
        raise FinancialDisclosureDataError(
            "SEC CompanyFacts 未包含该申报期可验证的标准指标"
        )
    error = (
        None
        if len(items) == len(_SEC_METRICS)
        else "SEC CompanyFacts 未包含部分标准指标，仅显示该申报期可核实字段"
    )
    if form.upper() == "10-Q" and error:
        error += "；缺少独立季度值的项目已隐藏，未用年初至今累计值替代"
    return _available(
        SEC_SOURCE,
        SEC_COMPANY_FACTS_URL.format(cik=cik),
        items,
        report_date=report_date,
        published_at=filing_date,
        error=error,
    )


def _us_eastmoney_ticker_candidates(stock: dict[str, Any]) -> list[str]:
    ticker = _us_source_ticker(stock)
    candidate = ticker.replace(".", "_").replace("-", "_")
    return [candidate] if re.fullmatch(r"[A-Z0-9_-]{1,10}", candidate) else []


def _us_eastmoney_page_url(ticker: str) -> str:
    return (
        US_EASTMONEY_FUNDAMENTALS_URL
        + "?"
        + urlencode({"code": ticker, "type": "web", "color": "w"})
        + "#/cwfx"
    )


def _load_us_eastmoney_security_code(stock: dict[str, Any]) -> tuple[str, str]:
    ticker_candidates = _us_eastmoney_ticker_candidates(stock)
    if not ticker_candidates:
        raise FinancialDisclosureDataError("东方财富未找到有效的美股代码")

    for ticker in ticker_candidates:
        params = {
            "reportName": US_EASTMONEY_PROFILE_REPORT,
            "columns": "SECUCODE,SECURITY_CODE,ORG_CODE",
            "quoteColumns": "",
            "filter": f'(SECURITY_CODE="{ticker}")',
            "pageNumber": "1",
            "pageSize": "10",
            "sortTypes": "",
            "sortColumns": "",
            "source": "SECURITIES",
            "client": "PC",
        }
        payload = _read_json(
            _eastmoney_json_url(params),
            source=US_EASTMONEY_SOURCE,
            referer=_us_eastmoney_page_url(ticker),
        )
        result = payload.get("result") if isinstance(payload, dict) else None
        rows = result.get("data") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            raise FinancialDisclosureDataError(
                "东方财富 USF10 未返回证券代码映射"
            )
        for row in rows[:10]:
            if not isinstance(row, dict):
                continue
            security_code = str(row.get("SECURITY_CODE") or "").strip().upper()
            secu_code = str(row.get("SECUCODE") or "").strip().upper()
            if (
                security_code == ticker
                and re.fullmatch(r"[A-Z0-9._-]{1,20}", secu_code)
            ):
                return ticker, secu_code
    raise FinancialDisclosureDataError("东方财富 USF10 未找到该美股代码")


_US_CURRENCY_NAME_ALIASES = {
    "澳元": "AUD",
    "巴西雷亚尔": "BRL",
    "加元": "CAD",
    "瑞士法郎": "CHF",
    "人民币": "CNY",
    "丹麦克朗": "DKK",
    "欧元": "EUR",
    "英镑": "GBP",
    "港元": "HKD",
    "印尼盾": "IDR",
    "新谢克尔": "ILS",
    "印度卢比": "INR",
    "日元": "JPY",
    "韩元": "KRW",
    "墨西哥比索": "MXN",
    "马来西亚林吉特": "MYR",
    "挪威克朗": "NOK",
    "新西兰元": "NZD",
    "瑞典克朗": "SEK",
    "新加坡元": "SGD",
    "泰铢": "THB",
    "新台币": "TWD",
    "美元": "USD",
    "南非兰特": "ZAR",
}


def _us_report_currency(row: dict[str, Any]) -> str | None:
    abbreviation = str(row.get("CURRENCY_ABBR") or "").strip().upper()
    text = str(row.get("CURRENCY") or "").strip().upper()
    named_currency = _US_CURRENCY_NAME_ALIASES.get(text)
    if text in _KNOWN_CURRENCY_CODES:
        named_currency = text
    if abbreviation:
        if abbreviation not in _KNOWN_CURRENCY_CODES:
            return None
        if named_currency and named_currency != abbreviation:
            return None
        return abbreviation
    return named_currency


_US_EASTMONEY_METRICS: tuple[tuple[str, str, str, str], ...] = (
    ("revenue", "营业收入", "OPERATE_INCOME", "currency"),
    ("grossProfit", "毛利润", "GROSS_PROFIT", "currency"),
    ("netIncome", "归母净利润", "PARENT_HOLDER_NETPROFIT", "currency"),
    ("basicEps", "基本每股收益", "BASIC_EPS", "per_share"),
    ("grossMargin", "销售毛利率", "GROSS_PROFIT_RATIO", "%"),
    ("netMargin", "销售净利率", "NET_PROFIT_RATIO", "%"),
    ("roe", "净资产收益率", "ROE_AVG", "%"),
    ("debtAssetRatio", "资产负债率", "DEBT_ASSET_RATIO", "%"),
)


def _load_us_eastmoney_fundamentals_uncached(
    stock: dict[str, Any]
) -> dict[str, Any]:
    ticker, secu_code = _load_cached(
        (
            "financial-disclosures-v1",
            "us-eastmoney-security-code",
            tuple(_us_eastmoney_ticker_candidates(stock)),
        ),
        _CACHE_DAY_SECONDS,
        lambda: _load_us_eastmoney_security_code(stock),
    )
    params = {
        "reportName": US_EASTMONEY_INDICATOR_REPORT,
        "columns": (
            "SECUCODE,SECURITY_CODE,REPORT_DATE,STD_REPORT_DATE,NOTICE_DATE,"
            "DATE_TYPE_CODE,REPORT_TYPE,CURRENCY,CURRENCY_ABBR,OPERATE_INCOME,"
            "GROSS_PROFIT,PARENT_HOLDER_NETPROFIT,BASIC_EPS,GROSS_PROFIT_RATIO,"
            "NET_PROFIT_RATIO,ROE_AVG,DEBT_ASSET_RATIO"
        ),
        "quoteColumns": "",
        "filter": f'(SECUCODE="{secu_code}")',
        "pageNumber": "1",
        "pageSize": str(_US_EASTMONEY_PAGE_SIZE),
        "sortTypes": "-1",
        "sortColumns": "REPORT_DATE",
        "source": "SECURITIES",
        "client": "PC",
    }
    page_url = _us_eastmoney_page_url(ticker)
    payload = _read_json(
        _eastmoney_json_url(params),
        source=US_EASTMONEY_SOURCE,
        max_bytes=1_000_000,
        referer=page_url,
    )
    result = payload.get("result") if isinstance(payload, dict) else None
    rows = result.get("data") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise FinancialDisclosureDataError(
            "东方财富 USF10 未返回财务指标"
        )
    candidates = [
        row
        for row in rows[:_US_EASTMONEY_PAGE_SIZE]
        if isinstance(row, dict)
        and _date(row.get("REPORT_DATE"))
        and _US_REPORTED_PERIOD_RE.fullmatch(
            str(row.get("REPORT_TYPE") or "").strip()
        )
        and str(row.get("SECUCODE") or "").strip().upper() == secu_code
        and str(row.get("SECURITY_CODE") or "").strip().upper() == ticker
    ]
    if not candidates:
        raise FinancialDisclosureDataError(
            "东方财富 USF10 没有可核实的 FY 或季度财报"
        )
    candidates.sort(
        key=lambda row: (
            _date(row.get("REPORT_DATE")) or "",
            str(row.get("REPORT_TYPE") or "").upper().endswith("/FY"),
            _date(row.get("NOTICE_DATE")) or "",
        ),
        reverse=True,
    )
    row = candidates[0]
    report_date = _date(row.get("REPORT_DATE"))
    published_at = _date(row.get("NOTICE_DATE"))
    currency = _us_report_currency(row)
    items: list[dict[str, Any]] = []
    for key, label, source_key, unit_type in _US_EASTMONEY_METRICS:
        value = _number(row.get(source_key))
        if value is None:
            continue
        if unit_type in {"currency", "per_share"}:
            if currency is None:
                continue
            unit = currency if unit_type == "currency" else f"{currency}/股"
        else:
            unit = unit_type
        items.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "unit": unit,
                "reportDate": report_date,
                "publishedAt": published_at,
            }
        )
    if not items:
        raise FinancialDisclosureDataError(
            "东方财富 USF10 当前报告期没有可核实的财务指标"
        )
    error = None
    if currency is None:
        error = "本期财报币种未能核实，已隐藏金额和每股指标"
    elif len(items) < len(_US_EASTMONEY_METRICS):
        error = "东方财富 USF10 未包含部分指标，仅显示该报告期可核实字段"
    return _available(
        US_EASTMONEY_SOURCE,
        page_url,
        items,
        report_date=report_date,
        published_at=published_at,
        error=error,
    )


def _load_us_eastmoney_fundamentals(stock: dict[str, Any]) -> dict[str, Any]:
    candidates = tuple(_us_eastmoney_ticker_candidates(stock))
    return _load_cached(
        ("financial-disclosures-v1", "us-eastmoney-fundamentals", candidates),
        _US_FUNDAMENTALS_CACHE_SECONDS,
        lambda: _load_us_eastmoney_fundamentals_uncached(stock),
    )


def _with_sec_fallback_note(
    fallback: dict[str, Any], sec_error: str
) -> dict[str, Any]:
    result = dict(fallback)
    if result.get("status") == "available":
        note = (
            f"SEC EDGAR 主源失败：{str(sec_error).strip()[:100]}；"
            "当前数据来自东方财富 USF10，未经 SEC 核验"
        )
        if result.get("error"):
            note += f"；{result['error']}"
    else:
        note = (
            f"SEC EDGAR 主源失败：{str(sec_error).strip()[:75]}；"
            "东方财富 USF10 备用源失败："
            f"{str(result.get('error') or '数据不可用').strip()[:90]}"
        )
    result["error"] = note[:300]
    return result


def _safe_facet(loader, source: str, source_url: str, *, fundamentals: bool = False):
    try:
        return loader()
    except (
        FinancialDisclosureDataError,
        HTTPError,
        URLError,
        OSError,
        TimeoutError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
    ) as exc:
        return _unavailable(source, source_url, exc, fundamentals=fundamentals)


def fetch_international_facets(stock: dict[str, Any]) -> dict[str, Any]:
    """Return independent announcements and fundamentals facets for HK or US."""
    symbol = str(stock.get("symbol") or "").strip()
    if symbol.lower().startswith("hk"):
        try:
            code = _hk_code(stock)
            stock_id = _hk_stock_ids().get(code, "")
            announcement_url = _hk_title_search_url(stock_id) if stock_id else HKEX_TITLE_SEARCH_URL + "?lang=en"
        except (FinancialDisclosureDataError, TypeError, AttributeError):
            announcement_url = HKEX_TITLE_SEARCH_URL + "?lang=en"
        try:
            code = _hk_code(stock)
            fundamentals_url = f"{HK_EASTMONEY_FUNDAMENTALS_URL}?type=web&code={code}"
        except (FinancialDisclosureDataError, TypeError, AttributeError):
            fundamentals_url = HK_EASTMONEY_FUNDAMENTALS_URL
        return {
            "announcements": _safe_facet(
                lambda: _load_hk_announcements(stock), HKEX_SOURCE, announcement_url
            ),
            "fundamentals": _safe_facet(
                lambda: _load_hk_fundamentals(stock),
                EASTMONEY_SOURCE,
                fundamentals_url,
                fundamentals=True,
            ),
        }

    if symbol.lower().startswith("us"):
        try:
            ticker = _us_ticker(stock)
        except (FinancialDisclosureDataError, TypeError, AttributeError) as exc:
            unavailable = _unavailable(SEC_SOURCE, SEC_TICKERS_URL, exc)
            return {
                "announcements": dict(unavailable),
                "fundamentals": _unavailable(
                    US_EASTMONEY_SOURCE,
                    US_EASTMONEY_FUNDAMENTALS_URL,
                    exc,
                    fundamentals=True,
                ),
            }
        announcements: dict[str, Any]
        fundamentals: dict[str, Any]
        sec_error: str | None = None
        try:
            cik_entry = _sec_ticker_ids().get(ticker)
            if not cik_entry:
                raise FinancialDisclosureDataError("SEC 未找到该美股交易代码")
        except (
            FinancialDisclosureDataError,
            HTTPError,
            URLError,
            OSError,
            TimeoutError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
        ) as exc:
            sec_error = str(exc) or "SEC 交易代码映射暂不可用"
            announcements = _unavailable(SEC_SOURCE, SEC_TICKERS_URL, exc)
            fundamentals = _unavailable(
                SEC_SOURCE, SEC_TICKERS_URL, exc, fundamentals=True
            )
        else:
            cik = cik_entry[0]
            source_url = SEC_BROWSE_URL.format(cik=str(int(cik)))
            submissions = _safe_facet(
                lambda: _read_json(
                    SEC_SUBMISSIONS_URL.format(cik=cik),
                    source=SEC_SOURCE,
                    max_bytes=_SEC_JSON_MAX_BYTES,
                ),
                SEC_SOURCE,
                source_url,
            )
            if submissions.get("status") == "unavailable":
                announcements = submissions
                fundamentals = _unavailable(
                    SEC_SOURCE,
                    SEC_COMPANY_FACTS_URL.format(cik=cik),
                    submissions.get("error") or "SEC Submissions 暂时不可用",
                    fundamentals=True,
                )
            else:
                announcements = _safe_facet(
                    lambda: _load_us_announcements(ticker, cik, submissions),
                    SEC_SOURCE,
                    source_url,
                )
                fundamentals = _safe_facet(
                    lambda: _load_us_fundamentals(
                        cik,
                        _read_json(
                            SEC_COMPANY_FACTS_URL.format(cik=cik),
                            source=SEC_SOURCE,
                            max_bytes=_SEC_JSON_MAX_BYTES,
                        ),
                        submissions,
                    ),
                    SEC_SOURCE,
                    SEC_COMPANY_FACTS_URL.format(cik=cik),
                    fundamentals=True,
                )
            if fundamentals.get("status") == "unavailable":
                sec_error = str(
                    fundamentals.get("error") or "SEC 财务数据暂不可用"
                )
        if sec_error:
            ticker_candidates = _us_eastmoney_ticker_candidates(stock)
            fallback_ticker = ticker_candidates[0] if ticker_candidates else ""
            fallback = _safe_facet(
                lambda: _load_us_eastmoney_fundamentals(stock),
                US_EASTMONEY_SOURCE,
                _us_eastmoney_page_url(fallback_ticker)
                if fallback_ticker
                else US_EASTMONEY_FUNDAMENTALS_URL,
                fundamentals=True,
            )
            fundamentals = _with_sec_fallback_note(fallback, sec_error)
        return {"announcements": announcements, "fundamentals": fundamentals}

    error = "仅支持 HK 或 US 股票披露数据"
    return {
        "announcements": _unavailable(HKEX_SOURCE, HKEX_TITLE_SEARCH_URL, error),
        "fundamentals": _unavailable(
            EASTMONEY_SOURCE, EASTMONEY_DATA_URL, error, fundamentals=True
        ),
    }
