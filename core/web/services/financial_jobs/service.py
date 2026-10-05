"""Public CRUD and safety gates for private financial research schedules."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.web.services import (
    financial_team_service,
    runtime_task_registry,
)

from .contract import (
    canonical_batch_id,
    canonical_schedule_id,
    iso_beijing,
    normalize_create_request,
    occurrence_batch_id,
    occurrence_research_date,
    parse_now,
    schedule_next_run,
)
from .errors import (
    FinancialJobConflictError,
    FinancialJobNotFoundError,
    FinancialJobValidationError,
)
from .store import FinancialResearchJobStore, default_store

TASK_OWNER = "financial_research_jobs"
TASK_ID_PREFIX = "financial-research-batch-"
TASK_LABEL = "股票研究批次"
MAX_BATCHES_PER_LIST = 60


def create_financial_research_schedule(
    assistant_agent_id: str,
    request: dict[str, Any],
    *,
    idempotency_key: str,
    now: datetime | None = None,
    store: FinancialResearchJobStore | None = None,
) -> dict[str, Any]:
    normalized_now = parse_now(now)
    key = str(idempotency_key or "").strip()
    if not 16 <= len(key) <= 200:
        raise FinancialJobValidationError("创建请求键长度无效")
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    selected_store = store or default_store()
    _require_financial_owner(assistant_agent_id)
    existing_state = selected_store.load(assistant_agent_id)
    key_was_seen = any(
        isinstance(schedule.get("_createIdempotency"), dict)
        and schedule["_createIdempotency"].get("keyHash") == key_hash
        for schedule in existing_state["schedules"].values()
    )
    normalized = normalize_create_request(
        request, now=normalized_now, allow_past_once=key_was_seen
    )
    input_hash = _request_hash(normalized)
    existing = _find_idempotent_schedule(
        existing_state, key_hash=key_hash, input_hash=input_hash
    )
    if existing is None:
        # Schedule creation is an explicit user write, so it may finish the
        # native team setup. GET requests never reach this provision path.
        financial_team_service.provision_financial_team(assistant_agent_id)

    created_at = iso_beijing(normalized_now)
    schedule_id = str(uuid4())
    execution = dict(normalized["execution"])
    enabled = execution["kind"] != "now"
    schedule: dict[str, Any] = {
        "scheduleId": schedule_id,
        "assistantAgentId": assistant_agent_id,
        "symbols": list(normalized["symbols"]),
        "periodDays": normalized["periodDays"],
        "depth": normalized["depth"],
        "execution": execution,
        "researchDate": normalized["researchDate"],
        "enabled": enabled,
        "createdAt": created_at,
        "updatedAt": created_at,
        "nextRunAt": None,
        "lastBatchId": None,
        "lastTriggeredAt": None,
        "_createIdempotency": {"keyHash": key_hash, "inputHash": input_hash},
    }
    if enabled:
        schedule["nextRunAt"] = schedule_next_run(schedule, now=normalized_now)

    if execution["kind"] == "now":
        occurrence_time = normalized_now.astimezone(
            __import__("zoneinfo").ZoneInfo("Asia/Shanghai")
        )
        batch_id = occurrence_batch_id(schedule_id, occurrence_time)
        schedule["lastBatchId"] = batch_id
        schedule["lastTriggeredAt"] = created_at
        schedule["lastOccurrence"] = {
            "batchId": batch_id,
            "scheduledAt": occurrence_time.isoformat(timespec="seconds"),
            "triggeredAt": created_at,
            "researchDate": occurrence_research_date(
                schedule, scheduled_at=occurrence_time, triggered_at=normalized_now
            ),
            "materialized": False,
        }

    def _insert(state: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        schedules = state["schedules"]
        for current in schedules.values():
            marker = current.get("_createIdempotency")
            if not isinstance(marker, dict) or marker.get("keyHash") != key_hash:
                continue
            if marker.get("inputHash") != input_hash:
                raise FinancialJobConflictError(
                    "同一创建请求键不能用于不同的研究参数"
                )
            return current, False
        schedules[schedule_id] = schedule
        return schedule, True

    state, result = selected_store.update(assistant_agent_id, _insert)
    created, _was_new = result
    created = state["schedules"].get(str(created.get("scheduleId") or ""), created)
    if str((created.get("execution") or {}).get("kind") or "") == "now":
        occurrence = created.get("lastOccurrence")
        if isinstance(occurrence, dict):
            from .runtime import ensure_occurrence_batch

            batch = ensure_occurrence_batch(
                created,
                occurrence,
                store=selected_store,
            )
        else:
            batch = None
    else:
        batch = None
    _record_event(
        "financial_jobs.schedule.created",
        assistant_agent_id=assistant_agent_id,
        schedule_id=str(created.get("scheduleId") or ""),
        outcome="replayed" if not _was_new else "created",
    )
    return {"schedule": project_schedule(created), "batch": batch}


def list_financial_research_schedules(
    assistant_agent_id: str,
    *,
    store: FinancialResearchJobStore | None = None,
) -> dict[str, Any]:
    _require_financial_owner(assistant_agent_id)
    state = (store or default_store()).load(assistant_agent_id)
    schedules = sorted(
        state["schedules"].values(),
        key=lambda item: str(item.get("updatedAt") or ""),
        reverse=True,
    )
    return {
        "assistantAgentId": assistant_agent_id,
        "schedules": [project_schedule(item) for item in schedules],
    }


def update_financial_research_schedule(
    assistant_agent_id: str,
    schedule_id: str,
    *,
    enabled: bool,
    now: datetime | None = None,
    store: FinancialResearchJobStore | None = None,
) -> dict[str, Any]:
    _require_financial_owner(assistant_agent_id)
    normalized_id = canonical_schedule_id(schedule_id)
    normalized_now = parse_now(now)
    selected_store = store or default_store()

    def _mutate(state: dict[str, Any]) -> dict[str, Any]:
        schedule = state["schedules"].get(normalized_id)
        if not isinstance(schedule, dict):
            raise FinancialJobNotFoundError("研究计划不存在")
        execution = schedule.get("execution") or {}
        kind = str(execution.get("kind") or "")
        if kind == "now":
            raise FinancialJobConflictError("立即研究记录不能启停")
        if kind == "once" and schedule.get("lastTriggeredAt"):
            raise FinancialJobConflictError("已触发的单次计划不能重新启用")
        if enabled and kind == "once":
            next_run = schedule_next_run(
                {**schedule, "enabled": True}, now=normalized_now
            )
            if not next_run:
                raise FinancialJobConflictError("单次计划执行时间已过，无法恢复")
        else:
            next_run = schedule_next_run(
                {**schedule, "enabled": enabled}, now=normalized_now
            )
        schedule["enabled"] = bool(enabled)
        schedule["nextRunAt"] = next_run if enabled else None
        schedule["updatedAt"] = iso_beijing(normalized_now)
        return schedule

    state, updated = selected_store.update(assistant_agent_id, _mutate)
    return project_schedule(state["schedules"][normalized_id] if not updated else updated)


def list_financial_research_batches(
    assistant_agent_id: str,
    *,
    limit: int = MAX_BATCHES_PER_LIST,
    task_store: Any | None = None,
) -> dict[str, Any]:
    _require_financial_owner(assistant_agent_id)
    selected_limit = max(1, min(MAX_BATCHES_PER_LIST, int(limit)))
    states = _task_store(task_store).iter_task_states()
    batches = [
        state.get("financialResearchBatch")
        for state in states
        if _is_our_batch(state, assistant_agent_id)
        and isinstance(state.get("financialResearchBatch"), dict)
    ]
    batches.sort(key=lambda item: str(item.get("triggeredAt") or ""), reverse=True)
    return {
        "assistantAgentId": assistant_agent_id,
        "batches": [project_batch(item) for item in batches[:selected_limit]],
    }


def get_financial_research_batch(
    assistant_agent_id: str,
    batch_id: str,
    *,
    task_store: Any | None = None,
) -> dict[str, Any]:
    _require_financial_owner(assistant_agent_id)
    state = _load_batch_state(assistant_agent_id, batch_id, task_store=task_store)
    return project_batch(state["financialResearchBatch"])


def stop_financial_research_batch(
    assistant_agent_id: str,
    batch_id: str,
    *,
    task_store: Any | None = None,
) -> dict[str, Any]:
    _require_financial_owner(assistant_agent_id)
    from .runtime import request_batch_stop

    return request_batch_stop(
        assistant_agent_id, batch_id, task_store=task_store
    )


def retry_financial_research_batch(
    assistant_agent_id: str,
    batch_id: str,
    *,
    task_store: Any | None = None,
) -> dict[str, Any]:
    _require_financial_owner(assistant_agent_id)
    from .runtime import retry_batch

    return retry_batch(assistant_agent_id, batch_id, task_store=task_store)


def project_schedule(schedule: dict[str, Any]) -> dict[str, Any]:
    execution = schedule.get("execution") if isinstance(schedule.get("execution"), dict) else {}
    return {
        "scheduleId": str(schedule.get("scheduleId") or ""),
        "assistantAgentId": str(schedule.get("assistantAgentId") or ""),
        "symbols": [str(item) for item in schedule.get("symbols", [])],
        "periodDays": int(schedule.get("periodDays") or 0),
        "depth": str(schedule.get("depth") or ""),
        "execution": {
            "kind": str(execution.get("kind") or ""),
            "scheduledAt": execution.get("scheduledAt"),
            "timeOfDay": execution.get("timeOfDay"),
            "timezone": "Asia/Shanghai",
        },
        "researchDate": schedule.get("researchDate"),
        "enabled": bool(schedule.get("enabled")),
        "createdAt": str(schedule.get("createdAt") or ""),
        "updatedAt": str(schedule.get("updatedAt") or ""),
        "nextRunAt": schedule.get("nextRunAt"),
        "lastBatchId": schedule.get("lastBatchId"),
        "lastTriggeredAt": schedule.get("lastTriggeredAt"),
    }


def project_batch(batch: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for raw in batch.get("items", []) if isinstance(batch.get("items"), list) else []:
        if not isinstance(raw, dict):
            continue
        refs = [
            {
                "role": str(ref.get("role") or ""),
                "sessionId": str(ref.get("sessionId") or ""),
                "turnId": str(ref.get("turnId") or ""),
            }
            for ref in raw.get("turnRefs", [])
            if isinstance(ref, dict)
        ]
        items.append(
            {
                "symbol": str(raw.get("symbol") or ""),
                "status": str(raw.get("status") or "queued"),
                "runId": raw.get("runId"),
                "startedAt": raw.get("startedAt"),
                "completedAt": raw.get("completedAt"),
                "terminalReason": raw.get("terminalReason"),
                "turnRefs": refs,
            }
        )
    return {
        "batchId": str(batch.get("batchId") or ""),
        "scheduleId": batch.get("scheduleId"),
        "assistantAgentId": str(batch.get("assistantAgentId") or ""),
        "status": str(batch.get("status") or "queued"),
        "triggeredAt": str(batch.get("triggeredAt") or ""),
        "updatedAt": str(batch.get("updatedAt") or ""),
        "researchDate": str(batch.get("researchDate") or ""),
        "periodDays": int(batch.get("periodDays") or 0),
        "depth": str(batch.get("depth") or ""),
        "symbols": [str(item) for item in batch.get("symbols", [])],
        "terminalReason": batch.get("terminalReason"),
        "items": items,
    }


def _require_financial_owner(assistant_agent_id: str) -> None:
    normalized = str(assistant_agent_id or "").strip()
    if not normalized:
        raise FinancialJobNotFoundError("金融助手不存在")
    financial_team_service.get_financial_team(normalized)


def _request_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _find_idempotent_schedule(
    state: dict[str, Any], *, key_hash: str, input_hash: str
) -> dict[str, Any] | None:
    for schedule in state["schedules"].values():
        marker = schedule.get("_createIdempotency")
        if not isinstance(marker, dict) or marker.get("keyHash") != key_hash:
            continue
        if marker.get("inputHash") != input_hash:
            raise FinancialJobConflictError("同一创建请求键不能用于不同的研究参数")
        return schedule
    return None


def _task_store(task_store: Any | None = None) -> Any:
    return task_store or runtime_task_registry.default_store()


def _batch_task_id(batch_id: str) -> str:
    return f"{TASK_ID_PREFIX}{canonical_batch_id(batch_id)}"


def _load_batch_state(
    assistant_agent_id: str, batch_id: str, *, task_store: Any | None = None
) -> dict[str, Any]:
    try:
        normalized_id = canonical_batch_id(batch_id)
    except FinancialJobValidationError as exc:
        raise FinancialJobNotFoundError("研究批次不存在") from exc
    state = _task_store(task_store).load_state(_batch_task_id(normalized_id))
    if not _is_our_batch(state, assistant_agent_id):
        raise FinancialJobNotFoundError("研究批次不存在")
    if not isinstance(state.get("financialResearchBatch"), dict):
        raise FinancialJobNotFoundError("研究批次不存在")
    return state


def _is_our_batch(state: Any, assistant_agent_id: str) -> bool:
    if not isinstance(state, dict):
        return False
    batch = state.get("financialResearchBatch")
    return (
        str(state.get("coordinationOwner") or "") == TASK_OWNER
        and str(state.get("kind") or "") == runtime_task_registry.KIND_RESEARCH_TASK
        and str(state.get("financialResearchAssistantAgentId") or "")
        == assistant_agent_id
        and isinstance(batch, dict)
        and str(batch.get("assistantAgentId") or "") == assistant_agent_id
    )


__all__ = [
    "MAX_BATCHES_PER_LIST",
    "TASK_ID_PREFIX",
    "TASK_LABEL",
    "TASK_OWNER",
    "create_financial_research_schedule",
    "get_financial_research_batch",
    "list_financial_research_batches",
    "list_financial_research_schedules",
    "project_batch",
    "project_schedule",
    "retry_financial_research_batch",
    "stop_financial_research_batch",
    "update_financial_research_schedule",
]


def _record_event(event_code: str, *, assistant_agent_id: str, outcome: str, schedule_id: str = "") -> None:
    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "finance",
            "jobs",
            event_code,
            message=event_code,
            outcome=outcome,
            lifecycle=True,
            fields={
                "assistantAgentId": str(assistant_agent_id)[:160],
                "scheduleId": str(schedule_id)[:160],
                "outcome": str(outcome)[:40],
            },
        )
    except Exception:  # noqa: BLE001 - diagnostics never block the user action
        return
