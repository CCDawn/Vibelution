"""Dispatch-tracking read model: inbox scan, receipt pairing, and API shape."""

import json
from pathlib import Path

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


def test_followups_do_not_count_as_dispatches_or_make_thread_receipts_ambiguous(seeded):
    original = _dispatch_row("original")
    followup = _dispatch_row("followup", kind="pa_followup")
    followup["threadId"] = original["threadId"]
    followup["metadata"] = {"paFollowupOfMessageId": "original"}
    legacy_followup = {**followup, "messageId": "legacy-followup", "kind": "agent_message"}
    _write_inbox(seeded, TARGET_ID, [original, followup, legacy_followup])
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row("receipt", thread_id=original["threadId"]),
    ])

    payload = dispatches_service.list_personal_assistant_dispatches(limit=1)

    assert [row["messageId"] for row in payload["dispatches"]] == ["original"]
    assert [row["messageId"] for row in payload["dispatches"][0]["receipts"]] == ["receipt"]
    assert payload["unmatchedReceipts"] == []


def test_receipt_to_followup_belongs_to_original_dispatch_and_checks_sender(seeded):
    original = _dispatch_row("original")
    followup = _dispatch_row("followup", kind="pa_followup")
    followup["threadId"] = original["threadId"]
    followup["metadata"] = {"paFollowupOfMessageId": "original"}
    _write_inbox(seeded, TARGET_ID, [original, followup])
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row("receipt", reply_to="followup"),
        _receipt_row("wrong-sender", reply_to="followup", source_agent=OTHER_ID),
    ])

    payload = dispatches_service.list_personal_assistant_dispatches()

    assert [row["messageId"] for row in payload["dispatches"]] == ["original"]
    assert [row["messageId"] for row in payload["dispatches"][0]["receipts"]] == ["receipt"]
    assert [row["messageId"] for row in payload["unmatchedReceipts"]] == ["wrong-sender"]


@pytest.mark.parametrize("fault", ["duplicate", "wrong-thread", "foreign-inbox"])
def test_followup_receipt_requires_unique_authoritative_link(seeded, fault):
    original = _dispatch_row("original")
    followup = _dispatch_row("followup", kind="pa_followup")
    followup["threadId"] = original["threadId"] if fault != "wrong-thread" else "unrelated-thread"
    followup["metadata"] = {"paFollowupOfMessageId": "original"}
    rows = [original, followup] if fault != "foreign-inbox" else [original]
    if fault == "duplicate":
        rows.append(dict(followup))
    _write_inbox(seeded, TARGET_ID, rows)
    if fault == "foreign-inbox":
        _write_inbox(seeded, OTHER_ID, [followup])
    _write_inbox(seeded, ASSISTANT_ID, [_receipt_row("receipt", reply_to="followup")])

    payload = dispatches_service.list_personal_assistant_dispatches()

    assert payload["dispatches"][0]["receipts"] == []
    assert [row["messageId"] for row in payload["unmatchedReceipts"]] == ["receipt"]


def test_patrol_feedback_never_chases_followups_as_new_dispatches(seeded, monkeypatch):
    from datetime import datetime, timezone

    from core.web.services import personal_assistant_patrol_service as patrol

    original = _dispatch_row("original")
    inbox_rows = [original]
    _write_inbox(seeded, TARGET_ID, inbox_rows)
    _write_inbox(seeded, ASSISTANT_ID, [])
    now = datetime.fromisoformat("2026-10-20T11:00:00+00:00").timestamp()
    observed = now
    sent = []
    monkeypatch.delenv(patrol.PA_PATROL_ENABLED_ENV, raising=False)
    monkeypatch.delenv(patrol.PA_PATROL_WAKE_ENABLED_ENV, raising=False)
    monkeypatch.setattr(patrol, "_read_pa_pending_messages", lambda _agent_id: [])

    def submit(**kwargs):
        sent.append(kwargs)
        row = _dispatch_row(
            f"followup-{len(sent)}", kind=kwargs["metadata"]["inboxKind"],
            created_at=datetime.fromtimestamp(observed, tz=timezone.utc).isoformat(),
        )
        row["threadId"] = kwargs["correlation_id"]
        row["metadata"] = dict(kwargs["metadata"])
        inbox_rows.append(row)
        _write_inbox(seeded, TARGET_ID, inbox_rows)
        return {"ok": True}

    monkeypatch.setattr(patrol, "_submit_followup_event", submit)
    patrol.reset_personal_assistant_patrol_for_tests()
    try:
        for minutes in (0, 31, 62, 93):
            observed = now + minutes * 60
            patrol.patrol_once(now=observed)
        assert [call["idempotency_key"] for call in sent] == [
            "pa-followup:original:1", "pa-followup:original:2",
        ]
        assert [row["messageId"] for row in dispatches_service.list_personal_assistant_dispatches()["dispatches"]] == ["original"]
    finally:
        patrol.reset_personal_assistant_patrol_for_tests()


def test_dispatches_receipt_matching_prefers_explicit_id_and_requires_unique_fallback(seeded):
    dispatch_1 = _dispatch_row("dispatch-1", created_at="2026-10-20T10:00:00+00:00")
    dispatch_2 = _dispatch_row("dispatch-2", created_at="2026-10-20T10:01:00+00:00")
    dispatch_1["threadId"] = dispatch_2["threadId"] = "shared-thread"
    unique_dispatch = _dispatch_row("dispatch-unique", created_at="2026-10-20T10:02:00+00:00")
    unique_dispatch["threadId"] = "unique-thread"
    _write_inbox(seeded, TARGET_ID, [dispatch_1, dispatch_2, unique_dispatch])
    _write_inbox(seeded, ASSISTANT_ID, [
        # Explicit IDs must win over an earlier same-thread dispatch.
        _receipt_row("receipt-r2", reply_to="dispatch-2", thread_id="shared-thread"),
        # An explicit but unknown ID must not fall back to the matching thread.
        _receipt_row("receipt-unknown-explicit", reply_to="missing-dispatch", thread_id="shared-thread"),
        # An explicit match must still come from the dispatch target.
        _receipt_row("receipt-wrong-source", reply_to="dispatch-1", thread_id="shared-thread", source_agent=OTHER_ID),
        # Without an explicit ID, a single thread+source candidate remains valid.
        _receipt_row("receipt-unique-fallback", thread_id="unique-thread"),
        # Ambiguous thread+source candidates must not be guessed.
        _receipt_row("receipt-ambiguous-fallback", thread_id="shared-thread"),
    ])

    payload = dispatches_service.list_personal_assistant_dispatches(limit=10)
    by_id = {dispatch["messageId"]: dispatch for dispatch in payload["dispatches"]}

    assert [receipt["messageId"] for receipt in by_id["dispatch-2"]["receipts"]] == ["receipt-r2"]
    assert [receipt["messageId"] for receipt in by_id["dispatch-1"]["receipts"]] == []
    assert [receipt["messageId"] for receipt in by_id["dispatch-unique"]["receipts"]] == ["receipt-unique-fallback"]
    assert {receipt["messageId"] for receipt in payload["unmatchedReceipts"]} == {
        "receipt-unknown-explicit",
        "receipt-wrong-source",
        "receipt-ambiguous-fallback",
    }


def test_dispatches_thread_fallback_uses_authoritative_candidates_beyond_display_window(seeded):
    dispatch_1 = _dispatch_row("dispatch-1", created_at="2026-10-20T10:00:00+00:00")
    dispatch_2 = _dispatch_row("dispatch-2", created_at="2026-10-20T10:01:00+00:00")
    dispatch_1["threadId"] = dispatch_2["threadId"] = "shared-thread"
    _write_inbox(seeded, TARGET_ID, [dispatch_1, dispatch_2])
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row("receipt-ambiguous-window", thread_id="shared-thread"),
    ])

    payload = dispatches_service.list_personal_assistant_dispatches(limit=1)

    assert [dispatch["messageId"] for dispatch in payload["dispatches"]] == ["dispatch-2"]
    assert payload["dispatches"][0]["receipts"] == []
    assert [receipt["messageId"] for receipt in payload["unmatchedReceipts"]] == [
        "receipt-ambiguous-window",
    ]


def test_dispatches_thread_fallback_keeps_unique_candidate_outside_window_unmatched(seeded):
    older_target_dispatch = _dispatch_row("dispatch-target", created_at="2026-10-20T10:00:00+00:00")
    newer_other_dispatch = _dispatch_row("dispatch-other", created_at="2026-10-20T10:01:00+00:00")
    older_target_dispatch["threadId"] = newer_other_dispatch["threadId"] = "same-thread"
    newer_other_dispatch["targetAgentId"] = OTHER_ID
    _write_inbox(seeded, TARGET_ID, [older_target_dispatch])
    _write_inbox(seeded, OTHER_ID, [newer_other_dispatch])
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row("receipt-window-excluded", thread_id="same-thread"),
    ])

    payload = dispatches_service.list_personal_assistant_dispatches(limit=1)

    assert [dispatch["messageId"] for dispatch in payload["dispatches"]] == ["dispatch-other"]
    assert payload["dispatches"][0]["receipts"] == []
    assert [receipt["messageId"] for receipt in payload["unmatchedReceipts"]] == [
        "receipt-window-excluded",
    ]


def test_dispatches_thread_fallback_rejects_non_authoritative_target_inbox_row(seeded):
    foreign_inbox_dispatch = _dispatch_row("dispatch-foreign-inbox")
    foreign_inbox_dispatch["threadId"] = "orphan-thread"
    _write_inbox(seeded, TARGET_ID, [])
    _write_inbox(seeded, OTHER_ID, [foreign_inbox_dispatch])
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row("receipt-non-authoritative", thread_id="orphan-thread"),
    ])

    payload = dispatches_service.list_personal_assistant_dispatches(limit=10)

    assert payload["dispatches"][0]["receipts"] == []
    assert [receipt["messageId"] for receipt in payload["unmatchedReceipts"]] == [
        "receipt-non-authoritative",
    ]


def test_dispatches_thread_fallback_deduplicates_ids_but_rejects_duplicate_visible_rows(seeded):
    first_duplicate = _dispatch_row("dispatch-duplicate", created_at="2026-10-20T10:00:00+00:00")
    second_duplicate = _dispatch_row("dispatch-duplicate", created_at="2026-10-20T10:01:00+00:00")
    first_duplicate["threadId"] = second_duplicate["threadId"] = "duplicate-thread"
    _write_inbox(seeded, TARGET_ID, [first_duplicate, second_duplicate])
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row("receipt-duplicate-id", thread_id="duplicate-thread"),
    ])

    one_visible = dispatches_service.list_personal_assistant_dispatches(limit=1)
    assert [receipt["messageId"] for receipt in one_visible["dispatches"][0]["receipts"]] == [
        "receipt-duplicate-id",
    ]

    both_visible = dispatches_service.list_personal_assistant_dispatches(limit=2)
    assert all(dispatch["receipts"] == [] for dispatch in both_visible["dispatches"])
    assert [receipt["messageId"] for receipt in both_visible["unmatchedReceipts"]] == [
        "receipt-duplicate-id",
    ]


@pytest.mark.parametrize("failure", ["io", "malformed"])
def test_dispatches_thread_fallback_does_not_infer_uniqueness_from_partial_scan(seeded, monkeypatch, failure):
    dispatch = _dispatch_row("dispatch-partial")
    _write_inbox(seeded, TARGET_ID, [dispatch])
    _write_inbox(seeded, ASSISTANT_ID, [
        _receipt_row("receipt-partial", thread_id=dispatch["threadId"]),
    ])
    original_open = Path.open

    class InterruptedRead:
        def __init__(self, stream):
            self.stream = stream
            self.first = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def __iter__(self):
            return self

        def __next__(self):
            if self.first:
                self.first = False
                return next(self.stream)
            if failure == "io":
                raise OSError("inbox read interrupted")
            return "{malformed"

    def interrupted_open(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if mode == "r" and path.name == dispatches_service.INBOX_FILENAME and path.parent.parent.name == TARGET_ID:
            return InterruptedRead(stream)
        return stream

    monkeypatch.setattr(Path, "open", interrupted_open)
    payload = dispatches_service.list_personal_assistant_dispatches(limit=10)

    assert payload["dispatches"][0]["receipts"] == []
    assert [receipt["messageId"] for receipt in payload["unmatchedReceipts"]] == ["receipt-partial"]


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
