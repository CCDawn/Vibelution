"""Companion-only delivery runtime for an optional second native bubble.

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
    build_companion_delivery_plan,
    transition_delivery_plan,
    upsert_delivery_plan,
)
from .mailbox import enqueue_mailbox_entry, normalize_mailbox
from .manifest import PLUGIN_ID
from .storage import VirtualHumanLifeStore

_PLANS_PATH = "conversation/delivery_plans.jsonl"
_ATTEMPTS_PATH = "proactive/deliveries.jsonl"
_MAILBOX_PATH = "conversation/mailbox.json"


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
            "deliveryKind": "followup",
            "deliveryPlanId": str(trigger.get("deliveryPlanId") or ""),
            "sourceTurnId": str(trigger.get("sourceTurnId") or ""),
            "generation": int(
                trigger.get("generation") or entry.get("generation") or 0
            ),
            "bubbleIndex": 2,
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
        trigger = {
            "reason": str(attempt.get("reason") or ""),
            "deliveryKind": "followup",
            "sourceTurnId": str(attempt.get("sourceTurnId") or ""),
            "generation": int(attempt.get("generation") or 0),
            "deliveryPlanId": str(attempt.get("deliveryPlanId") or ""),
            "bubbleIndex": 2,
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


__all__ = ["CompanionDeliveryRuntime"]
