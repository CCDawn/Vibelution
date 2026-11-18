"""Tests for the agent directory tool."""

from __future__ import annotations

import json

from tools import agent_directory_tools as mod

AGENTS = [
    {
        "agentId": "agent-1",
        "agentCode": "A001",
        "displayName": "会话 Agent",
        "status": "active",
        "roleKey": "session",
        "directSessionId": "session-1",
        "agentInboxPendingCount": 2,
    },
    {
        "agentId": "agent-2",
        "agentCode": "A002",
        "displayName": "研究 Agent",
        "status": "active",
        "roleKey": "research",
        "directSessionId": "session-2",
        "agentInboxPendingCount": 0,
    },
]

SESSIONS = [
    {
        "id": "session-1",
        "agentId": "agent-1",
        "title": "主线",
        "lastTurnStatus": "completed",
        "updatedAt": "2026-11-18T10:00:00Z",
    },
    {
        "id": "session-1b",
        "agentId": "agent-1",
        "title": "子线",
        "lastTurnStatus": "running",
        "updatedAt": "2026-11-18T11:00:00Z",
    },
    {
        "id": "session-2",
        "agentId": "agent-2",
        "title": "调研",
        "lastTurnStatus": "completed",
        "updatedAt": "2026-11-18T09:00:00Z",
    },
]


def test_directory_joins_agent_and_sessions(monkeypatch):
    monkeypatch.setattr(mod, "_load_agents", lambda: AGENTS)
    monkeypatch.setattr(mod, "_load_sessions", lambda: SESSIONS)

    payload = json.loads(mod.agent_directory_tool())

    assert payload["ok"] is True
    assert payload["totalAgents"] == 2
    assert payload["sessionsAvailable"] is True
    agent1 = next(agent for agent in payload["agents"] if agent["agentId"] == "agent-1")
    assert agent1["directSessionId"] == "session-1"
    assert agent1["inboxPendingCount"] == 2
    assert [session["sessionId"] for session in agent1["sessions"]] == ["session-1b", "session-1"]


def test_query_filters_by_code_case_insensitively(monkeypatch):
    monkeypatch.setattr(mod, "_load_agents", lambda: AGENTS)
    monkeypatch.setattr(mod, "_load_sessions", lambda: [])

    payload = json.loads(mod.agent_directory_tool(query="a002"))

    assert [agent["agentId"] for agent in payload["agents"]] == ["agent-2"]


def test_sessions_unavailable_is_reported_not_hidden(monkeypatch):
    monkeypatch.setattr(mod, "_load_agents", lambda: AGENTS)
    monkeypatch.setattr(mod, "_load_sessions", lambda: None)

    payload = json.loads(mod.agent_directory_tool())

    assert payload["ok"] is True
    assert payload["sessionsAvailable"] is False
    assert all(agent["sessions"] == [] for agent in payload["agents"])


def test_limit_is_bounded(monkeypatch):
    monkeypatch.setattr(mod, "_load_agents", lambda: AGENTS)
    monkeypatch.setattr(mod, "_load_sessions", lambda: [])

    assert json.loads(mod.agent_directory_tool(limit=0))["returned"] == 1
    assert json.loads(mod.agent_directory_tool(limit=999))["returned"] == 2


def test_sessions_per_agent_zero_skips_session_read(monkeypatch):
    monkeypatch.setattr(mod, "_load_agents", lambda: AGENTS)

    def fail():
        raise AssertionError("sessions must not be read when sessions_per_agent is 0")

    monkeypatch.setattr(mod, "_load_sessions", fail)

    payload = json.loads(mod.agent_directory_tool(sessions_per_agent=0))

    assert payload["sessionsAvailable"] is False


def test_agent_read_failure_is_reported(monkeypatch):
    def boom():
        raise RuntimeError("directory index down")

    monkeypatch.setattr(mod, "_load_agents", boom)

    payload = json.loads(mod.agent_directory_tool())

    assert payload["ok"] is False
    assert "agent_directory_unavailable" in payload["error"]
