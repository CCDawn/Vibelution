"""A paginated projection of native completed Turns, never a report database."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date as calendar_date

from core.chat.turn_journal import EVENT_TURN_COMPLETED, EVENT_USER_MESSAGE
from core.chat.conversation_store.repository import parse_directory_cursor_entry
from core.web.services import financial_market_service as market
from core.web.services import financial_report_service as reports

MAX_SESSIONS_PER_PAGE = 20


def _cursor(value: str) -> tuple[str, int]:
    if not value:
        return "", 0
    if not isinstance(value, str) or len(value) > 512:
        raise reports.FinancialReportInvalid("报告翻页标识无效")
    # The Native catalog can return a recency/session cursor, including a
    # pinned prefix. Only the final field belongs to this Turn-level catalog;
    # preserve the entire Native token when requesting the next session.
    session_cursor, separator, turn_offset = value.rpartition(":")
    if not separator or not re.fullmatch(r"\d{1,7}", turn_offset):
        raise reports.FinancialReportInvalid("报告翻页标识无效")
    if not re.fullmatch(r"\d{1,9}", session_cursor):
        native_cursor = parse_directory_cursor_entry(session_cursor)
        if native_cursor is None:
            raise reports.FinancialReportInvalid("报告翻页标识无效")
        reports._normalized_identifier(native_cursor[1], "sessionId")
    return session_cursor, int(turn_offset)


def _subject(request: str, fallback: str) -> tuple[str, str | None, str]:
    header = request[:500].split("\n", 1)[0]
    stock = re.search(r"(?:请研究\s*|综合股票\s+)(.{1,90}?)(?:，?\s*分析日期|的多分析师研究|研究日期)", header)
    title = stock.group(1).strip(" ，。") if stock else fallback
    canonical = _canonical_symbol(header)
    market_code = "HK" if re.search(r"港交所|港股|香港", header, re.I) else "US" if re.search(r"美股|NASDAQ|NYSE|纳斯达克|纽交所", header, re.I) else "CN" if re.search(r"上交所|深交所|北交所", header) else market.market_code_for_symbol(canonical) if canonical else ""
    # Only extract a code adjacent to a stock marker, not dates or Markdown.
    code = re.search(r"[（(]\s*((?:[036489]\d{5}|\d{5}|[A-Z][A-Z0-9.-]{0,9}))\s*[,，）)]", header)
    ticker = canonical[2:] if canonical else code.group(1) if code else None
    return title[:120] or "研究报告", ticker, market_code


def _canonical_symbol(header: str) -> str:
    """Resolve only explicitly prefixed symbols; bare numeric tickers are ambiguous."""
    # US canonical identities use lowercase `us` and uppercase tickers. A
    # case-insensitive match would misread prose (`use`) and currency (`USD`).
    symbol = re.search(
        r"(?<![A-Za-z0-9_])((?i:(?:sh|sz|bj)\d{6}|hk\d{1,5})|us[A-Z][A-Z0-9.\-]{0,9})(?![A-Za-z0-9_])",
        header,
    )
    if not symbol:
        return ""
    try:
        return market.normalize_symbol(symbol.group(1))
    except (market.MarketDataError, TypeError, ValueError):
        return ""


def _session_rows(agent_id: str, row: dict) -> list[dict]:
    session_id = str(row.get("id") or "")
    if not session_id or not reports._owned_session(agent_id, session_id):
        return []
    try:
        events = reports.session_service.load_session_conversation_events_snapshot(session_id)
    except (OSError, RuntimeError, ValueError):
        return []
    grouped: dict[str, list] = defaultdict(list)
    for event in events:
        if getattr(event, "session_id", None) == session_id:
            grouped[str(getattr(event, "turn_id", ""))].append(event)
    result = []
    for turn_id, turn_events in grouped.items():
        if not any(event.event_type == EVENT_TURN_COMPLETED for event in turn_events):
            continue
        try:
            text, completed_at, _suffix = reports._completed_report_from_events(events, session_id, turn_id, agent_id=agent_id)
        except reports.FinancialReportExportError:
            continue
        user_events = sorted((event for event in turn_events if event.event_type == EVENT_USER_MESSAGE and getattr(event, "visible_in_model", True)), key=lambda event: getattr(event, "sequence", 0))
        request = str((user_events[-1].payload or {}).get("content") or "") if user_events else ""
        title, ticker, market_code = _subject(request, str(row.get("title") or "研究报告"))
        preview = re.sub(r"https?://\S+|[#*_`>|]", " ", text)
        preview = re.sub(r"\s+", " ", preview).strip()[:240]
        result.append({"sessionId": session_id, "turnId": turn_id, "title": title, "sessionTitle": str(row.get("title") or "")[:120], "ticker": ticker, "marketCode": market_code or None, "completedAt": completed_at, "preview": preview, "chars": len(text), "kind": "review" if re.search(r"复盘|trade review|trading review", request, re.I) else "research"})
    return sorted(result, key=lambda item: (item["completedAt"], item["turnId"]), reverse=True)


def list_reports(agent_id: str, *, cursor: str = "", limit: int = 30, q: str = "", market_code: str = "", date_from: str = "", date_to: str = "", kind: str = "") -> dict:
    agent_id = reports._normalized_identifier(agent_id, "assistantAgentId")
    agent = reports.directory.get_agent(agent_id)
    if not isinstance(agent, dict) or (agent.get("metadata") or {}).get("financialAssistantProfile") != reports.assistant_service.PROFILE:
        raise reports.FinancialReportNotFound("金融助手不存在")
    if type(limit) is not int or not 1 <= limit <= 50 or market_code not in {"", "CN", "HK", "US"} or kind not in {"", "research", "review"} or len(q) > 120:
        raise reports.FinancialReportInvalid("报告筛选条件无效")
    for date in (date_from, date_to):
        if date:
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                    raise ValueError("format")
                # Validate the calendar, not only the string shape.
                calendar_date.fromisoformat(date)
            except ValueError:
                raise reports.FinancialReportInvalid("报告日期无效") from None
    if date_from and date_to and date_from > date_to:
        raise reports.FinancialReportInvalid("开始日期不能晚于结束日期")
    session_cursor, offset = _cursor(cursor)
    items: list[dict] = []
    scanned = 0
    next_cursor: str | None = None
    while scanned < MAX_SESSIONS_PER_PAGE:
        page = reports.session_service.query_sessions(agent_id=agent_id, limit=1, cursor=session_cursor)
        rows = page.get("items") or []
        if not rows:
            next_cursor = None
            break
        scanned += 1
        candidates = _session_rows(agent_id, rows[0])
        for index, report in enumerate(candidates[offset:], start=offset):
            stamp = report["completedAt"][:10]
            if market_code and report["marketCode"] != market_code or kind and report["kind"] != kind or date_from and stamp < date_from or date_to and stamp > date_to:
                continue
            if q.strip() and q.strip().casefold() not in (report["title"] + " " + report["sessionTitle"] + " " + (report["ticker"] or "") + " " + report["preview"]).casefold():
                continue
            items.append(report)
            if len(items) == limit:
                next_cursor = f"{session_cursor or '0'}:{index + 1}" if index + 1 < len(candidates) else f"{page['nextCursor']}:0" if page.get("nextCursor") else None
                break
        if len(items) == limit:
            break
        following = page.get("nextCursor")
        if not following:
            break
        session_cursor, offset = str(following), 0
        next_cursor = f"{session_cursor}:0"
    else:
        return {"items": items, "nextCursor": next_cursor, "scannedSessions": scanned, "order": "session_recency"}
    # Reaching the end of the native catalog clears a prior continuation.
    if len(items) < limit and not page.get("nextCursor"):
        next_cursor = None
    return {"items": items, "nextCursor": next_cursor, "scannedSessions": scanned, "order": "session_recency"}
