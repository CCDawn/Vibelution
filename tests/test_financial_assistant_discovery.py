from __future__ import annotations

from copy import deepcopy

import pytest

from core.web.services import agent_directory_service as directory
from core.web.services import financial_assistant_service as financial
from core.web.services.financial_backtest import runtime as backtests
from core.web.services.financial_jobs import runtime as jobs


@pytest.fixture
def registry(monkeypatch):
    state = {"agents": [
        {"agentId": "older", "createdAt": "2025-01-01", "metadata": {"financialAssistantProfile": financial.PROFILE}},
        {"agentId": "newer", "status": " active ", "updatedAt": "2026-01-01", "metadata": {"financialAssistantProfile": financial.PROFILE}},
        {"agentId": "archived", "status": "archived", "metadata": {"financialAssistantProfile": financial.PROFILE}},
        {"agentId": "other", "metadata": {"financialAssistantProfile": "other-profile"}},
        {"agentId": "unrelated", "metadata": None},
        {"agentId": "", "metadata": {"financialAssistantProfile": financial.PROFILE}},
        "invalid",
    ]}
    monkeypatch.setattr(directory, "_load_repaired_state_for_read", lambda: (state, True))

    def forbid_projection(*args, **kwargs):
        raise AssertionError("Worker discovery must not build Agent API projections")

    monkeypatch.setattr(directory, "list_agents", forbid_projection)
    monkeypatch.setattr(directory, "_agent_to_api", forbid_projection)
    monkeypatch.setattr(directory, "_build_agent_api_config_hydration_context", forbid_projection)
    monkeypatch.setattr(directory, "load_state", forbid_projection)
    return state


@pytest.mark.parametrize("worker", [backtests, jobs])
def test_worker_discovery_reads_only_ids_from_canonical_registry(registry, worker):
    before = deepcopy(registry)
    assert worker._financial_assistant_ids() == ["newer", "older"]
    assert registry == before


def test_discovery_observes_profile_status_and_membership_changes_on_next_read(registry):
    assert backtests._financial_assistant_ids() == ["newer", "older"]
    registry["agents"][1]["status"] = "archived"
    registry["agents"][0]["metadata"]["financialAssistantProfile"] = "other-profile"
    registry["agents"].append({"agentId": "added", "metadata": {"financialAssistantProfile": financial.PROFILE}})
    assert jobs._financial_assistant_ids() == ["added"]
    registry["agents"] = []
    assert backtests._financial_assistant_ids() == []


def test_id_discovery_preserves_explicit_project_scope(tmp_path, monkeypatch):
    original_root = directory._active_project_root()
    seen = []

    def load():
        seen.append(directory._active_project_root())
        return {"agents": [{"agentId": "scoped", "metadata": {"profile": "selected"}}]}, True

    monkeypatch.setattr(directory, "_load_repaired_state_for_read", load)
    assert directory.find_agent_ids_by_metadata("profile", "selected", project_root=tmp_path) == ["scoped"]
    assert seen == [tmp_path]
    assert directory._active_project_root() == original_root


@pytest.mark.parametrize("worker", [backtests, jobs])
def test_registry_failure_is_not_converted_to_an_empty_owner_list(monkeypatch, worker):
    def fail():
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(directory, "_load_repaired_state_for_read", fail)
    with pytest.raises(RuntimeError, match="registry unavailable"):
        worker._financial_assistant_ids()
