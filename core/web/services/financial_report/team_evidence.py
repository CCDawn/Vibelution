"""Read-only, fail-closed provenance bridge for a financial team's summary Turn."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from core.chat.turn_journal import (
    EVENT_TOOL_RESULT,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_FAILED,
    EVENT_TURN_INTERRUPTED,
    EVENT_USER_MESSAGE,
    fold_active_events,
    session_turn_items_from_events,
)
from core.web.services import session_service
from core.web.services.financial_report.conclusion_figures import (
    _market_quote_payload,
    _tool_records,
    _without_code,
)
from core.web.services.financial_research.as_of import (
    analysis_date_in_text,
    explicit_iso_date,
    on_or_before,
    published_date,
)
from core.web.services.financial_report.index_evidence import TOOL_NAME as INDEX_TOOL, index_reference
from core.web.services.financial_report.sector_evidence import sector_reference

_SUCCESS = {"completed", "success", "succeeded", "done"}
_MAX_OUTPUT = 32_000
_MAX_RECORDS = 60
_MAX_SYNTHESIS_REFERENCE_BYTES = 24_000
_MAX_SYNTHESIS_REFERENCE_ITEM_BYTES = 8_000
_MAX_SYNTHESIS_REFERENCE_ITEMS = 24
_MAX_SYNTHESIS_MARKET_ROWS = 16
_SYNTHESIS_ROLE_TOOLS = {
    "market": {"financial_market_snapshot_tool", INDEX_TOOL},
    "fundamental": {"financial_report_query_tool", "financial_evidence_search_tool"},
    "news": {"news_search_tool"},
}
_NEWS_RESULT = re.compile(
    r"(?m)^(?P<index>\d{1,2})\.\s+\[(?P<title>[^\]\r\n]{1,300})\]"
    r"\((?P<url>https://[^)\s\r\n]{1,2048})\)\s*$"
)


def original_tool_records(events: list, *, session_id: str = "", turn_id: str = "") -> list:
    """Read the latest raw outcome of each call on the active native branch."""
    latest = {}
    for event in fold_active_events(events):
        if (session_id and event.session_id != session_id) or (turn_id and event.turn_id != turn_id):
            continue
        if event.event_type != EVENT_TOOL_RESULT:
            continue
        tool = event.payload.get("toolCall") or event.payload.get("tool_call") or event.payload
        key = tool.get("callId") or tool.get("toolCallId")
        if key:
            latest[key] = event
    return [(name, output, "completed" if status in {"done", "succeeded"} else status)
        for name, output, status in _tool_records([], list(latest.values()))]


def _exact_turn(events: list, ref: dict, *, before: str, strict_before: bool = False) -> list:
    associated = {e.turn_id for e in events if e.session_id == ref.get("sessionId")
        and e.event_type == EVENT_USER_MESSAGE
        and ((e.payload or {}).get("metadata") or {}).get("clientSubmissionId") == ref.get("clientSubmissionId")}
    if associated != {ref.get("turnId")}:
        return []
    selected = [e for e in fold_active_events(events) if e.session_id == ref.get("sessionId") and e.turn_id == ref.get("turnId")]
    terminals = [e for e in selected if e.event_type in {EVENT_TURN_COMPLETED, EVENT_TURN_FAILED, EVENT_TURN_INTERRUPTED}]
    if len(terminals) != 1 or terminals[0].event_type != EVENT_TURN_COMPLETED or terminals[0].status not in _SUCCESS:
        return []
    terminal = terminals[0]
    payload = terminal.payload or {}
    if payload.get("marker") or payload.get("errorType") or payload.get("error_type"):
        return []
    for key in ("terminalReason", "terminal_reason", "finalStatus", "final_status", "resultStatus", "result_status"):
        if payload.get(key) and str(payload[key]).lower() not in _SUCCESS:
            return []
    completed = datetime.fromisoformat(terminal.timestamp.replace("Z", "+00:00"))
    boundary = datetime.fromisoformat(before.replace("Z", "+00:00"))
    if completed.tzinfo is None or boundary.tzinfo is None or completed > boundary or (strict_before and completed == boundary):
        return []
    users = [e for e in selected if e.event_type == EVENT_USER_MESSAGE and e.visible_in_model]
    if len(users) != 1 or not ref.get("clientSubmissionId"):
        return []
    metadata = (users[0].payload or {}).get("metadata") or {}
    if metadata.get("clientSubmissionId") != ref["clientSubmissionId"]:
        return []
    selected = [e for e in selected if e.sequence <= terminal.sequence]
    items = session_turn_items_from_events(selected, turn_id=ref["turnId"])
    latest = {}
    for item in items:
        key = item.get("itemId")
        if key and (item.get("revision", 0), item.get("sequence", 0)) >= (
            latest.get(key, {}).get("revision", -1), latest.get(key, {}).get("sequence", -1)):
            latest[key] = item
    if any(i.get("type") == "error" and i.get("status") == "failed" for i in latest.values()):
        return []
    if not any(i.get("type") == "assistant_message" and i.get("channel") == "answer"
        and i.get("phase") == "final_answer" and i.get("status") == "completed"
        and i.get("terminal") is True and not i.get("provisional")
        and str(i.get("text") or "").strip() for i in latest.values()):
        return []
    return selected


def _filing_records(payload: dict, report: str, symbol: str, cutoff) -> list[tuple[tuple, str]]:
    from core.web.services.team_knowledge.financial import validate_evidence
    from core.web.services.team_knowledge_service import TeamKnowledgeError

    found = []
    urls = {m.group(0).rstrip(",;.").split("#", 1)[0] for m in
        re.finditer(r"https://[^\s\]\[<>()}，。；：！？、]+", _without_code(report))}
    results = {r.get("knowledgeItemId"): r for r in payload.get("results", []) if isinstance(r, dict)}
    for citation in payload.get("citations", []):
        if not isinstance(citation, dict):
            continue
        row = results.get(citation.get("knowledgeItemId"))
        if not row or not isinstance(row.get("excerpt"), str) or not row["excerpt"].strip():
            continue
        for meta in citation.get("financialEvidence", []):
            try:
                meta = validate_evidence(meta, excerpt=row["excerpt"])
            except (TeamKnowledgeError, TypeError, ValueError):
                continue
            # No unlabelled page, different company, future disclosure, or URL substitution.
            if (str(meta["ticker"]).casefold() != symbol[2:].casefold()
                or meta["sourceUrl"] not in urls or meta["reportPeriod"] not in report
                or not on_or_before(meta["publishedAt"], cutoff)):
                continue
            compact = {"results": [row], "citations": [{
                "knowledgeItemId": citation["knowledgeItemId"], "financialEvidence": [meta]}]}
            found.append(((meta["sourceUrl"], meta["page"]), json.dumps(compact, ensure_ascii=False, sort_keys=True)))
    return found


def _eligible(records: list, report: str, symbol: str, cutoff) -> list[tuple[str, str, str]]:
    """Select original tool data, never text from a native final answer."""
    accepted = []
    for name, output, status in records[:_MAX_RECORDS]:
        status = str(status).strip().lower()
        if status in {"done", "succeeded"}:
            status = "completed"
        if status not in {"completed", "success", "partial", "degraded"} or len(output) > _MAX_OUTPUT:
            continue
        try:
            payload = json.loads(output)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict) or payload.get("ok") is False:
            continue
        if name == "financial_evidence_search_tool" and payload.get("status") in {"found", "ok"}:
            accepted.extend((name, text, status) for _, text in _filing_records(payload, report, symbol, cutoff))
        elif name == "financial_market_snapshot_tool":
            quote = payload.get("quote")
            if (isinstance(quote, dict) and str(payload.get("ticker") or "").casefold() == symbol.casefold()
                and on_or_before(quote.get("timestamp"), cutoff)):
                accepted.append((name, json.dumps(payload, ensure_ascii=False, sort_keys=True), status))
    return accepted


def _is_successful_tool(status: str) -> bool:
    normalized = str(status or "").strip().lower()
    if normalized in {"done", "succeeded"}:
        normalized = "completed"
    return normalized in {"completed", "success", "partial", "degraded"}


def _as_a_share(value: object) -> str:
    from core.web.services import financial_market_service as market

    try:
        symbol = market.normalize_symbol(str(value or ""))
        if market.market_code_for_symbol(symbol) == "CN":
            return symbol
    except (TypeError, ValueError, RuntimeError):
        pass
    return ""


def _safe_web_url(value: object) -> bool:
    text = str(value or "").strip()
    if not text or any(ord(char) < 32 for char in text):
        return False
    try:
        parsed = urlparse(text)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
    except (TypeError, ValueError):
        return False


def _reference_item(
    source: str,
    tool_name: str,
    payload: dict,
    *,
    truncated: bool = False,
    reference_type: str = "native_financial_tool_result",
) -> dict:
    content = json.dumps(
        {"toolName": tool_name, **payload}, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return {
        "source": source,
        "type": reference_type,
        "content": content,
        "truncated": truncated,
    }


def _market_reference(output: str, status: str, symbol: str, cutoff) -> tuple[dict, str] | None:
    if not _is_successful_tool(status) or len(output.encode("utf-8", errors="replace")) > _MAX_OUTPUT:
        return None
    try:
        payload = json.loads(output)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or not _eligible(
        [("financial_market_snapshot_tool", output, status)], "", symbol, cutoff
    ):
        return None
    verified_quote = _market_quote_payload(output)
    if (
        not isinstance(verified_quote, dict)
        or str(verified_quote.get("symbol") or "").casefold() != symbol.casefold()
        or not on_or_before(verified_quote.get("date"), cutoff)
    ):
        return None
    quote = payload.get("quote")
    if not isinstance(quote, dict):
        return None
    for identity in (quote.get("symbol"), quote.get("ticker")):
        if identity and _as_a_share(identity) != symbol:
            return None

    columns_value = (payload.get("candles") or {}).get("columns") if isinstance(payload.get("candles"), dict) else []
    rows_value = (payload.get("candles") or {}).get("rows") if isinstance(payload.get("candles"), dict) else []
    columns = [str(value)[:40] for value in columns_value[:16]] if isinstance(columns_value, list) else []
    rows = []
    for row in rows_value if isinstance(rows_value, list) else []:
        if not isinstance(row, list) or len(row) != len(columns) or not row:
            continue
        if not on_or_before(row[0], cutoff):
            continue
        if any(isinstance(value, (dict, list)) for value in row):
            continue
        rows.append(row)
    selected_rows = rows[-_MAX_SYNTHESIS_MARKET_ROWS:]
    truncated = len(selected_rows) < len(rows) or bool(payload.get("omittedCandleCount"))
    projected = {
        "ticker": symbol,
        "source": str(payload.get("source") or "")[:100],
        "sourceUrl": str(payload.get("sourceUrl") or "")[:512],
        "marketCode": payload.get("marketCode"),
        "currency": payload.get("currency"),
        "adjustment": payload.get("adjustment"),
        "priceUnit": payload.get("priceUnit"),
        "period": payload.get("period"),
        "quote": quote,
        "candles": {"columns": columns, "rows": selected_rows},
        "includedCandleCount": len(selected_rows),
        "returnedCandleCount": payload.get("returnedCandleCount"),
        "candleError": str(payload.get("candleError") or "")[:240],
        "researchDate": cutoff.isoformat(),
        "verification": "original_tool_output; untrusted reference; separate from filing-page numeric validation",
    }
    sector = sector_reference(payload.get("sectorContext"), symbol, cutoff)
    if sector is not None:
        projected["sectorContext"] = sector
    name = str(quote.get("name") or "").strip()
    if len(name) > 80 or any(ord(char) < 32 for char in name):
        name = ""
    item = _reference_item("行情分析师", "financial_market_snapshot_tool", projected, truncated=truncated)
    return item, name


def _report_query_reference(output: str, status: str, symbol: str, cutoff) -> dict | None:
    if not _is_successful_tool(status) or len(output.encode("utf-8", errors="replace")) > _MAX_OUTPUT:
        return None
    try:
        payload = json.loads(output)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("ok") is not True or payload.get("status") != "answer":
        return None
    scope = payload.get("scope")
    answer = payload.get("answer")
    citations = payload.get("citations")
    if (
        not isinstance(scope, dict)
        or _as_a_share(scope.get("ticker")) != symbol
        or not re.fullmatch(r"20\d{2}(?:FY|Q[1-4]|H[12])", str(scope.get("report_period") or ""))
        or not isinstance(answer, dict)
        or not isinstance(citations, list)
        or not citations
    ):
        return None
    selected_citations = []
    for citation in citations:
        if not isinstance(citation, dict):
            return None
        if (
            _as_a_share(citation.get("ticker")) != symbol
            or citation.get("report_period") != scope.get("report_period")
            or not isinstance(citation.get("source_id"), str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", citation["source_id"])
            or type(citation.get("page")) is not int
            or citation["page"] < 1
            or not isinstance(citation.get("reference_indexes"), list)
        ):
            return None
        source_url = citation.get("source_url")
        if source_url is not None and not _safe_web_url(source_url):
            return None
        selected_citations.append({
            "source_id": citation["source_id"],
            "page": citation["page"],
            "source_url": source_url,
            "report_period": citation["report_period"],
            "reference_indexes": [value for value in citation.get("reference_indexes", [])
                if type(value) is int and value >= 0][:16],
        })
    clipped = len(selected_citations) > 8
    explanation = str(answer.get("explanation") or "")
    formula = str(answer.get("formula") or "")
    clipped = clipped or len(explanation) > 1_200 or len(formula) > 240
    compact = {
        "ticker": symbol,
        "scope": {"report_period": scope["report_period"]},
        "answer": {
            "value": str(answer.get("value") or "")[:100],
            "unit": str(answer.get("unit") or "")[:24],
            "explanation": explanation[:1_200],
            "formula": formula[:240],
        },
        "citations": selected_citations[:8],
        "evidenceTrust": "untrusted_source_data",
        "verification": "scope_and_citation_structure_only",
        "publicationDateStatus": "not_returned; cannot be verified against research cutoff",
        "researchDate": cutoff.isoformat(),
    }
    return _reference_item("基本面分析师", "financial_report_query_tool", compact, truncated=clipped)


def _financial_pdf_references(output: str, status: str, symbol: str, cutoff) -> list[dict]:
    if not _is_successful_tool(status) or len(output.encode("utf-8", errors="replace")) > _MAX_OUTPUT:
        return []
    try:
        payload = json.loads(output)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict) or payload.get("ok") is False or payload.get("status") not in {"found", "ok"}:
        return []
    from core.web.services.team_knowledge.financial import validate_evidence
    from core.web.services.team_knowledge_service import TeamKnowledgeError

    code = symbol[2:]
    results = {row.get("knowledgeItemId"): row for row in payload.get("results", [])
        if isinstance(row, dict)}
    found: list[dict] = []
    for citation in payload.get("citations", []):
        if not isinstance(citation, dict):
            continue
        row = results.get(citation.get("knowledgeItemId"))
        excerpt = row.get("excerpt") if isinstance(row, dict) else None
        if not isinstance(excerpt, str) or not excerpt.strip():
            continue
        for raw_meta in citation.get("financialEvidence", []):
            try:
                meta = validate_evidence(raw_meta, excerpt=excerpt)
            except (TeamKnowledgeError, TypeError, ValueError):
                continue
            if (
                str(meta.get("ticker") or "").casefold() != code.casefold()
                or not on_or_before(meta.get("publishedAt"), cutoff)
            ):
                continue
            excerpt_limit = 1_600
            clipped = len(excerpt) > excerpt_limit
            record = {
                "ticker": symbol,
                "company": meta["company"],
                "reportPeriod": meta["reportPeriod"],
                "publishedAt": meta["publishedAt"],
                "sourceUrl": meta["sourceUrl"],
                "page": meta["page"],
                "documentSha256": meta["documentSha256"],
                "excerptSha256": meta["excerptSha256"],
                "excerpt": excerpt[:excerpt_limit],
                "excerptTruncated": clipped,
                "researchDate": cutoff.isoformat(),
                "verification": "validated original-PDF metadata and full source excerpt hash before prompt projection",
            }
            found.append(_reference_item("基本面分析师", "financial_evidence_search_tool", record,
                truncated=clipped))
            if len(found) >= _MAX_SYNTHESIS_REFERENCE_ITEMS:
                return found
    return found


def _news_references(output: str, status: str, symbol: str, issuer_name: str, cutoff) -> list[dict]:
    if (
        not issuer_name
        or not _is_successful_tool(status)
        or len(output.encode("utf-8", errors="replace")) > _MAX_OUTPUT
    ):
        return []
    normalized_name = re.sub(r"[\W_]+", "", issuer_name.casefold())
    if len(normalized_name) < 2:
        return []
    matches = list(_NEWS_RESULT.finditer(output))
    found: list[dict] = []
    for index, match in enumerate(matches):
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(output)
        lines = output[match.end():block_end].splitlines()
        metadata_line = next((line.strip() for line in lines if "provider=" in line and "sourceType=" in line), "")
        metadata = {}
        for part in metadata_line.removeprefix("-").strip().split(";"):
            key, separator, value = part.strip().partition("=")
            if separator:
                metadata[key.strip()] = value.strip()
        published = metadata.get("published", "")
        published_day = published_date(published)
        if metadata.get("sourceType", "").casefold() != "news" or published_day is None or published_day > cutoff:
            continue
        url = match.group("url")
        if not _safe_web_url(url):
            continue
        snippet_line = next((line.strip()[2:] for line in lines
            if line.strip().startswith("- ") and "provider=" not in line), "")
        title = match.group("title").strip()
        identity_text = re.sub(r"[\W_]+", "", f"{title} {snippet_line}".casefold())
        if normalized_name not in identity_text:
            continue
        result = {
            "ticker": symbol,
            "matchedIssuerName": issuer_name,
            "title": title,
            "sourceUrl": url,
            "provider": metadata.get("provider", "")[:80],
            "sourceType": "news",
            "publishedAt": published,
            "publishedDate": published_day.isoformat(),
            "snippet": snippet_line[:500],
            "researchDate": cutoff.isoformat(),
            "verification": "untrusted news reference; exact issuer name and publication date checked",
        }
        found.append(_reference_item("新闻分析师", "news_search_tool", result))
        if len(found) >= _MAX_SYNTHESIS_REFERENCE_ITEMS:
            break
    return found


def _public_fundamentals_reference(run: dict, symbol: str, cutoff) -> dict | None:
    snapshot = run.get("publicFundamentalsSnapshot")
    if not isinstance(snapshot, dict) or snapshot.get("status") != "available":
        return None
    source_url = str(snapshot.get("sourceUrl") or "").strip()
    parsed = urlparse(source_url) if _safe_web_url(source_url) else None
    host = (parsed.hostname or "").lower() if parsed else ""
    if not (host == "eastmoney.com" or host.endswith(".eastmoney.com")):
        return None
    from core.web.services.financial_research.official_filings import (
        filing_for_report_period,
    )

    filing_map = snapshot.get("periodFilings")
    filing_map = filing_map if isinstance(filing_map, dict) else {}
    items = []
    raw_items = snapshot.get("items") if isinstance(snapshot.get("items"), list) else []
    for item in raw_items[:16]:
        if not isinstance(item, dict):
            continue
        report_day = explicit_iso_date(item.get("reportDate"))
        published = published_date(item.get("publishedAt"))
        label = str(item.get("label") or "").strip()
        value = str(item.get("value") or "").strip()
        unit = str(item.get("unit") or "").strip()
        if (
            not label or not value or report_day is None or published is None
            or report_day > cutoff or published > cutoff
            or len(label) > 80 or len(value) > 100 or len(unit) > 24
            or any(ord(char) < 32 for char in label + value + unit)
        ):
            continue
        filing = filing_for_report_period(
            [filing_map[report_day.isoformat()]] if isinstance(filing_map.get(report_day.isoformat()), dict) else [],
            report_day.isoformat(),
            cutoff=cutoff,
        )
        items.append({
            "label": label,
            "value": value,
            "unit": unit,
            "reportDate": report_day.isoformat(),
            "publishedAt": published.isoformat(),
            "samePeriodOfficialFiling": filing,
            "verifiedAgainstOriginalPdf": False,
        })
    if not items:
        return None
    payload = {
        "ticker": symbol,
        "source": str(snapshot.get("source") or "东方财富")[:80],
        "sourceUrl": source_url,
        "retrievedAt": str(snapshot.get("fetchedAt") or "")[:40],
        "researchDate": cutoff.isoformat(),
        "items": items,
        "verification": "unverified public data snapshot; same-period CNINFO link is not a PDF value check; point-in-time revisions are not verified",
    }
    return _reference_item(
        "金融研究公共数据服务",
        "public_fundamentals_snapshot",
        payload,
        reference_type="public_fundamentals_snapshot",
    )


def _bounded_synthesis_references(candidates: list[dict]) -> list[dict]:
    accepted = []
    total = 0
    omitted = 0
    for index, item in enumerate(candidates):
        encoded = json.dumps(item, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) > _MAX_SYNTHESIS_REFERENCE_ITEM_BYTES:
            omitted += 1
            continue
        if (
            len(accepted) >= _MAX_SYNTHESIS_REFERENCE_ITEMS - 1
            or total + len(encoded) > _MAX_SYNTHESIS_REFERENCE_BYTES - 320
        ):
            omitted += len(candidates) - index
            break
        accepted.append(item)
        total += len(encoded)
    if omitted:
        notice = _reference_item(
            "证据边界",
            "source_evidence_limit",
            {
                "omittedItems": omitted,
                "maxItems": _MAX_SYNTHESIS_REFERENCE_ITEMS,
                "maxTotalBytes": _MAX_SYNTHESIS_REFERENCE_BYTES,
                "notice": "部分合格材料因上下文预算未传递；不得据此推断其内容或完整性。",
            },
            truncated=True,
            reference_type="source_evidence_truncation_notice",
        )
        accepted.append(notice)
    return accepted


def synthesis_tool_references(owner: str, run: dict) -> list[dict]:
    """Read bounded A-share source records for synthesis as explicitly untrusted references.

    The caller must have just revalidated the exact run's current team/role bindings.
    This is a read projection only: no Journal, run, or export-grounding state is written.
    """
    from core.web.services import financial_market_service as market

    if not isinstance(run, dict):
        return []
    owner_id = str(owner or "").strip()
    run_id = str(run.get("runId") or "").strip()
    synthesis = run.get("synthesis") if isinstance(run.get("synthesis"), dict) else {}
    if (
        not owner_id or str(run.get("assistantAgentId") or "").strip() != owner_id
        or not run_id or str(synthesis.get("agentId") or "").strip() != owner_id
    ):
        return []
    cutoff = explicit_iso_date(run.get("researchDate"))
    symbol = _as_a_share(run.get("symbol"))
    if cutoff is None or not symbol or market.market_code_for_symbol(symbol) != "CN":
        return []

    now = datetime.now(timezone.utc).isoformat()
    role_records: dict[str, list[tuple[str, str, str]]] = {}
    analysts = run.get("analysts") if isinstance(run.get("analysts"), dict) else {}
    for role in ("market", "fundamental", "news"):
        ref = analysts.get(role)
        if not isinstance(ref, dict):
            continue
        session_id = str(ref.get("sessionId") or "").strip()
        turn_id = str(ref.get("turnId") or "").strip()
        agent_id = str(ref.get("agentId") or "").strip()
        if not session_id or not turn_id or not agent_id or not ref.get("clientSubmissionId"):
            continue
        try:
            state = session_service.load_session_chat_state(session_service.PROJECT_ROOT, session_id)
            if not isinstance(state, dict) or str(state.get("agentId") or state.get("agent_id") or "") != agent_id:
                continue
            events = session_service.load_session_conversation_events_snapshot(session_id)
            selected = _exact_turn(events, ref, before=now)
            if not selected:
                continue
            role_records[role] = original_tool_records(selected, session_id=session_id, turn_id=turn_id)
        except (OSError, RuntimeError, TypeError, ValueError, KeyError, AttributeError):
            continue

    candidates: list[dict] = []
    issuer_names = []
    for name, output, status in role_records.get("market", [])[:_MAX_RECORDS]:
        if name not in _SYNTHESIS_ROLE_TOOLS["market"]:
            continue
        if name == INDEX_TOOL:
            projected = index_reference(output, status, cutoff)
            if projected is not None:
                candidates.append(_reference_item("行情分析师", INDEX_TOOL, projected))
            continue
        result = _market_reference(output, status, symbol, cutoff)
        if result is None:
            continue
        item, observed_name = result
        if observed_name:
            issuer_names.append(observed_name)
        candidates.append(item)

    normalized_issuer_names = {
        re.sub(r"[\W_]+", "", name.casefold()) for name in issuer_names
    }
    issuer_name = issuer_names[0] if issuer_names and len(normalized_issuer_names) == 1 else ""

    for name, output, status in role_records.get("fundamental", [])[:_MAX_RECORDS]:
        if name not in _SYNTHESIS_ROLE_TOOLS["fundamental"]:
            continue
        if name == "financial_report_query_tool":
            item = _report_query_reference(output, status, symbol, cutoff)
            if item is not None:
                candidates.append(item)
        elif name == "financial_evidence_search_tool":
            candidates.extend(_financial_pdf_references(output, status, symbol, cutoff))

    snapshot_item = _public_fundamentals_reference(run, symbol, cutoff)
    if snapshot_item is not None:
        candidates.append(snapshot_item)
    from core.web.services.financial_team.public_filings import public_filing_reference

    original_item = public_filing_reference(run.get("publicOriginalFilingSnapshot"), symbol, cutoff)
    if original_item is not None:
        candidates.append(original_item)

    for name, output, status in role_records.get("news", [])[:_MAX_RECORDS]:
        if name in _SYNTHESIS_ROLE_TOOLS["news"]:
            candidates.extend(_news_references(output, status, symbol, issuer_name, cutoff))
    return _bounded_synthesis_references(candidates)


def _without_conflicts(own: list, cross: list) -> list:
    """Conflicting original records cannot authorize either version's numbers."""
    market_variants = set()
    filing_variants: dict[tuple, set[str]] = {}
    for name, text, _ in [*own, *cross]:
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            continue
        if name == "financial_market_snapshot_tool":
            # Query windows and candle failures do not change the quote observation.
            # Keep the full records: calculations still reject ambiguous candle data.
            market_variants.add(json.dumps({key: payload.get(key) for key in (
                "ticker", "source", "sourceUrl", "marketCode", "currency", "priceUnit", "quote",
            )}, sort_keys=True))
        elif name == "financial_evidence_search_tool":
            rows = {r.get("knowledgeItemId"): r for r in payload.get("results", []) if isinstance(r, dict)}
            for citation in payload.get("citations", []):
                if not isinstance(citation, dict):
                    continue
                row = rows.get(citation.get("knowledgeItemId"))
                for meta in citation.get("financialEvidence", []):
                    if isinstance(meta, dict) and row:
                        key = (meta.get("sourceUrl"), meta.get("page"))
                        filing_variants.setdefault(key, set()).add(json.dumps({"excerpt": row.get("excerpt"), "sha": meta.get("documentSha256")}, sort_keys=True))
    bad_pages = {key for key, versions in filing_variants.items() if len(versions) > 1}
    result = []
    seen = set()
    for record in [*own, *cross]:
        name, text, _ = record
        if name == "financial_market_snapshot_tool" and len(market_variants) > 1:
            continue
        if name == "financial_evidence_search_tool" and bad_pages:
            try:
                payload = json.loads(text)
                if any((m.get("sourceUrl"), m.get("page")) in bad_pages
                    for c in payload.get("citations", []) for m in c.get("financialEvidence", [])):
                    continue
            except (TypeError, ValueError, AttributeError):
                continue
        if record not in seen:
            seen.add(record)
            result.append(record)
    return result


def team_report_records(owner: str, session_id: str, turn_id: str, *,
    request: str, report: str, completed_at: str, own: list) -> list:
    """Only an exact owner-scoped run with current role permissions can add evidence."""
    from core.web.services.financial_team import runs

    try:
        state = session_service.load_session_chat_state(session_service.PROJECT_ROOT, session_id)
        if not isinstance(state, dict) or (state.get("metadata") or {}).get("source") != "financial_team_synthesis":
            return own
        if str(state.get("agentId") or state.get("agent_id") or "") != owner:
            return own
        root = runs._run_root(owner)
        if not root.exists():
            return own
        paths = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)[:runs._MAX_RUNS]
        matches = []
        for path in paths:
            run = runs._load_run(path, owner)
            ref = run.get("synthesis") or {}
            if ref.get("sessionId") == session_id and ref.get("turnId") == turn_id and ref.get("agentId") == owner:
                matches.append(run)
        if len(matches) != 1:
            return own
        run = matches[0]
        runs.require_current_financial_team_run_bindings(owner, run["runId"])
        cutoff = explicit_iso_date(run.get("researchDate"))
        symbol = runs.market.normalize_symbol(run.get("symbol"))
        if cutoff is None or analysis_date_in_text(request) != cutoff or f"股票 {symbol} 的多分析师研究" not in request:
            return own
        summary = session_service.load_session_conversation_events_snapshot(session_id)
        summary_turn = _exact_turn(summary, run["synthesis"], before=completed_at)
        if not summary_turn:
            return own
        started_at = next(e.timestamp for e in summary_turn if e.event_type == EVENT_USER_MESSAGE)
        cross = []
        for ref in run["analysts"].values():
            sid = ref.get("sessionId")
            role_state = session_service.load_session_chat_state(session_service.PROJECT_ROOT, sid)
            if not isinstance(role_state, dict) or str(role_state.get("agentId") or role_state.get("agent_id") or "") != ref.get("agentId"):
                return own
            events = _exact_turn(session_service.load_session_conversation_events_snapshot(sid), ref, before=started_at, strict_before=True)
            if not events:
                return own
            cross.extend(_eligible(original_tool_records(events), report, symbol, cutoff))
            if len(cross) > _MAX_RECORDS:
                return own
        return _without_conflicts(own, cross) if cross else own
    except (OSError, RuntimeError, TypeError, ValueError, KeyError, AttributeError):
        # Missing provenance/changed ACL is a missing-data projection, never an export failure.
        return own
