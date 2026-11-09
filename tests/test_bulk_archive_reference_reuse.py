"""Guard the reference-reuse fast paths used by bulk Agent archive.

Bulk archive used to re-read the whole Agent directory (and the whole chat
state) several times per archived Agent. These tests pin the reuse contracts so
the extra full scans cannot quietly come back.
"""

from __future__ import annotations

from core.ui import chat_state as chat_state_module
from core.web.services import (
    agent_bulk_delete_service,
    agent_directory_service,
    agent_mode_binding_service,
    chat_room_service,
    session_service,
    team_service,
)
from core.web.services.agent_directory import ops_residual as ops_residual_module


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_bulk_delete_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)


def test_remove_agents_from_mode_bindings_accepts_precomputed_agent_options(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    first = session_service.create_chat_session(title="Mode Reuse One")
    second = session_service.create_chat_session(title="Mode Reuse Two")
    agent_mode_binding_service.update_mode_binding(
        "chat",
        available_agent_ids=[first["agentId"], second["agentId"]],
    )

    # Capture the projection once, then forbid any implicit re-read.
    payload = agent_mode_binding_service.get_mode_bindings_payload()
    agent_options = list(payload["agents"])

    def fail_scan(*args, **kwargs):
        raise AssertionError("remove_agents_from_mode_bindings re-read the Agent directory")

    monkeypatch.setattr(agent_mode_binding_service, "_agent_options", fail_scan)

    result = agent_mode_binding_service.remove_agents_from_mode_bindings(
        [first["agentId"]],
        agent_snapshots_by_agent_id={
            first["agentId"]: agent_directory_service.get_agent(
                first["agentId"], include_archived=True
            )
        },
        agent_options=agent_options,
    )

    assert result["removedAgentIds"] == [first["agentId"]]
    available = result["modes"]["chat"]["availableAgentIds"]
    assert first["agentId"] not in available
    assert second["agentId"] in available


def test_remove_agents_from_teams_resolves_one_agent_reference_snapshot(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    sessions = [session_service.create_chat_session(title=f"Team Reuse {index}") for index in range(4)]
    team = team_service.create_team(
        name="Team Reuse",
        members=[
            {"agentId": session["agentId"], "role": "lead" if index == 0 else "reviewer"}
            for index, session in enumerate(sessions)
        ],
    )

    map_reads: list[int] = []
    real_maps = team_service._agent_reference_maps

    def counting_maps():
        map_reads.append(1)
        return real_maps()

    link_kwargs: list[dict] = []
    real_link = team_service._ensure_team_chat_room_link

    def recording_link(team_payload, **kwargs):
        link_kwargs.append(kwargs)
        return real_link(team_payload, **kwargs)

    monkeypatch.setattr(team_service, "_agent_reference_maps", counting_maps)
    monkeypatch.setattr(team_service, "_ensure_team_chat_room_link", recording_link)

    result = team_service.remove_agents_from_teams(
        [sessions[0]["agentId"]], include_restore_token=True
    )

    assert result["removedByAgentId"][sessions[0]["agentId"]] == [team["teamId"]]
    # One snapshot per call, handed to the link sync: without it that sync does a
    # get_agent projection for every team member, for every team.
    assert len(map_reads) == 1
    assert link_kwargs and isinstance(link_kwargs[0].get("agent_refs"), dict)
    member_ids = [member["agentId"] for member in team_service.get_team(team["teamId"])["members"]]
    assert sessions[0]["agentId"] not in member_ids
    assert sessions[1]["agentId"] in member_ids


def test_list_team_chat_room_refs_returns_only_that_teams_rooms(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    first = session_service.create_chat_session(title="Room Ref One")
    second = session_service.create_chat_session(title="Room Ref Two")
    team = team_service.create_team(
        name="Room Ref Team",
        members=[
            {"agentId": first["agentId"], "role": "lead"},
            {"agentId": second["agentId"], "role": "reviewer"},
        ],
    )
    linked_room_id = str(team.get("linkedChatRoomId") or "").strip()
    assert linked_room_id

    refs = chat_room_service.list_team_chat_room_refs(team["teamId"])

    assert [ref["roomId"] for ref in refs] == [linked_room_id]
    assert set(refs[0]) == {"roomId", "status"}
    assert chat_room_service.list_team_chat_room_refs("team-does-not-exist") == []


def test_active_chat_session_memo_reloads_only_after_a_chat_state_write(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session_service.create_chat_session(title="Active Session Memo")

    loads: list[int] = []
    real_load = agent_directory_service.load_chat_state

    def counting_load(*args, **kwargs):
        loads.append(1)
        return real_load(*args, **kwargs)

    monkeypatch.setattr(agent_directory_service, "load_chat_state", counting_load)
    ops_residual_module._ACTIVE_CHAT_SESSION_CACHE.clear()

    first_read = agent_directory_service._active_chat_session_id()
    second_read = agent_directory_service._active_chat_session_id()

    assert first_read == second_read
    assert len(loads) == 1, "the active session id must be memoized inside one epoch"

    # Every chat-state write bumps the epoch; the memo must follow it.
    chat_state_module._bump_chat_state_write_epoch()
    agent_directory_service._active_chat_session_id()

    assert len(loads) == 2, "a chat-state write must invalidate the memo"
