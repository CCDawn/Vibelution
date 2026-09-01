from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.agent_plugins.virtual_human_life.delivery_plan import (
    DIALOGUE_BURST_VERSION,
)
from core.agent_plugins.virtual_human_life.mailbox import (
    claim_next_mailbox_entry,
    enqueue_mailbox_entry,
    normalize_mailbox,
)
from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService
from core.web.services import agent_directory_service
from core.web.services.virtual_human_life_service import (
    set_virtual_human_life_service_for_tests,
)
from tools.virtual_human_life_tools import virtual_human_dialogue_decision_v2_tool

UTC = timezone.utc


def _decision(
    *,
    act: str = "continue_dialogue",
    reason_code: str = "relevant_detail",
    topic_key: str = "shared-song",
    expects_user_reply: bool = False,
) -> dict[str, object]:
    return {
        "act": act,
        "reasonCode": reason_code,
        "topicKey": topic_key,
        "expectsUserReply": expects_user_reply,
        "referencedSourceKeys": [],
    }


def _service(
    tmp_path: Path,
    *,
    busy: list[bool],
    user_turns: list[str],
    continuation_payloads: list[dict],
    receipts: dict[str, str],
) -> VirtualHumanLifeService:
    agent = {
        "agentId": "agent-a",
        "status": "active",
        "directSessionId": "session-a",
    }

    def submit_user(**payload):
        user_turns.append(str(payload.get("content") or ""))
        return {
            "accepted": True,
            "turnId": f"turn-user-{len(user_turns)}",
            "status": "running",
        }

    def submit_continuation(**payload):
        continuation_payloads.append(dict(payload))
        return {
            "accepted": True,
            "turnId": f"turn-continuation-{len(continuation_payloads)}",
            "status": "running",
        }

    def resolve_receipt(_agent_id: str, identity: dict) -> dict | None:
        turn_id = str(identity.get("turnId") or identity.get("currentTurnId") or "")
        event_id = receipts.get(turn_id, "")
        if not event_id:
            return None
        return {"receiptEventId": event_id, "persistedAt": "2026-09-01T02:00:00Z"}

    service = VirtualHumanLifeService(
        project_root=tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        conversation_submitter=submit_user,
        proactive_submitter=submit_continuation,
        conversation_busy_provider=lambda _session_id: busy[0],
        delivery_receipt_resolver=resolve_receipt,
        auto_mailbox_dispatch=False,
        now_provider=lambda: datetime(2026, 9, 1, 2, 0, tzinfo=UTC),
    )
    service.set_binding(
        "agent-a",
        enabled=True,
        expected_version=0,
        config={"timezone": "Asia/Shanghai"},
    )
    return service


def _send(service: VirtualHumanLifeService, ordinal: int) -> dict:
    return service.queue_conversation_message(
        "agent-a",
        session_id="session-a",
        client_submission_id=f"submission-{ordinal}",
        content=f"用户消息 {ordinal}",
    )


def _plans(service: VirtualHumanLifeService) -> list[dict]:
    return service.store.read_jsonl("agent-a", "conversation/delivery_plans.jsonl")


def test_user_root_starts_v2_burst_without_precreating_future_message(
    tmp_path: Path,
) -> None:
    service = _service(
        tmp_path,
        busy=[False],
        user_turns=[],
        continuation_payloads=[],
        receipts={},
    )

    result = _send(service, 1)
    plan = _plans(service)[0]
    mailbox = service.store.read_json("agent-a", "conversation/mailbox.json") or {}

    assert result["turnId"] == "turn-user-1"
    assert plan["contractVersion"] == DIALOGUE_BURST_VERSION
    assert plan["status"] == "awaiting_terminal_receipt"
    assert plan["rootSourceKind"] == "user"
    assert plan["currentBubbleOrdinal"] == 1
    assert plan["currentTurnId"] == "turn-user-1"
    assert plan["deliveredCount"] == 0
    assert plan["decisionDraft"] is None
    assert not [
        item
        for item in mailbox.get("entries", [])
        if item.get("sourceKind") == "followup"
    ]
    assert "bubbleBudget" not in plan
    assert "followup" not in plan


def test_dialogue_decision_tool_binds_identity_from_current_companion_turn(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = _service(
        tmp_path,
        busy=[False],
        user_turns=[],
        continuation_payloads=[],
        receipts={},
    )
    _send(service, 1)
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {
            "agentId": "agent-a",
            "sessionId": "session-a",
            "turnId": "turn-user-1",
        },
    )
    set_virtual_human_life_service_for_tests(service)
    try:
        result = json.loads(
            virtual_human_dialogue_decision_v2_tool(
                act="continue_dialogue",
                reasonCode="relevant_detail",
                topicKey="shared-song",
                expectsUserReply=False,
                referencedSourceKeys=[],
            )
        )
    finally:
        set_virtual_human_life_service_for_tests(None)

    assert result == {
        "act": "continue_dialogue",
        "ok": True,
        "status": "draft_valid",
    }


def test_proactive_native_turn_starts_the_same_receipt_driven_v2_burst(
    tmp_path: Path,
) -> None:
    continuations: list[dict] = []
    service = _service(
        tmp_path,
        busy=[False],
        user_turns=[],
        continuation_payloads=continuations,
        receipts={},
    )
    attempt = {
        "agentId": "agent-a",
        "attemptId": "attempt-proactive-1",
        "triggerId": "trigger-proactive-1",
        "deliveryToken": "delivery-proactive-1",
        "bindingRevision": 1,
        "sessionId": "session-a",
        "reason": "想起一件事",
        "status": "reserved",
        "validUntil": "2026-09-01T02:05:00+00:00",
        "deliveryKind": "proactive",
        "localDate": "2026-09-01",
    }
    service.store.write_jsonl("agent-a", "proactive/deliveries.jsonl", [attempt])
    mailbox, _ = enqueue_mailbox_entry(
        normalize_mailbox(None),
        entry_id="proactive:delivery-proactive-1",
        session_id="session-a",
        source_kind="proactive",
        command=service.delivery_runtime._proactive_command(attempt),
        generation=1,
        now=datetime(2026, 9, 1, 2, 0, tzinfo=UTC),
    )
    service.store.write_json("agent-a", "conversation/mailbox.json", mailbox)

    result = service.dispatch_conversation_mailbox_once(
        "agent-a", session_id="session-a"
    )
    plan = _plans(service)[0]

    assert result["turnId"] == "turn-continuation-1"
    assert plan["rootSourceKind"] == "proactive"
    assert plan["currentTurnId"] == "turn-continuation-1"
    assert plan["status"] == "awaiting_terminal_receipt"


def test_terminal_receipts_drive_three_native_messages_then_await_user(
    tmp_path: Path,
) -> None:
    busy = [False]
    receipts: dict[str, str] = {}
    continuations: list[dict] = []
    service = _service(
        tmp_path,
        busy=busy,
        user_turns=[],
        continuation_payloads=continuations,
        receipts=receipts,
    )
    _send(service, 1)

    service.record_dialogue_decision_v2(
        "agent-a",
        session_id="session-a",
        turn_id="turn-user-1",
        model_decision=_decision(),
        tool_call_id="call-root",
    )
    receipts["turn-user-1"] = "assistant-root"
    reconciled = service.reconcile_dialogue_bursts("agent-a", session_id="session-a")
    assert reconciled["queuedContinuationEntryIds"]

    first = service.dispatch_conversation_mailbox_once(
        "agent-a", session_id="session-a"
    )
    assert first["sourceKind"] == "followup"
    assert first["turnId"] == "turn-continuation-1"
    assert continuations[0]["trigger"]["deliveryKind"] == "burst_continuation"
    assert continuations[0]["trigger"]["bubbleOrdinal"] == 2

    service.record_dialogue_decision_v2(
        "agent-a",
        session_id="session-a",
        turn_id="turn-continuation-1",
        model_decision=_decision(topic_key="song-detail"),
        tool_call_id="call-cont-1",
    )
    receipts["turn-continuation-1"] = "assistant-cont-1"
    service.record_delivery_receipt(
        "agent-a",
        delivery_token=str(first["deliveryToken"]),
        turn_id="turn-continuation-1",
        receipt_event_id="assistant-cont-1",
    )

    second = service.dispatch_conversation_mailbox_once(
        "agent-a", session_id="session-a"
    )
    assert second["turnId"] == "turn-continuation-2"
    assert continuations[1]["trigger"]["bubbleOrdinal"] == 3

    service.record_dialogue_decision_v2(
        "agent-a",
        session_id="session-a",
        turn_id="turn-continuation-2",
        model_decision=_decision(
            act="ask_user",
            reason_code="natural_question",
            topic_key="favorite-song",
            expects_user_reply=True,
        ),
        tool_call_id="call-cont-2",
    )
    receipts["turn-continuation-2"] = "assistant-cont-2"
    service.record_delivery_receipt(
        "agent-a",
        delivery_token=str(second["deliveryToken"]),
        turn_id="turn-continuation-2",
        receipt_event_id="assistant-cont-2",
    )

    plan = _plans(service)[0]
    assert plan["status"] == "await_user"
    assert plan["deliveredCount"] == 3
    assert plan["questionCount"] == 1
    assert plan["stopReason"] == "await_user"
    assert service.dispatch_conversation_mailbox_once(
        "agent-a", session_id="session-a"
    )["reason"] == "empty"


def test_user_interjection_cancels_not_admitted_continuation(tmp_path: Path) -> None:
    busy = [False]
    receipts: dict[str, str] = {}
    service = _service(
        tmp_path,
        busy=busy,
        user_turns=[],
        continuation_payloads=[],
        receipts=receipts,
    )
    _send(service, 1)
    service.record_dialogue_decision_v2(
        "agent-a",
        session_id="session-a",
        turn_id="turn-user-1",
        model_decision=_decision(),
        tool_call_id="call-root",
    )
    receipts["turn-user-1"] = "assistant-root"
    service.reconcile_dialogue_bursts("agent-a", session_id="session-a")

    busy[0] = True
    queued_user = _send(service, 2)
    mailbox = service.store.read_json("agent-a", "conversation/mailbox.json") or {}
    first_plan = _plans(service)[0]
    continuation = next(
        item
        for item in mailbox["entries"]
        if item["sourceKind"] == "followup"
        and item.get("deliveryPlanId") == first_plan["planId"]
    )

    assert queued_user["queued"] is True
    assert continuation["state"] == "cancelled"
    assert continuation["cancelReason"] == "user_interjected"
    assert first_plan["status"] == "cancelled"
    assert first_plan["stopReason"] == "user_interjected"


def test_repeated_receipt_does_not_increment_delivered_count_twice(tmp_path: Path) -> None:
    receipts: dict[str, str] = {}
    service = _service(
        tmp_path,
        busy=[False],
        user_turns=[],
        continuation_payloads=[],
        receipts=receipts,
    )
    _send(service, 1)
    service.record_dialogue_decision_v2(
        "agent-a",
        session_id="session-a",
        turn_id="turn-user-1",
        model_decision=_decision(act="stop", reason_code="complete", topic_key=""),
        tool_call_id="call-stop",
    )
    receipts["turn-user-1"] = "assistant-root"

    first = service.reconcile_dialogue_bursts("agent-a", session_id="session-a")
    second = service.reconcile_dialogue_bursts("agent-a", session_id="session-a")

    assert first["completedPlanIds"]
    assert second["completedPlanIds"] == []
    assert _plans(service)[0]["deliveredCount"] == 1


def test_delivered_continuation_receipt_replay_recovers_plan_advancement(
    tmp_path: Path,
) -> None:
    receipts: dict[str, str] = {}
    service = _service(
        tmp_path,
        busy=[False],
        user_turns=[],
        continuation_payloads=[],
        receipts=receipts,
    )
    _send(service, 1)
    service.record_dialogue_decision_v2(
        "agent-a",
        session_id="session-a",
        turn_id="turn-user-1",
        model_decision=_decision(),
        tool_call_id="call-root",
    )
    receipts["turn-user-1"] = "assistant-root"
    service.reconcile_dialogue_bursts("agent-a", session_id="session-a")
    first = service.dispatch_conversation_mailbox_once(
        "agent-a", session_id="session-a"
    )
    service.record_dialogue_decision_v2(
        "agent-a",
        session_id="session-a",
        turn_id=str(first["turnId"]),
        model_decision=_decision(topic_key="next-detail"),
        tool_call_id="call-continuation",
    )
    rows = service.store.read_jsonl("agent-a", "proactive/deliveries.jsonl")
    for row in rows:
        if row.get("deliveryToken") == first["deliveryToken"]:
            row.update(
                {
                    "status": "delivered",
                    "turnId": first["turnId"],
                    "receiptEventId": "assistant-continuation",
                    "deliveredAt": "2026-09-01T02:00:00+00:00",
                }
            )
    service.store.write_jsonl("agent-a", "proactive/deliveries.jsonl", rows)

    service.record_delivery_receipt(
        "agent-a",
        delivery_token=str(first["deliveryToken"]),
        turn_id=str(first["turnId"]),
        receipt_event_id="assistant-continuation",
    )
    mailbox = service.store.read_json("agent-a", "conversation/mailbox.json") or {}
    queued = [
        item
        for item in mailbox.get("entries", [])
        if item.get("sourceKind") == "followup" and item.get("state") == "queued"
    ]

    assert len(queued) == 1
    assert queued[0]["bubbleOrdinal"] == 3
    assert _plans(service)[0]["deliveredCount"] == 2


def test_eighth_message_is_delivered_but_ninth_is_blocked_by_hard_guard(
    tmp_path: Path,
) -> None:
    receipts: dict[str, str] = {}
    payloads: list[dict] = []
    service = _service(
        tmp_path,
        busy=[False],
        user_turns=[],
        continuation_payloads=payloads,
        receipts=receipts,
    )
    _send(service, 1)
    current_turn_id = "turn-user-1"
    current_delivery_token = ""

    for ordinal in range(1, 9):
        service.record_dialogue_decision_v2(
            "agent-a",
            session_id="session-a",
            turn_id=current_turn_id,
            model_decision=_decision(topic_key=f"detail-{ordinal}"),
            tool_call_id=f"call-{ordinal}",
        )
        receipt_event_id = f"assistant-{ordinal}"
        receipts[current_turn_id] = receipt_event_id
        if ordinal == 1:
            service.reconcile_dialogue_bursts("agent-a", session_id="session-a")
        else:
            service.record_delivery_receipt(
                "agent-a",
                delivery_token=current_delivery_token,
                turn_id=current_turn_id,
                receipt_event_id=receipt_event_id,
            )
        if ordinal < 8:
            dispatched = service.dispatch_conversation_mailbox_once(
                "agent-a", session_id="session-a"
            )
            current_turn_id = str(dispatched["turnId"])
            current_delivery_token = str(dispatched["deliveryToken"])

    plan = _plans(service)[0]
    mailbox = service.store.read_json("agent-a", "conversation/mailbox.json") or {}

    assert plan["deliveredCount"] == 8
    assert plan["status"] == "completed"
    assert plan["stopReason"] == "hard_guard"
    assert len(payloads) == 7
    assert not [item for item in mailbox.get("entries", []) if item["state"] == "queued"]


def test_mailbox_prioritizes_arrived_user_then_proactive_then_followup() -> None:
    now = datetime(2026, 9, 1, 2, 0, tzinfo=UTC)
    mailbox = normalize_mailbox(None)
    mailbox, _ = enqueue_mailbox_entry(
        mailbox,
        entry_id="continuation-1",
        session_id="session-a",
        source_kind="followup",
        command={
            "proactiveAttempt": {
                "delivery_token": "continuation-token",
                "trigger": {"deliveryKind": "burst_continuation"},
            }
        },
        generation=1,
        now=now,
    )
    mailbox, _ = enqueue_mailbox_entry(
        mailbox,
        entry_id="proactive-1",
        session_id="session-a",
        source_kind="proactive",
        command={"proactiveAttempt": {"delivery_token": "proactive-token"}},
        generation=1,
        now=now,
    )
    mailbox, _ = enqueue_mailbox_entry(
        mailbox,
        entry_id="user-1",
        session_id="session-a",
        source_kind="user",
        command={"content": "我插一句", "clientSubmissionId": "submission-1"},
        generation=2,
        now=now,
    )

    _, claimed = claim_next_mailbox_entry(
        mailbox,
        session_id="session-a",
        lease_owner="test",
        now=now,
        lease_seconds=30,
    )

    assert claimed is not None
    assert claimed["entryId"] == "user-1"
