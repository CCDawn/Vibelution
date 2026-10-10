from __future__ import annotations

import copy
import json
from datetime import date
from typing import Annotated, Literal

import pytest
from langchain_core.tools import tool
from pydantic import Field, ValidationError

from core.web.services.financial_research.as_of import research_analysis_date_context
from tests.helpers.tool_authorization import authorized_agent_tool_executor
from tests.test_financial_knowledge_service import finance_env as _finance_env
from tests.test_financial_market_tools import candle, overseas_snapshot, snapshot
from tests.test_financial_report_registry import definition
from tools import financial_market_tools as market_tools

finance_env = _finance_env
NAME = "financial_market_snapshot_tool"


def wrapper():
    return definition("tools/Key_Tools.py", NAME, {
        "tool": tool, "Annotated": Annotated, "Literal": Literal, "Field": Field,
        "_financial_market_snapshot_impl": market_tools.financial_market_snapshot_tool,
    })


def context():
    return {"status": "partial", "source": "东方财富", "symbol": "sz000001",
            "industry": {"label": "银行", "taxonomy": "eastmoney"}, "peerCoverage": "unavailable"}


def test_existing_snapshot_defaults_remain_unchanged_and_do_not_query_sector(monkeypatch):
    monkeypatch.setattr(market_tools.market, "get_stock_snapshot", lambda *_: snapshot())
    monkeypatch.setattr(market_tools.market, "get_sector_context", lambda *_args, **_kwargs: pytest.fail("implicit sector read"))
    value = json.loads(wrapper().invoke({"ticker": "000001"}))
    assert "sectorContext" not in value and value["quote"]["price"] == 12.34
    schema = wrapper().args_schema.model_json_schema()
    assert schema["properties"]["include_sector"]["default"] is False
    assert schema["required"] == ["ticker"]


@pytest.mark.parametrize("invalid", [1, "true", None])
def test_optional_sector_flag_requires_real_boolean(invalid):
    with pytest.raises(ValidationError):
        wrapper().invoke({"ticker": "000001", "include_sector": invalid})
    result = json.loads(market_tools.financial_market_snapshot_tool("000001", include_sector=invalid))
    assert result["ok"] is False


def test_sector_opt_in_preserves_source_object_and_native_cutoff(monkeypatch):
    source = context()
    before = copy.deepcopy(source)
    calls = []
    monkeypatch.setattr(market_tools.market, "get_stock_snapshot", lambda *_: snapshot())
    monkeypatch.setattr(market_tools.market, "get_sector_context", lambda symbol, **kwargs: calls.append((symbol, kwargs)) or source)
    with research_analysis_date_context("研究日期：2026-10-06"):
        raw = wrapper().invoke({"ticker": "000001", "include_sector": True})
    result = json.loads(raw)
    assert len(raw) <= market_tools.MAX_RESULT_CHARS
    assert calls == [("sz000001", {"cutoff": date(2026, 10, 6)})]
    assert result["sectorContext"] == source and result["status"] == "partial"
    assert result["quote"]["price"] == 12.34 and source == before


@pytest.mark.parametrize("failure", [market_tools.market.MarketDataError, RuntimeError, AttributeError])
def test_sector_source_failure_does_not_erase_primary_quote(monkeypatch, failure):
    monkeypatch.setattr(market_tools.market, "get_stock_snapshot", lambda *_: snapshot())

    def fail(*_args, **_kwargs):
        raise failure("private provider diagnostics")

    monkeypatch.setattr(market_tools.market, "get_sector_context", fail)
    raw = wrapper().invoke({"ticker": "000001", "include_sector": True})
    result = json.loads(raw)
    assert result["ok"] is True and result["quote"]["price"] == 12.34
    assert result["sectorContext"]["status"] == "unavailable"
    assert "private provider" not in raw


def test_foreign_sector_opt_in_does_not_query_a_share_source(monkeypatch):
    monkeypatch.setattr(market_tools.market, "get_stock_snapshot", lambda symbol, _: overseas_snapshot(symbol))
    monkeypatch.setattr(market_tools.market, "get_sector_context", lambda *_args, **_kwargs: pytest.fail("foreign sector read"))
    result = json.loads(wrapper().invoke({"ticker": "usNVDA", "include_sector": True}))
    assert result["sectorContext"]["reasonCode"] == "a_share_only"
    assert result["currency"] == "USD"


def test_native_executor_reuses_existing_explicit_snapshot_authorization(finance_env, monkeypatch):
    monkeypatch.setattr(market_tools.market, "get_stock_snapshot", lambda *_: snapshot())
    monkeypatch.setattr(market_tools.market, "get_sector_context", lambda *_args, **_kwargs: context())
    with authorized_agent_tool_executor(finance_env["owner"], executable_tools=(NAME,)) as execute:
        raw, _ = execute(NAME, {"ticker": "000001", "include_sector": True})
    assert json.loads(raw)["sectorContext"]["source"] == "东方财富"


def test_excessive_optional_payload_still_keeps_primary_quote(monkeypatch):
    monkeypatch.setattr(market_tools.market, "get_stock_snapshot", lambda *_: snapshot())
    monkeypatch.setattr(market_tools.market, "get_sector_context", lambda *_args, **_kwargs: {"status": "partial", "message": "x" * 2000})
    raw = wrapper().invoke({"ticker": "000001", "include_sector": True})
    result = json.loads(raw)
    assert len(raw) <= market_tools.MAX_RESULT_CHARS and result["quote"]["price"] == 12.34
    assert result["sectorContext"]["status"] == "unavailable"


def test_optional_sector_yields_to_requested_candles_without_mutating_source(monkeypatch):
    candles = [candle(f"2026-09-{day:02d}") for day in range(1, 26)]
    monkeypatch.setattr(market_tools.market, "get_stock_snapshot", lambda *_: snapshot(candles=candles))
    source = {**context(), "peers": [{"name": "x" * 190} for _ in range(5)]}
    before = copy.deepcopy(source)
    monkeypatch.setattr(market_tools.market, "get_sector_context", lambda *_args, **_kwargs: source)
    baseline_raw = market_tools.financial_market_snapshot_tool("000001", limit=20)
    baseline = json.loads(baseline_raw)
    monkeypatch.setattr(market_tools, "MAX_RESULT_CHARS", len(baseline_raw) + 450)
    observed = json.loads(market_tools.financial_market_snapshot_tool("000001", limit=20, include_sector=True))
    assert observed["candles"] == baseline["candles"]
    assert observed["quote"] == baseline["quote"] and source == before
    assert len(observed["sectorContext"]["peers"]) < 5
