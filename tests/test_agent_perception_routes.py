from __future__ import annotations

import copy
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import agents as agent_routes
from core.web.services.agent_perception.policy import default_agent_perception_policy


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})
_CONFIG_PATH = "/api/agents/agent-a/perception/configuration"


def _configuration() -> dict:
    policy = default_agent_perception_policy()
    return {
        "agentId": "agent-a",
        "agentUpdatedAt": "revision-1",
        "configured": False,
        "policy": policy,
        "sourceDecisions": [
            {
                "enforced": False,
                "allowed": None,
                "reason": "not_configured",
                "source": source,
                "trigger": "task",
                "mode": None,
                "scope": None,
            }
            for source in ("personal", "team", "knowledge", "projects")
        ],
        "policyFingerprint": "",
        "availableScopes": {"teams": [], "knowledgeBases": []},
    }


def test_configuration_route_returns_typed_scopes(monkeypatch):
    monkeypatch.setattr(agent_routes, "get_agent_perception_configuration", lambda _agent_id: _configuration())
    response = client.get(_CONFIG_PATH)
    assert response.status_code == 200
    assert response.json()["availableScopes"] == {"teams": [], "knowledgeBases": []}


def test_configuration_update_uses_cas_payload_and_typed_response(monkeypatch):
    calls = []

    def save(agent_id, policy, *, expected_agent_updated_at):
        calls.append((agent_id, policy, expected_agent_updated_at))
        return _configuration()

    monkeypatch.setattr(agent_routes, "save_agent_perception_configuration", save)
    response = client.put(
        _CONFIG_PATH,
        json={"policy": default_agent_perception_policy(), "expectedAgentUpdatedAt": "revision-1"},
    )
    assert response.status_code == 200
    assert calls[0][0] == "agent-a"
    assert calls[0][2] == "revision-1"
    assert response.json()["agentId"] == "agent-a"


def test_configuration_update_maps_revision_conflict_to_409(monkeypatch):
    def conflict(*_args, **_kwargs):
        raise agent_routes.AgentStateConflictError("Agent configuration changed")

    monkeypatch.setattr(agent_routes, "save_agent_perception_configuration", conflict)
    response = client.put(
        _CONFIG_PATH,
        json={"policy": default_agent_perception_policy(), "expectedAgentUpdatedAt": "stale"},
    )
    assert response.status_code == 409


def test_runtime_and_cancel_routes_return_typed_read_and_activity_projections(monkeypatch):
    run = {
        "runId": "run-1",
        "topicId": "topic-1",
        "status": "running",
        "sessionId": "session-1",
        "turnId": "turn-1",
        "startedAt": "2026-10-05T00:00:00Z",
        "finishedAt": None,
        "toolCallsUsed": 1,
        "sources": ["team"],
        "readCount": 1,
        "resultCount": 2,
        "inputTokensUsed": 64,
        "outputCharsUsed": 120,
    }
    runtime = {
        "schemaVersion": 1,
        "agentId": "agent-a",
        "enabled": True,
        "status": "running",
        "nextRunAt": "2026-10-05T01:00:00Z",
        "activeRun": run,
        "lastRun": run,
        "dailyBudget": {"date": "2026-10-05", "used": 1, "limit": 4, "remaining": 3},
        "notifications": {"unreadCount": 0, "totalCount": 0, "suppressedCount": 0, "items": []},
        "knowledgeScan": {"basesScanned": 0, "cursorCount": 0, "pendingCount": 0},
        "readableSources": [{"source": "team", "selectedCount": 1, "readableCount": 1}],
        "lastActivity": {
            "trigger": "background",
            "sources": ["team"],
            "readCount": 1,
            "resultCount": 2,
            "completedAt": "2026-10-05T00:00:00Z",
            "sessionId": "session-1",
            "turnId": "turn-1",
            "runId": "run-1",
        },
        "caps": {"maxCallsPerRun": 8, "maxInputTokensPerRun": 16000, "maxResultChars": 12000, "maxConcurrent": 1},
        "cancelAvailable": True,
        "updatedAt": "2026-10-05T00:00:00Z",
    }
    monkeypatch.setattr(agent_routes, "get_agent_perception_runtime", lambda _agent_id: runtime)
    response = client.get("/api/agents/agent-a/perception/runtime")
    assert response.status_code == 200
    assert response.json()["readableSources"][0]["source"] == "team"
    assert response.json()["lastActivity"]["runId"] == "run-1"

    monkeypatch.setattr(agent_routes, "cancel_agent_perception", lambda _agent_id, *, run_id: {
        "agentId": "agent-a", "runId": run_id or "", "status": "idle",
        "stopRequested": False, "cancelled": False, "reason": "no_active_run",
    })
    cancel = client.post("/api/agents/agent-a/perception/cancel", json={"runId": "run-1"})
    assert cancel.status_code == 200
    assert cancel.json()["runId"] == "run-1"


def test_perception_routes_reject_missing_control_token_and_opencode_session(monkeypatch):
    monkeypatch.setattr(agent_routes, "get_agent_perception_configuration", lambda _agent_id: _configuration())
    missing_token = TestClient(create_app()).get(_CONFIG_PATH)
    assert missing_token.status_code == 403

    forged_session = client.get(_CONFIG_PATH, headers={"X-OpenCode-Session": "untrusted-session"})
    assert forged_session.status_code == 403


def test_real_service_runtime_http_projection_save_close_and_cancel(monkeypatch, tmp_path):
    """Exercise the facade and runtime through HTTP, with only storage edges isolated."""
    from core.web.services import agent_directory_service, team_knowledge_service
    from core.web.services.agent_perception import runtime as perception_runtime
    from core.web.services.agent_perception import service as perception_service
    from core.web.services.agent_perception.policy import agent_perception_policy_fingerprint
    from core.web.services.agent_perception.store import AgentPerceptionStore, new_state

    policy = default_agent_perception_policy()
    policy["enabled"] = True
    policy["sources"]["personal"]["mode"] = "manual"
    policy["sources"]["team"].update({"mode": "auto", "teamIds": ["team-a"]})
    policy["sources"]["team"]["triggers"]["update"] = True
    policy["sources"]["knowledge"].update({
        "mode": "auto", "scope": "selected", "knowledgeBaseIds": ["team:team-a:kb"],
    })
    policy["sources"]["knowledge"]["triggers"]["task"] = True
    policy["sources"]["projects"]["mode"] = "auto"
    policy["sources"]["projects"]["triggers"]["task"] = True
    policy["background"].update({"enabled": True, "topics": ["agent controls"]})
    agent = {
        "agentId": "agent-a", "status": "active", "updatedAt": "revision-1",
        "configRevision": 1, "metadata": {"perceptionPolicy": copy.deepcopy(policy)},
    }

    class Directory:
        AgentNotFoundError = LookupError

        @staticmethod
        def get_agent(agent_id, include_archived=False):
            return copy.deepcopy(agent) if agent_id == "agent-a" else None

        @staticmethod
        def update_agent_instance(agent_id, *, metadata, expected_updated_at, allow_agent_perception_policy=False):
            assert agent_id == "agent-a"
            assert allow_agent_perception_policy is True
            if expected_updated_at != agent["updatedAt"]:
                raise agent_directory_service.AgentStateConflictError("stale Agent revision")
            agent["metadata"].update(copy.deepcopy(metadata))
            agent["updatedAt"] = "revision-2"
            agent["configRevision"] += 1
            return copy.deepcopy(agent)

        @staticmethod
        def resolve_memory_policy_for_agent(agent_id):
            return {"enabled": True, "readKnowledgeBaseIds": []}

        @staticmethod
        def list_current_episodic_events(agent_id, *, limit):
            return [{"episodeId": "episode-1", "text": "A current personal memory", "occurredAt": "2026-10-05T00:00:00Z"}][:limit]

    directory = Directory()
    monkeypatch.setattr(perception_service, "_directory", lambda: directory)
    monkeypatch.setattr(perception_service, "_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent_directory_service, "get_agent", directory.get_agent)
    monkeypatch.setattr(agent_directory_service, "update_agent_instance", directory.update_agent_instance)
    monkeypatch.setattr(agent_directory_service, "resolve_memory_policy_for_agent", directory.resolve_memory_policy_for_agent)
    monkeypatch.setattr(agent_directory_service, "list_current_episodic_events", directory.list_current_episodic_events)

    bases = [
        {"ownerType": "agent", "ownerId": "agent-a", "scopedKnowledgeBaseId": "agent:agent-a:private",
         "permissions": {"canRead": True}, "status": "active"},
        {"ownerType": "team", "ownerId": "team-a", "scopedKnowledgeBaseId": "team:team-a:kb",
         "permissions": {"canRead": True}, "status": "active", "teamName": "Team A", "displayName": "Team KB"},
    ]
    monkeypatch.setattr(team_knowledge_service, "list_knowledge_overview", lambda **_kwargs: {"knowledgeBases": bases})

    class NativeSession:
        @staticmethod
        def get_session_detail(session_id, *, message_limit, transcript_scope):
            assert session_id == "session-1"
            assert message_limit == 0 and transcript_scope == "none"
            return {"activeTurnId": "turn-1", "currentPhase": "running"}

        @staticmethod
        def request_stop_session_turn(session_id, *, expected_turn_id, cascade):
            assert session_id == "session-1" and expected_turn_id == "turn-1" and cascade is False
            return {"stopRequested": True}

    store = AgentPerceptionStore(path_resolver=lambda _agent: tmp_path / "perception-state.json")
    runtime = perception_runtime.AgentPerceptionRuntime(
        store=store,
        agent_loader=lambda agent_id: directory.get_agent(agent_id, include_archived=True),
        session_service=NativeSession(),
        clock=lambda: datetime(2026, 10, 5, 12, tzinfo=timezone.utc),
    )
    fingerprint = agent_perception_policy_fingerprint(policy)
    state = new_state("agent-a")
    state.update({
        "status": "running",
        "nextRunAt": "2026-10-05T13:00:00Z",
        "dailyRuns": {"2026-10-05": 1},
        "activeRun": {
            "runId": "run-1", "topicId": "topic-1", "status": "running",
            "sessionId": "session-1", "turnId": "turn-1", "startedAt": "2026-10-05T11:00:00Z",
            "finishedAt": None, "policyFingerprint": fingerprint, "toolCallsUsed": 2,
            "sourceReadCallsUsed": 3, "inputTokensUsed": 64, "outputCharsUsed": 120,
            "sources": ["team"], "readCount": 3, "resultCount": 4,
        },
        "lastRun": {
            "runId": "run-0", "topicId": "topic-1", "status": "completed",
            "sessionId": "session-0", "turnId": "turn-0", "startedAt": "2026-10-04T11:00:00Z",
            "finishedAt": "2026-10-04T11:01:00Z", "toolCallsUsed": 1,
            "sourceReadCallsUsed": 2, "inputTokensUsed": 32, "outputCharsUsed": 80,
            "sources": ["knowledge"], "readCount": 2, "resultCount": 1,
        },
        "lastActivity": {
            "trigger": "update", "sources": ["team"], "readCount": 1, "resultCount": 1,
            "completedAt": "2026-10-05T11:00:00Z", "sessionId": "session-1",
            "turnId": "turn-1", "runId": "run-1",
        },
        "updatedAt": "2026-10-05T11:00:00Z",
    })
    store.save(agent, state)
    monkeypatch.setattr(perception_runtime, "_get_default_runtime", lambda: runtime)

    initial = client.get("/api/agents/agent-a/perception/configuration")
    assert initial.status_code == 200
    assert initial.json()["schemaVersion"] == 1
    assert initial.json()["configurationRevision"] == 1

    projected = client.get("/api/agents/agent-a/perception/runtime")
    assert projected.status_code == 200, projected.text
    runtime_json = projected.json()
    assert runtime_json["activeRun"]["sourceReadCallsUsed"] == 3
    assert runtime_json["lastRun"]["sourceReadCallsUsed"] == 2
    assert runtime_json["lastActivity"]["trigger"] == "update"
    readable = {row["source"]: row for row in runtime_json["readableSources"]}
    assert readable["personal"]["readableCount"] == 1
    assert readable["personal"]["requiresUserRequest"] is True
    assert readable["team"]["triggers"]["update"] is True

    cancelled = client.post("/api/agents/agent-a/perception/cancel", json={"runId": "run-1"})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["stopRequested"] is True
    assert cancelled.json()["sessionId"] == "session-1"

    closed = default_agent_perception_policy()
    saved = client.put(
        _CONFIG_PATH,
        json={"policy": closed, "expectedAgentUpdatedAt": "revision-1"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["configured"] is True
    assert saved.json()["configurationRevision"] == 2
    assert saved.json()["policy"]["enabled"] is False

    after_close = client.get("/api/agents/agent-a/perception/runtime")
    assert after_close.status_code == 200, after_close.text
    assert all(row["readableCount"] == 0 for row in after_close.json()["readableSources"])


def test_real_agent_directory_http_configuration_cas_and_closed_runtime(tmp_path, monkeypatch):
    from tests.test_context_engine import _use_tmp_project_root
    from core.web.services import agent_directory_service

    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="感知控制 HTTP Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-perception-http",
    )
    agent_id = agent["agentId"]
    path = f"/api/agents/{agent_id}/perception/configuration"
    api = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    initial = api.get(path)
    assert initial.status_code == 200, initial.text
    initial_json = initial.json()
    assert initial_json["configured"] is False
    assert initial_json["configurationRevision"] == int(agent.get("configRevision") or 0)

    enabled = default_agent_perception_policy()
    enabled["enabled"] = True
    enabled["sources"]["personal"]["mode"] = "auto"
    enabled["sources"]["personal"]["triggers"]["task"] = True
    first_save = api.put(path, json={
        "policy": enabled,
        "expectedAgentUpdatedAt": initial_json["agentUpdatedAt"],
    })
    assert first_save.status_code == 200, first_save.text
    saved_json = first_save.json()
    assert saved_json["configured"] is True
    assert saved_json["policy"] == enabled

    readback = api.get(path)
    assert readback.status_code == 200, readback.text
    readback_json = readback.json()
    assert readback_json["policy"] == enabled
    assert readback_json["configurationRevision"] == saved_json["configurationRevision"]
    assert readback_json["agentUpdatedAt"] == saved_json["agentUpdatedAt"]

    stale_save = api.put(path, json={
        "policy": default_agent_perception_policy(),
        "expectedAgentUpdatedAt": initial_json["agentUpdatedAt"],
    })
    assert stale_save.status_code == 409, stale_save.text

    closed = default_agent_perception_policy()
    close_response = api.put(path, json={
        "policy": closed,
        "expectedAgentUpdatedAt": readback_json["agentUpdatedAt"],
    })
    assert close_response.status_code == 200, close_response.text
    assert close_response.json()["policy"]["enabled"] is False

    runtime_response = api.get(f"/api/agents/{agent_id}/perception/runtime")
    assert runtime_response.status_code == 200, runtime_response.text
    runtime_json = runtime_response.json()
    assert runtime_json["enabled"] is False
    assert all(row["readableCount"] == 0 for row in runtime_json["readableSources"])
