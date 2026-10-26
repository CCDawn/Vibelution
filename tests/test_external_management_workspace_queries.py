"""Directory discovery remains bounded, existing-only and independent of hydration."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from core.web.services.external_management import workspace_queries as queries
from core.web.services.external_management.service import ManagementError


def query(**values):
    return SimpleNamespace(**{"query": "", "offset": 0, "limit": 6, "archived": False, "member_offset": 0, **values})


@pytest.fixture
def env(tmp_path, monkeypatch):
    from core.infrastructure import developer_sandbox
    root = tmp_path / "project"
    root.mkdir()
    workspace = tmp_path / "target-data" / "workspace"
    workspace.mkdir(parents=True)
    config = tmp_path / "config.toml"
    config.write_text("[launcher.developer_mode]\nenabled = false\n", encoding="utf-8")
    directory = SimpleNamespace(CONFIG_PATH=config)
    def formal(project, *parts):
        assert project == root
        return workspace.joinpath(*parts)
    monkeypatch.setattr(developer_sandbox, "formal_workspace_path", formal)
    monkeypatch.setattr(queries, "formal_workspace_path", formal)
    def forbidden(*_args, **_kwargs):
        pytest.fail("query invoked a native writer, initializer or hydration")
    monkeypatch.setattr(developer_sandbox, "seeded_sandbox_workspace_path", forbidden)
    monkeypatch.setattr(developer_sandbox, "sandboxed_workspace_path", forbidden)
    team = {"teamId": "team-a", "name": "Ordinary team", "status": "active", "purpose": "Coordinate",
            "teamKind": "custom", "teamSource": "manual", "linkedChatRoomId": "room-a",
            "members": [{"agentId": "agent-a", "purpose": "SECRET member configuration"}]}
    room = {"roomId": "room-a", "title": "Ordinary room", "status": "ready", "purpose": "discussion",
            "config": {"source": "team", "teamId": "team-a", "teamKind": "custom", "teamSource": "manual"},
            "participants": [{"sessionId": "SECRET session"}], "rounds": [{"messages": ["SECRET body"]}]}
    teams_path, rooms_path = workspace / "teams/teams.json", workspace / "chat_rooms/chat_rooms.json"
    def write(teams=None, rooms=None):
        for path, payload in ((teams_path, {"teams": [team] if teams is None else teams}),
                              (rooms_path, {"rooms": [room] if rooms is None else rooms})):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
    write()
    return SimpleNamespace(root=root, directory=directory, workspace=workspace, config=config,
                           team=team, room=room, teams_path=teams_path, rooms_path=rooms_path, write=write)


def snapshot(env):
    return {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in env.root.parent.rglob("*") if path.is_file()}


@pytest.mark.parametrize("kind", [None, ""])
@pytest.mark.parametrize("source", [None, ""])
@pytest.mark.parametrize("legacy", ["research", "research_organization"])
def test_legacy_only_research_classification_filters_nonreserved_team_and_room(env, kind, source, legacy):
    env.team["teamId"] = "legacy-research-team"
    env.team["systemTeamKind"] = legacy
    for key, value in (("teamKind", kind), ("teamSource", source)):
        if value is None:
            env.team.pop(key)
        else:
            env.team[key] = value
    env.room["config"] = {"source": "team", "teamId": "legacy-research-team", "teamKind": kind if kind is not None else "research"}
    env.write()
    before = snapshot(env)
    assert queries.read_teams(env.root, env.directory, query())["teams"] == []
    assert queries.read_rooms(env.root, env.directory, query())["rooms"] == []
    with pytest.raises(ManagementError):
        queries.read_team(env.root, env.directory, "legacy-research-team", query())
    assert snapshot(env) == before


def test_all_queries_project_only_directory_fields_without_writes_or_hydration(env, monkeypatch):
    from core.web.services import chat_room_service, team_service
    def forbidden(*_args, **_kwargs):
        pytest.fail("legacy read/repair owner invoked")
    for owner, names in ((team_service, ("get_team", "list_teams", "list_team_compact_references")),
                         (chat_room_service, ("read_chat_rooms_snapshot", "get_chat_room_detail", "list_chat_rooms"))):
        for name in names:
            if hasattr(owner, name):
                monkeypatch.setattr(owner, name, forbidden)
    before = snapshot(env)
    teams = queries.read_teams(env.root, env.directory, query())
    team = queries.read_team(env.root, env.directory, "team-a", query())
    rooms = queries.read_rooms(env.root, env.directory, query())
    room = queries.read_room(env.root, env.directory, "room-a")
    assert teams == {"teams": [{"id": "team-a", "name": "Ordinary team", "status": "active", "purpose": "Coordinate", "memberCount": 1}],
                     "total": 1, "offset": 0, "nextOffset": None, "untrustedContent": True}
    assert team["team"] == {"id": "team-a", "name": "Ordinary team", "status": "active", "purpose": "Coordinate",
                            "members": [{"agentId": "agent-a"}], "memberTotal": 1, "memberOffset": 0, "nextMemberOffset": None}
    assert rooms == {"rooms": [{"id": "room-a", "title": "Ordinary room", "status": "ready"}],
                     "total": 1, "offset": 0, "nextOffset": None, "untrustedContent": True}
    assert room == {"room": rooms["rooms"][0], "untrustedContent": True}
    assert "SECRET" not in json.dumps([teams, team, rooms, room])
    assert snapshot(env) == before


def test_stable_sort_search_pages_archived_and_member_pagination(env):
    teams, rooms = [], []
    for number in reversed(range(8)):
        tid, rid = f"team-{number}", f"room-{number}"
        team = {**env.team, "teamId": tid, "name": f"Case {number}", "linkedChatRoomId": rid,
                "members": [{"agentId": f"agent-{i}"} for i in range(9)]}
        room = {**env.room, "roomId": rid, "title": f"Case {number}", "config": {"source": "team", "teamId": tid}}
        if number == 7:
            team["status"] = "archived"
        teams.append(team)
        rooms.append(room)
    env.write(teams, rooms)
    first = queries.read_teams(env.root, env.directory, query())
    assert first["total"] == 7 and first["nextOffset"] == 6 and len(first["teams"]) == 6
    assert [item["id"] for item in first["teams"]] == [f"team-{i}" for i in range(6)]
    second = queries.read_teams(env.root, env.directory, SimpleNamespace(query="", offset=6, limit=6, archived=True))
    assert [item["id"] for item in second["teams"]] == ["team-6", "team-7"] and second["nextOffset"] is None
    selected = queries.read_teams(env.root, env.directory, SimpleNamespace(query="cAsE 3", offset=0, limit=1, archived=False))
    assert selected["total"] == 1 and selected["teams"][0]["id"] == "team-3"
    assert queries.read_rooms(env.root, env.directory, query())["total"] == 7
    assert queries.read_rooms(env.root, env.directory, SimpleNamespace(query="", offset=7, limit=6, archived=True))["total"] == 8
    detail = queries.read_team(env.root, env.directory, "team-3", SimpleNamespace(member_offset=6, limit=2))["team"]
    assert detail["members"] == [{"agentId": "agent-6"}, {"agentId": "agent-7"}]
    assert (detail["memberOffset"], detail["memberTotal"], detail["nextMemberOffset"]) == (6, 9, 8)


@pytest.mark.parametrize("patch", [
    {"teamId": "research-team", "teamKind": "research", "teamSource": "research_organization"},
    {"internal": True}, {"metadata": {"virtualHumanCompanion": "owner"}}, {"systemManaged": True},
])
def test_known_private_team_and_linked_room_are_filtered_and_direct_reads_denied(env, patch):
    env.team.update(patch)
    env.room["config"] = {"source": "team", "teamId": env.team["teamId"]}
    env.write()
    assert queries.read_teams(env.root, env.directory, query())["teams"] == []
    assert queries.read_rooms(env.root, env.directory, query())["rooms"] == []
    with pytest.raises(ManagementError, match="TEAM_UNAVAILABLE"):
        queries.read_team(env.root, env.directory, env.team["teamId"], query())
    with pytest.raises(ManagementError, match="ROOM_UNAVAILABLE"):
        queries.read_room(env.root, env.directory, "room-a")


@pytest.mark.parametrize("source,extra", [
    ("hypothesis_first_candidate_generation.v1", {"questionId": "question-1"}),
    ("hypothesis_first_candidate_review.v1", {"scopeAuthority": "preformal_candidate_review_scope.v1", "candidateId": "candidate-1"}),
    ("challenge_workflow", {"scopeAuthority": "workflow_discussion_scope.v1", "scopeHash": "a" * 64}),
    ("", {"scopeAuthority": "workflow_discussion_scope.v1", "operatorDiscussionAuthority": {"workflowRunId": "SECRET run"}}),
])
def test_existing_system_workflow_rooms_do_not_block_ordinary_directory(env, source, extra):
    system = {**env.team, "teamId": "research-team", "teamKind": "research", "teamSource": "research_organization",
              "linkedChatRoomId": "room-system-linked"}
    scoped = {**env.room, "roomId": "room-system-scoped", "purpose": "meeting",
              "config": {"teamId": "research-team", **extra, **({"source": source} if source else {})}}
    env.write([env.team, system], [env.room, scoped])
    assert queries.read_rooms(env.root, env.directory, query())["rooms"] == [
        {"id": "room-a", "title": "Ordinary room", "status": "ready"}]
    with pytest.raises(ManagementError, match="ROOM_UNAVAILABLE"):
        queries.read_room(env.root, env.directory, "room-system-scoped")
    # A known system source must never promote an ordinary Team's room.
    if source:
        scoped["config"]["teamId"] = "team-a"
        env.team["linkedChatRoomId"] = "room-system-scoped"
        env.write([env.team, system], [scoped])
        with pytest.raises(ManagementError, match="ROOM_LIST_UNAVAILABLE"):
            queries.read_rooms(env.root, env.directory, query())


@pytest.mark.parametrize("patch", [
    {"status": "unknown"}, {"room_id": "different"}, {"title": []}, {"config": []},
    {"internal": True, "config": {"teamId": "research-team", "hidden": "false"}},
    {"config": {"teamId": "research-team", "teamKind": []}},
    {"config": {"teamId": "research-team", "source": "unknown-source"}},
    {"team_id": None}, {"teamId": "conflict"},
])
def test_system_team_proof_never_masks_corrupt_room_authority(env, patch):
    system = {**env.team, "teamId": "research-team", "teamKind": "research", "teamSource": "research_organization",
              "linkedChatRoomId": "room-system-linked"}
    scoped = {**env.room, "roomId": "room-system-scoped", "config": {"source": "challenge_workflow", "teamId": "research-team"}, **patch}
    env.write([env.team, system], [env.room, scoped])
    with pytest.raises(ManagementError, match="ROOM_LIST_UNAVAILABLE"):
        queries.read_rooms(env.root, env.directory, query())


@pytest.mark.parametrize("patch", [
    {"teamKind": "unknown"}, {"teamSource": "internal-unrecognized"}, {"teamKind": "research"},
    {"hidden": "false"}, {"metadata": []}, {"status": "unknown"}, {"name": {}}, {"team_id": "other"},
    {"members": [{"agentId": "agent-a"}, {"agentId": "agent-a"}]},
    {"members": [{"agent_id": "agent-a", "agentId": "agent-a"}]},
    {"members": [{"agentId": "agent-a"}] * 121},
    {"source": "internal"}, {"kind": "companion"}, {"archived": True}, {"archived": "false"},
])
def test_corrupt_team_authority_fails_closed_and_preserves_bytes(env, patch):
    env.team.update(patch)
    env.write()
    before = snapshot(env)
    with pytest.raises(ManagementError, match="TEAM_LIST_UNAVAILABLE") as rejected:
        queries.read_teams(env.root, env.directory, query())
    assert rejected.value.status_code == 503
    with pytest.raises(ManagementError, match="ROOM_LIST_UNAVAILABLE"):
        queries.read_rooms(env.root, env.directory, query())
    assert snapshot(env) == before


@pytest.mark.parametrize("kind,source,legacy,valid,private", [
    (None, "manual", "research_organization", False, False),
    ("", "manual", "research_organization", False, False),
    (None, "research_organization", "custom", False, False),
    (None, "research_organization", "manual", False, False),
    ("custom", None, "research_organization", False, False),
    ("research", None, "manual", False, False),
    ("custom", "manual", "research", False, False),
    ("research", "research_organization", "manual", False, False),
    (None, "manual", "custom", True, False),
    (None, "manual", "manual", True, False),
    (None, "research_organization", "research", True, True),
    (None, "research_organization", "research_organization", True, True),
    ("research", None, "research_organization", True, True),
    ("custom", "manual", "custom", True, False),
    (None, "external_team:" + "a" * 40, None, False, False),
    ("custom", "external_team:" + "a" * 40, None, False, False),
    ("template_demo", "external_team:" + "a" * 40, "research", False, False),
    ("template_demo", "external_team:" + "a" * 40, "template_demo", True, False),
    (None, "personal_assistant_action:" + "b" * 40, "template_demo", False, False),
    ("template_demo", "personal_assistant_action:" + "b" * 40, "team_template", True, False),
])
def test_each_present_team_classification_must_agree_even_without_explicit_kind(env, kind, source, legacy, valid, private):
    for key, value in (("teamKind", kind), ("teamSource", source), ("systemTeamKind", legacy)):
        env.team.pop(key, None)
        if value is not None:
            env.team[key] = value
    env.write()
    before = snapshot(env)
    if valid:
        result = queries.read_teams(env.root, env.directory, query())
        assert result["total"] == (0 if private else 1)
    else:
        for call, code in (
            (lambda: queries.read_teams(env.root, env.directory, query()), "TEAM_LIST_UNAVAILABLE"),
            (lambda: queries.read_team(env.root, env.directory, "team-a", query()), "TEAM_UNAVAILABLE"),
            (lambda: queries.read_rooms(env.root, env.directory, query()), "ROOM_LIST_UNAVAILABLE"),
        ):
            with pytest.raises(ManagementError, match=code):
                call()
    assert snapshot(env) == before


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("top,config", [
    ({"teamKind": "research"}, {}),
    ({"teamSource": "research_organization"}, {}),
    ({"teamTemplateId": "other-template"}, {}),
    ({"teamKind": "custom"}, {"teamKind": "research"}),
    ({"teamSource": "manual"}, {"teamSource": "financial"}),
    ({"teamTemplateId": "dev-team"}, {"teamTemplateId": "other-template"}),
    ({"teamKind": ""}, {"teamKind": "custom"}),
])
def test_room_top_config_and_team_classifications_agree_before_private_filter(env, private, top, config):
    env.team["internal"] = private
    env.team["teamTemplateId"] = "dev-team"
    env.room.update(top)
    env.room["config"].update(config)
    env.write()
    with pytest.raises(ManagementError, match="ROOM_LIST_UNAVAILABLE"):
        queries.read_rooms(env.root, env.directory, query())
    with pytest.raises(ManagementError, match="ROOM_UNAVAILABLE"):
        queries.read_room(env.root, env.directory, "room-a")


def test_matching_room_top_config_and_team_classifications_remain_readable(env):
    env.team["teamTemplateId"] = ""
    for record in (env.room, env.room["config"]):
        record.update(teamKind="custom", teamSource="manual", teamTemplateId="")
    env.write()
    assert queries.read_rooms(env.root, env.directory, query())["total"] == 1


def test_list_summary_budget_is_separate_from_detail_and_hidden_suffix_search(env):
    env.team["name"] = "N" * 32 + "NAME_SUFFIX"
    env.team["purpose"] = "P" * 64 + "PURPOSE_SUFFIX"
    env.write()
    listed = queries.read_teams(env.root, env.directory, query())["teams"][0]
    detail = queries.read_team(env.root, env.directory, "team-a", query())["team"]
    assert listed["name"] == "N" * 32 and listed["purpose"] == "P" * 64
    assert detail["name"].endswith("NAME_SUFFIX") and detail["purpose"].endswith("PURPOSE_SUFFIX")
    assert queries.read_teams(env.root, env.directory, query(query="NAME_SUFFIX"))["total"] == 0
    assert queries.read_teams(env.root, env.directory, query(query="PURPOSE_SUFFIX"))["total"] == 0


@pytest.mark.parametrize("patch", [
    {"config": []}, {"status": "unknown"}, {"purpose": "unknown"}, {"title": []},
    {"room_id": "other"}, {"config": {"source": "team", "teamId": "missing"}},
    {"config": {"source": "team", "teamId": "team-a", "teamSource": "other"}},
    {"teamId": "other"}, {"config": {"source": "companion"}},
    {"teamId": False}, {"teamId": None}, {"config": {"teamId": 0}},
    {"source": "internal"}, {"team_id": "other"}, {"archived": "false"},
])
def test_corrupt_room_authority_fails_closed(env, patch):
    env.room.update(patch)
    env.write()
    with pytest.raises(ManagementError, match="ROOM_LIST_UNAVAILABLE"):
        queries.read_rooms(env.root, env.directory, query())
    with pytest.raises(ManagementError, match="ROOM_UNAVAILABLE"):
        queries.read_room(env.root, env.directory, "room-a")


@pytest.mark.parametrize("raw", ["{broken", '{"rooms":[],"rooms":[]}', '{"rooms":{}}', '{"rooms":[null]}', '{}', '[]',
                                '{"rooms":[],"bad":NaN}', '{"rooms":[],"bad":Infinity}'])
def test_missing_or_damaged_room_authority_is_never_authoritative_empty(env, raw):
    env.rooms_path.write_text(raw, encoding="utf-8")
    with pytest.raises(ManagementError, match="ROOM_LIST_UNAVAILABLE"):
        queries.read_rooms(env.root, env.directory, query())
    env.rooms_path.unlink()
    with pytest.raises(ManagementError, match="ROOM_LIST_UNAVAILABLE"):
        queries.read_rooms(env.root, env.directory, query())
    assert not env.rooms_path.exists()


def test_duplicate_identity_or_ambiguous_two_way_links_fail_closed(env):
    env.write([env.team, copy.deepcopy(env.team)])
    with pytest.raises(ManagementError):
        queries.read_teams(env.root, env.directory, query())
    other = {**env.team, "teamId": "team-b"}
    env.write([env.team, other])
    with pytest.raises(ManagementError):
        queries.read_rooms(env.root, env.directory, query())
    env.team["linkedChatRoomId"] = "room-other"
    env.write()
    with pytest.raises(ManagementError):
        queries.read_room(env.root, env.directory, "room-a")


def test_native_safety_projection_truncates_text_and_search_never_uses_body(env):
    env.team["name"] = "A\x00\u202e" + "N" * 1000
    env.team["purpose"] = "P" * 4000
    env.room["title"] = "T" * 1000
    env.write()
    team = queries.read_team(env.root, env.directory, "team-a", query())["team"]
    room = queries.read_room(env.root, env.directory, "room-a")["room"]
    assert len(team["name"]) <= 120 and "\x00" not in team["name"] and "\u202e" not in team["name"]
    assert len(team["purpose"]) <= 240 and len(room["title"]) <= 120
    assert queries.read_rooms(env.root, env.directory, SimpleNamespace(query="SECRET", offset=0, limit=6, archived=False))["total"] == 0


@pytest.mark.parametrize("source", ["team_template", "external_team:" + "a" * 40, "personal_assistant_action:" + "b" * 40])
def test_explicit_native_template_sources_are_readable(env, source):
    env.team.update(teamKind="template_demo", teamSource=source, teamTemplateId="dev-team")
    env.room["config"] = {"source": source, "teamId": "team-a", "teamTemplateId": "dev-team"}
    env.write()
    assert queries.read_teams(env.root, env.directory, query())["total"] == 1
    assert queries.read_rooms(env.root, env.directory, query())["total"] == 1


def test_room_canonical_path_remains_formal_when_team_directory_is_sandboxed(env, monkeypatch):
    from core.web.services.external_management.state_snapshot import ExistingStateSnapshot
    sandbox = env.root.parent / "sandbox/teams.json"
    sandbox.parent.mkdir()
    sandbox.write_text(json.dumps({"teams": [env.team]}), encoding="utf-8")
    def path(_self, *parts):
        assert parts == ("teams", "teams.json")
        return sandbox
    monkeypatch.setattr(ExistingStateSnapshot, "path", path)
    env.teams_path.write_text("corrupt formal Team index", encoding="utf-8")
    assert queries.read_rooms(env.root, env.directory, query())["total"] == 1


def test_ordinary_standalone_room_needs_no_team_members_or_session_authority(env):
    env.room["config"] = {}
    env.room["purpose"] = "chat"
    env.write(teams=[])
    assert queries.read_rooms(env.root, env.directory, query())["rooms"] == [
        {"id": "room-a", "title": "Ordinary room", "status": "ready"}]
    env.room["config"] = {"teamKind": "research"}
    env.write(teams=[])
    with pytest.raises(ManagementError, match="ROOM_LIST_UNAVAILABLE"):
        queries.read_rooms(env.root, env.directory, query())


def test_existing_reader_caps_file_size_and_shared_archive_reader_is_compatible(env):
    from core.web.services.external_management.archive_state import ArchiveState
    from core.web.services.external_management.state_snapshot import ExistingStateSnapshot
    assert issubclass(ArchiveState, ExistingStateSnapshot)
    with env.rooms_path.open("wb") as stream:
        stream.write(b" " * (32 * 1024 * 1024 + 1))
    with pytest.raises(ManagementError, match="ROOM_LIST_UNAVAILABLE"):
        queries.read_rooms(env.root, env.directory, query())


def test_shared_archive_default_keeps_legacy_json_semantics_and_paths(env):
    import math
    from core.web.services.external_management.archive_state import ArchiveState
    from core.web.services.external_management.state_snapshot import ExistingStateSnapshot
    archive = ArchiveState(env.root, env.directory)
    assert archive.path("teams", "teams.json") == env.teams_path
    assert archive.project_root == env.root and archive.directory is env.directory
    env.teams_path.write_text('{"teams":[],"legacy":NaN}', encoding="utf-8")
    assert math.isnan(archive.read_json(env.teams_path)["legacy"])
    with pytest.raises(ValueError, match="Invalid JSON constant"):
        ExistingStateSnapshot.read_json(env.teams_path, strict=True)
    env.teams_path.write_text('{"teams":[],"teams":[]}', encoding="utf-8")
    with pytest.raises(ValueError, match="Ambiguous archive authority"):
        archive.read_json(env.teams_path)


def test_query_outputs_round_trip_through_shared_closed_contracts(env):
    from core.web.services.external_management.contracts import (
        DirectoryQuery, TeamReadQuery, TeamListResponse, TeamReadResponse, RoomListResponse, RoomReadResponse,
    )
    page = DirectoryQuery.model_validate({})
    detail = TeamReadQuery.model_validate({"team_id": "team-a"})
    for model, response in (
        (TeamListResponse, queries.read_teams(env.root, env.directory, page)),
        (RoomListResponse, queries.read_rooms(env.root, env.directory, page)),
        (TeamReadResponse, queries.read_team(env.root, env.directory, detail.team_id, detail)),
        (RoomReadResponse, queries.read_room(env.root, env.directory, "room-a")),
    ):
        assert model.model_validate(response).model_dump() == response
    empty_page = DirectoryQuery.model_validate({"offset": 100_000})
    TeamListResponse.model_validate(queries.read_teams(env.root, env.directory, empty_page))
    RoomListResponse.model_validate(queries.read_rooms(env.root, env.directory, empty_page))
    last_members = TeamReadQuery.model_validate({"team_id": "team-a", "member_offset": 120})
    TeamReadResponse.model_validate(queries.read_team(env.root, env.directory, last_members.team_id, last_members))
