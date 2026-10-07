"""Project a screening comparison from the Turn's own tool results.

The stored answer stays unchanged. When the request is the canonical screening
prompt and this Turn has a usable ``financial_market_screen_tool`` payload, the
report and export show those candidates. A filing page is filled only when a
same-turn ``financial_evidence_search_tool`` call names that ticker and its
excerpt cites a page. The announcement cell comes only from that screen
result's official annual-report filing when its URL is an allowlisted
exchange document on or before the analysis date. Otherwise the cell is
没有这一项. Quote fields are not filings. No usable screen payload leaves
the answer unchanged.
"""

from __future__ import annotations

import json
import re
from datetime import date

from core.chat.turn_journal import EVENT_TOOL_RESULT
from core.web.services.financial_report.conclusion_figures import (
    MISSING_FIGURE,
    filing_excerpts_from_tool_output,
)
from core.web.services.financial_research.official_filings import accepted_annual_filing

HEADING = "## 筛选对照（本轮工具结果）"
_FAILED = {
    "failed",
    "error",
    "timeout",
    "timed_out",
    "blocked",
    "cancelled",
    "canceled",
    "interrupted",
}
_SCREENING_REPORT_PROMPT = re.compile(
    r"^请研究以下股票筛选条件，生成筛选报告。分析截至 "
    r"(?P<analysis_date>\d{4}-\d{2}-\d{2})。按条件筛选股票，列出候选、筛选依据和数据限制。"
    r"(?:\r?\n|$)"
)
_A_SHARE = re.compile(r"(?<!\d)([036489]\d{5})(?!\d)")
_TICKER_FIELD = re.compile(r'"(?:ticker|symbol)"\s*:\s*"([^"\\]{1,40})"')
_MAX_ROWS = 20
_MAX_PAGES = 12


def is_screening_report_prompt(text: str) -> bool:
    match = _SCREENING_REPORT_PROMPT.match(str(text or "").strip())
    if match is None:
        return False
    try:
        date.fromisoformat(match.group("analysis_date"))
    except ValueError:
        return False
    return True


def project_screening_comparison(
    report_text: str,
    request_text: str,
    items: list | None = None,
    events: list | None = None,
) -> str:
    """Return the report, prefixed by the tool comparison when one exists."""

    original = str(report_text or "")
    if not is_screening_report_prompt(request_text):
        return original
    if original.startswith(HEADING + "\n"):
        return original
    records = _tool_records(items, events)
    payload = _last_screen_payload(records)
    if payload is None:
        return original
    rows = _rows(payload, _analysis_day(request_text))
    block = _render(payload, rows, _pages_by_code(records, {code for _name, code, _filing in rows}))
    if not rows:
        return block
    body = original.strip()
    if not body:
        return block
    return f"{block}\n## 模型原文\n\n候选、公告原文和财报页码以上表为准。\n\n{body}\n"


def _tool_records(items: list | None, events: list | None) -> list[tuple[str, str, str, str]]:
    records: list[tuple[str, str, str, str]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or item.get("kind") or "") != "tool_call":
            continue
        name = str(item.get("toolName") or "").strip()
        output = str(item.get("output") or "")
        if not name or not output:
            continue
        records.append((name, str(item.get("input") or ""), output, str(item.get("status") or "")))
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
            tool_call.get("name") or tool_call.get("toolName") or tool_call.get("tool_name") or ""
        ).strip()
        output = str(tool_call.get("result") or tool_call.get("output") or "")
        if not name or not output:
            continue
        arguments = tool_call.get("arguments")
        if arguments is None:
            arguments = tool_call.get("args")
        if isinstance(arguments, dict):
            try:
                raw_input = json.dumps(arguments, ensure_ascii=False)
            except (TypeError, ValueError):
                raw_input = ""
        else:
            raw_input = str(arguments or "")
        status = str(tool_call.get("status") or getattr(event, "status", "") or "")
        records.append((name, raw_input, output, status))
    return records


def _last_screen_payload(records: list[tuple[str, str, str, str]]) -> dict | None:
    found: dict | None = None
    for name, _raw_input, output, status in records:
        if name != "financial_market_screen_tool" or _failed(status):
            continue
        payload = _screen_payload(output)
        if payload is not None:
            found = payload
    return found


def _screen_payload(output: str) -> dict | None:
    try:
        payload = json.loads(output)
    except (json.JSONDecodeError, TypeError, ValueError, UnicodeError):
        return None
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return None
    if str(payload.get("status") or "") not in {"complete", "partial"}:
        return None
    if not isinstance(payload.get("items"), list):
        return None
    return payload


def _pages_by_code(records: list[tuple[str, str, str, str]], codes: set[str]) -> dict[str, str]:
    found: dict[str, set[int]] = {}
    for name, raw_input, output, status in records:
        if name != "financial_evidence_search_tool" or _failed(status):
            continue
        code = _ticker_from_input(raw_input)
        if code not in codes:
            continue
        pages = {page for page, _excerpt in filing_excerpts_from_tool_output(name, output)}
        if pages:
            found.setdefault(code, set()).update(pages)
    return {code: _format_pages(pages) for code, pages in found.items()}


def _analysis_day(request_text: str) -> date:
    match = _SCREENING_REPORT_PROMPT.match(str(request_text or "").strip())
    if match is None:
        raise ValueError("screening comparison requires the canonical analysis date")
    return date.fromisoformat(match.group("analysis_date"))


def _rows(payload: dict, cutoff: date) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    for raw in items[:_MAX_ROWS]:
        if not isinstance(raw, dict):
            continue
        name, code = _identity(raw)
        if code:
            rows.append((name, code, _filing_cell(raw, cutoff)))
    return rows


def _filing_cell(row: dict, cutoff: date) -> str:
    filing = accepted_annual_filing(row.get("officialFiling"), cutoff=cutoff)
    if filing is None:
        return MISSING_FIGURE
    return f"[{filing['title']}（{filing['announcedOn']}）]({filing['url']})"


def _render(payload: dict, rows: list[tuple[str, str, str]], pages: dict[str, str]) -> str:
    lines = [HEADING, ""]
    source = _plain(payload.get("source"), 100)
    fetched = _plain(payload.get("fetchedAt"), 64)
    if source:
        lines.append(f"来源：{source}")
    if fetched:
        lines.append(f"抓取时间：{fetched}")
    lines.append(_coverage_line(payload))
    count = _count_line(payload)
    if count:
        lines.append(count)
    if payload.get("outputTruncated") is True:
        lines.append("工具输出已截断，未列入被省略的候选。")
    message = _plain(payload.get("message"), 240)
    notice = _plain(payload.get("notice"), 240)
    if message:
        lines.append(message)
    if notice and notice != message:
        lines.append(notice)
    lines.append("")
    if not rows:
        lines.append("没有符合条件的候选。")
        return "\n".join(lines).rstrip() + "\n"
    lines.append("| 股票 | 代码 | 公告原文 | 财报页码 |")
    lines.append("| --- | --- | --- | --- |")
    for name, code, filing in rows:
        lines.append(f"| {name} | {code} | {filing} | {pages.get(code) or MISSING_FIGURE} |")
    lines.append("")
    lines.append("行情价格、市盈率和市净率不是财报，不列入本表。")
    lines.append("公告原文只列巨潮资讯或交易所年报链接。")
    return "\n".join(lines).rstrip() + "\n"


def _coverage_line(payload: dict) -> str:
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
    complete = coverage.get("complete") is True
    scope = "覆盖完整。" if complete else "覆盖不完整，结果仅基于已加载范围。"
    loaded = coverage.get("loaded")
    total = coverage.get("providerTotal")
    if _nonnegative_int(loaded) and _nonnegative_int(total):
        return f"已加载 {loaded} / 行情池 {total}。{scope}"
    return scope


def _count_line(payload: dict) -> str:
    returned = payload.get("returnedCount")
    if not _nonnegative_int(returned):
        return ""
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
    filtered = coverage.get("totalFiltered")
    if _nonnegative_int(filtered) and filtered != returned:
        return f"符合条件 {filtered}，本次返回 {returned}。"
    return f"符合条件 {returned}。"


def _identity(row: dict) -> tuple[str, str]:
    ticker = row.get("ticker") if isinstance(row.get("ticker"), str) else ""
    symbol = row.get("symbol") if isinstance(row.get("symbol"), str) else ""
    code = _ticker_key(ticker) or _ticker_key(symbol)
    if not code:
        return "", ""
    name = _plain(row.get("name"), 60) or code
    return name, code


def _ticker_from_input(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError, UnicodeError):
        payload = None
    if isinstance(payload, dict):
        for key in ("ticker", "symbol"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return _ticker_key(value)
    match = _TICKER_FIELD.search(text)
    return _ticker_key(match.group(1)) if match else ""


def _ticker_key(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _A_SHARE.search(text)
    if match:
        return match.group(1)
    compact = re.sub(r"\s+", "", text).upper()
    return compact[:20]


def _format_pages(pages: set[int]) -> str:
    ordered = sorted(pages)
    shown = "、".join(f"第 {page} 页" for page in ordered[:_MAX_PAGES])
    if len(ordered) > _MAX_PAGES:
        return shown + "等"
    return shown


def _plain(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"[\r\n|]+", " ", value).strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _failed(status: str) -> bool:
    return status.strip().lower() in _FAILED
