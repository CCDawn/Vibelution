"""Native archive CAS runs under the Team lock before reserving any cascade."""
from copy import deepcopy
import threading

import pytest

from core.web.services import agent_directory_service as directory, team_service
from core.web.services.team import team_admission
from core.web.services.team.team_crud import TeamStateConflictError, team_record_fingerprint
from tests.test_team_knowledge_service import isolate_developer_sandbox_config
from tests.test_team_service import _use_tmp_project_root


@pytest.fixture
def archive_env(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = directory.create_agent_instance(display_name="Archive CAS member", direct_session_id="session-cas")
    team = team_service.create_team(name="Archive CAS Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    return team, agent


def _record(team_id):
    return deepcopy(team_service._find_team(team_service._load_index(), team_id))


def test_archive_stale_native_fingerprint_rejects_before_lease_or_cascade(archive_env, monkeypatch):
    team, agent = archive_env
    before = _record(team["teamId"])
    monkeypatch.setattr(team_service, "_cascade_archive_member_agents_unlocked",
                        lambda *_args, **_kwargs: pytest.fail("Stale archive entered cascade"))
    with pytest.raises(TeamStateConflictError):
        team_service.archive_team(team["teamId"], expected_fingerprint="0" * 64)
    assert _record(team["teamId"]) == before
    assert directory.get_agent(agent["agentId"])["status"] == "active"
    with team_service._TEAM_LOCK:
        team_admission.assert_roster_mutation_allowed(team["teamId"])


@pytest.mark.parametrize("mutation", ["member", "room"])
def test_archive_fingerprint_covers_roster_and_linked_room(archive_env, monkeypatch, mutation):
    team, agent = archive_env
    fingerprint = team_record_fingerprint(_record(team["teamId"]))
    state = team_service._load_index()
    record = team_service._find_team(state, team["teamId"])
    if mutation == "member":
        record["members"][0]["role"] = "changed after preview"
    else:
        record["linkedChatRoomId"] = "changed-room"
    team_service._save_index(state)
    monkeypatch.setattr(team_service, "_cascade_archive_member_agents_unlocked",
                        lambda *_args, **_kwargs: pytest.fail("Changed archive entered cascade"))
    with pytest.raises(TeamStateConflictError):
        team_service.archive_team(team["teamId"], expected_fingerprint=fingerprint)
    assert directory.get_agent(agent["agentId"])["status"] == "active"


def test_archive_admission_cas_holds_lock_until_roster_lease_is_reserved(archive_env, monkeypatch):
    team, _agent = archive_env
    fingerprint = team_record_fingerprint(_record(team["teamId"]))
    observed_lock = []
    def check_settled(_service, _team_id):
        result = []
        def probe():
            acquired = team_service._TEAM_LOCK.acquire(blocking=False)
            result.append(acquired)
            if acquired:
                team_service._TEAM_LOCK.release()
        thread = threading.Thread(target=probe)
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive()
        observed_lock.extend(result)
    monkeypatch.setattr(team_admission, "_require_settled_workflows", check_settled)
    with team_admission.archive_admission(team["teamId"], expected_fingerprint=fingerprint):
        with team_service._TEAM_LOCK:
            with pytest.raises(team_service.TeamLockedError):
                team_admission.assert_roster_mutation_allowed(team["teamId"])
    assert observed_lock == [False]


@pytest.mark.parametrize("with_cas", [True, False])
def test_native_archive_keeps_old_callers_and_releases_global_lock_during_cascade(archive_env, monkeypatch, with_cas):
    team, agent = archive_env
    original_cascade = team_service._cascade_archive_member_agents_unlocked
    lock_free = []
    def cascade(*args, **kwargs):
        def probe():
            acquired = team_service._TEAM_LOCK.acquire(blocking=False)
            lock_free.append(acquired)
            if acquired:
                team_service._TEAM_LOCK.release()
        thread = threading.Thread(target=probe)
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive()
        return original_cascade(*args, **kwargs)
    monkeypatch.setattr(team_service, "_cascade_archive_member_agents_unlocked", cascade)
    kwargs = {"expected_fingerprint": team_record_fingerprint(_record(team["teamId"]))} if with_cas else {}
    result = team_service.archive_team(team["teamId"], **kwargs)
    assert result["status"] == "archived"
    assert directory.get_agent(agent["agentId"], include_archived=True)["status"] == "archived"
    assert lock_free and all(lock_free)
