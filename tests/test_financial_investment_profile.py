"""Investment settings retain explicit unknowns and refresh only the owning Agent."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.financial_preferences import router
from core.web.services import agent_directory_service as directory
from core.web.services import financial_preferences_service as service
from core.web.services import team_service
from core.web.services.agent_directory import episodic_memory, projections
from core.web.services.financial_assistant_service import PROFILE, ROLE
from core.web.services.financial_preferences import workspace
from tests.test_financial_knowledge_service import finance_env as _finance_env

finance_env = _finance_env


@pytest.fixture
def settings_env(tmp_path, monkeypatch):
    path = tmp_path / "financial-workspace.json"
    monkeypatch.setattr(workspace, "_agent", lambda agent_id: {"agentId": agent_id})
    monkeypatch.setattr(workspace, "_path", lambda agent_id: path)
    return path


def _agent():
    return directory.create_agent_instance(
        display_name="Investment owner", primary_mode="general", role_key=ROLE,
        prompt_template_id="prompt-chat-default",
        metadata={"financialAssistantProfile": PROFILE, "financialAssistantSetup": "ready"},
    )


def _fail(*args, **kwargs):
    pytest.fail("unexpected financial or episodic read")


def _context(agent, monkeypatch):
    monkeypatch.setattr(projections, "_team_knowledge_access_lines", lambda *args: [])
    monkeypatch.setattr(team_service, "build_team_roster_context_lines", lambda *args: ["Roster: none"])
    return directory.build_agent_runtime_context_block(
        agent["agentId"], agent_snapshot=agent, group_events_snapshot=[],
        inbox_messages_snapshot=[], episodic_events_snapshot=[],
        memory_policy_snapshot={"enabled": False},
    )


def test_legacy_file_is_read_only_and_new_profile_preserves_other_sections(settings_env):
    legacy = workspace._empty("owner")
    del legacy["investmentProfile"]
    settings_env.write_text(json.dumps(legacy), encoding="utf-8")
    before = settings_env.read_bytes()
    assert service.get_workspace_settings("owner")["investmentProfile"] is None
    assert settings_env.read_bytes() == before
    first = service.update_workspace_settings("owner", 0, {"investmentProfile": {"budgetCny": 7000}})
    profile = first["investmentProfile"]
    assert profile == {
        "budgetCny": 7000, "availableCashCny": None, "horizonMonths": None, "flexibleHorizon": None,
        "maxLossCny": None, "cashReserveCny": None, "maxPositionPct": None,
        "market": "CN", "holdingsStatus": "unknown",
    }
    assert service.update_workspace_settings("owner", 1, {"watchlist": []})["investmentProfile"] == profile
    assert service.update_workspace_settings("owner", 2, {"investmentProfile": None})["investmentProfile"] is None


def test_null_and_replacement_do_not_recover_old_budget_and_revision_is_atomic(settings_env):
    service.update_workspace_settings("owner", 0, {"investmentProfile": {"budgetCny": 7000, "horizonMonths": 3}})
    latest = service.update_workspace_settings("owner", 1, {"investmentProfile": {"budgetCny": None, "flexibleHorizon": False}})
    assert latest["investmentProfile"]["budgetCny"] is None
    assert latest["investmentProfile"]["horizonMonths"] is None
    assert latest["investmentProfile"]["flexibleHorizon"] is False
    before = settings_env.read_bytes()
    with pytest.raises(service.FinancialPreferenceError) as error:
        service.update_workspace_settings("owner", 1, {"investmentProfile": {"budgetCny": 1}})
    assert error.value.status_code == 409 and settings_env.read_bytes() == before


@pytest.mark.parametrize("profile", [
    [], "private budget", {"extra": 1}, {"budgetCny": True}, {"budgetCny": "7000"},
    {"budgetCny": 0}, {"budgetCny": -1}, {"budgetCny": 1e8 + 1},
    {"budgetCny": float("inf")}, {"budgetCny": float("nan")},
    {"horizonMonths": True}, {"horizonMonths": 1.0}, {"horizonMonths": "3"},
    {"horizonMonths": 0}, {"horizonMonths": 121}, {"flexibleHorizon": 1},
    {"maxLossCny": -1}, {"maxLossCny": "0"}, {"cashReserveCny": False},
    {"cashReserveCny": float("inf")}, {"maxPositionPct": 0}, {"maxPositionPct": 101},
    {"maxPositionPct": "20"}, {"market": "US"}, {"market": None},
    {"holdingsStatus": None}, {"holdingsStatus": "empty"},
    {"budgetCny": 7000, "maxLossCny": 7001}, {"budgetCny": 7000, "cashReserveCny": 7001},
])
def test_strict_service_validation_never_creates_file(settings_env, profile):
    with pytest.raises(service.FinancialPreferenceError):
        service.update_workspace_settings("owner", 0, {"investmentProfile": profile})
    assert not settings_env.exists()


def test_zero_loss_and_reserve_are_known_and_unknown_budget_stays_unknown(settings_env):
    result = service.update_workspace_settings("owner", 0, {"investmentProfile": {
        "maxLossCny": 0, "cashReserveCny": 0, "horizonMonths": 120,
        "maxPositionPct": 100, "holdingsStatus": "none",
    }})["investmentProfile"]
    assert result["budgetCny"] is None and result["maxLossCny"] == result["cashReserveCny"] == 0
    assert result["holdingsStatus"] == "none"


@pytest.mark.parametrize("invalid", [{"budgetCny": float("nan")}, {"budgetCny": 7000, "unknown": "instruction"}])
def test_corrupt_profile_is_not_silently_replaced(settings_env, invalid):
    state = workspace._empty("owner")
    state["investmentProfile"] = invalid
    settings_env.write_text(json.dumps(state), encoding="utf-8")
    before = settings_env.read_bytes()
    with pytest.raises(service.FinancialPreferenceError) as error:
        service.update_workspace_settings("owner", 0, {"investmentProfile": None})
    assert error.value.status_code == 409 and settings_env.read_bytes() == before


def test_http_contract_is_strict_nullable_and_uses_existing_workspace_endpoint(settings_env):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    path = "/api/financial-preferences/owner/workspace"
    assert client.get(path).json()["investmentProfile"] is None
    for profile in ({"budgetCny": True}, {"budgetCny": "7000"}, {"horizonMonths": 3.0}, {"unexpected": 1}, {"budgetCny": 5, "maxLossCny": 6}):
        assert client.patch(path, json={"expectedRevision": 0, "patch": {"investmentProfile": profile}}).status_code == 422
    result = client.patch(path, json={"expectedRevision": 0, "patch": {"investmentProfile": {"budgetCny": 7000}}})
    assert result.status_code == 200 and result.json()["investmentProfile"]["holdingsStatus"] == "unknown"
    assert client.patch(path, json={"expectedRevision": 0, "patch": {"investmentProfile": None}}).status_code == 409
    assert client.patch(path, json={"expectedRevision": 1, "patch": {"investmentProfile": None}}).json()["investmentProfile"] is None


def test_owner_identity_and_private_territory_remain_required(finance_env, monkeypatch):
    owner, other = _agent(), _agent()
    service.update_workspace_settings(owner["agentId"], 0, {"investmentProfile": {"budgetCny": 7000}})
    assert service.get_workspace_settings(other["agentId"])["investmentProfile"] is None
    owner_path = workspace._path(owner["agentId"])
    assert owner_path != workspace._path(other["agentId"])
    monkeypatch.setattr(workspace, "_path", lambda *args: owner_path)
    with pytest.raises(service.FinancialPreferenceError):
        service.get_workspace_settings(other["agentId"])


def test_invalid_private_territory_fails_before_any_write(finance_env, monkeypatch):
    owner = _agent()
    monkeypatch.setattr(directory, "resolve_agent_workspace_territory", lambda *args: {"privateRoot": str(finance_env["root"] / "public")})
    with pytest.raises(service.FinancialPreferenceError) as error:
        service.update_workspace_settings(owner["agentId"], 0, {"investmentProfile": {"budgetCny": 7000}})
    assert error.value.status_code == 409


def test_each_turn_reads_latest_explicit_config_with_memory_off_and_dynamic_suffix(finance_env, monkeypatch):
    from core.orchestration.context_engine import _split_agent_runtime_context_block

    agent = _agent()
    monkeypatch.setattr(episodic_memory, "list_episodic_events", _fail)
    service.update_workspace_settings(agent["agentId"], 0, {"investmentProfile": {"budgetCny": 7000}})
    path = workspace._path(agent["agentId"])
    before = path.read_bytes()
    first = _context(agent, monkeypatch)
    assert '"budgetCny":7000.0' in first and "即使个人记忆关闭" in first
    assert path.read_bytes() == before
    static, dynamic = _split_agent_runtime_context_block(first)
    assert "本轮投资配置" not in static and "本轮投资配置" in dynamic
    assert first.index("本轮投资配置") > first.index("AgentInboxMessages:")
    service.update_workspace_settings(agent["agentId"], 1, {"investmentProfile": {"budgetCny": 9000}})
    second = _context(agent, monkeypatch)
    assert '"budgetCny":9000.0' in second and '"budgetCny":7000.0' not in second
    service.update_workspace_settings(agent["agentId"], 2, {"investmentProfile": None})
    assert "InvestmentProfile: null" in _context(agent, monkeypatch)


def test_read_failure_forbids_using_stale_budget_without_breaking_context(finance_env, monkeypatch):
    agent = _agent()
    path = workspace._path(agent["agentId"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"broken":true}', encoding="utf-8")
    block = _context(agent, monkeypatch)
    assert "AgentInboxMessages: none" in block and "禁止依据旧预算给出金额" in block
    assert "InvestmentProfile:" not in block


def test_explicit_recorded_holdings_include_latest_identity_and_cost_without_notes(finance_env, monkeypatch):
    agent = _agent()
    position = {
        "id": "user-position", "stock": {"symbol": "sh600519", "ticker": "600519", "name": "贵州茅台", "market": "上交所"},
        "quantity": 100, "costPrice": 1200, "currency": "CNY", "note": "PRIVATE_POSITION_NOTE",
    }
    service.update_workspace_settings(agent["agentId"], 0, {
        "investmentProfile": {"holdingsStatus": "recorded"}, "manualPositions": [position],
    })
    first = _context(agent, monkeypatch)
    line = next(line for line in first.splitlines() if line.startswith("ManualPositions: "))
    assert json.loads(line.removeprefix("ManualPositions: ")) == [{
        "stock": position["stock"], "quantity": 100, "costPrice": 1200, "currency": "CNY",
    }]
    assert "PRIVATE_POSITION_NOTE" not in first and "非交易账本，不含实时价" in first
    service.update_workspace_settings(agent["agentId"], 1, {"manualPositions": [{**position, "quantity": 200}]})
    assert '"quantity":200.0' in _context(agent, monkeypatch)


@pytest.mark.parametrize("status", ["none", "unknown"])
def test_unconfirmed_holdings_never_inject_legacy_manual_positions(finance_env, monkeypatch, status):
    agent = _agent()
    service.update_workspace_settings(agent["agentId"], 0, {
        "investmentProfile": {"holdingsStatus": status},
        "manualPositions": [{
            "id": "legacy", "stock": {"symbol": "sh600519", "ticker": "600519", "name": "LEGACY_STOCK", "market": "上交所"},
            "quantity": 100, "costPrice": 1200, "currency": "CNY",
        }],
    })
    block = _context(agent, monkeypatch)
    assert "ManualPositions:" not in block and "LEGACY_STOCK" not in block


def test_recorded_without_manual_positions_explicitly_keeps_holdings_unknown(finance_env, monkeypatch):
    agent = _agent()
    service.update_workspace_settings(agent["agentId"], 0, {"investmentProfile": {"holdingsStatus": "recorded"}})
    block = _context(agent, monkeypatch)
    assert "ManualPositions: null" in block and "实际持仓未知，不得按空仓分析" in block


@pytest.mark.parametrize("changes", [
    {"metadata": {}},
    {"metadata": {"financialAssistantProfile": "other", "financialAssistantSetup": "ready"}},
    {"roleKey": "researcher"}, {"status": "archived"}, {"primaryMode": "coding"},
    {"metadata": {"financialAssistantProfile": PROFILE, "financialAssistantSetup": "pending"}},
])
def test_ordinary_and_ineligible_agents_never_touch_financial_workspace(finance_env, monkeypatch, changes):
    agent = {**_agent(), **changes}
    monkeypatch.setattr(workspace, "get_workspace", _fail)
    monkeypatch.setattr(workspace, "_path", _fail)
    block = _context(agent, monkeypatch)
    assert "本轮投资配置" not in block
