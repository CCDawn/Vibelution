"""Per-Agent scheduling for web chat turns and external Agent work."""

from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable


RecordSchedulerEvent = Callable[[dict[str, Any], str, str, dict[str, Any] | None], None]
SessionTurnCallback = Callable[[dict[str, Any]], None]
SessionTurnPredicate = Callable[[str, str], bool]


@dataclass
class ReleasedSchedulerTurn:
    context: dict[str, Any] | None
    external: bool
    dropped_contexts: list[dict[str, Any]]


class SessionTurnScheduler:
    """Serialize work by Agent while keeping queue policy behind one interface."""

    def __init__(
        self,
        *,
        agent_key_for_context: Callable[[dict[str, Any]], str],
        now: Callable[[], float],
        record_event: RecordSchedulerEvent,
        mark_queued: Callable[[dict[str, Any], int], None],
        mark_dequeued: SessionTurnCallback,
        is_session_running: Callable[[str], bool],
        is_session_turn_current: SessionTurnPredicate,
    ) -> None:
        self._agent_key_for_context = agent_key_for_context
        self._now = now
        self._record_event = record_event
        self._mark_queued = mark_queued
        self._mark_dequeued = mark_dequeued
        self._is_session_running = is_session_running
        self._is_session_turn_current = is_session_turn_current
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._active_turn_ids: dict[str, str] = {}
        self._queues: dict[str, deque[dict[str, Any]]] = {}

    def schedule(self, context: dict[str, Any], *, submit: SessionTurnCallback, release: SessionTurnCallback) -> None:
        job_context = dict(context)
        scheduled_at = self._now()
        job_context["_scheduler_scheduled_at_monotonic"] = scheduled_at
        context["_scheduler_scheduled_at_monotonic"] = scheduled_at
        agent_key = self._agent_key_for_context(job_context)
        job_context["_scheduler_agent_key"] = agent_key
        context["_scheduler_agent_key"] = agent_key
        turn_id = str(job_context.get("turn_id") or "").strip()
        queued_position = 0
        should_start = False
        with self._lock:
            if self._active_turn_ids.get(agent_key):
                queue_bucket = self._queues.setdefault(agent_key, deque())
                queue_bucket.append(job_context)
                queued_position = len(queue_bucket)
            else:
                self._active_turn_ids[agent_key] = turn_id
                should_start = True

        if not should_start:
            self._mark_queued(job_context, queued_position)
            return

        job_context["_scheduler_started_at_monotonic"] = self._now()
        self._record_event(job_context, "started", "running", None)
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
            "_scheduler_external": True,
            "_scheduler_ready_event": ready_event,
            "_scheduler_cancelled": False,
        }
        owner_name = str(owner or "external").strip() or "external"
        self._record_event(context, "external_waiting", "waiting", {"owner": owner_name})
        with self._condition:
            active_turn_id = str(self._active_turn_ids.get(agent_key) or "").strip()
            queued = self._queues.get(agent_key)
            if not active_turn_id and not queued:
                self._active_turn_ids[agent_key] = normalized_run_id
                acquired = True
            else:
                queue_bucket = self._queues.setdefault(agent_key, deque())
                queue_bucket.append(context)
                self._record_event(
                    context,
                    "external_queued",
                    "queued",
                    {"owner": owner_name, "queuePosition": len(queue_bucket)},
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
        self._record_event(context, "external_started", "running", {"owner": owner_name})
        try:
            yield
        finally:
            if acquired:
                self._record_event(context, "external_finished", "finished", {"owner": owner_name})
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
                            {"reason": "external_run_cancelled"},
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
        agent_key = str(context.get("_scheduler_agent_key") or self._agent_key_for_context(context)).strip()
        turn_id = str(context.get("turn_id") or "").strip()
        next_context: dict[str, Any] | None = None
        dropped_contexts: list[dict[str, Any]] = []
        with self._lock:
            if self._active_turn_ids.get(agent_key) == turn_id:
                self._active_turn_ids.pop(agent_key, None)
            queue_bucket = self._queues.get(agent_key)
            while queue_bucket:
                candidate = queue_bucket.popleft()
                candidate_session_id = str(candidate.get("session_id") or "").strip()
                candidate_turn_id = str(candidate.get("turn_id") or "").strip()
                if bool(candidate.get("_scheduler_cancelled")):
                    dropped_contexts.append(candidate)
                    continue
                if self.is_external(candidate):
                    ready_event = candidate.get("_scheduler_ready_event")
                    next_context = candidate
                    self._active_turn_ids[agent_key] = candidate_turn_id
                    if isinstance(ready_event, threading.Event):
                        ready_event.set()
                    break
                if self._is_session_running(candidate_session_id) and self._is_session_turn_current(
                    candidate_session_id, candidate_turn_id
                ):
                    next_context = candidate
                    self._active_turn_ids[agent_key] = candidate_turn_id
                    break
                dropped_contexts.append(candidate)
            if queue_bucket is not None and not queue_bucket:
                self._queues.pop(agent_key, None)
            self._condition.notify_all()

        if next_context is None:
            if dropped_contexts:
                return ReleasedSchedulerTurn(context=None, external=False, dropped_contexts=dropped_contexts)
            return None
        if self.is_external(next_context):
            return ReleasedSchedulerTurn(context=next_context, external=True, dropped_contexts=dropped_contexts)
        self._mark_dequeued(next_context)
        return ReleasedSchedulerTurn(context=next_context, external=False, dropped_contexts=dropped_contexts)

    def cancel_session_turn(self, session_id: str, turn_id: str) -> bool:
        normalized_session_id = str(session_id or "").strip()
        normalized_turn_id = str(turn_id or "").strip()
        removed = False
        with self._lock:
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
            self._active_turn_ids.clear()
            self._queues.clear()
            self._condition.notify_all()

    @staticmethod
    def is_external(context: dict[str, Any]) -> bool:
        return bool(context.get("_scheduler_external"))
