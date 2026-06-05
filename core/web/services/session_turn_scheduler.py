"""Session-aware scheduling for web chat turns and external Agent work."""

from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable


RecordSchedulerEvent = Callable[[dict[str, Any], str, str, dict[str, Any] | None], None]
SessionTurnCallback = Callable[[dict[str, Any]], None]
SessionTurnPredicate = Callable[[str, str], bool]


@dataclass
class ReleasedSchedulerTurn:
    context: dict[str, Any] | None
    external: bool
    dropped_contexts: list[dict[str, Any]]
    additional_contexts: list[dict[str, Any]] = field(default_factory=list)


class SessionTurnScheduler:
    """Serialize each session while allowing bounded same-Agent session concurrency."""

    def __init__(
        self,
        *,
        agent_key_for_context: Callable[[dict[str, Any]], str],
        session_key_for_context: Callable[[dict[str, Any]], str] | None = None,
        max_active_per_agent: int = 4,
        now: Callable[[], float],
        record_event: RecordSchedulerEvent,
        mark_queued: Callable[[dict[str, Any], int], None],
        mark_dequeued: SessionTurnCallback,
        is_session_running: Callable[[str], bool],
        is_session_turn_current: SessionTurnPredicate,
    ) -> None:
        self._agent_key_for_context = agent_key_for_context
        self._session_key_for_context = session_key_for_context or self._default_session_key_for_context
        self._max_active_per_agent = max(1, int(max_active_per_agent or 1))
        self._now = now
        self._record_event = record_event
        self._mark_queued = mark_queued
        self._mark_dequeued = mark_dequeued
        self._is_session_running = is_session_running
        self._is_session_turn_current = is_session_turn_current
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._active_turn_ids_by_session: dict[str, str] = {}
        self._active_session_keys_by_agent: dict[str, set[str]] = {}
        self._active_external_turn_ids_by_agent: dict[str, str] = {}
        self._queues: dict[str, deque[dict[str, Any]]] = {}

    def schedule(self, context: dict[str, Any], *, submit: SessionTurnCallback, release: SessionTurnCallback) -> None:
        job_context = dict(context)
        scheduled_at = self._now()
        self._annotate_context(job_context, scheduled_at=scheduled_at)
        self._copy_scheduler_annotations(job_context, context)
        queued_position = 0
        should_start = False
        with self._lock:
            queue_reason = self._chat_queue_reason_locked(job_context, respect_external_waiter=True)
            if queue_reason:
                self._set_queue_fields(job_context, queue_reason)
                queue_bucket = self._queues.setdefault(str(job_context["_scheduler_agent_key"]), deque())
                queue_bucket.append(job_context)
                queued_position = len(queue_bucket)
            else:
                self._activate_locked(job_context)
                should_start = True
                self._set_started_fields(job_context)
                self._copy_scheduler_annotations(job_context, context)

        if not should_start:
            self._copy_scheduler_annotations(job_context, context)
            self._mark_queued(job_context, queued_position)
            return

        job_context["_scheduler_started_at_monotonic"] = self._now()
        self._record_event(job_context, "started", "running", self._event_fields(job_context))
        try:
            submit(job_context)
        except Exception:
            release(job_context)
            raise

    @contextmanager
    def reserve_external(
        self,
        *,
        agent_id: str,
        run_id: str,
        session_id: str = "",
        owner: str = "external",
        wait_timeout_seconds: float | None = None,
        release: SessionTurnCallback,
    ):
        normalized_agent_id = str(agent_id or "").strip()
        normalized_run_id = str(run_id or "").strip()
        if not normalized_agent_id or not normalized_run_id:
            yield
            return

        agent_key = f"agent:{normalized_agent_id}"
        acquired = False
        ready_event = threading.Event()
        timeout_seconds = float(wait_timeout_seconds or 0.0)
        deadline = time.monotonic() + max(0.1, timeout_seconds) if timeout_seconds > 0 else None
        context = {
            "session_id": str(session_id or "").strip(),
            "turn_id": normalized_run_id,
            "agent_id": normalized_agent_id,
            "_scheduler_agent_key": agent_key,
            "_scheduler_session_key": f"external:{normalized_run_id}",
            "_scheduler_external": True,
            "_scheduler_ready_event": ready_event,
            "_scheduler_cancelled": False,
        }
        owner_name = str(owner or "external").strip() or "external"
        self._record_event(context, "external_waiting", "waiting", {"owner": owner_name})
        with self._condition:
            if self._can_start_external_locked(context) and not self._queues.get(agent_key):
                self._activate_locked(context)
                self._set_started_fields(context)
                acquired = True
            else:
                self._set_queue_fields(context, "agent_busy_for_external")
                queue_bucket = self._queues.setdefault(agent_key, deque())
                queue_bucket.append(context)
                self._record_event(
                    context,
                    "external_queued",
                    "queued",
                    {
                        "owner": owner_name,
                        "queuePosition": len(queue_bucket),
                        **self._event_fields(context),
                    },
                )
        while not acquired:
            if bool(context.get("_scheduler_cancelled")):
                raise RuntimeError(f"Agent execution slot reservation was cancelled: {normalized_agent_id}")
            if ready_event.is_set():
                if bool(context.get("_scheduler_cancelled")):
                    raise RuntimeError(f"Agent execution slot reservation was cancelled: {normalized_agent_id}")
                acquired = True
                break
            if deadline is None:
                ready_event.wait(timeout=0.25)
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.cancel_queued_context(agent_key, normalized_run_id)
                    raise TimeoutError(f"Timed out waiting for agent execution slot: {normalized_agent_id}")
                ready_event.wait(timeout=min(0.25, remaining))
            if ready_event.is_set():
                if bool(context.get("_scheduler_cancelled")):
                    raise RuntimeError(f"Agent execution slot reservation was cancelled: {normalized_agent_id}")
                acquired = True
        self._record_event(context, "external_started", "running", {"owner": owner_name, **self._event_fields(context)})
        try:
            yield
        finally:
            if acquired:
                self._record_event(context, "external_finished", "finished", {"owner": owner_name, **self._event_fields(context)})
                release(context)

    def cancel_queued_context(self, agent_key: str, turn_id: str) -> bool:
        normalized_agent_key = str(agent_key or "").strip()
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_agent_key or not normalized_turn_id:
            return False
        removed = False
        with self._condition:
            queue_bucket = self._queues.get(normalized_agent_key)
            if not queue_bucket:
                return False
            kept: deque[dict[str, Any]] = deque()
            while queue_bucket:
                queued_context = queue_bucket.popleft()
                if str(queued_context.get("turn_id") or "").strip() == normalized_turn_id:
                    removed = True
                    queued_context["_scheduler_cancelled"] = True
                    ready_event = queued_context.get("_scheduler_ready_event")
                    if isinstance(ready_event, threading.Event):
                        ready_event.set()
                    continue
                kept.append(queued_context)
            if kept:
                self._queues[normalized_agent_key] = kept
            else:
                self._queues.pop(normalized_agent_key, None)
            if removed:
                self._condition.notify_all()
        return removed

    def cancel_external_reservation(self, run_id: str) -> bool:
        normalized_run_id = str(run_id or "").strip()
        if not normalized_run_id:
            return False
        removed = False
        with self._condition:
            for agent_key in list(self._queues):
                queue_bucket = self._queues.get(agent_key)
                if not queue_bucket:
                    self._queues.pop(agent_key, None)
                    continue
                kept: deque[dict[str, Any]] = deque()
                while queue_bucket:
                    queued_context = queue_bucket.popleft()
                    queued_turn_id = str(queued_context.get("turn_id") or "").strip()
                    if self.is_external(queued_context) and queued_turn_id == normalized_run_id:
                        removed = True
                        queued_context["_scheduler_cancelled"] = True
                        ready_event = queued_context.get("_scheduler_ready_event")
                        if isinstance(ready_event, threading.Event):
                            ready_event.set()
                        self._record_event(
                            queued_context,
                            "external_cancelled",
                            "cancelled",
                            {"reason": "external_run_cancelled", **self._event_fields(queued_context)},
                        )
                        continue
                    kept.append(queued_context)
                if kept:
                    self._queues[agent_key] = kept
                else:
                    self._queues.pop(agent_key, None)
            if removed:
                self._condition.notify_all()
        return removed

    def release(self, context: dict[str, Any]) -> ReleasedSchedulerTurn | None:
        self._ensure_context_keys(context)
        agent_key = str(context.get("_scheduler_agent_key") or self._agent_key_for_context(context)).strip()
        session_key = str(context.get("_scheduler_session_key") or self._session_key_for_context(context)).strip()
        turn_id = str(context.get("turn_id") or "").strip()
        next_context: dict[str, Any] | None = None
        additional_contexts: list[dict[str, Any]] = []
        dropped_contexts: list[dict[str, Any]] = []
        with self._condition:
            self._deactivate_locked(agent_key, session_key, turn_id, external=self.is_external(context))
            queue_bucket = self._queues.get(agent_key)
            if queue_bucket:
                remaining: deque[dict[str, Any]] = deque()
                external_waiter_blocked = False
                while queue_bucket:
                    candidate = queue_bucket.popleft()
                    self._ensure_context_keys(candidate)
                    if bool(candidate.get("_scheduler_cancelled")):
                        dropped_contexts.append(candidate)
                        continue
                    if self.is_external(candidate):
                        if (
                            not external_waiter_blocked
                            and not remaining
                            and not next_context
                            and not additional_contexts
                            and self._can_start_external_locked(candidate)
                        ):
                            next_context = candidate
                            self._activate_locked(candidate)
                            self._set_started_fields(candidate)
                            ready_event = candidate.get("_scheduler_ready_event")
                            if isinstance(ready_event, threading.Event):
                                ready_event.set()
                            break
                        remaining.append(candidate)
                        external_waiter_blocked = True
                        break

                    candidate_session_id = str(candidate.get("session_id") or "").strip()
                    candidate_turn_id = str(candidate.get("turn_id") or "").strip()
                    if not (
                        self._is_session_running(candidate_session_id)
                        and self._is_session_turn_current(candidate_session_id, candidate_turn_id)
                    ):
                        dropped_contexts.append(candidate)
                        continue
                    if not external_waiter_blocked and not self._chat_queue_reason_locked(
                        candidate,
                        respect_external_waiter=False,
                    ):
                        self._activate_locked(candidate)
                        self._set_started_fields(candidate)
                        if next_context is None:
                            next_context = candidate
                        else:
                            additional_contexts.append(candidate)
                        continue
                    remaining.append(candidate)

                while queue_bucket:
                    remaining.append(queue_bucket.popleft())
                if remaining:
                    self._queues[agent_key] = remaining
                else:
                    self._queues.pop(agent_key, None)
            self._condition.notify_all()

        if next_context is None:
            if dropped_contexts:
                return ReleasedSchedulerTurn(context=None, external=False, dropped_contexts=dropped_contexts)
            return None
        if self.is_external(next_context):
            return ReleasedSchedulerTurn(context=next_context, external=True, dropped_contexts=dropped_contexts)
        self._mark_dequeued(next_context)
        for additional_context in additional_contexts:
            self._mark_dequeued(additional_context)
        return ReleasedSchedulerTurn(
            context=next_context,
            external=False,
            dropped_contexts=dropped_contexts,
            additional_contexts=additional_contexts,
        )

    def cancel_session_turn(self, session_id: str, turn_id: str) -> bool:
        normalized_session_id = str(session_id or "").strip()
        normalized_turn_id = str(turn_id or "").strip()
        removed = False
        with self._condition:
            for agent_key in list(self._queues):
                queue_bucket = self._queues.get(agent_key)
                if not queue_bucket:
                    self._queues.pop(agent_key, None)
                    continue
                kept: deque[dict[str, Any]] = deque()
                while queue_bucket:
                    queued_context = queue_bucket.popleft()
                    queued_session_id = str(queued_context.get("session_id") or "").strip()
                    queued_turn_id = str(queued_context.get("turn_id") or "").strip()
                    if queued_session_id == normalized_session_id and (
                        not normalized_turn_id or queued_turn_id == normalized_turn_id
                    ):
                        removed = True
                        queued_context["_scheduler_cancelled"] = True
                        continue
                    kept.append(queued_context)
                if kept:
                    self._queues[agent_key] = kept
                else:
                    self._queues.pop(agent_key, None)
            if removed:
                self._condition.notify_all()
        return removed

    def clear(self) -> None:
        """Reset in-memory scheduler queues for isolated tests or runtime shutdown cleanup."""

        with self._condition:
            self._active_turn_ids_by_session.clear()
            self._active_session_keys_by_agent.clear()
            self._active_external_turn_ids_by_agent.clear()
            self._queues.clear()
            self._condition.notify_all()

    @staticmethod
    def is_external(context: dict[str, Any]) -> bool:
        return bool(context.get("_scheduler_external"))

    @staticmethod
    def _default_session_key_for_context(context: dict[str, Any]) -> str:
        session_id = str(context.get("session_id") or "").strip()
        if session_id:
            return f"session:{session_id}"
        turn_id = str(context.get("turn_id") or "").strip()
        return f"turn:{turn_id or 'unknown'}"

    def _annotate_context(self, context: dict[str, Any], *, scheduled_at: float | None = None) -> None:
        if scheduled_at is not None:
            context["_scheduler_scheduled_at_monotonic"] = scheduled_at
        context["_scheduler_agent_key"] = str(
            context.get("_scheduler_agent_key") or self._agent_key_for_context(context)
        ).strip()
        context["_scheduler_session_key"] = str(
            context.get("_scheduler_session_key") or self._session_key_for_context(context)
        ).strip()
        context["_scheduler_agent_max_active"] = self._max_active_per_agent

    def _ensure_context_keys(self, context: dict[str, Any]) -> None:
        if not str(context.get("_scheduler_agent_key") or "").strip():
            context["_scheduler_agent_key"] = str(self._agent_key_for_context(context)).strip()
        if not str(context.get("_scheduler_session_key") or "").strip():
            context["_scheduler_session_key"] = str(self._session_key_for_context(context)).strip()
        context["_scheduler_agent_max_active"] = self._max_active_per_agent

    @staticmethod
    def _copy_scheduler_annotations(source: dict[str, Any], target: dict[str, Any]) -> None:
        for key, value in source.items():
            if str(key).startswith("_scheduler_"):
                target[key] = value

    def _chat_queue_reason_locked(self, context: dict[str, Any], *, respect_external_waiter: bool) -> str:
        agent_key = str(context.get("_scheduler_agent_key") or "").strip()
        session_key = str(context.get("_scheduler_session_key") or "").strip()
        if self._active_external_turn_ids_by_agent.get(agent_key):
            return "agent_external_active"
        if respect_external_waiter and self._agent_has_external_waiter_locked(agent_key):
            return "agent_external_waiting"
        if self._active_turn_ids_by_session.get(session_key):
            return "session_active"
        if self._agent_active_count_locked(agent_key) >= self._max_active_per_agent:
            return "agent_concurrency_limit"
        return ""

    def _can_start_external_locked(self, context: dict[str, Any]) -> bool:
        agent_key = str(context.get("_scheduler_agent_key") or "").strip()
        if self._active_external_turn_ids_by_agent.get(agent_key):
            return False
        return self._agent_active_count_locked(agent_key) == 0

    def _activate_locked(self, context: dict[str, Any]) -> None:
        agent_key = str(context.get("_scheduler_agent_key") or "").strip()
        turn_id = str(context.get("turn_id") or "").strip()
        if self.is_external(context):
            self._active_external_turn_ids_by_agent[agent_key] = turn_id
            return
        session_key = str(context.get("_scheduler_session_key") or "").strip()
        self._active_turn_ids_by_session[session_key] = turn_id
        self._active_session_keys_by_agent.setdefault(agent_key, set()).add(session_key)

    def _deactivate_locked(self, agent_key: str, session_key: str, turn_id: str, *, external: bool) -> None:
        if external:
            if self._active_external_turn_ids_by_agent.get(agent_key) == turn_id:
                self._active_external_turn_ids_by_agent.pop(agent_key, None)
            return
        if self._active_turn_ids_by_session.get(session_key) == turn_id:
            self._active_turn_ids_by_session.pop(session_key, None)
        active_sessions = self._active_session_keys_by_agent.get(agent_key)
        if active_sessions is not None:
            active_sessions.discard(session_key)
            if not active_sessions:
                self._active_session_keys_by_agent.pop(agent_key, None)

    def _agent_active_count_locked(self, agent_key: str) -> int:
        return len(self._active_session_keys_by_agent.get(agent_key) or set())

    def _agent_has_external_waiter_locked(self, agent_key: str) -> bool:
        queue_bucket = self._queues.get(agent_key)
        return any(self.is_external(item) for item in queue_bucket or [])

    def _set_queue_fields(self, context: dict[str, Any], reason: str) -> None:
        agent_key = str(context.get("_scheduler_agent_key") or "").strip()
        context["_scheduler_queue_reason"] = str(reason or "").strip()
        context["_scheduler_agent_active_count"] = self._agent_active_count_locked(agent_key)
        context["_scheduler_agent_max_active"] = self._max_active_per_agent

    def _set_started_fields(self, context: dict[str, Any]) -> None:
        agent_key = str(context.get("_scheduler_agent_key") or "").strip()
        context["_scheduler_queue_reason"] = ""
        context["_scheduler_agent_active_count"] = self._agent_active_count_locked(agent_key)
        context["_scheduler_agent_max_active"] = self._max_active_per_agent

    @staticmethod
    def _event_fields(context: dict[str, Any]) -> dict[str, Any]:
        return {
            "schedulerSessionKey": str(context.get("_scheduler_session_key") or "").strip(),
            "queueReason": str(context.get("_scheduler_queue_reason") or "").strip(),
            "agentActiveCount": int(context.get("_scheduler_agent_active_count") or 0),
            "agentMaxActive": int(context.get("_scheduler_agent_max_active") or 0),
        }
