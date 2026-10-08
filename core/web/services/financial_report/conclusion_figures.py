"""Hide ungrounded amounts in a financial research conclusion.

The stored Session answer stays unchanged. A conclusion amount stays only when
the same number is on a filing page the report cites, or when the conclusion
writes an arithmetic expression whose operands are those page numbers and this
module evaluates to the written result.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from core.chat.turn_journal import EVENT_TOOL_RESULT

MISSING_FIGURE = "没有这一项"
_MAX_DIGITS = 40
_FAILED_TOOL_STATUSES = {
    "failed",
    "error",
    "timeout",
    "timed_out",
    "blocked",
    "cancelled",
    "canceled",
    "interrupted",
}
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_HEADING = re.compile(r"(?m)^[ \t]{0,3}#{1,3}[ \t]+(?P<title>.+?)[ \t]*$")
_BOLD_HEADING = re.compile(
    r"(?m)^[ \t]{0,3}\*\*(?P<title>[^*\r\n]{1,60}?)\*\*"
    r"(?P<after>[ \t]*(?::|：)?[ \t]*(?P<body>.*))[ \t]*$"
)
_CONCLUSION_TITLE = re.compile(r"结论|摘要|简报|summary|conclusion", re.IGNORECASE)
_BOLD_SECTION_TITLE = re.compile(
    r"(?:结论|摘要|简报|关键事实|核心事实|风险|建议|summary|conclusions?|"
    r"key facts|facts|risks?|recommendations?)",
    re.IGNORECASE,
)
_PAGE = re.compile(
    r"第\s*(\d{1,6})\s*页|PDF\s*(\d{1,6})\s*页|\b(?:p\.|page\s+)(\d{1,6})\b",
    re.IGNORECASE,
)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_UNIT = (
    r"(?:%|％|万亿|亿元|万元|港元|美元|元(?:\s*/\s*股)?|股|"
    r"(?:CNY|RMB|HKD|USD)(?:\s*/\s*(?:股|share))?)"
)
_NUMBER = r"(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d+)?"
_PRICE_LABEL = (
    r"(?:最新公开报价|最新报价|股价|价格|收盘价|收盘|(?<![\u4e00-\u9fff])收|latest\s+quote|"
    r"stock\s+price|share\s+price)"
)
_PRICE_CLAIM = re.compile(
    rf"(?P<bold_open>\*\*)?(?P<label>{_PRICE_LABEL})(?(bold_open)\*\*)"
    rf"\s*(?:为|是|[:：])?\s*(?:\*\*)?"
    rf"(?P<number>{_NUMBER})\s*(?P<unit>"
    r"(?:CNY\s*元|RMB\s*元?|HKD\s*港元|USD\s*美元|"
    r"CNY|RMB|HKD|USD|港元|美元|元)"
    r"(?:\s*/\s*(?:股|share))?)\s*(?:\*\*)?",
    re.IGNORECASE,
)
_METRIC_CLAIM = re.compile(
    rf"(?<![A-Za-z])(?P<label>PB|PE|市净率|市盈率|涨跌幅)(?![A-Za-z])"
    rf"(?:\*\*)?\s*(?:为|是|[:：])?\s*(?:\*\*)?"
    rf"(?P<number>[+-]?{_NUMBER})(?P<unit>\s*[%％])?",
    re.IGNORECASE,
)
_FOLLOWING_CHANGE = re.compile(
    rf"[ \t*]*[、，,][ \t*]*(?P<number>[+-]?{_NUMBER})(?P<unit>\s*[%％])"
)
_CLAIM_DATE = re.compile(r"(?<!\d)(?P<date>(?:\d{4}-)?\d{2}-\d{2})(?!\d)")
_METRIC_FIELDS = {
    "pb": "pbRatio", "市净率": "pbRatio",
    "pe": "peRatio", "市盈率": "peRatio",
    "涨跌幅": "changePercent",
}
_MARKET_TOOL_STATUSES = {"completed", "success", "partial", "degraded"}
_MARKET_PAYLOAD_STATUSES = {"ok", "partial"}
_US_PROVIDER_SUFFIX = re.compile(r"\.(?:OQ|N|AM|PK|PNK|NYSE|NASDAQ)$", re.IGNORECASE)
_HIGH_RISK_CLAIM = re.compile(
    r"财报|财务报告|年报|季报|营收|营业收入|主营收入|收入|净利(?:润)?|利润|"
    r"现金流|经营现金流|自由现金流|财务指标|财务数据|"
    r"目标|预测|预期|预计|未来|forecast|revenue|net\s+income|"
    r"profit|earnings|cash\s+flow|target\s+price",
    re.IGNORECASE,
)
_STOCK_CODE = re.compile(
    r"(?i)(?<![A-Z0-9])(?:sh6\d{5}|sz[03]\d{5}|bj[489]\d{5}|hk\d{5}|"
    r"us[A-Z][A-Z0-9.\-]{0,9})(?![A-Z0-9])|(?<!\d)\d{6}(?!\d)"
)
_MARKDOWN_LINK = re.compile(r"!?\[[^\]\r\n]*\]\([^\)\r\n]*\)")
_INLINE_CODE = re.compile(r"`+[^`\r\n]*`+")
_URL = re.compile(r"https?://[^\s\]\[<>()}]+", re.IGNORECASE)
_FINANCIAL_SOURCE_URL = re.compile(
    r"https://gu\.qq\.com/(?:(?:sh6\d{5}|sz[03]\d{5}|bj[489]\d{5})|"
    r"hk\d{5}|us[A-Z][A-Z0-9.\-]{0,9})/gp",
    re.IGNORECASE,
)
_URL_CHINESE_PUNCTUATION = frozenset("，。；：！？、）】》」』")
_SENTENCE_BOUNDARY = re.compile(r"[。！？!?；;]|\.(?!\d)")
_AMOUNT = re.compile(
    rf"(?<![\d.])(?P<sign>[+-])?(?P<number>{_NUMBER})(?![\d.])(?P<unit>\s*{_UNIT})?",
    re.IGNORECASE,
)
_SCIENCE = re.compile(r"(?<![\d.])[+-]?\d+(?:\.\d+)?[eE][+-]?\d+(?![\d])")
_OPERATOR_GAP = re.compile(r"\s*([+＋×*/／÷]|[-－−])\s*")
_EQUALS_GAP = re.compile(r"\s*(?:=|＝|≈|约等于|约为)\s*")
_OPERATORS = {
    "+": "+",
    "＋": "+",
    "-": "-",
    "－": "-",
    "−": "-",
    "*": "*",
    "×": "*",
    "/": "/",
    "／": "/",
    "÷": "/",
}


def ground_report_text(
    report_text: str,
    excerpts: list[tuple[int, str]],
    kept_spans: list[tuple[int, int]] | None = None,
) -> str:
    """Return the report with ungrounded conclusion amounts replaced."""

    original = str(report_text or "")
    text = original.translate(_FULLWIDTH_DIGITS)
    if not text:
        return original
    pages = _cited_pages(text)
    allowed: set[str] = set()
    for page, excerpt in excerpts:
        if page in pages and excerpt:
            allowed |= _numbers_in_text(excerpt)
    spans = _conclusion_spans(text)
    if not spans:
        return original
    fences = [(match.start(), match.end()) for match in _FENCE.finditer(text)]
    page_numbers = set(allowed)
    computed = set(page_numbers)
    kept: list[tuple[int, int]] = []
    for start, end in spans:
        known = set(computed)
        for _ in range(4):
            added, positions = _confirmed_results(text[start:end], known, start, fences, text)
            if added <= known:
                break
            known |= added
            kept.extend((start + left, start + right) for left, right in positions)
        computed = known
    return _replace_amounts(
        original,
        text,
        spans,
        page_numbers,
        [*kept, *(kept_spans or [])],
        fences,
    )


def ground_completed_report(report_text: str, items: list, events: list) -> str:
    """Ground one completed Turn without reading anything outside that Turn."""

    records = _tool_records(items, events)
    return ground_report_records(report_text, records)


def ground_report_records(report_text: str, records: list[tuple[str, str, str]]) -> str:
    """Apply the same checker to caller-authorized original tool records."""
    market_kept = _market_quote_spans(str(report_text or ""), records)
    from core.web.services.financial_report.market_calculations import (
        market_calculation_spans,
    )

    market_kept.extend(market_calculation_spans(str(report_text or ""), records))
    grounded = ground_report_text(
        report_text,
        excerpts_from_records(records),
        market_kept,
    )
    return _normalize_source_links(grounded)


def excerpts_from_turn(items: list, events: list) -> list[tuple[int, str]]:
    return excerpts_from_records(_tool_records(items, events))


def excerpts_from_records(records: list[tuple[str, str, str]]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for name, output, status in records:
        if status.strip().lower() in _FAILED_TOOL_STATUSES:
            continue
        found.extend(filing_excerpts_from_tool_output(name, output))
    return found


def filing_excerpts_from_tool_output(tool_name: str, output: str) -> list[tuple[int, str]]:
    """Read page excerpts only from reviewed local filing search results."""

    if str(tool_name or "").strip() != "financial_evidence_search_tool":
        return []
    try:
        payload = json.loads(output)
    except (json.JSONDecodeError, TypeError, ValueError, UnicodeError):
        return []
    if not isinstance(payload, dict):
        return []
    pages_by_item: dict[str, list[int]] = {}
    for citation in payload.get("citations") or []:
        if not isinstance(citation, dict):
            continue
        item_id = str(citation.get("knowledgeItemId") or "")
        pages = [
            page
            for meta in citation.get("financialEvidence") or []
            if isinstance(meta, dict)
            for page in [_page(meta.get("page"))]
            if page is not None
        ]
        if item_id and pages:
            pages_by_item[item_id] = pages
    found: list[tuple[int, str]] = []
    for row in payload.get("results") or []:
        if not isinstance(row, dict):
            continue
        excerpt = str(row.get("excerpt") or "")
        if not excerpt.strip():
            continue
        for page in pages_by_item.get(str(row.get("knowledgeItemId") or ""), []):
            found.append((page, excerpt))
    return found


def _page(value: object) -> int | None:
    if type(value) is int and 1 <= value <= 100_000:
        return value
    if isinstance(value, str) and value.isdigit():
        page = int(value)
        if 1 <= page <= 100_000:
            return page
    return None


def _tool_records(items: list, events: list) -> list[tuple[str, str, str]]:
    records: list[tuple[str, str, str]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or item.get("kind") or "") != "tool_call":
            continue
        name = str(item.get("toolName") or "")
        output = str(item.get("output") or "")
        if name and output:
            records.append((name, output, str(item.get("status") or "")))
    for event in events or []:
        if str(getattr(event, "event_type", "") or "") != EVENT_TOOL_RESULT:
            continue
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            continue
        tool_call = payload.get("toolCall") or payload.get("tool_call") or payload
        if not isinstance(tool_call, dict):
            continue
        name = str(
            tool_call.get("name")
            or tool_call.get("toolName")
            or tool_call.get("tool_name")
            or ""
        )
        output = str(tool_call.get("result") or tool_call.get("output") or "")
        status = str(tool_call.get("status") or getattr(event, "status", "") or "")
        if name and output:
            records.append((name, output, status))
    return records


def _market_quote_spans(
    report_text: str,
    records: list[tuple[str, str, str]],
) -> list[tuple[int, int]]:
    conclusion_spans = _conclusion_spans(report_text)
    if not conclusion_spans:
        return []
    quotes = [
        quote
        for name, output, status in records
        if name == "financial_market_snapshot_tool"
        and status.strip().lower() in _MARKET_TOOL_STATUSES
        and len(output) <= 8_000
        for quote in [_market_quote_payload(output)]
        if quote is not None
    ]
    kept: list[tuple[int, int]] = []
    for start, end in conclusion_spans:
        chunk = report_text[start:end]
        for paragraph_start, paragraph_end in _paragraph_spans(chunk):
            paragraph = chunk[paragraph_start:paragraph_end]
            visible = _visible_report_text(paragraph)
            for quote in quotes:
                if not _contains_source_url(paragraph, quote["sourceUrl"]):
                    continue
                if not _contains_quote_identity(visible, quote):
                    continue
                if not _contains_quote_date(paragraph, quote["date"]):
                    continue
                if _contains_other_stock(visible, quote):
                    continue
                for match in _PRICE_CLAIM.finditer(paragraph):
                    currency = _currency_for_unit(match.group("unit"))
                    if currency != quote["currency"]:
                        continue
                    if _amount_decimal(match.group("number")) != quote["price"]:
                        continue
                    if not _safe_quote_claim(paragraph, match):
                        continue
                    amount = _AMOUNT.match(paragraph, match.start("number"))
                    if amount is None or amount.start("number") != match.start("number"):
                        continue
                    kept.append(
                        (
                            start + paragraph_start + amount.start(),
                            start + paragraph_start + amount.end(),
                        )
                    )
    kept.extend(_contextual_market_spans(report_text, conclusion_spans, quotes))
    return kept


def _contextual_market_spans(
    text: str, conclusion_spans: list[tuple[int, int]], quotes: list[dict]
) -> list[tuple[int, int]]:
    """Reuse a single stock's dated source, keeping field-specific occurrences.

    A report-level context requires an unambiguous stock and source. It cannot
    authorize another stock, date, currency, forecast, calculation or metric.
    """
    visible = _visible_report_text(text)
    sources = {match.group(0) for match in _FINANCIAL_SOURCE_URL.finditer(_without_code(text))}
    kept: list[tuple[int, int]] = []
    for quote in quotes:
        if not _contains_quote_identity(visible, quote) or _contains_other_stock(visible, quote):
            continue
        if sources != {quote["sourceUrl"]}:
            continue
        observations = {
            (item["date"], item["price"], item.get("peRatio"), item.get("pbRatio"), item.get("changePercent"))
            for item in quotes if item["symbol"] == quote["symbol"]
        }
        if len(observations) != 1:
            continue
        if not any(
            _contains_source_url(text[left:right], quote["sourceUrl"])
            and _contains_quote_date(text[left:right], quote["date"])
            for left, right in _paragraph_spans(text)
        ):
            continue
        for start, end in conclusion_spans:
            chunk = text[start:end]
            for left, right in _paragraph_spans(chunk, split_list_items=True):
                paragraph = chunk[left:right]
                clean = _without_code(paragraph)
                for match in _PRICE_CLAIM.finditer(clean):
                    if _currency_for_unit(match.group("unit")) != quote["currency"]:
                        continue
                    if _amount_decimal(match.group("number")) != quote["price"]:
                        continue
                    if not _safe_contextual_claim(clean, match, quote):
                        continue
                    amount = _AMOUNT.match(clean, match.start("number"))
                    if amount is None:
                        continue
                    base = start + left
                    kept.append((base + amount.start(), base + amount.end()))
                    change = _FOLLOWING_CHANGE.match(clean, match.end())
                    if change and _amount_decimal(change.group("number")) == quote.get("changePercent"):
                        value = _AMOUNT.match(clean, change.start("number"))
                        if value is not None and _safe_contextual_claim(clean, change, quote):
                            kept.append((base + value.start(), base + value.end()))
                for match in _METRIC_CLAIM.finditer(clean):
                    field = _METRIC_FIELDS[match.group("label").lower()]
                    if bool(match.group("unit")) != (field == "changePercent"):
                        continue
                    if _amount_decimal(match.group("number")) != quote.get(field):
                        continue
                    if not _safe_contextual_claim(clean, match, quote):
                        continue
                    amount = _AMOUNT.match(clean, match.start("number"))
                    if amount is not None and (field == "changePercent" or not amount.group("unit")):
                        kept.append((start + left + amount.start(), start + left + amount.end()))
    return kept


def _safe_contextual_claim(paragraph: str, match: re.Match[str], quote: dict) -> bool:
    prefix = paragraph[:match.start()]
    for boundary in _SENTENCE_BOUNDARY.finditer(prefix):
        prefix = paragraph[boundary.end():match.start()]
    if _HIGH_RISK_CLAIM.search(_visible_report_text(prefix)):
        return False
    if re.search(r"[+\-−×*/÷=＝≈]\s*$", prefix.rstrip().removesuffix("**").rstrip()):
        return False
    for dated in _CLAIM_DATE.finditer(_visible_report_text(paragraph)):
        if dated.group("date") not in {quote["date"], quote["date"][5:]}:
            return False
    # A different explicitly labelled quote date defeats inherited context.
    if re.search(r"行情(?:日期|时点|时间)|报价(?:日期|时点|时间)|quote\s+(?:date|time|timestamp)", paragraph, re.I):
        if not _contains_quote_date(paragraph, quote["date"]):
            return False
    tail = paragraph[match.end():].removeprefix("**").lstrip()
    return re.match(r"[+\-−×*/÷=＝≈]\s*\d", tail) is None


def _market_quote_payload(output: str) -> dict | None:
    try:
        payload = json.loads(output)
    except (json.JSONDecodeError, TypeError, ValueError, UnicodeError):
        return None
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return None
    if str(payload.get("status") or "").strip().lower() not in _MARKET_PAYLOAD_STATUSES:
        return None
    ticker = str(payload.get("ticker") or "").strip()
    currency = str(payload.get("currency") or "").strip().upper()
    source_url = str(payload.get("sourceUrl") or "").strip()
    quote = payload.get("quote")
    if not isinstance(quote, dict):
        return None
    symbol = str(quote.get("symbol") or "").strip()
    quote_ticker = str(quote.get("ticker") or "").strip()
    quote_currency = str(quote.get("currency") or "").strip().upper()
    market = _market_for_symbol(symbol)
    observed_ticker = quote_ticker
    if market is not None and market[0] == "USD":
        observed_ticker = _US_PROVIDER_SUFFIX.sub("", quote_ticker)
    if (
        market is None
        or ticker.casefold() != symbol.casefold()
        or observed_ticker.casefold() != symbol[2:].casefold()
    ):
        return None
    expected_currency, root_price_unit, quote_price_unit = market
    if currency != expected_currency or quote_currency != expected_currency:
        return None
    if payload.get("priceUnit") not in (None, "", root_price_unit):
        return None
    if quote.get("priceUnit") not in (None, "", quote_price_unit):
        return None
    if source_url != f"https://gu.qq.com/{symbol}/gp":
        return None
    timestamp = quote.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp.strip():
        return None
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed_timestamp.tzinfo is None:
        return None
    raw_price = quote.get("price")
    if isinstance(raw_price, bool) or not isinstance(raw_price, (int, float)):
        return None
    if not math.isfinite(float(raw_price)) or float(raw_price) <= 0:
        return None
    try:
        price = Decimal(str(raw_price))
    except (ArithmeticError, ValueError):
        return None
    if not price.is_finite() or price <= 0:
        return None
    metrics: dict[str, Decimal] = {}
    for field in ("changePercent", "peRatio", "pbRatio"):
        value = quote.get(field)
        if type(value) in (int, float) and math.isfinite(value):
            metrics[field] = Decimal(str(value))
    return {
        "symbol": symbol,
        "ticker": symbol[2:],
        "currency": expected_currency,
        "sourceUrl": source_url,
        "date": parsed_timestamp.date().isoformat(),
        "price": price,
        **metrics,
    }


def _market_for_symbol(symbol: str) -> tuple[str, str, str] | None:
    if re.fullmatch(r"(?:sh6\d{5}|sz[03]\d{5}|bj[489]\d{5})", symbol):
        return "CNY", "元", "CNY/share"
    if re.fullmatch(r"hk\d{5}", symbol):
        return "HKD", "HKD/share", "HKD/share"
    if re.fullmatch(r"us[A-Z][A-Z0-9.\-]{0,9}", symbol, re.IGNORECASE):
        return "USD", "USD/share", "USD/share"
    return None


def _paragraph_spans(text: str, *, split_list_items: bool = False) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    pattern = r"\r?\n[ \t]*\r?\n"
    if split_list_items:
        pattern += r"|\r?\n(?=[ \t]*(?:[-*+] |\d+[.)] ))"
    for separator in re.finditer(pattern, text):
        if separator.start() > cursor:
            spans.append((cursor, separator.start()))
        cursor = separator.end()
    if cursor < len(text):
        spans.append((cursor, len(text)))
    return spans


def _visible_report_text(text: str) -> str:
    value = _without_code(text)
    value = _MARKDOWN_LINK.sub(
        lambda match: re.sub(r"https?://[^\s)]+", "", match.group(0), flags=re.IGNORECASE),
        value,
    )
    return _URL.sub(" ", value)


def _without_code(text: str) -> str:
    value = _FENCE.sub(lambda match: " " * len(match.group(0)), text)
    return _INLINE_CODE.sub(lambda match: " " * len(match.group(0)), value)


def _contains_source_url(text: str, source_url: str) -> bool:
    return source_url in _without_code(text)


def _contains_quote_identity(text: str, quote: dict) -> bool:
    for identity in {quote["symbol"], quote["ticker"]}:
        if not identity:
            continue
        if identity.isdigit():
            if re.search(rf"(?<!\d){re.escape(identity)}(?!\d)", text):
                return True
        elif re.search(
            rf"(?<![A-Za-z0-9.\-]){re.escape(identity)}(?![A-Za-z0-9.\-])",
            text,
            re.IGNORECASE,
        ):
            return True
    return False


def _contains_quote_date(text: str, quote_date: str) -> bool:
    year, month, day = (int(part) for part in quote_date.split("-"))
    return re.search(
        rf"(?:行情(?:日期|时点|时间)|报价(?:日期|时点|时间)|quote\s+(?:date|time|timestamp))"
        rf"[ \t*]*(?:为|是|[:：])?[ \t*]*(?<!\d){year:04d}-{month:02d}-{day:02d}(?!\d)",
        text,
        re.IGNORECASE,
    ) is not None


def _contains_other_stock(text: str, quote: dict) -> bool:
    visible = text
    for match in _PRICE_CLAIM.finditer(visible):
        visible = visible.replace(match.group(0), " " * len(match.group(0)))
    expected = {quote["symbol"].casefold(), quote["ticker"].casefold()}
    for match in _STOCK_CODE.finditer(visible):
        code = match.group(0).lower()
        if code not in expected and code.removeprefix("sh").removeprefix("sz").removeprefix("bj") not in expected:
            return True
    return False


def _currency_for_unit(unit: str) -> str | None:
    value = re.sub(r"\s+", "", str(unit or "")).lower()
    if value.startswith(("cny", "rmb", "人民币", "元")):
        return "CNY"
    if value.startswith(("hkd", "港元")):
        return "HKD"
    if value.startswith(("usd", "美元")):
        return "USD"
    return None


def _amount_decimal(value: str) -> Decimal | None:
    try:
        amount = Decimal(str(value).replace(",", "").replace("，", ""))
    except (ArithmeticError, ValueError):
        return None
    return amount if amount.is_finite() else None


def _safe_quote_claim(paragraph: str, match: re.Match[str]) -> bool:
    start, end = match.span()
    sentence_start = 0
    sentence_end = len(paragraph)
    for boundary in _SENTENCE_BOUNDARY.finditer(paragraph):
        if boundary.end() <= start:
            sentence_start = boundary.end()
        elif boundary.start() >= end:
            sentence_end = boundary.start()
            break
    prefix = _visible_report_text(paragraph[sentence_start:start])
    if _HIGH_RISK_CLAIM.search(prefix):
        return False
    # A quoted share price is a raw quote. It cannot authorize arithmetic or
    # another numeric claim attached to that price statement.
    tail = _visible_report_text(paragraph[end:sentence_end])
    tail = re.sub(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", " ", tail)
    if re.search(r"(?:[+\-−×*/÷=＝≈]\s*\d|\d\s*[+\-−×*/÷=＝≈])", tail):
        return False
    return True


def _normalize_source_links(text: str) -> str:
    """Protect bare Tencent quote URLs from adjacent Chinese punctuation."""

    if not text:
        return text
    protected = [
        (match.start(), match.end())
        for pattern in (_FENCE, _INLINE_CODE, _MARKDOWN_LINK)
        for match in pattern.finditer(text)
    ]
    patches: list[tuple[int, int]] = []
    for match in _FINANCIAL_SOURCE_URL.finditer(text):
        if _inside(protected, match.start()):
            continue
        if match.start() > 0 and text[match.start() - 1] == "<":
            continue
        if match.end() < len(text) and text[match.end()] in _URL_CHINESE_PUNCTUATION:
            patches.append((match.start(), match.end()))
    for start, end in reversed(patches):
        text = text[:start] + "<" + text[start:end] + ">" + text[end:]
    return text


def _cited_pages(text: str) -> set[int]:
    pages: set[int] = set()
    for match in _PAGE.finditer(text):
        raw = next(group for group in match.groups() if group)
        page = int(raw)
        if 1 <= page <= 100_000:
            pages.add(page)
    return pages


def _conclusion_spans(text: str) -> list[tuple[int, int]]:
    headings: list[tuple[int, int, str, int]] = []
    markdown_headings = list(_HEADING.finditer(text))
    bold_headings = []
    for heading in markdown_headings:
        headings.append((heading.start(), heading.end(), heading.group("title"), heading.end()))
    for heading in _BOLD_HEADING.finditer(text):
        title = heading.group("title").strip().rstrip(":：").strip()
        body = heading.group("body") or ""
        if body.strip() and not _BOLD_SECTION_TITLE.search(title):
            continue
        body_start = heading.start("body") if body.strip() else heading.end()
        headings.append((heading.start(), heading.end(), title, body_start))
        bold_headings.append(heading)
    headings.sort(key=lambda heading: (heading[0], heading[1]))
    spans: list[tuple[int, int]] = []
    for index, heading in enumerate(headings):
        if not _CONCLUSION_TITLE.search(heading[2]):
            continue
        start = heading[3]
        end = headings[index + 1][0] if index + 1 < len(headings) else len(text)
        spans.append((start, end))
    if spans:
        return spans
    if markdown_headings or bold_headings:
        return []
    return [(0, len(text))]


def _numbers_in_text(text: str) -> set[str]:
    found: set[str] = set()
    for match in _AMOUNT.finditer(str(text or "").translate(_FULLWIDTH_DIGITS)):
        canonical = _canonical(match)
        if canonical is not None:
            found.add(canonical)
    return found


def _is_amount(match: re.Match[str]) -> bool:
    number = match.group("number") or ""
    digits = re.sub(r"\D", "", number)
    if not digits or len(digits) > _MAX_DIGITS:
        return False
    return bool(match.group("unit")) or any(mark in number for mark in (".", ",", "，"))


def _canonical_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _canonical(match: re.Match[str]) -> str | None:
    if not _is_amount(match):
        return None
    try:
        return _canonical_decimal(_decimal_from_match(match))
    except (ArithmeticError, ValueError):
        return None


def _keeps_amount(match: re.Match[str], known: set[str], chunk: str) -> bool:
    canonical = _canonical(match)
    if canonical is None or canonical in known:
        return True
    if match.group("sign") != "-":
        return False
    absolute = _absolute_key(match)
    if absolute not in known:
        return False
    previous = chunk[match.start() - 1] if match.start() else ""
    return previous == "" or previous.isspace()


def _absolute_key(match: re.Match[str]) -> str | None:
    try:
        return _canonical_decimal(abs(_decimal_from_match(match)))
    except (ArithmeticError, ValueError):
        return None


def _decimal_from_match(match: re.Match[str]) -> Decimal:
    raw = (match.group("number") or "").replace(",", "").replace("，", "")
    value = Decimal(raw)
    if match.group("sign") == "-":
        value = -value
    return value


def _written_places(match: re.Match[str]) -> int:
    number = (match.group("number") or "").replace(",", "").replace("，", "")
    if "." not in number:
        return 0
    return len(number.split(".", 1)[1])


def _is_percent(match: re.Match[str]) -> bool:
    unit = match.group("unit") or ""
    return "%" in unit or "％" in unit


def _rounds_to(computed: Decimal, match: re.Match[str]) -> bool:
    places = _written_places(match)
    quantum = Decimal(1).scaleb(-places)
    return computed.quantize(quantum, rounding=ROUND_HALF_UP) == _decimal_from_match(match)


def _inside_url(text: str, index: int) -> bool:
    window = text[max(0, index - 300) : index]
    start = max(window.rfind("http://"), window.rfind("https://"))
    if start < 0:
        return False
    return not any(char.isspace() for char in window[start:])


def _inside(spans: list[tuple[int, int]], index: int) -> bool:
    return any(start <= index < end for start, end in spans)


def _operator(text: str) -> str | None:
    match = _OPERATOR_GAP.fullmatch(text)
    if match is None:
        return None
    return _OPERATORS.get(match.group(1))


def _right_operand(chunk: str, left: re.Match[str], right: re.Match[str]) -> tuple[str, Decimal] | None:
    gap = chunk[left.end() : right.start()]
    operator = _operator(gap)
    value = _decimal_from_match(right)
    if operator is not None:
        return operator, value
    # "1.50 - 2.50" puts the minus on the second amount. That is subtraction.
    if right.group("sign") == "-" and gap.strip() == "":
        return "-", abs(value)
    return None


def _confirmed_results(
    chunk: str,
    known: set[str],
    base: int,
    fences: list[tuple[int, int]],
    full: str,
) -> tuple[set[str], list[tuple[int, int]]]:
    amounts: list[re.Match[str]] = []
    for match in _AMOUNT.finditer(chunk):
        if _canonical(match) is None:
            continue
        absolute = base + match.start()
        if _inside_url(full, absolute) or _inside(fences, absolute):
            continue
        amounts.append(match)
    found: set[str] = set()
    positions: list[tuple[int, int]] = []
    for index in range(len(amounts) - 2):
        left, right, result = amounts[index : index + 3]
        parsed = _right_operand(chunk, left, right)
        if parsed is None or not _EQUALS_GAP.fullmatch(chunk[right.end() : result.start()]):
            continue
        operator, right_value = parsed
        left_key = _canonical(left)
        subtracted = (
            operator == "-"
            and right.group("sign") == "-"
            and chunk[left.end() : right.start()].strip() == ""
        )
        right_key = _absolute_key(right) if subtracted else _canonical(right)
        if left_key not in known or right_key not in known:
            continue
        written = _confirm_math(left, operator, right_value, result)
        if written:
            found.add(written)
            positions.extend((item.start(), item.end()) for item in (left, right, result))
    return found, positions


def _confirm_math(
    left: re.Match[str],
    operator: str,
    right_value: Decimal,
    result: re.Match[str],
) -> str | None:
    left_value = _decimal_from_match(left)
    try:
        if operator == "+":
            computed = left_value + right_value
        elif operator == "-":
            computed = left_value - right_value
        elif operator == "*":
            computed = left_value * right_value
        else:
            if right_value == 0:
                return None
            computed = left_value / right_value
    except (ArithmeticError, ValueError):
        return None
    candidate = computed * 100 if _is_percent(result) else computed
    if not _rounds_to(candidate, result):
        return None
    return _canonical(result)


def _replace_amounts(
    original: str,
    normalized: str,
    spans: list[tuple[int, int]],
    known: set[str],
    kept: list[tuple[int, int]],
    fences: list[tuple[int, int]],
) -> str:
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        pieces.append(original[cursor:start])
        pieces.append(
            _replace_span(
                original[start:end],
                normalized[start:end],
                start,
                known,
                [(left - start, right - start) for left, right in kept if start <= left and right <= end],
                fences,
                normalized,
            )
        )
        cursor = end
    pieces.append(original[cursor:])
    return "".join(pieces)


def _replace_span(
    original_chunk: str,
    chunk: str,
    base: int,
    known: set[str],
    kept: list[tuple[int, int]],
    fences: list[tuple[int, int]],
    full: str,
) -> str:
    spans: list[tuple[int, int]] = []
    for match in _AMOUNT.finditer(chunk):
        if _keeps_amount(match, known, chunk) or (match.start(), match.end()) in kept:
            continue
        absolute = base + match.start()
        if _inside_url(full, absolute) or _inside(fences, absolute):
            continue
        spans.append((match.start(), match.end()))
    for match in _SCIENCE.finditer(chunk):
        absolute = base + match.start()
        if _inside_url(full, absolute) or _inside(fences, absolute):
            continue
        spans.append((match.start(), match.end()))
    spans.sort(key=lambda item: (item[0], item[0] - item[1]))
    chosen: list[tuple[int, int]] = []
    occupied = -1
    for start, end in spans:
        if start < occupied:
            continue
        chosen.append((start, end))
        occupied = end
    pieces: list[str] = []
    cursor = 0
    for start, end in chosen:
        pieces.append(original_chunk[cursor:start])
        pieces.append(MISSING_FIGURE)
        cursor = end
    pieces.append(original_chunk[cursor:])
    return "".join(pieces)
