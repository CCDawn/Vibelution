"""Companion-only delivery runtime for receipt-driven native message bursts.

This ledger coordinates delivery identity and mailbox ordering only.  It stores
no assistant text and delegates every visible bubble to the native Session
proactive Turn path.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from .delivery_plan import (
    DIALOGUE_BURST_VERSION,
    build_companion_delivery_plan,
    build_conversation_burst_plan_v2,
    transition_delivery_plan,
    upsert_delivery_plan,
)
from .dialogue_decision_v2 import resolve_companion_dialogue_decision_calls_v2
from .mailbox import enqueue_mailbox_entry, normalize_mailbox
from .manifest import PLUGIN_ID
from .storage import VirtualHumanLifeStore

_PLANS_PATH = "conversation/delivery_plans.jsonl"
_ATTEMPTS_PATH = "proactive/deliveries.jsonl"
_MAILBOX_PATH = "conversation/mailbox.json"
_COMPANION_CONTINUATION_DELIVERY_KINDS = frozenset(
    {"followup", "burst_continuation"}
)


def is_companion_continuation_delivery_kind(value: object) -> bool:
    return str(value or "").strip() in _COMPANION_CONTINUATION_DELIVERY_KINDS


def companion_delivery_kind_from_entry(entry: Mapping[str, Any]) -> str:
    command = entry.get("command") if isinstance(entry.get("command"), Mapping) else {}
    payload = (
        command.get("proactiveAttempt")
        if isinstance(command.get("proactiveAttempt"), Mapping)
        else {}
    )
    trigger = payload.get("trigger") if isinstance(payload.get("trigger"), Mapping) else {}
    return str(trigger.get("deliveryKind") or "").strip()


def _iso(value: datetime) -> str:
    normalized = (
        value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    )
    return normalized.astimezone(timezone.utc).isoformat()


class CompanionDeliveryRuntime:
    """Persist and reconcile the Companion's second-bubble delivery identity."""

    def __init__(
        self,
        store: VirtualHumanLifeStore,
        *,
        now_provider: Callable[[], datetime],
    ) -> None:
        self.store = store
        self.now_provider = now_provider

    def start_dialogue_burst(
        self,
        agent_id: str,
        *,
        session_id: str,
        root_entry_id: str,
        root_source_kind: str,
        generation: int,
        binding_revision: int,
        root_turn_id: str,
    ) -> dict[str, Any]:
        proposed = build_conversation_burst_plan_v2(
            agent_id=agent_id,
            session_id=session_id,
            root_entry_id=root_entry_id,
            root_source_kind=root_source_kind,
            generation=generation,
            binding_revision=binding_revision,
            root_turn_id=root_turn_id,
            now=self.now_provider(),
        )
        rows, plan = upsert_delivery_plan(
            self.store.read_jsonl(agent_id, _PLANS_PATH), proposed
        )
        self.store.write_jsonl(agent_id, _PLANS_PATH, rows)
        return plan

    def record_dialogue_decision_draft(
        self,
        agent_id: str,
        *,
        session_id: str,
        turn_id: str,
        generation: int,
        binding_revision: int,
        tool_call_id: str,
        model_decision: Mapping[str, Any],
        allowed_source_keys: list[str],
    ) -> dict[str, Any]:
        rows = self.store.read_jsonl(agent_id, _PLANS_PATH)
        plan = next(
            (
                item
                for item in reversed(rows)
                if str(item.get("contractVersion") or "") == DIALOGUE_BURST_VERSION
                and str(item.get("sessionId") or "") == str(session_id or "").strip()
                and str(item.get("currentTurnId") or "") == str(turn_id or "").strip()
                and str(item.get("status") or "")
                in {"running", "awaiting_terminal_receipt"}
            ),
            None,
        )
        if plan is None:
            raise ValueError("Companion dialogue burst for this Turn does not exist.")
        if int(plan.get("generation") or 0) != int(generation) or int(
            plan.get("bindingRevision") or 0
        ) != int(binding_revision):
            raise ValueError("Companion dialogue decision fence is stale.")

        calls: list[dict[str, Any]] = []
        existing = plan.get("decisionDraft")
        if isinstance(existing, Mapping):
            calls.append(
                {
                    "toolCallId": str(existing.get("toolCallId") or ""),
                    "arguments": {
                        "act": existing.get("act"),
                        "reasonCode": existing.get("reasonCode"),
                        "topicKey": existing.get("topicKey"),
                        "expectsUserReply": existing.get("expectsUserReply"),
                        "referencedSourceKeys": list(
                            existing.get("referencedSourceKeys") or []
                        ),
                    },
                }
            )
        calls.append(
            {
                "toolCallId": str(tool_call_id or "").strip(),
                "arguments": dict(model_decision),
            }
        )
        if str(plan.get("decisionDraftStatus") or "") in {"invalid", "conflict"}:
            resolution = {
                "status": str(plan.get("decisionDraftStatus") or "invalid"),
                "stopReason": str(
                    plan.get("decisionDraftStopReason") or "invalid_decision"
                ),
                "draft": None,
                "acceptedToolCallIds": list(plan.get("decisionToolCallIds") or []),
            }
        else:
            resolution = resolve_companion_dialogue_decision_calls_v2(
                calls=calls,
                system_context={
                    "agentId": str(agent_id).strip(),
                    "sessionId": str(session_id).strip(),
                    "turnId": str(turn_id).strip(),
                    "generation": int(generation),
                    "bindingRevision": int(binding_revision),
                },
                allowed_source_keys=allowed_source_keys,
            )
        plan["decisionDraft"] = deepcopy(resolution.get("draft"))
        plan["decisionDraftStatus"] = str(resolution.get("status") or "invalid")
        plan["decisionDraftStopReason"] = str(
            resolution.get("stopReason") or ""
        )
        plan["decisionToolCallIds"] = list(
            resolution.get("acceptedToolCallIds") or []
        )
        plan["updatedAt"] = _iso(self.now_provider())
        plan["version"] = int(plan.get("version") or 0) + 1
        self.store.write_jsonl(agent_id, _PLANS_PATH, rows)
        return deepcopy(plan)

    def reconcile_dialogue_burst_receipt(
        self,
        agent_id: str,
        *,
        plan_id: str,
        receipt_event_id: str,
        current_generation: int,
        binding_revision: int,
        local_date: str,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        rows = self.store.read_jsonl(agent_id, _PLANS_PATH)
        plan = next(
            (
                item
                for item in rows
                if str(item.get("planId") or "") == str(plan_id or "").strip()
                and str(item.get("contractVersion") or "") == DIALOGUE_BURST_VERSION
            ),
            None,
        )
        if plan is None:
            raise ValueError("Companion dialogue burst does not exist.")
        terminal_statuses = {"await_user", "completed", "cancelled", "failed", "expired"}
        normalized_receipt = str(receipt_event_id or "").strip()
        if not normalized_receipt:
            raise ValueError("Companion dialogue burst requires an assistant receipt.")
        processed_receipts = [
            str(item).strip()
            for item in list(plan.get("assistantReceiptEventIds") or [])
            if str(item).strip()
        ]
        if normalized_receipt in processed_receipts or str(
            plan.get("status") or ""
        ) in terminal_statuses:
            return deepcopy(plan), None
        if int(plan.get("generation") or 0) != int(current_generation):
            self._finish_v2_plan(plan, status="cancelled", stop_reason="user_interjected")
            self.store.write_jsonl(agent_id, _PLANS_PATH, rows)
            return deepcopy(plan), None
        if int(plan.get("bindingRevision") or 0) != int(binding_revision):
            self._finish_v2_plan(plan, status="cancelled", stop_reason="binding_changed")
            self.store.write_jsonl(agent_id, _PLANS_PATH, rows)
            return deepcopy(plan), None

        plan["latestAssistantReceiptEventId"] = normalized_receipt
        plan["assistantReceiptEventIds"] = [*processed_receipts, normalized_receipt][
            -8:
        ]
        plan["latestDeliveryReceiptId"] = normalized_receipt
        plan["deliveredCount"] = int(plan.get("deliveredCount") or 0) + 1
        draft = plan.get("decisionDraft")
        draft_status = str(plan.get("decisionDraftStatus") or "missing")
        effective_act = (
            str(draft.get("act") or "stop")
            if draft_status == "draft_valid" and isinstance(draft, Mapping)
            else "stop"
        )
        plan["nextAct"] = effective_act
        if effective_act == "ask_user":
            plan["questionCount"] = int(plan.get("questionCount") or 0) + 1
            self._finish_v2_plan(plan, status="await_user", stop_reason="await_user")
            self.store.write_jsonl(agent_id, _PLANS_PATH, rows)
            return deepcopy(plan), None
        if effective_act != "continue_dialogue":
            stop_reason = (
                "natural_stop"
                if draft_status == "draft_valid"
                else str(plan.get("decisionDraftStopReason") or "decision_tool_not_called")
            )
            self._finish_v2_plan(plan, status="completed", stop_reason=stop_reason)
            self.store.write_jsonl(agent_id, _PLANS_PATH, rows)
            return deepcopy(plan), None
        if int(plan.get("deliveredCount") or 0) >= 8:
            self._finish_v2_plan(plan, status="completed", stop_reason="hard_guard")
            self.store.write_jsonl(agent_id, _PLANS_PATH, rows)
            return deepcopy(plan), None

        reason_code = str((draft or {}).get("reasonCode") or "")
        topic_key = str((draft or {}).get("topicKey") or "")
        disclosed = list(plan.get("disclosedTopicKeys") or [])
        if reason_code == "self_disclosure":
            if disclosed and topic_key not in disclosed:
                self._finish_v2_plan(
                    plan, status="completed", stop_reason="self_disclosure_limit"
                )
                self.store.write_jsonl(agent_id, _PLANS_PATH, rows)
                return deepcopy(plan), None
            if topic_key and topic_key not in disclosed:
                disclosed.append(topic_key)
        plan["disclosedTopicKeys"] = disclosed
        next_ordinal = int(plan.get("currentBubbleOrdinal") or 0) + 1
        suffix = self._burst_hop_suffix(str(plan["planId"]), next_ordinal)
        attempt = self._ensure_v2_attempt(
            agent_id,
            plan=plan,
            ordinal=next_ordinal,
            suffix=suffix,
            local_date=local_date,
        )
        plan.update(
            {
                "status": "queued",
                "currentBubbleOrdinal": next_ordinal,
                "currentEntryId": f"continuation:{suffix}",
                "currentAttemptId": str(attempt["attemptId"]),
                "currentTriggerId": str(attempt["triggerId"]),
                "currentDeliveryToken": str(attempt["deliveryToken"]),
                "currentIdempotencyKey": str(attempt["idempotencyKey"]),
                "currentTurnId": "",
                "decisionDraft": None,
                "decisionDraftStatus": "missing",
                "decisionDraftStopReason": "",
                "decisionToolCallIds": [],
                "updatedAt": _iso(self.now_provider()),
                "expiresAt": _iso(self.now_provider() + timedelta(minutes=5)),
                "version": int(plan.get("version") or 0) + 1,
            }
        )
        self.store.write_jsonl(agent_id, _PLANS_PATH, rows)

        mailbox = normalize_mailbox(self.store.read_json(agent_id, _MAILBOX_PATH))
        mailbox, entry = enqueue_mailbox_entry(
            mailbox,
            entry_id=str(plan["currentEntryId"]),
            session_id=str(plan["sessionId"]),
            source_kind="followup",
            command=self._proactive_command(attempt),
            generation=int(plan["generation"]),
            now=self.now_provider(),
        )
        for stored in mailbox["entries"]:
            if str(stored.get("entryId") or "") != str(plan["currentEntryId"]):
                continue
            stored.update(
                {
                    "deliveryPlanId": str(plan["planId"]),
                    "deliveryToken": str(attempt["deliveryToken"]),
                    "bubbleOrdinal": next_ordinal,
                }
            )
            entry = deepcopy(stored)
            break
        self.store.write_json(agent_id, _MAILBOX_PATH, mailbox)
        self._patch_attempt(
            agent_id,
            str(attempt["deliveryToken"]),
            mailboxSequence=int(entry.get("arrivalSequence") or 0),
        )
        return deepcopy(plan), entry

    def mark_dialogue_burst_admitted(
        self,
        agent_id: str,
        *,
        entry: Mapping[str, Any],
        turn_id: str,
    ) -> dict[str, Any] | None:
        plan_id = str(entry.get("deliveryPlanId") or "").strip()
        if not plan_id:
            return None
        rows = self.store.read_jsonl(agent_id, _PLANS_PATH)
        plan = next(
            (
                item
                for item in rows
                if str(item.get("planId") or "") == plan_id
                and str(item.get("contractVersion") or "") == DIALOGUE_BURST_VERSION
            ),
            None,
        )
        if plan is None:
            return None
        normalized_turn_id = str(turn_id or "").strip()
        if str(plan.get("currentTurnId") or "") not in {"", normalized_turn_id}:
            raise ValueError("Companion dialogue burst admission identity conflicts.")
        plan.update(
            {
                "status": "awaiting_terminal_receipt",
                "currentTurnId": normalized_turn_id,
                "updatedAt": _iso(self.now_provider()),
                "expiresAt": _iso(self.now_provider() + timedelta(minutes=5)),
                "version": int(plan.get("version") or 0) + 1,
            }
        )
        self.store.write_jsonl(agent_id, _PLANS_PATH, rows)
        return deepcopy(plan)

    def cancel_dialogue_burst_for_entry(
        self, agent_id: str, entry: Mapping[str, Any], *, reason: str
    ) -> dict[str, Any] | None:
        plan_id = str(entry.get("deliveryPlanId") or "").strip()
        rows = self.store.read_jsonl(agent_id, _PLANS_PATH)
        plan = next(
            (
                item
                for item in rows
                if str(item.get("planId") or "") == plan_id
                and str(item.get("contractVersion") or "") == DIALOGUE_BURST_VERSION
            ),
            None,
        )
        if plan is None:
            return None
        self._finish_v2_plan(plan, status="cancelled", stop_reason=reason)
        self.store.write_jsonl(agent_id, _PLANS_PATH, rows)
        return deepcopy(plan)

    @staticmethod
    def _burst_hop_suffix(plan_id: str, ordinal: int) -> str:
        import hashlib

        return hashlib.sha256(f"{plan_id}\x1f{ordinal}".encode()).hexdigest()[:24]

    def _ensure_v2_attempt(
        self,
        agent_id: str,
        *,
        plan: Mapping[str, Any],
        ordinal: int,
        suffix: str,
        local_date: str,
    ) -> dict[str, Any]:
        delivery_token = f"burst-continuation-{suffix}"
        existing = next(
            (
                deepcopy(item)
                for item in reversed(self.store.read_jsonl(agent_id, _ATTEMPTS_PATH))
                if str(item.get("deliveryToken") or "") == delivery_token
            ),
            None,
        )
        if existing is not None:
            return existing
        now = self.now_provider()
        attempt = {
            "agentId": str(agent_id),
            "pluginId": PLUGIN_ID,
            "attemptId": f"burst-attempt:{suffix}",
            "triggerId": f"burst-trigger:{suffix}",
            "deliveryToken": delivery_token,
            "bindingRevision": int(plan.get("bindingRevision") or 0),
            "sessionId": str(plan.get("sessionId") or ""),
            "sourceEventId": str(plan.get("latestAssistantReceiptEventId") or ""),
            "reason": "自然延续当前对话",
            "idempotencyKey": f"burst-continuation:{suffix}",
            "status": "reserved",
            "candidateAt": _iso(now),
            "reservedAt": _iso(now),
            "createdAt": _iso(now),
            "expiresAt": _iso(now + timedelta(minutes=5)),
            "validUntil": _iso(now + timedelta(minutes=5)),
            "localDate": str(local_date or ""),
            "deliveryKind": "burst_continuation",
            "deliveryPlanId": str(plan.get("planId") or ""),
            "sourceTurnId": str(plan.get("currentTurnId") or ""),
            "generation": int(plan.get("generation") or 0),
            "bubbleOrdinal": int(ordinal),
        }
        rows = self.store.read_jsonl(agent_id, _ATTEMPTS_PATH)
        rows.append(attempt)
        self.store.write_jsonl(agent_id, _ATTEMPTS_PATH, rows)
        return deepcopy(attempt)

    def _finish_v2_plan(self, plan: dict[str, Any], *, status: str, stop_reason: str) -> None:
        plan.update(
            {
                "status": status,
                "stopReason": str(stop_reason or "")[:120],
                "updatedAt": _iso(self.now_provider()),
                "version": int(plan.get("version") or 0) + 1,
            }
        )

    def plan_user_response(
        self,
        agent_id: str,
        *,
        session_id: str,
        generation: int,
        source_entry_id: str,
        source_turn_id: str,
        expression_decision: dict[str, Any],
        binding_revision: int,
        local_date: str,
    ) -> dict[str, Any]:
        now = self.now_provider()
        proposed = build_companion_delivery_plan(
            session_id=session_id,
            generation=generation,
            source_entry_id=source_entry_id,
            source_turn_id=source_turn_id,
            expression_decision=expression_decision,
            now=now,
        )
        if not isinstance(proposed.get("followup"), dict):
            return deepcopy(proposed)
        rows, plan = upsert_delivery_plan(
            self.store.read_jsonl(agent_id, _PLANS_PATH),
            proposed,
        )
        self.store.write_jsonl(agent_id, _PLANS_PATH, rows)
        attempt = self.ensure_followup_attempt(
            agent_id,
            plan=plan,
            binding_revision=binding_revision,
            local_date=local_date,
        )
        mailbox = normalize_mailbox(self.store.read_json(agent_id, _MAILBOX_PATH))
        command = self._proactive_command(attempt)
        followup = dict(plan["followup"])
        mailbox, entry = enqueue_mailbox_entry(
            mailbox,
            entry_id=str(followup["entryId"]),
            session_id=str(plan["sessionId"]),
            source_kind="followup",
            command=command,
            generation=int(plan["generation"]),
            now=now,
        )
        for stored in mailbox["entries"]:
            if str(stored.get("entryId") or "") != str(followup["entryId"]):
                continue
            stored.update(
                {
                    "deliveryPlanId": str(plan["planId"]),
                    "deliveryToken": str(followup["deliveryToken"]),
                    "sourceTurnId": str(plan["sourceTurnId"]),
                    "bubbleIndex": 2,
                }
            )
            entry = deepcopy(stored)
            break
        self.store.write_json(agent_id, _MAILBOX_PATH, mailbox)
        self._patch_attempt(
            agent_id,
            str(attempt["deliveryToken"]),
            mailboxSequence=int(entry.get("arrivalSequence") or 0),
        )
        return self.transition_plan(
            agent_id,
            plan_id=str(plan["planId"]),
            status="queued",
        )

    def ensure_followup_attempt(
        self,
        agent_id: str,
        *,
        plan: Mapping[str, Any],
        binding_revision: int,
        local_date: str,
    ) -> dict[str, Any]:
        followup = (
            plan.get("followup") if isinstance(plan.get("followup"), Mapping) else {}
        )
        delivery_token = str(followup.get("deliveryToken") or "").strip()
        rows = self.store.read_jsonl(agent_id, _ATTEMPTS_PATH)
        existing = next(
            (
                deepcopy(item)
                for item in reversed(rows)
                if str(item.get("deliveryToken") or "") == delivery_token
            ),
            None,
        )
        if existing is not None:
            return existing
        if not delivery_token or int(binding_revision) < 1:
            raise ValueError("Companion follow-up identity is incomplete.")
        now = self.now_provider()
        valid_until = _iso(now + timedelta(minutes=30))
        attempt = {
            "agentId": str(agent_id).strip(),
            "pluginId": PLUGIN_ID,
            "attemptId": str(followup.get("attemptId") or ""),
            "triggerId": str(followup.get("triggerId") or ""),
            "deliveryToken": delivery_token,
            "bindingRevision": int(binding_revision),
            "sessionId": str(plan.get("sessionId") or ""),
            "sourceEventId": str(plan.get("sourceTurnId") or ""),
            "reason": "自然延续上一条回复",
            "idempotencyKey": str(followup.get("idempotencyKey") or ""),
            "status": "reserved",
            "candidateAt": _iso(now),
            "reservedAt": _iso(now),
            "createdAt": _iso(now),
            "expiresAt": valid_until,
            "validUntil": valid_until,
            "localDate": str(local_date or ""),
            "deliveryKind": "followup",
            "deliveryPlanId": str(plan.get("planId") or ""),
            "sourceTurnId": str(plan.get("sourceTurnId") or ""),
            "generation": int(plan.get("generation") or 0),
            "bubbleIndex": 2,
        }
        rows.append(attempt)
        self.store.write_jsonl(agent_id, _ATTEMPTS_PATH, rows)
        return deepcopy(attempt)

    def ensure_attempt_from_entry(
        self,
        agent_id: str,
        entry: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Restore a missing follow-up attempt from its durable mailbox command."""

        command = (
            entry.get("command") if isinstance(entry.get("command"), Mapping) else {}
        )
        payload = (
            command.get("proactiveAttempt")
            if isinstance(command.get("proactiveAttempt"), Mapping)
            else {}
        )
        delivery_token = str(payload.get("delivery_token") or "").strip()
        if str(entry.get("sourceKind") or "") != "followup" or not delivery_token:
            return None
        existing = next(
            (
                deepcopy(item)
                for item in reversed(self.store.read_jsonl(agent_id, _ATTEMPTS_PATH))
                if str(item.get("deliveryToken") or "") == delivery_token
            ),
            None,
        )
        if existing is not None:
            return existing
        trigger = (
            payload.get("trigger")
            if isinstance(payload.get("trigger"), Mapping)
            else {}
        )
        now = self.now_provider()
        valid_until = str(
            trigger.get("validUntil") or _iso(now + timedelta(minutes=30))
        )
        attempt = {
            "agentId": str(agent_id).strip(),
            "pluginId": PLUGIN_ID,
            "attemptId": str(trigger.get("attemptId") or ""),
            "triggerId": str(payload.get("trigger_id") or ""),
            "deliveryToken": delivery_token,
            "bindingRevision": int(payload.get("binding_revision") or 0),
            "sessionId": str(payload.get("session_id") or entry.get("sessionId") or ""),
            "sourceEventId": str(trigger.get("sourceTurnId") or ""),
            "reason": str(trigger.get("reason") or "自然延续上一条回复"),
            "idempotencyKey": str(trigger.get("idempotencyKey") or ""),
            "status": "reserved",
            "candidateAt": _iso(now),
            "reservedAt": _iso(now),
            "createdAt": _iso(now),
            "expiresAt": valid_until,
            "validUntil": valid_until,
            "localDate": str(trigger.get("localDate") or ""),
            "deliveryKind": str(trigger.get("deliveryKind") or "followup"),
            "deliveryPlanId": str(trigger.get("deliveryPlanId") or ""),
            "sourceTurnId": str(trigger.get("sourceTurnId") or ""),
            "generation": int(
                trigger.get("generation") or entry.get("generation") or 0
            ),
            "bubbleIndex": int(trigger.get("bubbleIndex") or 0),
            "bubbleOrdinal": int(trigger.get("bubbleOrdinal") or 0),
            "recoveredFromMailbox": True,
        }
        rows = self.store.read_jsonl(agent_id, _ATTEMPTS_PATH)
        rows.append(attempt)
        self.store.write_jsonl(agent_id, _ATTEMPTS_PATH, rows)
        return deepcopy(attempt)

    def cancel_entry(
        self,
        agent_id: str,
        entry: Mapping[str, Any],
        *,
        reason: str,
    ) -> None:
        delivery_token = str(entry.get("deliveryToken") or "").strip()
        command = (
            entry.get("command") if isinstance(entry.get("command"), Mapping) else {}
        )
        payload = (
            command.get("proactiveAttempt")
            if isinstance(command.get("proactiveAttempt"), Mapping)
            else {}
        )
        delivery_token = (
            delivery_token or str(payload.get("delivery_token") or "").strip()
        )
        if delivery_token:
            self._cancel_attempt(agent_id, delivery_token, reason=reason)
        delivery_kind = companion_delivery_kind_from_entry(entry)
        if (
            is_companion_continuation_delivery_kind(delivery_kind)
            and delivery_kind == "burst_continuation"
        ):
            self.cancel_dialogue_burst_for_entry(agent_id, entry, reason=reason)
            return
        plan_id = str(entry.get("deliveryPlanId") or "").strip()
        if plan_id:
            self.transition_plan(agent_id, plan_id=plan_id, status="cancelled")

    def transition_entry_plan(
        self,
        agent_id: str,
        entry: Mapping[str, Any],
        *,
        status: str,
        receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        plan_id = str(entry.get("deliveryPlanId") or "").strip()
        if not plan_id:
            command = (
                entry.get("command")
                if isinstance(entry.get("command"), Mapping)
                else {}
            )
            payload = (
                command.get("proactiveAttempt")
                if isinstance(command.get("proactiveAttempt"), Mapping)
                else {}
            )
            trigger = (
                payload.get("trigger")
                if isinstance(payload.get("trigger"), Mapping)
                else {}
            )
            plan_id = str(trigger.get("deliveryPlanId") or "").strip()
        if not plan_id:
            return None
        return self.transition_plan(
            agent_id,
            plan_id=plan_id,
            status=status,
            receipt=receipt,
        )

    def transition_plan(
        self,
        agent_id: str,
        *,
        plan_id: str,
        status: str,
        receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rows, plan = transition_delivery_plan(
            self.store.read_jsonl(agent_id, _PLANS_PATH),
            plan_id=plan_id,
            status=status,
            now=self.now_provider(),
            receipt=receipt,
        )
        self.store.write_jsonl(agent_id, _PLANS_PATH, rows)
        return plan

    def _cancel_attempt(
        self, agent_id: str, delivery_token: str, *, reason: str
    ) -> None:
        rows = self.store.read_jsonl(agent_id, _ATTEMPTS_PATH)
        changed = False
        for index in range(len(rows) - 1, -1, -1):
            if str(rows[index].get("deliveryToken") or "") != delivery_token:
                continue
            if str(rows[index].get("status") or "") in {
                "candidate",
                "reserved",
                "delivering",
            }:
                rows[index] = {
                    **rows[index],
                    "status": "cancelled",
                    "cancelledAt": _iso(self.now_provider()),
                    "cancellationReason": str(reason or "user_interjected")[:160],
                    "updatedAt": _iso(self.now_provider()),
                }
                changed = True
            break
        if changed:
            self.store.write_jsonl(agent_id, _ATTEMPTS_PATH, rows)

    def _patch_attempt(self, agent_id: str, delivery_token: str, **patch: Any) -> None:
        rows = self.store.read_jsonl(agent_id, _ATTEMPTS_PATH)
        for index in range(len(rows) - 1, -1, -1):
            if str(rows[index].get("deliveryToken") or "") != delivery_token:
                continue
            rows[index] = {
                **rows[index],
                **patch,
                "updatedAt": _iso(self.now_provider()),
            }
            self.store.write_jsonl(agent_id, _ATTEMPTS_PATH, rows)
            return

    @staticmethod
    def _proactive_command(attempt: Mapping[str, Any]) -> dict[str, Any]:
        delivery_kind = str(attempt.get("deliveryKind") or "followup")
        trigger = {
            "reason": str(attempt.get("reason") or ""),
            "deliveryKind": delivery_kind,
            "sourceTurnId": str(attempt.get("sourceTurnId") or ""),
            "generation": int(attempt.get("generation") or 0),
            "deliveryPlanId": str(attempt.get("deliveryPlanId") or ""),
            "bubbleIndex": int(attempt.get("bubbleIndex") or 0),
            "bubbleOrdinal": int(attempt.get("bubbleOrdinal") or 0),
            "attemptId": str(attempt.get("attemptId") or ""),
            "idempotencyKey": str(attempt.get("idempotencyKey") or ""),
            "validUntil": str(attempt.get("validUntil") or ""),
            "localDate": str(attempt.get("localDate") or ""),
        }
        return {
            "proactiveAttempt": {
                "session_id": str(attempt.get("sessionId") or ""),
                "agent_id": str(attempt.get("agentId") or ""),
                "origin": "proactive_plugin",
                "source_kind": PLUGIN_ID,
                "plugin_id": PLUGIN_ID,
                "trigger_id": str(attempt.get("triggerId") or ""),
                "delivery_token": str(attempt.get("deliveryToken") or ""),
                "binding_revision": int(attempt.get("bindingRevision") or 0),
                "trigger": trigger,
            },
            "idempotencyKey": str(attempt.get("idempotencyKey") or ""),
        }


__all__ = [
    "CompanionDeliveryRuntime",
    "companion_delivery_kind_from_entry",
    "is_companion_continuation_delivery_kind",
]
