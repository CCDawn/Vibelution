"""Explicit advisor proposals retain native source and atomic asset authority."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.chat.turn_journal import (
    EVENT_ASSISTANT_ITEM_COMMITTED, EVENT_BRANCH_REBASE, EVENT_TURN_COMPLETED,
    EVENT_TURN_FAILED, EVENT_TURN_INTERRUPTED,
)
from core.web.routes.financial_preferences import router
from core.web.services import financial_report_service as reports
from core.web.services import financial_research_service as research
from core.web.services.financial_preferences import advisor, advisor_proposals, workspace
from core.web.services.financial_preferences.investment import InvestmentProfile
from core.web.services.financial_preferences_service import FinancialPreferenceError
from tests.test_financial_report_service import _event, _turn


STOCK = {"symbol": "sh600000", "ticker": "600000", "name": "浦发银行", "market": "上交所"}
PROFILE = {**InvestmentProfile().model_dump(), "budgetCny": 7000.0, "availableCashCny": 7000.0, "cashReserveCny": 500.0, "maxPositionPct": 50.0, "holdingsStatus": "none"}
ORDERS = [{"symbol": "sh600000", "side": "buy", "quantity": 100}]


def _position(**changes):
    return {"id": "actual", "stock": dict(STOCK), "quantity": 100, "costPrice": 10, "currency": "CNY", "note": "", **changes}


def _fence(value):
    return "建议先核对风险。\n```investment-proposal\n" + json.dumps(value, ensure_ascii=False) + "\n```"


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / "financial-workspace.json"
    monkeypatch.setattr(workspace, "_agent", lambda agent_id: {"agentId": agent_id})
    monkeypatch.setattr(workspace, "_path", lambda agent_id: path)
    monkeypatch.setattr(reports.directory, "get_agent", lambda agent_id: {"agentId": agent_id, "metadata": {"financialAssistantProfile": "financial_assistant_v1"}})
    monkeypatch.setattr(reports.session_service, "load_session_chat_state", lambda root, session_id: {"agentId": "owner"})
    events = []
    monkeypatch.setattr(reports.session_service, "load_session_conversation_events_snapshot", lambda session_id: events)
    monkeypatch.setattr(research, "batch_quotes", lambda symbols: {
        "source": "test-provider", "items": [{"symbol": symbol, "quote": {"symbol": symbol, "price": 10, "timestamp": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}} for symbol in symbols],
    })
    return path, events


def _state():
    return workspace.get_workspace("owner")


def _proposal(events, *, kind="plan", turn="turn-1", **changes):
    value = {"kind": kind, "baseFingerprint": _state()["investmentStateFingerprint"]}
    if kind == "plan":
        value["plan"] = {"title": "分批买入计划", "rationale": "小额试仓，核对现金与风险", "orders": deepcopy(ORDERS), "reviewAfter": None}
    else:
        value["profile"] = dict(PROFILE)
    value.update(changes)
    events[:] = _turn(request="请制定投资计划", answer=_fence(value), turn_id=turn)
    return value


def _confirm(turn="turn-1", revision=None):
    return advisor.command("owner", {"action": "confirm_proposal", "expectedRevision": _state()["revision"] if revision is None else revision, "sessionId": "session-1", "turnId": turn})


def _plan(env):
    workspace.update_workspace("owner", 0, {"investmentProfile": PROFILE})
    _proposal(env[1])
    return _confirm()["investmentPlans"][-1]


def _adopt(plan, revision=None):
    return advisor.command("owner", {"action": "adopt", "expectedRevision": _state()["revision"] if revision is None else revision, "planId": plan["id"]})


def _execute(plan, **changes):
    return advisor.command("owner", {"action": "execute", "expectedRevision": _state()["revision"], "planId": plan["id"], "actualCashCny": 5980, "actualPositions": [_position(costPrice=10.15)], **changes})


def test_legacy_defaults_unknown_cash_and_plan_state_are_read_only(env):
    path, _ = env
    assert _state()["investmentPlans"] == [] and not path.exists()
    legacy = workspace._empty("owner")
    del legacy["investmentPlans"]
    legacy["investmentProfile"] = {"budgetCny": 7000}
    path.write_text(json.dumps(legacy), encoding="utf-8")
    before = path.read_bytes()
    state = _state()
    assert state["investmentProfile"]["availableCashCny"] is None
    assert state["investmentPlans"] == [] and path.read_bytes() == before
    assert len(state["investmentStateFingerprint"]) == 64
    state = workspace.update_workspace("owner", 0, {"investmentProfile": {"budgetCny": 7000, "availableCashCny": 9000}})
    assert state["investmentProfile"]["availableCashCny"] == 9000


def test_fingerprint_tracks_semantic_profile_and_positions_only(env):
    state = workspace.update_workspace("owner", 0, {"investmentProfile": PROFILE, "manualPositions": [_position(), _position(id="p2", stock={"symbol": "sz000001", "ticker": "000001", "name": "平安", "market": "深交所"})]})
    original = state["investmentStateFingerprint"]
    renamed = [{**row, "id": "new-" + row["id"], "stock": {**row["stock"], "name": "renamed"}, "note": "private note"} for row in reversed(state["manualPositions"])]
    state = workspace.update_workspace("owner", 1, {"manualPositions": renamed, "selectedStock": STOCK, "watchlist": [STOCK]})
    assert state["investmentStateFingerprint"] == original
    state = workspace.update_workspace("owner", 2, {"manualPositions": [{**row, "quantity": row["quantity"] + 1} for row in renamed]})
    assert state["investmentStateFingerprint"] != original


def test_proposal_read_uses_native_final_answer_and_never_writes(env):
    path, events = env
    proposal = _proposal(events)
    assert advisor_proposals.get_proposal("owner", "session-1", "turn-1") == {"proposal": proposal}
    assert not path.exists() and _state()["investmentPlans"] == []
    events[:] = _turn(request="仅普通聊天", answer="没有提案")
    assert advisor_proposals.get_proposal("owner", "session-1", "turn-1") == {"proposal": None}


def test_proposal_from_removed_native_branch_cannot_be_read_or_confirmed(env):
    _proposal(env[1])
    env[1].append(_event(EVENT_BRANCH_REBASE, 4, turn_id="turn-new", payload={"operation": "edit", "fromEventId": ""}))
    before = deepcopy(env[1])
    assert advisor_proposals.get_proposal("owner", "session-1", "turn-1")["proposal"] is None
    with pytest.raises(FinancialPreferenceError, match="没有可确认"):
        _confirm()
    assert env[1] == before and not env[0].exists()


def test_head_select_can_restore_proposal_with_original_native_turn_identity(env):
    proposal = _proposal(env[1])
    terminal_id = env[1][-1].event_id
    env[1].append(_event(EVENT_BRANCH_REBASE, 4, turn_id="turn-new", payload={"operation": "edit", "fromEventId": ""}))
    env[1].append(_event(EVENT_BRANCH_REBASE, 5, turn_id="turn-select", payload={"operation": "head_select", "fromEventId": terminal_id}))
    before = deepcopy(env[1])
    assert advisor_proposals.get_proposal("owner", "session-1", "turn-1")["proposal"] == proposal
    saved = _confirm()
    assert saved["investmentPlans"][-1]["source"] == {"sessionId": "session-1", "turnId": "turn-1"}
    assert env[1] == before


@pytest.mark.parametrize("invocation,iteration", [("inv-other", 0), ("inv-first", 1)])
def test_same_item_id_across_native_invocation_or_iteration_is_not_collapsed(env, invocation, iteration):
    value = _proposal(env[1])
    env[1][1].payload.update(invocationId="inv-first", iteration=0)
    second = {**env[1][1].payload, "invocationId": invocation, "iteration": iteration, "text": _fence(value)}
    env[1][:] = [env[1][0], env[1][1], _event(EVENT_ASSISTANT_ITEM_COMMITTED, 3, status="completed", payload=second), _event(EVENT_TURN_COMPLETED, 4, status="completed")]
    # Two independent answers each contain a proposal; the one-proposal rule
    # must reject both rather than silently retain whichever shared itemId won.
    assert advisor_proposals.get_proposal("owner", "session-1", "turn-1")["proposal"] is None


def test_later_nonfinal_revision_cannot_resurrect_completed_proposal(env, monkeypatch):
    value = _proposal(env[1])
    first = {"type": "assistant_message", "channel": "answer", "phase": "final_answer", "status": "completed", "text": _fence(value), "itemId": "a", "revision": 0, "sequence": 1}
    monkeypatch.setattr(advisor_proposals, "session_turn_items_from_events", lambda *args, **kwargs: [first, {**first, "revision": 1, "sequence": 2, "phase": "commentary", "status": "running"}])
    assert advisor_proposals.get_proposal("owner", "session-1", "turn-1")["proposal"] is None


@pytest.mark.parametrize("field,value", [("quantity", True), ("costPrice", True), ("quantity", 1.5), ("quantity", "100")])
def test_execution_http_rejects_coerced_actual_numbers(env, field, value):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    payload = {"action": "execute", "expectedRevision": 0, "planId": "p", "actualCashCny": 10, "actualPositions": [_position(**{field: value})]}
    assert TestClient(app).post("/api/financial-preferences/owner/workspace/advisor/command", json=payload).status_code == 422


@pytest.mark.parametrize("terminal", [EVENT_TURN_FAILED, EVENT_TURN_INTERRUPTED])
def test_failed_and_stopped_turn_cannot_supply_proposal(env, terminal):
    value = _proposal(env[1])
    env[1][:] = _turn(request="请制定计划", answer=_fence(value), terminal=terminal)
    assert advisor_proposals.get_proposal("owner", "session-1", "turn-1")["proposal"] is None
    with pytest.raises(FinancialPreferenceError):
        _confirm()
    assert not env[0].exists()


def test_source_ownership_and_terminal_error_markers_fail_closed(env, monkeypatch):
    _proposal(env[1])
    monkeypatch.setattr(reports.session_service, "load_session_chat_state", lambda *args: {"agentId": "other"})
    with pytest.raises(FinancialPreferenceError) as error:
        advisor_proposals.get_proposal("owner", "session-1", "turn-1")
    assert error.value.status_code == 404
    monkeypatch.setattr(reports.session_service, "load_session_chat_state", lambda *args: {"agentId": "owner"})
    env[1][-1].payload["terminalReason"] = "stopped"
    assert advisor_proposals.get_proposal("owner", "session-1", "turn-1")["proposal"] is None


@pytest.mark.parametrize("mutation", [
    lambda value: {**value, "source": {"sessionId": "spoof", "turnId": "spoof"}},
    lambda value: {**value, "baseFingerprint": "bad"},
    lambda value: {**value, "plan": {**value["plan"], "status": "adopted"}},
    lambda value: {**value, "plan": {**value["plan"], "orders": [{**ORDERS[0], "quantity": True}]}},
    lambda value: {**value, "plan": {**value["plan"], "orders": ORDERS * 2}},
    lambda value: {**value, "plan": {**value["plan"], "reviewAfter": "2026-10-20"}},
])
def test_strict_proposal_parser_rejects_forged_or_invalid_fields(env, mutation):
    assert advisor_proposals.parse_proposal(_fence(mutation(_proposal(env[1])))) is None


def test_parser_rejects_multiple_fences_duplicate_json_and_partial_profile(env):
    answer = _fence(_proposal(env[1]))
    assert advisor_proposals.parse_proposal(answer + "\n" + answer) is None
    assert advisor_proposals.parse_proposal('```investment-proposal\n{"kind":"plan","kind":"profile"}\n```') is None
    value = _proposal(env[1], kind="profile", profile={"budgetCny": 7000})
    assert advisor_proposals.parse_proposal(_fence(value)) is None


def test_user_message_cannot_spoof_assistant_final_proposal(env):
    value = _proposal(env[1])
    env[1][:] = _turn(request=_fence(value), answer="")
    assert advisor_proposals.get_proposal("owner", "session-1", "turn-1")["proposal"] is None


def test_profile_requires_explicit_confirmation_and_current_fingerprint(env):
    _proposal(env[1], kind="profile")
    assert _state()["investmentProfile"] is None
    state = _confirm()
    assert state["investmentProfile"] == PROFILE
    assert state["revision"] == 1
    before = env[0].read_bytes()
    with pytest.raises(FinancialPreferenceError, match="已变化"):
        _confirm()
    assert env[0].read_bytes() == before


def test_patch_cannot_forge_plans_or_fingerprint(env):
    for patch in ({"investmentPlans": []}, {"investmentStateFingerprint": "0" * 64}):
        with pytest.raises(FinancialPreferenceError):
            workspace.update_workspace("owner", 0, patch)
    assert not env[0].exists()


def test_adoption_checks_then_preserves_assets_and_execution_records_actual_snapshot(env):
    plan = _plan(env)
    before = _state()
    assert advisor.check_plan("owner", plan["id"])["passed"]
    adopted = _adopt(plan)
    assert adopted["manualPositions"] == before["manualPositions"]
    assert adopted["investmentProfile"] == before["investmentProfile"]
    assert adopted["investmentPlans"][-1]["status"] == "adopted"
    executed = _execute(plan)
    assert executed["investmentProfile"]["availableCashCny"] == 5980
    assert executed["investmentProfile"]["holdingsStatus"] == "recorded"
    assert executed["manualPositions"][0]["costPrice"] == 10.15
    assert executed["investmentPlans"][-1]["status"] == "executed"
    assert executed["investmentPlans"][-1]["stateFingerprint"] == executed["investmentStateFingerprint"]
    assert not executed["investmentPlans"][-1]["needsReview"]


@pytest.mark.parametrize("patch", [
    {"investmentProfile": {**PROFILE, "budgetCny": 6000}},
    {"investmentProfile": {**PROFILE, "availableCashCny": 6000}},
    {"manualPositions": [_position()]},
])
def test_changed_profile_or_holdings_requires_review_and_blocks_adoption(env, patch):
    plan = _plan(env)
    updated = workspace.update_workspace("owner", 2, patch)
    assert updated["investmentPlans"][-1]["needsReview"]
    with pytest.raises(FinancialPreferenceError, match="已变化"):
        _adopt(plan)
    assert not advisor.check_plan("owner", plan["id"])["passed"]


def test_unrelated_change_leaves_plan_fresh_and_overdue_plan_needs_review(env):
    plan = _plan(env)
    updated = workspace.update_workspace("owner", 2, {"watchlist": [STOCK]})
    assert not updated["investmentPlans"][-1]["needsReview"]
    raw = workspace._load(env[0], "owner")
    raw["investmentPlans"][-1]["reviewAfter"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert advisor.project_workspace(raw)["investmentPlans"][-1]["needsReview"]


def test_new_plan_supersedes_prior_current_plan_and_keeps_history(env):
    first = _plan(env)
    _adopt(first)
    _proposal(env[1], turn="turn-2")
    state = _confirm("turn-2")
    assert [row["status"] for row in state["investmentPlans"]] == ["invalidated", "proposed"]
    with pytest.raises(FinancialPreferenceError):
        _execute(first)
    before = env[0].read_bytes()
    with pytest.raises(FinancialPreferenceError, match="已经确认"):
        _confirm("turn-2")
    assert env[0].read_bytes() == before


def test_plan_history_is_bounded_and_last_invalidation_does_not_revive_old_plan(env):
    workspace.update_workspace("owner", 0, {"investmentProfile": PROFILE})
    for number in range(22):
        turn = f"turn-{number}"
        _proposal(env[1], turn=turn)
        state = _confirm(turn)
    assert len(state["investmentPlans"]) == 20
    assert state["investmentPlans"][0]["source"]["turnId"] == "turn-2"
    assert all(row["status"] == "invalidated" for row in state["investmentPlans"][:-1])
    state = advisor.command("owner", {"action": "invalidate", "expectedRevision": state["revision"], "planId": state["investmentPlans"][-1]["id"]})
    current = next(line for line in advisor.advisor_context_lines(state) if line.startswith("CurrentInvestmentPlan: "))
    assert json.loads(current.removeprefix("CurrentInvestmentPlan: "))["status"] == "invalidated"


def test_concurrent_adoption_has_one_winner_under_same_revision(env):
    plan = _plan(env)
    def attempt(_):
        try:
            return _adopt(plan, revision=2)["revision"]
        except FinancialPreferenceError as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(results) == [3, 409]
    assert _state()["manualPositions"] == []


def test_execution_is_adopted_fresh_explicit_atomic_and_can_record_empty_holdings(env, monkeypatch):
    plan = _plan(env)
    with pytest.raises(FinancialPreferenceError):
        _execute(plan)
    _adopt(plan)
    before = env[0].read_bytes()
    with pytest.raises(FinancialPreferenceError):
        _execute(plan, actualPositions=[_position(currency="USD")])
    assert env[0].read_bytes() == before
    monkeypatch.setattr(workspace, "atomic_write_json", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        _execute(plan)
    assert env[0].read_bytes() == before
    monkeypatch.undo()
    # Explicit actual snapshot can differ completely from the recommendation.
    # Restore fixture-owned routing after undo for the final transaction.
    monkeypatch.setattr(workspace, "_agent", lambda agent_id: {"agentId": agent_id})
    monkeypatch.setattr(workspace, "_path", lambda agent_id: env[0])
    result = _execute(plan, actualCashCny=9000, actualPositions=[])
    assert result["manualPositions"] == [] and result["investmentProfile"]["holdingsStatus"] == "none"
    assert result["investmentProfile"]["availableCashCny"] == 9000


def test_execution_after_assets_change_is_rejected_without_overwriting_actuals(env):
    plan = _plan(env)
    _adopt(plan)
    workspace.update_workspace("owner", 3, {"investmentProfile": {**PROFILE, "availableCashCny": 7500}})
    before = env[0].read_bytes()
    with pytest.raises(FinancialPreferenceError, match="已变化"):
        _execute(plan)
    assert env[0].read_bytes() == before


def test_overdue_review_is_dynamic_read_only_and_blocks_adoption(env):
    plan = _plan(env)
    raw = workspace._load(env[0], "owner")
    raw["investmentPlans"][-1]["reviewAfter"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    env[0].write_text(json.dumps(raw), encoding="utf-8")
    before = env[0].read_bytes()
    assert _state()["investmentPlans"][-1]["needsReview"]
    assert env[0].read_bytes() == before
    with pytest.raises(FinancialPreferenceError):
        _adopt(plan)


def test_stale_quote_blocks_adoption_without_using_fetch_time(env, monkeypatch):
    plan = _plan(env)
    monkeypatch.setattr(research, "batch_quotes", lambda symbols: {"fetchedAt": datetime.now(timezone.utc).isoformat(), "items": [{"symbol": symbol, "quote": {"price": 10, "timestamp": "2020-01-01T10:00:00+08:00"}} for symbol in symbols]})
    before = env[0].read_bytes()
    assert not advisor.check_plan("owner", plan["id"])["passed"]
    with pytest.raises(FinancialPreferenceError, match="未通过"):
        _adopt(plan)
    assert env[0].read_bytes() == before


def test_quotes_are_fetched_outside_write_lock_and_racing_changes_reject_adoption(env, monkeypatch):
    plan = _plan(env)
    original = research.batch_quotes
    def race(symbols):
        # Another page can save while the provider is being fetched. A held
        # transaction lock here would deadlock or fail this separate thread.
        with ThreadPoolExecutor(max_workers=1) as pool:
            saved = pool.submit(workspace.update_workspace, "owner", 2, {"watchlist": [STOCK]}).result(timeout=3)
        assert saved["revision"] == 3
        return original(symbols)
    monkeypatch.setattr(research, "batch_quotes", race)
    with pytest.raises(FinancialPreferenceError, match="其他页面"):
        _adopt(plan, revision=2)
    assert _state()["investmentPlans"][-1]["status"] == "proposed"


def test_final_answer_latest_revision_is_used_without_touching_native_journal(env, monkeypatch):
    value = _proposal(env[1])
    native_before = deepcopy(env[1])
    base = {"type": "assistant_message", "channel": "answer", "phase": "final_answer", "status": "completed", "itemId": "answer-1"}
    monkeypatch.setattr(advisor_proposals, "session_turn_items_from_events", lambda *args, **kwargs: [
        {**base, "revision": 1, "sequence": 2, "text": _fence(value)},
        {**base, "revision": 2, "sequence": 3, "text": _fence({**value, "plan": {**value["plan"], "title": "新修订"}})},
    ])
    proposal = advisor_proposals.get_proposal("owner", "session-1", "turn-1")["proposal"]
    assert proposal["plan"]["title"] == "新修订"
    _confirm()
    assert env[1] == native_before


def test_hold_plan_remains_explicit_and_no_order_is_added(env):
    workspace.update_workspace("owner", 0, {"investmentProfile": PROFILE})
    _proposal(env[1], plan={"title": "继续观望", "rationale": "等待更多证据", "orders": [], "reviewAfter": None})
    plan = _confirm()["investmentPlans"][-1]
    assert advisor.check_plan("owner", plan["id"])["orders"] == []
    state = _adopt(plan)
    assert state["manualPositions"] == []
    assert state["investmentProfile"]["availableCashCny"] == 7000


def test_http_contract_blocks_spoofing_and_preserves_typed_calculator_output(env):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    base = "/api/financial-preferences/owner/workspace"
    for action in ("execute", "confirm_proposal"):
        result = client.post(base + "/advisor/command", json={"action": action, "expectedRevision": 0})
        assert result.status_code == 422
    assert client.patch(base, json={"expectedRevision": 0, "patch": {"investmentPlans": []}}).status_code == 422
    plan = _plan(env)
    response = client.post(base + "/advisor/check", json={"planId": plan["id"]})
    assert response.status_code == 200, response.text
    assert response.json()["passed"] and response.json()["orders"][0]["quoteSource"] == "test-provider"
    assert client.get(base + "/advisor/proposal", params={"sessionId": "session-1", "turnId": "turn-1"}).status_code == 200
    assert client.post(base + "/advisor/command", json={"action": "adopt", "expectedRevision": 2, "planId": plan["id"], "orders": []}).status_code == 422
    result = client.post(base + "/advisor/command", json={"action": "adopt", "expectedRevision": 2, "planId": plan["id"]})
    assert result.status_code == 200 and result.json()["investmentPlans"][-1]["status"] == "adopted"
    assert client.post(base + "/advisor/command", json={"action": "execute", "expectedRevision": 3, "planId": plan["id"], "actualCashCny": 6000}).status_code == 422


def test_existing_workspace_patch_numeric_coercion_remains_compatible(env):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    position = _position(quantity="100", costPrice="10.5")
    result = client.patch("/api/financial-preferences/owner/workspace", json={"expectedRevision": 0, "patch": {"manualPositions": [position]}})
    assert result.status_code == 200, result.text
    assert result.json()["manualPositions"][0]["quantity"] == 100
    assert result.json()["manualPositions"][0]["costPrice"] == 10.5


def test_both_workspace_and_advisor_writes_reject_utf8_size_without_overwrite(env, monkeypatch):
    workspace.update_workspace("owner", 0, {"investmentProfile": PROFILE})
    before = env[0].read_bytes()
    monkeypatch.setattr(workspace, "_MAX_STATE_BYTES", len(before) + 30)
    with pytest.raises(FinancialPreferenceError, match="存储上限"):
        workspace.update_workspace("owner", 1, {"watchlist": [{**STOCK, "note": "中文" * 100}]})
    assert env[0].read_bytes() == before
    _proposal(env[1])
    with pytest.raises(FinancialPreferenceError, match="存储上限"):
        _confirm()
    assert env[0].read_bytes() == before
    assert _state()["revision"] == 1


def test_read_only_freshness_and_fingerprint_are_never_persisted(env):
    _plan(env)
    raw = json.loads(env[0].read_text(encoding="utf-8"))
    assert "investmentStateFingerprint" not in raw
    assert "needsReview" not in raw["investmentPlans"][-1]
