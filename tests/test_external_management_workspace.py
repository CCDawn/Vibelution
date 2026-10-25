"""Neutral Session metadata reads reject private sources without native writes."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.infrastructure import developer_sandbox
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes import launcher_assistant_management as route
    from core.web.services import agent_directory_service as directory, session_service as sessions
    from core.web.services import team_service as teams
    from core.web.services.session import directory_runtime
    from core.web.services.external_management.native import NativeAgentGateway
    from core.web.services.external_management.service import ManagementService, TargetIdentity

    root = tmp_path / "project"
    root.mkdir()
    row = {"sessionId": "session-a", "agentId": "agent-a", "title": "untrusted title", "status": "ready",
           "sessionKind": "main", "sessionRole": "primary", "conversationIndexKind": "personal_agent",
           "conversationIndexVisibility": "user_visible", "hiddenFromIndex": False, "pinnedAtMs": 123,
           "lastPreview": "SECRET preview"}
    runtime = {"conversation_id": "session-a", "agent_id": "agent-a", "session_kind": "main",
               "conversation_index_kind": "personal_agent", "last_turn_status": "running", "messages": ["SECRET body"]}
    agent = {"agentId": "agent-a", "directSessionId": "session-a", "kind": "persistent", "status": "active",
             "roleKey": "assistant_worker", "conversationIndexKind": "personal_agent", "metadata": {}}
    row["agentConfigRevisionId"] = "agent-a:" + "a" * 64
    snapshot = {"configRevisionId": row["agentConfigRevisionId"], "configHash": "a" * 64,
                "config": {"llmBindings": {"dialogue": {"modelId": "provider/old model"}},
                    "modelParametersByRef": {"provider/old model": {"contextWindow": 32000, "reasoningEffort": "high"}},
                    "reasoningEffortBySlot": {"dialogue": "low"}, "promptTemplateId": "SECRET prompt",
                    "personaProfile": {"secret": "SECRET persona"}, "toolPolicy": {"secret": "SECRET policy"},
                    "sessionBudgetParameters": {"maxCallsPerTurn": 99}},
                "source": "SECRET source", "createdAtMs": 1}
    agent["llmBindings"] = {"dialogue": {"modelId": "provider/current-B"}}
    current_snapshot = copy.deepcopy(snapshot)
    current_snapshot["configRevisionId"] = "agent-a:" + "b" * 64
    current_snapshot["config"]["llmBindings"]["dialogue"]["modelId"] = "provider/current-B"
    current_snapshot["config"]["modelParametersByRef"]["provider/current-B"] = {
        "contextWindow": 65536, "reasoningEffort": "high"}
    registry = root / "agents.json"
    plugin_root = root / "plugin"
    plugin_root.mkdir()
    team_root = root / "teams"
    team_root.mkdir()
    team_index = team_root / "teams.json"
    team_index.write_text('{"teams":[]}', encoding="utf-8")
    calls = []

    def registry_path(*parts, **kwargs):
        assert parts == ("agents", "agents.json") and kwargs == {"intent": "state", "seed": False}
        calls.append("registry")
        return registry

    def plugin_path(project, kind, *parts, **kwargs):
        assert project == root and kind == "agent_directory"
        assert parts == ("agents", "agent-a", "plugins", "virtual-human-life")
        assert kwargs == {"intent": "state", "seed": False}
        calls.append("binding")
        return plugin_root

    class Readers:
        def get_session(self, session_id, *, include_archived):
            assert session_id == "session-a" and include_archived is False
            calls.append("directory")
            return copy.deepcopy(row)

        def get_session_runtime_state(self, session_id):
            assert session_id == "session-a"
            calls.append("runtime")
            return copy.deepcopy(runtime)

        def get_agent_config_revision(self, agent_id, revision_id):
            assert agent_id == "agent-a" and revision_id == row["agentConfigRevisionId"]
            calls.append("revision")
            return copy.deepcopy(snapshot)

        def get_current_agent_config(self, agent_id):
            assert agent_id == "agent-a"
            calls.append("current-revision")
            return copy.deepcopy(current_snapshot)

        def __getattr__(self, name):
            pytest.fail("non-reader repository method: " + name)

    monkeypatch.setattr(directory, "PROJECT_ROOT", root)
    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    monkeypatch.setattr(teams, "PROJECT_ROOT", root)
    def team_path(project, *parts):
        assert project == root and parts == ("teams",)
        calls.append("team-index")
        return team_root
    monkeypatch.setattr(developer_sandbox, "sandboxed_workspace_path", team_path)
    monkeypatch.setattr(developer_sandbox, "seeded_sandbox_workspace_path", lambda *_args: pytest.fail("seeding forbidden"))
    monkeypatch.setattr(directory, "_workspace_path", registry_path)
    monkeypatch.setattr(developer_sandbox, "route_workspace_path", plugin_path)
    repository = Readers()
    monkeypatch.setattr(directory_runtime, "get_open_directory_store", lambda: SimpleNamespace(repository=repository))
    monkeypatch.setattr(directory_runtime, "directory_store_project_root", lambda: root)
    # These common-looking reads repair/open/reconcile and must never be called.
    def forbidden(*_args, **_kwargs):
        pytest.fail("native mutation, provisioning, selection or hydration")
    for owner, names in ((directory, ("get_agent", "load_state", "create_agent_instance", "current_agent_runtime")),
                         (sessions, ("load_session_chat_state", "query_sessions", "get_session_detail")),
                         (teams, ("list_teams_compact", "get_team", "_load_index", "_save_index")),
                         (directory_runtime, ("initialize_session_directory_runtime",))):
        for name in names:
            monkeypatch.setattr(owner, name, forbidden)
    identity = {"projectId": "target", "instanceId": "backend"}
    native = NativeAgentGateway(root)
    service = ManagementService(tmp_path / "management", identity=lambda: TargetIdentity(identity, "control"), native=native)
    grant = service.bind({"client_id": "launcher", "expected_binding": identity, "scopes": ["sessions:read"]})
    monkeypatch.setattr(route, "_SERVICE", service)
    app = FastAPI()
    app.include_router(route.router)
    headers = {CONTROL_TOKEN_HEADER: get_control_token(), route.SUBJECT_HEADER: grant["subject_id"],
               route.CAPABILITY_HEADER: grant["subject_capability"]}
    result = SimpleNamespace(root=root, row=row, runtime=runtime, agent=agent, registry=registry, plugin_root=plugin_root,
        directory=directory, sessions=sessions, directory_runtime=directory_runtime, repository=repository,
        client=TestClient(app), headers=headers, service=service, native=native, grant=grant, calls=calls, identity=identity,
        snapshot=snapshot, current_snapshot=current_snapshot)
    result.team_index, result.teams = team_index, teams
    result.save = lambda: registry.write_text(json.dumps({"agents": [agent]}), encoding="utf-8")
    result.save()
    return result


URL = "/v1/launcher-assistant-management/sessions/session-a"


@pytest.fixture
def list_env(env, monkeypatch):
    from core.chat.conversation_store import ConversationStore

    agents = []
    with ConversationStore(env.root / "list.sqlite3") as store:
        for index, label in enumerate(["ordinary"] * 8 + ["pa", "team", "companion", "hidden"]):
            aid, sid = f"agent-{index:02d}", f"session-{index:02d}"
            revision = store.repository.create_agent(agent_id=aid, display_name=aid, kind="persistent",
                config={}, source="test").result(timeout=3)["configRevisionId"]
            store.repository.create_session(session_id=sid, agent_id=aid, agent_config_revision_id=revision,
                title=("😀" * 60 if index == 0 else f"Visible {index}"),
                conversation_index_kind="personal_agent", conversation_index_visibility="user_visible",
                hidden_from_index=label == "hidden").result(timeout=3)
            runtime = {"conversation_id": sid, "agent_id": aid, "session_kind": "main",
                "conversation_index_kind": "personal_agent", "last_turn_status": "ready",
                "messages": ["PREVIEW_SECRET_SENTINEL"], "last_preview": "PREVIEW_SECRET_SENTINEL"}
            store.repository.upsert_session_runtime_state(sid, runtime, activate=index == 1).result(timeout=3)
            agent = {**env.agent, "agentId": aid, "directSessionId": sid, "metadata": {}}
            if label == "pa":
                agent["roleKey"] = "personal_assistant"
            agents.append(agent)
        env.registry.write_text(json.dumps({"agents": agents}), encoding="utf-8")
        env.team_index.write_text(json.dumps({"teams": [{"teamId": "private", "members": [{"agentId": "agent-09"}]}]}), encoding="utf-8")
        binding = env.plugin_root / "agent-10" / "binding.json"
        binding.parent.mkdir()
        binding.write_text('{"agentId":"agent-10","enabled":true}', encoding="utf-8")
        monkeypatch.setattr(env.directory_runtime, "get_open_directory_store", lambda: store)
        def plugin_path(project, kind, *parts, **kwargs):
            assert project == env.root and kind == "agent_directory" and kwargs == {"intent": "state", "seed": False}
            return env.plugin_root / parts[1]
        monkeypatch.setattr(__import__("core.infrastructure.developer_sandbox", fromlist=["unused"]), "route_workspace_path", plugin_path)
        def forbidden(*args, **kwargs):
            pytest.fail("session_list submitted a native write")
        monkeypatch.setattr(store.writer, "submit", forbidden)
        monkeypatch.setattr(store.writer, "submit_maintenance", forbidden)
        env.store, env.agents = store, agents
        yield env


def test_session_list_real_sqlite_visibility_pagination_and_zero_writes(list_env):
    env = list_env
    before = {str(p): p.read_bytes() for p in env.root.rglob("*") if p.is_file() and not p.name.endswith("-shm")}
    first = env.client.get(URL.rsplit("/", 1)[0], headers=env.headers)
    assert first.status_code == 200, first.text
    page = first.json()
    assert page["total"] == 8 and page["offset"] == 0 and page["limit"] == 6 and page["nextOffset"] == 6
    assert [row["id"] for row in page["sessions"]] == [f"session-{i:02d}" for i in range(6)]
    assert page["sessions"][0]["titlePreview"] == "😀" * 48 and page["sessions"][0]["titleTruncated"]
    second = env.client.get(URL.rsplit("/", 1)[0], params={"offset": 6}, headers=env.headers).json()
    assert [row["id"] for row in second["sessions"]] == ["session-06", "session-07"]
    assert second["nextOffset"] is None and second["total"] == 8
    for payload in (page, second):
        assert payload["untrustedContent"] is True
        assert "PREVIEW_SECRET_SENTINEL" not in json.dumps(payload)
        assert all(set(row) == {"id", "agentId", "titlePreview", "titleTruncated"} for row in payload["sessions"])
    assert env.store.repository.get_active_session_id() == "session-01"
    assert before == {str(p): p.read_bytes() for p in env.root.rglob("*") if p.is_file() and not p.name.endswith("-shm")}
    assert env.calls.count("registry") == 2 and env.calls.count("team-index") == 2


def test_session_list_query_never_searches_body_or_preview(list_env, monkeypatch):
    env = list_env
    original = env.store.repository.list_directory_page
    def guarded(**kwargs):
        assert kwargs.get("query", "") == ""
        return original(**kwargs)
    monkeypatch.setattr(env.store.repository, "list_directory_page", guarded)
    url = URL.rsplit("/", 1)[0]
    assert env.client.get(url, params={"query": "PREVIEW_SECRET_SENTINEL"}, headers=env.headers).json()["total"] == 0
    result = env.client.get(url, params={"query": "Visible 7", "agent_id": "agent-07"}, headers=env.headers)
    assert result.status_code == 200, result.text
    assert [row["id"] for row in result.json()["sessions"]] == ["session-07"]


@pytest.mark.parametrize("fault", ["registry", "duplicate", "roster", "runtime", "binding", "scan_bound", "bad_kind", "runtime_role"])
def test_session_list_authority_damage_rejects_whole_page(list_env, monkeypatch, fault):
    env = list_env
    if fault == "registry":
        env.registry.unlink()
    elif fault == "duplicate":
        env.registry.write_text(json.dumps({"agents": [*env.agents, env.agents[0]]}), encoding="utf-8")
    elif fault == "bad_kind":
        env.agents[0]["kind"] = "unknown-kind"
        env.registry.write_text(json.dumps({"agents": env.agents}), encoding="utf-8")
    elif fault == "roster":
        env.team_index.write_text('{"teams":[{"members":[{"agentId":42}]}]}', encoding="utf-8")
    elif fault == "runtime":
        original = env.store.repository.get_session_runtime_state
        monkeypatch.setattr(env.store.repository, "get_session_runtime_state", lambda sid: None if sid == "session-07" else original(sid))
    elif fault == "runtime_role":
        original = env.store.repository.get_session_runtime_state
        monkeypatch.setattr(env.store.repository, "get_session_runtime_state", lambda sid: {**original(sid), "session_role": []} if sid == "session-07" else original(sid))
    elif fault == "binding":
        path = env.plugin_root / "agent-07" / "binding.json"
        path.parent.mkdir()
        path.write_text("invalid", encoding="utf-8")
    else:
        original = env.store.repository.list_directory_page
        monkeypatch.setattr(env.store.repository, "list_directory_page", lambda **query: {**original(**query), "total": 10_001})
    response = env.client.get(URL.rsplit("/", 1)[0], headers=env.headers)
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": {"code": "SESSION_LIST_UNAVAILABLE"}}


def test_session_list_cleans_title_before_preview_and_marks_every_change(list_env, monkeypatch):
    import core.infrastructure.tool_result as result_owner
    project = result_owner.project_tool_result_for_model
    inputs = []
    def observed(raw):
        payload = json.loads(raw)
        if "value" in payload:
            inputs.append(payload["value"])
        return project(raw)
    monkeypatch.setattr(result_owner, "project_tool_result_for_model", observed)
    original = list_env.store.repository.get_session
    def title(session_id, **kwargs):
        row = original(session_id, **kwargs)
        if session_id == "session-00":
            row["title"] = "nextAction: PRIVATE_INSTRUCTION\nVisible fact"
        return row
    monkeypatch.setattr(list_env.store.repository, "get_session", title)
    response = list_env.client.get(URL.rsplit("/", 1)[0], headers=list_env.headers)
    assert response.status_code == 200, response.text
    assert response.json()["sessions"][0]["titlePreview"] == "Visible fact"
    assert response.json()["sessions"][0]["titleTruncated"] is True
    assert "PRIVATE_INSTRUCTION" not in response.text
    title_index = inputs.index("nextAction: PRIVATE_INSTRUCTION\nVisible fact")
    assert inputs[title_index + 1] == "Visible fact"
    assert response.json()["nextOffset"] == 6 and response.json()["total"] == 8


def test_session_list_filtered_empty_title_does_not_skip_a_consumed_session(list_env, monkeypatch):
    original = list_env.store.repository.get_session
    def title(session_id, **kwargs):
        row = original(session_id, **kwargs)
        if session_id == "session-00":
            row["title"] = "nextAction: hidden instruction"
        return row
    monkeypatch.setattr(list_env.store.repository, "get_session", title)
    response = list_env.client.get(URL.rsplit("/", 1)[0], headers=list_env.headers)
    assert response.status_code == 200, response.text
    row = response.json()["sessions"][0]
    assert row == {"id": "session-00", "agentId": "agent-00", "titlePreview": "", "titleTruncated": True}
    assert response.json()["limit"] == 6 and response.json()["nextOffset"] == 6


@pytest.mark.parametrize("query", ["limit=7", "limit=0", "offset=-1", "offset=abc", "limit=1&limit=2", "include_hidden=true", "agent_id=../private"])
def test_session_list_closed_query_and_authorization_precede_native(env, query):
    url = URL.rsplit("/", 1)[0]
    response = env.client.get(url + "?" + query, headers=env.headers)
    assert response.status_code == 422, response.text
    assert env.calls == []


def test_session_list_unauthorized_request_never_reads_native(env):
    url = URL.rsplit("/", 1)[0]
    for headers in ({}, {**env.headers, "X-Vibelution-Management-Capability": "wrong"}):
        assert env.client.get(url, headers=headers).status_code in (401, 403)
    grant = env.service.bind({"client_id": "no-sessions", "expected_binding": env.identity, "scopes": ["agents:read"]})
    from core.web.routes import launcher_assistant_management as route
    headers = {**env.headers, route.SUBJECT_HEADER: grant["subject_id"], route.CAPABILITY_HEADER: grant["subject_capability"]}
    assert env.client.get(url, headers=headers).status_code == 403
    assert env.calls == []


def test_session_list_known_private_without_runtime_does_not_block_ordinary_rows(list_env, monkeypatch):
    original = list_env.store.repository.get_session_runtime_state
    def read(sid):
        return None if sid in {"session-08", "session-09", "session-10"} else original(sid)
    monkeypatch.setattr(list_env.store.repository, "get_session_runtime_state", read)
    response = list_env.client.get(URL.rsplit("/", 1)[0], headers=list_env.headers)
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 8


@pytest.mark.parametrize("fault", ["owner_alias", "bad_binding", "runtime_owner"])
def test_session_list_private_marker_never_hides_identity_or_binding_damage(list_env, monkeypatch, fault):
    if fault == "owner_alias":
        original = list_env.store.repository.get_session
        def row(sid, **kwargs):
            result = original(sid, **kwargs)
            if sid == "session-08":
                result["agent_id"] = "foreign"
            return result
        monkeypatch.setattr(list_env.store.repository, "get_session", row)
    elif fault == "bad_binding":
        path = list_env.plugin_root / "agent-08" / "binding.json"
        path.parent.mkdir()
        path.write_text("invalid", encoding="utf-8")
    else:
        original = list_env.store.repository.get_session_runtime_state
        monkeypatch.setattr(list_env.store.repository, "get_session_runtime_state",
            lambda sid: {**original(sid), "agent_id": "foreign"} if sid == "session-08" else original(sid))
    response = list_env.client.get(URL.rsplit("/", 1)[0], headers=list_env.headers)
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "SESSION_LIST_UNAVAILABLE"}}


def test_session_list_never_silently_rewrites_an_identifier_during_model_projection(env, monkeypatch):
    from core.chat.conversation_store import ConversationStore
    with ConversationStore(env.root / "list-id.sqlite3") as store:
        revision = store.repository.create_agent(agent_id="agent-a", display_name="A", kind="persistent",
            config={}, source="test").result(timeout=3)["configRevisionId"]
        store.repository.create_session(session_id="please", agent_id="agent-a", agent_config_revision_id=revision,
            title="Visible fact", conversation_index_kind="personal_agent",
            conversation_index_visibility="user_visible").result(timeout=3)
        store.repository.upsert_session_runtime_state("please", {"conversation_id": "please", "agent_id": "agent-a",
            "session_kind": "main", "conversation_index_kind": "personal_agent"}).result(timeout=3)
        env.agent["directSessionId"] = "please"
        env.save()
        monkeypatch.setattr(env.directory_runtime, "get_open_directory_store", lambda: store)
        monkeypatch.setattr(store.writer, "submit", lambda *args, **kwargs: pytest.fail("read submitted a write"))
        response = env.client.get(URL.rsplit("/", 1)[0], headers=env.headers)
        assert response.status_code == 503
        assert response.json() == {"detail": {"code": "SESSION_LIST_UNAVAILABLE"}}


@pytest.mark.parametrize("patch", [
    {"session_role": "unknown-role"},
    {"read_only": True, "session_kind": "unknown-kind"},
    {"read_only": True, "session_role": "unknown-role"},
    {"read_only": True, "conversation_index_visibility": "unknown-visibility"},
    {"read_only": True, "conversation_index_kind": "unknown-index-kind"},
    {"read_only": True, "sessionRole": "unknown-role"},
    {"read_only": True, "archive_state": []},
    {"read_only": True, "archiveState": []},
    {"read_only": True, "personalAssistantProfile": {"bad": 1}},
    {"read_only": True, "virtualHumanCompanion": {"bad": 1}},
    {"read_only": True, "virtualHumanSelfWake": [1]},
    {"read_only": True, "lifeStewardForAgentId": 1},
])
def test_session_list_unknown_native_semantics_cannot_hide_behind_private_marker(list_env, monkeypatch, patch):
    original = list_env.store.repository.get_session_runtime_state
    monkeypatch.setattr(list_env.store.repository, "get_session_runtime_state",
        lambda sid: {**original(sid), **patch} if sid == "session-00" else original(sid))
    response = list_env.client.get(URL.rsplit("/", 1)[0], headers=list_env.headers)
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": {"code": "SESSION_LIST_UNAVAILABLE"}}


@pytest.mark.parametrize("role", ["", "primary", "workspace"])
def test_session_list_retains_native_conversation_roles(list_env, monkeypatch, role):
    original = list_env.store.repository.get_session_runtime_state
    monkeypatch.setattr(list_env.store.repository, "get_session_runtime_state",
        lambda sid: {**original(sid), "session_role": role} if sid == "session-00" else original(sid))
    response = list_env.client.get(URL.rsplit("/", 1)[0], headers=list_env.headers)
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 8


@pytest.mark.parametrize("patch", [
    {"session_kind": "supervised"},
    {"archive_state": {"status": "archived"}},
    {"read_only": True},
])
def test_session_list_canonical_private_semantics_remain_filtered(list_env, monkeypatch, patch):
    original = list_env.store.repository.get_session_runtime_state
    monkeypatch.setattr(list_env.store.repository, "get_session_runtime_state",
        lambda sid: {**original(sid), **patch} if sid == "session-00" else original(sid))
    response = list_env.client.get(URL.rsplit("/", 1)[0], headers=list_env.headers)
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 7
    assert all(row["id"] != "session-00" for row in response.json()["sessions"])


@pytest.mark.parametrize("empty", [None, False, "", 0, [], {}])
def test_session_list_preserves_existing_falsey_marker_boundary(list_env, monkeypatch, empty):
    original = list_env.store.repository.get_session_runtime_state
    patch = {key: empty for key in ("personalAssistantProfile", "virtualHumanCompanion", "virtualHumanSelfWake", "lifeStewardForAgentId")}
    monkeypatch.setattr(list_env.store.repository, "get_session_runtime_state",
        lambda sid: {**original(sid), **patch} if sid == "session-00" else original(sid))
    response = list_env.client.get(URL.rsplit("/", 1)[0], headers=list_env.headers)
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 8


def test_config_reads_historical_revision_only_and_never_writes(env, monkeypatch):
    before = {str(p): p.read_bytes() for p in env.root.parent.rglob("*") if p.is_file()}
    monkeypatch.setattr(env.service.store, "write", lambda *_a, **_k: pytest.fail("intent write"))
    monkeypatch.setattr(env.service.store, "lock", lambda *_a, **_k: pytest.fail("intent lock"))
    response = env.client.get(URL + "/config", headers=env.headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"source": "session_agent_config_revision", "untrustedContent": True, "config": {
        "sessionId": "session-a", "agentId": "agent-a", "agentConfigRevisionId": env.row["agentConfigRevisionId"],
        "modelId": "provider/old model", "contextWindow": 32000, "reasoningEffort": "high"}}
    assert env.calls == ["directory", "runtime", "registry", "team-index", "binding", "revision"]
    assert "SECRET" not in response.text and "current-B" not in response.text
    assert before == {str(p): p.read_bytes() for p in env.root.parent.rglob("*") if p.is_file()}


def test_config_comparison_is_native_derived_and_metadata_only(env, monkeypatch):
    before = {str(p): p.read_bytes() for p in env.root.parent.rglob("*") if p.is_file()}
    monkeypatch.setattr(env.service.store, "write", lambda *_a, **_k: pytest.fail("intent write"))
    monkeypatch.setattr(env.service.store, "lock", lambda *_a, **_k: pytest.fail("intent lock"))
    response = env.client.get(URL + "/config-comparison", headers=env.headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"source": "session_agent_config_comparison", "untrustedContent": True,
        "sessionId": "session-a", "agentId": "agent-a",
        "pinned": {"agentConfigRevisionId": env.row["agentConfigRevisionId"], "modelId": "provider/old model",
                   "contextWindow": 32000, "reasoningEffort": "high"},
        "current": {"agentConfigRevisionId": env.current_snapshot["configRevisionId"], "modelId": "provider/current-B",
                    "contextWindow": 65536, "reasoningEffort": "high"},
        "sameRevision": False, "changedFields": ["modelId", "contextWindow"]}
    assert env.calls == ["directory", "runtime", "registry", "team-index", "binding", "revision", "current-revision"]
    assert "SECRET" not in response.text and "configHash" not in response.text
    assert before == {str(p): p.read_bytes() for p in env.root.parent.rglob("*") if p.is_file()}


def test_read_only_public_projection_and_frozen_identity(env, monkeypatch):
    before = {str(path): path.read_bytes() for path in env.root.parent.rglob("*") if path.is_file()}
    records = copy.deepcopy((env.row, env.runtime, env.agent))
    def forbidden(*_args, **_kwargs):
        pytest.fail("GET attempted an intent or receipt write")
    monkeypatch.setattr(env.service.store, "write", forbidden)
    monkeypatch.setattr(env.service.store, "lock", forbidden)
    response = env.client.get(URL, headers=env.headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"session": {"id": "session-a", "title": "untrusted title", "agentId": "agent-a",
        "pinned": True, "pinnedAtMs": 123, "status": "running", "archived": False}, "untrustedContent": True}
    assert env.calls == ["directory", "runtime", "registry", "team-index", "binding"]
    assert records == (env.row, env.runtime, env.agent)
    assert before == {str(path): path.read_bytes() for path in env.root.parent.rglob("*") if path.is_file()}


@pytest.mark.parametrize("suffix", ["", "/config", "/config-comparison"])
@pytest.mark.parametrize("target,patch", [
    ("row", {"hiddenFromIndex": True}), ("row", {"conversationIndexVisibility": "team_private"}),
    ("row", {"conversationIndexKind": "hidden"}), ("row", {"conversationIndexKind": "system_entry"}),
    ("row", {"conversationIndexKind": "team_agent"}), ("row", {"conversationIndexKind": "invalid"}),
    ("row", {"conversationIndexKind": "user_chat"}), ("row", {"sessionKind": "child"}),
    ("row", {"parentSessionId": "parent"}), ("row", {"teamId": "team"}), ("row", {"sessionId": "other"}),
    ("row", {"agent_id": "different"}),
    ("runtime", {"read_only": True}), ("runtime", {"readOnly": True}), ("runtime", {"archived": True}),
    ("runtime", {"archive_state": {"status": "archived"}}), ("runtime", {"archiveState": []}),
    ("runtime", {"agentId": "different"}), ("runtime", {"agent_id": ""}),
    ("runtime", {"conversation_id": "other"}), ("runtime", {"root_session_id": "parent"}),
    ("runtime", {"agent_profile_id": "legacy-profile"}), ("runtime", {"created_by": "research_organization"}),
    ("runtime", {"hidden_from_index": True}), ("runtime", {"session_kind": "child"}),
    ("runtime", {"conversation_index_kind": "personal_agent", "conversationIndexKind": "hidden"}),
    ("runtime", {"conversation_index_kind": "personal_agent", "conversationIndexKind": "user_chat"}),
    ("agent", {"status": "archived"}), ("agent", {"kind": "ephemeral"}),
    ("agent", {"directSessionId": "other"}), ("agent", {"roleKey": "personal_assistant"}),
    ("agent", {"roleKey": ""}), ("agent", {"conversationIndexKind": "hidden"}),
    ("agent", {"metadata": {"personalAssistantProfile": "default"}}),
    ("agent", {"metadata": {"virtualHumanCompanion": True}}),
    ("agent", {"metadata": {"virtualHumanSelfWake": True}}),
    ("agent", {"metadata": {"lifeStewardForAgentId": "owner"}}),
    ("agent", {"metadata": {"teamId": "team"}}), ("agent", {"metadata": {"protected": True}}),
    ("agent", {"createdBy": "system_repair"}), ("agent", {"metadata": {"systemRole": "ceo"}}),
    ("agent", {"roleKey": "challenge_cup_member"}),
    ("agent", {"metadata": {"conversationIndexKind": "hidden"}}),
])
def test_private_ambiguous_and_conflicting_sources_fail_closed(env, target, patch, suffix):
    getattr(env, target).update(patch)
    env.save()
    response = env.client.get(URL + suffix, headers=env.headers)
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": {"code": "SESSION_UNAVAILABLE"}}


@pytest.mark.parametrize("contents", [None, "invalid", "[]", "{}", '{"agents":null}', '{"agents":[null]}'])
def test_registry_missing_or_corrupt_never_repaired(env, contents):
    if contents is None:
        env.registry.unlink()
    else:
        env.registry.write_text(contents, encoding="utf-8")
    assert env.client.get(URL, headers=env.headers).status_code == 404
    assert env.registry.exists() is (contents is not None)


@pytest.mark.parametrize("contents", [None, "broken", "[]", "{}", '{"teams":null}', '{"teams":[null]}',
    '{"teams":[{"members":null}]}', '{"teams":[{"members":[{}]}]}',
    '{"teams":[{"members":[{"agent_id":"agent-a"}]}]}'])
def test_roster_authority_unavailable_or_unsupported_denies_without_repair(env, contents):
    if contents is None:
        env.team_index.unlink()
    else:
        env.team_index.write_text(contents, encoding="utf-8")
    before = env.team_index.read_bytes() if contents is not None else None
    assert env.client.get(URL, headers=env.headers).status_code == 404
    assert (env.team_index.read_bytes() if env.team_index.exists() else None) == before


@pytest.mark.parametrize("team_patch,member_patch", [
    ({"teamSource": "research_organization"}, {}), ({"teamKind": "self_evolution"}, {}),
    ({"systemTeamKind": "supervised_evolution"}, {}), ({"teamKind": "custom"}, {}),
    ({"status": "archived"}, {"agentStatus": "archived"}), ({}, {"status": "archived"}),
    ({}, {"agentId": " agent-a ", "memberId": "legacy", "agentName": "legacy"}),
])
def test_roster_only_team_member_blocks_ordinary_agent_without_metadata(env, team_patch, member_patch):
    team = {"teamId": "team-a", "status": "active", "members": [{"agentId": "agent-a", **member_patch}], **team_patch}
    env.team_index.write_text(json.dumps({"teams": [team]}), encoding="utf-8")
    before = env.team_index.read_bytes()
    assert env.agent["metadata"] == {} and env.row["conversationIndexKind"] == "personal_agent"
    response = env.client.get(URL, headers=env.headers)
    assert response.status_code == 404, response.text
    assert env.team_index.read_bytes() == before


def test_unrelated_valid_team_roster_allows_ordinary_read(env):
    env.team_index.write_text(json.dumps({"teams": [{"teamId": "team-a", "members": [{"agentId": "agent-b"}]}]}), encoding="utf-8")
    assert env.client.get(URL, headers=env.headers).status_code == 200


@pytest.mark.parametrize("member_id", [123, ["agent-a"], {"id": "agent-a"}, " \t\n "])
def test_invalid_raw_roster_agent_id_denies_before_projection(env, member_id):
    env.team_index.write_text(json.dumps({"teams": [{"teamId": "team-a", "members": [{"agentId": member_id}]}]}), encoding="utf-8")
    before = env.team_index.read_bytes()
    response = env.client.get(URL, headers=env.headers)
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": {"code": "SESSION_UNAVAILABLE"}}
    assert env.team_index.read_bytes() == before


def test_valid_raw_roster_agent_id_retains_native_normalization(env):
    env.team_index.write_text(json.dumps({"teams": [{"teamId": "team-a", "members": [{"agentId": " agent-b "}]}]}), encoding="utf-8")
    assert env.client.get(URL, headers=env.headers).status_code == 200


def test_duplicate_registry_owner_and_competing_direct_owner_deny(env):
    env.registry.write_text(json.dumps({"agents": [env.agent, env.agent]}), encoding="utf-8")
    assert env.client.get(URL, headers=env.headers).status_code == 404
    env.registry.write_text(json.dumps({"agents": [env.agent, {**env.agent, "agentId": "agent-b"}]}), encoding="utf-8")
    assert env.client.get(URL, headers=env.headers).status_code == 404


@pytest.mark.parametrize("binding", ['{"enabled":true}', '{"enabled":null}', '{}', '[]', 'broken',
                                    '{"enabled":false,"agentId":"other"}'])
def test_native_companion_binding_without_metadata_is_protected(env, binding):
    path = env.plugin_root / "binding.json"
    path.write_text(binding, encoding="utf-8")
    response = env.client.get(URL, headers=env.headers)
    assert response.status_code == 404
    assert path.read_text(encoding="utf-8") == binding


def test_explicit_disabled_companion_binding_can_read(env):
    (env.plugin_root / "binding.json").write_text('{"enabled":false,"agentId":"agent-a"}', encoding="utf-8")
    assert env.client.get(URL, headers=env.headers).status_code == 200


def test_open_store_and_every_project_binding_are_required(env, monkeypatch):
    monkeypatch.setattr(env.directory_runtime, "get_open_directory_store", lambda: None)
    assert env.client.get(URL, headers=env.headers).status_code == 503
    monkeypatch.setattr(env.directory_runtime, "directory_store_project_root", lambda: env.root / "other")
    assert env.client.get(URL, headers=env.headers).status_code == 409
    monkeypatch.setattr(env.directory, "PROJECT_ROOT", env.root / "other")
    assert env.client.get(URL, headers=env.headers).status_code == 409
    assert not env.calls


def test_team_authority_root_mismatch_denies(env, monkeypatch):
    monkeypatch.setattr(env.teams, "PROJECT_ROOT", env.root / "other")
    assert env.client.get(URL, headers=env.headers).status_code == 404
    assert "team-index" not in env.calls


@pytest.mark.parametrize("session_id", ["", " ../session-a", "bad/path", "bad?query", "x" * 161, None, 1])
def test_shared_closed_session_query_rejects_invalid_ids_before_native(env, session_id):
    from core.web.services.external_management.service import ManagementError
    with pytest.raises(ManagementError, match="INVALID_INPUT"):
        env.service.read_session(env.grant["subject_id"], env.grant["subject_capability"], session_id)
    assert not env.calls


@pytest.mark.parametrize("suffix", ["", "/config", "/config-comparison"])
def test_control_capability_scope_and_closed_query_before_any_native_read(env, suffix):
    assert env.client.get(URL + suffix).status_code == 403
    assert env.client.get(URL + suffix, headers={**env.headers, "X-Vibelution-Management-Capability": "x" * 48}).status_code == 403
    assert env.client.get(URL + suffix + "?body=true", headers=env.headers).status_code == 422
    grant = env.service.bind({"client_id": "old", "expected_binding": env.identity, "scopes": ["agents:read"]})
    assert env.client.get(URL + suffix, headers={**env.headers, "X-Vibelution-Management-Subject": grant["subject_id"],
        "X-Vibelution-Management-Capability": grant["subject_capability"]}).status_code == 403
    assert not env.calls


def test_old_subject_never_inherits_new_scope(env):
    from core.web.services.external_management.service import ManagementError
    payload = {"client_id": "legacy", "expected_binding": env.identity, "scopes": ["agents:read"]}
    old = env.service.bind(payload)
    with pytest.raises(ManagementError, match="SUBJECT_GRANT_CONFLICT"):
        env.service.bind({**payload, "scopes": ["agents:read", "sessions:read"]})
    assert env.service.bind(payload) == old


@pytest.mark.parametrize("seal", ["ordinary", "runtime_archived", "directory_archived", "roster_hidden", "team_missing"])
def test_real_sqlite_readers_do_not_submit_or_change_selection(env, monkeypatch, seal):
    from core.chat.conversation_store import ConversationStore

    path = env.root / "conversations.sqlite3"
    with ConversationStore(path) as store:
        revision = store.repository.create_agent(agent_id="agent-a", display_name="A", kind="persistent",
            config={}, source="test").result(timeout=3)["configRevisionId"]
        store.repository.create_session(session_id="session-a", agent_id="agent-a", agent_config_revision_id=revision,
            title="real title", conversation_index_kind="personal_agent", conversation_index_visibility="user_visible",
            archived=seal == "directory_archived").result(timeout=3)
        store.repository.create_session(session_id="session-selected", agent_id="agent-a", agent_config_revision_id=revision,
            title="selected", conversation_index_kind="personal_agent", conversation_index_visibility="user_visible").result(timeout=3)
        runtime = copy.deepcopy(env.runtime)
        if seal == "runtime_archived":
            runtime["archive_state"] = {"status": "archived", "source": "user"}
        store.repository.upsert_session_runtime_state("session-a", runtime).result(timeout=3)
        runtime = store.repository.get_session_runtime_state("session-a")
        store.repository.upsert_session_runtime_state("session-selected", {"conversation_id": "session-selected",
            "agent_id": "agent-a"}, activate=True).result(timeout=3)
        if seal == "roster_hidden":
            env.team_index.write_text(json.dumps({"teams": [{"teamId": "hidden-team", "teamSource": "research_organization",
                "members": [{"agentId": "agent-a"}]}]}), encoding="utf-8")
        elif seal == "team_missing":
            env.team_index.unlink()
        monkeypatch.setattr(env.directory_runtime, "get_open_directory_store", lambda: store)
        before = {file: file.read_bytes() for file in env.root.rglob("*") if file.is_file() and not file.name.endswith("-shm")}
        def forbidden(*_args, **_kwargs):
            pytest.fail("reader submitted a native SQLite write")
        monkeypatch.setattr(store.writer, "submit", forbidden)
        monkeypatch.setattr(store.writer, "submit_maintenance", forbidden)
        response = env.client.get(URL, headers=env.headers)
        assert response.status_code == (200 if seal == "ordinary" else 404), response.text
        if seal == "ordinary":
            assert response.json()["session"]["title"] == "real title"
            assert response.json()["session"]["pinnedAtMs"] is None
        assert store.repository.get_active_session_id() == "session-selected"
        assert store.repository.get_session_runtime_state("session-a") == runtime
        assert before == {file: file.read_bytes() for file in env.root.rglob("*") if file.is_file() and not file.name.endswith("-shm")}


@pytest.mark.parametrize("fault", ["missing-pin", "bad-pin", "missing-revision", "wrong-revision", "cross-agent",
    "missing-config", "bad-config", "missing-binding", "bad-binding", "blank-model", "model-trim", "model-newline",
    "model-control", "model-long", "model-number", "bad-map", "bad-entry", "context-bool", "context-string",
    "context-float", "context-zero", "context-negative", "context-overflow", "context-null", "effort-null",
    "effort-number", "effort-uppercase", "effort-space", "effort-newline", "effort-long", "legacy-map", "legacy-null"])
def test_config_missing_or_damaged_selected_fields_never_fall_back(env, monkeypatch, fault):
    config = env.snapshot["config"]
    entry = config["modelParametersByRef"]["provider/old model"]
    if fault == "missing-pin": env.row.pop("agentConfigRevisionId")
    elif fault == "bad-pin": env.row["agentConfigRevisionId"] = True
    elif fault == "missing-revision": monkeypatch.setattr(env.repository, "get_agent_config_revision", lambda *_a: None)
    elif fault == "wrong-revision": env.snapshot["configRevisionId"] = "agent-a:" + "b" * 64
    elif fault == "cross-agent": env.row["agentConfigRevisionId"] = env.snapshot["configRevisionId"] = "agent-other:" + "a" * 64
    elif fault == "missing-config": env.snapshot.pop("config")
    elif fault == "bad-config": env.snapshot["config"] = []
    elif fault == "missing-binding": config.pop("llmBindings")
    elif fault == "bad-binding": config["llmBindings"]["dialogue"] = []
    elif fault.startswith("model-") or fault == "blank-model":
        config["llmBindings"]["dialogue"]["modelId"] = {"blank-model": "", "model-trim": " provider/model",
            "model-newline": "provider/model\nother", "model-control": "provider/\x85model", "model-long": "x" * 301,
            "model-number": 5}[fault]
    elif fault == "bad-map": config["modelParametersByRef"] = []
    elif fault == "bad-entry": config["modelParametersByRef"]["provider/old model"] = None
    elif fault.startswith("context-"):
        entry["contextWindow"] = {"context-bool": True, "context-string": "32000", "context-float": 32000.0,
            "context-zero": 0, "context-negative": -1, "context-overflow": 2**53, "context-null": None}[fault]
    elif fault.startswith("effort-"):
        entry["reasoningEffort"] = {"effort-null": None, "effort-number": 1, "effort-uppercase": "HIGH",
            "effort-space": " high", "effort-newline": "high\n", "effort-long": "x" * 41}[fault]
    elif fault.startswith("legacy-"):
        entry.pop("reasoningEffort")
        config["reasoningEffortBySlot"] = [] if fault == "legacy-map" else {"dialogue": None}
    response = env.client.get(URL + "/config", headers=env.headers)
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": {"code": "SESSION_CONFIG_UNAVAILABLE"}}


@pytest.mark.parametrize("mode,expected", [("unset", None), ("legacy", "low"), ("clear", ""), ("override", "high")])
def test_config_pure_resolution_keeps_missing_legacy_and_explicit_clear_distinct(env, mode, expected):
    config = env.snapshot["config"]
    entry = config["modelParametersByRef"]["provider/old model"]
    entry.pop("contextWindow")
    if mode in {"unset", "legacy"}: entry.pop("reasoningEffort")
    if mode == "unset": config.pop("reasoningEffortBySlot")
    if mode == "clear": entry["reasoningEffort"] = ""
    config["modelParametersByRef"]["unselected"] = {"contextWindow": "SECRET", "reasoningEffort": {"bad": True}}
    response = env.client.get(URL + "/config", headers=env.headers)
    assert response.status_code == 200, response.text
    assert response.json()["config"]["contextWindow"] is None
    assert response.json()["config"]["reasoningEffort"] == expected
    assert "SECRET" not in response.text and "unselected" not in response.text


@pytest.mark.parametrize("case", ["ordinary", "missing-revision", "cross-agent", "bad-json", "hidden-roster", "companion"])
def test_config_real_sqlite_pin_is_historical_zero_write_and_selection_unchanged(env, monkeypatch, case):
    import sqlite3
    from core.chat.conversation_store import ConversationStore
    old_config = copy.deepcopy(env.snapshot["config"])
    path = env.root / "historical.sqlite3"
    with ConversationStore(path) as store:
        pinned = store.repository.create_agent(agent_id="agent-a", display_name="A", kind="persistent",
            config=old_config, source="test").result(timeout=3)["configRevisionId"]
        if case == "cross-agent":
            other_revision = store.repository.create_agent(agent_id="other", display_name="Other", kind="persistent",
                config=old_config, source="test").result(timeout=3)["configRevisionId"]
        store.repository.create_session(session_id="session-a", agent_id="agent-a", agent_config_revision_id=pinned,
            title="real", conversation_index_kind="personal_agent", conversation_index_visibility="user_visible").result(timeout=3)
        store.repository.upsert_session_runtime_state("session-a", env.runtime).result(timeout=3)
        store.repository.upsert_session_runtime_state("selected", {"conversation_id": "selected"}, activate=True).result(timeout=3)
        current = {**old_config, "llmBindings": {"dialogue": {"modelId": "provider/current-B"}}}
        store.repository.import_agent_config_snapshots([{"agent_id": "agent-a", "display_name": "Current",
            "kind": "persistent", "status": "active", "config": current, "source": "test"}]).result(timeout=3)
        if case in {"bad-json", "missing-revision", "cross-agent"}:
            with sqlite3.connect(path) as db:
                if case == "bad-json": db.execute("UPDATE agent_config_revisions SET config_json='[]' WHERE revision_id=?", (pinned,))
                else: db.execute("UPDATE sessions SET agent_config_revision_id=? WHERE session_id='session-a'",
                    (other_revision if case == "cross-agent" else "agent-a:" + "e" * 64,))
        if case == "hidden-roster":
            env.team_index.write_text(json.dumps({"teams": [{"teamId": "team", "members": [{"agentId": "agent-a"}]}]}), encoding="utf-8")
        if case == "companion":
            (env.plugin_root / "binding.json").write_text('{"agentId":"agent-a","enabled":true}', encoding="utf-8")
        monkeypatch.setattr(env.directory_runtime, "get_open_directory_store", lambda: store)
        def forbidden(*_args, **_kwargs): pytest.fail("read called writer, repair, config or current revision")
        monkeypatch.setattr(store.writer, "submit", forbidden)
        monkeypatch.setattr(store.writer, "submit_maintenance", forbidden)
        monkeypatch.setattr(store.repository, "get_current_agent_config", forbidden)
        monkeypatch.setattr(env.sessions, "get_config", forbidden)
        monkeypatch.setattr(env.sessions, "_ensure_session_conversation_record", forbidden)
        before = {f: f.read_bytes() for f in env.root.rglob("*") if f.is_file() and not f.name.endswith("-shm")}
        response = env.client.get(URL + "/config", headers=env.headers)
        assert response.status_code == (200 if case == "ordinary" else 404), response.text
        if case == "ordinary":
            assert response.json()["config"]["modelId"] == "provider/old model"
            assert response.json()["config"]["agentConfigRevisionId"] == pinned
            assert "SECRET" not in response.text
        assert store.repository.get_active_session_id() == "selected"
        assert before == {f: f.read_bytes() for f in env.root.rglob("*") if f.is_file() and not f.name.endswith("-shm")}


@pytest.mark.parametrize("side,fault", [(side, fault) for side in ("pinned", "current") for fault in (
    "missing", "config-list", "wrong-actor", "context-bool", "context-string", "context-overflow",
    "context-null", "model-trim", "effort-list", "legacy-map")])
def test_comparison_both_sides_reuse_strict_projection_and_fail_closed(env, monkeypatch, side, fault):
    snapshot = env.snapshot if side == "pinned" else env.current_snapshot
    method = "get_agent_config_revision" if side == "pinned" else "get_current_agent_config"
    config = snapshot["config"]
    model = config["llmBindings"]["dialogue"]["modelId"]
    entry = config["modelParametersByRef"][model]
    if fault == "missing": monkeypatch.setattr(env.repository, method, lambda *_a: None)
    elif fault == "config-list": snapshot["config"] = []
    elif fault == "wrong-actor": snapshot["configRevisionId"] = "other:" + "d" * 64
    elif fault == "context-bool": entry["contextWindow"] = True
    elif fault == "context-string": entry["contextWindow"] = "32000"
    elif fault == "context-overflow": entry["contextWindow"] = 2**53
    elif fault == "context-null": entry["contextWindow"] = None
    elif fault == "model-trim": config["llmBindings"]["dialogue"]["modelId"] = " model"
    elif fault == "effort-list": entry["reasoningEffort"] = []
    elif fault == "legacy-map":
        entry.pop("reasoningEffort")
        config["reasoningEffortBySlot"] = []
    response = env.client.get(URL + "/config-comparison", headers=env.headers)
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": {"code": "SESSION_CONFIG_COMPARISON_UNAVAILABLE"}}
    # Damaged current data must never break the separate history-only surface.
    if side == "current":
        env.calls.clear()
        history = env.client.get(URL + "/config", headers=env.headers)
        assert history.status_code == 200 and "current-revision" not in env.calls


@pytest.mark.parametrize("same_revision", [True, False])
def test_comparison_identical_fields_do_not_imply_same_revision(env, same_revision):
    revision = env.row["agentConfigRevisionId"] if same_revision else env.current_snapshot["configRevisionId"]
    env.current_snapshot.clear()
    env.current_snapshot.update(copy.deepcopy(env.snapshot), configRevisionId=revision)
    response = env.client.get(URL + "/config-comparison", headers=env.headers)
    assert response.status_code == 200, response.text
    assert response.json()["sameRevision"] is same_revision and response.json()["changedFields"] == []


def test_comparison_legacy_and_null_unset_semantics_remain_distinct(env):
    old = env.snapshot["config"]
    old["modelParametersByRef"]["provider/old model"] = {}
    old["reasoningEffortBySlot"] = {"dialogue": "low"}
    current = env.current_snapshot["config"]
    current["modelParametersByRef"]["provider/current-B"] = {"reasoningEffort": ""}
    response = env.client.get(URL + "/config-comparison", headers=env.headers)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["pinned"]["contextWindow"] is None and value["current"]["contextWindow"] is None
    assert value["pinned"]["reasoningEffort"] == "low" and value["current"]["reasoningEffort"] == ""
    assert value["changedFields"] == ["modelId", "reasoningEffort"]


@pytest.mark.parametrize("case", ["different", "same-revision", "same-fields", "legacy", "missing-current",
                                  "missing-pin", "corrupt-current", "wrong-actor", "team", "companion"])
def test_comparison_real_sqlite_immutable_snapshots_and_zero_writer(env, monkeypatch, case):
    import sqlite3
    from core.chat.conversation_store import ConversationStore
    old = copy.deepcopy(env.snapshot["config"])
    if case == "legacy":
        old["modelParametersByRef"]["provider/old model"].pop("reasoningEffort")
        old["reasoningEffortBySlot"]["dialogue"] = "low"
    path = env.root / "comparison.sqlite3"
    with ConversationStore(path) as store:
        pinned = store.repository.create_agent(agent_id="agent-a", display_name="A", kind="persistent",
            config=old, source="test").result(timeout=3)["configRevisionId"]
        store.repository.create_session(session_id="session-a", agent_id="agent-a", agent_config_revision_id=pinned,
            title="ordinary", conversation_index_kind="personal_agent", conversation_index_visibility="user_visible").result(timeout=3)
        store.repository.upsert_session_runtime_state("session-a", env.runtime).result(timeout=3)
        store.repository.upsert_session_runtime_state("selected", {"conversation_id": "selected"}, activate=True).result(timeout=3)
        current = copy.deepcopy(old)
        if case in {"same-fields", "legacy"}: current["displayName"] = "different non-exported configuration"
        elif case != "same-revision":
            current = copy.deepcopy(env.current_snapshot["config"])
        current_id = pinned
        if case != "same-revision":
            current_id = store.repository.import_agent_config_snapshots([{"agent_id": "agent-a", "display_name": "B",
                "kind": "persistent", "status": "active", "config": current, "source": "test"}]).result(timeout=3)[0]["configRevisionId"]
        if case == "wrong-actor":
            other = store.repository.create_agent(agent_id="other", display_name="Other", kind="persistent",
                config=current, source="test").result(timeout=3)["configRevisionId"]
        if case in {"missing-current", "missing-pin", "corrupt-current", "wrong-actor"}:
            with sqlite3.connect(path) as db:
                if case == "missing-current": db.execute("UPDATE agents SET current_config_revision_id=NULL WHERE agent_id='agent-a'")
                elif case == "missing-pin": db.execute("UPDATE sessions SET agent_config_revision_id=? WHERE session_id='session-a'", ("agent-a:" + "f" * 64,))
                elif case == "wrong-actor": db.execute("UPDATE agents SET current_config_revision_id=? WHERE agent_id='agent-a'", (other,))
                else: db.execute("UPDATE agent_config_revisions SET config_json='[]' WHERE revision_id=?", (current_id,))
        if case == "team": env.team_index.write_text(json.dumps({"teams": [{"teamId": "private", "members": [{"agentId": "agent-a"}]}]}), encoding="utf-8")
        if case == "companion": (env.plugin_root / "binding.json").write_text('{"agentId":"agent-a","enabled":true}', encoding="utf-8")
        monkeypatch.setattr(env.directory_runtime, "get_open_directory_store", lambda: store)
        def forbidden(*_a, **_k): pytest.fail("comparison called writer, ensure or config bootstrap")
        for name in ("submit", "submit_maintenance"): monkeypatch.setattr(store.writer, name, forbidden)
        for name in ("get_config", "_ensure_session_conversation_record"): monkeypatch.setattr(env.sessions, name, forbidden)
        before = {f: f.read_bytes() for f in env.root.rglob("*") if f.is_file() and not f.name.endswith("-shm")}
        response = env.client.get(URL + "/config-comparison", headers=env.headers)
        valid = case in {"different", "same-revision", "same-fields", "legacy"}
        assert response.status_code == (200 if valid else 404), response.text
        if valid:
            value = response.json()
            assert value["pinned"]["agentConfigRevisionId"] == pinned
            assert value["current"]["agentConfigRevisionId"] == current_id
            assert value["sameRevision"] is (case == "same-revision")
            assert value["changedFields"] == (["modelId", "contextWindow"] if case == "different" else [])
            if case == "legacy": assert value["pinned"]["reasoningEffort"] == "low"
            assert "SECRET" not in response.text and "different non-exported" not in response.text
        elif case not in {"team", "companion", "missing-pin"}:
            # Current failures do not prevent a valid historical read.
            assert env.client.get(URL + "/config", headers=env.headers).status_code == 200
        assert store.repository.get_active_session_id() == "selected"
        assert before == {f: f.read_bytes() for f in env.root.rglob("*") if f.is_file() and not f.name.endswith("-shm")}
