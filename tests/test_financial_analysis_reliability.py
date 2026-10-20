"""Live-analysis regressions: budget drift, ETF reads, and reference holdings."""

from copy import deepcopy
import json

import pytest

from core.web.services import financial_market_service as market
from core.web.services.financial_preferences import advisor, advisor_proposals, workspace
from core.web.services.financial_preferences.analysis_checks import assess_budget
from core.web.services.financial_preferences.position_evidence import is_reference_position
from core.web.services.financial_preferences_service import FinancialPreferenceError
from tests.test_financial_advisor import env, _fence, _confirm, _position, _plan, _adopt, _execute
from tests.test_financial_report_service import _turn
from tests.test_financial_advisor_calculator import calculate, held, quotes, order, NOW
from tests.test_financial_market_service import market_quote_wire
from tests.test_financial_market_tools import snapshot
from tools.financial_market_tools import financial_market_snapshot_tool


def test_native_6000_budget_and_600_volatility_detect_the_original_wrong_answer():
    events = _turn(request="我有约6000元闲置资金，接受600元以上波动，最大亏损未确认。")
    result = assess_budget("以600元起步。对600元预算的适配较差。", events, "turn-1", None, None)
    assert result["budgetCny"] == 6000 and result["budgetSource"] == "conversation"
    assert len(result["issues"]) == 1
    assert "600 元" in result["issues"][0]


@pytest.mark.parametrize("answer", [
    "投资预算6000元，最大亏损未确认；接受600元波动不等于最大亏损600元。",
    "预算6000元。假设预算600元，则另行分析。",
    "预算6000元。假设预算600元，600元预算只适合观察。",
    "预算6000元。\n> 预算600元，600元预算仅为示例。",
    "上一轮把预算写成600元的结论作废。预算6000元。",
    '此前说“预算600元”是错误的。预算6000元。',
    "预算6000元。\n```json\n{\"example\": \"预算600元\"}\n```",
])
def test_volatility_hypotheticals_quotes_and_corrections_are_not_conflicts(answer):
    events = _turn(request="投资预算6000元，接受600元波动。")
    assert not assess_budget(answer, events, "turn-1", None, None)["issues"]


def test_new_request_wins_and_future_turn_or_invisible_guidance_is_not_authority():
    events = _turn(request="预算6000元", turn_id="old")
    events += _turn(request="预算改为8000元", turn_id="now", guidance="预算600元")
    events += _turn(request="预算9000元", turn_id="future")
    result = assess_budget("预算8000元", events, "now", {"budgetCny": 6000}, None)
    assert result["budgetCny"] == 8000 and not result["issues"]
    assert assess_budget("预算600元", events, "now", None, None)["issues"]


def test_explicit_budget_clauses_are_not_hidden_by_conditionals_or_corrections():
    events = _turn(request="预算6000元", turn_id="old") + _turn(request="预算改为8000元，不是6000元", turn_id="now")
    result = assess_budget("预算6000元", events, "now", None, None)
    assert result["budgetCny"] == 8000 and result["issues"]
    assert assess_budget("预算600元，如果担心波动可以观望", _turn(request="预算6000元"), "turn-1", None, None)["issues"]


def test_saved_current_profile_takes_precedence_over_older_conversation_budget():
    events = _turn(request="预算6000元", turn_id="old") + _turn(request="请按当前保存的投资条件分析", turn_id="now")
    result = assess_budget("预算8000元", events, "now", {"budgetCny": 8000}, None)
    assert result == {"budgetCny": 8000, "budgetSource": "saved_profile", "issues": []}


def test_ambiguous_budget_is_not_arbitrarily_selected_and_unknown_is_not_a_pass():
    events = _turn(request="预算6000元，预算8000元")
    result = assess_budget("预算6000元", events, "turn-1", {"budgetCny": 7000}, None)
    assert result["budgetCny"] is None and result["issues"]
    unknown = assess_budget("可以先观望", _turn(request="我接受600元波动"), "turn-1", None, None)
    assert unknown == {"budgetCny": None, "budgetSource": "unknown", "issues": []}


@pytest.mark.parametrize("rate", ["千分之五", "0.5%", "5‰", "万分之五十", "万分之五十五", "百分之零点五", "为成交额的0.5%"])
def test_stock_stamp_duty_order_of_magnitude_errors_are_not_confirmable(rate):
    result = assess_budget(f"预算6000元。股票卖出另有印花税约{rate}。", _turn(request="预算6000元"), "turn-1", {"budgetCny": 6000, "market": "CN"}, None)
    assert any("印花税" in issue for issue in result["issues"])


@pytest.mark.parametrize("text", [
    "股票卖出印花税0.05%", "股票卖出印花税万分之五", "股票卖出印花税0.5‰",
    "ETF卖出印花税0%", "历史2019年股票卖出印花税0.1%",
    "港股卖出时，印花税率0.1%", "ETF交易时，印花税0%",
    "历史2019年股票卖出时，印花税0.1%",
    "美国股票卖出印花税0%", "境外股票卖出印花税0%",
])
def test_current_stock_fee_units_and_unrelated_market_claims_are_not_false_conflicts(text):
    assert not assess_budget(text, _turn(request="预算6000元"), "turn-1", {"budgetCny": 6000, "market": "CN"}, None)["issues"]


@pytest.mark.parametrize("text", [
    "ETF免印花税，股票卖出印花税0.5%。",
    "股票买入和卖出印花税均为0.5%。",
])
def test_explicit_stock_sell_fee_assertion_is_checked_after_other_market_clause(text):
    assert assess_budget(text, _turn(request="预算6000元"), "turn-1", {"budgetCny": 6000, "market": "CN"}, None)["issues"]


def test_wrong_budget_proposal_cannot_be_confirmed_or_write_native_state(env):
    path, events = env
    profile = {"budgetCny": 600}
    from core.web.services.financial_preferences.investment import InvestmentProfile
    proposal = {"kind": "profile", "baseFingerprint": workspace.get_workspace("owner")["investmentStateFingerprint"], "profile": InvestmentProfile(**profile).model_dump()}
    events[:] = _turn(request="我有约6000元闲置资金", answer="预算600元\n" + _fence(proposal))
    before = deepcopy(events)
    result = advisor_proposals.get_proposal("owner", "session-1", "turn-1")
    assert result["proposal"] is None and result["assessment"]["issues"]
    with pytest.raises(FinancialPreferenceError):
        _confirm()
    assert not path.exists() and events == before


def test_plain_answer_without_proposal_is_checked_and_preserved(env):
    path, events = env
    events[:] = _turn(request="我有约6000元闲置资金", answer="以600元起步。")
    before = deepcopy(events)
    result = advisor_proposals.get_proposal("owner", "session-1", "turn-1")
    assert result["proposal"] is None and result["assessment"]["budgetCny"] == 6000
    assert result["assessment"]["issues"] and events == before and not path.exists()


def test_stock_fee_conflict_blocks_profile_confirmation_without_mutating_workspace(env):
    path, events = env
    from core.web.services.financial_preferences.investment import InvestmentProfile

    proposal = {"kind": "profile", "baseFingerprint": workspace.get_workspace("owner")["investmentStateFingerprint"], "profile": InvestmentProfile(budgetCny=6000).model_dump()}
    events[:] = _turn(request="预算6000元", answer="预算6000元。股票卖出印花税为成交额的0.5%。\n" + _fence(proposal))
    before = deepcopy(events)
    result = advisor_proposals.get_proposal("owner", "session-1", "turn-1")
    assert result["proposal"] is None and any("印花税" in issue for issue in result["assessment"]["issues"])
    with pytest.raises(FinancialPreferenceError):
        _confirm()
    assert not path.exists() and events == before


@pytest.mark.parametrize("code, expected", [("510300", "sh510300"), ("sh510880", "sh510880"), ("510500", "sh510500"), ("159915", "sz159915"), ("sz159919", "sz159919")])
def test_etfs_are_readable_but_not_admitted_as_a_share_trades(code, expected, monkeypatch):
    assert market.normalize_symbol(code) == expected
    with pytest.raises(market.MarketDataError):
        market.normalize_a_share_symbol(code)
    monkeypatch.setattr(market, "get_stock_snapshot", lambda symbol, period: snapshot(symbol))
    result = json.loads(financial_market_snapshot_tool(code, limit=2))
    assert result["ok"] and result["ticker"] == expected
    assert result["instrumentType"] == "etf" and result["priceUnit"] == "元/份"
    assert result["tradingCalculationSupported"] is False


def test_etf_quote_has_no_invented_stock_valuation_and_keeps_provider_time():
    wire = market_quote_wire("sh510300", {1: "沪深300ETF", 2: "510300", 3: "4.123", 4: "4.100", 5: "4.110", 6: "123", 30: "20261020161450", 31: "0.023", 32: "0.56", 33: "4.130", 34: "4.090", 37: "5.07", 39: "0", 45: "9999", 46: "0"})
    quote = market.parse_quote(wire, "510300")
    assert quote["price"] == 4.123 and quote["volume"] == 12300
    assert quote["timestamp"] == "2026-10-20T16:14:50+08:00"
    assert quote["peRatio"] is quote["pbRatio"] is quote["marketCap"] is None


@pytest.mark.parametrize("note", ["验收20261011手工持仓", "[测试]记录", "模拟持仓", "20261011功能验收", "fixture: demo", "仅用于验收", "这是测试持仓", "仅供模拟交易使用", "模拟盘持仓"])
def test_explicit_reference_markers_are_isolated(note):
    assert is_reference_position({"note": note})


@pytest.mark.parametrize("note", ["", "真实持仓", "非模拟持仓", "公司测试业务增长", "压力测试后继续持有"])
def test_ordinary_notes_and_negated_markers_are_not_reference_holdings(note):
    assert not is_reference_position({"note": note})


def test_reference_holdings_do_not_inflate_assets_and_block_adoption():
    value = held()
    value["manualPositions"][0]["note"] = "验收20261011手工持仓"
    before = deepcopy(value)
    result = calculate(value, [order()], quotes(), now=NOW)
    assert not result["passed"] and any("测试" in reason for reason in result["blockers"])
    assert value == before


def test_execution_cannot_relabel_a_reference_snapshot_as_actual(env):
    plan = _plan(env)
    _adopt(plan)
    path, _ = env
    before = path.read_bytes()
    with pytest.raises(FinancialPreferenceError, match="参考记录"):
        _execute(plan, actualPositions=[_position(note="验收20261011手工持仓")])
    assert path.read_bytes() == before


def test_reference_holdings_are_not_sent_for_quotes_or_injected_in_context(env, monkeypatch):
    from core.web.services.financial_assistant_service import PROFILE, ROLE
    from core.web.services.financial_preferences.investment import InvestmentProfile, build_investment_context_lines
    from core.web.services import financial_research_service as research

    state = workspace._empty("owner")
    state["investmentProfile"] = InvestmentProfile(holdingsStatus="recorded").model_dump()
    state["manualPositions"] = [_position(note="验收20261011手工持仓", quantity=9999)]
    state = advisor.project_workspace(state)
    monkeypatch.setattr(workspace, "get_workspace", lambda _: deepcopy(state))
    monkeypatch.setattr(research, "batch_quotes", lambda _: pytest.fail("sample holdings must not leave the private workspace"))
    agent = {"agentId": "owner", "status": "active", "primaryMode": "general", "roleKey": ROLE, "metadata": {"financialAssistantProfile": PROFILE, "financialAssistantSetup": "ready"}}
    text = "\n".join(build_investment_context_lines(agent))
    assert "已从真实资产分析中隔离" in text and "ManualPositions: null" in text
    assert "9999" not in text and "不得按空仓分析" in text
    assert advisor._quotes(state, []) == {}


def test_actual_execution_does_not_gain_etf_admission_from_read_support(env):
    plan = _plan(env)
    _adopt(plan)
    before = env[0].read_bytes()
    stock = {"symbol": "sh510300", "ticker": "510300", "name": "沪深300ETF", "market": "上交所"}
    with pytest.raises(FinancialPreferenceError, match="A 股股票"):
        _execute(plan, actualPositions=[_position(stock=stock)])
    assert env[0].read_bytes() == before
