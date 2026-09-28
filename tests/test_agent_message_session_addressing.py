# -*- coding: utf-8 -*-
"""ADR 0002: agent collaboration lands on explicit target sessions."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools import agent_message_tools


def test_agent_message_tool_signature_requires_target_session() -> None:
    import inspect

    signature = inspect.signature(agent_message_tools.agent_message_tool)
    assert signature.parameters["content"].default is inspect.Parameter.empty
    assert signature.parameters["target_session"].default is inspect.Parameter.empty
    doc = agent_message_tools.agent_message_tool.__doc__ or ""
    assert "target_session" in doc
    assert "sessionReferences" in doc or "sessionId" in doc
    assert "session_reference_query_tool" in doc


def test_agent_message_tool_requires_target_session(monkeypatch) -> None:
    # Patch runtime via directory service imports inside the tool.
    import core.web.services.agent_directory_service as ads

    monkeypatch.setattr(ads, "current_agent_runtime", lambda: {"agentId": "agent-source", "sessionId": "session-source"})
    # Empty string still blocked by runtime guard (schema also marks param required).
    result = json.loads(agent_message_tools.agent_message_tool(content="hello", target_session=""))
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
        lambda *args, **kwargs: {"id": "session-target", "agentId": "agent-source"},
    )
    monkeypatch.setattr(
        ads,
        "list_agents",
        lambda include_archived=False: [
            {"agentId": "agent-source", "agentCode": "A001", "displayName": "Source", "directSessionId": "session-source"},
        ],
    )
    monkeypatch.setattr(
        ads,
        "get_agent",
        lambda agent_id, include_archived=False: {
            "agentId": agent_id,
            "agentCode": "A001",
            "displayName": "Source",
            "directSessionId": "session-source",
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
                        "targetAgentId": "agent-source",
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
    assert result["targetAgentId"] == "agent-source"
    assert result["wakeStatus"] == "started"
    assert captured["metadata"]["targetSessionId"] == "session-target"
    assert captured["wake_target"] is True


def test_agent_message_tool_blocks_cross_agent_without_authorized_research_route(monkeypatch) -> None:
    import core.web.services.agent_directory_service as ads
    from core.agent_kernel import adapters
    from core.web.services import session_service

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
            {"agentId": "agent-source", "agentCode": "A001", "displayName": "Source", "directSessionId": "session-source"},
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
    kernel_calls: list[dict] = []
    monkeypatch.setattr(adapters, "submit_agent_message_event", lambda **kwargs: kernel_calls.append(kwargs))
    monkeypatch.setattr(agent_message_tools, "_try_send_research_org_message", lambda **kwargs: None)
    monkeypatch.setattr(agent_message_tools, "_record_agent_message_tool_event", lambda *args, **kwargs: None)

    result = json.loads(
        agent_message_tools.agent_message_tool(
            content="please review",
            target_session="session-target",
            wake_target=True,
        )
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["route"] == "policy"
    assert result["error"] == "policy_blocked"
    assert result["reason"] == "cross_agent_policy_required"
    assert result["targetSessionId"] == "session-target"
    assert result["delivery"]["allowed"] is False
    assert result["delivery"]["wakeStatus"] == "blocked"
    assert kernel_calls == []


def test_agent_message_tool_allows_same_active_team(monkeypatch) -> None:
    import core.web.services.agent_directory_service as ads
    from core.web.services import session_service, team_service

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
            {"agentId": "agent-source", "agentCode": "A001", "displayName": "Source", "directSessionId": "session-source"},
            {"agentId": "agent-target", "agentCode": "A002", "displayName": "Target", "directSessionId": "session-target"},
        ],
    )
    monkeypatch.setattr(
        ads,
        "get_agent",
        lambda agent_id, include_archived=False: {
            "agentId": agent_id,
            "agentCode": "A002" if agent_id == "agent-target" else "A001",
            "displayName": "Target" if agent_id == "agent-target" else "Source",
            "directSessionId": "session-target" if agent_id == "agent-target" else "session-source",
            "metadata": {},
        },
    )
    recorded: list[dict] = []
    monkeypatch.setattr(
        team_service,
        "shared_active_team_for_agents",
        lambda source_agent_id, target_agent_id: {"teamId": "team-alpha", "name": "Alpha"},
    )
    monkeypatch.setattr(
        team_service,
        "record_team_member_message",
        lambda team_id, **kwargs: recorded.append({"teamId": team_id, **kwargs}) or {"teamId": team_id, **kwargs},
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
                        "inboxMessageId": "agentmsg-team-1",
                        "targetSessionId": "session-target",
                        "wake": {
                            "wakeRequested": True,
                            "wakeStatus": "started",
                            "messageId": "agentmsg-team-1",
                            "targetSessionId": "session-target",
                            "turnId": "turn-1",
                            "reason": "",
                        },
                    }
                ]
            },
            "event": {"eventId": "evt-team-1", "idempotencyKey": "k-team"},
            "task": {"taskId": "task-team-1"},
            "execution": {"workRunId": "run-team-1"},
            "adapter": {"adapterVersion": "1", "eventId": "evt-team-1", "idempotencyKey": "k-team"},
            "reused": False,
        }

    monkeypatch.setattr("core.agent_kernel.adapters.submit_agent_message_event", fake_submit)
    monkeypatch.setattr(agent_message_tools, "_try_send_research_org_message", lambda **kwargs: None)
    monkeypatch.setattr(agent_message_tools, "_record_agent_message_tool_event", lambda *a, **k: None)

    result = json.loads(
        agent_message_tools.agent_message_tool(
            content="full body must stay in session",
            target_session="session-target",
            summary="handoff note",
        )
    )
    assert result["ok"] is True
    assert result["route"] == "same_team"
    assert result["teamId"] == "team-alpha"
    assert result["targetSessionId"] == "session-target"
    assert captured["metadata"]["targetSessionId"] == "session-target"
    assert captured["wake_target"] is True
    assert recorded and recorded[0]["teamId"] == "team-alpha"
    assert recorded[0]["summary"] == "handoff note"
    assert "content" not in recorded[0]
    assert "full body must stay in session" not in json.dumps(recorded)


def _patch_cross_agent_same_team_runtime(monkeypatch, *, agent_metadata: dict):
    import core.web.services.agent_directory_service as ads
    from core.web.services import session_service, team_service

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
            {"agentId": "agent-source", "agentCode": "A001", "displayName": "Source", "directSessionId": "session-source"},
            {"agentId": "agent-target", "agentCode": "A002", "displayName": "Target", "directSessionId": "session-target"},
        ],
    )
    monkeypatch.setattr(
        ads,
        "get_agent",
        lambda agent_id, include_archived=False: {
            "agentId": agent_id,
            "agentCode": "A002" if agent_id == "agent-target" else "A001",
            "displayName": "Target" if agent_id == "agent-target" else "Source",
            "directSessionId": "session-target" if agent_id == "agent-target" else "session-source",
            "metadata": dict(agent_metadata),
        },
    )
    recorded: list[dict] = []
    monkeypatch.setattr(
        team_service,
        "shared_active_team_for_agents",
        lambda source_agent_id, target_agent_id: {"teamId": "team-alpha", "name": "Alpha"},
    )
    monkeypatch.setattr(
        team_service,
        "record_team_member_message",
        lambda team_id, **kwargs: recorded.append({"teamId": team_id, **kwargs}) or {"teamId": team_id, **kwargs},
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
                        "inboxMessageId": "agentmsg-team-org-1",
                        "targetSessionId": "session-target",
                        "wake": {
                            "wakeRequested": False,
                            "wakeStatus": "not_requested",
                            "messageId": "agentmsg-team-org-1",
                            "targetSessionId": "session-target",
                            "turnId": "",
                            "reason": "",
                        },
                    }
                ]
            },
            "event": {"eventId": "evt-team-org-1", "idempotencyKey": "k-team-org"},
            "task": {"taskId": "task-team-org-1"},
            "execution": {"workRunId": "run-team-org-1"},
            "adapter": {"adapterVersion": "1", "eventId": "evt-team-org-1", "idempotencyKey": "k-team-org"},
            "reused": False,
        }

    monkeypatch.setattr("core.agent_kernel.adapters.submit_agent_message_event", fake_submit)
    monkeypatch.setattr(agent_message_tools, "_record_agent_message_tool_event", lambda *a, **k: None)
    return captured, recorded


def test_plain_same_team_send_ignores_missing_research_org_intent(monkeypatch) -> None:
    from core.web.services import research_organization_service

    captured, recorded = _patch_cross_agent_same_team_runtime(
        monkeypatch,
        agent_metadata={"researchOrgRole": "member"},
    )
    monkeypatch.setattr(
        research_organization_service,
        "get_research_organization",
        lambda: {"agents": [{"agentId": "agent-source"}, {"agentId": "agent-target"}]},
    )
    monkeypatch.setattr(
        research_organization_service,
        "send_research_org_message",
        lambda payload: (_ for _ in ()).throw(AssertionError("research org send should not run")),
    )

    result = json.loads(
        agent_message_tools.agent_message_tool(
            content="peer handoff without org metadata",
            target_session="session-target",
            summary="peer note",
            wake_target=False,
        )
    )
    assert result["ok"] is True
    assert result["route"] == "same_team"
    assert result["teamId"] == "team-alpha"
    assert captured["wake_target"] is False
    assert recorded and recorded[0]["summary"] == "peer note"


def test_research_org_typed_message_without_intent_still_blocked_on_same_team(monkeypatch) -> None:
    from core.web.services import research_organization_service

    captured, recorded = _patch_cross_agent_same_team_runtime(
        monkeypatch,
        agent_metadata={"researchOrgRole": "member"},
    )
    monkeypatch.setattr(
        research_organization_service,
        "get_research_organization",
        lambda: {"agents": [{"agentId": "agent-source"}, {"agentId": "agent-target"}]},
    )
    org_sends: list[dict] = []
    monkeypatch.setattr(
        research_organization_service,
        "send_research_org_message",
        lambda payload: org_sends.append(payload) or payload,
    )

    result = json.loads(
        agent_message_tools.agent_message_tool(
            content="please review",
            target_session="session-target",
            summary="org task",
            metadata_json=json.dumps({"researchOrgMessageType": "task"}),
        )
    )
    assert result["ok"] is False
    assert result["route"] == "research_org"
    assert result["reason"] == "research_org_intent_required"
    assert captured == {}
    assert recorded == []
    assert org_sends == []


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
    written: list[dict] = []

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
        _append_jsonl=lambda path, payload: written.append(payload) or path.write_text(
            json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8"
        ),
        _record_memory_event=lambda *a, **k: None,
        _resolve_project_path=lambda p: tmp_path / "ws",
    )
    monkeypatch.setattr(ops_residual, "_service", lambda: service)
    full_body = "line1\nline2\nline3\nline4\nline5 full collab body"
    message = ops_residual.write_agent_inbox_message(
        "agent-target",
        content=full_body,
        summary="short preview",
        source_agent_id="",
        target_session_id="session-collab-tab",
        metadata={"ssot": "session", "bodyPreviewOnly": True},
    )
    assert message["targetSessionId"] == "session-collab-tab"
    assert message["messageId"] == "agentmsg-fixed"
    # SSOT: inbox must not keep full body when bodyPreviewOnly/ssot=session.
    assert message["content"] == "short preview"
    assert message["summary"] == "short preview"
    assert full_body not in message["content"]


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


# ---------------------------------------------------------------------------
# Kernel delivery historyStatus contract (ADR 0002 amended 2026-09-28):
# appended | pending | deferred | rejected; skipped_busy lands the full body on
# the busy session without waking and consumes the inbox row afterwards.
# ---------------------------------------------------------------------------


def _kernel_delivery_event(**overrides) -> dict:
    event = {
        "eventId": "evt-deliv-1",
        "recipients": ["agent-target"],
        "senderAgentId": "agent-source",
        "correlationId": "thread-deliv-1",
        "semanticPayload": {"semanticType": "agent.message", "payload": {"content": "full body"}},
        "deliveryPolicy": {"wakeTarget": True},
        "metadata": {"targetSessionId": "session-target"},
    }
    event.update(overrides)
    return event


def _kernel_delivery_task() -> dict:
    return {"taskId": "task-deliv-1", "goal": "deliver"}


def _patch_kernel_delivery(
    monkeypatch,
    *,
    wake: dict | None = None,
    wake_raises: Exception | None = None,
    append_result: dict | None = None,
    inbox_row: dict | None = None,
    promote_raises: Exception | None = None,
) -> SimpleNamespace:
    from core.agent_kernel import service as kernel_service
    import core.web.services.agent_directory_service as ads
    from core.web.services import session_service

    calls = SimpleNamespace(wake=[], append=[], consume=[], inbox=[], promote=[], scenes=[])

    monkeypatch.setattr(kernel_service, "_ensure_agent_directory_root", lambda: None)
    monkeypatch.setattr(kernel_service, "_ensure_session_root", lambda: None)
    monkeypatch.setattr(
        kernel_service,
        "record_runtime_scene_event",
        lambda *a, **k: calls.scenes.append({"args": a, "kwargs": k}),
    )

    def fake_write_inbox(agent_id, **kwargs):
        calls.inbox.append({"agentId": agent_id, **kwargs})
        if inbox_row is not None:
            return dict(inbox_row)
        return {"messageId": "agentmsg-k1", "targetSessionId": kwargs.get("target_session_id") or ""}

    monkeypatch.setattr(ads, "write_agent_inbox_message", fake_write_inbox)

    if promote_raises is not None:
        def fake_promote(*a, **k):
            calls.promote.append({"args": a, "kwargs": k})
            raise promote_raises
    else:
        def fake_promote(*a, **k):
            calls.promote.append({"args": a, "kwargs": k})
            return {}

    monkeypatch.setattr(ads, "promote_agent_inbox_message_body", fake_promote)

    def fake_consume(*a, **k):
        calls.consume.append({"args": a, "kwargs": k})
        return {}

    monkeypatch.setattr(ads, "consume_agent_inbox_message", fake_consume)

    if wake_raises is not None:
        def fake_wake(message):
            calls.wake.append(dict(message))
            raise wake_raises
    else:
        def fake_wake(message):
            calls.wake.append(dict(message))
            merged = {
                "wakeRequested": True,
                "messageId": "agentmsg-k1",
                "targetAgentId": "agent-target",
                "targetSessionId": "session-target",
                "turnId": "",
                "reason": "",
            }
            merged.update(wake or {})
            return merged

    monkeypatch.setattr(session_service, "wake_agent_for_inbox_message", fake_wake)

    def fake_append(**kwargs):
        calls.append.append(dict(kwargs))
        if append_result is not None:
            return dict(append_result)
        return {"historyStatus": "appended", "historyMessageId": str(kwargs.get("message_id") or "")}

    monkeypatch.setattr(kernel_service, "_append_collab_body_to_session", fake_append)
    return calls


@pytest.mark.parametrize(
    "wake_status,expected_history_status",
    [
        ("started", "appended"),
        ("started_consume_failed", "appended"),
        ("skipped_busy", "deferred"),
        ("skipped_in_flight", "deferred"),
        ("skipped_invalid_session", "rejected"),
        ("skipped_policy_blocked", "rejected"),
        ("failed", "pending"),
    ],
)
def test_kernel_wake_status_maps_to_history_status(monkeypatch, wake_status, expected_history_status) -> None:
    from core.agent_kernel import service as kernel_service

    calls = _patch_kernel_delivery(monkeypatch, wake={"wakeStatus": wake_status, "turnId": "turn-9"})
    deliveries = kernel_service._deliver_event_to_recipients(
        _kernel_delivery_event(), _kernel_delivery_task()
    )
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery["historyStatus"] == expected_history_status
    if wake_status != "skipped_busy":
        assert delivery["historyMessageId"] == "agentmsg-k1"
    # Only the wake path persists the body for these statuses; the kernel must
    # not double-land it through the busy/SSOT landing helper.
    assert calls.append == []


def test_kernel_skipped_busy_promotes_row_body_without_touching_session(monkeypatch) -> None:
    from core.agent_kernel import service as kernel_service

    calls = _patch_kernel_delivery(monkeypatch, wake={"wakeStatus": "skipped_busy", "reason": "session running"})
    deliveries = kernel_service._deliver_event_to_recipients(
        _kernel_delivery_event(), _kernel_delivery_task()
    )
    delivery = deliveries[0]
    assert delivery["historyStatus"] == "deferred"
    # Summary-only SSOT row is promoted to the full body so the idle drain
    # lands it verbatim after the busy session releases.
    assert len(calls.promote) == 1
    assert calls.promote[0]["args"][0] == "agent-target"
    assert calls.promote[0]["args"][1] == "agentmsg-k1"
    assert calls.promote[0]["kwargs"] == {"content": "full body"}
    # The busy session must not be mutated mid-turn, and the pending row must
    # survive to drive the drain wake.
    assert calls.append == []
    assert calls.consume == []


def test_kernel_skipped_busy_promote_failure_still_defers(monkeypatch) -> None:
    from core.agent_kernel import service as kernel_service

    calls = _patch_kernel_delivery(
        monkeypatch,
        wake={"wakeStatus": "skipped_busy"},
        promote_raises=RuntimeError("promote boom"),
    )
    deliveries = kernel_service._deliver_event_to_recipients(
        _kernel_delivery_event(), _kernel_delivery_task()
    )
    assert deliveries[0]["historyStatus"] == "deferred"
    assert len(calls.promote) == 1
    promote_scenes = [
        scene for scene in calls.scenes
        if "busy_promote_failed" in str(scene["kwargs"].get("message", ""))
    ]
    assert promote_scenes and promote_scenes[0]["kwargs"].get("outcome") == "drain_wakes_with_summary"


def test_kernel_skipped_busy_without_session_skips_promote(monkeypatch) -> None:
    from core.agent_kernel import service as kernel_service

    event = _kernel_delivery_event()
    event["metadata"] = {}
    calls = _patch_kernel_delivery(
        monkeypatch,
        wake={"wakeStatus": "skipped_busy", "targetSessionId": ""},
        inbox_row={"messageId": "agentmsg-k1"},
    )
    deliveries = kernel_service._deliver_event_to_recipients(event, _kernel_delivery_task())
    assert deliveries[0]["historyStatus"] == "deferred"
    # Non-SSOT rows already carry the full body; nothing to promote.
    assert calls.promote == []
    assert calls.append == []
    assert calls.consume == []


def test_kernel_wake_exception_maps_to_pending(monkeypatch) -> None:
    from core.agent_kernel import service as kernel_service

    calls = _patch_kernel_delivery(monkeypatch, wake_raises=RuntimeError("wake boom"))
    deliveries = kernel_service._deliver_event_to_recipients(
        _kernel_delivery_event(), _kernel_delivery_task()
    )
    delivery = deliveries[0]
    assert delivery["wake"]["wakeStatus"] == "failed"
    assert delivery["historyStatus"] == "pending"
    assert calls.append == []


def test_kernel_no_wake_lands_body_on_session_ssot(monkeypatch) -> None:
    from core.agent_kernel import service as kernel_service

    calls = _patch_kernel_delivery(
        monkeypatch,
        append_result={"historyStatus": "appended", "historyMessageId": "agentmsg-k1"},
    )
    event = _kernel_delivery_event(deliveryPolicy={"wakeTarget": False})
    deliveries = kernel_service._deliver_event_to_recipients(event, _kernel_delivery_task())
    delivery = deliveries[0]
    assert delivery["historyStatus"] == "appended"
    assert delivery["historyMessageId"] == "agentmsg-k1"
    assert len(calls.append) == 1
    assert calls.append[0]["content"] == "full body"
    assert calls.wake == []


# ---------------------------------------------------------------------------
# Tool-level receipt: flat historyStatus must mirror the kernel authority.
# ---------------------------------------------------------------------------


def test_agent_message_tool_flat_history_status_follows_kernel(monkeypatch) -> None:
    import core.web.services.agent_directory_service as ads
    import core.web.services.session_service as session_service

    monkeypatch.setattr(ads, "current_agent_runtime", lambda: {"agentId": "agent-source", "sessionId": "session-source"})
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda *args, **kwargs: {"id": "session-target", "agentId": "agent-source"},
    )
    monkeypatch.setattr(
        ads,
        "list_agents",
        lambda include_archived=False: [
            {"agentId": "agent-source", "agentCode": "A001", "displayName": "Source", "directSessionId": "session-source"},
        ],
    )
    monkeypatch.setattr(
        ads,
        "get_agent",
        lambda agent_id, include_archived=False: {
            "agentId": agent_id,
            "agentCode": "A001",
            "displayName": "Source",
            "directSessionId": "session-source",
            "metadata": {},
        },
    )

    def fake_submit(**kwargs):
        return {
            "outcome": {
                "deliveries": [
                    {
                        "targetAgentId": "agent-source",
                        "status": "delivered",
                        "inboxMessageId": "agentmsg-flat-1",
                        "targetSessionId": "session-target",
                        "historyStatus": "deferred",
                        "historyMessageId": "",
                        "wake": {
                            "wakeRequested": True,
                            "wakeStatus": "skipped_in_flight",
                            "messageId": "agentmsg-flat-1",
                            "targetSessionId": "session-target",
                            "turnId": "",
                            "reason": "duplicate wake in flight",
                        },
                    }
                ]
            },
            "event": {"eventId": "evt-flat-1", "idempotencyKey": "k-flat"},
            "task": {"taskId": "task-flat-1"},
            "execution": {"workRunId": "run-flat-1"},
            "adapter": {"adapterVersion": "1", "eventId": "evt-flat-1", "idempotencyKey": "k-flat"},
            "reused": False,
        }

    monkeypatch.setattr("core.agent_kernel.adapters.submit_agent_message_event", fake_submit)
    monkeypatch.setattr(agent_message_tools, "_try_send_research_org_message", lambda **kwargs: None)
    monkeypatch.setattr(agent_message_tools, "_record_agent_message_tool_event", lambda *a, **k: None)

    result = json.loads(
        agent_message_tools.agent_message_tool(
            content="in-flight follow-up",
            target_session="session-target",
            summary="follow-up",
        )
    )
    assert result["ok"] is True
    assert result["wakeStatus"] == "skipped_in_flight"
    # Kernel authority wins over the legacy sent+wake guess.
    assert result["historyStatus"] == "deferred"
    assert result["delivery"]["historyStatus"] == "deferred"


def test_agent_message_tool_flat_history_status_legacy_fallback(monkeypatch) -> None:
    import core.web.services.agent_directory_service as ads
    import core.web.services.session_service as session_service

    monkeypatch.setattr(ads, "current_agent_runtime", lambda: {"agentId": "agent-source", "sessionId": "session-source"})
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda *args, **kwargs: {"id": "session-target", "agentId": "agent-source"},
    )
    monkeypatch.setattr(
        ads,
        "list_agents",
        lambda include_archived=False: [
            {"agentId": "agent-source", "agentCode": "A001", "displayName": "Source", "directSessionId": "session-source"},
        ],
    )
    monkeypatch.setattr(
        ads,
        "get_agent",
        lambda agent_id, include_archived=False: {
            "agentId": agent_id,
            "agentCode": "A001",
            "displayName": "Source",
            "directSessionId": "session-source",
            "metadata": {},
        },
    )

    def fake_submit(**kwargs):
        return {
            "outcome": {
                "deliveries": [
                    {
                        # Legacy kernel shape: no historyStatus passthrough.
                        "targetAgentId": "agent-source",
                        "status": "delivered",
                        "inboxMessageId": "agentmsg-legacy-1",
                        "targetSessionId": "session-target",
                        "wake": {
                            "wakeRequested": True,
                            "wakeStatus": "started",
                            "messageId": "agentmsg-legacy-1",
                            "targetSessionId": "session-target",
                            "turnId": "turn-legacy",
                            "reason": "",
                        },
                    }
                ]
            },
            "event": {"eventId": "evt-legacy-1", "idempotencyKey": "k-legacy"},
            "task": {"taskId": "task-legacy-1"},
            "execution": {"workRunId": "run-legacy-1"},
            "adapter": {"adapterVersion": "1", "eventId": "evt-legacy-1", "idempotencyKey": "k-legacy"},
            "reused": False,
        }

    monkeypatch.setattr("core.agent_kernel.adapters.submit_agent_message_event", fake_submit)
    monkeypatch.setattr(agent_message_tools, "_try_send_research_org_message", lambda **kwargs: None)
    monkeypatch.setattr(agent_message_tools, "_record_agent_message_tool_event", lambda *a, **k: None)

    result = json.loads(
        agent_message_tools.agent_message_tool(
            content="legacy kernel",
            target_session="session-target",
            summary="legacy",
        )
    )
    assert result["ok"] is True
    assert result["historyStatus"] == "appended"


def test_agent_message_tool_same_team_flat_history_status_follows_kernel(monkeypatch) -> None:
    import core.web.services.agent_directory_service as ads
    from core.web.services import session_service, team_service

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
            {"agentId": "agent-source", "agentCode": "A001", "displayName": "Source", "directSessionId": "session-source"},
            {"agentId": "agent-target", "agentCode": "A002", "displayName": "Target", "directSessionId": "session-target"},
        ],
    )
    monkeypatch.setattr(
        ads,
        "get_agent",
        lambda agent_id, include_archived=False: {
            "agentId": agent_id,
            "agentCode": "A002" if agent_id == "agent-target" else "A001",
            "displayName": "Target" if agent_id == "agent-target" else "Source",
            "directSessionId": "session-target" if agent_id == "agent-target" else "session-source",
            "metadata": {},
        },
    )
    monkeypatch.setattr(
        team_service,
        "shared_active_team_for_agents",
        lambda source_agent_id, target_agent_id: {"teamId": "team-alpha", "name": "Alpha"},
    )
    monkeypatch.setattr(
        team_service,
        "record_team_member_message",
        lambda team_id, **kwargs: {"teamId": team_id, **kwargs},
    )

    def fake_submit(**kwargs):
        return {
            "outcome": {
                "deliveries": [
                    {
                        "targetAgentId": "agent-target",
                        "status": "delivered",
                        "inboxMessageId": "agentmsg-team-busy-1",
                        "targetSessionId": "session-target",
                        "historyStatus": "deferred",
                        "historyMessageId": "",
                        "wake": {
                            "wakeRequested": True,
                            "wakeStatus": "skipped_busy",
                            "messageId": "agentmsg-team-busy-1",
                            "targetSessionId": "session-target",
                            "turnId": "",
                            "reason": "session running",
                        },
                    }
                ]
            },
            "event": {"eventId": "evt-team-busy-1", "idempotencyKey": "k-team-busy"},
            "task": {"taskId": "task-team-busy-1"},
            "execution": {"workRunId": "run-team-busy-1"},
            "adapter": {"adapterVersion": "1", "eventId": "evt-team-busy-1", "idempotencyKey": "k-team-busy"},
            "reused": False,
        }

    monkeypatch.setattr("core.agent_kernel.adapters.submit_agent_message_event", fake_submit)
    monkeypatch.setattr(agent_message_tools, "_try_send_research_org_message", lambda **kwargs: None)
    monkeypatch.setattr(agent_message_tools, "_record_agent_message_tool_event", lambda *a, **k: None)

    result = json.loads(
        agent_message_tools.agent_message_tool(
            content="busy teammate handoff",
            target_session="session-target",
            summary="handoff",
        )
    )
    assert result["ok"] is True
    assert result["route"] == "same_team"
    assert result["wakeStatus"] == "skipped_busy"
    assert result["historyStatus"] == "deferred"
