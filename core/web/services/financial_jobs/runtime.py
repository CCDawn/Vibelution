"""Lifecycle-owned scheduler and serial batch runner for finance jobs."""

from __future__ import annotations

import copy
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from core.web.services import (
    financial_assistant_service,
    financial_team_service,
    runtime_task_registry,
    session_service,
)
from core.web.services.financial_team import runs as financial_runs

from . import service
from .contract import (
    due_occurrence,
    iso_beijing,
    occurrence_batch_id,
    occurrence_research_date,
    parse_now,
    schedule_next_run,
)
from .errors import FinancialJobConflictError, FinancialJobNotFoundError
from .store import FinancialResearchJobStore, default_store

PRIMARY_ROLES = ("market", "fundamental", "news")
RUNNER_LEASE_SECONDS = 45.0
POLL_INTERVAL_SECONDS = 1.0
MAX_BATCHES_PER_TICK = 6
MAX_STOP_WAIT_SECONDS = 15 * 60
_ERROR_LOG_COOLDOWN_SECONDS = 60.0
_MAX_ERROR_LOG_KEYS = 128
_ERROR_LOG_LOCK = threading.Lock()
_ERROR_LOGGED_AT: dict[str, float] = {}
_LOGGER = logging.getLogger(__name__)


def batch_task_id(batch_id: str) -> str:
    normalized = service._batch_task_id(batch_id)
    return normalized


def ensure_occurrence_batch(
    schedule: dict[str, Any],
    occurrence: dict[str, Any],
    *,
    store: FinancialResearchJobStore | None = None,
    task_store: Any | None = None,
) -> dict[str, Any]:
    assistant_agent_id = str(schedule.get("assistantAgentId") or "").strip()
    batch_id = str(occurrence.get("batchId") or "").strip()
    if not assistant_agent_id or not batch_id:
        raise FinancialJobConflictError("研究计划批次标识不完整")
    identifier = batch_task_id(batch_id)
    tasks = task_store or runtime_task_registry.default_store()
    triggered_at = str(occurrence.get("triggeredAt") or "").strip()
    if not triggered_at:
        raise FinancialJobConflictError("研究计划触发时间缺失")
    batch = {
        "batchId": batch_id,
        "scheduleId": str(schedule.get("scheduleId") or ""),
        "assistantAgentId": assistant_agent_id,
        "status": "queued",
        "triggeredAt": triggered_at,
        "updatedAt": triggered_at,
        "researchDate": str(occurrence.get("researchDate") or ""),
        "periodDays": int(schedule.get("periodDays") or 0),
        "depth": str(schedule.get("depth") or ""),
        "symbols": [str(item) for item in schedule.get("symbols", [])],
        "terminalReason": None,
        "items": [
            {
                "symbol": str(symbol),
                "status": "queued",
                "runId": None,
                "startedAt": None,
                "completedAt": None,
                "terminalReason": None,
                "turnRefs": [],
            }
            for symbol in schedule.get("symbols", [])
        ],
    }
    snapshot = runtime_task_registry.new_snapshot(
        kind=runtime_task_registry.KIND_RESEARCH_TASK,
        task_id=identifier,
        status="queued",
        label=service.TASK_LABEL,
        backgrounding_disabled=True,
        branch_generation=0,
    )
    snapshot.update(
        {
            "coordinationOwner": service.TASK_OWNER,
            "financialResearchAssistantAgentId": assistant_agent_id,
            "financialResearchBatchId": batch_id,
            "financialResearchBatch": batch,
            "financialResearchAttemptCounts": {
                str(symbol): 0 for symbol in schedule.get("symbols", [])
            },
        }
    )
    state, _created = tasks.register_task_if_absent(snapshot, branch_generation=0)
    if not _is_owned_batch_state(state, assistant_agent_id, batch_id):
        raise FinancialJobConflictError("批次标识已被其他任务占用")
    batch = state.get("financialResearchBatch")
    _mark_occurrence_materialized(
        assistant_agent_id,
        str(schedule.get("scheduleId") or ""),
        batch_id,
        store=store or default_store(),
    )
    return service.project_batch(batch if isinstance(batch, dict) else {})


def request_batch_stop(
    assistant_agent_id: str,
    batch_id: str,
    *,
    task_store: Any | None = None,
) -> dict[str, Any]:
    tasks = task_store or runtime_task_registry.default_store()
    state = service._load_batch_state(assistant_agent_id, batch_id, task_store=tasks)
    identifier = str(state.get("taskId") or "")
    batch = state["financialResearchBatch"]
    if _terminal_batch_status(str(batch.get("status") or "")):
        return service.project_batch(batch)
    requested = tasks.request_stop(identifier, "user")
    if not requested:
        latest = tasks.load_state(identifier)
        latest_batch = latest.get("financialResearchBatch") if latest else None
        if isinstance(latest_batch, dict):
            return service.project_batch(latest_batch)
        raise FinancialJobNotFoundError("研究批次不存在")

    def _mark(state_now: dict[str, Any]) -> dict[str, Any]:
        current = state_now.get("financialResearchBatch")
        if isinstance(current, dict) and not _terminal_batch_status(
            str(current.get("status") or "")
        ):
            current["status"] = "stop_requested"
            current["updatedAt"] = iso_beijing(datetime.now(timezone.utc))
        return state_now

    latest = tasks.update_task(identifier, _mark) or requested
    latest_batch = latest.get("financialResearchBatch") or batch
    _request_exact_batch_turns(assistant_agent_id, latest_batch, task_store=tasks)
    _record_event(
        "financial_jobs.batch.stop_requested",
        assistant_agent_id=assistant_agent_id,
        batch_id=batch_id,
        status=str(latest_batch.get("status") or "stop_requested"),
        reason="user_requested",
    )
    return service.project_batch(latest_batch)


def retry_batch(
    assistant_agent_id: str,
    batch_id: str,
    *,
    task_store: Any | None = None,
) -> dict[str, Any]:
    tasks = task_store or runtime_task_registry.default_store()
    state = service._load_batch_state(assistant_agent_id, batch_id, task_store=tasks)
    batch = state["financialResearchBatch"]
    if str(batch.get("status") or "") not in {"partial", "failed", "stopped"}:
        raise FinancialJobConflictError("当前批次没有可安全重试的未完成股票")
    retryable = [
        item
        for item in batch.get("items", [])
        if isinstance(item, dict)
        and str(item.get("status") or "") in {"failed", "cancelled", "skipped"}
    ]
    if not retryable:
        raise FinancialJobConflictError("当前批次没有可安全重试的未完成股票")
    for item in retryable:
        run_id = str(item.get("runId") or "").strip()
        if run_id:
            run = _load_private_financial_team_run(assistant_agent_id, run_id)
            if not _run_safe_for_retry(assistant_agent_id, run):
                raise FinancialJobConflictError(
                    "该股票仍有运行中的 Turn 或未知提交，系统不会重复发送"
                )

    def _retry(state_now: dict[str, Any]) -> dict[str, Any]:
        current_batch = state_now.get("financialResearchBatch")
        if not isinstance(current_batch, dict) or str(
            current_batch.get("status") or ""
        ) not in {"partial", "failed", "stopped"}:
            raise FinancialJobConflictError("批次状态已变化，请刷新后重试")
        current_attempts = state_now.get("financialResearchAttemptCounts")
        attempts = current_attempts if isinstance(current_attempts, dict) else {}
        for item in current_batch.get("items", []):
            if not isinstance(item, dict) or str(item.get("status") or "") not in {
                "failed",
                "cancelled",
                "skipped",
            }:
                continue
            symbol = str(item.get("symbol") or "")
            attempts[symbol] = int(attempts.get(symbol) or 0) + 1
            item.update(
                {
                    "status": "queued",
                    "runId": None,
                    "startedAt": None,
                    "completedAt": None,
                    "terminalReason": None,
                    "turnRefs": [],
                }
            )
        state_now["financialResearchAttemptCounts"] = attempts
        current_batch["status"] = "queued"
        current_batch["terminalReason"] = None
        current_batch["updatedAt"] = _now_iso()
        state_now["status"] = "queued"
        state_now["completedAt"] = ""
        state_now["stopInitiator"] = None
        state_now["stopRequestedAt"] = ""
        state_now["terminalReason"] = ""
        state_now["updatedAt"] = current_batch["updatedAt"]
        return state_now

    updated = tasks.update_task(str(state.get("taskId") or ""), _retry)
    if not updated:
        raise FinancialJobNotFoundError("研究批次不存在")
    _record_event(
        "financial_jobs.batch.retried",
        assistant_agent_id=assistant_agent_id,
        batch_id=batch_id,
        status="queued",
        reason="safe_items_only",
    )
    return service.project_batch(updated["financialResearchBatch"])


class FinancialResearchJobsWorker:
    """One lifecycle owner for due schedules and active serial batches."""

    def __init__(
        self,
        *,
        store: FinancialResearchJobStore | None = None,
        task_store: Any | None = None,
        assistant_loader: Callable[[], list[str]] | None = None,
        now_provider: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
        max_batches_per_tick: int = MAX_BATCHES_PER_TICK,
        worker_id: str | None = None,
    ) -> None:
        self._store = store or default_store()
        self._tasks = task_store or runtime_task_registry.default_store()
        self._assistant_loader = assistant_loader or _financial_assistant_ids
        self._now_provider = now_provider
        self._poll_interval_seconds = max(0.05, min(float(poll_interval_seconds), 30.0))
        self._max_batches_per_tick = max(1, min(int(max_batches_per_tick), 32))
        self._worker_id = worker_id or str(uuid4())
        self._held_leases: set[tuple[str, str]] = set()
        self._assistant_cache: tuple[float, list[str]] = (float("-inf"), [])
        self._next_report_check_at = float("-inf")

    def _check_report_outcomes(self, *, should_stop: Callable[[], bool]) -> None:
        """Reuse the managed lifecycle, with a separate bounded report owner."""
        now = parse_now(self._now_provider()).timestamp()
        if should_stop() or now < self._next_report_check_at:
            return
        self._next_report_check_at = now + 60
        from core.web.services.financial_report.validation import process_due_for_agent
        remaining = 2
        for agent_id in self._assistant_ids(now):
            if should_stop() or remaining <= 0:
                break
            try:
                remaining -= process_due_for_agent(agent_id, max_checks=remaining, stop_requested=should_stop)
            except Exception as exc:  # noqa: BLE001 - isolate unavailable owner data
                _log_scheduler_error("report-outcome-check", exc)

    def process_pending_once(
        self, *, stop_requested: Callable[[], bool] | None = None
    ) -> int:
        should_stop = stop_requested or (lambda: False)
        if should_stop():
            return 0
        now = parse_now(self._now_provider())
        try:
            self._trigger_due_schedules(now=now, should_stop=should_stop)
        except Exception as exc:  # noqa: BLE001 - an isolated schedule failure must not stop batch work
            _log_scheduler_error("schedule-scan", exc)
        if should_stop():
            return 0
        try:
            states = sorted(
                self._tasks.active_task_states(),
                key=lambda item: str(item.get("createdAt") or ""),
            )
        except Exception as exc:  # noqa: BLE001 - a registry read failure is retried next tick
            _log_scheduler_error("active-task-scan", exc)
            return 0
        processed = 0
        for state in states:
            if should_stop() or processed >= self._max_batches_per_tick:
                break
            if not _is_owned_batch_state(state):
                continue
            assistant_agent_id = str(
                state.get("financialResearchAssistantAgentId") or ""
            )
            batch_id = str(state.get("financialResearchBatchId") or "")
            if not assistant_agent_id or not batch_id:
                continue
            try:
                lease = self._store.acquire_runner_lease(
                    assistant_agent_id,
                    batch_id=batch_id,
                    worker_id=self._worker_id,
                    now_epoch=now.timestamp(),
                    lease_seconds=RUNNER_LEASE_SECONDS,
                )
            except Exception as exc:  # noqa: BLE001 - isolate owner-specific lease failures
                _log_scheduler_error("runner-lease", exc)
                continue
            if not lease:
                continue
            self._held_leases.add((assistant_agent_id, batch_id))
            processed += 1
            task_id = str(state.get("taskId") or "")
            try:
                latest = self._tasks.load_state(task_id) or state
                self._process_batch(latest, should_stop=should_stop, now=now)
            except Exception as exc:  # noqa: BLE001 - quarantine uncertain state; never fan out to later symbols
                _log_scheduler_error("batch-process", exc)
                self._quarantine_batch(state, now=now)
            try:
                settled = self._tasks.load_state(task_id) or {}
            except Exception as exc:  # noqa: BLE001 - lease expiry permits a safe later retry
                _log_scheduler_error("batch-readback", exc)
                continue
            if runtime_task_registry.is_terminal_status(str(settled.get("status") or "")):
                self._release_lease(assistant_agent_id, batch_id)
        return processed

    def run_forever(self, *, stop_requested: Callable[[], bool]) -> None:
        try:
            while not stop_requested():
                try:
                    self.process_pending_once(stop_requested=stop_requested)
                    self._check_report_outcomes(should_stop=stop_requested)
                except Exception as exc:  # noqa: BLE001 - keep the lifecycle-owned scheduler alive
                    _log_scheduler_error("worker-tick", exc)
                remaining = self._poll_interval_seconds
                while remaining > 0 and not stop_requested():
                    interval = min(0.05, remaining)
                    time.sleep(interval)
                    remaining -= interval
        finally:
            for assistant_agent_id, batch_id in tuple(self._held_leases):
                self._release_lease(assistant_agent_id, batch_id)

    def _trigger_due_schedules(
        self, *, now: datetime, should_stop: Callable[[], bool]
    ) -> None:
        for assistant_agent_id in self._assistant_ids(now.timestamp()):
            if should_stop():
                return
            try:
                state = self._store.load(assistant_agent_id)
            except Exception as exc:  # noqa: BLE001 - one unreadable owner cannot stop other jobs
                _log_scheduler_error("owner-schedule-load", exc)
                continue
            for schedule_id, schedule in list(state["schedules"].items()):
                if should_stop():
                    return
                occurrence = schedule.get("lastOccurrence")
                if isinstance(occurrence, dict) and not bool(occurrence.get("materialized")):
                    try:
                        ensure_occurrence_batch(schedule, occurrence, store=self._store, task_store=self._tasks)
                    except Exception as exc:  # noqa: BLE001 - preserve the occurrence for the next poll
                        _log_scheduler_error("occurrence-materialize", exc)
                        continue
                if not bool(schedule.get("enabled")):
                    continue
                try:
                    due = due_occurrence(schedule, now=now)
                except Exception as exc:  # noqa: BLE001 - one corrupt schedule cannot stop other schedules
                    _log_scheduler_error("schedule-due-check", exc)
                    continue
                if due is None:
                    try:
                        expected_next = schedule_next_run(schedule, now=now)
                    except Exception as exc:  # noqa: BLE001 - one corrupt plan cannot stop the scan
                        _log_scheduler_error("schedule-next-run", exc)
                        continue
                    if expected_next and expected_next != schedule.get("nextRunAt"):
                        try:
                            self._refresh_next_run(assistant_agent_id, schedule_id, expected_next)
                        except Exception as exc:  # noqa: BLE001 - retry refresh on a later poll
                            _log_scheduler_error("schedule-refresh", exc)
                    continue
                try:
                    reserved = self._reserve_occurrence(
                        assistant_agent_id,
                        schedule_id,
                        due=due,
                        now=now,
                    )
                except Exception as exc:  # noqa: BLE001 - preserve other scheduled owners
                    _log_scheduler_error("occurrence-reserve", exc)
                    continue
                if reserved is None:
                    continue
                try:
                    latest_schedule = self._store.load(assistant_agent_id)["schedules"].get(schedule_id)
                except Exception as exc:  # noqa: BLE001 - the reserved occurrence is recovered next poll
                    _log_scheduler_error("reserved-schedule-readback", exc)
                    continue
                if isinstance(latest_schedule, dict):
                    try:
                        ensure_occurrence_batch(
                            latest_schedule, reserved, store=self._store, task_store=self._tasks
                        )
                    except Exception as exc:  # noqa: BLE001 - recover from the stored occurrence next poll
                        _log_scheduler_error("occurrence-recovery", exc)
                        continue

    def _reserve_occurrence(
        self,
        assistant_agent_id: str,
        schedule_id: str,
        *,
        due: datetime,
        now: datetime,
    ) -> dict[str, Any] | None:
        occurrence: dict[str, Any] | None = None

        def _mutate(state: dict[str, Any]) -> None:
            nonlocal occurrence
            schedule = state["schedules"].get(schedule_id)
            if not isinstance(schedule, dict) or not schedule.get("enabled"):
                return
            refreshed_due = due_occurrence(schedule, now=now)
            if refreshed_due is None or refreshed_due != due:
                return
            triggered_at = iso_beijing(now)
            batch_id = occurrence_batch_id(schedule_id, due)
            occurrence = {
                "batchId": batch_id,
                "scheduledAt": due.isoformat(timespec="seconds"),
                "triggeredAt": triggered_at,
                "researchDate": occurrence_research_date(
                    schedule, scheduled_at=due, triggered_at=now
                ),
                "materialized": False,
            }
            schedule["lastOccurrence"] = occurrence
            schedule["lastBatchId"] = batch_id
            schedule["lastTriggeredAt"] = triggered_at
            if str((schedule.get("execution") or {}).get("kind") or "") == "once":
                schedule["enabled"] = False
                schedule["nextRunAt"] = None
            else:
                schedule["nextRunAt"] = schedule_next_run(schedule, now=now)
            schedule["updatedAt"] = triggered_at

        self._store.update(assistant_agent_id, _mutate)
        return occurrence

    def _refresh_next_run(
        self, assistant_agent_id: str, schedule_id: str, next_run: str
    ) -> None:
        def _mutate(state: dict[str, Any]) -> None:
            schedule = state["schedules"].get(schedule_id)
            if isinstance(schedule, dict) and schedule.get("enabled"):
                schedule["nextRunAt"] = next_run
                schedule["updatedAt"] = _now_iso()

        self._store.update(assistant_agent_id, _mutate)

    def _process_batch(
        self,
        state: dict[str, Any],
        *,
        should_stop: Callable[[], bool],
        now: datetime,
    ) -> None:
        task_id = str(state.get("taskId") or "")
        batch = state.get("financialResearchBatch")
        if not task_id or not isinstance(batch, dict):
            return
        if _terminal_batch_status(str(batch.get("status") or "")):
            return
        if _stop_was_requested(state):
            self._settle_stop(state, now=now)
            return
        items = batch.get("items") if isinstance(batch.get("items"), list) else []
        blocked_item = next(
            (
                item
                for item in items
                if isinstance(item, dict)
                and str(item.get("status") or "") == "blocked"
            ),
            None,
        )
        if blocked_item is not None:
            self._finish_existing_terminal_item(task_id, batch, blocked_item)
            return
        current_item = next(
            (
                item
                for item in items
                if isinstance(item, dict)
                and str(item.get("status") or "")
                in {"queued", "preparing", "submitting", "running"}
            ),
            None,
        )
        if current_item is None:
            statuses = {
                str(item.get("status") or "")
                for item in items
                if isinstance(item, dict)
            }
            completed_count = sum(
                1
                for item in items
                if isinstance(item, dict)
                and str(item.get("status") or "") == "completed"
            )
            has_failures = bool(statuses & {"failed", "cancelled", "skipped"})
            if has_failures:
                final_status = "partial" if completed_count else "failed"
                reason = (
                    "部分股票完成，部分研究未完成"
                    if completed_count
                    else "所有股票研究均未完成"
                )
            else:
                final_status, reason = "completed", ""
            self._finish_batch(
                task_id,
                batch,
                status=final_status,
                generic_status="completed" if final_status == "partial" else final_status,
                reason=reason,
            )
            return
        self._advance_item(
            state,
            current_item,
            should_stop=should_stop,
            now=now,
        )

    def _advance_item(
        self,
        state: dict[str, Any],
        item: dict[str, Any],
        *,
        should_stop: Callable[[], bool],
        now: datetime,
    ) -> None:
        task_id = str(state.get("taskId") or "")
        batch = copy.deepcopy(state["financialResearchBatch"])
        assistant_agent_id = str(batch.get("assistantAgentId") or "")
        batch_id = str(batch.get("batchId") or "")
        symbol = str(item.get("symbol") or "")
        current = next(
            (row for row in batch["items"] if row.get("symbol") == symbol), item
        )
        latest_state = self._tasks.load_state(task_id) or state
        if _stop_was_requested(latest_state):
            self._settle_stop(latest_state, now=now)
            return
        if should_stop():
            return
        current["status"] = "preparing"
        current["startedAt"] = current.get("startedAt") or iso_beijing(now)
        batch["status"] = "running"
        batch["updatedAt"] = iso_beijing(now)
        state = self._save_batch(task_id, batch, runtime_status="running") or state

        run_id = str(current.get("runId") or "").strip()
        attempt_counts = state.get("financialResearchAttemptCounts")
        attempt = int((attempt_counts or {}).get(symbol) or 0) if isinstance(attempt_counts, dict) else 0
        try:
            if not run_id:
                run = financial_team_service.create_financial_team_run(
                    assistant_agent_id,
                    symbol=symbol,
                    period_days=int(batch["periodDays"]),
                    research_date=str(batch["researchDate"]),
                    depth=str(batch["depth"]),
                    idempotency_key=f"financial-job-{batch_id}-{symbol}-{attempt}",
                )
                run_id = str(run.get("runId") or "").strip()
                if not run_id:
                    self._block_item(task_id, batch, current, "研究记录没有返回有效标识", now=now)
                    return
                current["runId"] = run_id
                current["status"] = "submitting"
                run = _load_private_financial_team_run(assistant_agent_id, run_id)
                _sync_turn_refs(current, run)
                batch["updatedAt"] = _now_iso()
                state = self._save_batch(task_id, batch, runtime_status="running") or state

            latest_state = self._tasks.load_state(task_id) or state
            if _stop_was_requested(latest_state):
                self._request_exact_run_turns(assistant_agent_id, run_id)
                self._settle_stop(latest_state, now=now)
                return
            if should_stop():
                return

            for role in PRIMARY_ROLES:
                latest_state = self._tasks.load_state(task_id) or state
                if _stop_was_requested(latest_state):
                    self._request_exact_run_turns(assistant_agent_id, run_id)
                    self._settle_stop(latest_state, now=now)
                    return
                if should_stop():
                    return
                try:
                    run = financial_team_service.submit_financial_team_primary_role(
                        assistant_agent_id, run_id, role
                    )
                    if str(run.get("runId") or "") != run_id:
                        raise FinancialJobConflictError(
                            "分析提交返回了不同的研究标识"
                        )
                    run = _load_private_financial_team_run(assistant_agent_id, run_id)
                except session_service.SessionBusyError:
                    self._wait_for_session(task_id, batch, current, now=now)
                    return
                except (
                    session_service.SessionNotFoundError,
                    session_service.SessionValidationError,
                ):
                    try:
                        run = _load_private_financial_team_run(
                            assistant_agent_id, run_id
                        )
                    except Exception as exc:  # noqa: BLE001 - unreadable state cannot authorize a retry
                        _log_scheduler_error("failed-submit-state-readback", exc)
                        self._block_item(
                            task_id,
                            batch,
                            current,
                            "提交状态无法核验，系统未重发；请核对原生会话",
                            now=now,
                        )
                        return
                    if _run_safe_for_retry(assistant_agent_id, run):
                        self._fail_item(
                            task_id,
                            batch,
                            current,
                            "分析成员暂不可提交，检查配置后可安全重试",
                            now=now,
                        )
                    else:
                        self._block_item(
                            task_id,
                            batch,
                            current,
                            "部分分析 Turn 已启动，停止后续股票；请核对当前研究",
                            now=now,
                        )
                    return
                except Exception:  # noqa: BLE001 - unknown submit outcome must never resend
                    self._block_item(
                        task_id,
                        batch,
                        current,
                        "分析提交结果未知，系统未自动重发；请核对原生会话",
                        now=now,
                    )
                    return
                _sync_turn_refs(current, run)
                current["status"] = "submitting"
                batch["updatedAt"] = _now_iso()
                state = self._save_batch(task_id, batch, runtime_status="running") or state
                latest_state = self._tasks.load_state(task_id) or state
                if _stop_was_requested(latest_state):
                    self._request_exact_run_turns(assistant_agent_id, run_id)
                    self._settle_stop(latest_state, now=now)
                    return
                if should_stop():
                    return

            run = _load_private_financial_team_run(assistant_agent_id, run_id)
            _sync_turn_refs(current, run)
            coordination_status = str(run.get("coordinationStatus") or "")
            if coordination_status == "completed":
                current["status"] = "completed"
                current["completedAt"] = _now_iso()
                current["terminalReason"] = None
                batch["updatedAt"] = current["completedAt"]
                self._save_batch(task_id, batch, runtime_status="running")
                _record_event(
                    "financial_jobs.batch.item_completed",
                    assistant_agent_id=assistant_agent_id,
                    batch_id=batch_id,
                    symbol=symbol,
                    status="completed",
                    reason="native_team_run_completed",
                )
                return
            if coordination_status == "blocked":
                reason = str(run.get("coordinationError") or "").strip()
                if _run_safe_for_retry(assistant_agent_id, run):
                    self._fail_item(
                        task_id,
                        batch,
                        current,
                        reason or "分析未完成，核对后可安全重试",
                        now=now,
                    )
                else:
                    self._block_item(
                        task_id,
                        batch,
                        current,
                        "分析状态需要核对，系统未重发也未启动后续股票",
                        now=now,
                    )
                return
            current["status"] = "running"
            current["terminalReason"] = None
            batch["status"] = "running"
            batch["updatedAt"] = _now_iso()
            self._save_batch(task_id, batch, runtime_status="running")
        except Exception as exc:  # noqa: BLE001 - fail closed without exposing native content
            _log_scheduler_error("item-advance", exc)
            self._block_item(
                task_id,
                batch,
                current,
                "研究状态无法安全核验，系统已暂停后续股票",
                now=now,
            )

    def _wait_for_session(
        self,
        task_id: str,
        batch: dict[str, Any],
        item: dict[str, Any],
        *,
        now: datetime,
    ) -> None:
        item["status"] = "queued"
        item["terminalReason"] = None
        batch["status"] = "queued"
        batch["updatedAt"] = iso_beijing(now)
        self._save_batch(task_id, batch, runtime_status="queued")

    def _fail_item(
        self,
        task_id: str,
        batch: dict[str, Any],
        item: dict[str, Any],
        reason: str,
        *,
        now: datetime,
    ) -> None:
        item["status"] = "failed"
        item["completedAt"] = iso_beijing(now)
        item["terminalReason"] = str(reason or "研究未完成")[:240]
        batch["status"] = "running"
        batch["updatedAt"] = iso_beijing(now)
        self._save_batch(task_id, batch, runtime_status="running")
        _record_event(
            "financial_jobs.batch.item_failed",
            assistant_agent_id=str(batch.get("assistantAgentId") or ""),
            batch_id=str(batch.get("batchId") or ""),
            symbol=str(item.get("symbol") or ""),
            status="failed",
            reason="verified_run_failure",
        )

    def _block_item(
        self,
        task_id: str,
        batch: dict[str, Any],
        item: dict[str, Any],
        reason: str,
        *,
        now: datetime,
    ) -> None:
        item["status"] = "blocked"
        item["completedAt"] = iso_beijing(now)
        item["terminalReason"] = str(reason or "研究状态需要核对")[:240]
        self._finish_existing_terminal_item(task_id, batch, item)

    def _finish_existing_terminal_item(
        self, task_id: str, batch: dict[str, Any], item: dict[str, Any]
    ) -> None:
        items = batch.get("items", [])
        current_symbol = str(item.get("symbol") or "")
        current_index = next(
            (index for index, row in enumerate(items) if row.get("symbol") == current_symbol),
            -1,
        )
        for later in items[current_index + 1 :]:
            if str(later.get("status") or "") in {"queued", "preparing", "submitting"}:
                later["status"] = "skipped"
                later["completedAt"] = _now_iso()
                later["terminalReason"] = "前一只股票未完成，未启动后续研究"
        if str(item.get("status") or "") == "blocked":
            final_status, reason, generic_status = (
                "blocked",
                "当前研究状态需要核对，未继续后续股票",
                "blocked",
            )
        elif str(item.get("status") or "") == "cancelled":
            final_status, reason, generic_status = (
                "stopped",
                "批次已停止，未启动的股票已跳过",
                "stopped",
            )
        elif str(item.get("status") or "") == "skipped":
            completed = any(str(row.get("status") or "") == "completed" for row in items)
            final_status, reason, generic_status = (
                ("partial", "部分股票完成，剩余研究未启动", "completed")
                if completed
                else ("failed", "批次未完成，未启动的股票已跳过", "failed")
            )
        else:
            completed = any(str(row.get("status") or "") == "completed" for row in items)
            final_status, reason, generic_status = (
                ("partial", "部分股票完成，剩余研究未继续", "completed")
                if completed
                else ("failed", "研究未完成，未继续后续股票", "failed")
            )
        batch["status"] = final_status
        batch["terminalReason"] = reason
        batch["updatedAt"] = _now_iso()
        self._finish_batch(
            task_id,
            batch,
            status=final_status,
            generic_status=generic_status,
            reason=reason,
        )

    def _settle_stop(self, state: dict[str, Any], *, now: datetime) -> None:
        task_id = str(state.get("taskId") or "")
        batch = copy.deepcopy(state.get("financialResearchBatch") or {})
        assistant_agent_id = str(batch.get("assistantAgentId") or "")
        items = batch.get("items") if isinstance(batch.get("items"), list) else []
        active_item = next(
            (
                row
                for row in items
                if isinstance(row, dict)
                and (
                    str(row.get("status") or "")
                    in {"preparing", "submitting", "running"}
                    or (
                        str(row.get("status") or "") == "queued"
                        and bool(str(row.get("runId") or "").strip())
                    )
                )
            ),
            None,
        )
        if active_item and active_item.get("runId"):
            coordinator_pending = self._request_exact_run_turns(
                assistant_agent_id, str(active_item.get("runId") or "")
            )
            try:
                run = _load_private_financial_team_run(
                    assistant_agent_id, str(active_item.get("runId") or "")
                )
            except Exception:  # noqa: BLE001 - an unreadable run keeps stop verification fail-closed
                run = None
            if (
                coordinator_pending
                or not isinstance(run, dict)
                or not _run_turns_settled(run)
            ):
                requested_at = str(state.get("stopRequestedAt") or "")
                if _stop_request_timed_out(requested_at, now):
                    self._block_item(
                        task_id,
                        batch,
                        active_item,
                        "停止状态暂不可核验，请先核对原生会话",
                        now=now,
                    )
                else:
                    batch["status"] = "stop_requested"
                    batch["updatedAt"] = iso_beijing(now)
                    self._save_batch(task_id, batch, runtime_status="running")
                return
        for item in items:
            status = str(item.get("status") or "")
            if status == "completed":
                continue
            if item is active_item or status in {"queued", "preparing", "submitting", "running"}:
                item["status"] = "cancelled" if item is active_item else "skipped"
                item["completedAt"] = iso_beijing(now)
                item["terminalReason"] = (
                    "用户请求停止本批次"
                    if item is active_item
                    else "批次已停止，未启动该股票"
                )
        batch["status"] = "stopped"
        batch["terminalReason"] = "批次已停止，未启动的股票已跳过"
        batch["updatedAt"] = iso_beijing(now)
        self._finish_batch(
            task_id,
            batch,
            status="stopped",
            generic_status="stopped",
            reason=batch["terminalReason"],
        )

    def _finish_batch(
        self,
        task_id: str,
        batch: dict[str, Any],
        *,
        status: str,
        generic_status: str,
        reason: str,
    ) -> None:
        now = _now_iso()
        batch["status"] = status
        batch["terminalReason"] = reason or None
        batch["updatedAt"] = now

        def _mutate(state: dict[str, Any]) -> dict[str, Any]:
            current = state.get("financialResearchBatch")
            if _stop_was_requested(state) and status not in {"stopped", "blocked"}:
                if isinstance(current, dict):
                    current["status"] = "stop_requested"
                state["status"] = "running"
                return state
            state["financialResearchBatch"] = copy.deepcopy(batch)
            state["status"] = generic_status
            state["completedAt"] = now
            state["updatedAt"] = now
            state["terminalReason"] = reason or ""
            return state

        self._tasks.update_task(task_id, _mutate)

    def _save_batch(
        self,
        task_id: str,
        batch: dict[str, Any],
        *,
        runtime_status: str,
    ) -> dict[str, Any] | None:
        snapshot: dict[str, Any] | None = None

        def _mutate(state: dict[str, Any]) -> dict[str, Any]:
            nonlocal snapshot
            current = state.get("financialResearchBatch")
            outgoing = copy.deepcopy(batch)
            if _stop_was_requested(state) and not _terminal_batch_status(
                str(outgoing.get("status") or "")
            ):
                outgoing["status"] = "stop_requested"
                state["status"] = "running"
            else:
                state["status"] = runtime_status
            outgoing["updatedAt"] = _now_iso()
            # The stop route changes only the status and stop intention. Keep
            # it sticky if it landed after this worker's read.
            if isinstance(current, dict) and str(current.get("status") or "") == "stop_requested" and not _terminal_batch_status(str(outgoing.get("status") or "")):
                outgoing["status"] = "stop_requested"
            state["financialResearchBatch"] = outgoing
            state["updatedAt"] = outgoing["updatedAt"]
            snapshot = copy.deepcopy(state)
            return state

        self._tasks.update_task(task_id, _mutate)
        return snapshot

    def _request_exact_run_turns(self, assistant_agent_id: str, run_id: str) -> bool:
        coordinator_pending = _request_financial_team_coordinator_stop(
            assistant_agent_id, run_id, task_store=self._tasks
        )
        _request_exact_batch_turns(
            assistant_agent_id,
            {"items": [{"runId": run_id}]},
            task_store=self._tasks,
            request_coordinator=False,
        )
        return coordinator_pending

    def _assistant_ids(self, now_epoch: float) -> list[str]:
        cached_at, cached_ids = self._assistant_cache
        if now_epoch - cached_at < 15.0:
            return list(cached_ids)
        try:
            ids = [
                str(agent_id or "").strip()
                for agent_id in self._assistant_loader()
                if str(agent_id or "").strip()
            ]
        except Exception:  # noqa: BLE001 - discovery failure does not stop batch processing
            ids = []
        unique = list(dict.fromkeys(ids))
        self._assistant_cache = (now_epoch, unique)
        return unique

    def _release_lease(self, assistant_agent_id: str, batch_id: str) -> None:
        try:
            self._store.release_runner_lease(
                assistant_agent_id,
                batch_id=batch_id,
                worker_id=self._worker_id,
            )
        finally:
            self._held_leases.discard((assistant_agent_id, batch_id))

    def _quarantine_batch(self, state: dict[str, Any], *, now: datetime) -> None:
        task_id = str(state.get("taskId") or "")
        if not task_id:
            return
        try:
            latest = self._tasks.load_state(task_id) or state
            batch = copy.deepcopy(latest.get("financialResearchBatch") or {})
            if not isinstance(batch, dict) or _terminal_batch_status(str(batch.get("status") or "")):
                return
            active = next(
                (
                    item
                    for item in batch.get("items", [])
                    if isinstance(item, dict)
                    and (
                        str(item.get("status") or "")
                        in {"preparing", "submitting", "running"}
                        or (
                            str(item.get("status") or "") == "queued"
                            and bool(str(item.get("runId") or "").strip())
                        )
                    )
                ),
                None,
            )
            if active is not None:
                active["status"] = "blocked"
                active["completedAt"] = iso_beijing(now)
                active["terminalReason"] = "研究状态无法安全核验，自动后续提交已暂停"
            batch["status"] = "blocked"
            batch["terminalReason"] = "研究状态无法安全核验，自动后续提交已暂停"
            batch["updatedAt"] = iso_beijing(now)
            self._finish_batch(
                task_id,
                batch,
                status="blocked",
                generic_status="blocked",
                reason=batch["terminalReason"],
            )
        except Exception as exc:  # noqa: BLE001 - preserve the original failure and lease expiry
            _log_scheduler_error("batch-quarantine", exc)


def run_forever(*, stop_requested: Callable[[], bool]) -> None:
    """StartupJobGroup entry point for recurring jobs and queued batches."""

    FinancialResearchJobsWorker().run_forever(stop_requested=stop_requested)


def _mark_occurrence_materialized(
    assistant_agent_id: str,
    schedule_id: str,
    batch_id: str,
    *,
    store: FinancialResearchJobStore,
) -> None:
    if not schedule_id:
        return

    def _mutate(state: dict[str, Any]) -> None:
        schedule = state["schedules"].get(schedule_id)
        occurrence = schedule.get("lastOccurrence") if isinstance(schedule, dict) else None
        if isinstance(occurrence, dict) and str(occurrence.get("batchId") or "") == batch_id:
            occurrence["materialized"] = True

    store.update(assistant_agent_id, _mutate)


def _request_financial_team_coordinator_stop(
    assistant_agent_id: str,
    run_id: str,
    *,
    task_store: Any,
) -> bool:
    """Persist a stop on this run's coordinator task and report if it is pending.

    A colliding task ID is never stopped. Identity/read failures are treated as
    pending so the batch cannot claim a clean stop while the coordinator may
    still submit debate or synthesis turns.
    """

    from core.web.services.financial_team import coordinator

    try:
        coordinator_id = coordinator.coordination_task_id(run_id)
        state = task_store.load_state(coordinator_id)
    except Exception:  # noqa: BLE001 - identity/read failures must remain pending
        return True
    if not state:
        return False
    if (
        str(state.get("taskId") or "") != coordinator_id
        or str(state.get("coordinationOwner") or "") != coordinator.TASK_OWNER
        or str(state.get("kind") or "") != runtime_task_registry.KIND_RESEARCH_TASK
        or str(state.get("financialTeamAssistantAgentId") or "") != assistant_agent_id
        or str(state.get("financialTeamRunId") or "") != run_id
    ):
        return True
    if runtime_task_registry.is_terminal_status(str(state.get("status") or "")):
        return False
    try:
        request_stop = getattr(task_store, "request_stop", None)
        if not callable(request_stop):
            return True
        request_stop(coordinator_id, "user")
        latest = task_store.load_state(coordinator_id)
    except Exception:  # noqa: BLE001 - an unverified stop must remain pending
        return True
    if (
        not latest
        or str(latest.get("taskId") or "") != coordinator_id
        or str(latest.get("coordinationOwner") or "") != coordinator.TASK_OWNER
        or str(latest.get("kind") or "") != runtime_task_registry.KIND_RESEARCH_TASK
        or str(latest.get("financialTeamAssistantAgentId") or "") != assistant_agent_id
        or str(latest.get("financialTeamRunId") or "") != run_id
    ):
        return True
    return not runtime_task_registry.is_terminal_status(str(latest.get("status") or ""))


def _request_exact_batch_turns(
    assistant_agent_id: str,
    batch: dict[str, Any],
    *,
    task_store: Any | None = None,
    request_coordinator: bool = True,
) -> None:
    tasks = task_store or runtime_task_registry.default_store()
    run_ids = {
        str(item.get("runId") or "").strip()
        for item in batch.get("items", [])
        if isinstance(item, dict) and str(item.get("runId") or "").strip()
    }
    for run_id in run_ids:
        if request_coordinator:
            _request_financial_team_coordinator_stop(
                assistant_agent_id, run_id, task_store=tasks
            )
        try:
            current = _load_private_financial_team_run(
                assistant_agent_id, run_id
            )
        except Exception as exc:  # noqa: BLE001 - isolate one run from the remaining stop requests
            _log_scheduler_error("stop-run-readback", exc)
            continue
        refs = [
            ref
            for ref in _all_run_refs(current)
            if str(ref.get("submissionState") or "") == "accepted"
        ]
        for ref in refs:
            session_id = str(ref.get("sessionId") or "").strip()
            turn_id = str(ref.get("turnId") or "").strip()
            if not session_id or not turn_id:
                continue
            try:
                session_service.request_stop_session_turn(
                    session_id,
                    expected_turn_id=turn_id,
                    fast_ack=True,
                    cascade=False,
                )
            except Exception as exc:  # noqa: BLE001 - exact identity mismatch must not target another turn
                _log_scheduler_error("stop-exact-turn", exc)
                continue


def _load_private_financial_team_run(
    assistant_agent_id: str, run_id: str
) -> dict[str, Any]:
    """Read validated internal submission state for one exact owned run.

    The public team-run projection deliberately removes ``submissionState``.
    Batch recovery and stop decisions therefore read the authoritative private
    run record through the owner-checked path and loader in ``financial_team.runs``.
    """

    owner_id = str(assistant_agent_id or "")
    path = financial_runs._run_path(owner_id, str(run_id or "").strip())
    run = financial_runs._load_run(path, owner_id)
    if str(run.get("runId") or "") != path.stem:
        raise financial_runs.FinancialTeamRunError(
            "股票研究记录标识与存储路径不匹配，未使用该记录"
        )
    return run


def _all_run_refs(run: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    analysts = run.get("analysts") if isinstance(run.get("analysts"), dict) else {}
    for role in (*PRIMARY_ROLES, "bull", "bear"):
        raw = analysts.get(role)
        if isinstance(raw, dict):
            refs.append({"role": role, **raw})
    synthesis = run.get("synthesis")
    if isinstance(synthesis, dict):
        refs.append({"role": "synthesis", **synthesis})
    return refs


def _sync_turn_refs(item: dict[str, Any], run: dict[str, Any]) -> None:
    item["turnRefs"] = [
        {
            "role": str(ref.get("role") or ""),
            "sessionId": str(ref.get("sessionId") or ""),
            "turnId": str(ref.get("turnId") or ""),
        }
        for ref in _all_run_refs(run)
        if str(ref.get("submissionState") or "") == "accepted"
        if str(ref.get("sessionId") or "").strip()
        and str(ref.get("turnId") or "").strip()
    ]


def _run_safe_for_retry(assistant_agent_id: str, run: dict[str, Any]) -> bool:
    if str(run.get("assistantAgentId") or "") != assistant_agent_id:
        return False
    if str(run.get("coordinationStatus") or "") in {"waiting", "running"}:
        return False
    for ref in _all_run_refs(run):
        turn_id = str(ref.get("turnId") or "").strip()
        session_id = str(ref.get("sessionId") or "").strip()
        submission_state = str(ref.get("submissionState") or "reserved").strip()
        if not turn_id:
            if submission_state in {"submitting", "accepted"}:
                return False
            continue
        if not session_id:
            return False
        try:
            snapshot = session_service.get_session_turn_completion_snapshot(
                session_id, turn_id
            )
        except Exception:  # noqa: BLE001 - unreadable completion evidence must block retry
            return False
        if (
            not isinstance(snapshot, dict)
            or str(snapshot.get("sessionId") or "") != session_id
            or str(snapshot.get("turnId") or "") != turn_id
            or not bool(snapshot.get("terminal"))
        ):
            return False
    return True


def _run_turns_settled(run: dict[str, Any]) -> bool:
    for ref in _all_run_refs(run):
        turn_id = str(ref.get("turnId") or "").strip()
        if not turn_id:
            if str(ref.get("submissionState") or "reserved") in {"submitting", "accepted"}:
                return False
            continue
        session_id = str(ref.get("sessionId") or "").strip()
        if not session_id:
            return False
        try:
            snapshot = session_service.get_session_turn_completion_snapshot(
                session_id, turn_id
            )
        except Exception:  # noqa: BLE001 - unreadable completion evidence must keep stop pending
            return False
        if (
            not isinstance(snapshot, dict)
            or str(snapshot.get("sessionId") or "") != session_id
            or str(snapshot.get("turnId") or "") != turn_id
            or not bool(snapshot.get("terminal"))
        ):
            return False
    return True


def _stop_request_timed_out(raw: str, now: datetime) -> bool:
    if not raw:
        return False
    try:
        started = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    if started.tzinfo is None:
        started = started.astimezone()
    return (now - started.astimezone(now.tzinfo)).total_seconds() >= MAX_STOP_WAIT_SECONDS


def _is_owned_batch_state(state: Any, assistant_agent_id: str = "", batch_id: str = "") -> bool:
    if not isinstance(state, dict):
        return False
    batch = state.get("financialResearchBatch")
    return (
        str(state.get("coordinationOwner") or "") == service.TASK_OWNER
        and str(state.get("kind") or "") == runtime_task_registry.KIND_RESEARCH_TASK
        and isinstance(batch, dict)
        and str(state.get("financialResearchAssistantAgentId") or "")
        == str(batch.get("assistantAgentId") or "")
        and (not assistant_agent_id or str(batch.get("assistantAgentId") or "") == assistant_agent_id)
        and (not batch_id or str(batch.get("batchId") or "") == batch_id)
    )


def _is_terminal_item_state(state: str) -> bool:
    return state in {"completed", "failed", "blocked", "cancelled", "skipped"}


def _terminal_batch_status(status: str) -> bool:
    return status in {"completed", "partial", "failed", "stopped", "blocked"}


def _log_scheduler_error(scope: str, exc: Exception) -> None:
    error_type = type(exc).__name__[:80]
    key = f"{str(scope or '')[:80]}:{error_type}"
    now = time.monotonic()
    with _ERROR_LOG_LOCK:
        last_logged = _ERROR_LOGGED_AT.get(key)
        if last_logged is not None and now - last_logged < _ERROR_LOG_COOLDOWN_SECONDS:
            return
        if len(_ERROR_LOGGED_AT) >= _MAX_ERROR_LOG_KEYS:
            oldest_key = min(_ERROR_LOGGED_AT, key=_ERROR_LOGGED_AT.get)
            _ERROR_LOGGED_AT.pop(oldest_key, None)
        _ERROR_LOGGED_AT[key] = now
    _LOGGER.warning(
        "Financial research scheduler isolated %s failure (%s)",
        str(scope or "unknown")[:80],
        error_type,
    )


def _stop_was_requested(state: dict[str, Any]) -> bool:
    return str(state.get("stopInitiator") or "") in runtime_task_registry.STOP_INITIATORS


def _now_iso() -> str:
    return iso_beijing(parse_now())


def _record_event(
    event_code: str,
    *,
    assistant_agent_id: str,
    batch_id: str,
    status: str,
    reason: str,
    symbol: str = "",
) -> None:
    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "finance",
            "jobs",
            event_code,
            message=event_code,
            outcome=status,
            lifecycle=True,
            fields={
                "assistantAgentId": str(assistant_agent_id)[:160],
                "batchId": str(batch_id)[:160],
                "symbol": str(symbol)[:16],
                "status": str(status)[:40],
                "reason": str(reason)[:120],
            },
        )
    except Exception:  # noqa: BLE001 - diagnostics never block the worker
        return


def _financial_assistant_ids() -> list[str]:
    return [
        str(agent.get("agentId") or "").strip()
        for agent in financial_assistant_service._agents()
        if str(agent.get("status") or "active") == "active"
        and str(agent.get("agentId") or "").strip()
    ]


__all__ = [
    "FinancialResearchJobsWorker",
    "batch_task_id",
    "ensure_occurrence_batch",
    "request_batch_stop",
    "retry_batch",
    "run_forever",
]
