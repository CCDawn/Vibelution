"""Market wrapper schema, deny-first policy, and real native executor contract."""

import ast
import json
from pathlib import Path
from typing import Annotated, Literal

import pytest
from langchain_core.tools import tool
from pydantic import Field, ValidationError

from core.authorization.tool_policy_evaluator import evaluate_tool_policy, normalize_legacy_tool_policy
from core.authorization.tool_policy_models import TurnToolGrant
from core.web.services import tool_catalog
from core.infrastructure.event_bus import EventNames, get_event_bus
from tests.helpers.tool_authorization import authorized_agent_tool_executor
from tests.test_financial_knowledge_service import finance_env as _finance_env
from tests.test_financial_report_registry import definition
from tests.test_financial_market_tools import overseas_snapshot, snapshot
from tools import financial_market_tools as market_tools

finance_env = _finance_env
NAME = "financial_market_snapshot_tool"
SCREEN_NAME = "financial_market_screen_tool"
ROOT = Path(__file__).resolve().parents[1]


def registered_tool():
    return definition("tools/Key_Tools.py", NAME, {
        "tool": tool,
        "Annotated": Annotated, "Literal": Literal, "Field": Field,
        "_financial_market_snapshot_impl": market_tools.financial_market_snapshot_tool,
    })


def registered_screen_tool():
    return definition("tools/Key_Tools.py", SCREEN_NAME, {
        "tool": tool,
        "Annotated": Annotated, "Literal": Literal, "Field": Field,
        "_financial_market_screen_impl": market_tools.financial_market_screen_tool,
    })


def test_market_wrapper_schema_dispatch_and_unique_registration(monkeypatch):
    wrapper = registered_tool()
    schema = wrapper.args_schema.model_json_schema()
    assert schema["required"] == ["ticker"]
    assert set(schema["properties"]) == {"ticker", "period", "limit"}
    assert schema["properties"]["period"]["default"] == "day"
    assert schema["properties"]["period"]["enum"] == ["day", "week", "month"]
    assert schema["properties"]["limit"]["default"] == 20
    assert schema["properties"]["limit"]["minimum"] == 1
    assert schema["properties"]["limit"]["maximum"] == 120
    calls = []
    monkeypatch.setattr(market_tools.market, "get_stock_snapshot", lambda *args: calls.append(args) or snapshot("sh600519"))
    result = json.loads(wrapper.invoke({"ticker": "sh600519", "period": "week", "limit": 3}))
    assert calls == [("sh600519", "week")]
    for invalid in ({"ticker": "600519", "period": "minute"}, {"ticker": "600519", "limit": 121}, {"ticker": "600519", "limit": True}):
        with pytest.raises(ValidationError):
            wrapper.invoke(invalid)
    assert len(calls) == 1
    assert result["quote"]["timestamp"]
    source = ast.parse((ROOT / "tools/Key_Tools.py").read_text(encoding="utf-8-sig"))
    builder = next(item for item in source.body if isinstance(item, ast.FunctionDef) and item.name == "_build_key_tools")
    assert sum(isinstance(item, ast.Name) and item.id == NAME for item in builder.body[-1].value.elts) == 1


def test_market_tool_is_explicit_read_only_network_access_without_model_cost():
    descriptor = tool_catalog.build_tool_descriptor(NAME, args_schema=registered_tool().args_schema.model_json_schema())
    assert descriptor.risk == "network" and descriptor.scopes == ("network",)
    assert descriptor.approval == "on_request"
    assert NAME in tool_catalog.explicit_allow_tool_names()
    assert "read_only" in descriptor.capabilities
    assert "model_cost" not in tool_catalog.risk_tags_for_tool(NAME)


def test_market_screen_wrapper_schema_dispatch_and_unique_registration(monkeypatch):
    wrapper = registered_screen_tool()
    schema = wrapper.args_schema.model_json_schema()
    assert set(schema["properties"]) == {
        "min_price", "max_price", "min_change_percent", "max_change_percent",
        "min_pe", "max_pe", "min_volume_lots", "min_pb", "max_pb",
        "min_turnover_yuan", "max_turnover_yuan", "sort_by", "direction", "limit",
    }
    assert schema.get("required", []) == []
    assert schema["properties"]["limit"]["default"] == 15
    assert schema["properties"]["limit"]["minimum"] == 1
    assert schema["properties"]["limit"]["maximum"] == 20
    calls = []
    monkeypatch.setattr(market_tools.research, "screen_stocks", lambda **kwargs: calls.append(kwargs) or {
        "source": "新浪财经", "sourceUrl": "https://vip.stock.finance.sina.com.cn/mkt/#hs_a",
        "fetchedAt": "2026-10-05T07:00:00+00:00", "dataDate": None, "dataTime": "15:00:00",
        "coverage": {"providerTotal": 10, "loaded": 10, "complete": True, "failedPages": [],
                     "invalidRows": 0, "duplicateRows": 0, "totalFiltered": 1},
        "items": [{"symbol": "sh600519", "ticker": "600519", "name": "贵州茅台", "market": "上交所",
                   "price": 1600.0, "changePercent": 1.0, "peRatio": 20.0, "pbRatio": 8.0,
                   "volumeLots": 1000, "turnoverYuan": 1_000_000.0, "timeOfDay": "15:00:00"}],
    })

    result = json.loads(wrapper.invoke({
        "min_price": 100,
        "max_change_percent": 5,
        "min_turnover_yuan": 1000000,
        "sort_by": "turnoverYuan",
        "direction": "asc",
        "limit": 5,
    }))

    assert calls == [{
        "min_price": 100, "max_price": None, "min_change_percent": None,
        "max_change_percent": 5, "min_pe": None, "max_pe": None,
        "min_volume_lots": None, "min_pb": None, "max_pb": None,
        "min_turnover_yuan": 1000000, "max_turnover_yuan": None,
        "sort_by": "turnoverYuan", "direction": "asc", "page": 1, "page_size": 5,
    }]
    assert result["items"][0]["symbol"] == "sh600519"
    assert result["coverage"]["complete"] is True
    for invalid in ({"limit": 21}, {"min_price": -1}, {"max_pe": 100001}):
        with pytest.raises(ValidationError):
            wrapper.invoke(invalid)
    source = ast.parse((ROOT / "tools/Key_Tools.py").read_text(encoding="utf-8-sig"))
    builder = next(item for item in source.body if isinstance(item, ast.FunctionDef) and item.name == "_build_key_tools")
    assert sum(isinstance(item, ast.Name) and item.id == SCREEN_NAME for item in builder.body[-1].value.elts) == 1


def test_market_screen_tool_is_explicit_read_only_network_access_without_model_cost():
    descriptor = tool_catalog.build_tool_descriptor(
        SCREEN_NAME, args_schema=registered_screen_tool().args_schema.model_json_schema()
    )
    assert descriptor.risk == "network" and descriptor.scopes == ("network",)
    assert descriptor.approval == "on_request"
    assert SCREEN_NAME in tool_catalog.explicit_allow_tool_names()
    assert "read_only" in descriptor.capabilities
    assert "stock_screening" in descriptor.capabilities
    assert "model_cost" not in tool_catalog.risk_tags_for_tool(SCREEN_NAME)
    financial_bundle = next(
        bundle for bundle in tool_catalog.list_tool_bundles()
        if bundle["bundleId"] == "financial_reports"
    )
    assert SCREEN_NAME in financial_bundle["toolNames"]
    assert SCREEN_NAME in financial_bundle["preferredToolNames"]


@pytest.mark.parametrize("assigned,network,blocked,grant,expected", [
    (False, "controlled", [], {}, "not_assigned"),
    (True, "none", [], {}, "network_denied"),
    (True, "controlled", [NAME], {}, "agent_blocked"),
    (True, "controlled", [], {"network_access": "none"}, "network_denied"),
    (True, "controlled", [], {"denied_tools": (NAME,)}, "turn_denied"),
    (True, "controlled", [], {"approval_mode": "never"}, "approval_required"),
    (True, "controlled", [], {}, None),
])
def test_market_uses_existing_deny_first_authorization(assigned, network, blocked, grant, expected):
    descriptor = tool_catalog.build_tool_descriptor(NAME, args_schema=registered_tool().args_schema.model_json_schema())
    policy = normalize_legacy_tool_policy({
        "allowedTools": [NAME] if assigned else [], "blockedTools": blocked,
        "networkAccess": network, "mutationAccess": "none",
    }, registered_tool_names=[NAME], policy_id="market-test")
    grant_args = {"allowed_capabilities": ("financial_market",), "denied_tools": (), "approval_mode": "on_request", **grant}
    result = evaluate_tool_policy(agent_id="market-test", policy=policy,
        grant=TurnToolGrant(turn_id="market-test", source="session", **grant_args),
        descriptors=[descriptor], registry_version=1, registry_fingerprint="market-test")
    if expected:
        assert NAME not in result.executable_tools
        assert dict(result.denied)[NAME].code.value == expected
    else:
        assert result.executable_tools == (NAME,)


@pytest.mark.parametrize("ticker", ["sh600519", "hk00700", "usNVDA"])
def test_actual_native_executor_returns_complete_json_and_blocks_unassigned_network(finance_env, monkeypatch, ticker):
    calls = []
    provider_snapshot = snapshot(ticker) if ticker == "sh600519" else overseas_snapshot(ticker)
    monkeypatch.setattr(market_tools.market, "get_stock_snapshot", lambda *args: calls.append(args) or provider_snapshot)
    with authorized_agent_tool_executor(finance_env["owner"], executable_tools=(NAME,)) as execute:
        raw, _ = execute(NAME, {"ticker": ticker, "period": "day", "limit": 2})
    result = json.loads(raw)
    assert result["ticker"] == ticker and result["ok"] is True
    assert result["quote"]["timestamp"] and result["sourceUrl"]
    assert result["quote"] == provider_snapshot["stock"]
    if ticker != "sh600519":
        assert result["adjustment"] == "raw" and result["volumeUnit"] == "shares"
        assert result["candles"]["rows"][0][-1] == 7654321
    assert len(raw) <= market_tools.MAX_RESULT_CHARS
    assert len(calls) == 1
    with authorized_agent_tool_executor(finance_env["owner"], executable_tools=()) as execute:
        raw, _ = execute(NAME, {"ticker": ticker})
    assert len(calls) == 1
    assert "未被本回合授权" in str(raw) or "未授权" in str(raw) or "blocked" in str(raw).lower()


def test_actual_executor_emits_failure_for_unavailable_quotes(finance_env, monkeypatch):
    def unavailable(*args):
        raise market_tools.market.MarketDataError("provider unavailable")

    monkeypatch.setattr(market_tools.market, "get_stock_snapshot", unavailable)
    events = []
    bus = get_event_bus()
    publish = bus.publish

    def capture(name, payload, *args, **kwargs):
        if name in {EventNames.TOOL_SUCCESS, EventNames.TOOL_ERROR}:
            events.append((name, payload))
        return publish(name, payload, *args, **kwargs)

    monkeypatch.setattr(bus, "publish", capture)
    with authorized_agent_tool_executor(finance_env["owner"], executable_tools=(NAME,)) as execute:
        raw, _ = execute(NAME, {"ticker": "600519"})
    assert json.loads(raw)["ok"] is False
    assert events[-1][0] == EventNames.TOOL_ERROR
    assert events[-1][1]["semanticStatus"] == "failed"


def test_actual_native_executor_runs_screen_only_after_finance_tool_authorization(finance_env, monkeypatch):
    calls = []
    monkeypatch.setattr(market_tools.research, "screen_stocks", lambda **kwargs: calls.append(kwargs) or {
        "source": "新浪财经", "sourceUrl": "https://vip.stock.finance.sina.com.cn/mkt/#hs_a",
        "fetchedAt": "2026-10-05T07:00:00+00:00", "dataDate": None, "dataTime": None,
        "coverage": {"providerTotal": 10, "loaded": 10, "complete": True, "failedPages": [],
                     "invalidRows": 0, "duplicateRows": 0, "totalFiltered": 0},
        "items": [],
    })
    with authorized_agent_tool_executor(finance_env["owner"], executable_tools=(SCREEN_NAME,)) as execute:
        raw, _ = execute(SCREEN_NAME, {"min_price": 1, "limit": 3})
    result = json.loads(raw)
    assert result["ok"] is True and result["status"] == "complete"
    assert calls and calls[0]["min_price"] == 1 and calls[0]["page_size"] == 3
    with authorized_agent_tool_executor(finance_env["owner"], executable_tools=()) as execute:
        blocked, _ = execute(SCREEN_NAME, {"min_price": 1})
    assert len(calls) == 1
    assert "未被本回合授权" in str(blocked) or "未授权" in str(blocked) or "blocked" in str(blocked).lower()
