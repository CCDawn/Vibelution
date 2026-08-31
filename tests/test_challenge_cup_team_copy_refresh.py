"""Version-gated managed copy refresh for the materialized Challenge Cup Team.

Pins the ``challengeCupTeamCopyVersion`` contract: a materialized team record
whose description/purpose exactly match the previous managed copy (v2) is
refreshed to the canonical phased (a_then_b) copy and stamped with the current
version; customized copies are never overwritten; bootstrap surfaces the
refresh as a required step only while the copy is outdated.
"""

from __future__ import annotations

from core.web.services import agent_directory_service, team_service
from core.web.services.team import system_bootstrap, system_teams

_V2_COPY = system_teams._CHALLENGE_CUP_TEAM_COPY_HISTORY[2]
_V3_COPY = system_teams._challenge_cup_research_team_copy_fields()


def _use_tmp_project_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)


def _seed_team_record(copy: dict[str, str], *, version: int | None = None) -> None:
    now = team_service.utc_now_iso()
    team = {
        "teamId": team_service.CHALLENGE_CUP_RESEARCH_TEAM_ID,
        "name": team_service.RESEARCH_TEAM_DISPLAY_NAME,
        "description": copy["description"],
        "purpose": copy["purpose"],
        "status": team_service.DEFAULT_TEAM_STATUS,
        "members": [],
        "linkedChatRoomId": "",
        "createdAt": now,
        "updatedAt": now,
    }
    if version is not None:
        team["challengeCupTeamCopyVersion"] = version
    with team_service._TEAM_LOCK:
        state = team_service._load_index()
        state.setdefault("teams", []).append(team)
        state["updatedAt"] = now
        team_service._save_index(state)


def _stored_team() -> dict:
    with team_service._TEAM_LOCK:
        state = team_service._load_index()
        return dict(team_service._find_team(state, team_service.CHALLENGE_CUP_RESEARCH_TEAM_ID) or {})


def test_placeholder_carries_phased_copy_and_version() -> None:
    placeholder = system_teams._challenge_cup_research_team_placeholder("2026-01-01T00:00:00Z")

    assert placeholder["description"] == _V3_COPY["description"]
    assert placeholder["purpose"] == _V3_COPY["purpose"]
    assert placeholder["challengeCupTeamCopyVersion"] == system_teams.CHALLENGE_CUP_TEAM_COPY_VERSION
    # The phased copy keeps the six-loop order and stacks experiments behind it.
    assert "125 题" in placeholder["purpose"]
    assert "反馈修正" in placeholder["purpose"]
    assert "深实验" in placeholder["purpose"]


def test_materialized_v2_team_copy_is_refreshed(tmp_path, monkeypatch) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_team_record(_V2_COPY)

    assert system_teams.challenge_cup_research_team_copy_outdated() is True
    assert "challenge_cup_team_copy_refresh" in system_bootstrap._system_team_bootstrap_required_steps()

    result = system_teams.apply_challenge_cup_research_team_copy_refresh(reason="test")
    assert result["refreshed"] is True
    assert result["skippedCustom"] is False

    stored = _stored_team()
    assert stored["description"] == _V3_COPY["description"]
    assert stored["purpose"] == _V3_COPY["purpose"]
    assert stored["challengeCupTeamCopyVersion"] == system_teams.CHALLENGE_CUP_TEAM_COPY_VERSION
    assert system_teams.challenge_cup_research_team_copy_outdated() is False
    assert "challenge_cup_team_copy_refresh" not in (
        system_bootstrap._system_team_bootstrap_required_steps()
    )


def test_custom_team_copy_is_never_overwritten(tmp_path, monkeypatch) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    custom = {"description": "运营自定义的团队描述", "purpose": "运营自定义的团队目标"}
    _seed_team_record(custom)

    assert system_teams.challenge_cup_research_team_copy_outdated() is False
    result = system_teams.apply_challenge_cup_research_team_copy_refresh(reason="test")

    assert result["refreshed"] is False
    assert result["skippedCustom"] is True
    stored = _stored_team()
    assert stored["description"] == custom["description"]
    assert stored["purpose"] == custom["purpose"]
    assert "challengeCupTeamCopyVersion" not in stored


def test_current_team_copy_refresh_is_a_noop(tmp_path, monkeypatch) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_team_record(_V3_COPY, version=system_teams.CHALLENGE_CUP_TEAM_COPY_VERSION)

    assert system_teams.challenge_cup_research_team_copy_outdated() is False
    result = system_teams.apply_challenge_cup_research_team_copy_refresh(reason="test")

    assert result["refreshed"] is False
    assert result["skippedCustom"] is False


def test_missing_team_copy_refresh_is_a_noop(tmp_path, monkeypatch) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)

    assert system_teams.challenge_cup_research_team_copy_outdated() is False
    result = system_teams.apply_challenge_cup_research_team_copy_refresh(reason="test")

    assert result["teamPresent"] is False
    assert result["refreshed"] is False
