"""Failures in one system Team must not starve independent initialization."""
from __future__ import annotations

import pytest

from core.web.services import team_service as service
from core.web.services.team import system_bootstrap


@pytest.fixture
def bootstrap_state(monkeypatch):
    state = dict(service._TEAM_SYSTEM_BOOTSTRAP_STATE)
    state.update(status="idle", attempt=0, checkedAtMonotonic=0.0)
    monkeypatch.setattr(service, "_TEAM_SYSTEM_BOOTSTRAP_STATE", state)
    monkeypatch.setattr(service, "_TEAM_SYSTEM_BOOTSTRAP_THREAD", None)
    monkeypatch.setattr(system_bootstrap, "_record_system_team_bootstrap_event", lambda *args, **kwargs: None)
    return state


def test_missing_challenge_assets_do_not_block_other_system_teams(monkeypatch, bootstrap_state):
    calls = []

    def missing_challenge():
        calls.append("challenge")
        raise service.TeamServiceError("Challenge Cup AgentDirectory asset is missing: coordinator")

    monkeypatch.setattr(service, "bootstrap_challenge_cup_research_team", missing_challenge)
    monkeypatch.setattr(service, "ensure_ai_search_system_team", lambda: calls.append("ai_search"))
    monkeypatch.setattr(service, "ensure_knowledge_expansion_team_agents", lambda **kwargs: calls.append("knowledge"))
    monkeypatch.setattr(service, "ensure_evolution_system_teams", lambda: calls.append("evolution"))
    monkeypatch.setattr(system_bootstrap, "_apply_challenge_cup_context_policy_migration", lambda **kwargs: None)
    monkeypatch.setattr(system_bootstrap, "_apply_challenge_cup_team_copy_refresh", lambda **kwargs: None)
    monkeypatch.setattr(system_bootstrap, "_system_team_bootstrap_required_steps", lambda: ["challenge_cup_research_team"])

    system_bootstrap._run_system_team_bootstrap(
        "failed-assets", ["challenge_cup_research_team", "ai_search_system_team",
                          "knowledge_expansion_team_agents", "evolution_system_teams"], "team_list",
    )

    assert calls == ["challenge", "ai_search", "knowledge", "evolution"]
    assert bootstrap_state["status"] == "failed"
    assert bootstrap_state["requiredSteps"] == ["challenge_cup_research_team"]
    assert "asset is missing" in bootstrap_state["lastError"]
    assert bootstrap_state["checkedAtMonotonic"] > 0


def test_fresh_directory_initializes_independent_teams_without_creating_challenge_assets(tmp_path, monkeypatch, bootstrap_state):
    from tests.test_team_service import _use_tmp_project_root

    _use_tmp_project_root(tmp_path, monkeypatch)
    steps = system_bootstrap._system_team_bootstrap_required_steps()
    assert "challenge_cup_research_team" in steps
    system_bootstrap._run_system_team_bootstrap("fresh-directory", steps, "team_list")
    assert bootstrap_state["status"] == "failed"
    assert "Challenge Cup AgentDirectory asset is missing:" in bootstrap_state["lastError"]
    assert bootstrap_state["requiredSteps"] == ["challenge_cup_research_team"]
    teams = service.list_teams_compact()["teams"]
    team_ids = {team["teamId"] for team in teams}
    assert service.AI_SEARCH_TEAM_ID in team_ids
    assert service.KNOWLEDGE_EXPANSION_TEAM_ID in team_ids
    assert service.EVOLUTION_SYSTEM_TEAM_IDS <= team_ids
    assert service.CHALLENGE_CUP_RESEARCH_TEAM_ID not in team_ids


@pytest.mark.parametrize("allow_sync_check", [True, False])
@pytest.mark.parametrize("status", ["failed", "needs_retry"])
def test_failed_bootstrap_reads_keep_diagnosis_until_retry_window(monkeypatch, bootstrap_state, allow_sync_check, status):
    bootstrap_state.update(status=status, lastError="missing assets", attempt=7,
                           requiredSteps=["challenge_cup_research_team"], checkedAtMonotonic=100.0)
    now = [101.0]
    monkeypatch.setattr(service, "_perf_counter", lambda: now[0])
    threads = []

    class Thread:
        def __init__(self, **kwargs):
            threads.append(kwargs)

        def start(self):
            pass

        def is_alive(self):
            return False

    monkeypatch.setattr(service.threading, "Thread", Thread)
    monkeypatch.setattr(system_bootstrap, "_system_team_bootstrap_required_steps", lambda: ["challenge_cup_research_team"])
    monkeypatch.setattr(service, "_try_acquire_team_lock", lambda: True)
    monkeypatch.setattr(service, "_release_team_lock_if_acquired", lambda acquired: None)
    for _ in range(5):
        snapshot = system_bootstrap.request_system_team_bootstrap(allow_sync_check=allow_sync_check)
        assert snapshot["status"] == status
        assert snapshot["lastError"] == "missing assets"
        assert snapshot["attempt"] == 7
    assert threads == []

    now[0] = 100.0 + service.TEAM_SYSTEM_BOOTSTRAP_READY_CACHE_TTL_SECONDS + 1
    snapshot = system_bootstrap.request_system_team_bootstrap(allow_sync_check=allow_sync_check)
    assert snapshot["status"] == "running"
    assert snapshot["attempt"] == 8
    assert len(threads) == 1
