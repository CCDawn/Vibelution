"""Summary exports read tools from exact guarded analyst Turns, never their prose."""
import hashlib
import json
from dataclasses import replace

import pytest

from core.chat.turn_journal import (
    EVENT_ASSISTANT_ITEM_COMMITTED, EVENT_BRANCH_REBASE, EVENT_TOOL_RESULT, EVENT_TURN_COMPLETED,
    EVENT_USER_MESSAGE, TurnJournalEvent,
)
from core.web.services import financial_report_service as reports
from core.web.services.financial_team import runs

RUN_ID = "11111111-1111-4111-8111-111111111111"
URL = "https://example.com/original.pdf"
TEXT = "营业收入 200.00 元"
ANSWER = f"## 结论\n贵州茅台（600519）营业收入 200.00 元，见第5页。无证据数字 999.00 元。\n## 证据来源\n{URL}，2024FY 第5页。"


def event(kind, seq, session, turn, payload=None, status="completed"):
    return TurnJournalEvent(schema_version=2, event_id=f"{session}-{seq}",
        session_id=session, turn_id=turn, sequence=seq, event_type=kind,
        status=status, timestamp=f"2026-10-06T{'13' if session == 'summary-session' else '12'}:00:{seq:02d}+08:00",
        source="test", payload=payload or {})


def turn(session, tid, submission, answer, tool=None):
    result = [event(EVENT_USER_MESSAGE, 1, session, tid, {
        "content": "你是主助手的股票研究汇总角色。请综合股票 sh600519 的多分析师研究。研究日期：2026-10-06；观察周期：近30天",
        "metadata": {"clientSubmissionId": submission}})]
    if tool:
        result.append(event(EVENT_TOOL_RESULT, 2, session, tid, {"toolCall": {
            "callId": "tc", "name": "financial_evidence_search_tool", "result": json.dumps(tool), "status": "done"}}))
    result.extend([event(EVENT_ASSISTANT_ITEM_COMMITTED, 3, session, tid, {
        "kind": "assistant_message", "channel": "answer", "phase": "final_answer",
        "status": "completed", "text": answer, "itemId": "a", "revision": 0, "terminal": True}),
        event(EVENT_TURN_COMPLETED, 4, session, tid)])
    return result


@pytest.fixture
def team_report(monkeypatch, tmp_path):
    run = {"runId": RUN_ID, "assistantAgentId": "owner", "symbol": "sh600519",
        "researchDate": "2026-10-06", "analysts": {"fundamental": {
            "agentId": "analyst", "sessionId": "analyst-session", "turnId": "at", "clientSubmissionId": "as"}},
        "synthesis": {"agentId": "owner", "sessionId": "summary-session", "turnId": "st", "clientSubmissionId": "ss"}}
    (tmp_path / f"{RUN_ID}.json").write_text("{}")
    meta = {"schemaVersion": 1, "evidenceKind": "original_pdf_excerpt", "sourceId": "pdf",
        "company": "贵州茅台", "ticker": "600519", "reportPeriod": "2024FY",
        "reportVersion": "original", "documentSha256": "a" * 64, "page": 5,
        "sourceUrl": URL, "publishedAt": "2025-04-03T00:00:00+08:00",
        "excerptSha256": hashlib.sha256(TEXT.encode()).hexdigest()}
    tool = {"ok": True, "status": "found", "results": [{"knowledgeItemId": "k", "excerpt": TEXT}],
        "citations": [{"knowledgeItemId": "k", "financialEvidence": [meta]}]}
    journals = {"summary-session": turn("summary-session", "st", "ss", ANSWER),
        "analyst-session": turn("analyst-session", "at", "as", "模型意见 999.00 元", tool)}
    states = {"summary-session": {"agentId": "owner", "metadata": {"source": "financial_team_synthesis"}},
        "analyst-session": {"agentId": "analyst"}}
    monkeypatch.setattr(reports.directory, "get_agent", lambda _: {"metadata": {"financialAssistantProfile": "financial_assistant_v1"}})
    monkeypatch.setattr(reports.session_service, "load_session_chat_state", lambda _, sid: states[sid])
    monkeypatch.setattr(reports.session_service, "load_session_conversation_events_snapshot", lambda sid: journals[sid])
    monkeypatch.setattr(runs, "_run_root", lambda _: tmp_path)
    monkeypatch.setattr(runs, "_load_run", lambda *_: run)
    monkeypatch.setattr(runs, "require_current_financial_team_run_bindings", lambda *_: None)
    return run, tool, journals, states


def exported():
    return reports.export_financial_report("owner", session_id="summary-session", turn_id="st", format="markdown")["content"]


def test_summary_reuses_original_tool_evidence_without_trusting_analyst_prose(team_report):
    before = repr(team_report)
    text = exported()
    assert "200.00 元" in text
    assert "999.00" not in text
    assert repr(team_report) == before


@pytest.mark.parametrize("damage", ["owner", "turn", "submission", "failed", "future", "ticker", "url", "guard", "no-final", "late", "url-prefix"])
def test_summary_rejects_unrelated_or_unverifiable_role_evidence(team_report, monkeypatch, damage):
    run, tool, journals, states = team_report
    if damage == "owner": states["analyst-session"]["agentId"] = "other"
    if damage == "turn": run["analysts"]["fundamental"]["turnId"] = "other-turn"
    if damage == "submission": run["analysts"]["fundamental"]["clientSubmissionId"] = "other-submission"
    if damage == "failed": journals["analyst-session"][-1] = replace(journals["analyst-session"][-1], status="failed")
    if damage == "no-final": journals["analyst-session"] = [e for e in journals["analyst-session"] if e.event_type != EVENT_ASSISTANT_ITEM_COMMITTED]
    if damage == "late": journals["analyst-session"][-1] = replace(journals["analyst-session"][-1], timestamp="2026-10-07T12:00:00+08:00")
    if damage == "url-prefix": journals["summary-session"] = turn("summary-session", "st", "ss", ANSWER.replace(URL, URL + ".evil"))
    if damage in {"future", "ticker", "url"}:
        meta = tool["citations"][0]["financialEvidence"][0]
        meta[{"future": "publishedAt", "ticker": "ticker", "url": "sourceUrl"}[damage]] = {
            "future": "2027-01-01T00:00:00+08:00", "ticker": "000858", "url": "https://example.com/other.pdf"}[damage]
        journals["analyst-session"] = turn("analyst-session", "at", "as", "opinion", tool)
    if damage == "guard":
        def deny(*_): raise runs.FinancialTeamRunConflictError("changed binding")
        monkeypatch.setattr(runs, "require_current_financial_team_run_bindings", deny)
    assert "200.00" not in exported()


def test_conflicting_pdf_excerpts_are_missing_instead_of_selecting_a_role(team_report):
    run, tool, journals, states = team_report
    run["analysts"]["news"] = {"agentId": "news", "sessionId": "news-session", "turnId": "nt", "clientSubmissionId": "ns"}
    states["news-session"] = {"agentId": "news"}
    other = json.loads(json.dumps(tool))
    other["results"][0]["excerpt"] = "营业收入 300.00 元"
    other["citations"][0]["financialEvidence"][0]["excerptSha256"] = hashlib.sha256("营业收入 300.00 元".encode()).hexdigest()
    journals["news-session"] = turn("news-session", "nt", "ns", "opinion", other)
    assert "200.00" not in exported()


def test_duplicate_tool_observations_do_not_erase_verified_evidence(team_report):
    _, _, journals, _ = team_report
    journals["analyst-session"].insert(2, replace(journals["analyst-session"][1], event_id="duplicate"))
    assert "200.00 元" in exported()


def test_ambiguous_summary_run_and_plain_opinion_cannot_supply_evidence(team_report, tmp_path):
    (tmp_path / "another.json").write_text("{}")
    assert "200.00" not in exported()


def test_catalog_and_export_apply_the_same_team_evidence(team_report):
    row = reports._completed_report_from_events(team_report[2]["summary-session"], "summary-session", "st", agent_id="owner")
    assert row[0] == exported()


def test_tampered_excerpt_cannot_reuse_the_original_hash(team_report):
    _, tool, journals, _ = team_report
    tool["results"][0]["excerpt"] = "营业收入 200.00 元；其他数字 300.00 元"
    journals["analyst-session"] = turn("analyst-session", "at", "as", "opinion", tool)
    assert "200.00" not in exported()


def test_superseded_branch_tool_is_not_original_evidence(team_report):
    _, _, journals, _ = team_report
    original = journals["analyst-session"]
    marker = event(EVENT_BRANCH_REBASE, 5, "analyst-session", "at", {
        "operation": "edit", "branchId": "new", "fromEventId": original[0].event_id,
        "replacedTurnIds": []})
    journals["analyst-session"] = [*original, marker,
        replace(original[2], event_id="active-final", sequence=6),
        replace(original[3], event_id="active-terminal", sequence=7)]
    assert "200.00" not in exported()


@pytest.mark.parametrize("damage", ["provisional", "nonterminal", "failed-final", "failed-item"])
def test_latest_answer_revision_and_errors_control_role_eligibility(team_report, damage):
    _, _, journals, _ = team_report
    original = journals["analyst-session"]
    payload = dict(original[2].payload, revision=1)
    if damage == "provisional": payload["provisional"] = True
    if damage == "nonterminal": payload["terminal"] = False
    if damage == "failed-final": payload["status"] = "failed"
    if damage == "failed-item": payload.update(kind="error", itemId="error", status="failed")
    revised = replace(original[2], event_id="revised", sequence=4, payload=payload)
    journals["analyst-session"] = [*original[:3], revised, replace(original[3], sequence=5)]
    assert "200.00" not in exported()


def test_same_second_role_completion_cannot_prove_prior_evidence(team_report):
    _, _, journals, _ = team_report
    original = journals["analyst-session"]
    original[-1] = replace(original[-1], timestamp=journals["summary-session"][0].timestamp)
    assert "200.00" not in exported()


def test_latest_failed_tool_call_cannot_fall_back_to_earlier_success(team_report):
    _, _, journals, _ = team_report
    original = journals["analyst-session"]
    payload = {"toolCall": dict(original[1].payload["toolCall"], status="failed")}
    failed = replace(original[1], event_id="latest-tool", sequence=3, payload=payload)
    journals["analyst-session"] = [*original[:2], failed,
        replace(original[2], sequence=4), replace(original[3], sequence=5)]
    assert "200.00" not in exported()


@pytest.mark.parametrize("damage", ["old-branch", "latest-failed"])
def test_summary_own_tools_follow_active_branch_and_latest_call(team_report, damage):
    _, tool, journals, _ = team_report
    # No analyst source can mask a stale summary-only tool regression.
    journals["analyst-session"] = turn("analyst-session", "at", "as", "opinion")
    original = turn("summary-session", "st", "ss", ANSWER, tool)
    if damage == "old-branch":
        marker = event(EVENT_BRANCH_REBASE, 3, "summary-session", "new-turn", {
            "operation": "edit", "branchId": "new", "fromEventId": original[0].event_id,
            "replacedTurnIds": []})
        journals["summary-session"] = [*original[:2], marker,
            replace(original[2], event_id="active-final", sequence=4),
            replace(original[3], sequence=5)]
    else:
        payload = {"toolCall": dict(original[1].payload["toolCall"], status="failed")}
        failed = replace(original[1], event_id="latest-tool", sequence=3, payload=payload)
        journals["summary-session"] = [*original[:2], failed,
            replace(original[2], sequence=4), replace(original[3], sequence=5)]
    assert "200.00" not in exported()


def test_duplicate_submission_mapping_and_after_summary_tools_fail_closed(team_report):
    _, _, journals, _ = team_report
    journals["analyst-session"].append(replace(journals["analyst-session"][0], turn_id="interference"))
    assert "200.00" not in exported()
    journals["analyst-session"].pop()
    journals["analyst-session"][-1] = replace(journals["analyst-session"][-1], timestamp="2026-10-06T13:00:02+08:00")
    assert "200.00" not in exported()


@pytest.mark.parametrize("conflict", [False, True])
def test_original_market_quote_is_reused_but_conflicting_quotes_are_not(team_report, conflict):
    run, _, journals, states = team_report
    source = "https://gu.qq.com/sh600519/gp"
    payload = {"ok": True, "status": "ok", "ticker": "sh600519", "source": "腾讯财经",
        "sourceUrl": source, "currency": "CNY", "priceUnit": "元", "quote": {
            "symbol": "sh600519", "ticker": "600519", "currency": "CNY", "priceUnit": "CNY/share",
            "price": 200, "timestamp": "2026-09-30T16:15:00+08:00"}}
    answer = f"## 结论\n贵州茅台 sh600519 股价 200.00 元，行情日期 2026-09-30，腾讯财经 {source}。"
    journals["summary-session"] = turn("summary-session", "st", "ss", answer)
    analyst = turn("analyst-session", "at", "as", "opinion", payload)
    analyst[1] = replace(analyst[1], payload={"toolCall": {"callId": "tc", "name": "financial_market_snapshot_tool", "result": json.dumps(payload), "status": "completed"}})
    journals["analyst-session"] = analyst
    if conflict:
        run["analysts"]["market"] = {"agentId": "market", "sessionId": "market-session", "turnId": "mt", "clientSubmissionId": "ms"}
        states["market-session"] = {"agentId": "market"}
        payload["quote"]["price"] = 300
        other = turn("market-session", "mt", "ms", "opinion", payload)
        other[1] = replace(other[1], payload={"toolCall": {"callId": "tc", "name": "financial_market_snapshot_tool", "result": json.dumps(payload), "status": "completed"}})
        journals["market-session"] = other
    assert ("200.00 元" in exported()) is not conflict
