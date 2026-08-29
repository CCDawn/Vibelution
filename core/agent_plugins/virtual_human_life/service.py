"""Virtual human life domain service.

The service is deliberately Agent-scoped. Merely importing the plugin or reading an
unbound Agent never creates storage, prompt segments, tools, timers, or messages.
"""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import shutil
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterable
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .affect import (
    BASELINE_MOOD,
    episode_from_life_event,
    episode_from_relationship_event,
    project_affect,
)
from .causal_contracts import CAUSAL_SCHEMA_VERSION, authorized_reuse_receipt
from .conversation_continuity import (
    build_proactive_candidate,
    evaluate_proactive_candidate,
    project_open_loops,
    resolve_open_loop,
    upsert_open_loop,
)
from .domain import (
    apply_completed_event_to_state,
    apply_relationship_interaction_to_state,
    compute_event_salience,
    evolve_state_for_time,
)
from .drives import (
    apply_completed_event_to_drives,
    default_drive_projection,
    link_schedule_to_drives,
    prompt_drive_summary,
)
from .manifest import (
    PLUGIN_ID,
    PROMPT_PACK_FILES,
    PROMPT_PACK_ID,
    STORAGE_SCHEMA_VERSION,
    TOOL_BUNDLE_ID,
    VIRTUAL_HUMAN_TOOL_NAMES,
)
from .planning import (
    PLANNER_ACTIVITY_KINDS,
    build_deterministic_schedule,
    validate_schedule_proposal,
)
from .prompt_pack import load_prompt_pack
from .relationship_events import make_relationship_event, project_relationships
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
        episodic_lister: Callable[..., list[dict[str, Any]]] | None = None,
        schedule_planner: Callable[[dict[str, Any]], Any] | None = None,
        schedule_planner_timeout_seconds: float = 2.0,
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
        self.episodic_lister = episodic_lister
        self.schedule_planner = schedule_planner
        self.schedule_planner_timeout_seconds = max(
            0.2, min(30.0, float(schedule_planner_timeout_seconds or 2.0))
        )
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
                "causal": None,
                "health": self._health_projection(agent_id, binding=None),
            }
        local_now = self._local_now(binding)
        today = local_now.date().isoformat()
        tomorrow = (local_now.date() + timedelta(days=1)).isoformat()
        state = self.store.read_json(agent_id, "state.json")
        today_schedule = self.store.read_json(agent_id, f"schedules/{today}.json")
        tomorrow_schedule = self.store.read_json(agent_id, f"schedules/{tomorrow}.json")
        usage = self.proactive_usage(agent_id, today)
        causal = self._causal_projection(agent_id, now=local_now)
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
            "causal": causal,
            "storageSchemaVersion": STORAGE_SCHEMA_VERSION,
            "toolBundleId": TOOL_BUNDLE_ID,
            "promptPackId": PROMPT_PACK_ID,
            "health": self._health_projection(agent_id, binding=binding),
        }

    def schedule_for(self, agent_id: str, local_date: str) -> dict[str, Any]:
        self.require_agent(agent_id)
        local_date = _local_date_text(local_date)
        payload = self.store.read_json(agent_id, f"schedules/{local_date}.json")
        if payload is None:
            binding = self._require_enabled_binding(agent_id)
            # Reads and ordinary snapshot projections must stay cheap and
            # deterministic.  The injected Agent planner is reserved for an
            # explicit replan/planTomorrow command or the nightly heartbeat;
            # otherwise a missing historical file could block a UI request on
            # an external model call.
            payload = self._deterministic_schedule(
                agent_id, date.fromisoformat(local_date), binding
            )
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
        normalized = link_schedule_to_drives(
            normalized,
            self.store.read_json(agent_id, "drives/state.json")
            or default_drive_projection(now=self._now()),
        )
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
        causal = snapshot.get("causal") if isinstance(snapshot.get("causal"), dict) else {}
        open_loop_projection = (
            causal.get("openLoops") if isinstance(causal.get("openLoops"), dict) else {}
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
            "lifeDrives": prompt_drive_summary(
                causal.get("drives") if isinstance(causal.get("drives"), dict) else {}
            ),
            "affect": {
                "expressionTier": str(
                    (causal.get("affect") or {}).get("expressionTier") or "natural"
                ),
                "activeEpisodeIds": list(
                    (causal.get("affect") or {}).get("activeEpisodeIds") or []
                )[:8],
            },
            "openLoops": [
                {
                    "topicKey": str(item.get("topicKey") or ""),
                    "kind": str(item.get("kind") or "topic"),
                    "summary": str(item.get("summary") or "")[:160],
                    "expiresAt": str(item.get("expiresAt") or ""),
                }
                for item in list(open_loop_projection.get("open") or [])[:6]
                if isinstance(item, dict)
            ],
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

    def filter_tool_names(
        self,
        agent_id: str,
        tool_names: Iterable[str],
        *,
        runtime_context: dict[str, Any] | None = None,
    ) -> list[str]:
        names = [str(name or "").strip() for name in tool_names if str(name or "").strip()]
        binding = self.binding_for(agent_id)
        agent = self._agent(agent_id, include_archived=True)
        enabled = bool(
            binding
            and binding.get("enabled")
            and agent
            and str(agent.get("status") or "active").strip().lower() == "active"
        )
        plugin_tools = set(VIRTUAL_HUMAN_TOOL_NAMES)
        if enabled:
            allowed_tools = set(plugin_tools)
            runtime_metadata = (
                runtime_context.get("runtimeMetadata")
                if isinstance(runtime_context, dict)
                and isinstance(runtime_context.get("runtimeMetadata"), dict)
                else {}
            )
            life_runtime = (
                runtime_metadata.get("virtualHumanLife")
                if isinstance(runtime_metadata.get("virtualHumanLife"), dict)
                else {}
            )
            if str(life_runtime.get("kind") or "").strip() == "tool_activity":
                allowed_tools.update(
                    str(name or "").strip()
                    for name in list(life_runtime.get("requiredToolNames") or [])
                    if str(name or "").strip()
                )
            # ``names`` has already been intersected with the Agent ToolPolicy.
            # This second boundary keeps ordinary companion dialogue on the
            # dedicated plugin bundle while allowing a scheduled tool activity
            # only the exact tools it declared up front.
            return [name for name in names if name in allowed_tools]
        return [name for name in names if name not in plugin_tools]

    def heartbeat_agent(
        self,
        agent_id: str,
        *,
        now: datetime | None = None,
        coalesced: bool = False,
        allow_planner: bool = True,
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
            affect_baseline = self._affect_baseline(agent_id, state=state)
            evolved_state = evolve_state_for_time(
                state,
                now=local_now,
                baseline_valence=_clamp(
                    affect_baseline.get("valence"), -100, 100, 12
                ),
            )
            state.clear()
            state.update(evolved_state)
            affect_projection = project_affect(
                self.store.read_jsonl(agent_id, "affect/episodes.jsonl"),
                now=current,
                baseline_mood=affect_baseline,
            )
            self.store.write_json(agent_id, "affect/state.json", affect_projection)
            state["mood"] = deepcopy(affect_projection["mood"])
            completed_events: list[dict[str, Any]] = []
            tool_activities_to_dispatch: list[tuple[str, dict[str, Any]]] = []
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
                tool_activities_to_dispatch.extend(
                    (schedule_local_date, item)
                    for item in advanced["toolActivitiesToDispatch"]
                )
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
            if allow_planner and local_now.time().replace(tzinfo=None) >= planning_time:
                tomorrow_path = f"schedules/{tomorrow.isoformat()}.json"
                existing_tomorrow = self.store.read_json(agent_id, tomorrow_path)
                needs_agent_planning = bool(
                    self.schedule_planner is not None
                    and isinstance(existing_tomorrow, dict)
                    and str(existing_tomorrow.get("plannerStatus") or "").strip()
                    not in {"accepted", "fallback"}
                )
                if existing_tomorrow is None or needs_agent_planning:
                    generated_tomorrow = self._generate_schedule(
                        agent_id, tomorrow, binding
                    )
                    if isinstance(existing_tomorrow, dict):
                        generated_tomorrow["scheduleVersion"] = int(
                            existing_tomorrow.get("scheduleVersion") or 1
                        ) + 1
                        generated_tomorrow["planningReviewAt"] = _iso(current)
                    self.store.write_json(
                        agent_id,
                        tomorrow_path,
                        generated_tomorrow,
                    )
            elif self.store.read_json(agent_id, f"schedules/{tomorrow.isoformat()}.json") is None:
                # Keep startup/pre-night behavior deterministic and cheap.  The
                # nightly pass above is the only point that asks an injected
                # planner to replace this provisional schedule.
                self.store.write_json(
                    agent_id,
                    f"schedules/{tomorrow.isoformat()}.json",
                    self._deterministic_schedule(agent_id, tomorrow, binding),
                )
            state["currentActivityId"] = current_activity_id
            state["sleepState"] = self._derive_sleep_state(
                local_now=local_now,
                binding=binding,
                schedule=schedule,
                current_activity_id=current_activity_id,
            )
            state["lastHeartbeatAt"] = _iso(current)
            state["updatedAt"] = _iso(current)
            self.store.write_json(agent_id, "state.json", state)
            dispatched_tool_activity_count = 0
            for dispatch_date, activity in tool_activities_to_dispatch:
                if coalesced or str(binding.get("autonomyLevel") or "") != "autonomous":
                    continue
                if self._dispatch_tool_activity(
                    agent_id,
                    local_date=dispatch_date,
                    activity=activity,
                ):
                    dispatched_tool_activity_count += 1
            diary_created = 0
            memory_promoted = 0
            review_dates = {local_date}
            review_dates.update(date_text for date_text, _schedule in schedules_to_advance)
            for review_date in sorted(review_dates):
                try:
                    review = self._review_diary_locked(agent_id, local_date=review_date)
                except Exception as exc:  # noqa: BLE001 - diary failure never rolls back events
                    logger.warning(
                        "Virtual human diary review failed for agent=%s date=%s (%s).",
                        str(agent_id).strip(),
                        review_date,
                        type(exc).__name__,
                    )
                    continue
                diary_created += int(review.get("createdDiaryCount") or 0)
                memory_promoted += int(review.get("promotedMemoryCount") or 0)
            candidate_result = {
                "evaluatedCandidateCount": 0,
                "selectedCandidateId": "",
            }
            if not coalesced:
                candidate_result = self._evaluate_proactive_candidates(
                    agent_id,
                    now=current,
                    binding=binding,
                    state=state,
                    dispatch=self.proactive_submitter is not None,
                )
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
                "createdDiaryCount": diary_created,
                "promotedMemoryCount": memory_promoted,
                "dispatchedToolActivityCount": dispatched_tool_activity_count,
                **candidate_result,
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

    def list_open_loops(self, agent_id: str) -> dict[str, Any]:
        self.require_agent(agent_id)
        return project_open_loops(
            self.store.read_jsonl(agent_id, "conversation/open_loops.jsonl"),
            now=self._now(),
        )

    def list_proactive_candidates(
        self,
        agent_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        self.require_agent(agent_id)
        bounded = max(1, min(100, int(limit or 20)))
        return deepcopy(
            self.store.read_jsonl(agent_id, "proactive/candidates.jsonl")[-bounded:]
        )

    def _causal_projection(
        self,
        agent_id: str,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        drives = self.store.read_json(agent_id, "drives/state.json") or default_drive_projection(
            now=now
        )
        affect = project_affect(
            self.store.read_jsonl(agent_id, "affect/episodes.jsonl"),
            now=now,
            baseline_mood=self._affect_baseline(agent_id),
        )
        open_loops = project_open_loops(
            self.store.read_jsonl(agent_id, "conversation/open_loops.jsonl"),
            now=now,
        )
        return {
            "schemaVersion": CAUSAL_SCHEMA_VERSION,
            "drives": drives,
            "affect": affect,
            "relationships": self.list_relationships(agent_id),
            "openLoops": open_loops,
            "proactiveCandidates": self.list_proactive_candidates(agent_id),
            "reuseReceipt": authorized_reuse_receipt(),
        }

    def list_memory_promotion_receipts(
        self,
        agent_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.require_agent(agent_id)
        bounded = max(1, min(500, int(limit or 100)))
        return deepcopy(
            self.store.read_jsonl(agent_id, "memory/promotion_receipts.jsonl")[-bounded:]
        )

    def list_memories(
        self,
        agent_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Project VHL promotion receipts onto the Agent's current episodes.

        The receipt ledger remains the plugin's promotion authority, while the
        canonical episodic event store remains the source of memory text.  No
        second memory store is created and a receipt for another Agent can never
        be joined because both reads are scoped by ``agent_id``.
        """

        self.require_agent(agent_id)
        bounded = max(1, min(500, int(limit or 100)))
        receipts = self.store.read_jsonl(agent_id, "memory/promotion_receipts.jsonl")
        episodes = self._list_current_episodic_events(agent_id)
        episodes_by_id = {
            str(item.get("episodeId") or item.get("eventId") or "").strip(): item
            for item in episodes
            if str(item.get("episodeId") or item.get("eventId") or "").strip()
        }
        projected: list[dict[str, Any]] = []
        seen_receipt_ids: set[str] = set()
        seen_episode_ids: set[str] = set()
        for receipt in reversed(receipts):
            if not isinstance(receipt, dict):
                continue
            receipt_id = str(receipt.get("receiptId") or "").strip()
            episode_id = str(receipt.get("episodeId") or "").strip()
            episode = episodes_by_id.get(episode_id)
            if not episode or (receipt_id and receipt_id in seen_receipt_ids):
                continue
            # A source event is promoted once; old corrupted ledgers should not
            # make the UI display the same episode repeatedly.
            if episode_id in seen_episode_ids:
                continue
            if receipt_id:
                seen_receipt_ids.add(receipt_id)
            seen_episode_ids.add(episode_id)
            source_event_ids = [
                str(item).strip()
                for item in list(receipt.get("sourceEventIds") or [])
                if str(item).strip()
            ]
            projected.append(
                {
                    "agentId": str(agent_id).strip(),
                    "episodeId": episode_id,
                    "text": str(episode.get("text") or "").strip()[:1200],
                    "occurredAt": str(
                        receipt.get("occurredAt") or episode.get("occurredAt") or ""
                    ).strip(),
                    "salienceScore": _clamp(
                        receipt.get("salienceScore"), 0, 100, 0
                    ),
                    "sourceEventIds": source_event_ids,
                    "promotedAt": str(
                        receipt.get("promotedAt")
                        or receipt.get("writtenAt")
                        or receipt.get("createdAt")
                        or ""
                    ).strip(),
                }
            )
            if len(projected) >= bounded:
                break
        projected.reverse()
        return deepcopy(projected)

    def _list_current_episodic_events(self, agent_id: str) -> list[dict[str, Any]]:
        if self.episodic_lister is None:
            return []
        try:
            rows = self.episodic_lister(str(agent_id).strip(), limit=500)
        except TypeError:
            try:
                rows = self.episodic_lister(str(agent_id).strip())
            except Exception as exc:  # noqa: BLE001 - optional memory adapter boundary
                logger.warning(
                    "Virtual human episodic memory lookup failed for agent=%s (%s).",
                    str(agent_id).strip(),
                    type(exc).__name__,
                )
                return []
        except Exception as exc:  # noqa: BLE001 - optional memory adapter boundary
            logger.warning(
                "Virtual human episodic memory lookup failed for agent=%s (%s).",
                str(agent_id).strip(),
                type(exc).__name__,
            )
            return []
        return [item for item in list(rows or []) if isinstance(item, dict)]

    def _health_projection(
        self,
        agent_id: str,
        *,
        binding: dict[str, Any] | None,
    ) -> dict[str, Any]:
        enabled = bool(binding and binding.get("enabled"))
        heartbeat_enabled = enabled
        if heartbeat_enabled and self.runtime_acceptance_provider is not None:
            try:
                heartbeat_enabled = bool(self.runtime_acceptance_provider())
            except Exception:  # noqa: BLE001 - health is fail-closed
                heartbeat_enabled = False
        agent = self._agent(agent_id, include_archived=True)
        profile = agent.get("personaProfile") if isinstance(agent, dict) else None
        persona_initialized = bool(
            isinstance(profile, dict)
            and any(
                bool(value)
                for value in profile.values()
                if value is not None and str(value).strip() != ""
            )
        )
        prompt_ready = False
        prompt_segment_count = 0
        if enabled:
            try:
                prompt_ready = bool(load_prompt_pack())
                prompt_segment_count = 2 if prompt_ready else 0
            except Exception:  # noqa: BLE001 - health must stay redacted and bounded
                prompt_ready = False
                prompt_segment_count = 0
        receipts = self.store.read_jsonl(agent_id, "memory/promotion_receipts.jsonl")
        promotion_times = [
            str(
                item.get("promotedAt")
                or item.get("writtenAt")
                or item.get("createdAt")
                or ""
            ).strip()
            for item in receipts
            if isinstance(item, dict)
        ]
        promotion_times = [item for item in promotion_times if item]
        attempts = self.store.read_jsonl(agent_id, "proactive/deliveries.jsonl")
        latest_attempt = attempts[-1] if attempts else {}
        latest_status = str(latest_attempt.get("status") or "").strip() or None
        latest_at = str(
            latest_attempt.get("updatedAt")
            or latest_attempt.get("deliveredAt")
            or latest_attempt.get("createdAt")
            or ""
        ).strip() or None
        latest_error = ""
        if latest_status not in {None, "delivered"}:
            latest_error = str(
                latest_attempt.get("failureType")
                or latest_attempt.get("cancellationReason")
                or latest_attempt.get("expiryReason")
                or ""
            ).strip()[:160]
        return {
            "personaInitialized": persona_initialized,
            "promptPackReady": bool(prompt_ready),
            "promptSegmentCount": int(prompt_segment_count),
            "promptPackFileCount": len(PROMPT_PACK_FILES) if prompt_ready else 0,
            "memoryPromotionCount": len({
                str(item.get("receiptId") or "")
                for item in receipts
                if isinstance(item, dict) and str(item.get("receiptId") or "").strip()
            }),
            "latestPromotionAt": max(promotion_times) if promotion_times else None,
            "heartbeatEnabled": heartbeat_enabled,
            "lastProactiveStatus": latest_status,
            "lastProactiveAt": latest_at,
            "lastProactiveError": latest_error or None,
        }

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
                command_id=normalized_key,
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
        with self._lock_for(agent_id):
            return self._review_diary_locked(agent_id, local_date=local_date)

    def _review_diary_locked(self, agent_id: str, *, local_date: str) -> dict[str, Any]:
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
        promoted_source_ids = {
            str(source_id)
            for row in self.store.read_jsonl(
                agent_id,
                "memory/promotion_receipts.jsonl",
            )
            for source_id in list(row.get("sourceEventIds") or [])
            if str(source_id)
        }
        existing_episode_by_source: dict[str, str] = {}
        for episode in self._list_current_episodic_events(agent_id):
            episode_id = str(episode.get("episodeId") or episode.get("eventId") or "").strip()
            if not episode_id:
                continue
            for ref in list(episode.get("refs") or []):
                if not isinstance(ref, dict) or str(ref.get("type") or "") != "item":
                    continue
                source_id = str(ref.get("id") or "").strip()
                if source_id:
                    existing_episode_by_source.setdefault(source_id, episode_id)
        created: list[dict[str, Any]] = []
        promoted: list[dict[str, Any]] = []
        for event in events:
            event_id = str(event.get("eventId") or "").strip()
            outcome = event.get("outcome") if isinstance(event.get("outcome"), dict) else {}
            if (
                not event_id
                or str(event.get("kind") or "") != "activity_completed"
                or str(outcome.get("status") or "") != "succeeded"
                or not str(outcome.get("summary") or "").strip()
            ):
                continue
            salience = compute_event_salience(event)
            if event_id not in recorded_source_ids:
                entry = {
                    "diaryEntryId": f"diary-{uuid.uuid4().hex[:16]}",
                    "agentId": str(agent_id).strip(),
                    "localDate": normalized_date,
                    "title": str(event.get("title") or "生活记录")[:160],
                    "content": str(outcome.get("summary") or "").strip()[:1200],
                    "sourceEventIds": [event_id],
                    "salienceScore": salience,
                    "writtenAt": _iso(self._now()),
                    "projectionKind": "deterministic_event_summary",
                }
                self.store.append_jsonl(
                    agent_id,
                    f"diary/{normalized_date}.jsonl",
                    entry,
                )
                recorded_source_ids.add(event_id)
                created.append(entry)
            if salience < 70 or event_id in promoted_source_ids:
                continue
            episode_id = existing_episode_by_source.get(event_id, "")
            if not episode_id and self.episodic_writer is not None:
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
                "promotedAt": _iso(self._now()),
            }
            # The source-event index is the idempotency boundary.  Re-read is
            # intentionally avoided because this method owns the agent lock.
            if event_id in promoted_source_ids:
                continue
            self.store.append_jsonl(agent_id, "memory/promotion_receipts.jsonl", receipt)
            promoted_source_ids.add(event_id)
            existing_episode_by_source[event_id] = episode_id
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
            affect_projection = project_affect(
                self.store.read_jsonl(agent_id, "affect/episodes.jsonl"),
                now=self._now(),
                baseline_mood=mood,
            )
            self.store.write_json(agent_id, "affect/state.json", affect_projection)
            state["mood"] = deepcopy(affect_projection["mood"])
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
            self.store.write_json(
                agent_id,
                "relationships/base.json",
                {
                    "schemaVersion": CAUSAL_SCHEMA_VERSION,
                    "relationships": list(relationship_by_target.values()),
                    "createdAt": _iso(self._now()),
                    "source": "legacy_pet_import",
                },
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

    def _evaluate_proactive_candidates(
        self,
        agent_id: str,
        *,
        now: datetime,
        binding: dict[str, Any],
        state: dict[str, Any],
        dispatch: bool,
    ) -> dict[str, Any]:
        rows = self.store.read_jsonl(agent_id, "proactive/candidates.jsonl")
        recent_cutoff = now.astimezone(timezone.utc) - timedelta(hours=24)
        recent_topic_keys = {
            str(item.get("topicKey") or "")
            for item in rows
            if str(item.get("status") or "") in {"selected", "delivered"}
            and (_parse_datetime(item.get("selectedAt")) or now) >= recent_cutoff
            and str(item.get("topicKey") or "")
        }
        unanswered_count = sum(
            1
            for item in rows
            if str(item.get("status") or "") in {"selected", "delivered"}
            and not str(item.get("userRepliedAt") or "")
            and (_parse_datetime(item.get("selectedAt")) or now) >= now - timedelta(days=3)
        )
        evaluated = 0
        eligible_indices: list[int] = []
        local_now = now.astimezone(self._zone(binding))
        for index, item in enumerate(rows):
            if str(item.get("status") or "") not in {
                "pending",
                "eligible",
                "suppressed",
            }:
                continue
            evaluated += 1
            decision = evaluate_proactive_candidate(
                item,
                now=now,
                quiet_hours=self._inside_quiet_hours(
                    local_now, binding.get("quietHours")
                ),
                sleep_state=str(state.get("sleepState") or ""),
                busy=bool(str(state.get("currentActivityId") or "")),
                recent_topic_keys=recent_topic_keys,
                unanswered_count=unanswered_count,
            )
            rows[index] = decision
            if str(decision.get("decision") or "") == "eligible":
                eligible_indices.append(index)
        selected_candidate_id = ""
        if eligible_indices:
            selected_index = max(
                eligible_indices,
                key=lambda index: int(rows[index].get("score") or 0),
            )
            selected = rows[selected_index]
            selected_candidate_id = str(selected.get("candidateId") or "")
            if dispatch:
                try:
                    attempt = self.request_proactive_message(
                        agent_id,
                        reason=str(selected.get("reason") or "")[:600],
                        source_event_id=str(selected.get("sourceEventId") or "")[:200],
                        valid_for_minutes=45,
                        idempotency_key=f"candidate:{selected_candidate_id}",
                    )
                except VirtualHumanLifeError as exc:
                    selected["status"] = "suppressed"
                    selected["decision"] = "suppress"
                    selected["suppressionReason"] = type(exc).__name__
                    selected["suppressionDetail"] = str(exc)[:200]
                    selected["evaluatedAt"] = _iso(now)
                else:
                    selected["status"] = "selected"
                    selected["decision"] = "selected"
                    selected["selectedAt"] = _iso(now)
                    selected["deliveryToken"] = str(
                        attempt.get("deliveryToken") or ""
                    )
                    selected["triggerId"] = str(attempt.get("triggerId") or "")
        self.store.write_jsonl(agent_id, "proactive/candidates.jsonl", rows[-512:])
        return {
            "evaluatedCandidateCount": evaluated,
            "selectedCandidateId": selected_candidate_id,
        }

    def request_proactive_message(
        self,
        agent_id: str,
        *,
        reason: str,
        source_event_id: str = "",
        valid_for_minutes: int = 30,
        idempotency_key: str = "",
        tool_activity: dict[str, Any] | None = None,
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
            normalized_tool_activity = self._normalize_proactive_tool_activity(
                tool_activity
            )
            request_fingerprint = self._proactive_request_fingerprint(
                agent_id=str(agent_id).strip(),
                reason=str(reason or "").strip()[:600],
                source_event_id=normalized_source_event_id,
                idempotency_key=normalized_idempotency_key,
                tool_activity=normalized_tool_activity,
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
            if normalized_tool_activity:
                attempt["toolActivity"] = normalized_tool_activity
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
                        **(
                            {"toolActivity": dict(attempt["toolActivity"])}
                            if isinstance(attempt.get("toolActivity"), dict)
                            else {}
                        ),
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
            delivered = self._update_attempt(
                agent_id,
                delivery_token,
                status="delivered",
                deliveredAt=_iso(self._now()),
                receiptEventId=normalized_receipt_event_id,
            )
            candidates = self.store.read_jsonl(
                agent_id, "proactive/candidates.jsonl"
            )
            changed = False
            for candidate in candidates:
                if str(candidate.get("deliveryToken") or "") != str(
                    delivery_token or ""
                ):
                    continue
                candidate["status"] = "delivered"
                candidate["decision"] = "delivered"
                candidate["deliveredAt"] = str(delivered.get("deliveredAt") or "")
                candidate["receiptEventId"] = normalized_receipt_event_id
                changed = True
            if changed:
                self.store.write_jsonl(
                    agent_id, "proactive/candidates.jsonl", candidates
                )
            return delivered

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
        command_id: str = "",
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
            should_refresh = bool(
                self.schedule_planner is not None
                and isinstance(existing, dict)
                and str(existing.get("plannerStatus") or "").strip()
                not in {"accepted", "fallback"}
            )
            if existing is None or should_refresh:
                existing = self._generate_schedule(agent_id, date.fromisoformat(target_date), binding)
                if should_refresh:
                    existing["scheduleVersion"] = int(existing.get("scheduleVersion") or 1) + 1
                self.store.write_json(agent_id, f"schedules/{target_date}.json", existing)
            return {"schedule": deepcopy(existing), "created": created}
        if command == "triggerDiaryReview":
            return self.review_diary(agent_id, local_date=local_date)
        if command == "recordRelationshipInteraction":
            target_id = str(arguments.get("targetId") or "").strip()
            if not target_id or len(target_id) > 160:
                raise VirtualHumanLifeError("Relationship targetId is required.")
            current = self._now()
            interaction_id = (
                f"relationship:{command_id}"
                if command_id
                else f"relationship:{target_id}:{current.isoformat()}"
            )
            relationship_event = make_relationship_event(
                event_id=interaction_id,
                target_id=target_id,
                kind=str(arguments.get("kind") or "interaction")[:120],
                intimacy_delta=_clamp(arguments.get("intimacyDelta"), -20, 20, 0),
                trust_delta=_clamp(arguments.get("trustDelta"), -20, 20, 0),
                occurred_at=current,
                source_turn_id=str(arguments.get("sourceTurnId") or "")[:200],
            )
            events = self.store.read_jsonl(agent_id, "relationships/events.jsonl")
            if not any(
                str(item.get("eventId") or "") == interaction_id for item in events
            ):
                events.append(relationship_event)
                self.store.write_jsonl(
                    agent_id,
                    "relationships/events.jsonl",
                    events[-1024:],
                )
            base_payload = self.store.read_json(agent_id, "relationships/base.json") or {}
            base_rows = [
                item
                for item in list(base_payload.get("relationships") or [])
                if isinstance(item, dict)
            ]
            relationships = project_relationships(base_rows, events, now=current)
            self.store.write_json(
                agent_id,
                "relationships.json",
                {"relationships": relationships, "updatedAt": _iso(current)},
            )
            relationship = next(
                item
                for item in relationships
                if str(item.get("targetId") or "") == target_id
            )
            evolved_state = apply_relationship_interaction_to_state(
                state,
                interaction_id=interaction_id,
                intimacy_delta=int(relationship_event["intimacyDelta"]),
                trust_delta=int(relationship_event["trustDelta"]),
                kind=str(relationship_event["kind"]),
                now=current,
            )
            state.clear()
            state.update(evolved_state)
            affect = self._record_affect_episode(
                agent_id,
                episode_from_relationship_event(relationship_event, now=current),
                now=current,
            )
            state["mood"] = deepcopy(affect["mood"])
            if target_id == "user":
                stage_text = {
                    "getting_to_know": "正在逐渐熟悉彼此",
                    "friend": "已经形成稳定而自然的朋友关系",
                    "close": "彼此信任并保持亲近",
                }.get(str(relationship.get("relationshipStage") or ""), "正在相处")
                state["relationshipSummary"] = (
                    f"与用户{stage_text}；最近一次互动是"
                    f"{relationship.get('lastInteractionKind') or '日常交流'!s}。"
                )
            return {
                "relationship": deepcopy(relationship),
                "relationshipEventId": interaction_id,
            }
        if command == "recordOpenLoop":
            topic_key = str(arguments.get("topicKey") or "").strip()[:120]
            summary = str(arguments.get("summary") or "").strip()[:300]
            if not topic_key or not summary:
                raise VirtualHumanLifeError("Open loop topicKey and summary are required.")
            current = self._now()
            rows = upsert_open_loop(
                self.store.read_jsonl(agent_id, "conversation/open_loops.jsonl"),
                loop_id=f"open-loop:{command_id}",
                topic_key=topic_key,
                kind=str(arguments.get("kind") or "topic")[:40],
                summary=summary,
                source_turn_id=str(arguments.get("sourceTurnId") or "")[:200],
                now=current,
                expires_at=current
                + timedelta(
                    minutes=_clamp(
                        arguments.get("expiresInMinutes"),
                        5,
                        43_200,
                        10_080,
                    )
                ),
            )
            self.store.write_jsonl(agent_id, "conversation/open_loops.jsonl", rows)
            open_loop = next(
                item
                for item in reversed(rows)
                if str(item.get("topicKey") or "") == topic_key
                and str(item.get("status") or "") == "open"
            )
            return {"openLoop": deepcopy(open_loop)}
        if command == "resolveOpenLoop":
            topic_key = str(arguments.get("topicKey") or "").strip()[:120]
            if not topic_key:
                raise VirtualHumanLifeError("Open loop topicKey is required.")
            rows = resolve_open_loop(
                self.store.read_jsonl(agent_id, "conversation/open_loops.jsonl"),
                topic_key=topic_key,
                resolution=str(arguments.get("resolution") or "")[:300],
                source_turn_id=str(arguments.get("sourceTurnId") or "")[:200],
                now=self._now(),
            )
            self.store.write_jsonl(agent_id, "conversation/open_loops.jsonl", rows)
            open_loop = next(
                (
                    item
                    for item in reversed(rows)
                    if str(item.get("topicKey") or "") == topic_key
                ),
                None,
            )
            if open_loop is None:
                raise VirtualHumanLifeError("Open loop was not found.")
            return {"openLoop": deepcopy(open_loop)}
        if command == "recordConversationReply":
            source_turn_id = str(arguments.get("sourceTurnId") or "").strip()[:200]
            if not source_turn_id:
                raise VirtualHumanLifeError("Conversation reply sourceTurnId is required.")
            current = self._now()
            candidates = self.store.read_jsonl(
                agent_id, "proactive/candidates.jsonl"
            )
            acknowledged: list[str] = []
            for candidate in candidates:
                if str(candidate.get("status") or "") not in {
                    "selected",
                    "delivered",
                } or str(candidate.get("userRepliedAt") or ""):
                    continue
                candidate["userRepliedAt"] = _iso(current)
                candidate["userReplyTurnId"] = source_turn_id
                acknowledged.append(str(candidate.get("candidateId") or ""))
            if acknowledged:
                self.store.write_jsonl(
                    agent_id, "proactive/candidates.jsonl", candidates
                )
            topic_key = str(arguments.get("topicKey") or "").strip()[:120]
            resolved_count = 0
            if topic_key:
                loops = resolve_open_loop(
                    self.store.read_jsonl(
                        agent_id, "conversation/open_loops.jsonl"
                    ),
                    topic_key=topic_key,
                    resolution=str(arguments.get("resolution") or "用户已经回应")[:300],
                    source_turn_id=source_turn_id,
                    now=current,
                )
                resolved_count = sum(
                    1
                    for item in loops
                    if str(item.get("topicKey") or "") == topic_key
                    and str(item.get("status") or "") == "resolved"
                )
                self.store.write_jsonl(
                    agent_id, "conversation/open_loops.jsonl", loops
                )
            return {
                "acknowledgedCandidateIds": acknowledged,
                "resolvedOpenLoopCount": resolved_count,
            }
        if command == "proposeToolActivity":
            schedule = self.schedule_for(agent_id, local_date)
            title = str(arguments.get("title") or "").strip()[:160]
            if not title:
                raise VirtualHumanLifeError("Tool activity title is required.")
            starts_at = _parse_datetime(arguments.get("startAt"))
            ends_at = _parse_datetime(arguments.get("endAt"))
            if starts_at is None or ends_at is None or ends_at <= starts_at:
                raise VirtualHumanLifeError(
                    "Tool activity requires a valid startAt/endAt window."
                )
            if ends_at - starts_at > timedelta(hours=8):
                raise VirtualHumanLifeError("Tool activity window must not exceed 8 hours.")
            zone = self._zone(binding)
            if (
                starts_at.astimezone(zone).date().isoformat() != local_date
                or ends_at.astimezone(zone).date().isoformat() != local_date
            ):
                raise VirtualHumanLifeError(
                    "Tool activity startAt/endAt must stay inside localDate."
                )
            for existing in list(schedule.get("activities") or []):
                if not isinstance(existing, dict) or str(existing.get("status") or "planned") in {
                    "cancelled",
                    "skipped",
                    "failed",
                    "unknown",
                }:
                    continue
                existing_start = _parse_datetime(existing.get("startAt"))
                existing_end = _parse_datetime(existing.get("endAt"))
                if (
                    existing_start is not None
                    and existing_end is not None
                    and starts_at < existing_end
                    and ends_at > existing_start
                ):
                    raise VirtualHumanLifeError(
                        "Tool activity would overlap an existing schedule activity."
                    )
            raw_tool_names = arguments.get("requiredToolNames")
            candidates = raw_tool_names if isinstance(raw_tool_names, list) else []
            required_tool_names: list[str] = []
            for item in candidates:
                name = str(item or "").strip()
                if not name or name in required_tool_names:
                    continue
                required_tool_names.append(name[:160])
                if len(required_tool_names) >= 8:
                    break
            if not required_tool_names:
                raise VirtualHumanLifeError(
                    "Tool activity requires at least one requiredToolName."
                )
            activity = {
                "activityId": f"life-tool-{uuid.uuid4().hex[:16]}",
                "title": title,
                "kind": "tool",
                "startAt": _iso(starts_at),
                "endAt": _iso(ends_at),
                "status": "planned",
                "origin": "agent_proposed_tool_activity",
                "requiredToolNames": required_tool_names,
                "executionPolicy": "agent_tool_policy",
                "createdAt": _iso(self._now()),
            }
            schedule["activities"] = [*list(schedule.get("activities") or []), activity]
            schedule["activities"].sort(key=lambda item: str(item.get("startAt") or ""))
            schedule["scheduleVersion"] = int(schedule.get("scheduleVersion") or 1) + 1
            schedule["planningMode"] = "agent_augmented"
            schedule["updatedAt"] = _iso(self._now())
            self.store.write_json(agent_id, f"schedules/{local_date}.json", schedule)
            return {"activity": deepcopy(activity), "scheduleVersion": schedule["scheduleVersion"]}
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
            planner_status = str(generated.get("plannerStatus") or "").strip().lower()
            if planner_status == "accepted":
                # Preserve the evidence that this replan came from the Agent
                # planner; otherwise a successful LLM proposal would be
                # mislabeled as deterministic in the UI and audit trail.
                generated["planningMode"] = "agent_proposed"
            elif planner_status == "fallback":
                generated["planningMode"] = "deterministic_replan_fallback"
            else:
                generated["planningMode"] = "deterministic_replan"
            generated["replanReason"] = str(arguments.get("reason") or "")[:300]
            generated["replanRequestedAt"] = _iso(self._now())
            self.store.write_json(agent_id, f"schedules/{local_date}.json", generated)
            return {"schedule": deepcopy(generated)}
        if command not in {
            "startActivity",
            "completeActivity",
            "cancelActivity",
            "skipActivity",
            "failActivity",
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
        elif command in {"cancelActivity", "skipActivity", "failActivity"}:
            activity["status"] = {
                "cancelActivity": "cancelled",
                "skipActivity": "skipped",
                "failActivity": "failed",
            }[command]
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
                "activityKind": str(
                    activity.get("activityKind") or activity.get("kind") or "simulated"
                ).strip().lower(),
                "title": str(activity.get("title") or "计划活动"),
                "localDate": local_date,
                "driveRefs": deepcopy(
                    list(activity.get("driveLinks") or outcome.get("driveRefs") or [])
                )[:8],
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
            self._apply_completed_event_to_state(agent_id, state, event, now)
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
        if self.store.read_json(agent_id, "drives/state.json") is None:
            self.store.write_json(
                agent_id,
                "drives/state.json",
                default_drive_projection(now=self._now()),
            )
        if self.store.read_json(agent_id, "relationships.json") is None:
            now = _iso(self._now())
            self.store.write_json(
                agent_id,
                "relationships.json",
                {
                    "relationships": [
                        {
                            "targetId": "user",
                            "kind": "user",
                            "intimacy": 50,
                            "trust": 50,
                            "interactionCount": 0,
                            "relationshipStage": "getting_to_know",
                            "updatedAt": now,
                        }
                    ],
                    "updatedAt": now,
                },
            )
        if self.store.read_json(agent_id, "relationships/base.json") is None:
            relationships = self.store.read_json(agent_id, "relationships.json") or {}
            self.store.write_json(
                agent_id,
                "relationships/base.json",
                {
                    "schemaVersion": CAUSAL_SCHEMA_VERSION,
                    "relationships": deepcopy(list(relationships.get("relationships") or [])),
                    "createdAt": _iso(self._now()),
                },
            )
        affect_state = self.store.read_json(agent_id, "affect/state.json")
        if affect_state is None or not isinstance(affect_state.get("baselineMood"), dict):
            episodes = self.store.read_jsonl(agent_id, "affect/episodes.jsonl")
            state = self.store.read_json(agent_id, "state.json") or {}
            state_mood = state.get("mood") if isinstance(state.get("mood"), dict) else None
            baseline = state_mood if not episodes else BASELINE_MOOD
            self.store.write_json(
                agent_id,
                "affect/state.json",
                project_affect(episodes, now=self._now(), baseline_mood=baseline),
            )
        local_today = self._local_now(binding).date()
        for target_date in (local_today, local_today + timedelta(days=1)):
            path = f"schedules/{target_date.isoformat()}.json"
            if self.store.read_json(agent_id, path) is None:
                self.store.write_json(
                    agent_id,
                    path,
                    self._deterministic_schedule(agent_id, target_date, binding),
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
        self._timezone_for_name(timezone_name)
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
        sleep_state = self._derive_sleep_state(
            local_now=local_now,
            binding=binding,
            schedule=None,
            current_activity_id="",
        )
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
            "sleepState": sleep_state,
            "socialNeed": 42,
            "processedEventIds": [],
            "processedInteractionIds": [],
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
        fallback = self._deterministic_schedule(agent_id, local_date, binding)
        if self.schedule_planner is None:
            return fallback
        proposal, failure_reason = self._invoke_schedule_planner(
            agent_id,
            local_date=local_date,
            binding=binding,
        )
        activities, validation_reason = validate_schedule_proposal(
            proposal,
            agent_id=agent_id,
            local_date=local_date,
            zone=self._zone(binding),
        )
        if activities:
            return link_schedule_to_drives({
                **fallback,
                "activities": activities,
                "planningMode": "agent_proposed",
                "plannerStatus": "accepted",
                "plannerFallbackReason": "",
            }, self.store.read_json(agent_id, "drives/state.json") or default_drive_projection(now=self._now()))
        fallback["plannerStatus"] = "fallback"
        fallback["plannerFallbackReason"] = (
            validation_reason or failure_reason or "invalid_proposal"
        )
        return fallback

    def _deterministic_schedule(
        self,
        agent_id: str,
        local_date: date,
        binding: dict[str, Any],
    ) -> dict[str, Any]:
        return link_schedule_to_drives(
            build_deterministic_schedule(
                agent_id,
                local_date,
                timezone_name=str(binding.get("timezone") or "Asia/Shanghai"),
                zone=self._zone(binding),
                now=self._now(),
            ),
            self.store.read_json(agent_id, "drives/state.json")
            or default_drive_projection(now=self._now()),
        )

    def _invoke_schedule_planner(
        self,
        agent_id: str,
        *,
        local_date: date,
        binding: dict[str, Any],
    ) -> tuple[Any, str]:
        """Invoke an injected Agent planner with a hard timeout and no disk writes."""

        context = {
            "agentId": str(agent_id).strip(),
            "localDate": local_date.isoformat(),
            "timezone": str(binding.get("timezone") or "Asia/Shanghai"),
            "constraints": {
                "maxActivities": 8,
                "maxDurationMinutes": 480,
                "sameLocalDate": True,
                "allowedKinds": ["simulated", "tool"],
                "allowedActivityKinds": list(PLANNER_ACTIVITY_KINDS),
            },
            "state": self.store.read_json(agent_id, "state.json") or {},
            "lifeDrives": prompt_drive_summary(
                self.store.read_json(agent_id, "drives/state.json")
                or default_drive_projection(now=self._now())
            ),
            # The requested date is tomorrow, so filtering the diary by that
            # date would always hide the recent experiences that should guide
            # planning.  Keep the input bounded but use the latest entries
            # across already recorded local days.
            "recentDiary": self.list_diary(agent_id, limit=5),
        }
        result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def run() -> None:
            try:
                result_queue.put(("ok", self.schedule_planner(context)))
            except Exception as exc:  # noqa: BLE001 - adapter boundary
                result_queue.put(("error", type(exc).__name__))

        worker = threading.Thread(
            target=run,
            name="virtual-human-schedule-planner",
            daemon=True,
        )
        worker.start()
        worker.join(timeout=self.schedule_planner_timeout_seconds)
        if worker.is_alive():
            return None, "timeout"
        try:
            status, value = result_queue.get_nowait()
        except queue.Empty:
            return None, "adapter_error"
        if status != "ok":
            return None, "adapter_error"
        return value, ""

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
        tool_activities_to_dispatch: list[dict[str, Any]] = []
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
                if (
                    str(activity.get("kind") or "simulated").strip().lower() == "tool"
                    and not str(activity.get("executionDispatchStatus") or "").strip()
                ):
                    tool_activities_to_dispatch.append(deepcopy(activity))
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
                "salienceScore": self._simulated_activity_salience(
                    str(activity.get("title") or "")
                ),
                "recordedAt": _iso(current),
            }
            event = {
                "eventId": f"life-event-{uuid.uuid4().hex[:16]}",
                "agentId": str(agent_id).strip(),
                "activityId": str(activity.get("activityId") or ""),
                "kind": "activity_completed",
                "activityKind": str(
                    activity.get("activityKind") or activity.get("kind") or "simulated"
                ).strip().lower(),
                "title": str(activity.get("title") or "计划活动"),
                "localDate": event_local_date,
                "driveRefs": deepcopy(list(activity.get("driveLinks") or []))[:8],
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
            self._apply_completed_event_to_state(agent_id, state, event, current)
        return {
            "changed": changed,
            "currentActivityId": current_activity_id,
            "completedEvents": completed_events,
            "toolActivitiesToDispatch": tool_activities_to_dispatch,
        }

    def _dispatch_tool_activity(
        self,
        agent_id: str,
        *,
        local_date: str,
        activity: dict[str, Any],
    ) -> bool:
        activity_id = str(activity.get("activityId") or "").strip()
        if not activity_id or self.proactive_submitter is None:
            return False
        title = str(activity.get("title") or "工具型活动").strip()
        required_tools = [
            str(item or "").strip()
            for item in list(activity.get("requiredToolNames") or [])
            if str(item or "").strip()
        ]
        reason = (
            f"日程中的工具型活动“{title}”已经开始。请先用 virtual_human_status_tool "
            "确认最新 stateVersion，再只使用当前 Agent ToolPolicy 允许的工具尝试执行；"
            "成功后调用 virtual_human_activity_tool complete 记录可信 outcome，"
            "失败则调用 fail，禁止自行扩权或把计划当成结果。"
        )
        failure_reason = ""
        try:
            attempt = self.request_proactive_message(
                agent_id,
                reason=reason,
                valid_for_minutes=60,
                idempotency_key=f"life-activity-execution:{activity_id}",
                tool_activity={
                    "activityId": activity_id,
                    "requiredToolNames": required_tools,
                },
            )
            dispatch_status = str(attempt.get("status") or "requested")
            turn_id = str(attempt.get("turnId") or "")
            delivery_token = str(attempt.get("deliveryToken") or "")
            dispatched = dispatch_status in {"reserved", "delivering", "delivered"}
            if not dispatched:
                failure_reason = dispatch_status or "not_dispatched"
        except VirtualHumanLifeError as exc:
            dispatch_status = "unavailable"
            turn_id = ""
            delivery_token = ""
            dispatched = False
            failure_reason = type(exc).__name__
        schedule = self.store.read_json(agent_id, f"schedules/{local_date}.json") or {}
        for row in list(schedule.get("activities") or []):
            if not isinstance(row, dict) or str(row.get("activityId") or "") != activity_id:
                continue
            row["executionDispatchStatus"] = dispatch_status
            row["executionRequestedAt"] = _iso(self._now())
            row["executionPolicy"] = "agent_tool_policy"
            row["requiredToolNames"] = required_tools
            if turn_id:
                row["executionTurnId"] = turn_id
            if delivery_token:
                row["executionDeliveryToken"] = delivery_token
            if not dispatched:
                row["executionUnavailableReason"] = failure_reason
            break
        schedule["scheduleVersion"] = int(schedule.get("scheduleVersion") or 1) + 1
        schedule["updatedAt"] = _iso(self._now())
        self.store.write_json(agent_id, f"schedules/{local_date}.json", schedule)
        return dispatched

    @staticmethod
    def _simulated_activity_salience(title: str) -> int:
        return compute_event_salience(
            {
                "kind": "activity_completed",
                "title": str(title or ""),
                "outcome": {
                    "status": "succeeded",
                    "kind": "deterministic_simulation",
                    "summary": f"完成了{title or '计划活动'}。",
                },
            }
        )

    def _apply_completed_event_to_state(
        self,
        agent_id: str,
        state: dict[str, Any],
        event: dict[str, Any],
        now: datetime,
    ) -> None:
        evolved_state = apply_completed_event_to_state(state, event, now=now)
        state.clear()
        state.update(evolved_state)

        drives = self.store.read_json(agent_id, "drives/state.json") or default_drive_projection(
            now=now
        )
        drive_result = apply_completed_event_to_drives(drives, event, now=now)
        self.store.write_json(agent_id, "drives/state.json", drive_result["projection"])
        if isinstance(drive_result.get("change"), dict):
            self.store.append_jsonl(
                agent_id,
                "drives/events.jsonl",
                drive_result["change"],
            )

        episode = episode_from_life_event(event, now=now)
        affect = self._record_affect_episode(agent_id, episode, now=now)
        state["mood"] = deepcopy(affect["mood"])

        if not bool(event.get("simulatedAfterRestart")):
            relationships = self.list_relationships(agent_id)
            relationship = next(
                (
                    item
                    for item in relationships
                    if str(item.get("targetId") or "") == "user"
                ),
                {},
            )
            candidate = build_proactive_candidate(
                event,
                drive_projection=drive_result["projection"],
                affect_projection=affect,
                relationship=relationship,
                now=now,
            )
            rows = self.store.read_jsonl(agent_id, "proactive/candidates.jsonl")
            if not any(
                str(item.get("candidateId") or "")
                == str(candidate.get("candidateId") or "")
                for item in rows
            ):
                self.store.append_jsonl(
                    agent_id,
                    "proactive/candidates.jsonl",
                    candidate,
                )

    def _record_affect_episode(
        self,
        agent_id: str,
        episode: dict[str, Any] | None,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        episodes = self.store.read_jsonl(agent_id, "affect/episodes.jsonl")
        episode_id = str((episode or {}).get("episodeId") or "")
        if episode_id and not any(
            str(item.get("episodeId") or "") == episode_id for item in episodes
        ):
            episodes.append(deepcopy(episode or {}))
            self.store.write_jsonl(agent_id, "affect/episodes.jsonl", episodes[-512:])
        projection = project_affect(
            episodes,
            now=now,
            baseline_mood=self._affect_baseline(agent_id),
        )
        self.store.write_json(agent_id, "affect/state.json", projection)
        return projection

    def _affect_baseline(
        self,
        agent_id: str,
        *,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        affect_state = self.store.read_json(agent_id, "affect/state.json") or {}
        baseline = affect_state.get("baselineMood")
        if isinstance(baseline, dict):
            return deepcopy(baseline)
        source_state = state if isinstance(state, dict) else (
            self.store.read_json(agent_id, "state.json") or {}
        )
        mood = source_state.get("mood")
        if isinstance(mood, dict):
            return deepcopy(mood)
        return deepcopy(BASELINE_MOOD)

    def _require_enabled_binding(self, agent_id: str) -> dict[str, Any]:
        binding = self.binding_for(agent_id)
        agent = self._agent(agent_id, include_archived=False)
        if not binding or not bool(binding.get("enabled")):
            raise BindingDisabledError("virtual-human-life is not enabled for this Agent.")
        if not agent:
            raise AgentUnavailableError("The bound Agent is not active.")
        self._ensure_initialized(agent_id, binding)
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

    @staticmethod
    def _timezone_for_name(timezone_name: str) -> tzinfo:
        normalized = str(timezone_name or "Asia/Shanghai").strip()
        try:
            return ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            # ``tzdata`` is an explicit runtime dependency, but an already-running
            # Windows/minimal-Python host may not have refreshed dependencies yet.
            # Keep only the product default usable in that bounded case; arbitrary
            # misspelled IANA names must continue to fail closed.
            if normalized == "Asia/Shanghai":
                return timezone(timedelta(hours=8), name="Asia/Shanghai")
            raise VirtualHumanLifeError(f"Unknown timezone: {normalized}") from exc

    def _zone(self, binding: dict[str, Any]) -> tzinfo:
        return self._timezone_for_name(
            str(binding.get("timezone") or "Asia/Shanghai")
        )

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

    def _derive_sleep_state(
        self,
        *,
        local_now: datetime,
        binding: dict[str, Any],
        schedule: dict[str, Any] | None,
        current_activity_id: str,
    ) -> str:
        if str(current_activity_id or "").strip():
            return "awake"
        if self._inside_quiet_hours(local_now, binding.get("quietHours")):
            return "sleeping"
        activity_end_times = [
            parsed
            for activity in list((schedule or {}).get("activities") or [])
            if isinstance(activity, dict)
            if (parsed := _parse_datetime(activity.get("endAt"))) is not None
        ]
        if activity_end_times and max(activity_end_times) <= local_now.astimezone(timezone.utc):
            return "resting"
        return "awake"

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
        tool_activity: dict[str, Any] | None = None,
    ) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "agentId": agent_id,
                    "reason": reason,
                    "sourceEventId": source_event_id,
                    "idempotencyKey": idempotency_key,
                    "toolActivity": dict(tool_activity or {}),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _normalize_proactive_tool_activity(
        value: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        activity_id = str(value.get("activityId") or "").strip()[:160]
        required_tools: list[str] = []
        for item in list(value.get("requiredToolNames") or []):
            name = str(item or "").strip()[:160]
            if not name or name in required_tools:
                continue
            required_tools.append(name)
            if len(required_tools) >= 8:
                break
        if not activity_id or not required_tools:
            return {}
        return {
            "activityId": activity_id,
            "requiredToolNames": required_tools,
        }

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
