"""Read-only, fail-closed provenance bridge for a financial team's summary Turn."""
from __future__ import annotations

import json
import re
from datetime import datetime

from core.chat.turn_journal import (
    EVENT_TURN_COMPLETED, EVENT_TURN_FAILED, EVENT_TURN_INTERRUPTED,
    EVENT_USER_MESSAGE, EVENT_TOOL_RESULT, fold_active_events, session_turn_items_from_events,
)
from core.web.services import session_service
from core.web.services.financial_report.conclusion_figures import _tool_records, _without_code
from core.web.services.financial_research.as_of import (
    analysis_date_in_text, explicit_iso_date, on_or_before,
)

_SUCCESS = {"completed", "success", "succeeded", "done"}
_MAX_OUTPUT = 32_000
_MAX_RECORDS = 60


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
