from __future__ import annotations

import ast
import copy
import json
from datetime import date
from pathlib import Path
from typing import Annotated

import pytest
from langchain_core.tools import tool
from pydantic import Field, ValidationError

from core.web.services import tool_catalog
from core.web.services.financial_market.indices import INDEX_NAMES
from core.web.services.financial_research.as_of import research_analysis_date_context
from tests.helpers.tool_authorization import authorized_agent_tool_executor
from tests.test_financial_knowledge_service import finance_env as _finance_env
from tests.test_financial_report_registry import definition
from tools import financial_index_tools as indices

finance_env = _finance_env
NAME = "financial_index_context_tool"


def index_payload(limit: int = 2) -> dict:
    return {"status": "available", "source": "腾讯财经", "requestedCutoff": "2026-10-06",
            "priceUnit": "points", "adjustment": "raw_index",
            "fetchedAt": "2026-10-10T08:00:00+00:00", "items": [
                {"symbol": symbol, "name": name, "status": "available", "basis": "daily_close",
                 "sourceUrl": f"https://gu.qq.com/{symbol}/gp",
                 "quote": {"price": 3100, "previousClose": 3000, "change": 100,
                           "changePercent": 3.3333, "date": "2026-09-30"},
                 "candles": [{"date": f"2026-09-{day:02}", "open": 3000, "close": 3100,
                              "high": 3200, "low": 2900} for day in range(31 - limit, 31)]}
                for symbol, name in INDEX_NAMES.items()]}


def registered_tool():
    return definition("tools/Key_Tools.py", NAME,
                      {"tool": tool, "Annotated": Annotated, "Field": Field,
                       "_financial_index_context_impl": indices.financial_index_context_tool})


def test_index_tool_schema_registration_and_explicit_network_permission():
    wrapper = registered_tool()
    schema = wrapper.args_schema.model_json_schema()
    assert set(schema["properties"]) == {"limit"}
    assert schema["properties"]["limit"]["default"] == 2
    for value in [1, 21, True]:
        with pytest.raises(ValidationError):
            wrapper.invoke({"limit": value})
    descriptor = tool_catalog.build_tool_descriptor(NAME, args_schema=schema)
    assert descriptor.risk == "network" and "read_only" in descriptor.capabilities
    assert NAME in tool_catalog.explicit_allow_tool_names()
    assert "model_cost" not in tool_catalog.risk_tags_for_tool(NAME)
    bundle = next(row for row in tool_catalog.TOOL_BUNDLE_DEFINITIONS if row["bundleId"] == "financial_reports")
    assert NAME in bundle["toolNames"] and NAME in bundle["preferredToolNames"]
    assert all(NAME not in row["toolNames"] for row in tool_catalog.TOOL_BUNDLE_DEFINITIONS if row is not bundle)
    source = ast.parse((Path(__file__).resolve().parents[1] / "tools/Key_Tools.py").read_text(encoding="utf-8-sig"))
    builder = next(row for row in source.body if isinstance(row, ast.FunctionDef) and row.name == "_build_key_tools")
    assert sum(isinstance(row, ast.Name) and row.id == NAME for row in builder.body[-1].value.elts) == 1


def test_native_cutoff_reaches_source_and_output_remains_complete_bounded_json(monkeypatch):
    source = index_payload(20)
    frozen = copy.deepcopy(source)
    calls = []
    monkeypatch.setattr(indices.market, "get_index_context", lambda **kwargs: calls.append(kwargs) or source)
    with research_analysis_date_context("研究日期：2026-10-06"):
        raw = registered_tool().invoke({"limit": 20})
    result = json.loads(raw)
    assert calls == [{"cutoff": date(2026, 10, 6), "limit": 20}]
    assert len(raw) <= indices.MAX_RESULT_CHARS
    assert len(result["items"]) == 5 and result["ok"] is True
    assert any(row["omittedCandleCount"] > 0 for row in result["items"])
    assert all(row["quote"]["date"] == "2026-09-30" for row in result["items"])
    assert source == frozen


def test_unavailable_provider_is_not_relabelled_success(monkeypatch):
    monkeypatch.setattr(indices.market, "get_index_context", lambda **_: {"status": "unavailable", "items": []})
    assert json.loads(indices.financial_index_context_tool())["ok"] is False


def test_native_executor_requires_index_authorization_and_preserves_json(finance_env, monkeypatch):
    calls = []
    monkeypatch.setattr(indices.market, "get_index_context", lambda **kwargs: calls.append(kwargs) or index_payload())
    with authorized_agent_tool_executor(finance_env["owner"], executable_tools=(NAME,)) as execute:
        raw, _ = execute(NAME, {"limit": 2})
    assert json.loads(raw)["ok"] is True
    with authorized_agent_tool_executor(finance_env["owner"], executable_tools=()) as execute:
        denied, _ = execute(NAME, {"limit": 2})
    assert len(calls) == 1
    assert "未授权" in str(denied) or "未被本回合授权" in str(denied) or "blocked" in str(denied).lower()
