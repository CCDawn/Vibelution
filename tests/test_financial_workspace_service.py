"""Workspace settings preserve revisions, owner boundaries and native authorities."""

import json

import pytest

from core.web.services import financial_preferences_service as service
from core.web.services.financial_preferences import workspace

STOCK = {"symbol": "sh600519", "ticker": "600519", "name": "贵州茅台", "market": "上交所"}


@pytest.fixture
def settings_env(tmp_path, monkeypatch):
    path = tmp_path / "financial-workspace.json"
    monkeypatch.setattr(workspace, "_agent", lambda agent_id: {"agentId": agent_id})
    monkeypatch.setattr(workspace, "_path", lambda agent_id: path)
    return path


def test_read_does_not_create_state_and_partial_updates_preserve_other_sections(settings_env):
    empty = service.get_workspace_settings("owner")
    assert empty["revision"] == 0 and not settings_env.exists()
    first = service.update_workspace_settings("owner", 0, {"watchlist": [{**STOCK, "tags": ["消费"], "note": "关注财报"}]})
    second = service.update_workspace_settings("owner", 1, {"selectedStock": STOCK})
    assert second["revision"] == 2 and second["watchlist"] == first["watchlist"]
    assert service.get_workspace_settings("owner")["selectedStock"] == STOCK


def test_us_provider_exchange_suffix_is_canonicalized_for_watchlist_and_manual_positions(settings_env):
    provider_stock = {"symbol": "usAAPL", "ticker": "AAPL.OQ", "name": "苹果", "market": "NASDAQ"}
    result = service.update_workspace_settings("owner", 0, {
        "selectedStock": provider_stock,
        "watchlist": [{**provider_stock, "tags": [], "note": ""}],
        "manualPositions": [{"id": "apple", "stock": provider_stock, "quantity": 5, "costPrice": 180, "currency": "USD"}],
    })
    assert result["selectedStock"] == {**provider_stock, "ticker": "AAPL"}
    assert result["watchlist"][0]["ticker"] == "AAPL"
    assert result["manualPositions"][0]["stock"]["ticker"] == "AAPL"


def test_us_share_class_is_not_mistaken_for_exchange_suffix_and_ticker_conflicts_are_rejected(settings_env):
    brk = {"symbol": "usBRK.B", "ticker": "BRK.B", "name": "伯克希尔", "market": "NYSE"}
    result = service.update_workspace_settings("owner", 0, {"selectedStock": brk})
    assert result["selectedStock"]["symbol"] == "usBRK.B"
    assert result["selectedStock"]["ticker"] == "BRK.B"
    with pytest.raises(service.FinancialPreferenceError, match="不匹配"):
        service.update_workspace_settings("owner", 1, {"selectedStock": {**brk, "ticker": "MSFT.OQ"}})
    with pytest.raises(service.FinancialPreferenceError, match="不匹配"):
        service.update_workspace_settings("owner", 1, {"selectedStock": {"symbol": "usAAPL", "ticker": "AAPL.X", "name": "苹果", "market": "NASDAQ"}})
    assert service.get_workspace_settings("owner")["revision"] == 1


def test_stale_revision_cannot_overwrite_latest_user_settings(settings_env):
    service.update_workspace_settings("owner", 0, {"selectedStock": STOCK})
    before = settings_env.read_bytes()
    with pytest.raises(service.FinancialPreferenceError, match="其他页面"):
        service.update_workspace_settings("owner", 0, {"watchlist": []})
    assert settings_env.read_bytes() == before


@pytest.mark.parametrize("patch", [
    {"watchlist": [{**STOCK, "tags": ["x" * 31]}]},
    {"watchlist": [{**STOCK, "ticker": "000001"}]},
    {"watchlist": [STOCK, STOCK]},
    {"manualPositions": [{"id": "p1", "stock": STOCK, "quantity": float("inf"), "costPrice": 1, "currency": "CNY"}]},
    {"manualPositions": [{"id": "p1", "stock": STOCK, "quantity": 100, "costPrice": 1, "currency": "USD"}]},
    {"unknown": []},
])
def test_invalid_settings_never_create_file(settings_env, patch):
    with pytest.raises(service.FinancialPreferenceError):
        service.update_workspace_settings("owner", 0, patch)
    assert not settings_env.exists()


def test_corrupt_state_is_not_replaced(settings_env):
    settings_env.write_text('{"broken":true}', encoding="utf-8")
    with pytest.raises(service.FinancialPreferenceError, match="未覆盖"):
        service.update_workspace_settings("owner", 0, {"watchlist": []})
    assert json.loads(settings_env.read_text())["broken"] is True


@pytest.mark.parametrize("payload", [
    {"schemaVersion": True, "agentId": "owner", "revision": 1},
    {"schemaVersion": 1.0, "agentId": "owner", "revision": 1},
    {"schemaVersion": 1, "agentId": "owner", "revision": 1, "futureSection": {"value": "keep"}},
])
def test_invalid_persisted_schema_or_unknown_top_level_field_is_not_overwritten(settings_env, payload):
    original = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    settings_env.write_bytes(original)

    with pytest.raises(service.FinancialPreferenceError, match="未覆盖") as error:
        service.update_workspace_settings("owner", 1, {"watchlist": []})

    assert error.value.status_code == 409
    assert settings_env.read_bytes() == original


def test_research_profiles_allow_only_one_default(settings_env):
    profile = {"id": "one", "name": "财报", "scope": "financial", "depth": "detailed", "isDefault": True}
    with pytest.raises(service.FinancialPreferenceError, match="一个默认"):
        service.update_workspace_settings("owner", 0, {"profiles": [profile, {**profile, "id": "two"}]})


def test_review_bookmarks_validate_exact_owned_report_without_storing_transcript(settings_env, monkeypatch):
    from core.web.services import financial_report_service as reports

    observed = []
    monkeypatch.setattr(reports, "_completed_report", lambda *ids: observed.append(ids) or ("PRIVATE REPORT", "2026-10-06", "600519"))
    case = {"id": "case1", "sessionId": "session1", "turnId": "turn1", "title": "财报复盘"}
    service.update_workspace_settings("owner", 0, {"reviewCases": [case]})
    assert observed == [("owner", "session1", "turn1")]
    assert "PRIVATE REPORT" not in settings_env.read_text(encoding="utf-8")


def test_stale_review_bookmark_remains_removable_after_native_report_disappears(settings_env, monkeypatch):
    from core.web.services import financial_report_service as reports

    monkeypatch.setattr(reports, "_completed_report", lambda *ids: ("原文", "2026-10-06", "600519"))
    case = {"id": "case1", "sessionId": "session1", "turnId": "turn1", "title": "财报复盘"}
    service.update_workspace_settings("owner", 0, {"reviewCases": [case]})
    monkeypatch.setattr(reports, "_completed_report", lambda *ids: (_ for _ in ()).throw(reports.FinancialReportNotFound("已删除")))
    result = service.update_workspace_settings("owner", 1, {"reviewCases": []})
    assert result["reviewCases"] == []
