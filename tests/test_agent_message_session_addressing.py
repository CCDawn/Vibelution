# -*- coding: utf-8 -*-
"""ADR 0002: agent collaboration lands on explicit target sessions."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools import agent_message_tools


def test_agent_message_tool_requires_target_session(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_message_tools,
        "agent_message_tool",
        agent_message_tools.agent_message_tool,
    )
    # Patch runtime via directory service imports inside the tool.
    import core.web.services.agent_directory_service as ads

    monkeypatch.setattr(ads, "current_agent_runtime", lambda: {"agentId": "agent-source", "sessionId": "session-source"})
    result = json.loads(agent_message_tools.agent_message_tool(content="hello"))
    assert result["ok"] is False
    assert result["error"] == "target_session_required"


def test_agent_message_tool_session_not_found(monkeypatch) -> None:
    import core.web.services.agent_directory_service as ads
    import core.web.services.session_service as session_service

    monkeypatch.setattr(ads, "current_agent_runtime", lambda: {"agentId": "agent-source", "sessionId": "session-source"})
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda *args, **kwargs: None,
    )
    result = json.loads(
        agent_message_tools.agent_message_tool(
            content="hello",
            target_session="session-missing",
        )
    )
    assert result["ok"] is False
    assert result["error"] == "session_not_found"


def test_agent_message_tool_session_agent_mismatch(monkeypatch) -> None:
    import core.web.services.agent_directory_service as ads
    import core.web.services.session_service as session_service

    monkeypatch.setattr(ads, "current_agent_runtime", lambda: {"agentId": "agent-source", "sessionId": "session-source"})
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda *args, **kwargs: {"id": "session-target", "agentId": "agent-owner"},
    )
    monkeypatch.setattr(
        ads,
        "list_agents",
        lambda include_archived=False: [
            {"agentId": "agent-other", "agentCode": "A099", "displayName": "Other"},
            {"agentId": "agent-owner", "agentCode": "A001", "displayName": "Owner"},
        ],
    )
    result = json.loads(
        agent_message_tools.agent_message_tool(
            content="hello",
            target_session="session-target",
            target_agent="A099",
        )
    )
    assert result["ok"] is False
    assert result["error"] == "session_agent_mismatch"


def test_agent_message_tool_delivers_with_target_session_metadata(monkeypatch) -> None:
    import core.web.services.agent_directory_service as ads
    import core.web.services.session_service as session_service

    monkeypatch.setattr(ads, "current_agent_runtime", lambda: {"agentId": "agent-source", "sessionId": "session-source"})
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda *args, **kwargs: {"id": "session-target", "agentId": "agent-target"},
    )
    monkeypatch.setattr(
        ads,
        "list_agents",
        lambda include_archived=False: [
            {"agentId": "agent-target", "agentCode": "A002", "displayName": "Target", "directSessionId": "session-direct"},
        ],
    )
    monkeypatch.setattr(
        ads,
        "get_agent",
        lambda agent_id, include_archived=False: {
            "agentId": agent_id,
            "agentCode": "A002" if agent_id == "agent-target" else "A001",
            "displayName": "Target" if agent_id == "agent-target" else "Source",
            "directSessionId": "session-direct" if agent_id == "agent-target" else "session-source",
            "metadata": {},
        },
    )

    captured: dict = {}

    def fake_submit(**kwargs):
        captured.update(kwargs)
        return {
            "outcome": {
                "deliveries": [
                    {
                        "targetAgentId": "agent-target",
                        "status": "delivered",
                        "inboxMessageId": "agentmsg-1",
                        "targetSessionId": "session-target",
                        "wake": {
                            "wakeRequested": True,
                            "wakeStatus": "started",
                            "messageId": "agentmsg-1",
                            "targetSessionId": "session-target",
                            "turnId": "turn-1",
                            "reason": "",
                        },
                    }
                ]
            },
            "event": {"eventId": "evt-1", "idempotencyKey": "k1"},
            "task": {"taskId": "task-1"},
            "execution": {"workRunId": "run-1"},
            "adapter": {"adapterVersion": "1", "eventId": "evt-1", "idempotencyKey": "k1"},
            "reused": False,
        }

    monkeypatch.setattr(
        "core.agent_kernel.adapters.submit_agent_message_event",
        fake_submit,
    )
    monkeypatch.setattr(agent_message_tools, "_try_send_research_org_message", lambda **kwargs: None)
    monkeypatch.setattr(agent_message_tools, "_record_agent_message_tool_event", lambda *a, **k: None)

    result = json.loads(
        agent_message_tools.agent_message_tool(
            content="please review",
            target_session="session-target",
            summary="review",
        )
    )
    assert result["ok"] is True
    assert result["status"] == "sent"
    assert result["targetSessionId"] == "session-target"
    assert result["targetAgentId"] == "agent-target"
    assert result["wakeStatus"] == "started"
    assert captured["metadata"]["targetSessionId"] == "session-target"
    assert captured["wake_target"] is True


def test_write_agent_inbox_message_respects_explicit_target_session(tmp_path, monkeypatch) -> None:
    from core.web.services.agent_directory import ops_residual

    agent = {
        "agentId": "agent-target",
        "agentCode": "A002",
        "displayName": "Target",
        "directSessionId": "session-direct",
        "workspacePath": str(tmp_path / "ws"),
    }
    (tmp_path / "ws" / "events").mkdir(parents=True)

    service = SimpleNamespace(
        get_agent=lambda agent_id, include_archived=False: agent if agent_id == "agent-target" else None,
        AgentNotFoundError=ValueError,
        AgentDirectoryError=ValueError,
        utc_now_iso=lambda: "2026-08-03T00:00:00+00:00",
        _new_event_id=lambda prefix: f"{prefix}-fixed",
        _agent_inbox_thread_id=lambda src, tgt: "thread-1",
        trim_lines=lambda text, max_lines=4: str(text or "")[:200],
        _safe_metadata=lambda metadata: dict(metadata or {}),
        _agent_workspace_event_path=lambda target_agent, name: tmp_path / "ws" / "events" / name,
        _append_jsonl=lambda path, payload: path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8"),
        _record_memory_event=lambda *a, **k: None,
        _resolve_project_path=lambda p: tmp_path / "ws",
    )
    monkeypatch.setattr(ops_residual, "_service", lambda: service)
    message = ops_residual.write_agent_inbox_message(
        "agent-target",
        content="hi",
        source_agent_id="",
        target_session_id="session-collab-tab",
    )
    assert message["targetSessionId"] == "session-collab-tab"
    assert message["messageId"] == "agentmsg-fixed"


def test_wake_prefers_persisted_target_session(monkeypatch) -> None:
    from core.web.services.session import agent_sessions

    calls: list[tuple] = []

    class FakeService:
        _AGENT_INBOX_WAKE_STATE_LOCK = __import__("threading").Lock()
        _AGENT_INBOX_WAKE_IN_FLIGHT_MESSAGE_IDS: set[str] = set()

        def get_agent(self, agent_id, include_archived=False):
            return {
                "agentId": "agent-target",
                "directSessionId": "session-direct",
                "metadata": {},
                "status": "active",
            }

        def get_session_detail(self, session_id, **kwargs):
            if session_id == "session-collab-tab":
                return {"id": session_id, "agentId": "agent-target"}
            return None

        def evaluate_delegation_wake_policy(self, policy, agent_id=""):
            return SimpleNamespace(allowed=True, reason="")

        def _is_session_running(self, session_id):
            return False

        def _format_agent_inbox_wake_prompt(self, message):
            return "wake-prompt"

        def submit_session_message(self, session_id, prompt, **kwargs):
            calls.append((session_id, prompt, kwargs))
            return {"startedTurnId": "turn-xyz"}

        def consume_agent_inbox_message(self, *a, **k):
            return {}

        def _record_agent_inbox_wake_event(self, *a, **k):
            return None

    monkeypatch.setattr(agent_sessions, "_service", lambda: FakeService())
    delivery = agent_sessions.wake_agent_for_inbox_message(
        {
            "messageId": "msg-1",
            "targetAgentId": "agent-target",
            "targetSessionId": "session-collab-tab",
            "content": "hello",
            "kind": "agent_direct_message",
        }
    )
    assert delivery["targetSessionId"] == "session-collab-tab"
    assert delivery["wakeStatus"] in {"started", "succeeded", "ok"} or calls
    assert calls and calls[0][0] == "session-collab-tab"
