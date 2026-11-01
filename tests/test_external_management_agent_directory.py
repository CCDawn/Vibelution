"""All registered identities remain queryable without hydration or side effects."""
from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from core.web.services.external_agent.policy import external_mcp_eligibility
from core.web.services.external_management import agent_directory as readers
from core.web.services.external_management.contracts import (
    AgentDirectoryQuery,
    AgentDirectoryResponse,
)
from core.web.services.external_management.service import ManagementError


def agent(aid, **values):
    return {"agentId": aid, "agentCode": "AG-" + aid.upper(), "displayName": aid,
            "status": "active", "kind": "persistent", "primaryMode": "chat", "roleKey": "assistant_worker",
            "directSessionId": "session-" + aid, "metadata": {"conversationIndexKind": "personal_agent"},
            "prompt": "SECRET prompt", "workspacePath": "SECRET path", **values}


@pytest.fixture
def env(tmp_path, monkeypatch):
    from core.infrastructure import developer_sandbox
    from core.web.services import agent_directory_service as native
    root, workspace, config = tmp_path / "project", tmp_path / "data/workspace", tmp_path / "config.toml"
    root.mkdir()
    workspace.mkdir(parents=True)
    gateway = "[external_agent_gateway]\nenabled = true\nallowed_agent_ids = []\ndenied_agent_ids = []\n"
    config.write_text("[launcher.developer_mode]\nenabled = false\n" + gateway, encoding="utf-8")
    directory = SimpleNamespace(CONFIG_PATH=config, **{name: getattr(native, name) for name in
        ("agent_conversation_index_classification", "_normalize_primary_mode", "_infer_agent_primary_mode",
         "_normalize_agent_code", "_fallback_agent_code", "_normalize_role_key", "_infer_agent_role_key")})
    monkeypatch.setattr(developer_sandbox, "formal_workspace_path", lambda project, *parts: workspace.joinpath(*parts))
    def forbidden(*_args, **_kwargs):
        pytest.fail("Directory read invoked a native initializer, hydrator or writer")
    for name in ("get_agent", "list_agents", "ensure_agent", "_load_state", "_save_state", "_agent_to_api_summary"):
        if hasattr(native, name):
            monkeypatch.setattr(native, name, forbidden)
    monkeypatch.setattr(developer_sandbox, "seeded_sandbox_workspace_path", forbidden)
    monkeypatch.setattr(developer_sandbox, "sandboxed_workspace_path", forbidden)
    agents = [agent("ordinary"), agent("archived", status="archived"),
        agent("team", metadata={"conversationIndexKind": "team_agent", "teamId": "team-a"}),
        agent("rostered"), agent("system", primaryMode="self_evolution", metadata={"conversationIndexKind": "hidden", "protected": True}),
        agent("companion", metadata={"conversationIndexKind": "hidden", "virtualHumanCompanion": True}),
        agent("hidden", metadata={"conversationIndexKind": "hidden", "hidden": True}),
        agent("invalid", metadata={"conversationIndexKind": "bogus"}), agent("missing", metadata={}),
        agent("personal-archived", status="archived")]
    teams = [{"teamId": "team-a", "name": "System team", "status": "active", "teamKind": "research",
              "systemManaged": True, "members": [{"agentId": "team"}, {"agentId": "rostered"}], "prompt": "SECRET team prompt"},
             {"teamId": "old-team", "name": "Archived team", "status": "archived", "members": [{"agentId": "archived"}]}]
    agents_path, teams_path = workspace / "agents/agents.json", workspace / "teams/teams.json"
    def write():
        for path, field, rows in ((agents_path, "agents", agents), (teams_path, "teams", teams)):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({field: rows}, ensure_ascii=False), encoding="utf-8")
    write()
    return SimpleNamespace(root=root, workspace=workspace, directory=directory, config=config, gateway=gateway,
        agents=agents, teams=teams, agents_path=agents_path, teams_path=teams_path, write=write)


def read(env, **parameters):
    return readers.read_agents(env.root, env.directory, AgentDirectoryQuery(**parameters))


def inventory(env):
    return {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in env.root.parent.rglob("*") if path.is_file()}


def all_pages(env, **parameters):
    first = read(env, **parameters)
    items, page = list(first["agents"]), first
    while page["nextOffset"] is not None:
        page = read(env, **parameters, offset=page["nextOffset"], expected_revision=first["revision"])
        items.extend(page["agents"])
        assert page["revision"] == first["revision"]
    return first, items


def test_complete_directory_includes_all_lifecycle_and_ownership_classes(env):
    before = inventory(env)
    first, items = all_pages(env)
    by_id = {item["agentId"]: item for item in items}
    assert len(items) == first["total"] == first["registryTotal"] == len(env.agents)
    assert set(by_id) == {row["agentId"] for row in env.agents}
    assert first["counts"] == {"active": 8, "archived": 2, "dispatchable": 1}
    assert by_id["ordinary"]["ownership"]["kind"] == "personal"
    assert by_id["personal-archived"]["ownership"]["kind"] == "personal"
    assert by_id["team"]["ownership"]["kind"] == "team"
    assert by_id["team"]["ownership"]["teams"] == [{"teamId": "team-a", "name": "System team", "status": "active"}]
    assert by_id["archived"]["ownership"]["teams"][0]["status"] == "archived"
    assert by_id["system"]["ownership"] == {"kind": "system", "mode": "self_evolution", "teams": [],
        "recordedTeams": [], "createdBy": "", "templateId": "", "ownerAgentId": "", "ownerAgentName": ""}
    assert by_id["companion"]["ownership"]["kind"] == "companion"
    assert by_id["invalid"]["ownership"]["kind"] == "unknown"
    assert by_id["hidden"]["dispatchReason"] == "unsupported_agent_class"
    assert by_id["rostered"]["dispatchReason"] == "active_team_member"
    assert by_id["team"]["dispatchReason"] == "team_dedicated_agent"
    assert "SECRET" not in json.dumps(items)
    assert all(set(item) == {"agentId", "agentCode", "displayName", "status", "ownership", "dispatchable", "dispatchReason"} for item in items)
    assert inventory(env) == before


def test_dispatch_matches_native_summary_classification_and_operator_policy(env):
    env.config.write_text("[launcher.developer_mode]\nenabled = false\n[external_agent_gateway]\nenabled = true\n"
        'allowed_agent_ids = ["ordinary", "hidden", "invalid"]\ndenied_agent_ids = ["ordinary"]\n', encoding="utf-8")
    _, items = all_pages(env)
    active = {member["agentId"] for team in env.teams if team["status"] == "active" for member in team["members"]}
    for raw, item in ((row, next(item for item in items if item["agentId"] == row["agentId"])) for row in env.agents):
        projected = {**raw, "conversationIndexKind": env.directory.agent_conversation_index_classification(raw)["kind"]}
        expected = external_mcp_eligibility(projected, active_team_lookup=lambda aid: {"teamId": "team-a"} if aid in active else None,
            operator_enabled=lambda aid: aid in {"hidden", "invalid"},
            operator_explicitly_enabled=lambda aid: aid in {"hidden", "invalid"})
        assert (item["dispatchable"], item["dispatchReason"]) == (expected.eligible, expected.reason)
    assert next(item for item in items if item["agentId"] == "hidden")["dispatchable"] is True
    assert next(item for item in items if item["agentId"] == "invalid")["dispatchable"] is False


def test_legacy_challenge_cup_references_do_not_become_current_team_members(env):
    env.agents[:] = [agent(f"legacy-{i}", metadata={"challengeCupTeamId": "team-a", "bindingStatus": "legacy",
        "activeBinding": False, "prompt": "SECRET legacy prompt"}) for i in range(4)]
    env.write()
    before = inventory(env)
    page, items = all_pages(env)
    assert page["registryTotal"] == 4 and len(items) == 4
    for item in items:
        assert item["ownership"]["teams"] == []
        assert item["ownership"]["recordedTeams"] == [{"teamId": "team-a", "name": "System team", "status": "active"}]
        assert item["ownership"]["kind"] == "unknown"
        assert (item["dispatchable"], item["dispatchReason"]) == (False, "team_dedicated_agent")
    assert read(env, query="System team")["total"] == 4
    assert "SECRET" not in json.dumps(items) and inventory(env) == before


def test_recorded_team_references_are_canonical_sorted_deduplicated_and_separate(env):
    row = next(row for row in env.agents if row["agentId"] == "team")
    row.update({"teamId": "missing-z", "challengeCupTeamId": "old-team", "knowledgeExpansionTeamId": "old-team"})
    row["metadata"]["knowledgeExpansionTeamId"] = "missing-z"
    env.write()
    _, items = all_pages(env)
    item = next(item for item in items if item["agentId"] == "team")
    assert item["ownership"]["teams"] == [{"teamId": "team-a", "name": "System team", "status": "active"}]
    assert item["ownership"]["recordedTeams"] == [
        {"teamId": "missing-z", "name": "", "status": "unavailable"},
        {"teamId": "old-team", "name": "Archived team", "status": "archived"}]


def test_archived_template_and_user_sources_survive_missing_index_without_invented_teams(env):
    templates = [agent(f"template-{i:02}", status="archived", createdBy="team_template" if i % 2 else "",
        metadata={"teamTemplateId": "dev-team", "creationSpec": {"source": "team_template", "prompt": "SECRET"}})
        for i in range(16)]
    users = [agent(f"user-{i}", status="archived", createdBy="user", metadata={}) for i in range(3)]
    env.agents[:] = templates + users
    env.teams[:] = []
    env.write()
    before = inventory(env)
    page, items = all_pages(env)
    assert page["counts"] == {"active": 0, "archived": 19, "dispatchable": 0}
    for item in items:
        owner = item["ownership"]
        assert owner["teams"] == owner["recordedTeams"] == []
        assert owner["ownerAgentId"] == owner["ownerAgentName"] == ""
        if item["agentId"].startswith("template-"):
            assert (owner["kind"], owner["createdBy"], owner["templateId"]) == ("unknown", "team_template", "dev-team")
        else:
            assert (owner["kind"], owner["createdBy"], owner["templateId"]) == ("personal", "user", "")
    assert read(env, query="dev-team")["total"] == 16
    assert read(env, query="team_template")["total"] == 16
    assert "SECRET" not in json.dumps(items) and inventory(env) == before


def test_explicit_companion_owners_resolve_only_registered_names_and_keep_dangling_ids(env):
    env.agents[:] = [agent("owner", displayName="Use agent"),
        agent("steward", metadata={"conversationIndexKind": "hidden", "lifeStewardForAgentId": "owner"}),
        agent("wake", metadata={"conversationIndexKind": "hidden", "selfWakeForAgentId": "owner"}),
        agent("dangling", metadata={"conversationIndexKind": "hidden", "lifeStewardForAgentId": "absent-owner"})]
    env.teams[:] = []
    env.write()
    before = inventory(env)
    _, items = all_pages(env)
    by_id = {item["agentId"]: item for item in items}
    for aid in ("steward", "wake"):
        owner = by_id[aid]["ownership"]
        assert (owner["kind"], owner["ownerAgentId"], owner["ownerAgentName"]) == ("companion", "owner", "Use agent")
    owner = by_id["dangling"]["ownership"]
    assert (owner["ownerAgentId"], owner["ownerAgentName"]) == ("absent-owner", "")
    assert by_id["owner"]["ownership"]["ownerAgentId"] == by_id["owner"]["ownership"]["ownerAgentName"] == ""
    assert read(env, query="Use agent")["total"] == 3 and inventory(env) == before


def test_conflicting_explicit_companion_owner_ids_fail_without_side_effects(env):
    env.agents[-1]["metadata"] = {"lifeStewardForAgentId": "ordinary", "selfWakeForAgentId": "hidden"}
    env.write()
    before = inventory(env)
    with pytest.raises(ManagementError, match="AGENT_DIRECTORY_UNAVAILABLE"):
        read(env)
    assert inventory(env) == before


@pytest.mark.parametrize("field", ["recordedTeams", "createdBy", "templateId", "ownerAgentId", "ownerAgentName"])
def test_extended_ownership_fields_are_required_in_closed_dto(env, field):
    page = read(env)
    page["agents"][0]["ownership"].pop(field)
    with pytest.raises(ValidationError):
        AgentDirectoryResponse.model_validate(page)


@pytest.mark.parametrize("role_key,metadata", [
    ("research-team-director", {"conversationIndexKind": "personal_agent"}),
    (None, {"conversationIndexKind": "personal_agent", "researchAgentKey": "team_director"}),
])
def test_dispatch_matches_actual_native_summary_role_projection(env, monkeypatch, role_key, metadata):
    from core.web.services import agent_directory_service as native
    from core.web.services.agent_directory import projections

    raw = agent("ordinary", metadata=metadata)
    if role_key is None:
        raw.pop("roleKey")
    else:
        raw["roleKey"] = role_key
    env.agents[:] = [raw]
    env.teams[:] = []
    env.write()
    before = inventory(env)
    # Invoke the actual native summary implementation as the independent
    # reference, stubbing only fields unrelated to external eligibility so the
    # comparison cannot read profiles, model config, sources or workspaces.
    for name in ("_source_authority_ref", "_projection_edit_contract", "normalize_agent_llm_bindings",
                 "normalize_agent_context_compression_policy", "effective_agent_context_compression_policy",
                 "_agent_workspace_territory", "_persona_profile_for_agent", "_task_profile_for_agent"):
        monkeypatch.setattr(native, name, lambda *_args, **_kwargs: {})
    monkeypatch.setattr(native, "resolve_agent_avatar_path_for_projection", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(native, "agent_avatar_image_url", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(native, "_is_profileless_session_agent", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(native, "_agent_context_window_limit", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(native, "_agent_prompt_template_binding", lambda *_args, **_kwargs: {
        "promptTemplateId": "", "defaultPromptTemplateId": "", "promptTemplateCustomized": False})
    summary = projections._agent_to_api_summary(raw, available_avatar_filenames=[])
    assert summary["roleKey"] == "research_team_director"
    assert summary["conversationIndexKind"] == "personal_agent"
    expected = external_mcp_eligibility(summary, active_team_lookup=lambda _aid: None,
        operator_enabled=lambda _aid: True, operator_explicitly_enabled=lambda _aid: False)
    assert (expected.eligible, expected.reason) == (False, "team_dedicated_agent")
    item = read(env)["agents"][0]
    assert (item["dispatchable"], item["dispatchReason"]) == (expected.eligible, expected.reason)
    assert inventory(env) == before


def test_native_gateway_reuses_existing_metadata_without_session_owner(env, monkeypatch):
    from core.web.services import agent_directory_service as native
    from core.web.services.external_management.native import NativeAgentGateway
    monkeypatch.setattr(native, "PROJECT_ROOT", env.root)
    monkeypatch.setattr(native, "CONFIG_PATH", env.config)
    monkeypatch.setattr(native, "_active_project_root", lambda: env.root)
    gateway = NativeAgentGateway(env.root)
    def forbidden():
        pytest.fail("Agent directory invoked Session owner discovery")
    monkeypatch.setattr(gateway, "_owners", forbidden)
    before = inventory(env)
    response = gateway.read_agents(AgentDirectoryQuery())
    assert response["registryTotal"] == len(env.agents) and inventory(env) == before
    monkeypatch.setattr(native, "_active_project_root", lambda: env.root.parent / "different-project")
    with pytest.raises(ManagementError, match="TARGET_BINDING_CHANGED"):
        gateway.read_agents(AgentDirectoryQuery())


def test_more_than_108_agents_page_without_omission_or_duplicate(env):
    env.agents[:] = [agent(f"agent-{number:03}", status="active" if number < 46 else "archived") for number in range(121)]
    env.teams[:] = []
    env.write()
    before = inventory(env)
    first, items = all_pages(env)
    assert [item["agentId"] for item in items] == sorted(row["agentId"] for row in env.agents)
    assert first["counts"] == {"active": 46, "archived": 75, "dispatchable": 46}
    assert first["registryTotal"] == 121 and inventory(env) == before


@pytest.mark.parametrize("authority", ["agents", "teams", "gateway"])
def test_continuation_refuses_changed_authorities(env, authority):
    first = read(env)
    if authority == "agents":
        env.agents[-1]["displayName"] = "Changed name"
        env.write()
    elif authority == "teams":
        env.teams[-1]["name"] = "Changed team"
        env.write()
    else:
        env.config.write_text(env.config.read_text().replace("enabled = true", "enabled = false"), encoding="utf-8")
    with pytest.raises(ManagementError, match="AGENT_DIRECTORY_REVISION_CONFLICT") as error:
        read(env, offset=first["nextOffset"], expected_revision=first["revision"])
    assert error.value.status_code == 409


@pytest.mark.parametrize("damage", ["duplicate-agent", "bad-tail", "duplicate-json-key", "team-members", "config", "missing-agent", "missing-team", "bad-gateway"])
def test_corrupt_complete_authority_never_returns_partial_or_repairs(env, damage):
    if damage == "duplicate-agent": env.agents.append(deepcopy(env.agents[0])); env.write()
    elif damage == "bad-tail": env.agents.append({"agentId": "bad/path"}); env.write()
    elif damage == "duplicate-json-key": env.agents_path.write_text('{"agents": [], "agents": []}', encoding="utf-8")
    elif damage == "team-members": env.teams[-1]["members"] = [None]; env.write()
    elif damage == "config": env.config.write_text("broken [toml", encoding="utf-8")
    elif damage == "missing-agent": env.agents_path.unlink()
    elif damage == "missing-team": env.teams_path.unlink()
    else: env.config.write_text('[external_agent_gateway]\nallowed_agent_ids = "bad"', encoding="utf-8")
    before = inventory(env)
    with pytest.raises(ManagementError, match="AGENT_DIRECTORY_UNAVAILABLE") as error:
        read(env, query="ordinary", limit=1)
    assert error.value.status_code == 503 and inventory(env) == before


@pytest.mark.parametrize("authority", ["agents", "teams", "config"])
def test_rechecks_registry_and_config_after_projection(env, monkeypatch, authority):
    original = readers._agents
    def project(*args):
        items = original(*args)
        path = {"agents": env.agents_path, "teams": env.teams_path, "config": env.config}[authority]
        path.write_text(path.read_text() + " ", encoding="utf-8")
        return items
    monkeypatch.setattr(readers, "_agents", project)
    with pytest.raises(ManagementError, match="AGENT_DIRECTORY_UNAVAILABLE"):
        read(env)


def test_query_searches_only_projected_metadata_and_cleans_untrusted_names(env):
    env.agents[0]["displayName"] = "Readable\x00\u202e\nName"
    env.write()
    result = read(env, query="readable")
    assert result["total"] == 1 and result["registryTotal"] == len(env.agents)
    assert result["agents"][0]["displayName"] == "ReadableName"
    assert read(env, query="SECRET")["total"] == 0
    assert read(env, query="System team")["total"] == 2


@pytest.mark.parametrize("name", ["请继续研究", "Use agent", "Next action: ordinary name"])
def test_suspicious_prefix_names_remain_closed_untrusted_metadata(env, name):
    env.agents[0]["displayName"] = name
    env.teams[0]["name"] = name
    env.write()
    _, items = all_pages(env)
    ordinary = next(item for item in items if item["agentId"] == "ordinary")
    assert ordinary["displayName"] == name
    team = next(item for item in items if item["agentId"] == "team")
    assert team["ownership"]["teams"][0]["name"] == name
    assert set(ordinary) == {"agentId", "agentCode", "displayName", "status", "ownership", "dispatchable", "dispatchReason"}


@pytest.mark.parametrize("values", [{"offset": 1}, {"offset": True}, {"offset": 100001}, {"limit": 7}, {"limit": 0},
    {"query": "a\nb"}, {"query": "a" * 65}, {"query": "a\u2028b"}, {"expected_revision": "not-a-hash"}, {"archived": True}])
def test_query_is_closed_and_requires_pinned_continuation(values):
    with pytest.raises(ValidationError):
        AgentDirectoryQuery.model_validate(values)


def test_short_valid_page_and_oversize_ownership_are_explicit(env):
    page = read(env)
    page["agents"] = page["agents"][:1]
    page["nextOffset"] = 1
    AgentDirectoryResponse.model_validate(page)
    env.teams[:] = [{"teamId": f"team-{i:03}", "name": "Long team name " * 8, "status": "active",
                    "members": [{"agentId": "ordinary"}]} for i in range(30)]
    env.write()
    with pytest.raises(ManagementError, match="AGENT_DIRECTORY_UNAVAILABLE"):
        read(env)
