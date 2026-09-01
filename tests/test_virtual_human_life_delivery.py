from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.agent_plugins.virtual_human_life.delivery_plan import (
    DIALOGUE_BURST_VERSION,
    build_companion_delivery_plan,
)
from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService

UTC = timezone.utc


def _agent() -> dict[str, str]:
    return {
        "agentId": "agent-a",
        "status": "active",
        "directSessionId": "session-agent-a",
    }


def _service(
    tmp_path: Path,
    *,
    busy: list[bool],
    user_turns: list[str],
    followup_payloads: list[dict],
) -> VirtualHumanLifeService:
    agent = _agent()

    def submit_user(**payload):
        user_turns.append(str(payload.get("content") or ""))
        return {
            "accepted": True,
            "turnId": f"turn-user-{len(user_turns)}",
            "status": "running",
        }

    def submit_followup(**payload):
        followup_payloads.append(dict(payload))
        return {
            "accepted": True,
            "turnId": f"turn-followup-{len(followup_payloads)}",
            "status": "running",
        }

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
        proactive_submitter=submit_followup,
        conversation_busy_provider=lambda _session_id: busy[0],
        auto_mailbox_dispatch=False,
        now_provider=lambda: datetime(2026, 9, 1, 1, 30, tzinfo=UTC),
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
        session_id="session-agent-a",
        client_submission_id=f"submission-{ordinal}",
        content=f"第 {ordinal} 条普通消息",
    )


def _seed_legacy_followup(service: VirtualHumanLifeService) -> dict:
    mailbox = service.store.read_json("agent-a", "conversation/mailbox.json") or {}
    source = next(
        item
        for item in mailbox.get("entries", [])
        if item.get("entryId") == "user:submission-3"
    )
    binding = service.binding_for("agent-a") or {}
    return service.delivery_runtime.plan_user_response(
        "agent-a",
        session_id="session-agent-a",
        generation=int(source.get("generation") or 0),
        source_entry_id=str(source.get("entryId") or ""),
        source_turn_id=str(source.get("turnId") or ""),
        expression_decision={"followup": True, "questionBudget": 0},
        binding_revision=int(binding.get("bindingRevision") or 0),
        local_date="2026-09-01",
    )


def test_delivery_plan_is_stable_and_never_exceeds_two_bubbles() -> None:
    now = datetime(2026, 9, 1, 1, 30, tzinfo=UTC)
    first = build_companion_delivery_plan(
        session_id="session-a",
        generation=3,
        source_entry_id="user:submission-3",
        source_turn_id="turn-user-3",
        expression_decision={"followup": True, "questionBudget": 1},
        now=now,
    )
    repeated = build_companion_delivery_plan(
        session_id="session-a",
        generation=3,
        source_entry_id="user:submission-3",
        source_turn_id="turn-user-3",
        expression_decision={"followup": True, "questionBudget": 1},
        now=now,
    )

    assert first == repeated
    assert first["bubbleBudget"] == 2
    assert first["followup"]["bubbleIndex"] == 2
    assert first["followup"]["entryId"].startswith("followup:")
    assert first["followup"]["deliveryToken"]

    single = build_companion_delivery_plan(
        session_id="session-a",
        generation=4,
        source_entry_id="user:submission-4",
        source_turn_id="turn-user-4",
        expression_decision={"followup": False, "questionBudget": 0},
        now=now,
    )
    assert single["bubbleBudget"] == 1
    assert single["followup"] is None


def test_user_turn_uses_v2_without_precreating_a_fixed_followup(
    tmp_path: Path,
) -> None:
    busy = [False]
    user_turns: list[str] = []
    followup_payloads: list[dict] = []
    service = _service(
        tmp_path,
        busy=busy,
        user_turns=user_turns,
        followup_payloads=followup_payloads,
    )

    _send(service, 1)
    _send(service, 2)
    third = _send(service, 3)
    mailbox = service.store.read_json("agent-a", "conversation/mailbox.json") or {}
    followups = [
        item
        for item in mailbox.get("entries", [])
        if item.get("sourceKind") == "followup"
    ]

    assert third["turnId"] == "turn-user-3"
    assert followups == []
    assert followup_payloads == []
    assert len(user_turns) == 3
    plans = service.store.read_jsonl(
        "agent-a", "conversation/delivery_plans.jsonl"
    )
    assert plans[-1]["contractVersion"] == DIALOGUE_BURST_VERSION


def test_user_interjection_cancels_unsent_followup_and_preserves_arrival_order(
    tmp_path: Path,
) -> None:
    busy = [False]
    user_turns: list[str] = []
    followup_payloads: list[dict] = []
    service = _service(
        tmp_path,
        busy=busy,
        user_turns=user_turns,
        followup_payloads=followup_payloads,
    )
    _send(service, 1)
    _send(service, 2)
    _send(service, 3)
    _seed_legacy_followup(service)

    busy[0] = True
    fourth = _send(service, 4)
    mailbox = service.store.read_json("agent-a", "conversation/mailbox.json") or {}
    entries = list(mailbox.get("entries") or [])
    followup = next(item for item in entries if item.get("sourceKind") == "followup")
    user_four = next(
        item
        for item in entries
        if (item.get("command") or {}).get("clientSubmissionId") == "submission-4"
    )
    attempt = service.proactive_attempt(
        "agent-a",
        str(followup.get("deliveryToken") or followup.get("commandFingerprint") or ""),
    )

    assert fourth["queued"] is True
    assert followup["state"] == "cancelled"
    assert followup["cancelReason"] == "user_interjected"
    assert user_four["arrivalSequence"] > followup["arrivalSequence"]
    assert attempt is None or attempt["status"] == "cancelled"
    assert followup_payloads == []


def test_retrying_same_user_submission_does_not_duplicate_followup(
    tmp_path: Path,
) -> None:
    busy = [False]
    user_turns: list[str] = []
    followup_payloads: list[dict] = []
    service = _service(
        tmp_path,
        busy=busy,
        user_turns=user_turns,
        followup_payloads=followup_payloads,
    )
    _send(service, 1)
    _send(service, 2)
    _send(service, 3)
    _seed_legacy_followup(service)

    busy[0] = True
    repeated = _send(service, 3)
    mailbox = service.store.read_json("agent-a", "conversation/mailbox.json") or {}
    followups = [
        item
        for item in mailbox.get("entries", [])
        if item.get("sourceKind") == "followup"
    ]
    plans = service.store.read_jsonl("agent-a", "conversation/delivery_plans.jsonl")

    assert repeated["queueSequence"] == 3
    assert len(followups) == 1
    assert len(
        [item for item in plans if item.get("contractVersion") == "companion_delivery.v1"]
    ) == 1


def test_followup_receipt_closes_plan_without_using_proactive_quota(
    tmp_path: Path,
) -> None:
    busy = [False]
    service = _service(
        tmp_path,
        busy=busy,
        user_turns=[],
        followup_payloads=[],
    )
    _send(service, 1)
    _send(service, 2)
    _send(service, 3)
    _seed_legacy_followup(service)
    dispatched = service.dispatch_conversation_mailbox_once(
        "agent-a", session_id="session-agent-a"
    )

    receipt = service.record_delivery_receipt(
        "agent-a",
        delivery_token=str(dispatched["deliveryToken"]),
        turn_id=str(dispatched["turnId"]),
        receipt_event_id="assistant-receipt-1",
    )
    plans = service.store.read_jsonl("agent-a", "conversation/delivery_plans.jsonl")
    legacy_plan = next(
        item for item in plans if item.get("contractVersion") == "companion_delivery.v1"
    )

    assert receipt["deliveryKind"] == "followup"
    assert legacy_plan["status"] == "delivered"
    assert legacy_plan["receipt"]["receiptEventId"] == "assistant-receipt-1"
    assert service.proactive_usage("agent-a", "2026-09-01")["delivered"] == 0


def test_followup_attempt_is_recovered_from_mailbox_without_duplicate_turn(
    tmp_path: Path,
) -> None:
    busy = [False]
    followup_payloads: list[dict] = []
    service = _service(
        tmp_path,
        busy=busy,
        user_turns=[],
        followup_payloads=followup_payloads,
    )
    _send(service, 1)
    _send(service, 2)
    _send(service, 3)
    _seed_legacy_followup(service)
    service.store.write_jsonl("agent-a", "proactive/deliveries.jsonl", [])

    delivered = service.dispatch_conversation_mailbox_once(
        "agent-a", session_id="session-agent-a"
    )
    attempts = service.store.read_jsonl("agent-a", "proactive/deliveries.jsonl")

    assert delivered["sourceKind"] == "followup"
    assert delivered["turnId"] == "turn-followup-1"
    assert len(attempts) == 1
    assert attempts[0]["recoveredFromMailbox"] is True
    assert len(followup_payloads) == 1
