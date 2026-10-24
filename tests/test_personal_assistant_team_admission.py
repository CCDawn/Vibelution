"""Native Team admission races with real workflow commits in isolated storage."""
from __future__ import annotations

import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.web.services import team_service
from core.web.services.team import team_admission, team_crud, team_store
from core.web.services.team_workflow.generic import runtime, service, store


@pytest.fixture
def env(tmp_path, monkeypatch):
    state = {"teams": [
        {"teamId": "team-a", "name": "A", "status": "active", "teamKind": "custom", "members": [{"agentId": "agent-a"}]},
        {"teamId": "team-b", "name": "B", "status": "active", "teamKind": "custom", "members": []},
    ]}
    lock = threading.RLock()
    monkeypatch.setattr(team_service, "_TEAM_LOCK", lock)
    monkeypatch.setattr(team_service, "_teams_root", lambda: tmp_path / "teams")
    monkeypatch.setattr(team_store, "_teams_root", lambda: tmp_path / "teams")

    def load():
        return copy.deepcopy(state)

    def save(payload):
        state.clear()
        state.update(copy.deepcopy(payload))

    def team(team_id):
        return copy.deepcopy(next(item for item in state["teams"] if item["teamId"] == team_id))

    monkeypatch.setattr(team_service, "_load_index", load)
    monkeypatch.setattr(team_store, "_load_index", load)
    monkeypatch.setattr(team_service, "_save_index", save)
    monkeypatch.setattr(team_service, "get_team", team)
    monkeypatch.setattr(team_service, "_agent_reference", lambda agent_id, **kwargs: {"agentId": agent_id, "status": "active"})
    monkeypatch.setattr(team_service, "_normalize_members", lambda members, **kwargs: copy.deepcopy(members))
    monkeypatch.setattr(team_service, "_ensure_members_can_join_team", lambda *args, **kwargs: None)
    monkeypatch.setattr(team_service, "_ensure_active_member_direct_sessions", lambda *args: None)
    monkeypatch.setattr(team_service, "_ensure_team_chat_room_link", lambda *args, **kwargs: None)
    monkeypatch.setattr(team_service, "_sync_team_canvas_membership", lambda *args: None)
    monkeypatch.setattr(team_service, "_ensure_team_member_agents_can_archive", lambda *args: None)
    monkeypatch.setattr(team_service, "_delete_team_linked_chat_rooms", lambda *args, **kwargs: [])
    monkeypatch.setattr(team_service, "_record_team_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(team_service, "_relative_path", str)
    cascade = Mock(return_value={"archivedAgentIds": ["agent-a"], "removedFromRoomIds": []})
    monkeypatch.setattr(team_service, "_cascade_archive_member_agents_unlocked", cascade)
    monkeypatch.setattr(runtime, "ensure_admission", lambda: None)
    monkeypatch.setattr(service, "_wake", lambda: None)
    flow = {"id": "flow-a", "name": "Flow", "fields": [],
            "steps": [{"id": "out", "label": "Output", "kind": "output", "owner": "", "instruction": ""}]}
    service.save_flow("team-a", "flow-a", {"flow": flow, "expectedRevision": 0})
    return SimpleNamespace(state=state, team=team, load=load, save=save, cascade=cascade,
                           flow=flow, tmp_path=tmp_path, lock=lock)


def start(key="request-a"):
    return service.start_run("team-a", "flow-a", {"values": {}, "expectedRevision": 1, "idempotencyKey": key})


def wait_for_barrier(event, future):
    if not event.wait(5):
        future.result(timeout=1)  # Surface a native failure before the barrier.
        pytest.fail("Native operation completed without reaching the barrier.")


def test_archive_lease_blocks_concurrent_pa_membership_without_holding_global_lock(env):
    entered, release = threading.Event(), threading.Event()

    def cascade(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return {"archivedAgentIds": ["agent-a"]}

    env.cascade.side_effect = cascade
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(team_crud.archive_team, "team-a", protected_agent_ids=("assistant",))
        try:
            wait_for_barrier(entered, future)
            with pytest.raises(team_service.TeamLockedError):
                team_crud.update_team("team-a", members=[{"agentId": "agent-a"}, {"agentId": "assistant"}])
            assert env.team("team-a")["members"] == [{"agentId": "agent-a"}]
            # This completes before A's cascade releases: no global lock is held.
            assert team_crud.update_team("team-b", members=[{"agentId": "other"}])["members"] == [{"agentId": "other"}]
        finally:
            release.set()
        assert future.result(timeout=5)["status"] == "archived"
    assert env.cascade.call_args.args == (["agent-a"],)


def test_canonical_protected_member_is_rejected_at_native_reservation(env):
    env.state["teams"][0]["members"].append({"agentId": "assistant"})
    with pytest.raises(team_service.TeamLockedError, match="Protected"):
        team_crud.archive_team("team-a", protected_agent_ids=("assistant",))
    env.cascade.assert_not_called()
    assert env.team("team-a")["status"] == "active"


def test_workflow_commit_wins_then_archive_rejects_without_waiting_for_run_lock(env, monkeypatch):
    committed, release = threading.Event(), threading.Event()
    original = service._commit_new_run

    def commit(*args):
        original(*args)
        committed.set()
        assert release.wait(5)  # The caller still owns the flow/run file locks.

    monkeypatch.setattr(service, "_commit_new_run", commit)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(start)
        try:
            wait_for_barrier(committed, future)
            with pytest.raises(team_service.TeamLockedError, match="completed or stopped"):
                team_crud.archive_team("team-a", protected_agent_ids=("assistant",))
            env.cascade.assert_not_called()
        finally:
            release.set()
        assert future.result(timeout=5)["status"] == "running"


def test_archive_reservation_wins_then_native_start_cannot_write_run(env):
    entered, release = threading.Event(), threading.Event()

    def cascade(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return {"archivedAgentIds": ["agent-a"]}

    env.cascade.side_effect = cascade
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(team_crud.archive_team, "team-a", protected_agent_ids=("assistant",))
        try:
            wait_for_barrier(entered, future)
            with pytest.raises(store.Conflict, match="admission"):
                start()
            assert store.records("team-a", "runs") == []
        finally:
            release.set()
        assert future.result(timeout=5)["status"] == "archived"
    with pytest.raises(store.WorkflowError):
        start("after-archive")


@pytest.mark.parametrize("record", [
    {"status": "running"}, {"status": "waiting"}, {"status": "failed"},
    {"status": "completed", "recovery": {"status": "repairing"}},
    {"status": "stopped", "recovery": {"status": "awaiting_deployment"}},
])
def test_failed_or_unresolved_workflows_cannot_be_archived(env, record):
    store.write(store.path("team-a", "runs", "old-run"), record)
    with pytest.raises(team_service.TeamLockedError):
        team_crud.archive_team("team-a")
    env.cascade.assert_not_called()
    assert env.team("team-a")["status"] == "active"


def test_native_failure_releases_lease_for_future_membership_and_run_admission(env):
    env.cascade.side_effect = RuntimeError("fixture cascade failure")
    with pytest.raises(RuntimeError, match="fixture cascade"):
        team_crud.archive_team("team-a")
    assert team_crud.update_team("team-a", members=[{"agentId": "agent-a"}])["status"] == "active"
    assert start()["status"] == "running"


def test_current_archive_compensation_can_only_restore_its_frozen_member_set(env):
    frozen = env.team("team-a")

    def cascade(*args, **kwargs):
        state = env.load()
        state["teams"][0]["members"] = []
        env.save(state)
        assert team_crud.restore_removed_agents_to_teams({"teams": [frozen]}) == {"restoredTeamIds": ["team-a"]}
        unsafe = {**frozen, "members": [*frozen["members"], {"agentId": "assistant"}]}
        with pytest.raises(team_service.TeamLockedError, match="restore"):
            team_crud.restore_removed_agents_to_teams({"teams": [unsafe]})
        return {"archivedAgentIds": ["agent-a"]}

    env.cascade.side_effect = cascade
    result = team_crud.archive_team("team-a", protected_agent_ids=("assistant",))
    assert result["status"] == "archived" and result["members"] == frozen["members"]


def test_other_transaction_restore_is_rejected_before_any_snapshot_is_written(env):
    entered, release = threading.Event(), threading.Event()

    def cascade(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return {"archivedAgentIds": ["agent-a"]}

    env.cascade.side_effect = cascade
    before = env.load()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(team_crud.archive_team, "team-a")
        try:
            wait_for_barrier(entered, future)
            snapshots = [env.team("team-b"), env.team("team-a")]
            snapshots[0]["name"] = "Do not partially restore this"
            with pytest.raises(team_service.TeamLockedError, match="restore"):
                team_crud.restore_removed_agents_to_teams({"teams": snapshots})
            assert env.load() == before
        finally:
            release.set()
        future.result(timeout=5)


def test_empty_team_and_settled_workflows_can_be_archived(env):
    env.state["teams"][0]["members"] = []
    store.write(store.path("team-a", "runs", "old-run"), {"status": "completed", "recovery": {"status": "resolved"}})
    assert team_crud.archive_team("team-a", protected_agent_ids=("assistant",))["status"] == "archived"
    env.cascade.assert_not_called()


def test_repair_child_creation_uses_same_native_commit_admission(env):
    flow = {**env.flow, "fields": [{"id": "incident", "label": "Incident", "kind": "text", "required": True}]}
    with team_admission.archive_admission("team-a"):
        with pytest.raises(store.Conflict, match="admission"):
            service.create_repair_run("team-a", run_id="repair-child", flow=flow, incident="Fixture", parent={"runId": "parent", "issueId": "issue"})
    assert store.records("team-a", "runs") == []
