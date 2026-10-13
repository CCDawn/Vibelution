"""Agent-owned wake commands; native Session receipts remain the execution authority.

Reference: OpenClaw's bounded next_check and Hermes' agent-managed scheduling.
Only one future command is active. No transcript or synthetic life outcome is stored.
"""

from __future__ import annotations

import hashlib
import logging
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .service import VirtualHumanLifeService

PATH = "autonomy/next_wakeup.json"
MIN_DELAY = timedelta(minutes=1)
MAX_DELAY = timedelta(days=7)
MAX_DAILY_WAKES = 24
SESSION_PATH = "autonomy/native_session.json"
logger = logging.getLogger(__name__)


def _time(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Wake time requires an explicit timezone.")
    return parsed.astimezone(timezone.utc)


class SelfContinuity:
    def __init__(self, service: VirtualHumanLifeService) -> None:
        self.service = service

    def snapshot(self, agent_id: str) -> dict[str, Any]:
        return deepcopy(
            self.service.store.read_json(agent_id, PATH)
            or {"revision": 0, "status": "empty"}
        )

    def _enabled(self, agent_id: str) -> dict[str, Any]:
        s = self.service
        if (
            s.runtime_acceptance_provider is not None
            and not s.runtime_acceptance_provider()
        ):
            raise ValueError("Virtual human runtime is stopping.")
        binding = s._require_enabled_binding(agent_id)
        agent = s._agent(agent_id, include_archived=False) or {}
        if agent.get("status") != "active" or not agent.get("directSessionId"):
            raise ValueError(
                "Self wakeups require an active Companion with a direct Session."
            )
        if binding.get("autonomyLevel") != "autonomous":
            raise ValueError("Self wakeups require autonomous life mode.")
        return binding

    def _own_sessions(self, agent_id: str) -> set[str]:
        agent = self.service._agent(agent_id, include_archived=False) or {}
        reference = self.service.store.read_json(agent_id, SESSION_PATH) or {}
        return {
            str(agent.get("directSessionId") or ""),
            str(reference.get("sessionId") or "")
            if reference.get("agentId") == agent_id
            and reference.get("runtimeAgentId") not in {None, "", agent_id}
            else "",
        } - {""}

    def schedule(
        self,
        agent_id: str,
        *,
        session_id: str,
        source_turn_id: str,
        wake_at: str,
        intent: str,
        reason: str,
        expected_revision: int,
        idempotency_key: str,
        required_tool_names: list[str] | None = None,
    ) -> dict[str, Any]:
        s = self.service
        with s._lock_for(agent_id):
            binding = self._enabled(agent_id)
            if not session_id or session_id not in self._own_sessions(agent_id):
                raise ValueError("Self wakeups require the Companion direct Session.")
            if not source_turn_id.strip():
                raise ValueError("Self wakeups require a native source Turn.")
            current = self.snapshot(agent_id)
            key = idempotency_key.strip()
            if not key or len(key) > 160:
                raise ValueError("A bounded idempotency key is required.")
            intent, reason = intent.strip(), reason.strip()
            if not intent or len(intent) > 600 or not reason or len(reason) > 300:
                raise ValueError("A bounded intent and reason are required.")
            wake = _time(wake_at)
            tools = list(
                dict.fromkeys(str(name).strip() for name in required_tool_names or [])
            )
            if len(tools) > 8 or any(not name or len(name) > 160 for name in tools):
                raise ValueError("Wake tool references exceed their budget.")
            request = {
                "wakeAt": wake.isoformat(),
                "intent": intent,
                "reason": reason,
                "requiredToolNames": tools,
                "sessionId": session_id,
            }
            fingerprint = hashlib.sha256(
                repr(sorted(request.items())).encode()
            ).hexdigest()
            if current.get("idempotencyKey") == key:
                if current.get("fingerprint") != fingerprint:
                    raise ValueError(
                        "Wake idempotency key conflicts with an existing request."
                    )
                return current
            if int(current["revision"]) != int(expected_revision):
                raise ValueError(
                    "Wake plan revision changed; read the current plan again."
                )
            now = s._now()
            if not MIN_DELAY <= wake - now <= MAX_DELAY:
                raise ValueError(
                    "Wake time must be between one minute and seven days in the future."
                )
            plan = {
                **request,
                "wakeId": "self-wake-"
                + hashlib.sha256(f"{agent_id}:{key}".encode()).hexdigest()[:24],
                "revision": int(current["revision"]) + 1,
                "status": "scheduled",
                "bindingRevision": int(binding["bindingRevision"]),
                "sourceTurnId": source_turn_id,
                "idempotencyKey": key,
                "fingerprint": fingerprint,
                "createdAt": now.isoformat(),
                "wakeRequests": list(current.get("wakeRequests") or [])[
                    -MAX_DAILY_WAKES:
                ],
            }
            s.store.write_json(agent_id, PATH, plan)
            return deepcopy(plan)

    def cancel(
        self, agent_id: str, *, session_id: str, expected_revision: int
    ) -> dict[str, Any]:
        s = self.service
        with s._lock_for(agent_id):
            self._enabled(agent_id)
            if session_id not in self._own_sessions(agent_id):
                raise ValueError("Self wakeups require the Companion direct Session.")
            plan = self.snapshot(agent_id)
            if plan["revision"] != expected_revision:
                raise ValueError("Wake plan revision changed.")
            if plan.get("status") != "cancelled":
                plan.update(status="cancelled", revision=plan["revision"] + 1)
                s.store.write_json(agent_id, PATH, plan)
            return plan

    def require_dispatch(self, agent_id: str, wake_id: str) -> dict[str, Any]:
        binding = self._enabled(agent_id)
        plan = self.snapshot(agent_id)
        if plan.get("bindingRevision") != binding["bindingRevision"] or plan.get(
            "sessionId"
        ) not in self._own_sessions(agent_id):
            raise ValueError("Self wake command identity is stale.")
        if plan.get("wakeId") != wake_id or plan.get("status") != "reserved":
            raise ValueError("Self wake command is not reserved by its scheduler.")
        if _time(plan["wakeAt"]) > self.service._now():
            raise ValueError("Self wake command is not due.")
        return plan

    def _review(
        self,
        agent_id: str,
        binding: dict[str, Any],
        plan: dict[str, Any],
        now: datetime,
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        # A new review command is future work, never replay of the missed action.
        replacement = {
            "revision": int(plan.get("revision") or 0) + 1,
            "status": "scheduled",
            "wakeId": "self-review-"
            + hashlib.sha256(f"{agent_id}:{now.isoformat()}".encode()).hexdigest()[:24],
            "wakeAt": (now + MIN_DELAY).isoformat(),
            "intent": "查看自己的目标、近期真实经历和未完成计划，决定接下来做什么并安排下一次唤醒。",
            "reason": reason
            or ("restart_review" if plan.get("wakeId") else "initial_planning"),
            "sessionId": str(
                (self.service._agent(agent_id, include_archived=False) or {}).get(
                    "directSessionId"
                )
                or ""
            ),
            "bindingRevision": int(binding["bindingRevision"]),
            "createdAt": now.isoformat(),
            "wakeRequests": list(plan.get("wakeRequests") or [])[-MAX_DAILY_WAKES:],
            "requiredToolNames": [],
        }
        self.service.store.write_json(agent_id, PATH, replacement)
        return replacement

    def tick(
        self, agent_id: str, *, now: datetime, restarted: bool = False
    ) -> dict[str, Any]:
        s = self.service
        with s._lock_for(agent_id):
            binding = s._require_enabled_binding(agent_id)
            if binding.get("autonomyLevel") != "autonomous" or (
                s.runtime_acceptance_provider is not None
                and not s.runtime_acceptance_provider()
            ):
                return {"status": "paused"}
            if (s.store.read_json(agent_id, "state.json") or {}).get("lifePaused"):
                return {"status": "paused"}
            plan = self.snapshot(agent_id)
            if plan["status"] == "empty":
                return self._review(agent_id, binding, plan, now)
            if plan["status"] == "cancelled":
                return plan
            stale_binding = plan.get("bindingRevision") != binding.get(
                "bindingRevision"
            )
            if stale_binding and plan["status"] != "cancelled":
                return self._review(
                    agent_id, binding, plan, now, reason="binding_review"
                )
            if restarted and (
                stale_binding
                or plan["status"] in {"reserved", "dispatched"}
                or (plan["status"] == "scheduled" and _time(plan["wakeAt"]) <= now)
            ):
                return self._review(agent_id, binding, plan, now)
            if plan["status"] == "interrupted":
                return self._review(
                    agent_id, binding, plan, now, reason="action_review"
                )
            if plan["status"] == "dispatched" and plan.get("deliveryToken"):
                attempt = (
                    s.proactive_attempt(agent_id, str(plan["deliveryToken"])) or {}
                )
                from core.chat.turn_journal import turn_has_terminal_event

                native_closed = bool(
                    attempt.get("sessionId")
                    and attempt.get("turnId")
                    and turn_has_terminal_event(
                        s.project_root,
                        str(attempt["sessionId"]),
                        str(attempt["turnId"]),
                    )
                )
                if (
                    attempt.get("status") in {"failed", "cancelled", "expired"}
                    or (
                        attempt.get("status") == "delivered"
                        and not s._delivered_attempt_awaits_native_close(attempt)
                    )
                    or native_closed
                ):
                    if native_closed and attempt.get("status") in {
                        "reserved",
                        "delivering",
                    }:
                        s.cancel_proactive_attempt(
                            agent_id,
                            str(plan["deliveryToken"]),
                            reason="native_action_closed_without_message_receipt",
                        )
                    return self._review(
                        agent_id, binding, plan, now, reason="action_review"
                    )
            if (
                stale_binding
                or plan["status"] != "scheduled"
                or _time(plan["wakeAt"]) > now
            ):
                return plan
            session_id = plan["sessionId"]
            direct = str(
                (s._agent(agent_id, include_archived=False) or {}).get(
                    "directSessionId"
                )
                or ""
            )
            if s.conversation_busy_provider is not None and any(
                s.conversation_busy_provider(own_session)
                for own_session in self._own_sessions(agent_id)
                if own_session
            ):
                return {**plan, "waitReason": "native_session_busy"}
            mailbox = s.store.read_json(agent_id, "conversation/mailbox.json") or {}
            if any(
                entry.get("state")
                in {"queued", "dispatching", "awaiting_native_admission"}
                for entry in mailbox.get("entries", [])
                if entry.get("sessionId") in {direct, session_id}
            ):
                return {**plan, "waitReason": "mailbox_pending"}
            local_date = now.astimezone(s._zone(binding)).date()
            requests = [
                stamp
                for stamp in plan.get("wakeRequests", [])
                if _time(stamp).astimezone(s._zone(binding)).date() == local_date
            ]
            if len(requests) >= MAX_DAILY_WAKES:
                return {**plan, "waitReason": "wake_budget"}
            plan.update(status="reserved", wakeRequests=[*requests, now.isoformat()])
            s.store.write_json(agent_id, PATH, plan)
            try:
                attempt = s.request_proactive_message(
                    agent_id,
                    reason=plan["intent"],
                    idempotency_key=plan["wakeId"],
                    valid_for_minutes=60,
                    _self_wake_id=plan["wakeId"],
                )
            except Exception:
                plan["status"] = "interrupted"
                s.store.write_json(agent_id, PATH, plan)
                raise
            # Scheduling success is not an activity outcome. Keep only a native receipt reference.
            latest = self.snapshot(agent_id)
            if (
                latest.get("wakeId") == plan["wakeId"]
                and latest.get("status") == "reserved"
                and latest.get("revision") == plan["revision"]
            ):
                latest.update(
                    status="dispatched",
                    deliveryToken=attempt.get("deliveryToken"),
                    turnId=attempt.get("turnId"),
                )
                s.store.write_json(agent_id, PATH, latest)
            return latest

    def interrupt_for_user(self, agent_id: str) -> None:
        """Cancel only this plugin's autonomous work; human conversation wins."""
        s = self.service
        attempts = [
            row
            for row in s.store.read_jsonl(agent_id, "proactive/deliveries.jsonl")
            if row.get("deliveryKind") == "self_wake"
            and (
                row.get("status") in {"reserved", "delivering"}
                or (
                    row.get("status") == "delivered"
                    and s._delivered_attempt_awaits_native_close(row)
                )
            )
        ]
        for row in attempts:
            s.cancel_proactive_attempt(
                agent_id, str(row["deliveryToken"]), reason="user_message_arrived"
            )
            if s.self_wake_canceller is not None and row.get("turnId"):
                try:
                    s.self_wake_canceller(
                        agent_id, str(row["sessionId"]), str(row["turnId"])
                    )
                except Exception as exc:  # noqa: BLE001 - a settled stop race cannot reject the human; receipt is fenced
                    logger.warning(
                        "Autonomous native stop request failed for agent=%s (%s).",
                        agent_id,
                        type(exc).__name__,
                    )
