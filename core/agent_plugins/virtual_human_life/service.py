"""Virtual human life domain service.

The service is deliberately Agent-scoped. Merely importing the plugin or reading an
unbound Agent never creates storage, prompt segments, tools, timers, or messages.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterable
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .manifest import (
    PLUGIN_ID,
    PROMPT_PACK_ID,
    STORAGE_SCHEMA_VERSION,
    TOOL_BUNDLE_ID,
    VIRTUAL_HUMAN_TOOL_NAMES,
)
from .prompt_pack import load_prompt_pack
from .storage import VirtualHumanLifeStorageError, VirtualHumanLifeStore

logger = logging.getLogger(__name__)


class VirtualHumanLifeError(RuntimeError):
    """Base virtual human life error."""


class AgentUnavailableError(VirtualHumanLifeError):
    """Raised when the target Agent does not exist or is not active."""


class BindingConflictError(VirtualHumanLifeError):
    """Raised when optimistic binding or state versions do not match."""


class BindingDisabledError(VirtualHumanLifeError):
    """Raised when an enabled binding is required."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clamp(value: object, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _local_date_text(value: object) -> str:
    normalized = str(value or "").strip()
    date.fromisoformat(normalized)
    return normalized


class VirtualHumanLifeService:
    def __init__(
        self,
        project_root: Path,
        *,
        agent_loader: Callable[..., dict[str, Any] | None],
        agent_lister: Callable[[], list[dict[str, Any]]],
        plugin_root_resolver: Callable[[str], Path] | None = None,
        proactive_submitter: Callable[..., dict[str, Any]] | None = None,
        delivery_receipt_resolver: Callable[[str, dict[str, Any]], dict[str, Any] | None]
        | None = None,
        episodic_writer: Callable[..., dict[str, Any]] | None = None,
        now_provider: Callable[[], datetime] = _utc_now,
        runtime_acceptance_provider: Callable[[], bool] | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.store = VirtualHumanLifeStore(
            self.project_root,
            plugin_root_resolver=plugin_root_resolver,
        )
        self.agent_loader = agent_loader
        self.agent_lister = agent_lister
        self.proactive_submitter = proactive_submitter
        self.delivery_receipt_resolver = delivery_receipt_resolver
        self.episodic_writer = episodic_writer
        self.now_provider = now_provider
        self.runtime_acceptance_provider = runtime_acceptance_provider
        self._agent_locks_guard = threading.Lock()
        self._agent_locks: dict[str, threading.RLock] = {}

    def plugin_root(self, agent_id: str) -> Path:
        return self.store.plugin_root(agent_id)

    def require_agent(
        self,
        agent_id: str,
        *,
        include_archived: bool = True,
    ) -> dict[str, Any]:
        agent = self._agent(agent_id, include_archived=include_archived)
        if agent is None:
            raise AgentUnavailableError(f"Agent not found: {str(agent_id or '').strip()}")
        return deepcopy(agent)

    def _plugin_purge_staging_parent(self) -> Path:
        parent = self.project_root / ".tmp" / "virtual-human-life-purge"
        parent.mkdir(parents=True, exist_ok=True)
        return parent.resolve()

    def _stage_plugin_workspace(self, agent_id: str) -> str | None:
        root = self.plugin_root(agent_id)
        if not root.exists():
            return None
        if not root.is_dir():
            raise VirtualHumanLifeStorageError(
                "Virtual human plugin root is not a directory."
            )
        staging_parent = self._plugin_purge_staging_parent()
        staging_root = Path(
            tempfile.mkdtemp(
                prefix=f"{str(agent_id).strip()}-",
                dir=str(staging_parent),
            )
        ).resolve()
        staged_root = staging_root / "plugin"
        try:
            shutil.move(str(root), str(staged_root))
        except Exception:
            shutil.rmtree(staging_root, ignore_errors=True)
            raise
        return str(staging_root)

    def _staged_plugin_workspace(self, token: dict[str, Any]) -> tuple[str, Path] | None:
        agent_id = str(token.get("agentId") or "").strip()
        staging_value = str(token.get("pluginPurgeStagingRoot") or "").strip()
        if not agent_id or not staging_value:
            return None
        staging_root = Path(staging_value).resolve()
        try:
            staging_root.relative_to(self._plugin_purge_staging_parent())
        except ValueError as exc:
            raise VirtualHumanLifeStorageError(
                "Virtual human purge staging path is outside the staging root."
            ) from exc
        return agent_id, staging_root

    def _restore_staged_plugin_workspace(self, token: dict[str, Any]) -> None:
        staged = self._staged_plugin_workspace(token)
        if staged is None:
            return
        agent_id, staging_root = staged
        staged_root = staging_root / "plugin"
        if not staged_root.exists():
            return
        root = self.plugin_root(agent_id)
        if root.exists():
            raise BindingConflictError(
                "Virtual human plugin workspace changed during purge compensation."
            )
        root.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged_root), str(root))

    def _cleanup_staged_plugin_workspace(self, token: dict[str, Any] | None) -> None:
        if not isinstance(token, dict):
            return
        staged = self._staged_plugin_workspace(token)
        if staged is None:
            return
        _agent_id, staging_root = staged
        if staging_root.exists():
            shutil.rmtree(staging_root)

    def binding_for(self, agent_id: str) -> dict[str, Any] | None:
        payload = self.store.read_json(agent_id, "binding.json")
        return self._normalize_binding(payload) if payload is not None else None

    def set_binding(
        self,
        agent_id: str,
        *,
        enabled: bool,
        expected_version: int,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock_for(agent_id):
            agent = self._agent(agent_id, include_archived=True)
            if not agent:
                raise AgentUnavailableError(f"Agent not found: {agent_id}")
            if enabled and str(agent.get("status") or "active").strip().lower() != "active":
                raise AgentUnavailableError("Only an active Agent can enable virtual-human-life.")
            current = self.binding_for(agent_id)
            current_version = int((current or {}).get("configVersion") or 0)
            if int(expected_version) != current_version:
                raise BindingConflictError(
                    f"Binding version changed: expected {expected_version}, current {current_version}."
                )
            next_binding = self._default_binding(agent_id)
            if current:
                next_binding.update(current)
            next_binding.update(self._normalized_binding_config(config or {}))
            next_binding.update(
                {
                    "agentId": str(agent_id).strip(),
                    "pluginId": PLUGIN_ID,
                    "enabled": bool(enabled),
                    "configVersion": current_version + 1,
                    "bindingRevision": int((current or {}).get("bindingRevision") or 0) + 1,
                    "updatedAt": _iso(self._now()),
                }
            )
            self.store.write_json(agent_id, "binding.json", next_binding)
            if enabled:
                self._ensure_initialized(agent_id, next_binding)
            else:
                self.cancel_open_proactive_attempts(
                    agent_id,
                    reason="binding_disabled",
                    minimum_revision=int(next_binding["bindingRevision"]),
                )
            return deepcopy(next_binding)

    def snapshot(self, agent_id: str) -> dict[str, Any]:
        self.require_agent(agent_id)
        binding = self.binding_for(agent_id)
        if binding is None:
            return {
                "pluginId": PLUGIN_ID,
                "agentId": str(agent_id or "").strip(),
                "installed": True,
                "bound": False,
                "binding": None,
                "state": None,
                "todaySchedule": None,
                "tomorrowSchedule": None,
                "proactiveUsage": {"delivered": 0, "limit": 0, "remaining": 0},
            }
        local_now = self._local_now(binding)
        today = local_now.date().isoformat()
        tomorrow = (local_now.date() + timedelta(days=1)).isoformat()
        state = self.store.read_json(agent_id, "state.json")
        today_schedule = self.store.read_json(agent_id, f"schedules/{today}.json")
        tomorrow_schedule = self.store.read_json(agent_id, f"schedules/{tomorrow}.json")
        usage = self.proactive_usage(agent_id, today)
        return {
            "pluginId": PLUGIN_ID,
            "agentId": str(agent_id or "").strip(),
            "installed": True,
            "bound": True,
            "binding": binding,
            "state": state,
            "todaySchedule": today_schedule,
            "tomorrowSchedule": tomorrow_schedule,
            "proactiveUsage": usage,
            "storageSchemaVersion": STORAGE_SCHEMA_VERSION,
            "toolBundleId": TOOL_BUNDLE_ID,
            "promptPackId": PROMPT_PACK_ID,
        }

    def schedule_for(self, agent_id: str, local_date: str) -> dict[str, Any]:
        self.require_agent(agent_id)
        local_date = _local_date_text(local_date)
        payload = self.store.read_json(agent_id, f"schedules/{local_date}.json")
        if payload is None:
            binding = self._require_enabled_binding(agent_id)
            payload = self._generate_schedule(agent_id, date.fromisoformat(local_date), binding)
            self.store.write_json(agent_id, f"schedules/{local_date}.json", payload)
        return deepcopy(payload)

    def save_schedule(self, agent_id: str, schedule: dict[str, Any]) -> dict[str, Any]:
        binding = self._require_enabled_binding(agent_id)
        local_date = str(schedule.get("localDate") or "").strip()
        if not local_date:
            local_date = self._local_now(binding).date().isoformat()
        date.fromisoformat(local_date)
        normalized = deepcopy(schedule)
        normalized["agentId"] = str(agent_id).strip()
        normalized["localDate"] = local_date
        normalized["scheduleVersion"] = max(1, int(normalized.get("scheduleVersion") or 1))
        normalized["updatedAt"] = _iso(self._now())
        self.store.write_json(agent_id, f"schedules/{local_date}.json", normalized)
        return deepcopy(normalized)

    def build_prompt_segments(
        self,
        agent_id: str,
        *,
        session_id: str = "",
        run_id: str = "",
    ) -> list[dict[str, Any]]:
        binding = self.binding_for(agent_id)
        agent = self._agent(agent_id, include_archived=True)
        if (
            not binding
            or not bool(binding.get("enabled"))
            or not agent
            or str(agent.get("status") or "active").strip().lower() != "active"
        ):
            return []
        snapshot = self.snapshot(agent_id)
        state = snapshot.get("state") if isinstance(snapshot.get("state"), dict) else {}
        today_schedule = (
            snapshot.get("todaySchedule")
            if isinstance(snapshot.get("todaySchedule"), dict)
            else {}
        )
        tomorrow_schedule = (
            snapshot.get("tomorrowSchedule")
            if isinstance(snapshot.get("tomorrowSchedule"), dict)
            else {}
        )
        trigger = self._attempt_for_turn(agent_id, run_id)
        rules = load_prompt_pack()
        remaining = [
            {
                "activityId": str(item.get("activityId") or ""),
                "title": str(item.get("title") or ""),
                "status": str(item.get("status") or "planned"),
                "startAt": str(item.get("startAt") or ""),
            }
            for item in list(today_schedule.get("activities") or [])
            if str(item.get("status") or "planned") not in {"completed", "cancelled", "skipped"}
        ][:6]
        tomorrow = [
            {
                "title": str(item.get("title") or ""),
                "startAt": str(item.get("startAt") or ""),
            }
            for item in list(tomorrow_schedule.get("activities") or [])[:5]
        ]
        dynamic_payload = {
            "mood": state.get("mood") or {},
            "energy": state.get("energy"),
            "currentActivityId": state.get("currentActivityId") or "",
            "todayRemaining": remaining,
            "tomorrowSummary": tomorrow,
            "relationshipSummary": state.get("relationshipSummary") or "",
            "proactiveTrigger": (
                {
                    "triggerId": trigger.get("triggerId"),
                    "reason": trigger.get("reason"),
                    "sourceEventId": trigger.get("sourceEventId"),
                }
                if trigger
                else None
            ),
            "sessionId": str(session_id or "").strip(),
        }
        return [
            {
                "key": "virtual_human_life_rules",
                "block": rules,
                "placement": "cache_prefix",
                "stability": "agent_static",
                "trust": "operator_controlled",
            },
            {
                "key": "virtual_human_life_state",
                "block": "## Current Virtual Life State\n"
                + json.dumps(dynamic_payload, ensure_ascii=False, sort_keys=True),
                "placement": "volatile_turn",
                "stability": "turn_dynamic",
                "trust": "derived_runtime",
            },
        ]

    def filter_tool_names(self, agent_id: str, tool_names: Iterable[str]) -> list[str]:
        names = [str(name or "").strip() for name in tool_names if str(name or "").strip()]
        binding = self.binding_for(agent_id)
        agent = self._agent(agent_id, include_archived=True)
        enabled = bool(
            binding
            and binding.get("enabled")
            and agent
            and str(agent.get("status") or "active").strip().lower() == "active"
        )
        if enabled:
            return names
        plugin_tools = set(VIRTUAL_HUMAN_TOOL_NAMES)
        return [name for name in names if name not in plugin_tools]

    def heartbeat_agent(
        self,
        agent_id: str,
        *,
        now: datetime | None = None,
        coalesced: bool = False,
    ) -> dict[str, Any]:
        with self._lock_for(agent_id):
            binding = self._require_enabled_binding(agent_id)
            current = (now or self._now()).astimezone(timezone.utc)
            proactive_reconciliation = self.reconcile_proactive_attempts(
                agent_id,
                now=current,
            )
            local_now = current.astimezone(self._zone(binding))
            local_date = local_now.date().isoformat()
            schedule = self.schedule_for(agent_id, local_date)
            state = self.store.read_json(agent_id, "state.json") or self._default_state(
                agent_id, binding
            )
            # ``localDate`` is a runtime projection, not an enable-time constant.  Keep
            # it aligned with the binding timezone even when the only thing that
            # happened since the previous heartbeat was crossing local midnight.
            state["localDate"] = local_now.date().isoformat()
            state["timezone"] = str(binding.get("timezone") or "Asia/Shanghai")
            if bool(state.get("lifePaused")):
                state["lastHeartbeatAt"] = _iso(current)
                state["updatedAt"] = _iso(current)
                self.store.write_json(agent_id, "state.json", state)
                return {
                    "agentId": str(agent_id).strip(),
                    "bindingRevision": int(binding.get("bindingRevision") or 0),
                    "completedEventCount": 0,
                    "completedEventIds": [],
                    "coalesced": bool(coalesced),
                    "paused": True,
                    "recoveredDeliveryCount": len(
                        proactive_reconciliation["deliveredDeliveryTokens"]
                    ),
                    "expiredDeliveryCount": len(
                        proactive_reconciliation["expiredDeliveryTokens"]
                    ),
                    "heartbeatAt": _iso(current),
                }
            completed_events: list[dict[str, Any]] = []
            current_activity_id = ""
            schedules_to_advance: list[tuple[str, dict[str, Any]]] = []
            # A freshly enabled binding may restart before its first periodic
            # heartbeat.  The initialized state's timestamp is still a valid
            # recovery anchor, while the 24-hour bound below prevents replaying
            # an arbitrarily old schedule.
            last_heartbeat = _parse_datetime(
                state.get("lastHeartbeatAt") or state.get("updatedAt")
            )
            if (
                coalesced
                and last_heartbeat is not None
                and timedelta(0) <= current - last_heartbeat <= timedelta(hours=24)
            ):
                previous_local_date = last_heartbeat.astimezone(
                    self._zone(binding)
                ).date().isoformat()
                if previous_local_date != local_date:
                    previous_schedule = self.store.read_json(
                        agent_id,
                        f"schedules/{previous_local_date}.json",
                    )
                    if previous_schedule is not None:
                        schedules_to_advance.append(
                            (previous_local_date, previous_schedule)
                        )
            schedules_to_advance.append((local_date, schedule))
            for schedule_local_date, candidate_schedule in schedules_to_advance:
                advanced = self._advance_schedule_activities(
                    agent_id,
                    schedule=candidate_schedule,
                    state=state,
                    current=current,
                    event_local_date=schedule_local_date,
                    coalesced=coalesced,
                )
                completed_events.extend(advanced["completedEvents"])
                if str(advanced.get("currentActivityId") or ""):
                    current_activity_id = str(advanced["currentActivityId"])
                if bool(advanced.get("changed")):
                    candidate_schedule["scheduleVersion"] = int(
                        candidate_schedule.get("scheduleVersion") or 1
                    ) + 1
                    candidate_schedule["updatedAt"] = _iso(current)
                    self.store.write_json(
                        agent_id,
                        f"schedules/{schedule_local_date}.json",
                        candidate_schedule,
                    )
            tomorrow = local_now.date() + timedelta(days=1)
            planning_time = self._clock(binding.get("nightlyPlanningTime"), default=time(22, 30))
            if local_now.time().replace(tzinfo=None) >= planning_time:
                tomorrow_path = f"schedules/{tomorrow.isoformat()}.json"
                if self.store.read_json(agent_id, tomorrow_path) is None:
                    self.store.write_json(
                        agent_id,
                        tomorrow_path,
                        self._generate_schedule(agent_id, tomorrow, binding),
                    )
            state["currentActivityId"] = current_activity_id
            state["lastHeartbeatAt"] = _iso(current)
            state["updatedAt"] = _iso(current)
            self.store.write_json(agent_id, "state.json", state)
            if completed_events and not coalesced and self.proactive_submitter is not None:
                latest = completed_events[-1]
                try:
                    self.request_proactive_message(
                        agent_id,
                        reason=f"刚刚{latest['outcome']['summary']}想自然地分享一下。",
                        source_event_id=str(latest.get("eventId") or ""),
                        valid_for_minutes=45,
                    )
                except VirtualHumanLifeError:
                    pass
            return {
                "agentId": str(agent_id).strip(),
                "bindingRevision": int(binding.get("bindingRevision") or 0),
                "completedEventCount": len(completed_events),
                "completedEventIds": [str(item.get("eventId") or "") for item in completed_events],
                "coalesced": bool(coalesced),
                "recoveredDeliveryCount": len(
                    proactive_reconciliation["deliveredDeliveryTokens"]
                ),
                "expiredDeliveryCount": len(
                    proactive_reconciliation["expiredDeliveryTokens"]
                ),
                "heartbeatAt": _iso(current),
            }

    def list_events(
        self,
        agent_id: str,
        *,
        date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.require_agent(agent_id)
        binding = self.binding_for(agent_id)
        if binding is None:
            return []
        local_date = _local_date_text(date or self._local_now(binding).date().isoformat())
        bounded = max(1, min(500, int(limit or 100)))
        return self.store.read_jsonl(agent_id, f"events/{local_date}.jsonl")[-bounded:]

    def list_diary(
        self,
        agent_id: str,
        *,
        local_date: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.require_agent(agent_id)
        if self.binding_for(agent_id) is None:
            return []
        bounded = max(1, min(500, int(limit or 100)))
        if local_date:
            date.fromisoformat(local_date)
            rows = self.store.read_jsonl(agent_id, f"diary/{local_date}.jsonl")
        else:
            diary_root = self.plugin_root(agent_id) / "diary"
            rows = []
            if diary_root.is_dir():
                for path in sorted(diary_root.glob("*.jsonl")):
                    rows.extend(self.store.read_jsonl(agent_id, f"diary/{path.name}"))
        rows.sort(key=lambda item: str(item.get("writtenAt") or item.get("localDate") or ""))
        return deepcopy(rows[-bounded:])

    def list_relationships(self, agent_id: str) -> list[dict[str, Any]]:
        self.require_agent(agent_id)
        payload = self.store.read_json(agent_id, "relationships.json") or {}
        rows = [item for item in list(payload.get("relationships") or []) if isinstance(item, dict)]
        rows.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
        return deepcopy(rows)

    def list_memory_promotion_receipts(
        self,
        agent_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        bounded = max(1, min(500, int(limit or 100)))
        return deepcopy(
            self.store.read_jsonl(agent_id, "memory/promotion_receipts.jsonl")[-bounded:]
        )

    def execute_command(
        self,
        agent_id: str,
        *,
        command: str,
        expected_version: int,
        idempotency_key: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_command = str(command or "").strip()
        normalized_key = str(idempotency_key or "").strip()
        if not normalized_command:
            raise VirtualHumanLifeError("Command is required.")
        if not normalized_key or len(normalized_key) > 200:
            raise VirtualHumanLifeError("A bounded idempotencyKey is required.")
        normalized_arguments = deepcopy(arguments or {})
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "agentId": str(agent_id or "").strip(),
                    "command": normalized_command,
                    "expectedVersion": int(expected_version),
                    "arguments": normalized_arguments,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        receipt_path = f"commands/{hashlib.sha256(normalized_key.encode('utf-8')).hexdigest()}.json"
        with self._lock_for(agent_id):
            previous = self.store.read_json(agent_id, receipt_path)
            if previous is not None:
                if (
                    str(previous.get("idempotencyKey") or "") != normalized_key
                    or str(previous.get("fingerprint") or "") != fingerprint
                ):
                    raise BindingConflictError("Idempotency key was already used for another command.")
                result = previous.get("response")
                return deepcopy(result) if isinstance(result, dict) else {}
            binding = self._require_enabled_binding(agent_id)
            state = self.store.read_json(agent_id, "state.json") or self._default_state(
                agent_id, binding
            )
            current_version = max(1, int(state.get("stateVersion") or 1))
            if int(expected_version) != current_version:
                raise BindingConflictError(
                    f"Life state version changed: expected {expected_version}, current {current_version}."
                )
            result = self._execute_command_locked(
                agent_id,
                binding=binding,
                state=state,
                command=normalized_command,
                arguments=normalized_arguments,
            )
            state["stateVersion"] = current_version + 1
            state["updatedAt"] = _iso(self._now())
            self.store.write_json(agent_id, "state.json", state)
            response = {
                "agentId": str(agent_id).strip(),
                "command": normalized_command,
                "idempotencyKey": normalized_key,
                "stateVersion": int(state["stateVersion"]),
                "result": result,
            }
            self.store.write_json(
                agent_id,
                receipt_path,
                {
                    "idempotencyKey": normalized_key,
                    "fingerprint": fingerprint,
                    "response": response,
                    "createdAt": _iso(self._now()),
                },
            )
            return deepcopy(response)

    def review_diary(self, agent_id: str, *, local_date: str) -> dict[str, Any]:
        binding = self._require_enabled_binding(agent_id)
        normalized_date = str(local_date or "").strip() or self._local_now(binding).date().isoformat()
        date.fromisoformat(normalized_date)
        events = self.list_events(agent_id, date=normalized_date, limit=500)
        existing = self.list_diary(agent_id, local_date=normalized_date, limit=500)
        recorded_source_ids = {
            str(source_id)
            for row in existing
            for source_id in list(row.get("sourceEventIds") or [])
            if str(source_id)
        }
        created: list[dict[str, Any]] = []
        promoted: list[dict[str, Any]] = []
        for event in events:
            event_id = str(event.get("eventId") or "").strip()
            outcome = event.get("outcome") if isinstance(event.get("outcome"), dict) else {}
            if (
                not event_id
                or event_id in recorded_source_ids
                or str(event.get("kind") or "") != "activity_completed"
                or str(outcome.get("status") or "") != "succeeded"
                or not str(outcome.get("summary") or "").strip()
            ):
                continue
            entry = {
                "diaryEntryId": f"diary-{uuid.uuid4().hex[:16]}",
                "agentId": str(agent_id).strip(),
                "localDate": normalized_date,
                "title": str(event.get("title") or "生活记录")[:160],
                "content": str(outcome.get("summary") or "").strip()[:1200],
                "sourceEventIds": [event_id],
                "writtenAt": _iso(self._now()),
                "projectionKind": "deterministic_event_summary",
            }
            self.store.append_jsonl(agent_id, f"diary/{normalized_date}.jsonl", entry)
            recorded_source_ids.add(event_id)
            created.append(entry)
            salience = _clamp(outcome.get("salienceScore"), 0, 100, 0)
            if salience < 70 or self.episodic_writer is None:
                continue
            try:
                episode = self.episodic_writer(
                    str(agent_id).strip(),
                    kind="private_note",
                    text=str(outcome.get("summary") or "").strip(),
                    refs=[{"type": "item", "id": event_id}],
                    occurred_at=str(event.get("occurredAt") or ""),
                )
            except Exception as exc:  # noqa: BLE001 - optional memory adapter boundary
                logger.warning(
                    "Virtual human memory promotion failed for agent=%s (%s).",
                    str(agent_id).strip(),
                    type(exc).__name__,
                )
                continue
            episode_id = str((episode or {}).get("episodeId") or "").strip()
            if not episode_id:
                continue
            receipt = {
                "receiptId": f"memory-promotion-{uuid.uuid4().hex[:16]}",
                "episodeId": episode_id,
                "sourceEventIds": [event_id],
                "promotionReason": "life_event_salience_threshold",
                "salienceScore": salience,
                "occurredAt": str(event.get("occurredAt") or ""),
                "writtenAt": _iso(self._now()),
            }
            self.store.append_jsonl(agent_id, "memory/promotion_receipts.jsonl", receipt)
            promoted.append(receipt)
        return {
            "localDate": normalized_date,
            "createdDiaryCount": len(created),
            "promotedMemoryCount": len(promoted),
            "diaryEntries": deepcopy(created),
            "memoryPromotionReceipts": deepcopy(promoted),
        }

    def preview_legacy_pet_import(
        self,
        agent_id: str,
        *,
        source_path: Path | None = None,
    ) -> dict[str, Any]:
        self._require_enabled_binding(agent_id)
        source, payload, digest = self._load_legacy_pet_payload(source_path)
        attributes = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
        diary = payload.get("diary") if isinstance(payload.get("diary"), dict) else {}
        social = payload.get("social") if isinstance(payload.get("social"), dict) else {}
        entries = [item for item in list(diary.get("entries") or []) if isinstance(item, dict)]
        friends = [item for item in list(social.get("friends") or []) if isinstance(item, dict)]
        return {
            "agentId": str(agent_id).strip(),
            "sourcePath": str(source),
            "sourceDigest": digest,
            "sourceVersion": str(payload.get("version") or "unknown"),
            "mappedState": {
                "mood": _clamp(attributes.get("mood"), 0, 100, 50),
                "energy": _clamp(attributes.get("energy"), 0, 100, 70),
                "userAffinity": _clamp(attributes.get("love"), 0, 100, 50),
            },
            "diaryEntryCount": len(entries),
            "relationshipCount": len(friends),
            "excludedFields": ["hunger"] if "hunger" in payload else [],
        }

    def import_legacy_pet(
        self,
        agent_id: str,
        *,
        source_path: Path | None = None,
        expected_source_digest: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        normalized_key = str(idempotency_key or "").strip()
        if not normalized_key or len(normalized_key) > 200:
            raise VirtualHumanLifeError("A bounded idempotencyKey is required.")
        receipt_path = (
            "migration_receipts/"
            + hashlib.sha256(normalized_key.encode("utf-8")).hexdigest()
            + ".json"
        )
        with self._lock_for(agent_id):
            existing = self.store.read_json(agent_id, receipt_path)
            if existing is not None:
                return deepcopy(existing)
            preview = self.preview_legacy_pet_import(agent_id, source_path=source_path)
            if str(preview["sourceDigest"]) != str(expected_source_digest or "").strip():
                raise BindingConflictError("Legacy pet source changed after preview.")
            _source, payload, _digest = self._load_legacy_pet_payload(source_path)
            state = self.store.read_json(agent_id, "state.json") or {}
            mapped = preview["mappedState"]
            mood = state.get("mood") if isinstance(state.get("mood"), dict) else {}
            mood["valence"] = max(-100, min(100, int(mapped["mood"]) * 2 - 100))
            mood["label"] = "happy" if int(mapped["mood"]) >= 65 else "calm"
            mood["updatedAt"] = _iso(self._now())
            state["mood"] = mood
            state["energy"] = int(mapped["energy"])
            state["stateVersion"] = max(1, int(state.get("stateVersion") or 1)) + 1
            state["legacyPetImportedAt"] = _iso(self._now())
            state["updatedAt"] = _iso(self._now())
            self.store.write_json(agent_id, "state.json", state)
            relationships = self.list_relationships(agent_id)
            relationship_by_target = {
                str(item.get("targetId") or ""): item for item in relationships
            }
            relationship_by_target["user"] = {
                "targetId": "user",
                "kind": "user",
                "intimacy": int(mapped["userAffinity"]),
                "trust": int(mapped["userAffinity"]),
                "interactionCount": 0,
                "legacyImport": True,
                "updatedAt": _iso(self._now()),
            }
            social = payload.get("social") if isinstance(payload.get("social"), dict) else {}
            for friend in list(social.get("friends") or []):
                if not isinstance(friend, dict):
                    continue
                target_id = str(friend.get("model_name") or "").strip()
                if not target_id:
                    continue
                affinity = _clamp(friend.get("friendship_level"), 0, 100, 0)
                relationship_by_target[target_id] = {
                    "targetId": target_id,
                    "kind": "legacy_model_friend",
                    "intimacy": affinity,
                    "trust": affinity,
                    "interactionCount": _clamp(friend.get("collaboration_count"), 0, 100000, 0),
                    "lastInteractionAt": str(friend.get("last_interaction") or ""),
                    "legacyImport": True,
                    "updatedAt": _iso(self._now()),
                }
            self.store.write_json(
                agent_id,
                "relationships.json",
                {"relationships": list(relationship_by_target.values()), "updatedAt": _iso(self._now())},
            )
            diary = payload.get("diary") if isinstance(payload.get("diary"), dict) else {}
            imported_diary = 0
            for item in list(diary.get("entries") or []):
                if not isinstance(item, dict):
                    continue
                local_date = str(item.get("date") or "").strip()
                try:
                    date.fromisoformat(local_date)
                except ValueError:
                    continue
                entry = {
                    "diaryEntryId": f"legacy-diary-{uuid.uuid4().hex[:16]}",
                    "agentId": str(agent_id).strip(),
                    "localDate": local_date,
                    "title": str(item.get("title") or "旧日记")[:160],
                    "content": str(item.get("content") or item.get("task_summary") or "")[:1200],
                    "sourceEventIds": [],
                    "writtenAt": _iso(self._now()),
                    "legacyImport": True,
                    "legacySourceDigest": str(preview["sourceDigest"]),
                }
                self.store.append_jsonl(agent_id, f"diary/{local_date}.jsonl", entry)
                imported_diary += 1
            receipt = {
                "receiptId": f"legacy-import-{uuid.uuid4().hex[:16]}",
                "agentId": str(agent_id).strip(),
                "status": "imported",
                "sourcePath": str(preview["sourcePath"]),
                "sourceDigest": str(preview["sourceDigest"]),
                "idempotencyKey": normalized_key,
                "importedDiaryCount": imported_diary,
                "importedRelationshipCount": len(relationship_by_target),
                "excludedFields": list(preview["excludedFields"]),
                "sourcePreserved": True,
                "importedAt": _iso(self._now()),
            }
            self.store.write_json(agent_id, receipt_path, receipt)
            return deepcopy(receipt)

    def request_proactive_message(
        self,
        agent_id: str,
        *,
        reason: str,
        source_event_id: str = "",
        valid_for_minutes: int = 30,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        with self._lock_for(agent_id):
            binding = self._require_enabled_binding(agent_id)
            if self.runtime_acceptance_provider is not None and not bool(
                self.runtime_acceptance_provider()
            ):
                raise VirtualHumanLifeError(
                    "Virtual human life runtime is stopping and no new proactive trigger is accepted."
                )
            if not bool(binding.get("proactiveMessagesEnabled", True)):
                raise BindingDisabledError("Proactive messages are disabled for this binding.")
            agent = self._agent(agent_id, include_archived=False)
            if not agent:
                raise AgentUnavailableError("The bound Agent is not active.")
            session_id = str(agent.get("directSessionId") or "").strip()
            if not session_id:
                raise AgentUnavailableError("The bound Agent has no direct session.")
            now = self._now()
            local_now = now.astimezone(self._zone(binding))
            self.reconcile_proactive_attempts(agent_id, now=now)
            normalized_source_event_id = str(source_event_id or "").strip()[:200]
            normalized_idempotency_key = str(idempotency_key or "").strip()
            if len(normalized_idempotency_key) > 200:
                raise VirtualHumanLifeError("A bounded proactive idempotencyKey is required.")
            # Heartbeat-originated messages get a stable key from their source event;
            # callers without a source event can still intentionally request a fresh
            # message by omitting the key.
            if not normalized_idempotency_key and normalized_source_event_id:
                normalized_idempotency_key = f"life-event:{normalized_source_event_id}"
            request_fingerprint = self._proactive_request_fingerprint(
                agent_id=str(agent_id).strip(),
                reason=str(reason or "").strip()[:600],
                source_event_id=normalized_source_event_id,
                idempotency_key=normalized_idempotency_key,
            )
            if normalized_idempotency_key:
                previous = self._proactive_attempt_for_idempotency_key(
                    agent_id,
                    normalized_idempotency_key,
                )
                if previous is not None:
                    previous_fingerprint = str(previous.get("idempotencyFingerprint") or "")
                    if previous_fingerprint and previous_fingerprint != request_fingerprint:
                        raise BindingConflictError(
                            "Proactive idempotency key was already used for another trigger."
                        )
                    return deepcopy(previous)
            identity_digest = (
                hashlib.sha256(
                    f"{str(agent_id).strip()}:{normalized_idempotency_key}".encode()
                ).hexdigest()[:24]
                if normalized_idempotency_key
                else ""
            )
            trigger_id = (
                f"life-trigger-{identity_digest}"
                if identity_digest
                else f"life-trigger-{uuid.uuid4().hex[:16]}"
            )
            attempt_id = (
                f"life-attempt-{identity_digest}"
                if identity_digest
                else f"life-attempt-{uuid.uuid4().hex[:16]}"
            )
            delivery_token = (
                f"life-delivery-{identity_digest}"
                if identity_digest
                else f"life-delivery-{uuid.uuid4().hex}"
            )
            expires_at = _iso(
                now + timedelta(minutes=_clamp(valid_for_minutes, 1, 1440, 30))
            )
            attempt = {
                "agentId": str(agent_id).strip(),
                "pluginId": PLUGIN_ID,
                "attemptId": attempt_id,
                "triggerId": trigger_id,
                "deliveryToken": delivery_token,
                "bindingRevision": int(binding.get("bindingRevision") or 0),
                "sessionId": session_id,
                "sourceEventId": normalized_source_event_id,
                "reason": str(reason or "").strip()[:600],
                "idempotencyKey": normalized_idempotency_key,
                "idempotencyFingerprint": request_fingerprint,
                "status": "candidate",
                "candidateAt": _iso(now),
                "createdAt": _iso(now),
                "expiresAt": expires_at,
                "validUntil": expires_at,
                "localDate": local_now.date().isoformat(),
            }
            self.store.append_jsonl(
                agent_id,
                "proactive/triggers.jsonl",
                {
                    "triggerId": trigger_id,
                    "agentId": str(agent_id).strip(),
                    "pluginId": PLUGIN_ID,
                    "bindingRevision": int(binding.get("bindingRevision") or 0),
                    "reason": attempt["reason"],
                    "sourceEventIds": (
                        [normalized_source_event_id] if normalized_source_event_id else []
                    ),
                    "targetSessionId": session_id,
                    "attemptId": attempt_id,
                    "deliveryToken": delivery_token,
                    "createdAt": _iso(now),
                    "expiresAt": expires_at,
                    "idempotencyKey": normalized_idempotency_key,
                    "status": "queued",
                },
            )
            self.store.append_jsonl(agent_id, "proactive/deliveries.jsonl", attempt)
            if self._inside_quiet_hours(local_now, binding.get("quietHours")):
                self._update_attempt(
                    agent_id,
                    delivery_token,
                    status="cancelled",
                    cancelledAt=_iso(now),
                    cancellationReason="quiet_hours",
                )
                raise VirtualHumanLifeError("Current local time is inside quiet hours.")
            usage = self.proactive_usage(agent_id, local_now.date().isoformat())
            if usage["remaining"] <= 0:
                self._update_attempt(
                    agent_id,
                    delivery_token,
                    status="cancelled",
                    cancelledAt=_iso(now),
                    cancellationReason="daily_limit_reached",
                )
                raise VirtualHumanLifeError("Daily proactive message limit reached.")
            latest_delivery = self._latest_delivered_attempt(agent_id)
            minimum_interval = timedelta(
                minutes=_clamp(
                    binding.get("proactiveMinimumIntervalMinutes"), 1, 1440, 180
                )
            )
            if latest_delivery:
                delivered_at = _parse_datetime(latest_delivery.get("deliveredAt"))
                if delivered_at and now - delivered_at < minimum_interval:
                    self._update_attempt(
                        agent_id,
                        delivery_token,
                        status="cancelled",
                        cancelledAt=_iso(now),
                        cancellationReason="minimum_interval_not_elapsed",
                    )
                    raise VirtualHumanLifeError("Proactive message minimum interval has not elapsed.")
            attempt = self._update_attempt(
                agent_id,
                delivery_token,
                status="reserved",
                reservedAt=_iso(self._now()),
            )
            if self.proactive_submitter is None:
                return deepcopy(attempt)
            if not self.proactive_turn_is_current(
                agent_id=agent_id,
                binding_revision=int(attempt["bindingRevision"]),
                delivery_token=delivery_token,
            ):
                return self._update_attempt(
                    agent_id,
                    delivery_token,
                    status="cancelled",
                    cancellationReason="binding_revision_changed_before_delivery",
                )
            try:
                accepted = self.proactive_submitter(
                    session_id=session_id,
                    agent_id=str(agent_id).strip(),
                    origin="proactive_plugin",
                    source_kind=PLUGIN_ID,
                    plugin_id=PLUGIN_ID,
                    trigger_id=trigger_id,
                    delivery_token=delivery_token,
                    binding_revision=int(attempt["bindingRevision"]),
                    trigger={
                        "reason": attempt["reason"],
                        "sourceEventId": attempt["sourceEventId"],
                        "idempotencyKey": attempt["idempotencyKey"],
                        "validUntil": attempt["validUntil"],
                    },
                )
            except Exception as exc:  # noqa: BLE001 - Session submitter adapter boundary
                return self._update_attempt(
                    agent_id,
                    delivery_token,
                    status="failed",
                    failedAt=_iso(self._now()),
                    failureType=type(exc).__name__,
                )
            if not bool((accepted or {}).get("accepted")):
                return self._update_attempt(
                    agent_id,
                    delivery_token,
                    status="failed",
                    failedAt=_iso(self._now()),
                    failureType="session_not_accepted",
                )
            return self._update_attempt(
                agent_id,
                delivery_token,
                status="delivering",
                turnId=str(accepted.get("turnId") or "").strip(),
                deliveryStartedAt=_iso(self._now()),
            )

    def reconcile_proactive_attempts(
        self,
        agent_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, list[str]]:
        """Recover persisted receipts and expire stale attempts without resending."""

        with self._lock_for(agent_id):
            current = (now or self._now()).astimezone(timezone.utc)
            rows = self.store.read_jsonl(agent_id, "proactive/deliveries.jsonl")
            delivered_tokens: list[str] = []
            expired_tokens: list[str] = []
            changed = False
            for index, row in enumerate(rows):
                status = str(row.get("status") or "").strip()
                delivery_token = str(row.get("deliveryToken") or "").strip()
                if not delivery_token:
                    continue
                receipt: dict[str, Any] | None = None
                if (
                    status in {"delivering", "expired", "cancelled"}
                    and str(row.get("turnId") or "").strip()
                    and self.delivery_receipt_resolver is not None
                ):
                    try:
                        candidate = self.delivery_receipt_resolver(agent_id, deepcopy(row))
                        receipt = candidate if isinstance(candidate, dict) else None
                    except Exception as exc:  # noqa: BLE001 - receipt adapter boundary
                        logger.warning(
                            "Virtual human delivery receipt lookup failed for agent=%s (%s).",
                            str(agent_id).strip(),
                            type(exc).__name__,
                        )
                        receipt = None
                receipt_event_id = str((receipt or {}).get("receiptEventId") or "").strip()
                if receipt_event_id:
                    delivered_at = str((receipt or {}).get("persistedAt") or "").strip()
                    rows[index] = {
                        **row,
                        "status": "delivered",
                        "deliveredAt": delivered_at or _iso(current),
                        "receiptEventId": receipt_event_id,
                        "updatedAt": _iso(current),
                    }
                    delivered_tokens.append(delivery_token)
                    changed = True
                    continue
                if status not in {"candidate", "reserved", "delivering"}:
                    continue
                expires_at = _parse_datetime(row.get("expiresAt") or row.get("validUntil"))
                if expires_at is None or current <= expires_at:
                    continue
                rows[index] = {
                    **row,
                    "status": "expired",
                    "expiredAt": _iso(current),
                    "expiryReason": (
                        "delivery_unconfirmed_before_expiry"
                        if status == "delivering"
                        else "candidate_window_elapsed"
                    ),
                    "updatedAt": _iso(current),
                }
                expired_tokens.append(delivery_token)
                changed = True
            if changed:
                self.store.write_jsonl(agent_id, "proactive/deliveries.jsonl", rows)
            self._sync_proactive_trigger_ledger(agent_id, rows)
            return {
                "deliveredDeliveryTokens": delivered_tokens,
                "expiredDeliveryTokens": expired_tokens,
            }

    def proactive_attempt(self, agent_id: str, delivery_token: str) -> dict[str, Any] | None:
        normalized = str(delivery_token or "").strip()
        return next(
            (
                deepcopy(item)
                for item in reversed(self.store.read_jsonl(agent_id, "proactive/deliveries.jsonl"))
                if str(item.get("deliveryToken") or "").strip() == normalized
            ),
            None,
        )

    def proactive_usage(self, agent_id: str, local_date: str) -> dict[str, int]:
        binding = self.binding_for(agent_id)
        limit = _clamp((binding or {}).get("proactiveDailyLimit"), 0, 20, 2) if binding else 0
        delivered_tokens = {
            str(item.get("deliveryToken") or "").strip()
            for item in self.store.read_jsonl(agent_id, "proactive/deliveries.jsonl")
            if str(item.get("status") or "").strip() == "delivered"
            and str(item.get("localDate") or "").strip() == str(local_date or "").strip()
            and str(item.get("deliveryToken") or "").strip()
        }
        delivered = len(delivered_tokens)
        return {"delivered": delivered, "limit": limit, "remaining": max(0, limit - delivered)}

    def record_delivery_receipt(
        self,
        agent_id: str,
        *,
        delivery_token: str,
        turn_id: str,
        receipt_event_id: str,
    ) -> dict[str, Any]:
        with self._lock_for(agent_id):
            attempt = self.proactive_attempt(agent_id, delivery_token)
            if attempt is None:
                raise VirtualHumanLifeError("Proactive delivery attempt not found.")
            if str(attempt.get("status") or "") == "delivered":
                if str(attempt.get("turnId") or "").strip() != str(turn_id or "").strip():
                    raise VirtualHumanLifeError("Delivery receipt turn id mismatch.")
                if str(attempt.get("receiptEventId") or "").strip() != str(receipt_event_id or "").strip():
                    raise VirtualHumanLifeError("Delivery receipt does not match the recorded receipt.")
                return attempt
            if str(attempt.get("status") or "") not in {
                "delivering",
                "expired",
                "cancelled",
            }:
                raise VirtualHumanLifeError(
                    "Only an admitted attempt can accept a persisted receipt."
                )
            if str(attempt.get("turnId") or "").strip() != str(turn_id or "").strip():
                raise VirtualHumanLifeError("Delivery receipt turn id mismatch.")
            normalized_receipt_event_id = str(receipt_event_id or "").strip()
            if not normalized_receipt_event_id:
                raise VirtualHumanLifeError("A persisted assistant receipt event is required.")
            authoritative_receipt: dict[str, Any] | None = None
            if self.delivery_receipt_resolver is not None:
                try:
                    resolved = self.delivery_receipt_resolver(agent_id, deepcopy(attempt))
                    authoritative_receipt = resolved if isinstance(resolved, dict) else None
                except Exception as exc:
                    raise VirtualHumanLifeError(
                        "Delivery receipt authority could not be verified."
                    ) from exc
                if str((authoritative_receipt or {}).get("receiptEventId") or "").strip() != normalized_receipt_event_id:
                    raise VirtualHumanLifeError(
                        "Delivery receipt does not match a persisted assistant event."
                    )
            binding = self.binding_for(agent_id)
            revision_matches = bool(
                binding
                and int(binding.get("bindingRevision") or 0)
                == int(attempt.get("bindingRevision") or 0)
            )
            valid_until = _parse_datetime(attempt.get("validUntil"))
            if (
                not revision_matches or (valid_until is not None and self._now() > valid_until)
            ) and authoritative_receipt is None:
                raise VirtualHumanLifeError(
                    "Delivery receipt is stale and has no authoritative persisted event."
                )
            return self._update_attempt(
                agent_id,
                delivery_token,
                status="delivered",
                deliveredAt=_iso(self._now()),
                receiptEventId=normalized_receipt_event_id,
            )

    def proactive_turn_is_current(
        self,
        *,
        agent_id: str,
        binding_revision: int,
        delivery_token: str,
    ) -> bool:
        self.reconcile_proactive_attempts(agent_id)
        binding = self.binding_for(agent_id)
        agent = self._agent(agent_id, include_archived=False)
        attempt = self.proactive_attempt(agent_id, delivery_token)
        if not binding or not binding.get("enabled") or not agent or not attempt:
            return False
        if int(binding.get("bindingRevision") or 0) != int(binding_revision):
            return False
        if int(attempt.get("bindingRevision") or 0) != int(binding_revision):
            return False
        if str(attempt.get("status") or "") not in {"reserved", "delivering"}:
            return False
        valid_until = _parse_datetime(attempt.get("validUntil"))
        return valid_until is None or self._now() <= valid_until

    def cancel_open_proactive_attempts(
        self,
        agent_id: str,
        *,
        reason: str,
        minimum_revision: int = 0,
    ) -> list[str]:
        with self._lock_for(agent_id):
            rows = self.store.read_jsonl(agent_id, "proactive/deliveries.jsonl")
            changed_tokens: list[str] = []
            changed = False
            for row in rows:
                if str(row.get("status") or "") not in {"candidate", "reserved", "delivering"}:
                    continue
                if minimum_revision and int(row.get("bindingRevision") or 0) >= minimum_revision:
                    continue
                row["status"] = "cancelled"
                row["cancelledAt"] = _iso(self._now())
                row["cancellationReason"] = str(reason or "binding_invalidated")[:160]
                changed_tokens.append(str(row.get("deliveryToken") or ""))
                changed = True
            if changed:
                self.store.write_jsonl(agent_id, "proactive/deliveries.jsonl", rows)
            self._sync_proactive_trigger_ledger(agent_id, rows)
            return changed_tokens

    def cancel_proactive_attempt(
        self,
        agent_id: str,
        delivery_token: str,
        *,
        reason: str,
    ) -> dict[str, Any] | None:
        """Cancel one open delivery without reopening terminal receipts."""

        with self._lock_for(agent_id):
            attempt = self.proactive_attempt(agent_id, delivery_token)
            if attempt is None:
                return None
            if str(attempt.get("status") or "") not in {"candidate", "reserved", "delivering"}:
                return attempt
            return self._update_attempt(
                agent_id,
                delivery_token,
                status="cancelled",
                cancelledAt=_iso(self._now()),
                cancellationReason=str(reason or "binding_invalidated")[:160],
            )

    def prepare_agent_archive(
        self,
        agent_id: str,
        *,
        stage_workspace: bool = False,
    ) -> dict[str, Any] | None:
        with self._lock_for(agent_id):
            binding = self.binding_for(agent_id)
            if binding is None:
                return None
            attempts = self.store.read_jsonl(agent_id, "proactive/deliveries.jsonl")
            previous_open = [
                deepcopy(item)
                for item in attempts
                if str(item.get("status") or "") in {"candidate", "reserved", "delivering"}
            ]
            invalidated = deepcopy(binding)
            invalidated["enabled"] = False
            invalidated["configVersion"] = int(binding.get("configVersion") or 0) + 1
            invalidated["bindingRevision"] = int(binding.get("bindingRevision") or 0) + 1
            invalidated["updatedAt"] = _iso(self._now())
            invalidated["disabledReason"] = "agent_archive_prepare"
            self.store.write_json(agent_id, "binding.json", invalidated)
            cancelled_tokens = self.cancel_open_proactive_attempts(
                agent_id,
                reason="agent_archive_prepare",
                minimum_revision=int(invalidated["bindingRevision"]),
            )
            token = {
                "agentId": str(agent_id).strip(),
                "previousBinding": binding,
                "previousOpenAttempts": previous_open,
                "cancelledDeliveryTokens": cancelled_tokens,
                "preparedRevision": int(invalidated["bindingRevision"]),
            }
            if stage_workspace:
                try:
                    staging_root = self._stage_plugin_workspace(agent_id)
                except Exception:
                    self.rollback_agent_archive(token)
                    raise
                if staging_root:
                    token["pluginPurgeStagingRoot"] = staging_root
            return token

    def rollback_agent_archive(self, token: dict[str, Any] | None) -> None:
        if not isinstance(token, dict):
            return
        agent_id = str(token.get("agentId") or "").strip()
        previous = token.get("previousBinding")
        if not agent_id or not isinstance(previous, dict):
            return
        with self._lock_for(agent_id):
            self._restore_staged_plugin_workspace(token)
            current = self.binding_for(agent_id)
            if current and int(current.get("bindingRevision") or 0) != int(
                token.get("preparedRevision") or 0
            ):
                raise BindingConflictError("Plugin binding changed after archive prepare.")
            restored = deepcopy(previous)
            restored["updatedAt"] = _iso(self._now())
            self.store.write_json(agent_id, "binding.json", restored)
            rows = self.store.read_jsonl(agent_id, "proactive/deliveries.jsonl")
            previous_by_token = {
                str(item.get("deliveryToken") or ""): item
                for item in list(token.get("previousOpenAttempts") or [])
                if isinstance(item, dict) and str(item.get("deliveryToken") or "")
            }
            for index, row in enumerate(rows):
                delivery_token = str(row.get("deliveryToken") or "")
                if (
                    delivery_token in previous_by_token
                    and str(row.get("status") or "") == "cancelled"
                    and str(row.get("cancellationReason") or "") == "agent_archive_prepare"
                ):
                    rows[index] = deepcopy(previous_by_token[delivery_token])
            self.store.write_jsonl(agent_id, "proactive/deliveries.jsonl", rows)
            self._cleanup_staged_plugin_workspace(token)

    def commit_agent_purge(self, token: dict[str, Any] | None) -> None:
        try:
            self._cleanup_staged_plugin_workspace(token)
        except Exception as exc:  # noqa: BLE001 - purge is already committed
            logger.warning(
                "Failed to clean virtual human purge staging (%s).",
                type(exc).__name__,
            )

    def _execute_command_locked(
        self,
        agent_id: str,
        *,
        binding: dict[str, Any],
        state: dict[str, Any],
        command: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        local_now = self._local_now(binding)
        local_date = str(arguments.get("localDate") or local_now.date().isoformat()).strip()
        date.fromisoformat(local_date)
        if command in {"pauseLife", "resumeLife"}:
            paused = command == "pauseLife"
            state["lifePaused"] = paused
            state["pausedReason"] = (
                str(arguments.get("reason") or "").strip()[:300] if paused else ""
            )
            return {"paused": paused}
        if command == "planTomorrow":
            target_date = (local_now.date() + timedelta(days=1)).isoformat()
            existing = self.store.read_json(agent_id, f"schedules/{target_date}.json")
            created = existing is None
            if existing is None:
                existing = self._generate_schedule(agent_id, date.fromisoformat(target_date), binding)
                self.store.write_json(agent_id, f"schedules/{target_date}.json", existing)
            return {"schedule": deepcopy(existing), "created": created}
        if command == "triggerDiaryReview":
            return self.review_diary(agent_id, local_date=local_date)
        if command == "recordRelationshipInteraction":
            target_id = str(arguments.get("targetId") or "").strip()
            if not target_id or len(target_id) > 160:
                raise VirtualHumanLifeError("Relationship targetId is required.")
            rows = self.list_relationships(agent_id)
            relationship = next(
                (item for item in rows if str(item.get("targetId") or "") == target_id),
                {
                    "targetId": target_id,
                    "kind": str(arguments.get("targetKind") or "person")[:80],
                    "intimacy": 50,
                    "trust": 50,
                    "interactionCount": 0,
                },
            )
            relationship["intimacy"] = _clamp(
                int(relationship.get("intimacy") or 50)
                + _clamp(arguments.get("intimacyDelta"), -20, 20, 0),
                0,
                100,
                50,
            )
            relationship["trust"] = _clamp(
                int(relationship.get("trust") or 50)
                + _clamp(arguments.get("trustDelta"), -20, 20, 0),
                0,
                100,
                50,
            )
            relationship["interactionCount"] = int(
                relationship.get("interactionCount") or 0
            ) + 1
            relationship["lastInteractionKind"] = str(
                arguments.get("kind") or "interaction"
            )[:120]
            relationship["lastInteractionNote"] = str(arguments.get("note") or "")[:600]
            relationship["lastInteractionAt"] = _iso(self._now())
            relationship["updatedAt"] = _iso(self._now())
            by_target = {str(item.get("targetId") or ""): item for item in rows}
            by_target[target_id] = relationship
            self.store.write_json(
                agent_id,
                "relationships.json",
                {"relationships": list(by_target.values()), "updatedAt": _iso(self._now())},
            )
            if target_id == "user":
                state["relationshipSummary"] = (
                    f"与用户的关系：亲近度 {relationship['intimacy']}/100，"
                    f"信任度 {relationship['trust']}/100。"
                )
            return {"relationship": deepcopy(relationship)}
        if command == "replan":
            previous = self.schedule_for(agent_id, local_date)
            generated = self._generate_schedule(agent_id, date.fromisoformat(local_date), binding)
            terminal = [
                item
                for item in list(previous.get("activities") or [])
                if isinstance(item, dict)
                and str(item.get("status") or "")
                in {"completed", "cancelled", "skipped", "failed", "unknown"}
            ]
            generated["activities"] = [*terminal, *generated["activities"]]
            generated["scheduleVersion"] = int(previous.get("scheduleVersion") or 1) + 1
            generated["planningMode"] = "deterministic_replan"
            generated["replanReason"] = str(arguments.get("reason") or "")[:300]
            self.store.write_json(agent_id, f"schedules/{local_date}.json", generated)
            return {"schedule": deepcopy(generated)}
        if command not in {
            "startActivity",
            "completeActivity",
            "cancelActivity",
            "skipActivity",
        }:
            raise VirtualHumanLifeError(f"Unsupported life command: {command}")
        schedule = self.schedule_for(agent_id, local_date)
        activity_id = str(arguments.get("activityId") or "").strip()
        activity = next(
            (
                item
                for item in list(schedule.get("activities") or [])
                if isinstance(item, dict)
                and str(item.get("activityId") or "").strip() == activity_id
            ),
            None,
        )
        if activity is None:
            raise VirtualHumanLifeError(f"Life activity not found: {activity_id}")
        status = str(activity.get("status") or "planned")
        if status in {"completed", "cancelled", "skipped", "failed", "unknown"}:
            raise BindingConflictError(f"Life activity is already terminal: {status}")
        now = self._now()
        if command == "startActivity":
            activity["status"] = "active"
            activity["startedAt"] = _iso(now)
            state["currentActivityId"] = activity_id
            result: dict[str, Any] = {"activity": deepcopy(activity)}
        elif command in {"cancelActivity", "skipActivity"}:
            activity["status"] = "cancelled" if command == "cancelActivity" else "skipped"
            activity["finishedAt"] = _iso(now)
            activity["reason"] = str(arguments.get("reason") or "")[:300]
            if str(state.get("currentActivityId") or "") == activity_id:
                state["currentActivityId"] = ""
            result = {"activity": deepcopy(activity)}
        else:
            outcome = arguments.get("outcome") if isinstance(arguments.get("outcome"), dict) else {}
            summary = str(outcome.get("summary") or "").strip()
            if str(outcome.get("status") or "") != "succeeded" or not summary:
                raise VirtualHumanLifeError(
                    "A succeeded outcome with a non-empty summary is required to complete an activity."
                )
            normalized_outcome = {
                **deepcopy(outcome),
                "status": "succeeded",
                "summary": summary[:1200],
                "recordedAt": _iso(now),
            }
            event = {
                "eventId": f"life-event-{uuid.uuid4().hex[:16]}",
                "agentId": str(agent_id).strip(),
                "activityId": activity_id,
                "kind": "activity_completed",
                "title": str(activity.get("title") or "计划活动"),
                "startedAt": str(activity.get("startedAt") or activity.get("startAt") or ""),
                "occurredAt": _iso(now),
                "outcome": normalized_outcome,
                "simulatedAfterRestart": False,
            }
            activity["status"] = "completed"
            activity["completedAt"] = _iso(now)
            activity["outcome"] = normalized_outcome
            activity["actualEventId"] = event["eventId"]
            self.store.append_jsonl(agent_id, f"events/{local_date}.jsonl", event)
            self._apply_completed_event_to_state(state, event, now)
            result = {"activity": deepcopy(activity), "eventId": event["eventId"]}
        schedule["scheduleVersion"] = int(schedule.get("scheduleVersion") or 1) + 1
        schedule["updatedAt"] = _iso(now)
        self.store.write_json(agent_id, f"schedules/{local_date}.json", schedule)
        return result

    def _load_legacy_pet_payload(
        self,
        source_path: Path | None,
    ) -> tuple[Path, dict[str, Any], str]:
        if source_path is None:
            from core.infrastructure import developer_sandbox

            source = developer_sandbox.formal_workspace_path(
                self.project_root, "memory", "pet_info.json"
            ).resolve()
        else:
            source = Path(source_path).expanduser().resolve()
        if source.name.lower() != "pet_info.json" or not source.is_file():
            raise VirtualHumanLifeError("Legacy pet_info.json was not found.")
        try:
            raw = source.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise VirtualHumanLifeError("Legacy pet_info.json is unreadable.") from exc
        if not isinstance(payload, dict):
            raise VirtualHumanLifeError("Legacy pet_info.json must contain an object.")
        return source, payload, hashlib.sha256(raw).hexdigest()

    def _ensure_initialized(self, agent_id: str, binding: dict[str, Any]) -> None:
        if self.store.read_json(agent_id, "state.json") is None:
            self.store.write_json(agent_id, "state.json", self._default_state(agent_id, binding))
        local_today = self._local_now(binding).date()
        for target_date in (local_today, local_today + timedelta(days=1)):
            path = f"schedules/{target_date.isoformat()}.json"
            if self.store.read_json(agent_id, path) is None:
                self.store.write_json(
                    agent_id,
                    path,
                    self._generate_schedule(agent_id, target_date, binding),
                )

    def _default_binding(self, agent_id: str) -> dict[str, Any]:
        return {
            "agentId": str(agent_id).strip(),
            "pluginId": PLUGIN_ID,
            "enabled": False,
            "configVersion": 0,
            "bindingRevision": 0,
            "timezone": "Asia/Shanghai",
            "nightlyPlanningTime": "22:30",
            "heartbeatIntervalSeconds": 60,
            "autonomyLevel": "autonomous",
            "proactiveMessagesEnabled": True,
            "proactiveDailyLimit": 2,
            "proactiveMinimumIntervalMinutes": 180,
            "quietHours": {"start": "23:00", "end": "08:00"},
            "toolBundleId": TOOL_BUNDLE_ID,
            "promptPackId": PROMPT_PACK_ID,
            "storageSchemaVersion": STORAGE_SCHEMA_VERSION,
        }

    def _normalize_binding(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._default_binding(str(payload.get("agentId") or ""))
        normalized.update(payload)
        normalized.update(self._normalized_binding_config(normalized))
        normalized["enabled"] = bool(payload.get("enabled"))
        normalized["configVersion"] = max(0, int(payload.get("configVersion") or 0))
        normalized["bindingRevision"] = max(0, int(payload.get("bindingRevision") or 0))
        return normalized

    def _normalized_binding_config(self, config: dict[str, Any]) -> dict[str, Any]:
        timezone_name = str(config.get("timezone") or "Asia/Shanghai").strip()
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise VirtualHumanLifeError(f"Unknown timezone: {timezone_name}") from exc
        autonomy = str(config.get("autonomyLevel") or "autonomous").strip().lower()
        if autonomy not in {"assisted", "autonomous"}:
            raise VirtualHumanLifeError("autonomyLevel must be assisted or autonomous.")
        quiet = config.get("quietHours") if isinstance(config.get("quietHours"), dict) else {}
        return {
            "timezone": timezone_name,
            "nightlyPlanningTime": self._clock_text(
                config.get("nightlyPlanningTime"), default="22:30"
            ),
            "heartbeatIntervalSeconds": _clamp(
                config.get("heartbeatIntervalSeconds"), 15, 3600, 60
            ),
            "autonomyLevel": autonomy,
            "proactiveMessagesEnabled": bool(
                config.get("proactiveMessagesEnabled", True)
            ),
            "proactiveDailyLimit": _clamp(config.get("proactiveDailyLimit"), 0, 20, 2),
            "proactiveMinimumIntervalMinutes": _clamp(
                config.get("proactiveMinimumIntervalMinutes"), 1, 1440, 180
            ),
            "quietHours": {
                "start": self._clock_text(quiet.get("start"), default="23:00"),
                "end": self._clock_text(quiet.get("end"), default="08:00"),
            },
        }

    def _default_state(self, agent_id: str, binding: dict[str, Any]) -> dict[str, Any]:
        now = self._now()
        local_now = now.astimezone(self._zone(binding))
        return {
            "schemaVersion": STORAGE_SCHEMA_VERSION,
            "agentId": str(agent_id).strip(),
            "stateVersion": 1,
            "localDate": local_now.date().isoformat(),
            "timezone": str(binding.get("timezone") or "Asia/Shanghai"),
            "currentLocation": "home",
            "currentActivityId": "",
            "mood": {
                "label": "calm",
                "valence": 12,
                "arousal": 28,
                "stability": 72,
                "causeEventIds": [],
                "updatedAt": _iso(now),
            },
            "energy": 76,
            "sleepState": "awake",
            "socialNeed": 42,
            "relationshipSummary": "正在与用户建立尊重边界的长期陪伴关系。",
            "lifePaused": False,
            "scheduleVersion": 1,
            "lastHeartbeatAt": "",
            "updatedAt": _iso(now),
        }

    def _generate_schedule(
        self,
        agent_id: str,
        local_date: date,
        binding: dict[str, Any],
    ) -> dict[str, Any]:
        zone = self._zone(binding)
        seed = int(
            hashlib.sha256(f"{agent_id}:{local_date.isoformat()}".encode()).hexdigest()[:8],
            16,
        )
        variants = [
            ("整理房间和做早餐", "专注处理自己的学习与创作", "傍晚散步", "写私人日记并放松"),
            ("慢慢醒来并准备早餐", "阅读和推进个人项目", "做一顿晚饭", "听音乐并回顾一天"),
            ("晨间伸展和早餐", "练习一项长期技能", "去附近走走", "整理明天的想法"),
        ]
        titles = variants[seed % len(variants)]
        slots = [(8, 0, 9, 0), (10, 0, 12, 0), (18, 0, 19, 0), (21, 30, 22, 15)]
        activities: list[dict[str, Any]] = []
        for index, (title, slot) in enumerate(zip(titles, slots), start=1):
            start_hour, start_minute, end_hour, end_minute = slot
            start_at = datetime.combine(local_date, time(start_hour, start_minute), tzinfo=zone)
            end_at = datetime.combine(local_date, time(end_hour, end_minute), tzinfo=zone)
            activities.append(
                {
                    "activityId": f"life-{local_date.isoformat()}-{index}",
                    "title": title,
                    "kind": "simulated",
                    "startAt": _iso(start_at),
                    "endAt": _iso(end_at),
                    "status": "planned",
                    "origin": "deterministic_daily_plan",
                }
            )
        return {
            "schemaVersion": STORAGE_SCHEMA_VERSION,
            "agentId": str(agent_id).strip(),
            "localDate": local_date.isoformat(),
            "timezone": str(binding.get("timezone") or "Asia/Shanghai"),
            "scheduleVersion": 1,
            "planningMode": "deterministic_mvp",
            "activities": activities,
            "createdAt": _iso(self._now()),
            "updatedAt": _iso(self._now()),
        }

    def _advance_schedule_activities(
        self,
        agent_id: str,
        *,
        schedule: dict[str, Any],
        state: dict[str, Any],
        current: datetime,
        event_local_date: str,
        coalesced: bool,
    ) -> dict[str, Any]:
        completed_events: list[dict[str, Any]] = []
        current_activity_id = ""
        changed = False
        for activity in list(schedule.get("activities") or []):
            if not isinstance(activity, dict):
                continue
            status = str(activity.get("status") or "planned").strip().lower()
            starts_at = _parse_datetime(activity.get("startAt"))
            ends_at = _parse_datetime(activity.get("endAt"))
            if status in {"completed", "cancelled", "skipped", "failed", "unknown"}:
                continue
            if starts_at and starts_at <= current and (not ends_at or current < ends_at):
                if status == "planned":
                    activity["status"] = "active"
                    activity["startedAt"] = _iso(current)
                    changed = True
                current_activity_id = str(activity.get("activityId") or "")
                continue
            if ends_at is None or current < ends_at:
                continue
            kind = str(activity.get("kind") or "simulated").strip().lower()
            if kind != "simulated":
                activity["status"] = "unknown"
                activity["unknownReason"] = "tool_activity_has_no_verified_outcome"
                activity["updatedAt"] = _iso(current)
                changed = True
                continue
            outcome = {
                "status": "succeeded",
                "kind": "deterministic_simulation",
                "summary": f"完成了{activity.get('title') or '计划活动'!s}。",
                "recordedAt": _iso(current),
            }
            event = {
                "eventId": f"life-event-{uuid.uuid4().hex[:16]}",
                "agentId": str(agent_id).strip(),
                "activityId": str(activity.get("activityId") or ""),
                "kind": "activity_completed",
                "title": str(activity.get("title") or "计划活动"),
                "occurredAt": _iso(current),
                "outcome": outcome,
                "simulatedAfterRestart": bool(coalesced),
            }
            activity["status"] = "completed"
            activity["completedAt"] = _iso(current)
            activity["outcome"] = outcome
            if coalesced:
                activity["simulatedAfterRestart"] = True
            self.store.append_jsonl(
                agent_id,
                f"events/{event_local_date}.jsonl",
                event,
            )
            completed_events.append(event)
            changed = True
            self._apply_completed_event_to_state(state, event, current)
        return {
            "changed": changed,
            "currentActivityId": current_activity_id,
            "completedEvents": completed_events,
        }

    def _apply_completed_event_to_state(
        self,
        state: dict[str, Any],
        event: dict[str, Any],
        now: datetime,
    ) -> None:
        mood = state.get("mood") if isinstance(state.get("mood"), dict) else {}
        valence = _clamp(mood.get("valence"), -100, 100, 0)
        mood.update(
            {
                "label": "happy" if valence >= 5 else "calm",
                "valence": min(100, valence + 5),
                "arousal": _clamp(mood.get("arousal"), 0, 100, 30),
                "stability": _clamp(mood.get("stability"), 0, 100, 70),
                "causeEventIds": (
                    [*list(mood.get("causeEventIds") or []), str(event.get("eventId") or "")]
                )[-8:],
                "updatedAt": _iso(now),
            }
        )
        state["mood"] = mood
        state["energy"] = max(0, _clamp(state.get("energy"), 0, 100, 70) - 2)
        state["currentActivityId"] = ""

    def _require_enabled_binding(self, agent_id: str) -> dict[str, Any]:
        binding = self.binding_for(agent_id)
        agent = self._agent(agent_id, include_archived=False)
        if not binding or not bool(binding.get("enabled")):
            raise BindingDisabledError("virtual-human-life is not enabled for this Agent.")
        if not agent:
            raise AgentUnavailableError("The bound Agent is not active.")
        return binding

    def _agent(self, agent_id: str, *, include_archived: bool) -> dict[str, Any] | None:
        try:
            return self.agent_loader(agent_id, include_archived=include_archived)
        except TypeError:
            return self.agent_loader(agent_id)

    def _lock_for(self, agent_id: str) -> threading.RLock:
        normalized = str(agent_id or "").strip()
        with self._agent_locks_guard:
            lock = self._agent_locks.get(normalized)
            if lock is None:
                lock = threading.RLock()
                self._agent_locks[normalized] = lock
            return lock

    def _now(self) -> datetime:
        value = self.now_provider()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _zone(self, binding: dict[str, Any]) -> ZoneInfo:
        return ZoneInfo(str(binding.get("timezone") or "Asia/Shanghai"))

    def _local_now(self, binding: dict[str, Any]) -> datetime:
        return self._now().astimezone(self._zone(binding))

    @staticmethod
    def _clock(value: object, *, default: time) -> time:
        raw = str(value or "").strip()
        try:
            hour, minute = raw.split(":", maxsplit=1)
            return time(_clamp(hour, 0, 23, default.hour), _clamp(minute, 0, 59, default.minute))
        except (ValueError, AttributeError):
            return default

    def _clock_text(self, value: object, *, default: str) -> str:
        parsed = self._clock(value, default=self._clock(default, default=time(0, 0)))
        return f"{parsed.hour:02d}:{parsed.minute:02d}"

    def _inside_quiet_hours(self, local_now: datetime, quiet_hours: object) -> bool:
        quiet = quiet_hours if isinstance(quiet_hours, dict) else {}
        start = self._clock(quiet.get("start"), default=time(23, 0))
        end = self._clock(quiet.get("end"), default=time(8, 0))
        current = local_now.time().replace(tzinfo=None)
        if start == end:
            return False
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def _update_attempt(
        self,
        agent_id: str,
        delivery_token: str,
        **patch: Any,
    ) -> dict[str, Any]:
        rows = self.store.read_jsonl(agent_id, "proactive/deliveries.jsonl")
        normalized = str(delivery_token or "").strip()
        for index in range(len(rows) - 1, -1, -1):
            if str(rows[index].get("deliveryToken") or "").strip() != normalized:
                continue
            rows[index] = {**rows[index], **patch, "updatedAt": _iso(self._now())}
            self.store.write_jsonl(agent_id, "proactive/deliveries.jsonl", rows)
            self._sync_proactive_trigger_ledger(agent_id, rows)
            return deepcopy(rows[index])
        raise VirtualHumanLifeError("Proactive delivery attempt not found.")

    @staticmethod
    def _proactive_request_fingerprint(
        *,
        agent_id: str,
        reason: str,
        source_event_id: str,
        idempotency_key: str,
    ) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "agentId": agent_id,
                    "reason": reason,
                    "sourceEventId": source_event_id,
                    "idempotencyKey": idempotency_key,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def _proactive_attempt_for_idempotency_key(
        self,
        agent_id: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        normalized = str(idempotency_key or "").strip()
        if not normalized:
            return None
        return next(
            (
                deepcopy(item)
                for item in reversed(self.store.read_jsonl(agent_id, "proactive/deliveries.jsonl"))
                if str(item.get("idempotencyKey") or "").strip() == normalized
            ),
            None,
        )

    def _sync_proactive_trigger_ledger(
        self,
        agent_id: str,
        attempts: list[dict[str, Any]],
    ) -> None:
        trigger_rows = self.store.read_jsonl(agent_id, "proactive/triggers.jsonl")
        if not trigger_rows:
            return
        by_trigger = {
            str(item.get("triggerId") or "").strip(): item
            for item in attempts
            if str(item.get("triggerId") or "").strip()
        }
        status_map = {
            "candidate": "queued",
            "reserved": "leased",
            "delivering": "generating",
            "delivered": "generated",
            "failed": "failed",
            "expired": "expired",
            "cancelled": "cancelled",
        }
        changed = False
        now = _iso(self._now())
        for index, row in enumerate(trigger_rows):
            trigger_id = str(row.get("triggerId") or "").strip()
            attempt = by_trigger.get(trigger_id)
            if attempt is None:
                continue
            next_status = status_map.get(str(attempt.get("status") or "").strip())
            if not next_status:
                continue
            if (
                str(row.get("status") or "") != next_status
                or str(row.get("attemptId") or "") != str(attempt.get("attemptId") or "")
                or str(row.get("deliveryToken") or "") != str(attempt.get("deliveryToken") or "")
            ):
                trigger_rows[index] = {
                    **row,
                    "status": next_status,
                    "attemptId": str(attempt.get("attemptId") or ""),
                    "deliveryToken": str(attempt.get("deliveryToken") or ""),
                    "updatedAt": now,
                }
                changed = True
        if changed:
            self.store.write_jsonl(agent_id, "proactive/triggers.jsonl", trigger_rows)

    def _latest_delivered_attempt(self, agent_id: str) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in reversed(self.store.read_jsonl(agent_id, "proactive/deliveries.jsonl"))
                if str(item.get("status") or "") == "delivered"
            ),
            None,
        )

    def _attempt_for_turn(self, agent_id: str, run_id: str) -> dict[str, Any] | None:
        normalized = str(run_id or "").strip()
        if not normalized:
            return None
        return next(
            (
                item
                for item in reversed(self.store.read_jsonl(agent_id, "proactive/deliveries.jsonl"))
                if str(item.get("turnId") or "").strip() == normalized
                and str(item.get("status") or "") in {"delivering", "delivered"}
            ),
            None,
        )


__all__ = [
    "AgentUnavailableError",
    "BindingConflictError",
    "BindingDisabledError",
    "VirtualHumanLifeError",
    "VirtualHumanLifeService",
    "VirtualHumanLifeStorageError",
]
