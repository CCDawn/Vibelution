"""Dispatch-tracking read model: inbox scan, receipt pairing, and API shape."""

import json

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service as directory
from core.web.services import personal_assistant_dispatches_service as dispatches_service
from core.web.services import personal_assistant_service as service
from tests.test_personal_assistant_service import (
    finance_env as _finance_env,
)
from tests.test_personal_assistant_service import (
    personal_env as _personal_env,
)

finance_env = _finance_env
personal_env = _personal_env

ASSISTANT_ID = "assistant-agent"
TARGET_ID = "target-agent"
OTHER_ID = "other-agent"


def _agent_row(agent_id: str, *, is_assistant: bool = False) -> dict:
    # workspacePath must be the canonical private workspace for the agentId;
    # hydration migrates any other shape via legacyWorkspacePath and the scan
    # would then look in a directory the test never wrote to.
    row = {
        "agentId": agent_id,
        "displayName": agent_id,
        "status": "active",
        "workspacePath": f"workspace/agents/{agent_id}",
        "metadata": {},
    }
    if is_assistant:
        row["roleKey"] = service.ROLE
        row["primaryMode"] = "general"
        row["metadata"] = {"personalAssistantProfile": service.PROFILE}
    return row


def _seed_agents(personal_env, rows) -> None:
    state = directory.load_state()
    state["agents"] = rows
    directory.save_state(state)


def _write_inbox(personal_env, agent_id: str, rows) -> None:
    root = personal_env["root"]
    inbox = root / "workspace" / "agents" / agent_id / "events" / "agent_inbox_messages.jsonl"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    with open(inbox, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _dispatch_row(message_id: str, *, kind: str = "agent_message", status: str = "pending",
                  created_at: str = "2026-10-20T10:00:00+00:00", summary: str = "dispatch summary") -> dict:
    return {
        "eventId": f"event-{message_id}",
        "messageId": message_id,
        "threadId": f"thread-{message_id}",
        "kind": kind,
        "status": status,
        "sourceAgentId": ASSISTANT_ID,
        "sourceAgentName": "个人助理",
        "targetAgentId": TARGET_ID,
        "targetAgentName": "target",
        "targetSessionId": "target-session",
        "summary": summary,
        "createdAt": created_at,
        "metadata": {},
    }


def _receipt_row(message_id: str, *, reply_to: str = "", thread_id: str = "",
                 source_agent: str = TARGET_ID, created_at: str = "2026-10-20T11:00:00+00:00",
                 status: str = "pending", summary: str = "receipt summary") -> dict:
    return {
        "eventId": f"event-{message_id}",
        "messageId": message_id,
        "threadId": thread_id,
        "kind": "agent_inbox_message",
        "status": status,
        "sourceAgentId": source_agent,
        "sourceAgentName": source_agent,
        "targetAgentId": ASSISTANT_ID,
        "summary": summary,
        "createdAt": created_at,
        "metadata": {"replyToMessageId": reply_to} if reply_to else {},
    }


@pytest.fixture
def seeded(personal_env):
    _seed_agents(personal_env, [
        _agent_row(ASSISTANT_ID, is_assistant=True),
        _agent_row(TARGET_ID),
        _agent_row(OTHER_ID),
    ])
    return personal_env


def test_dispatches_pair_receipts_and_flag_unmatched(seeded):
    _write_inbox(seeded, TARGET_ID, [
        _dispatch_row("dispatch-1", status="consumed", created_at="2026-10-20T10:00:00+00:00"),
        # Auto-acknowledgements the assistant itself sent are not dispatches.
        _dispatch_row("dispatch-reply", kind="agent_inbox_reply", created_at="2026-10-20T09:00:00+00:00"),
    ])
    _write_inbox(seeded, ASSISTANT_ID, [
        # Explicit receipt without replyToMessageId pairs via thread+source.
        _receipt_row("receipt-thread", thread_id="thread-dispatch-1"),
        # Unrelated inbound message stays unmatched.
        _receipt_row("receipt-foreign", source_agent=OTHER_ID, created_at="2026-10-20T12:00:00+00:00"),
    ])

    payload = dispatches_service.list_personal_assistant_dispatches(limit=10)

    assert payload["assistantAgentId"] == ASSISTANT_ID
    assert [d["messageId"] for d in payload["dispatches"]] == ["dispatch-1"]
    dispatch = payload["dispatches"][0]
    assert dispatch["targetAgentId"] == TARGET_ID
    assert dispatch["deliveryStatus"] == "consumed"
    assert [r["messageId"] for r in dispatch["receipts"]] == ["receipt-thread"]
    assert [r["messageId"] for r in payload["unmatchedReceipts"]] == ["receipt-foreign"]


def test_dispatches_limit_keeps_newest_window(seeded):
    rows = [
        _dispatch_row(f"dispatch-{index:02d}", created_at=f"2026-10-20T10:{index:02d}:00+00:00")
        for index in range(5)
    ]
    _write_inbox(seeded, TARGET_ID, rows)

    payload = dispatches_service.list_personal_assistant_dispatches(limit=2)

    assert [d["messageId"] for d in payload["dispatches"]] == ["dispatch-04", "dispatch-03"]


def test_dispatches_missing_assistant_raises(personal_env):
    _seed_agents(personal_env, [
        _agent_row(OTHER_ID),
    ])
    with pytest.raises(dispatches_service.PersonalAssistantMissingError):
        dispatches_service.list_personal_assistant_dispatches()


@pytest.fixture
def client(personal_env):
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def test_dispatches_endpoint_returns_projection(client, seeded, monkeypatch):
    monkeypatch.setattr(
        dispatches_service,
        "list_personal_assistant_dispatches",
        lambda *, limit: {
            "assistantAgentId": ASSISTANT_ID,
            "dispatches": [{
                "messageId": "dispatch-1",
                "threadId": None,
                "targetAgentId": TARGET_ID,
                "targetAgentName": "target",
                "targetSessionId": "s",
                "summary": "sum",
                "deliveryStatus": "pending",
                "sentAt": "2026-10-20T10:00:00+00:00",
                "receipts": [],
            }],
            "unmatchedReceipts": [],
            "generatedAt": "2026-10-20T12:00:00+00:00",
        },
    )
    response = client.get("/api/personal-assistant/dispatches", params={"limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["assistantAgentId"] == ASSISTANT_ID
    assert body["dispatches"][0]["messageId"] == "dispatch-1"


def test_dispatches_endpoint_maps_missing_assistant_to_404(client, monkeypatch):
    def _raise(*, limit):
        raise dispatches_service.PersonalAssistantMissingError("missing")

    monkeypatch.setattr(dispatches_service, "list_personal_assistant_dispatches", _raise)
    response = client.get("/api/personal-assistant/dispatches")
    assert response.status_code == 404


def test_dispatches_endpoint_rejects_out_of_range_limit(client):
    assert client.get("/api/personal-assistant/dispatches", params={"limit": 0}).status_code == 422
    assert client.get("/api/personal-assistant/dispatches", params={"limit": 201}).status_code == 422
