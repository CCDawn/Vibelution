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
from tests.test_financial_market_tools import snapshot
from tools import financial_market_tools as market_tools

finance_env = _finance_env
NAME = "financial_market_snapshot_tool"
ROOT = Path(__file__).resolve().parents[1]


def registered_tool():
    return definition("tools/Key_Tools.py", NAME, {
        "tool": tool,
        "Annotated": Annotated, "Literal": Literal, "Field": Field,
        "_financial_market_snapshot_impl": market_tools.financial_market_snapshot_tool,
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


def test_actual_native_executor_returns_complete_json_and_blocks_unassigned_network(finance_env, monkeypatch):
    calls = []
    monkeypatch.setattr(market_tools.market, "get_stock_snapshot", lambda *args: calls.append(args) or snapshot("sh600519"))
    with authorized_agent_tool_executor(finance_env["owner"], executable_tools=(NAME,)) as execute:
        raw, _ = execute(NAME, {"ticker": "sh600519", "period": "day", "limit": 2})
    result = json.loads(raw)
    assert result["quote"]["timestamp"] and result["sourceUrl"]
    assert len(raw) <= market_tools.MAX_RESULT_CHARS
    assert len(calls) == 1
    with authorized_agent_tool_executor(finance_env["owner"], executable_tools=()) as execute:
        raw, _ = execute(NAME, {"ticker": "sh600519"})
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
