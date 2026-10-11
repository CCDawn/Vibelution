"""Project a screening comparison from the Turn's own tool results.

The stored answer stays unchanged. When the request is the canonical screening
prompt and this Turn has a usable ``financial_market_screen_tool`` payload, the
report and export show those candidates. A filing page is filled only when a
same-turn ``financial_evidence_search_tool`` call names that ticker and its
excerpt cites a page. The announcement cell names the annual report,
semi-annual report, first-quarter report, and third-quarter report. Each
kind is an allowlisted exchange document on or before the analysis date,
or 没有这一项. Quote fields are not filings. No usable screen payload
leaves the answer unchanged.
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
from core.web.services.financial_research.official_filings import (
    accepted_annual_filing,
    accepted_periodic_filing,
)

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
    batches = _screen_batches(records)
    if not batches:
        return original
    cutoff = _analysis_day(request_text)
    rendered = []
    has_rows = False
    for index, (raw_input, payload, _output) in enumerate(batches, start=1):
        rows = _rows(payload, cutoff)
        has_rows = has_rows or bool(rows)
        rendered.append(
            _render_batch(
                payload,
                rows,
                _pages_by_code(records, {code for _name, code, _filing in rows}),
                batch_number=index,
                raw_input=raw_input,
            )
        )
    block_lines = [HEADING, ""]
    if len(batches) > 1:
        block_lines.extend(
            [
                f"本轮包含 {len(batches)} 个独立筛选快照。筛选条件或抓取时间不同的批次分别展示，不合并为一个候选集合。",
                "",
            ]
        )
    block_lines.extend("\n".join(rendered).splitlines())
    block = "\n".join(block_lines).rstrip() + "\n"
    if not has_rows:
        # An unusable or cleared screen must not preserve model-invented stock
        # candidates. The screen source's warning remains the visible result.
        return block
    body = original.strip()
    if not body:
        return block
    return f"{block}\n## 模型正文（未经工具候选校验）\n\n{body}\n"


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
    deduplicated: list[tuple[str, str, str, str]] = []
    positions: dict[tuple[str, str, str], int] = {}
    for record in records:
        key = record[:3]
        previous_index = positions.get(key)
        if previous_index is None:
            positions[key] = len(deduplicated)
            deduplicated.append(record)
            continue
        previous = deduplicated[previous_index]
        if _failed(previous[3]) and not _failed(record[3]):
            deduplicated[previous_index] = record
        elif not _failed(record[3]):
            deduplicated[previous_index] = record
    return deduplicated


def _screen_batches(
    records: list[tuple[str, str, str, str]],
) -> list[tuple[str, dict, str]]:
    found: list[tuple[str, dict, str]] = []
    positions: dict[str, int] = {}
    for name, _raw_input, output, status in records:
        if name != "financial_market_screen_tool" or _failed(status):
            continue
        payload = _screen_payload(output)
        if payload is None:
            continue
        criteria = _screen_criteria_key(payload, _raw_input)
        snapshot = _screen_snapshot_key(payload, output)
        batch_key = json.dumps([criteria, snapshot], ensure_ascii=True, sort_keys=True)
        previous_index = positions.get(batch_key)
        record = (_raw_input, payload, output)
        if previous_index is None:
            positions[batch_key] = len(found)
            found.append(record)
        else:
            # A retry for the same filters and same source snapshot is one
            # observation; the latest returned payload is authoritative.
            found[previous_index] = record
    return found


def _screen_criteria_key(payload: dict, raw_input: str) -> dict:
    arguments = _screen_arguments(raw_input)
    filters = payload.get("requestedFilters")
    if not isinstance(filters, dict):
        filters = _requested_filter_arguments(arguments)
    return {
        "filters": {key: filters[key] for key in sorted(filters)},
        "sortBy": payload.get("sortBy") or arguments.get("sort_by"),
        "direction": payload.get("direction") or arguments.get("direction"),
        "page": payload.get("requestedPage") or payload.get("page") or arguments.get("page", 1),
        # Limit is part of the request: different page sizes can return distinct
        # windows from the same filter set and market snapshot.
        "limit": payload.get("requestedLimit") or arguments.get("limit"),
    }


def _screen_arguments(raw_input: str) -> dict:
    try:
        arguments = json.loads(raw_input)
    except (json.JSONDecodeError, TypeError, ValueError, UnicodeError):
        return {}
    return arguments if isinstance(arguments, dict) else {}


def _requested_filter_arguments(arguments: dict) -> dict:
    return {
        key: arguments[key]
        for key, _label in _FILTER_LABELS
        if key in arguments and arguments[key] is not None
    }


def _screen_snapshot_key(payload: dict, output: str) -> dict:
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
    fetched_at = payload.get("fetchedAt")
    if not isinstance(fetched_at, str) or not fetched_at.strip():
        return {"exactOutput": output}
    return {
        "fetchedAt": fetched_at,
        "source": payload.get("source"),
        "dataDate": payload.get("dataDate"),
        "dataTime": payload.get("dataTime"),
        "providerTotal": coverage.get("providerTotal"),
        "loaded": coverage.get("loaded"),
        "complete": coverage.get("complete"),
        "totalFiltered": coverage.get("totalFiltered"),
    }


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


_FILING_LABELS = (
    ("annual", "年报"),
    ("semiannual", "半年报"),
    ("q1", "一季报"),
    ("q3", "三季报"),
)


def _filing_cell(row: dict, cutoff: date) -> str:
    found: dict[str, dict[str, str]] = {}
    raw_periodic = row.get("periodicFilings")
    if isinstance(raw_periodic, list):
        for raw in raw_periodic[:8]:
            record = accepted_periodic_filing(raw, cutoff=cutoff)
            if record is None:
                continue
            prior = found.get(record["kind"])
            if prior is None or record["announcedOn"] > prior["announcedOn"]:
                found[record["kind"]] = record
    annual = accepted_annual_filing(row.get("officialFiling"), cutoff=cutoff)
    if annual is not None:
        found["annual"] = annual
    parts: list[str] = []
    for kind, label in _FILING_LABELS:
        record = found.get(kind)
        if record is None:
            parts.append(f"{label}：{MISSING_FIGURE}")
        else:
            parts.append(f"{label}：[{record['title']}（{record['announcedOn']}）]({record['url']})")
    return "；".join(parts)


_FILTER_LABELS = (
    ("min_price", "最低股价"),
    ("max_price", "最高股价"),
    ("min_change_percent", "最小涨幅"),
    ("max_change_percent", "最大涨幅"),
    ("min_pe", "市盈率下限"),
    ("max_pe", "市盈率上限"),
    ("min_volume_lots", "成交量下限"),
    ("min_pb", "市净率下限"),
    ("max_pb", "市净率上限"),
    ("min_turnover_yuan", "成交额下限"),
    ("max_turnover_yuan", "成交额上限"),
)
_FILTER_UNITS = {
    "min_price": "元",
    "max_price": "元",
    "min_change_percent": "%",
    "max_change_percent": "%",
    "min_pe": "倍",
    "max_pe": "倍",
    "min_volume_lots": "手",
    "min_pb": "倍",
    "max_pb": "倍",
    "min_turnover_yuan": "元",
    "max_turnover_yuan": "元",
}


def _render_batch(
    payload: dict,
    rows: list[tuple[str, str, str]],
    pages: dict[str, str],
    *,
    batch_number: int,
    raw_input: str = "",
) -> str:
    arguments = _screen_arguments(raw_input)
    lines = [f"### 筛选批次 {batch_number}", f"筛选条件：{_filter_line(payload, arguments)}"]
    sort_by = _plain(payload.get("sortBy"), 50)
    direction = _plain(payload.get("direction"), 20)
    if not sort_by:
        sort_by = _plain(arguments.get("sort_by"), 50)
    if not direction:
        direction = _plain(arguments.get("direction"), 20)
    requested_page = payload.get("requestedPage") or payload.get("page") or arguments.get("page", 1)
    requested_limit = payload.get("requestedLimit") or arguments.get("limit")
    page_text = f"第 {requested_page} 页" if _positive_int(requested_page) else "页码未提供"
    limit_text = f"请求上限 {requested_limit} 条" if _positive_int(requested_limit) else "请求上限未提供"
    if sort_by or direction:
        sort_labels = {"changePercent": "涨跌幅", "peRatio": "市盈率", "pbRatio": "市净率", "turnoverYuan": "成交额", "volumeLots": "成交量", "price": "价格"}
        direction_label = {"asc": "升序", "desc": "降序"}.get(direction, direction)
        sort_text = f"排序：{sort_labels.get(sort_by, sort_by or '未提供')} {direction_label}".strip()
    else:
        sort_text = "排序：未提供"
    lines.append(f"{sort_text}；{page_text}；{limit_text}。")
    source = _plain(payload.get("source"), 100)
    fetched = _plain(payload.get("fetchedAt"), 64)
    if source:
        lines.append(f"来源：{source}")
    if fetched:
        lines.append(f"抓取时间：{fetched}")
    data_date = _plain(payload.get("dataDate"), 40)
    data_time = _plain(payload.get("dataTime"), 40)
    if data_date or data_time:
        lines.append(f"行情时间：{' '.join(value for value in (data_date, data_time) if value)}")
    lines.append(_coverage_line(payload))
    count = _count_line(payload)
    if count:
        lines.append(count)
    if payload.get("outputTruncated") is True:
        omitted = payload.get("omittedCount")
        if _nonnegative_int(omitted) and omitted:
            lines.append(f"工具输出受长度限制，本次请求另有 {omitted} 只候选未列出。")
        else:
            lines.append("工具输出受长度限制，候选详情不完整。")
    message = _plain(payload.get("message"), 240)
    notice = _plain(payload.get("notice"), 240)
    if message:
        lines.append(message)
    if notice and notice != message:
        lines.append(notice)
    lines.append("")
    if not rows:
        total = (payload.get("coverage") or {}).get("totalFiltered") if isinstance(payload.get("coverage"), dict) else None
        if total == 0 and (payload.get("coverage") or {}).get("complete") is True:
            lines.append("完整股票池内没有符合条件的候选。")
        else:
            lines.append("本批次没有返回可核验的候选明细，不能据此断定完整股票池内没有符合条件的股票。")
        return "\n".join(lines).rstrip() + "\n"
    lines.append("| 股票 | 代码 | 公告原文 | 财报页码 |")
    lines.append("| --- | --- | --- | --- |")
    for name, code, filing in rows:
        lines.append(f"| {name} | {code} | {filing} | {pages.get(code) or MISSING_FIGURE} |")
    lines.append("")
    lines.append("行情价格、市盈率和市净率不是财报，不列入本表。")
    lines.append("公告原文只列巨潮资讯或交易所的年报、半年报、一季报和三季报链接。")
    return "\n".join(lines).rstrip() + "\n"


def _filter_line(payload: dict, arguments: dict | None = None) -> str:
    filters = payload.get("requestedFilters")
    if not isinstance(filters, dict):
        filters = _requested_filter_arguments(arguments or {})
    if not filters:
        if "requestedFilters" in payload or arguments:
            return "无额外阈值（从工具请求参数确认）。"
        return "工具未提供可核对的筛选阈值。"
    parts: list[str] = []
    for key, label in _FILTER_LABELS:
        value = filters.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            rendered = _plain(str(value), 60)
        elif isinstance(value, int):
            rendered = f"{value:,}"
        else:
            rendered = f"{value:,.8f}".rstrip("0").rstrip(".")
        unit = _FILTER_UNITS.get(key, "")
        operator = "≥" if key.startswith("min_") else "≤"
        parts.append(f"{label} {operator} {rendered}{unit}")
    return "；".join(parts) if parts else "无额外阈值（按工具股票池查询）。"


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
        return f"符合条件 {filtered} 只；本批次返回 {returned} 只。"
    return f"符合条件 {returned} 只；本批次返回 {returned} 只。"


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


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _failed(status: str) -> bool:
    return status.strip().lower() in _FAILED
